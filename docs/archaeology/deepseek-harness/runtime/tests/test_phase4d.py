"""Phase 4-D: Real Agent Loop + AgentScope 2.0 Python E2E tests.

All AgentScope access is public API only (agentscope 2.0.2). The deterministic
models are AgentScope-compatible ChatModelBase subclasses; real model adapters
share the same ModelAdapter runtime interface.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
KERNEL = Path(__file__).resolve().parents[3] / "python-cordis" / "kernel"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(KERNEL))

from agentscope.credential import CredentialBase  # noqa: E402
from agentscope.message import (  # noqa: E402
    TextBlock,
    ToolCallBlock,
    ToolCallState,
)
from agentscope.model import ChatModelBase, ChatResponse  # noqa: E402

from compaction import (  # noqa: E402
    CONTEXT_WINDOW_EXCEEDED,
    NO_RETRY,
    CompactionEngine,
    TokenMeter,
    build_model_context,
    retry_safe,
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
    REQUEST_HEADER,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    SessionEvent,
)
from initiator import (  # noqa: E402
    InitiatorContext,
    current_initiator,
    require_initiator,
)
from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from recovery import rebuild_session, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from surface import SurfaceProjection  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import ENDED, Session  # noqa: E402


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


def msg_text(msg) -> str:
    parts = []
    content = msg.content if isinstance(msg.content, list) else [msg.content]
    for block in content:
        parts.append(getattr(block, "text", getattr(block, "delta", "")))
    return "".join(parts)


class DeterministicAgentScopeModel(ChatModelBase):
    """AgentScope-compatible deterministic model (test-only).

    script items: str = final text; (str, [(call_id, name, args)]) = tool step.
    overflow_on = 1-based call index that raises CONTEXT_WINDOW_EXCEEDED.
    """

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
        self.seen: list = []

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        self.calls += 1
        self.seen.append(list(messages))
        if self.overflow_on is not None and self.calls == self.overflow_on:
            raise RuntimeError("CONTEXT_WINDOW_EXCEEDED")
        if not self.script:
            return ChatResponse(content=[TextBlock(text="final answer")], is_last=True)
        item = self.script.pop(0)
        if isinstance(item, str):
            return ChatResponse(content=[TextBlock(text=item)], is_last=True)
        text, calls = item
        blocks: list = []
        if text:
            blocks.append(TextBlock(text=text))
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


class StreamingAgentScopeModel(ChatModelBase):
    """Streaming deterministic model: chunks with is_last semantics."""

    def __init__(self, chunks) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="det-stream",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            max_retries=0,
            retry_delay=0.0,
            context_size=1024,
        )
        self.chunks = list(chunks)

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        async def stream():
            for text, is_last in self.chunks:
                yield ChatResponse(
                    content=[TextBlock(text=text)] if text else [],
                    is_last=is_last,
                )

        return stream()


class Phase4DRealAgentScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_agentscope_basic_turn(self) -> None:
        runtime = ToolRuntime()
        model = DeterministicAgentScopeModel(["hello from agentscope"])
        adapter = AgentScopeModelAdapter(
            model,
            runtime,
            name="agent-a",
            system_prompt="system prompt",
        )
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("hi")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 1)
        self.assertEqual(
            event_types(session.store),
            [
                USER_MESSAGE,
                TURN_START,
                STEP_START,
                AGENT_REQUEST,
                EXECUTION_ATTEMPT_START,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                EXECUTION_ATTEMPT_END,
                STEP_END,
                TURN_END,
            ],
        )
        final = next(
            e for e in session.store.events()
            if e.event_type == ASSISTANT_MESSAGE
        )
        self.assertEqual(final.payload["content"], "hello from agentscope")
        request = next(
            e for e in session.store.events()
            if e.event_type == AGENT_REQUEST
        )
        self.assertEqual(request.payload["model"], "det-agent")
        self.assertEqual(msg_text(model.seen[0][-1]), "hi")

    async def test_real_agentscope_tool_call(self) -> None:
        async def lookup(args, ctx, signal):
            return "result:42"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap-c"))
        model = DeterministicAgentScopeModel(
            [
                ("calling lookup", [("c1", "lookup", {"q": "x"})]),
                "answer:42",
            ],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("go")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 2)
        self.assertEqual(
            event_types(session.store),
            [
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
                EXECUTION_ATTEMPT_END,
                STEP_END,
                TURN_END,
            ],
        )
        call_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_CALL
        )
        result_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_RESULT
        )
        self.assertEqual(result_ev.payload["content"], "result:42")
        self.assertEqual(
            result_ev.source_event_seqs,
            (call_ev.seq,),
        )
        self.assertEqual(
            result_ev.payload["tool_call_id"],
            call_ev.payload["call_id"],
        )
        self.assertNotEqual(turn.steps[0].step_id, turn.steps[1].step_id)

    async def test_real_agentscope_multi_step(self) -> None:
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration("t1", lambda a, c, s: "r1", owner="cap-c"),
        )
        runtime.register(
            ToolRegistration("t2", lambda a, c, s: "r2", owner="cap-c"),
        )
        model = DeterministicAgentScopeModel(
            [
                ("first", [("c1", "t1", {})]),
                ("second", [("c2", "t2", {})]),
                "done",
            ],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("go")

        self.assertEqual(len(turn.steps), 3)
        self.assertEqual(
            [s.status for s in turn.steps],
            [ENDED, ENDED, ENDED],
        )
        calls = [e for e in session.store.events() if e.event_type == TOOL_CALL]
        results = [
            e for e in session.store.events() if e.event_type == TOOL_RESULT
        ]
        self.assertEqual([e.payload["name"] for e in calls], ["t1", "t2"])
        self.assertEqual(
            [e.source_event_seqs for e in results],
            [(calls[0].seq,), (calls[1].seq,)],
        )
        self.assertEqual(
            {e.step_id for e in calls},
            {turn.steps[0].step_id, turn.steps[1].step_id},
        )

    async def test_real_agentscope_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase4d-") as td:
            path = Path(td) / "s1.jsonl"
            store = EventStore("s1", path=path)
            store.open()
            runtime = ToolRuntime()
            runtime.register(
                ToolRegistration(
                    "lookup",
                    lambda a, c, s: "value:42",
                    owner="cap-c",
                ),
            )
            model = DeterministicAgentScopeModel(
                [
                    ("calling lookup", [("c1", "lookup", {"q": "x"})]),
                    "answer:42",
                ],
            )
            adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
            session = Session("s1")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("agent-a"),
            ).run_turn("hello")
            surface_a = SurfaceProjection(store).derive_messages()
            seq_count = store.last_seq()
            normalized = [
                REQUEST_HEADER if t == AGENT_REQUEST else t
                for t in event_types(store)
            ]
            store.close()

            reopened = EventStore("s1", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                [REQUEST_HEADER if t == AGENT_REQUEST else t
                 for t in event_types(reopened)],
                normalized,
            )
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                surface_a,
            )
            rebuilt = rebuild_session(reopened)
            self.assertEqual(len(rebuilt.turns), 1)
            self.assertEqual(len(rebuilt.turns[0].steps), 2)
            reopened.close()

    async def test_real_agentscope_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase4d-") as td:
            path = Path(td) / "s2.jsonl"
            store = EventStore("s2", path=path)
            store.open()
            runtime = ToolRuntime()
            runtime.register(
                ToolRegistration(
                    "lookup",
                    lambda a, c, s: "result:42",
                    owner="cap-c",
                ),
            )
            model = DeterministicAgentScopeModel(
                [
                    ("calling lookup", [("c1", "lookup", {"q": "x"})]),
                    "answer:42",
                ],
            )
            adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
            session = Session("s2")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("agent-a"),
            ).run_turn("hello")
            store.close()

            reopened = EventStore("s2", path=path)
            reopened.open()
            history = replay(reopened)
            self.assertEqual(history.session_id, "s2")
            self.assertEqual(len(history.turns), 1)
            turn = history.turns[0]
            self.assertEqual(turn.end_reason, "completed")
            self.assertEqual(len(turn.steps), 2)
            self.assertEqual(turn.steps[0].request["model"], "det-agent")
            self.assertEqual(
                turn.steps[0].tool_calls[0]["name"],
                "lookup",
            )
            self.assertEqual(
                turn.steps[0].tool_results[0].content,
                "result:42",
            )
            self.assertEqual(
                turn.steps[1].assistant_messages[0]["content"],
                "answer:42",
            )
            reopened.close()

    async def test_stream_reconstruction(self) -> None:
        runtime = ToolRuntime()
        model = StreamingAgentScopeModel(
            [("Hello ", False), ("world", False), ("", True)],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("hi")

        self.assertEqual(turn.end_reason, "completed")
        chunks = [
            e for e in session.store.events()
            if e.event_type == ASSISTANT_CHUNK
        ]
        self.assertEqual(
            [e.payload["content"] for e in chunks],
            ["Hello ", "world"],
        )
        final = next(
            e for e in session.store.events()
            if e.event_type == ASSISTANT_MESSAGE
        )
        self.assertEqual(final.payload["content"], "Hello world")
        self.assertEqual(
            final.source_event_seqs,
            tuple(e.seq for e in chunks),
        )


class Phase4DCompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_overflow_compaction_retry(self) -> None:
        session = Session("s1")
        prior_history(session.store)
        executed: list = []

        async def lookup(args, ctx, signal):
            executed.append(dict(args))
            return "stock:5"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap-c"))
        engine = CompactionEngine(
            session.store,
            TokenMeter(
                context_window=100000,
                threshold_ratio=0.8,
                retain_ratio=0.16,
            ),
            max_overflow_retries=1,
        )
        model = DeterministicAgentScopeModel(
            [("calling lookup", [("c1", "lookup", {"sku": "A"})]), "done"],
            overflow_on=1,
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
            compaction=engine,
        ).run_turn("go")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(engine.overflow_retries, 1)
        types = event_types(session.store)
        self.assertIn(COMPACTION_START, types)
        self.assertIn(COMPACTION_SUMMARY, types)
        self.assertIn(COMPACTION_END, types)
        self.assertEqual(len(executed), 1)
        self.assertEqual(
            len([e for e in session.store.events() if e.event_type == TOOL_CALL]),
            1,
        )
        # Second request uses the rebuilt (compacted) context.
        self.assertTrue(
            any(
                "compacted-summary" in msg_text(m)
                for m in model.seen[1]
            ),
        )
        # Compaction replacement is an append-only surface replace.
        replacement = next(
            e
            for e in session.store.events()
            if e.event_type == USER_MESSAGE and e.surface_op is not None
        )
        self.assertEqual(replacement.surface_op["op"], "replace")
        shadowed = set(
            range(
                replacement.surface_op["start"],
                replacement.surface_op["end"] + 1,
            ),
        )
        self.assertTrue(shadowed.issubset(set(replacement.source_event_seqs)))
        # No tool side effect happened before the retry.
        call_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_CALL
        )
        last_compact = max(
            e.seq for e in session.store.events()
            if e.event_type == COMPACTION_END
        )
        self.assertGreater(call_ev.seq, last_compact)

    async def test_compaction_persisted_surface(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase4d-") as td:
            path = Path(td) / "s3.jsonl"
            store = EventStore("s3", path=path)
            store.open()
            prior_history(store)
            runtime = ToolRuntime()
            runtime.register(
                ToolRegistration(
                    "lookup",
                    lambda a, c, s: "stock:5",
                    owner="cap-c",
                ),
            )
            engine = CompactionEngine(
                store,
                TokenMeter(
                    context_window=100000,
                    threshold_ratio=0.8,
                    retain_ratio=0.16,
                ),
                max_overflow_retries=1,
            )
            model = DeterministicAgentScopeModel(
                [("calling lookup", [("c1", "lookup", {})]), "done"],
                overflow_on=1,
            )
            adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
            session = Session("s3")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("agent-a"),
                compaction=engine,
            ).run_turn("go")
            surface_a = SurfaceProjection(store).derive_messages()
            seq_count = store.last_seq()
            store.close()

            reopened = EventStore("s3", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                surface_a,
            )
            types = event_types(reopened)
            self.assertIn(COMPACTION_START, types)
            self.assertIn(COMPACTION_SUMMARY, types)
            self.assertIn(COMPACTION_END, types)
            history = replay(reopened)
            self.assertEqual(len(history.turns[0].steps), 2)
            reopened.close()

    async def test_tool_side_effect_retry_boundary(self) -> None:
        session = Session("s1")
        prior_history(session.store, 2)
        executed: list = []

        async def lookup(args, ctx, signal):
            executed.append(dict(args))
            return "stock:5"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap-c"))
        engine = CompactionEngine(
            session.store,
            TokenMeter(
                context_window=100000,
                threshold_ratio=0.8,
                retain_ratio=0.16,
            ),
            max_overflow_retries=1,
        )
        model = DeterministicAgentScopeModel(
            [("calling lookup", [("c1", "lookup", {"sku": "A"})]), "call2"],
            overflow_on=2,
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
            compaction=engine,
        ).run_turn("go")

        # Overflow in step 2 retries step 2 only; the step-1 tool side effect
        # is never re-executed.
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(engine.overflow_retries, 1)
        self.assertEqual(executed, [{"sku": "A"}])
        self.assertEqual(
            len([e for e in session.store.events() if e.event_type == TOOL_CALL]),
            1,
        )
        step2 = turn.steps[1]
        self.assertEqual(
            [
                e.event_type
                for e in session.store.events()
                if e.step_id == step2.step_id
            ],
            [
                STEP_START,
                AGENT_REQUEST,
                EXECUTION_ATTEMPT_START,
                EXECUTION_ATTEMPT_END,
                EXECUTION_ATTEMPT_START,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                EXECUTION_ATTEMPT_END,
                STEP_END,
            ],
        )

        # Same-step tool result after request blocks retry at the decision
        # level (retry_safe contract from Phase 4-C).
        unsafe = EventStore("unsafe")
        unsafe.append(
            SessionEvent(
                0,
                REQUEST_HEADER,
                "unsafe",
                payload={"model": "det"},
            ),
        )
        unsafe.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                "unsafe",
                payload={
                    "tool_call_id": "c1",
                    "content": "ran",
                    "is_error": False,
                },
                source_event_seqs=(),
            ),
        )
        self.assertFalse(retry_safe(unsafe))
        engine2 = CompactionEngine(
            unsafe,
            TokenMeter(context_window=100000),
        )
        decision = engine2.handle_request_error(CONTEXT_WINDOW_EXCEEDED)
        self.assertEqual(decision.kind, NO_RETRY)
        self.assertEqual(decision.reason, "retry_not_safe")


class Phase4DInitiatorAndBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_initiator_through_agentloop(self) -> None:
        seen: list[str] = []

        async def probe(args, ctx, signal):
            await asyncio.sleep(0)
            seen.append(require_initiator().agent_id)
            return "ok"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("probe", probe, owner="cap-c"))
        model = DeterministicAgentScopeModel(
            [("probing", [("c1", "probe", {})]), "done"],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("go")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(seen, ["agent-a"])
        self.assertIsNone(current_initiator())
        with self.assertRaises(RuntimeError):
            require_initiator()

    async def test_owner_vs_initiator(self) -> None:
        seen: list[str] = []

        async def probe(args, ctx, signal):
            seen.append(require_initiator().agent_id)
            return "ok"

        runtime = ToolRuntime()
        registration = ToolRegistration("probe", probe, owner="cap-c")
        runtime.register(registration)
        model = DeterministicAgentScopeModel(
            [("probing", [("c1", "probe", {})]), "done"],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("go")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(runtime.get("probe").owner, "cap-c")
        self.assertEqual(registration.owner, "cap-c")
        self.assertEqual(seen, ["agent-a"])
        self.assertNotEqual(registration.owner, seen[0])

    async def test_tool_failure_boundary(self) -> None:
        async def failing(args, ctx, signal):
            raise ValueError("boom")

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("failing", failing, owner="cap-c"))
        model = DeterministicAgentScopeModel(
            [("calling failing", [("c1", "failing", {})]), "final"],
        )
        adapter = AgentScopeModelAdapter(model, runtime, name="agent-a")
        session = Session("s1")

        turn = await AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        ).run_turn("go")

        result_ev = next(
            e for e in session.store.events() if e.event_type == TOOL_RESULT
        )
        self.assertTrue(result_ev.payload["is_error"])
        self.assertEqual(result_ev.payload["error_code"], "EXECUTION_ERROR")
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual({s.status for s in turn.steps}, {ENDED})
        self.assertEqual(
            [e.payload["reason"] for e in session.store.events()
             if e.event_type == TURN_END],
            ["completed"],
        )


class Phase4DGoldenScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_golden_inventory_procurement_e2e(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase4d-") as td:
            path = Path(td) / "golden.jsonl"
            store = EventStore("golden", path=path)
            store.open()
            initiators: list[str] = []

            async def inventory(args, ctx, signal):
                initiators.append(require_initiator().agent_id)
                return "stock:5"

            async def suggest(args, ctx, signal):
                initiators.append(require_initiator().agent_id)
                return "suggestion:created"

            runtime = ToolRuntime()
            runtime.register(
                ToolRegistration(
                    "inventory.lookup",
                    inventory,
                    owner="ERP",
                ),
            )
            runtime.register(
                ToolRegistration(
                    "procurement.suggest",
                    suggest,
                    owner="ERP",
                ),
            )
            model = DeterministicAgentScopeModel(
                [
                    (
                        "checking inventory",
                        [("c1", "inventory.lookup", {"sku": "A"})],
                    ),
                    (
                        "creating suggestion",
                        [("c2", "procurement.suggest", {"sku": "A", "qty": 10})],
                    ),
                    "done: procurement suggestion created for 10",
                ],
            )
            adapter = AgentScopeModelAdapter(
                model,
                runtime,
                name="agent-a",
                system_prompt="You are a procurement assistant.",
            )
            session = Session("golden")
            session.store = store
            turn = await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("agent-a"),
            ).run_turn("查询库存，如果不足则创建采购建议。")

            # 1. Event order.
            self.assertEqual(
                event_types(store),
                [
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
                ],
            )
            # 2. Owner.
            self.assertEqual(runtime.get("inventory.lookup").owner, "ERP")
            self.assertEqual(runtime.get("procurement.suggest").owner, "ERP")
            # 3. Initiator.
            self.assertEqual(initiators, ["agent-a", "agent-a"])
            # 4. Tool lineage.
            calls = [
                e for e in store.events() if e.event_type == TOOL_CALL
            ]
            results = [
                e for e in store.events() if e.event_type == TOOL_RESULT
            ]
            self.assertEqual(
                [e.payload["name"] for e in calls],
                ["inventory.lookup", "procurement.suggest"],
            )
            self.assertEqual(
                [e.source_event_seqs for e in results],
                [(calls[0].seq,), (calls[1].seq,)],
            )
            self.assertEqual(
                [e.payload["tool_call_id"] for e in results],
                [calls[0].payload["call_id"], calls[1].payload["call_id"]],
            )
            # 5. Surface.
            messages = SurfaceProjection(store).derive_messages()
            self.assertEqual(
                [m.role for m in messages],
                ["user", "assistant", "tool", "assistant", "tool", "assistant"],
            )
            self.assertEqual(
                messages[-1].content,
                "done: procurement suggestion created for 10",
            )
            # 6. Final context.
            context = build_model_context(
                session,
                system_prompt="",
                tools=runtime.names(),
            )
            self.assertEqual(
                context.messages[-1].content,
                "done: procurement suggestion created for 10",
            )
            self.assertEqual(context.tools, ("inventory.lookup", "procurement.suggest"))
            # 7. Persistence.
            seq_count = store.last_seq()
            store.close()
            reopened = EventStore("golden", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                messages,
            )
            # 8. Replay.
            history = replay(reopened)
            self.assertEqual(len(history.turns), 1)
            golden_turn = history.turns[0]
            self.assertEqual(golden_turn.end_reason, "completed")
            self.assertEqual(len(golden_turn.steps), 3)
            self.assertEqual(
                [len(s.tool_calls) for s in golden_turn.steps],
                [1, 1, 0],
            )
            self.assertEqual(
                golden_turn.steps[1].tool_calls[0]["name"],
                "procurement.suggest",
            )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
