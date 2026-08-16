"""Phase 4-C: context projection + compaction tests.

Contract: 21-context-compaction-contract.md / 22-context-compaction-requirements.md.
Token counts are PHASE-4C ESTIMATION; summaries are PHASE-4C TEST SUMMARIZER.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

import compaction  # noqa: E402
from compaction import (  # noqa: E402
    COMPACTION_END,
    COMPACTION_PRUNE,
    COMPACTION_START,
    COMPACTION_SUMMARY,
    CONTEXT_WINDOW_EXCEEDED,
    FAILED,
    NO_RETRY,
    RETRY,
    CompactionEngine,
    CompactionError,
    CompactionPlan,
    ModelContext,
    TokenEstimate,
    TokenMeter,
    build_model_context,
    prune_tool_result,
    retry_safe,
)
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    ASSISTANT_MESSAGE,
    REQUEST_HEADER,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)
from surface import Message, SurfaceProjection  # noqa: E402
from tool_runtime import ToolCall, ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import ExecutionContext, Session, Turn  # noqa: E402


def make_surface_store(
    sid: str = "s1",
    count: int = 8,
    content: str = "x" * 80,
) -> EventStore:
    store = EventStore(sid)
    events: list[SessionEvent] = []
    for i in range(count):
        events.append(
            SessionEvent(
                0,
                USER_MESSAGE,
                sid,
                payload={"content": f"user {i}: {content}"},
            ),
        )
        events.append(
            SessionEvent(
                0,
                ASSISTANT_MESSAGE,
                sid,
                payload={"content": f"assistant {i}: {content}", "tool_calls": []},
            ),
        )
    store.append_many(events)
    return store


def make_engine(store: EventStore, **kw) -> CompactionEngine:
    kw.setdefault("context_window", 200)
    kw.setdefault("threshold_ratio", 0.5)
    kw.setdefault("retain_ratio", 0.2)
    return CompactionEngine(store, TokenMeter(**kw))


def with_request_header(store: EventStore) -> EventStore:
    store.append(
        SessionEvent(
            0,
            REQUEST_HEADER,
            store.session_id,
            payload={"model": "deterministic-test"},
        ),
    )
    return store


class Phase4CTokenMeterTests(unittest.TestCase):
    def test_token_meter(self) -> None:
        meter = TokenMeter(
            context_window=1000,
            threshold_ratio=0.8,
            retain_ratio=0.16,
        )
        estimate = meter.estimate(
            (Message("user", "a" * 100),),
            system="s" * 100,
            tools=("a", "b"),
        )
        self.assertEqual(estimate.system_tokens, 29)
        self.assertEqual(estimate.message_tokens, 29)
        self.assertEqual(estimate.tools_tokens, 7)
        self.assertEqual(estimate.total_tokens, 65)
        self.assertEqual(meter.threshold_tokens(), 800)
        self.assertEqual(meter.retain_tokens_for(), 160)
        self.assertTrue(meter.pressure(TokenEstimate(0, 0, 800)))
        self.assertFalse(meter.pressure(TokenEstimate(0, 0, 799)))

    def test_explicit_retain_tokens_wins(self) -> None:
        meter = TokenMeter(1000, retain_ratio=0.16, retain_tokens=99)
        self.assertEqual(meter.retain_tokens_for(), 99)


class Phase4CCompactionTests(unittest.TestCase):
    def test_pressure_trigger(self) -> None:
        store = make_surface_store("pressure")
        engine = make_engine(store)
        before = len(store.events())
        decision = engine.maybe_compact()
        self.assertEqual(decision.kind, NO_RETRY)
        self.assertEqual(decision.reason, "compacted")
        self.assertEqual(len(store.events()), before + 4)
        types = [e.event_type for e in store.events()]
        self.assertEqual(types[-4:], [
            COMPACTION_START,
            COMPACTION_SUMMARY,
            USER_MESSAGE,
            COMPACTION_END,
        ])
        messages = SurfaceProjection(store).derive_messages()
        self.assertLess(len(messages), 16)
        self.assertIn("compacted-summary", messages[-1].content)

    def test_overflow_trigger(self) -> None:
        store = with_request_header(make_surface_store("overflow"))
        engine = CompactionEngine(
            store,
            TokenMeter(context_window=10000),
            max_overflow_retries=1,
        )
        decision = engine.handle_request_error(CONTEXT_WINDOW_EXCEEDED)
        self.assertEqual(decision.kind, RETRY)
        self.assertEqual(decision.replace_generation, 1)
        self.assertEqual(engine.overflow_retries, 1)
        self.assertIn(
            "compacted-summary",
            SurfaceProjection(store).derive_messages()[-1].content,
        )

        again = engine.handle_request_error(CONTEXT_WINDOW_EXCEEDED)
        self.assertEqual(again.kind, NO_RETRY)
        self.assertEqual(again.reason, "max_overflow_retries")

    def test_overflow_trigger_ignores_other_errors(self) -> None:
        store = with_request_header(make_surface_store("other"))
        engine = CompactionEngine(store, TokenMeter(context_window=10000))
        decision = engine.handle_request_error("RATE_LIMITED")
        self.assertEqual(decision.kind, NO_RETRY)
        self.assertEqual(decision.reason, "not_overflow")

    def test_compaction_plan_and_replacement(self) -> None:
        store = make_surface_store("plan")
        engine = make_engine(store)
        plan = engine.plan(reason="pressure")
        self.assertIsInstance(plan, CompactionPlan)
        self.assertLess(plan.start, plan.end)
        self.assertIsNotNone(plan.retained_range)
        self.assertGreater(plan.token_before, plan.token_after)
        self.assertEqual(plan.replace_generation, 1)
        self.assertTrue(plan.source_event_seqs)

        decision = engine.compact(reason="pressure")
        self.assertEqual(decision.kind, NO_RETRY)
        replacement = next(
            e
            for e in store.events()
            if e.event_type == USER_MESSAGE and e.surface_op is not None
        )
        self.assertEqual(replacement.surface_op["op"], "replace")
        self.assertEqual(replacement.surface_op["start"], plan.start)
        self.assertEqual(replacement.surface_op["end"], plan.end)
        self.assertEqual(
            replacement.payload["source"],
            {
                "kind": "plugin",
                "plugin": "compact",
                "compaction_id": "plan/compact-1",
            },
        )
        self.assertTrue(
            set(plan.source_event_seqs).issubset(
                set(replacement.source_event_seqs),
            ),
        )
        self.assertEqual(
            replacement.payload["content"],
            plan.summary_content,
        )

    def test_original_events_preserved(self) -> None:
        store = make_surface_store("preserve")
        original = store.events()
        engine = make_engine(store)
        engine.compact(reason="pressure")
        events = store.events()
        self.assertEqual(len(events), len(original) + 4)
        self.assertEqual(events[: len(original)], original)

    def test_surface_rebuild_after_compaction(self) -> None:
        store = make_surface_store("rebuild")
        engine = make_engine(store)
        plan = engine.plan(reason="pressure")
        assert plan is not None and plan.retained_range is not None
        engine.compact(reason="pressure")
        messages = SurfaceProjection(store).derive_messages()
        self.assertEqual(messages[-1].role, "user")
        self.assertEqual(messages[-1].content, plan.summary_content)
        retained = [
            e
            for e in store.events()
            if plan.retained_range[0] <= e.seq <= plan.retained_range[1]
        ]
        self.assertEqual(
            [m.content for m in messages[:-1]],
            [m.content for m in _messages_from_events(tuple(retained))],
        )

    def test_derive_messages_after_compaction(self) -> None:
        store = make_surface_store("derive")
        first_original = store.events()[0].payload["content"]
        engine = make_engine(store)
        engine.compact(reason="pressure")
        messages = SurfaceProjection(store).derive_messages()
        contents = [m.content for m in messages]
        self.assertNotIn(first_original, contents)
        self.assertTrue(any("compacted-summary" in c for c in contents))

    def test_compaction_idempotent_generation(self) -> None:
        store = make_surface_store("idem")
        engine = make_engine(store)
        first = engine.compact(reason="pressure")
        self.assertEqual(first.replace_generation, 1)
        count = len(store.events())
        second = engine.compact(reason="pressure")
        self.assertEqual(second.kind, NO_RETRY)
        self.assertEqual(second.reason, "no_pressure")
        self.assertEqual(len(store.events()), count)

    def test_compaction_busy(self) -> None:
        store = make_surface_store("busy")
        engine = make_engine(store)
        compaction._SESSION_BUSY.add(store.session_id)
        try:
            with self.assertRaises(CompactionError) as cm:
                engine.compact(reason="pressure")
            self.assertEqual(cm.exception.category, "busy")
        finally:
            compaction._SESSION_BUSY.discard(store.session_id)

    def test_compaction_cancelled(self) -> None:
        store = make_surface_store("cancel")
        engine = make_engine(store)
        before = len(store.events())
        engine.cancel()
        decision = engine.compact(reason="pressure")
        self.assertEqual(decision.kind, NO_RETRY)
        self.assertEqual(decision.reason, "cancelled")
        self.assertEqual(len(store.events()), before)

    def test_compaction_retry(self) -> None:
        store = with_request_header(make_surface_store("retry"))
        session = Session("retry")
        session.store = store
        engine = CompactionEngine(store, TokenMeter(context_window=10000))
        decision = engine.handle_request_error(CONTEXT_WINDOW_EXCEEDED)
        self.assertEqual(decision.kind, RETRY)
        context = build_model_context(session)
        self.assertIn("compacted-summary", context.messages[-1].content)

    def test_retry_not_allowed_after_tool_side_effect(self) -> None:
        store = make_surface_store("unsafe")
        with_request_header(store)
        store.append(
            SessionEvent(
                0,
                ASSISTANT_MESSAGE,
                store.session_id,
                payload={"content": "committed", "tool_calls": []},
            ),
        )
        self.assertFalse(retry_safe(store))

        store2 = make_surface_store("unsafe2")
        with_request_header(store2)
        store2.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                store2.session_id,
                payload={"tool_call_id": "c1", "content": "ran", "is_error": False},
                source_event_seqs=(1,),
            ),
        )
        engine2 = CompactionEngine(store2, TokenMeter(context_window=10000))
        decision = engine2.handle_request_error(CONTEXT_WINDOW_EXCEEDED)
        self.assertEqual(decision.kind, NO_RETRY)
        self.assertEqual(decision.reason, "retry_not_safe")

        store3 = with_request_header(make_surface_store("safe"))
        self.assertTrue(retry_safe(store3))

    def test_compaction_failure_preserves_history(self) -> None:
        store = make_surface_store("summary-fail")
        before = store.events()

        def boom(shadowed, max_chars):
            raise RuntimeError("summarizer down")

        engine = CompactionEngine(
            store,
            TokenMeter(context_window=200, threshold_ratio=0.5),
            summarizer=boom,
        )
        with self.assertRaises(CompactionError) as cm:
            engine.compact(reason="pressure")
        self.assertEqual(cm.exception.category, "summary")
        self.assertEqual(store.events(), before)
        self.assertEqual(engine._generation, 0)

        failing = FailAtReplacementStore("commit-fail")
        failing.append_many(
            list(make_surface_store("commit-fail").events()),
        )
        commit_before = failing.events()
        engine2 = make_engine(failing)
        with self.assertRaises(CompactionError) as cm2:
            engine2.compact(reason="pressure")
        self.assertEqual(cm2.exception.category, "commit")
        events = failing.events()
        self.assertEqual(events[: len(commit_before)], commit_before)
        self.assertEqual(events[-1].event_type, COMPACTION_END)
        self.assertEqual(events[-1].payload["error"], "commit")
        self.assertFalse(
            any(
                e.event_type == USER_MESSAGE and e.surface_op is not None
                for e in events
            ),
        )
        self.assertEqual(
            SurfaceProjection(failing).derive_messages(),
            SurfaceProjection(
                _store_from_events("commit-fail", commit_before),
            ).derive_messages(),
        )

        flaky = FailFlushStore("flush-fail")
        flaky.append_many(
            list(make_surface_store("flush-fail").events()),
        )
        engine3 = make_engine(flaky)
        with self.assertRaises(CompactionError) as cm3:
            engine3.compact(reason="pressure")
        self.assertEqual(cm3.exception.category, "persistence")
        self.assertEqual(flaky.events()[-1].event_type, COMPACTION_END)
        self.assertIn(
            "compacted-summary",
            SurfaceProjection(flaky).derive_messages()[-1].content,
        )


class Phase4CPruningTests(unittest.TestCase):
    def test_tool_result_pruning(self) -> None:
        store = _tool_result_store("prune")
        long_content = store.events()[-1].payload["content"]
        replacement = prune_tool_result(store, store.last_seq())
        self.assertIsNotNone(replacement)
        messages = SurfaceProjection(store).derive_messages()
        pruned = messages[-1].content
        self.assertTrue(pruned.startswith(long_content[:80]))
        self.assertTrue(pruned.endswith(long_content[-20:]))
        self.assertIn("pruned", pruned)
        self.assertLess(len(pruned), len(long_content))

    def test_pruning_preserves_source_event(self) -> None:
        store = _tool_result_store("lineage")
        original_seq = store.last_seq()
        original = store.events()[-1]
        replacement = prune_tool_result(store, original_seq)
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.source_event_seqs, (original_seq,))
        self.assertEqual(replacement.surface_op["op"], "replace")
        self.assertEqual(store.events()[original_seq - 1], original)
        self.assertEqual(
            store.events()[original_seq - 1].payload["content"],
            original.payload["content"],
        )
        self.assertTrue(
            any(e.event_type == COMPACTION_PRUNE for e in store.events()),
        )

    def test_pruning_short_result_is_noop(self) -> None:
        store = EventStore("short")
        store.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                "short",
                payload={"tool_call_id": "c1", "content": "tiny", "is_error": False},
            ),
        )
        self.assertIsNone(prune_tool_result(store, 1))
        self.assertEqual(len(store.events()), 1)


class Phase4CRestartTests(unittest.TestCase):
    def test_restart_rebuild_same_compacted_surface(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase4c-") as td:
            tmp = Path(td)
            base = make_surface_store("restart").events()

            path_a = tmp / "compact-before-restart.jsonl"
            store_a = EventStore("restart", path=path_a)
            store_a.open()
            store_a.append_many(base)
            make_engine(store_a).compact(reason="pressure")
            messages_a = SurfaceProjection(store_a).derive_messages()
            events_a = store_a.events()
            store_a.close()

            reopened = EventStore("restart", path=path_a)
            reopened.open()
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                messages_a,
            )
            self.assertEqual(
                [e.event_type for e in reopened.events()],
                [e.event_type for e in events_a],
            )
            reopened.close()

            path_b = tmp / "compact-after-restart.jsonl"
            store_b = EventStore("restart", path=path_b)
            store_b.open()
            store_b.append_many(base)
            store_b.close()
            store_b2 = EventStore("restart", path=path_b)
            store_b2.open()
            make_engine(store_b2).compact(reason="pressure")
            messages_b = SurfaceProjection(store_b2).derive_messages()
            events_b = store_b2.events()
            store_b2.close()

            self.assertEqual(messages_a, messages_b)
            self.assertEqual(
                [e.event_type for e in events_a],
                [e.event_type for e in events_b],
            )


class Phase4CBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_state_not_in_model_context(self) -> None:
        runtime = ToolRuntime()

        class SecretCapability:
            async def install(self) -> None:
                self.state = "capability-private-state"
                runtime.register(
                    ToolRegistration(
                        "lookup",
                        lambda args, ctx, signal: "tool-output-visible",
                        owner="cap-c",
                    ),
                )

            async def dispose(self) -> None:
                runtime.unregister("lookup")
                self.state = "capability-disposed-state"

        cap = SecretCapability()
        await cap.install()
        session = Session("cap")
        turn = Turn("t1", session)
        turn.begin()
        step = turn.new_step()
        step.begin()
        ctx = ExecutionContext(session, turn, step)

        self.assertEqual(session.store.events(), ())
        result = await runtime.execute(ToolCall("c1", "lookup", {}), ctx)
        self.assertFalse(result.is_error)
        self.assertEqual(
            [e.event_type for e in session.store.events()],
            [TOOL_CALL, TOOL_RESULT],
        )

        context = build_model_context(
            session,
            system_prompt="system prompt",
            tools=runtime.names(),
            runtime_context="runtime context",
            current_input="current input",
        )
        self.assertIsInstance(context, ModelContext)
        self.assertEqual(context.tools, ("lookup",))
        contents = [m.content for m in context.messages]
        self.assertNotIn(cap.state, contents)
        self.assertNotIn("capability-private-state", contents)
        self.assertNotIn(cap.state, context.runtime_context)
        self.assertEqual(context.messages[-1].content, "tool-output-visible")

        await cap.dispose()
        self.assertEqual(
            [e.event_type for e in session.store.events()],
            [TOOL_CALL, TOOL_RESULT],
        )
        self.assertNotIn(cap.state, contents)


class FailAtReplacementStore(EventStore):
    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self._armed = True

    def append(self, event: SessionEvent) -> SessionEvent:
        if (
            self._armed
            and event.event_type == USER_MESSAGE
            and event.surface_op is not None
            and event.surface_op.get("op") == "replace"
        ):
            self._armed = False
            raise IOError("injected append failure")
        return super().append(event)


class FailFlushStore(EventStore):
    def flush(self) -> None:
        raise IOError("injected flush failure")


def _tool_result_store(sid: str) -> EventStore:
    store = EventStore(sid)
    store.append_many(
        [
            SessionEvent(
                0,
                TOOL_CALL,
                sid,
                payload={"call_id": "c1", "name": "lookup", "arguments": {}},
            ),
            SessionEvent(
                0,
                TOOL_RESULT,
                sid,
                payload={
                    "tool_call_id": "c1",
                    "content": "L" * 200,
                    "is_error": False,
                    "error_code": None,
                },
                source_event_seqs=(1,),
            ),
        ],
    )
    return store


def _messages_from_events(events: tuple[SessionEvent, ...]) -> tuple[Message, ...]:
    messages: list[Message] = []
    for event in events:
        if event.event_type == USER_MESSAGE:
            messages.append(Message("user", event.payload["content"]))
        elif event.event_type == ASSISTANT_MESSAGE:
            messages.append(
                Message(
                    "assistant",
                    event.payload.get("content", ""),
                    tool_calls=tuple(event.payload.get("tool_calls", ())),
                ),
            )
        elif event.event_type == TOOL_RESULT:
            messages.append(
                Message(
                    "tool",
                    event.payload["content"],
                    tool_call_id=event.payload["tool_call_id"],
                ),
            )
    return tuple(messages)


def _store_from_events(sid: str, events: tuple[SessionEvent, ...]) -> EventStore:
    store = EventStore(sid)
    store.append_many(list(events))
    return store


if __name__ == "__main__":
    unittest.main()
