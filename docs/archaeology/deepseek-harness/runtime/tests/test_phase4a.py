"""Phase 4-A: DSH minimal Python runtime skeleton tests.

Each test asserts one of the Phase 4-A acceptance behaviors. The runtime is
stdlib-only; the only external imports are the Phase 2 kernel
(PluginManager / CapabilityDescriptor / adapters.agentscope) used to prove
Capability -> EffectRegistry -> Tool registration cleanup.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
KERNEL = Path(__file__).resolve().parents[3] / "python-cordis" / "kernel"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(KERNEL))

from adapters.agentscope import register_tool  # noqa: E402
from agentscope.tool import FunctionTool, Toolkit  # noqa: E402
from capability import CapabilityDescriptor  # noqa: E402
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
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
from manager import PluginManager  # noqa: E402
from runtime import ModelResponse, ModelToolCall, RuntimeCoordinator  # noqa: E402
from surface import Message, SurfaceProjection  # noqa: E402
from tool_runtime import (  # noqa: E402
    ALLOW,
    ASK,
    DENY,
    ToolCall,
    ToolRegistration,
    ToolResult,
    ToolRuntime,
)
from turn_step import ENDED, ExecutionContext, Session, Turn  # noqa: E402


def event_types(store: EventStore) -> list[str]:
    return [e.event_type for e in store.events()]


def tool_result_events(store: EventStore):
    return [e for e in store.events() if e.event_type == TOOL_RESULT]


class ScriptedModel:
    """Deterministic fake model: returns a scripted response per step."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.seen: list[tuple[Message, ...]] = []

    async def __call__(self, messages):
        self.seen.append(messages)
        return self.responses.pop(0)


class OwnedToolCapability:
    """Phase 2 capability: owns one runtime tool + one AgentScope Toolkit tool.

    Both registrations are collected as scope effects, so Capability dispose
    removes them through EffectRegistry cleanup.
    """

    def __init__(
        self,
        scope,
        runtime: ToolRuntime,
        owner: str,
        toolkit: Toolkit | None = None,
        hook_log: list[str] | None = None,
        tool_fn=None,
    ) -> None:
        self.scope = scope
        self.runtime = runtime
        self.owner = owner
        self.toolkit = toolkit
        self.hook_log = hook_log
        self.tool_fn = tool_fn

    async def install(self) -> None:
        async def setup(collect):
            log = self.hook_log

            async def default_fn(args, ctx, signal):
                if log is not None:
                    log.append("execute")
                return "result:ok"

            fn = self.tool_fn or default_fn

            def pre_execute(call, ctx):
                if log is not None:
                    log.append("pre_execute")
                return ALLOW

            def guard(call, ctx):
                if log is not None:
                    log.append("guard")
                return None

            def post_execute(call, result, ctx):
                if log is not None:
                    log.append("post_execute")
                return None

            def finalize(call, result, ctx):
                if log is not None:
                    log.append("finalize")
                return None

            reg = ToolRegistration(
                name="lookup",
                fn=fn,
                owner=self.owner,
                pre_execute=pre_execute,
                guard=guard,
                post_execute=post_execute,
                finalize=finalize,
            )
            collect("tool:lookup", self.runtime.register(reg))
            if self.toolkit is not None:
                collect(
                    "toolkit:lookup",
                    register_tool(
                        self.toolkit,
                        FunctionTool(lambda q: "ok", name="lookup"),
                    ),
                )

        await self.scope.effect("cap-c.install", setup)


