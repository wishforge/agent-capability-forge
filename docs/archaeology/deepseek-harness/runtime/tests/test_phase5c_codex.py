"""Phase 5-C: minimal Codex rollout adapter tests.

FIXTURE TEST: driven by deterministic rollout JSONL fixtures written to the
pinned openai/codex RolloutItem schema (commit
279b93242cfef379e65da97e87e44b83c5934fd7). This is not a real Codex E2E;
real tool execution happens in the Unified ToolRuntime.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(RUNTIME))

from backend.adapters.codex import (  # noqa: E402
    ADAPTER,
    BACKEND_SPECIFIC,
    EXACT,
    LOSSY,
    CodexAdapter,
)
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    EXECUTION_ATTEMPT_END,
    EXECUTION_ATTEMPT_START,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
)
from initiator import InitiatorContext, require_initiator  # noqa: E402
from model_adapter import (  # noqa: E402
    ModelChunk,
    ModelFinal,
    ModelRequestError,
    ModelToolCallEvent,
)
from recovery import rebuild_session, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from surface import SurfaceProjection  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import ENDED, Session  # noqa: E402

GOLDEN_EVENTS = [
    USER_MESSAGE,
    TURN_START,
    STEP_START,
    AGENT_REQUEST,
    EXECUTION_ATTEMPT_START,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    TOOL_CALL,
    TOOL_RESULT,
    EXECUTION_ATTEMPT_END,
    STEP_END,
    STEP_START,
    AGENT_REQUEST,
    EXECUTION_ATTEMPT_START,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    TOOL_CALL,
    TOOL_RESULT,
    EXECUTION_ATTEMPT_END,
    STEP_END,
    STEP_START,
    AGENT_REQUEST,
    EXECUTION_ATTEMPT_START,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    EXECUTION_ATTEMPT_END,
    STEP_END,
    TURN_END,
]


def event_types(store: EventStore) -> list[str]:
    return [e.event_type for e in store.events()]


def inventory_runtime() -> ToolRuntime:
    runtime = ToolRuntime()
    runtime.register(
        ToolRegistration(
            "inventory.lookup",
            lambda a, c, s: "stock:5",
            owner="ERP",
        ),
    )
    runtime.register(
        ToolRegistration(
            "procurement.suggest",
            lambda a, c, s: "suggestion:created",
            owner="ERP",
        ),
    )
    return runtime


class Phase5CCodexTests(unittest.IsolatedAsyncioTestCase):
    def test_codex_backend_instantiates(self) -> None:
        adapter = CodexAdapter(FIXTURES / "codex_golden.jsonl")

        self.assertEqual(adapter.mapping_metadata.backend, "codex")
        self.assertEqual(adapter.mapping_metadata.mapping_quality, ADAPTER)
        self.assertEqual(adapter.mapping_metadata.source_event_type, "session_meta")
        self.assertEqual(
            adapter.mapping_metadata.raw_event_ref["line"],
            1,
        )
        self.assertEqual(len(adapter.segments), 3)
        first = adapter.request(0)
        self.assertIsInstance(first[0], ModelChunk)
        self.assertIsInstance(first[1], ModelFinal)
        self.assertIsInstance(first[2], ModelToolCallEvent)

        # Semantic core files must not mention/import codex at all.
        for name in ("runtime.py", "model_adapter.py"):
            source = (RUNTIME / name).read_text()
            self.assertNotIn("codex", source.lower())
            self.assertNotIn("CodexAdapter", source)

    async def test_codex_basic_turn(self) -> None:
        runtime = inventory_runtime()
        session = Session("s-basic")

        turn = await AgentRuntime(
            session,
            runtime,
            CodexAdapter(FIXTURES / "codex_golden.jsonl"),
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 3)
        self.assertEqual({s.status for s in turn.steps}, {ENDED})
        final = next(
            e
            for e in session.store.events()
            if e.event_type == ASSISTANT_MESSAGE
            and e.payload["content"].startswith("已完成")
        )
        self.assertEqual(
            final.payload["content"],
            "已完成：库存不足，采购建议已生成（10 件）。",
        )

    async def test_codex_single_tool(self) -> None:
        session = Session("s-single")
        adapter = CodexAdapter(FIXTURES / "codex_golden.jsonl")

        turn = await AgentRuntime(
            session,
            inventory_runtime(),
            adapter,
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        self.assertEqual(len(turn.steps[0].tool_calls), 1)
        call = turn.steps[0].tool_calls[0]
        self.assertEqual(call.call_id, "call-1")
        self.assertEqual(call.name, "inventory.lookup")
        self.assertEqual(call.arguments, {"sku": "A"})
        meta = adapter.call_metadata["call-1"]
        self.assertEqual(meta.mapping_quality, EXACT)
        self.assertEqual(meta.raw_event_ref["line"], 7)
        self.assertEqual(meta.source_event_type, "custom_tool_call_output")

    async def test_codex_tool_result(self) -> None:
        session = Session("s-result")

        await AgentRuntime(
            session,
            inventory_runtime(),
            CodexAdapter(FIXTURES / "codex_golden.jsonl"),
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        call_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_CALL
        )
        result_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_RESULT
        )
        self.assertEqual(result_ev.payload["content"], "stock:5")
        self.assertFalse(result_ev.payload["is_error"])
        self.assertEqual(
            result_ev.payload["tool_call_id"],
            call_ev.payload["call_id"],
        )
        self.assertEqual(result_ev.source_event_seqs, (call_ev.seq,))

    async def test_codex_multi_step(self) -> None:
        session = Session("s-multi")

        turn = await AgentRuntime(
            session,
            inventory_runtime(),
            CodexAdapter(FIXTURES / "codex_golden.jsonl"),
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        self.assertEqual(len(turn.steps), 3)
        self.assertEqual(
            [len(s.tool_calls) for s in turn.steps],
            [1, 1, 0],
        )
        self.assertEqual(
            [s.tool_calls[0].name for s in turn.steps[:2]],
            ["inventory.lookup", "procurement.suggest"],
        )
        self.assertNotEqual(turn.steps[0].step_id, turn.steps[1].step_id)

    async def test_codex_event_mapping(self) -> None:
        session = Session("s-events")
        adapter = CodexAdapter(FIXTURES / "codex_golden.jsonl")

        await AgentRuntime(
            session,
            inventory_runtime(),
            adapter,
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        self.assertEqual(event_types(session.store), GOLDEN_EVENTS)
        self.assertEqual(
            adapter.turn_metadata.source_event_type,
            "task_started",
        )
        self.assertEqual(adapter.turn_metadata.mapping_quality, ADAPTER)
        self.assertEqual(
            adapter.turn_metadata.raw_event_ref["line"],
            4,
        )
        self.assertEqual(len(adapter.step_metadata), 3)
        self.assertEqual(
            [m.source_event_type for m in adapter.step_metadata],
            ["message", "message", "message"],
        )
        self.assertEqual(
            [m.raw_event_ref["line"] for m in adapter.step_metadata],
            [5, 8, 11],
        )
        self.assertEqual(
            [m.mapping_quality for m in adapter.step_metadata],
            [ADAPTER, ADAPTER, ADAPTER],
        )

    def test_codex_lossiness_visible(self) -> None:
        adapter = CodexAdapter(FIXTURES / "codex_lossy.jsonl")

        self.assertIn("STEP_BOUNDARY_PERSISTED", adapter.mapping_metadata.missing_semantics)
        self.assertIn("EXEC_FAILURE_STRUCTURED_SUCCESS", adapter.mapping_metadata.missing_semantics)
        self.assertIn("CHUNK_TO_MESSAGE_LINEAGE", adapter.mapping_metadata.missing_semantics)
        self.assertIn("CRASH_OUTCOME_NATIVE_MARKER", adapter.mapping_metadata.missing_semantics)
        self.assertIn("AMBIENT_INITIATOR", adapter.mapping_metadata.missing_semantics)
        self.assertIn("COMPACTION_RETRY_SAME_STEP", adapter.mapping_metadata.missing_semantics)
        # Unpaired Codex tool result: LOSSY, with raw ref, never guessed.
        call_meta = adapter.call_metadata["call-x"]
        self.assertEqual(call_meta.mapping_quality, LOSSY)
        self.assertEqual(call_meta.source_event_type, "custom_tool_call")
        self.assertEqual(call_meta.raw_event_ref["line"], 6)

    async def test_codex_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5c-") as td:
            path = Path(td) / "golden.jsonl"
            store = EventStore("s-persist", path=path)
            store.open()
            session = Session("s-persist")
            session.store = store
            await AgentRuntime(
                session,
                inventory_runtime(),
                CodexAdapter(FIXTURES / "codex_golden.jsonl"),
                InitiatorContext("agent-c"),
            ).run_turn("查询库存，如果不足则生成采购建议。")
            surface_a = SurfaceProjection(store).derive_messages()
            seq_count = store.last_seq()
            store.close()

            reopened = EventStore("s-persist", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                surface_a,
            )
            rebuilt = rebuild_session(reopened)
            self.assertEqual(len(rebuilt.turns), 1)
            self.assertEqual(len(rebuilt.turns[0].steps), 3)
            reopened.close()

    async def test_codex_replay(self) -> None:
        executed: list[str] = []

        async def inventory(args, ctx, signal):
            executed.append("inventory")
            return "stock:5"

        async def suggest(args, ctx, signal):
            executed.append("suggest")
            return "suggestion:created"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("inventory.lookup", inventory, owner="ERP"))
        runtime.register(ToolRegistration("procurement.suggest", suggest, owner="ERP"))

        with tempfile.TemporaryDirectory(prefix="phase5c-") as td:
            path = Path(td) / "golden.jsonl"
            store = EventStore("s-replay", path=path)
            store.open()
            session = Session("s-replay")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                CodexAdapter(FIXTURES / "codex_golden.jsonl"),
                InitiatorContext("agent-c"),
            ).run_turn("查询库存，如果不足则生成采购建议。")
            self.assertEqual(executed, ["inventory", "suggest"])
            store.close()

            reopened = EventStore("s-replay", path=path)
            reopened.open()
            history = replay(reopened)
            reopened.close()

        self.assertEqual(executed, ["inventory", "suggest"])  # no re-execution
        self.assertEqual(history.session_id, "s-replay")
        self.assertEqual(len(history.turns), 1)
        golden = history.turns[0]
        self.assertEqual(golden.end_reason, "completed")
        self.assertEqual(len(golden.steps), 3)
        self.assertEqual(
            [len(s.tool_calls) for s in golden.steps],
            [1, 1, 0],
        )
        self.assertEqual(
            golden.steps[0].tool_calls[0]["call_id"],
            "call-1",
        )
        self.assertEqual(
            golden.steps[0].tool_results[0].content,
            "stock:5",
        )
        self.assertEqual(
            golden.steps[2].assistant_messages[0]["content"],
            "已完成：库存不足，采购建议已生成（10 件）。",
        )

    async def test_codex_owner_vs_initiator(self) -> None:
        seen: list[str] = []

        async def inventory(args, ctx, signal):
            seen.append(require_initiator().agent_id)
            return "stock:5"

        async def suggest(args, ctx, signal):
            seen.append(require_initiator().agent_id)
            return "suggestion:created"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("inventory.lookup", inventory, owner="ERP"))
        runtime.register(ToolRegistration("procurement.suggest", suggest, owner="ERP"))
        adapter = CodexAdapter(FIXTURES / "codex_golden.jsonl")

        await AgentRuntime(
            Session("s-owner"),
            runtime,
            adapter,
            InitiatorContext("agent-c"),
        ).run_turn("查询库存，如果不足则生成采购建议。")

        self.assertEqual(seen, ["agent-c", "agent-c"])
        self.assertEqual(runtime.get("inventory.lookup").owner, "ERP")
        self.assertEqual(runtime.get("procurement.suggest").owner, "ERP")
        self.assertIn("AMBIENT_INITIATOR", adapter.mapping_metadata.missing_semantics)
        self.assertEqual(
            adapter.ownership_metadata.mapping_quality,
            BACKEND_SPECIFIC,
        )

    async def test_codex_error_mapping(self) -> None:
        session = Session("s-error")
        adapter = CodexAdapter(FIXTURES / "codex_error.jsonl")

        with self.assertRaises(ModelRequestError) as raised:
            await AgentRuntime(
                session,
                inventory_runtime(),
                adapter,
                InitiatorContext("agent-c"),
            ).run_turn("查询库存。")

        self.assertEqual(raised.exception.code, "MODEL_ERROR")
        self.assertIn("fatal tool failure", str(raised.exception))
        self.assertEqual(
            event_types(session.store)[-2:],
            [STEP_END, TURN_END],
        )
        self.assertEqual(
            next(
                e.payload["reason"]
                for e in session.store.events()
                if e.event_type == TURN_END
            ),
            "error",
        )
        self.assertEqual(adapter.error_metadata.mapping_quality, LOSSY)
        self.assertEqual(adapter.error_metadata.source_event_type, "error")
        self.assertEqual(adapter.error_metadata.raw_event_ref["line"], 8)
        self.assertEqual(adapter.call_metadata["call-err"].mapping_quality, EXACT)


if __name__ == "__main__":
    unittest.main()
