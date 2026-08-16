"""Phase 5-F: ExecutionAttempt + BackendEventRef + BackendMetadata extensions.

The extension types live in runtime/extensions.py and are shared by the
AgentScope and Codex adapters. The semantic core must stay backend-neutral.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

from agentscope.credential import CredentialBase  # noqa: E402
from agentscope.message import (  # noqa: E402
    TextBlock,
    ToolCallBlock,
    ToolCallState,
)
from agentscope.model import ChatModelBase, ChatResponse  # noqa: E402

from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from backend.adapters.codex import CodexAdapter  # noqa: E402
from compaction import (  # noqa: E402
    CompactionEngine,
    TokenMeter,
)
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    COMPACTION_END,
    COMPACTION_START,
    COMPACTION_SUMMARY,
    EXECUTION_ATTEMPT_END,
    EXECUTION_ATTEMPT_START,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    SessionEvent,
)
from extensions import (  # noqa: E402
    ABORTED,
    ADAPTER,
    EXACT,
    FAILED,
    LOSSY,
    RUNNING,
    SUCCEEDED,
    SYNTHETIC,
    BackendEventRef,
    BackendMetadata,
)
from initiator import InitiatorContext  # noqa: E402
from model_adapter import (  # noqa: E402
    ModelChunk,
    ModelFinal,
    ModelRequestError,
    ModelToolCall,
    ModelToolCallEvent,
)
from recovery import replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import Session  # noqa: E402


def event_types(store: EventStore) -> list[str]:
    return [e.event_type for e in store.events()]


def prior_history(store: EventStore, count: int = 6) -> None:
    for i in range(count):
        store.append(
            SessionEvent(
                0,
                USER_MESSAGE,
                store.session_id,
                payload={"content": f"user {i}: " + "x" * 80},
            ),
        )
        store.append(
            SessionEvent(
                0,
                ASSISTANT_MESSAGE,
                store.session_id,
                payload={
                    "content": f"assistant {i}: " + "x" * 80,
                    "tool_calls": [],
                },
            ),
        )


class MinimalAdapter:
    """Backend-neutral ModelAdapter with no dependency on any backend."""

    delegates_tools = False
    model_name = "minimal"

    def __init__(self, *, mapping_metadata: BackendMetadata | None = None) -> None:
        self.step_tool_results = []
        self.mapping_metadata = mapping_metadata

    async def stream(self, ctx, model_context):
        yield ModelFinal("minimal ok", ())


class UnsafeRetryAdapter:
    """Streams a tool call, lets the tool execute, then overflows."""

    delegates_tools = False
    model_name = "unsafe"

    def __init__(self) -> None:
        self.step_tool_results = []

    async def stream(self, ctx, model_context):
        yield ModelFinal(
            "calling lookup",
            (ModelToolCall("c1", "lookup", {}),),
        )
        yield ModelToolCallEvent("c1", "lookup", {})
        raise ModelRequestError(
            "CONTEXT_WINDOW_EXCEEDED",
            "overflow after tool side effect",
        )


class AbortedAdapter:
    """Streams one chunk then fails with a non-model runtime error."""

    delegates_tools = False
    model_name = "aborted"

    def __init__(self) -> None:
        self.step_tool_results = []

    async def stream(self, ctx, model_context):
        yield ModelChunk("partial")
        raise RuntimeError("backend crashed mid-stream")


class DeterministicAgentScopeModel(ChatModelBase):
    """AgentScope-compatible deterministic model (test-only)."""

    def __init__(self, script, overflow_on: int | None = None) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="det-agent",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            max_retries=0,
            retry_delay=0.0,
            context_size=1024,
        )
        self.script = list(script)
        self.overflow_on = overflow_on
        self.calls = 0

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **kwargs,
    ):
        self.calls += 1
        if self.overflow_on is not None and self.calls == self.overflow_on:
            raise RuntimeError("CONTEXT_WINDOW_EXCEEDED")
        if not self.script:
            return ChatResponse(
                content=[TextBlock(text="final answer")],
                is_last=True,
            )
        item = self.script.pop(0)
        if isinstance(item, str):
            return ChatResponse(content=[TextBlock(text=item)], is_last=True)
        text, calls = item
        blocks = [TextBlock(text=text)]
        for call_id, name, args in calls:
            blocks.append(
                ToolCallBlock(
                    id=call_id,
                    name=name,
                    input=json.dumps(args),
                    state=ToolCallState.PENDING,
                ),
            )
        return ChatResponse(content=blocks, is_last=True)


def overflow_engine(store: EventStore) -> CompactionEngine:
    return CompactionEngine(
        store,
        TokenMeter(
            context_window=100000,
            threshold_ratio=0.8,
            retain_ratio=0.16,
        ),
        max_overflow_retries=1,
    )


def attempt_events(store: EventStore) -> list[dict]:
    return [
        e.payload
        for e in store.events()
        if e.event_type in (EXECUTION_ATTEMPT_START, EXECUTION_ATTEMPT_END)
    ]


class Phase5FExecutionAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_has_attempt(self) -> None:
        session = Session("s5f-basic")
        runtime = ToolRuntime()
        agent = AgentRuntime(
            session,
            runtime,
            MinimalAdapter(),
            InitiatorContext("a"),
        )

        turn = await agent.run_turn("hi")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(agent.executions), 1)
        execution = next(iter(agent.executions.values()))
        self.assertEqual(len(execution.attempts), 1)
        attempt = execution.attempts[0]
        self.assertEqual(attempt.execution_id, turn.steps[0].step_id)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, SUCCEEDED)
        starts = [
            e for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_START
        ]
        ends = [
            e for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        ]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 1)
        self.assertEqual(
            starts[0].payload["attempt_id"],
            ends[0].payload["attempt_id"],
        )

    async def test_retry_keeps_same_execution(self) -> None:
        session = Session("s5f-same-exec")
        prior_history(session.store)
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["done"], overflow_on=1)
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        await agent.run_turn("go")

        self.assertEqual(len(agent.executions), 1)
        attempts = next(iter(agent.executions.values())).attempts
        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            {a.execution_id for a in attempts},
            {attempts[0].execution_id},
        )
        events = attempt_events(session.store)
        self.assertEqual(
            {e["execution_id"] for e in events},
            {attempts[0].execution_id},
        )

    async def test_attempt_numbers_monotonic(self) -> None:
        session = Session("s5f-monotonic")
        prior_history(session.store)
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["done"], overflow_on=1)
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        await agent.run_turn("go")

        attempts = next(iter(agent.executions.values())).attempts
        self.assertEqual(
            [a.attempt_number for a in attempts],
            [1, 2],
        )
        self.assertEqual(
            [e["attempt_number"] for e in attempt_events(session.store)],
            [1, 1, 2, 2],
        )

    async def test_retry_does_not_create_new_step(self) -> None:
        session = Session("s5f-one-step")
        prior_history(session.store)
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["done"], overflow_on=1)
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        turn = await agent.run_turn("go")

        self.assertEqual(len(turn.steps), 1)
        self.assertEqual(
            len([e for e in session.store.events() if e.event_type == STEP_START]),
            1,
        )

    async def test_compaction_retry_creates_new_attempt(self) -> None:
        session = Session("s5f-compact")
        prior_history(session.store)
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["done"], overflow_on=1)
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        await agent.run_turn("go")

        attempts = next(iter(agent.executions.values())).attempts
        self.assertEqual([a.attempt_number for a in attempts], [1, 2])
        self.assertNotEqual(attempts[0].attempt_id, attempts[1].attempt_id)
        self.assertIn(COMPACTION_START, event_types(session.store))
        self.assertIn(COMPACTION_SUMMARY, event_types(session.store))
        self.assertIn(COMPACTION_END, event_types(session.store))

    async def test_failed_attempt_then_success(self) -> None:
        session = Session("s5f-fail-then-ok")
        prior_history(session.store)
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["done"], overflow_on=1)
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        await agent.run_turn("go")

        attempts = next(iter(agent.executions.values())).attempts
        self.assertEqual(
            [a.status for a in attempts],
            [FAILED, SUCCEEDED],
        )
        ends = [
            e.payload["status"]
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        ]
        self.assertEqual(ends, [FAILED, SUCCEEDED])

    async def test_aborted_attempt(self) -> None:
        session = Session("s5f-aborted")
        agent = AgentRuntime(
            session,
            ToolRuntime(),
            AbortedAdapter(),
            InitiatorContext("a"),
        )

        with self.assertRaises(RuntimeError):
            await agent.run_turn("go")

        end = next(
            e.payload
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        )
        self.assertEqual(end["status"], ABORTED)
        self.assertEqual(end["reason"], "interrupted")
        self.assertEqual(
            next(
                e.payload["reason"]
                for e in session.store.events()
                if e.event_type == TURN_END
            ),
            "error",
        )

    async def test_golden_compaction_retry(self) -> None:
        """Golden scenario: Turn=1, Step=1, Execution=1, Attempts=2."""
        session = Session("s5f-golden")
        prior_history(session.store)
        executed: list[dict] = []

        async def lookup(args, ctx, signal):
            executed.append(dict(args))
            return "stock:5"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap"))
        model = DeterministicAgentScopeModel(
            [("calling lookup", [("c1", "lookup", {"sku": "A"})]), "done"],
            overflow_on=1,
        )
        adapter = AgentScopeModelAdapter(
            model,
            runtime,
            name="agent-a",
            max_iters=2,
        )
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        turn = await agent.run_turn("go")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(
            len([e for e in session.store.events() if e.event_type == TURN_START]),
            1,
        )
        self.assertEqual(
            len([e for e in session.store.events() if e.event_type == STEP_START]),
            1,
        )
        self.assertEqual(len(agent.executions), 1)
        attempts = next(iter(agent.executions.values())).attempts
        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            [a.status for a in attempts],
            [FAILED, SUCCEEDED],
        )
        self.assertEqual(executed, [{"sku": "A"}])
        self.assertEqual(
            next(
                e.payload["content"]
                for e in session.store.events()
                if e.event_type == ASSISTANT_MESSAGE
                and e.payload["content"] == "done"
            ),
            "done",
        )
        self.assertIn(COMPACTION_START, event_types(session.store))


class Phase5FBackendRefTests(unittest.TestCase):
    def test_backend_event_ref(self) -> None:
        ref = BackendEventRef(
            backend="codex",
            event_id="call-1",
            event_type="function_call",
            reference={"rollout_path": "/tmp/r.jsonl", "line": 12},
            quality=EXACT,
        )
        self.assertEqual(ref.backend, "codex")
        self.assertEqual(ref.event_id, "call-1")
        self.assertEqual(ref.event_type, "function_call")
        self.assertEqual(ref.reference["line"], 12)
        self.assertEqual(ref.quality, EXACT)
        self.assertEqual(
            BackendEventRef(
                backend="agentscope",
                reference={"synthetic": "seq-1"},
                quality=SYNTHETIC,
            ).quality,
            SYNTHETIC,
        )

    def test_exact_mapping_metadata(self) -> None:
        adapter = CodexAdapter(
            Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
        )
        meta = adapter.call_metadata["call-1"]
        self.assertEqual(meta.mapping_quality, EXACT)
        self.assertEqual(meta.backend_event_ref.event_id, "call-1")
        self.assertEqual(meta.backend_event_ref.event_type, "custom_tool_call_output")
        self.assertEqual(meta.raw_event_ref["line"], 7)
        self.assertEqual(meta.backend, "codex")

    def test_lossy_mapping_visible(self) -> None:
        adapter = CodexAdapter(
            Path(__file__).parent / "fixtures" / "codex_lossy.jsonl",
        )
        self.assertIn(
            "STEP_BOUNDARY_PERSISTED",
            adapter.mapping_metadata.missing_semantics,
        )
        self.assertIn(
            "COMPACTION_RETRY_SAME_STEP",
            adapter.mapping_metadata.missing_semantics,
        )
        call_meta = adapter.call_metadata["call-x"]
        self.assertEqual(call_meta.mapping_quality, LOSSY)
        self.assertEqual(call_meta.backend_event_ref.quality, EXACT)
        self.assertEqual(call_meta.raw_event_ref["line"], 6)

    def test_core_never_reads_backend_metadata(self) -> None:
        core_files = (
            "events.py",
            "event_store.py",
            "surface.py",
            "compaction.py",
            "tool_runtime.py",
            "turn_step.py",
            "initiator.py",
            "recovery.py",
            "runtime.py",
            "model_adapter.py",
            "extensions.py",
        )
        for name in core_files:
            source = (RUNTIME / name).read_text(encoding="utf-8")
            self.assertNotIn("codex", source.lower(), name)
            self.assertNotIn("agentscope", source.lower(), name)


class Phase5FBackendAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def test_agentscope_attempt(self) -> None:
        session = Session("s5f-ags")
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["hello"])
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("a"),
        )

        await agent.run_turn("hi")

        self.assertEqual(len(agent.executions), 1)
        attempt = next(iter(agent.executions.values())).attempts[0]
        self.assertEqual(attempt.status, SUCCEEDED)
        start = next(
            e.payload
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_START
        )
        end = next(
            e.payload
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        )
        self.assertEqual(end["backend_event_ref"]["backend"], "agentscope")
        self.assertEqual(
            end["backend_event_ref"]["event_type"],
            "TextBlockDeltaEvent",
        )
        turn_start = next(
            e.payload
            for e in session.store.events()
            if e.event_type == TURN_START
        )
        self.assertEqual(
            turn_start["backend_metadata"]["backend"],
            "agentscope",
        )
        self.assertEqual(
            turn_start["backend_metadata"]["mapping_quality"],
            ADAPTER,
        )
        self.assertIn(
            "THINKING_BLOCK_LOSSY",
            turn_start["backend_metadata"]["missing_semantics"],
        )
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.ended_at)

    async def test_codex_attempt(self) -> None:
        session = Session("s5f-codex")
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
        agent = AgentRuntime(
            session,
            runtime,
            CodexAdapter(
                Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
            ),
            InitiatorContext("c"),
        )

        turn = await agent.run_turn("查询库存")

        self.assertEqual(len(turn.steps), 3)
        self.assertEqual(len(agent.executions), 3)
        attempts = [
            execution.attempts[0]
            for execution in agent.executions.values()
        ]
        self.assertEqual(
            [a.attempt_number for a in attempts],
            [1, 1, 1],
        )
        self.assertEqual(
            [a.status for a in attempts],
            [SUCCEEDED, SUCCEEDED, SUCCEEDED],
        )
        self.assertEqual(
            len(
                {
                    a.attempt_id
                    for a in attempts
                },
            ),
            3,
        )
        end = next(
            e.payload
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        )
        self.assertEqual(end["backend_event_ref"]["backend"], "codex")
        self.assertEqual(end["backend_event_ref"]["quality"], SYNTHETIC)
        turn_start = next(
            e.payload
            for e in session.store.events()
            if e.event_type == TURN_START
        )
        self.assertIn(
            "STEP_BOUNDARY_PERSISTED",
            turn_start["backend_metadata"]["missing_semantics"],
        )

    async def test_raw_backend_reference_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5f-") as td:
            path = Path(td) / "refs.jsonl"
            store = EventStore("s5f-refs", path=path)
            store.open()
            session = Session("s5f-refs")
            session.store = store
            runtime = ToolRuntime()
            runtime.register(
                ToolRegistration(
                    "inventory.lookup",
                    lambda a, c, s: "stock:5",
                    owner="ERP",
                ),
            )
            await AgentRuntime(
                session,
                runtime,
                CodexAdapter(
                    Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
                ),
                InitiatorContext("c"),
            ).run_turn("查询库存")
            store.close()

            reopened = EventStore("s5f-refs", path=path)
            reopened.open()
            call_ev = next(
                e
                for e in reopened.events()
                if e.event_type == TOOL_CALL
            )
            ref = call_ev.payload["backend_event_ref"]
            self.assertEqual(ref["backend"], "codex")
            self.assertEqual(ref["event_id"], "call-1")
            self.assertIn("rollout_path", ref["reference"])
            self.assertEqual(ref["reference"]["line"], 7)
            attempt_end = next(
                e
                for e in reopened.events()
                if e.event_type == EXECUTION_ATTEMPT_END
            )
            self.assertEqual(
                attempt_end.payload["backend_event_ref"]["backend"],
                "codex",
            )
            reopened.close()

    async def test_replay_preserves_attempt_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5f-") as td:
            path = Path(td) / "attempts.jsonl"
            store = EventStore("s5f-attempts", path=path)
            store.open()
            prior_history(store)
            runtime = ToolRuntime()
            model = DeterministicAgentScopeModel(["done"], overflow_on=1)
            adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
            session = Session("s5f-attempts")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("a"),
                compaction=overflow_engine(store),
            ).run_turn("go")
            store.close()

            reopened = EventStore("s5f-attempts", path=path)
            reopened.open()
            history = replay(reopened)
            reopened.close()

        self.assertEqual(len(history.executions), 1)
        execution = history.executions[0]
        attempts = execution.attempts
        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            [a.attempt_number for a in attempts],
            [1, 2],
        )
        self.assertEqual(
            [a.status for a in attempts],
            [FAILED, SUCCEEDED],
        )
        self.assertEqual(
            attempts[0].execution_id,
            attempts[1].execution_id,
        )
        self.assertEqual(
            attempts[1].parent_execution_id,
            attempts[0].execution_id,
        )
        self.assertIsNone(attempts[0].parent_execution_id)

    async def test_tool_side_effect_blocks_unsafe_retry(self) -> None:
        session = Session("s5f-unsafe")
        prior_history(session.store)
        executed: list[dict] = []

        async def lookup(args, ctx, signal):
            executed.append(dict(args))
            return "stock:5"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap"))
        agent = AgentRuntime(
            session,
            runtime,
            UnsafeRetryAdapter(),
            InitiatorContext("a"),
            compaction=overflow_engine(session.store),
        )

        with self.assertRaises(ModelRequestError):
            await agent.run_turn("go")

        self.assertEqual(executed, [{}])
        self.assertEqual(
            len(
                [
                    e
                    for e in session.store.events()
                    if e.event_type == TOOL_CALL
                ],
            ),
            1,
        )
        self.assertEqual(len(agent.executions), 1)
        attempt = next(iter(agent.executions.values())).attempts[0]
        self.assertEqual(attempt.status, ABORTED)
        self.assertEqual(attempt.reason, "UNSAFE_RETRY_BLOCKED")
        end = next(
            e.payload
            for e in session.store.events()
            if e.event_type == EXECUTION_ATTEMPT_END
        )
        self.assertEqual(end["status"], ABORTED)
        self.assertEqual(end["reason"], "UNSAFE_RETRY_BLOCKED")
        self.assertEqual(
            len(
                [
                    e
                    for e in session.store.events()
                    if e.event_type == EXECUTION_ATTEMPT_END
                ],
            ),
            1,
        )
        self.assertEqual(
            len(
                [
                    e
                    for e in session.store.events()
                    if e.event_type == EXECUTION_ATTEMPT_START
                ],
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