class Phase4ARuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_event_order(self) -> None:
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration(
                "lookup",
                lambda args, ctx, signal: "value",
                owner="cap-c",
            ),
        )
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling lookup",
                    (ModelToolCall("c1", "lookup", {"q": "x"}),),
                ),
                ModelResponse("final answer"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("hello")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(
            event_types(session.store),
            [
                USER_MESSAGE,
                TURN_START,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                TOOL_CALL,
                TOOL_RESULT,
                STEP_END,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                STEP_END,
                TURN_END,
            ],
        )
        self.assertEqual(
            [e.seq for e in session.store.events()],
            list(range(1, len(session.store.events()) + 1)),
        )

    async def test_multi_step_turn(self) -> None:
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration(
                "lookup",
                lambda args, ctx, signal: "value",
                owner="cap-c",
            ),
        )
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling lookup",
                    (ModelToolCall("c1", "lookup", {}),),
                ),
                ModelResponse("final answer"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("hello")

        self.assertEqual(len(turn.steps), 2)
        self.assertEqual({s.status for s in turn.steps}, {ENDED})
        self.assertNotEqual(turn.steps[0].step_id, turn.steps[1].step_id)
        self.assertEqual(
            {e.turn_id for e in session.store.events()},
            {turn.turn_id},
        )
        self.assertEqual(len(turn.steps[0].tool_calls), 1)
        self.assertEqual(turn.steps[1].tool_calls, [])

    async def test_tool_waterfall(self) -> None:
        log: list[str] = []

        async def tool_fn(args, ctx, signal):
            log.append("execute")
            return "value"

        def make_reg(name: str, pre=None) -> ToolRegistration:
            return ToolRegistration(
                name=name,
                fn=tool_fn,
                owner="cap-c",
                pre_execute=pre,
                guard=lambda call, ctx: (
                    log.append("guard") or None
                ),
                post_execute=lambda call, result, ctx: (
                    log.append("post_execute") or None
                ),
                finalize=lambda call, result, ctx: (
                    log.append("finalize") or None
                ),
            )

        session = Session("s1")
        turn = Turn("t1", session)
        turn.begin()
        step = turn.new_step()
        step.begin()
        ctx = ExecutionContext(session, turn, step)

        runtime = ToolRuntime()
        runtime.register(
            make_reg(
                "wf",
                lambda call, ctx: (log.append("pre_execute"), ALLOW)[1],
            ),
        )
        result = await runtime.execute(ToolCall("c1", "wf", {}), ctx)

        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "value")
        self.assertEqual(
            log,
            ["pre_execute", "guard", "execute", "post_execute", "finalize"],
        )
        self.assertEqual(event_types(session.store), [TOOL_CALL, TOOL_RESULT])
        result_ev = session.store.events()[1]
        self.assertEqual(
            result_ev.source_event_seqs,
            (session.store.events()[0].seq,),
        )

        # ASK -> approval seam rejects -> is_error, tool body never runs.
        log.clear()
        approval_log: list[str] = []
        ask_runtime = ToolRuntime(
            approval=lambda call, ctx: (
                approval_log.append("approval") or False
            ),
        )
        ask_runtime.register(
            make_reg(
                "wf-ask",
                lambda call, ctx: (log.append("pre_execute"), ASK)[1],
            ),
        )
        ask_result = await ask_runtime.execute(
            ToolCall("c2", "wf-ask", {}),
            ctx,
        )
        self.assertTrue(ask_result.is_error)
        self.assertEqual(approval_log, ["approval"])
        self.assertNotIn("execute", log)

        # DENY -> is_error, still post-execute/finalize/materialize.
        log.clear()
        deny_runtime = ToolRuntime()
        deny_runtime.register(
            make_reg(
                "wf-deny",
                lambda call, ctx: (log.append("pre_execute"), DENY)[1],
            ),
        )
        deny_result = await deny_runtime.execute(
            ToolCall("c3", "wf-deny", {}),
            ctx,
        )
        self.assertTrue(deny_result.is_error)
        self.assertEqual(
            log,
            ["pre_execute", "post_execute", "finalize"],
        )

    async def test_tool_failure_does_not_fail_step(self) -> None:
        async def failing(args, ctx, signal):
            raise ValueError("boom")

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("failing", failing, owner="cap-c"))
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling failing",
                    (ModelToolCall("c1", "failing", {}),),
                ),
                ModelResponse("final answer"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("go")

        result_ev = tool_result_events(session.store)[0]
        self.assertTrue(result_ev.payload["is_error"])
        self.assertEqual(result_ev.payload["error_code"], "EXECUTION_ERROR")
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual({s.status for s in turn.steps}, {ENDED})
        self.assertEqual(
            [e.payload["reason"] for e in session.store.events() if e.event_type == TURN_END],
            ["completed"],
        )

    async def test_model_visible_projection(self) -> None:
        ts = "2026-08-16T00:00:00+00:00"

        def make_store(session_id: str) -> EventStore:
            store = EventStore(session_id)
            store.append_many(
                [
                    SessionEvent(
                        0,
                        USER_MESSAGE,
                        session_id,
                        payload={"content": "hi"},
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        TURN_START,
                        session_id,
                        turn_id="t1",
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        STEP_START,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        ASSISTANT_CHUNK,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        payload={"content": "chunk text"},
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        ASSISTANT_MESSAGE,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        payload={
                            "content": "assembled",
                            "tool_calls": [],
                        },
                        source_event_seqs=(4,),
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        TOOL_CALL,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        payload={
                            "call_id": "c1",
                            "name": "lookup",
                            "arguments": {"q": "x"},
                        },
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        TOOL_RESULT,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        payload={
                            "tool_call_id": "c1",
                            "content": "result:x",
                            "is_error": False,
                        },
                        source_event_seqs=(6,),
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        STEP_END,
                        session_id,
                        turn_id="t1",
                        step_id="t1/s1",
                        timestamp=ts,
                    ),
                    SessionEvent(
                        0,
                        TURN_END,
                        session_id,
                        turn_id="t1",
                        payload={"reason": "completed"},
                        timestamp=ts,
                    ),
                ],
            )
            return store

        store_a = make_store("a")
        store_b = make_store("b")
        messages_a = SurfaceProjection(store_a).derive_messages()
        messages_b = SurfaceProjection(store_b).derive_messages()

        self.assertEqual(messages_a, messages_b)
        self.assertEqual([m.role for m in messages_a], ["user", "assistant", "tool"])
        self.assertEqual(messages_a[1].content, "assembled")
        self.assertEqual(messages_a[2].tool_call_id, "c1")
        self.assertEqual(messages_a[2].content, "result:x")
        self.assertNotIn("chunk text", [m.content for m in messages_a])

    async def test_next_step_from_tool_result(self) -> None:
        runtime = ToolRuntime()

        async def weather(args, ctx, signal):
            return "sunny:24C"

        runtime.register(ToolRegistration("weather", weather, owner="cap-c"))
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "checking weather",
                    (ModelToolCall("c1", "weather", {"city": "Paris"}),),
                ),
                ModelResponse("It is sunny in Paris."),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        await coordinator.run_turn("weather in Paris?")

        self.assertEqual(len(model.seen), 2)
        second_input = model.seen[1]
        self.assertEqual(second_input[-1].role, "tool")
        self.assertEqual(second_input[-1].tool_call_id, "c1")
        self.assertEqual(second_input[-1].content, "sunny:24C")

    async def test_initiator_propagation(self) -> None:
        seen: list[str] = []

        async def probe(args, ctx, signal):
            await asyncio.sleep(0)  # force a context-switch boundary
            seen.append(require_initiator().agent_id)
            return "ok"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("probe", probe, owner="cap-c"))
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "probing",
                    (ModelToolCall("c1", "probe", {}),),
                ),
                ModelResponse("done"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        await coordinator.run_turn("go")

        self.assertEqual(seen, ["agent-a"])
        self.assertIsNone(current_initiator())
        with self.assertRaises(RuntimeError):
            require_initiator()

    async def test_owner_and_initiator_are_distinct(self) -> None:
        initiators: list[str] = []

        async def probe(args, ctx, signal):
            initiators.append(require_initiator().agent_id)
            return "ok"

        runtime = ToolRuntime()
        reg = ToolRegistration("probe", probe, owner="cap-c")
        runtime.register(reg)
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "probing",
                    (ModelToolCall("c1", "probe", {}),),
                ),
                ModelResponse("done"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        await coordinator.run_turn("go")

        self.assertEqual(reg.owner, "cap-c")
        self.assertEqual(runtime.get("probe").owner, "cap-c")
        self.assertEqual(initiators, ["agent-a"])
        self.assertNotEqual(reg.owner, initiators[0])

    async def test_capability_dispose_removes_tool(self) -> None:
        runtime = ToolRuntime()
        toolkit = Toolkit()
        manager = PluginManager()
        manager.register(
            CapabilityDescriptor(
                id="cap-c",
                version="1",
                factory=lambda scope: OwnedToolCapability(
                    scope,
                    runtime,
                    owner="cap-c",
                    toolkit=toolkit,
                ),
            ),
        )

        cap = await manager.install("cap-c")
        self.assertIsNotNone(runtime.get("lookup"))
        self.assertIsNotNone(await toolkit.get_tool("lookup"))
        self.assertEqual(cap.scope.state, "ACTIVE")

        errors = await manager.unload("cap-c")

        self.assertEqual(errors, [])
        self.assertIsNone(runtime.get("lookup"))
        self.assertIsNone(await toolkit.get_tool("lookup"))
        self.assertEqual(cap.scope.state, "DISPOSED")

    async def test_concludes_turn(self) -> None:
        runtime = ToolRuntime()

        async def finisher(args, ctx, signal):
            return ToolResult("c1", "done", concludes_turn=True)

        runtime.register(ToolRegistration("finisher", finisher, owner="cap-c"))
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling finisher",
                    (ModelToolCall("c1", "finisher", {}),),
                ),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("finish it")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 1)
        self.assertEqual(len(model.seen), 1)
        self.assertEqual(
            event_types(session.store),
            [
                USER_MESSAGE,
                TURN_START,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                TOOL_CALL,
                TOOL_RESULT,
                STEP_END,
                TURN_END,
            ],
        )

    async def test_timeout(self) -> None:
        async def slow(args, ctx, signal):
            await asyncio.Event().wait()

        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration("slow", slow, owner="cap-c", timeout_ms=10),
        )
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling slow",
                    (ModelToolCall("c1", "slow", {}),),
                ),
                ModelResponse("final answer"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("go")

        result_ev = tool_result_events(session.store)[0]
        self.assertTrue(result_ev.payload["is_error"])
        self.assertEqual(result_ev.payload["error_code"], "TOOL_TIMEOUT")
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 2)

    async def test_cancellation(self) -> None:
        started = asyncio.Event()

        async def cancellable(args, ctx, signal):
            started.set()
            await signal.wait()
            raise asyncio.CancelledError

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("cancel", cancellable, owner="cap-c"))
        session = Session("s1")
        turn = Turn("t1", session)
        turn.begin()
        step = turn.new_step()
        step.begin()
        ctx = ExecutionContext(session, turn, step)

        task = asyncio.create_task(
            runtime.execute(ToolCall("c1", "cancel", {}), ctx),
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        runtime.cancel("c1")
        result = await asyncio.wait_for(task, timeout=1)

        self.assertTrue(result.is_error)
        self.assertEqual(result.error_code, "ABORTED")
        self.assertEqual(event_types(session.store), [TOOL_CALL, TOOL_RESULT])

        # Cancellation before dispatch is explicit, not silently ignored.
        pre_runtime = ToolRuntime()
        pre_runtime.register(
            ToolRegistration("pre-cancel", cancellable, owner="cap-c"),
        )
        session2 = Session("s2")
        turn2 = Turn("t2", session2)
        turn2.begin()
        step2 = turn2.new_step()
        step2.begin()
        pre_runtime.cancel("c-pre")
        pre_result = await pre_runtime.execute(
            ToolCall("c-pre", "pre-cancel", {}),
            ExecutionContext(session2, turn2, step2),
        )
        self.assertEqual(pre_result.error_code, "ABORTED_BEFORE_DISPATCH")

    async def test_multiple_tools_same_step(self) -> None:
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration("t1", lambda args, ctx, signal: "r1", owner="cap-c"),
        )
        runtime.register(
            ToolRegistration("t2", lambda args, ctx, signal: "r2", owner="cap-c"),
        )
        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling both",
                    (
                        ModelToolCall("c1", "t1", {}),
                        ModelToolCall("c2", "t2", {}),
                    ),
                ),
                ModelResponse("final answer"),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("go")

        self.assertEqual(len(turn.steps[0].tool_calls), 2)
        calls = [e for e in session.store.events() if e.event_type == TOOL_CALL]
        results = tool_result_events(session.store)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(results), 2)
        self.assertEqual({e.step_id for e in calls}, {turn.steps[0].step_id})
        self.assertEqual({e.step_id for e in results}, {turn.steps[0].step_id})
        self.assertEqual(
            [e.source_event_seqs for e in results],
            [(calls[0].seq,), (calls[1].seq,)],
        )
        self.assertEqual(
            {e.payload["name"] for e in calls},
            {"t1", "t2"},
        )

    async def test_assistant_final_without_tool(self) -> None:
        runtime = ToolRuntime()
        session = Session("s1")
        model = ScriptedModel([ModelResponse("hello back")])
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )

        turn = await coordinator.run_turn("hello")

        self.assertEqual(len(turn.steps), 1)
        self.assertEqual(
            event_types(session.store),
            [
                USER_MESSAGE,
                TURN_START,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                STEP_END,
                TURN_END,
            ],
        )
        self.assertNotIn(TOOL_CALL, event_types(session.store))

    async def test_integration_full_chain(self) -> None:
        runtime = ToolRuntime()
        hook_log: list[str] = []
        initiators: list[str] = []

        async def lookup_fn(args, ctx, signal):
            hook_log.append("execute")
            initiators.append(require_initiator().agent_id)
            return "value:42"

        manager = PluginManager()
        manager.register(
            CapabilityDescriptor(
                id="cap-c",
                version="1",
                factory=lambda scope: OwnedToolCapability(
                    scope,
                    runtime,
                    owner="cap-c",
                    hook_log=hook_log,
                    tool_fn=lookup_fn,
                ),
            ),
        )
        await manager.install("cap-c")

        session = Session("s1")
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling lookup",
                    (ModelToolCall("c1", "lookup", {"q": "life"} ),),
                ),
                ModelResponse("The answer is 42."),
            ],
        )
        coordinator = RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        )
        turn = await coordinator.run_turn("what is the answer?")

        # 1. SessionEvent order.
        self.assertEqual(
            event_types(session.store),
            [
                USER_MESSAGE,
                TURN_START,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                TOOL_CALL,
                TOOL_RESULT,
                STEP_END,
                STEP_START,
                AGENT_REQUEST,
                ASSISTANT_CHUNK,
                ASSISTANT_MESSAGE,
                STEP_END,
                TURN_END,
            ],
        )
        # 2. Tool ownership: Capability C owns Tool T.
        self.assertEqual(runtime.get("lookup").owner, "cap-c")
        # 3. Tool initiator: Agent A caused the execution.
        self.assertEqual(initiators, ["agent-a"])
        # 4. Tool call/result lineage.
        call_ev = next(e for e in session.store.events() if e.event_type == TOOL_CALL)
        result_ev = next(e for e in session.store.events() if e.event_type == TOOL_RESULT)
        self.assertEqual(result_ev.source_event_seqs, (call_ev.seq,))
        self.assertEqual(result_ev.payload["tool_call_id"], call_ev.payload["call_id"])
        # 5. Model-visible messages.
        self.assertEqual(model.seen[1][-1].role, "tool")
        self.assertEqual(model.seen[1][-1].content, "value:42")
        final_msg = next(
            e for e in session.store.events()
            if e.event_type == ASSISTANT_MESSAGE and e.step_id == turn.steps[1].step_id
        )
        self.assertEqual(final_msg.payload["content"], "The answer is 42.")
        self.assertNotIn("chunk text", model.seen[1][0].content)
        # 6. Turn/Step boundaries.
        self.assertEqual(len(turn.steps), 2)
        self.assertEqual({s.turn.turn_id for s in turn.steps}, {turn.turn_id})
        self.assertNotEqual(turn.steps[0].step_id, turn.steps[1].step_id)
        step_end_events = [
            e for e in session.store.events() if e.event_type == STEP_END
        ]
        turn_end_event = next(
            e for e in session.store.events() if e.event_type == TURN_END
        )
        self.assertLess(step_end_events[-1].seq, turn_end_event.seq)
        # 7. Tool Waterfall ordering.
        self.assertEqual(
            hook_log,
            ["pre_execute", "guard", "execute", "post_execute", "finalize"],
        )
        self.assertLess(call_ev.seq, result_ev.seq)

        await manager.unload("cap-c")
        self.assertIsNone(runtime.get("lookup"))


if __name__ == "__main__":
    unittest.main()
