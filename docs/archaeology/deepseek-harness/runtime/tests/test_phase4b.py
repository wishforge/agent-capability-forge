"""Phase 4-B: JSONL persistence, tail repair, reconstruction, replay, resume.

These tests validate the Phase 4-B implementation contract. Physical
durability (fsync), full DSH resume/fork semantics, and TOOL_NOT_STARTED
determination remain assumptions (19-phase4b-assumptions.md), not proven DSH
facts.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
KERNEL = Path(__file__).resolve().parents[3] / "python-cordis" / "kernel"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(KERNEL))

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
from initiator import InitiatorContext  # noqa: E402
from recovery import (  # noqa: E402
    TOOL_NOT_STARTED,
    TOOL_OUTCOME_UNKNOWN,
    find_unresolved_tools,
    rebuild_session,
    repair_interrupted_turn,
    replay,
    resume,
)
from runtime import ModelResponse, ModelToolCall, RuntimeCoordinator  # noqa: E402
from surface import SurfaceProjection  # noqa: E402
from tool_runtime import ToolCall, ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import ACTIVE, ENDED, Session  # noqa: E402


class ScriptedModel:
    """Deterministic fake model: returns a scripted response per step."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.seen: list = []

    async def __call__(self, messages):
        self.seen.append(messages)
        return self.responses.pop(0)


def make_event(
    event_type: str,
    session_id: str = "s1",
    turn_id: str | None = None,
    step_id: str | None = None,
    payload: dict | None = None,
    source: tuple[int, ...] = (),
) -> SessionEvent:
    return SessionEvent(
        0,
        event_type,
        session_id,
        turn_id=turn_id,
        step_id=step_id,
        payload=payload or {},
        source_event_seqs=source,
    )


def interrupted_events(sid: str = "s1") -> list[SessionEvent]:
    """A turn that crashes after tool/call, before tool/result."""
    return [
        make_event(USER_MESSAGE, sid, turn_id="s1/turn-1", payload={"content": "hi"}),
        make_event(TURN_START, sid, turn_id="s1/turn-1"),
        make_event(
            STEP_START,
            sid,
            turn_id="s1/turn-1",
            step_id="s1/turn-1/step-1",
        ),
        make_event(
            AGENT_REQUEST,
            sid,
            turn_id="s1/turn-1",
            step_id="s1/turn-1/step-1",
            payload={"model": "deterministic-fake", "tools": ("lookup",)},
        ),
        make_event(
            ASSISTANT_CHUNK,
            sid,
            turn_id="s1/turn-1",
            step_id="s1/turn-1/step-1",
            payload={"content": "calling lookup"},
        ),
        make_event(
            ASSISTANT_MESSAGE,
            sid,
            turn_id="s1/turn-1",
            step_id="s1/turn-1/step-1",
            payload={
                "content": "calling lookup",
                "tool_calls": [{"id": "c1", "name": "lookup", "arguments": {}}],
            },
        ),
        make_event(
            TOOL_CALL,
            sid,
            turn_id="s1/turn-1",
            step_id="s1/turn-1/step-1",
            payload={"call_id": "c1", "name": "lookup", "arguments": {}},
        ),
    ]


def write_store(path: Path, events: list[SessionEvent], sid: str = "s1") -> EventStore:
    store = EventStore(sid, path=path)
    store.open()
    store.append_many(events)
    store.close()
    return store


class Phase4BPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="phase4b-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_jsonl_append_and_reload(self) -> None:
        path = self.tmp / "s1.jsonl"
        store = EventStore("s1", path=path)
        store.open()
        store.append_many(
            [
                make_event(USER_MESSAGE, payload={"content": "hi"}),
                make_event(TURN_START, turn_id="t1"),
                make_event(STEP_START, turn_id="t1", step_id="t1/s1"),
            ],
        )
        store.close()

        self.assertTrue(path.exists())
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 3)
        reopened = EventStore("s1", path=path)
        reopened.open()
        self.assertEqual(reopened.read_all(), store.events())
        reopened.close()

    def test_sequence_continuity(self) -> None:
        path = self.tmp / "s2.jsonl"
        store = EventStore("s2", path=path)
        store.open()
        stored = store.append_many(
            [
                make_event(USER_MESSAGE, "s2", payload={"i": 0}),
                make_event(USER_MESSAGE, "s2", payload={"i": 1}),
                make_event(USER_MESSAGE, "s2", payload={"i": 2}),
            ],
        )
        self.assertEqual([e.seq for e in stored], [1, 2, 3])
        store.close()

        reopened = EventStore("s2", path=path)
        reopened.open()
        self.assertEqual([e.seq for e in reopened.read_all()], [1, 2, 3])
        self.assertEqual(reopened.last_seq(), 3)
        self.assertEqual([e.seq for e in reopened.read_from(2)], [2, 3])
        fourth = reopened.append(make_event(USER_MESSAGE, "s2", payload={"i": 3}))
        self.assertEqual(fourth.seq, 4)
        reopened.close()

        again = EventStore("s2", path=path)
        again.open()
        self.assertEqual([e.seq for e in again.read_all()], [1, 2, 3, 4])
        again.close()

    def test_append_only(self) -> None:
        path = self.tmp / "s3.jsonl"
        store = EventStore("s3", path=path)
        store.open()
        store.append(make_event(USER_MESSAGE, "s3", payload={"content": "a"}))
        store.append(make_event(TURN_START, "s3", turn_id="t1"))
        first = path.read_bytes()

        store.append(
            make_event(STEP_START, "s3", turn_id="t1", step_id="t1/s1"),
        )
        second = path.read_bytes()

        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.splitlines()), 3)
        # No update/delete surface exists: the log is structurally append-only.
        self.assertFalse(hasattr(store, "update"))
        self.assertFalse(hasattr(store, "delete"))
        store.close()

    def test_partial_tail_repair(self) -> None:
        path = self.tmp / "s4.jsonl"
        store = EventStore("s4", path=path)
        store.open()
        first = store.append(
            make_event(USER_MESSAGE, "s4", payload={"content": "a"}),
        )
        second = store.append(
            make_event(USER_MESSAGE, "s4", payload={"content": "b"}),
        )
        store.close()
        path.write_bytes(path.read_bytes() + b'{"seq":3,"event_type":"user/mess')

        repaired = EventStore("s4", path=path)
        repaired.open()
        self.assertEqual([e.seq for e in repaired.read_all()], [1, 2])
        self.assertTrue(repaired.repair_tail())
        self.assertFalse(repaired.repair_tail())
        appended = repaired.append(
            make_event(USER_MESSAGE, "s4", payload={"content": "c"}),
        )
        self.assertEqual(appended.seq, 3)
        repaired.close()

        again = EventStore("s4", path=path)
        again.open()
        self.assertEqual([e.seq for e in again.read_all()], [1, 2, 3])
        self.assertEqual(again.read_all()[1], second)
        self.assertEqual(again.read_all()[0], first)
        again.close()

    def test_garbled_tail_repair(self) -> None:
        path = self.tmp / "s5.jsonl"
        store = EventStore("s5", path=path)
        store.open()
        store.append(make_event(USER_MESSAGE, "s5", payload={"content": "a"}))
        store.append(make_event(USER_MESSAGE, "s5", payload={"content": "b"}))
        store.close()
        path.write_bytes(path.read_bytes() + b"not-json\n")

        repaired = EventStore("s5", path=path)
        repaired.open()
        self.assertEqual([e.seq for e in repaired.read_all()], [1, 2])
        self.assertTrue(repaired.repair_tail())
        appended = repaired.append(
            make_event(USER_MESSAGE, "s5", payload={"content": "c"}),
        )
        self.assertEqual(appended.seq, 3)
        repaired.close()

        again = EventStore("s5", path=path)
        again.open()
        self.assertEqual([e.seq for e in again.read_all()], [1, 2, 3])
        again.close()

    def test_duplicate_seq_rejected(self) -> None:
        path = self.tmp / "s6.jsonl"
        store = EventStore("s6", path=path)
        store.open()
        store.append(make_event(USER_MESSAGE, "s6", payload={"content": "a"}))

        with self.assertRaises(ValueError):
            store.append(
                SessionEvent(1, USER_MESSAGE, "s6", payload={"content": "dup"}),
            )
        with self.assertRaises(ValueError):
            store.append(
                SessionEvent(9, USER_MESSAGE, "s6", payload={"content": "gap"}),
            )
        accepted = store.append(
            SessionEvent(2, USER_MESSAGE, "s6", payload={"content": "ok"}),
        )
        self.assertEqual(accepted.seq, 2)
        store.close()

    def test_rebuild_session(self) -> None:
        path = self.tmp / "s7.jsonl"
        events = [
            make_event(USER_MESSAGE, turn_id="t1", payload={"content": "hi"}),
            make_event(TURN_START, turn_id="t1"),
            make_event(STEP_START, turn_id="t1", step_id="t1/s1"),
            make_event(
                AGENT_REQUEST,
                turn_id="t1",
                step_id="t1/s1",
                payload={"model": "deterministic-fake", "tools": ("lookup",)},
            ),
            make_event(
                ASSISTANT_MESSAGE,
                turn_id="t1",
                step_id="t1/s1",
                payload={
                    "content": "calling",
                    "tool_calls": [
                        {"id": "c1", "name": "lookup", "arguments": {"q": "x"}},
                    ],
                },
            ),
            make_event(
                TOOL_CALL,
                turn_id="t1",
                step_id="t1/s1",
                payload={"call_id": "c1", "name": "lookup", "arguments": {"q": "x"}},
            ),
            make_event(
                TOOL_RESULT,
                turn_id="t1",
                step_id="t1/s1",
                payload={
                    "tool_call_id": "c1",
                    "content": "value",
                    "is_error": False,
                },
                source=(6,),
            ),
            make_event(STEP_END, turn_id="t1", step_id="t1/s1"),
            make_event(TURN_END, turn_id="t1", payload={"reason": "completed"}),
        ]
        write_store(path, events)

        store = EventStore("s1", path=path)
        store.open()
        session = rebuild_session(store)

        self.assertEqual(session.session_id, "s1")
        self.assertEqual(len(session.turns), 1)
        turn = session.turns[0]
        self.assertEqual(turn.turn_id, "t1")
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(turn.status, ENDED)
        self.assertEqual(len(turn.steps), 1)
        step = turn.steps[0]
        self.assertEqual(step.status, ENDED)
        self.assertEqual(step.tool_calls, [ToolCall("c1", "lookup", {"q": "x"})])
        self.assertEqual(step.request_header["model"], "deterministic-fake")
        store.close()


class Phase4BRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="phase4b-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    async def _completed_store(self, path: Path, sid: str = "s8") -> EventStore:
        store = EventStore(sid, path=path)
        store.open()
        session = Session(sid)
        session.store = store
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration(
                "lookup",
                lambda args, ctx, signal: "value:42",
                owner="cap-c",
            ),
        )
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling lookup",
                    (ModelToolCall("c1", "lookup", {"q": "x"}),),
                ),
                ModelResponse("answer:42"),
            ],
        )
        await RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        ).run_turn("hello")
        return store

    async def test_rebuild_surface(self) -> None:
        path = self.tmp / "s8.jsonl"
        store = EventStore("s8", path=path)
        store.open()
        session = Session("s8")
        session.store = store
        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration(
                "lookup",
                lambda args, ctx, signal: "value:42",
                owner="cap-c",
            ),
        )
        model = ScriptedModel(
            [
                ModelResponse(
                    "calling lookup",
                    (ModelToolCall("c1", "lookup", {"q": "x"}),),
                ),
                ModelResponse("answer:42"),
            ],
        )
        await RuntimeCoordinator(
            session,
            runtime,
            model,
            InitiatorContext("agent-a"),
        ).run_turn("hello")
        messages_a = SurfaceProjection(store).derive_messages()
        store.close()

        reopened = EventStore("s8", path=path)
        reopened.open()
        session_b = rebuild_session(reopened)
        messages_b = SurfaceProjection(reopened).derive_messages()

        self.assertEqual(messages_a, messages_b)
        self.assertEqual(len(session_b.turns), 1)
        self.assertEqual(
            [m.role for m in messages_b],
            ["user", "assistant", "tool", "assistant"],
        )
        reopened.close()

    async def test_replay_history(self) -> None:
        path = self.tmp / "s9.jsonl"
        store = await self._completed_store(path)
        store.close()

        reopened = EventStore("s8", path=path)
        reopened.open()
        history = replay(reopened)

        self.assertEqual(history.session_id, "s8")
        self.assertEqual(len(history.turns), 1)
        turn = history.turns[0]
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(len(turn.steps), 2)
        step0 = turn.steps[0]
        self.assertEqual(step0.request["model"], "deterministic-fake")
        self.assertEqual(len(step0.assistant_messages), 1)
        self.assertEqual(step0.assistant_messages[0]["tool_calls"][0]["id"], "c1")
        self.assertEqual(len(step0.tool_calls), 1)
        self.assertEqual(step0.tool_calls[0]["name"], "lookup")
        self.assertEqual(len(step0.tool_results), 1)
        result = step0.tool_results[0]
        self.assertEqual(result.call_id, "c1")
        self.assertEqual(result.content, "value:42")
        self.assertFalse(result.is_error)
        call_ev = next(
            e for e in reopened.events() if e.event_type == TOOL_CALL
        )
        self.assertEqual(result.source_event_seqs, (call_ev.seq,))
        step1 = turn.steps[1]
        self.assertEqual(step1.tool_calls, ())
        self.assertEqual(step1.assistant_messages[0]["content"], "answer:42")
        reopened.close()

    def test_tool_call_without_result(self) -> None:
        path = self.tmp / "s10.jsonl"
        write_store(path, interrupted_events())

        store = EventStore("s1", path=path)
        store.open()
        unresolved = find_unresolved_tools(store)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, TOOL_OUTCOME_UNKNOWN)
        self.assertNotEqual(unresolved[0].status, TOOL_NOT_STARTED)
        self.assertEqual(unresolved[0].call.payload["call_id"], "c1")
        self.assertEqual(unresolved[0].call.seq, 7)

        session = rebuild_session(store)
        turn = session.turns[0]
        self.assertEqual(turn.status, ACTIVE)
        self.assertEqual(turn.steps[0].status, ACTIVE)
        store.close()

    def test_tool_outcome_unknown_repair(self) -> None:
        path = self.tmp / "s11.jsonl"
        write_store(path, interrupted_events())

        store = EventStore("s1", path=path)
        store.open()
        unresolved = repair_interrupted_turn(store)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, TOOL_OUTCOME_UNKNOWN)

        event_types = [e.event_type for e in store.events()]
        self.assertEqual(event_types[-3:], [TOOL_RESULT, STEP_END, TURN_END])
        result_ev, step_end_ev, turn_end_ev = store.events()[-3:]
        self.assertTrue(result_ev.payload["is_error"])
        self.assertEqual(result_ev.payload["error_code"], TOOL_OUTCOME_UNKNOWN)
        self.assertEqual(result_ev.source_event_seqs, (unresolved[0].call.seq,))
        self.assertEqual(step_end_ev.step_id, "s1/turn-1/step-1")
        self.assertEqual(turn_end_ev.payload["reason"], "interrupted")
        self.assertEqual(find_unresolved_tools(store), ())
        store.close()

        again = EventStore("s1", path=path)
        again.open()
        self.assertEqual(
            [e.event_type for e in again.events()][-3:],
            [TOOL_RESULT, STEP_END, TURN_END],
        )
        session = rebuild_session(again)
        self.assertEqual(session.turns[0].end_reason, "interrupted")
        self.assertEqual(session.turns[0].status, ENDED)
        self.assertEqual(session.turns[0].steps[0].status, ENDED)
        again.close()

    async def test_restart_after_complete_turn(self) -> None:
        path = self.tmp / "s12.jsonl"
        store = await self._completed_store(path)
        messages_a = SurfaceProjection(store).derive_messages()
        last_before = store.last_seq()
        store.close()

        reopened = EventStore("s8", path=path)
        reopened.open()
        self.assertEqual(reopened.last_seq(), last_before)
        messages_b = SurfaceProjection(reopened).derive_messages()
        self.assertEqual(messages_a, messages_b)

        runtime = ToolRuntime()
        runtime.register(
            ToolRegistration(
                "lookup",
                lambda args, ctx, signal: "value:42",
                owner="cap-c",
            ),
        )
        session, unresolved, turn = await resume(
            reopened,
            runtime,
            ScriptedModel([ModelResponse("ok")]),
            InitiatorContext("agent-a"),
            "continue",
        )
        self.assertEqual(unresolved, ())
        self.assertEqual(len(session.turns), 2)
        self.assertEqual(
            [t.end_reason for t in session.turns],
            ["completed", "completed"],
        )
        self.assertEqual(turn.end_reason, "completed")
        self.assertGreater(reopened.last_seq(), last_before)
        reopened.close()

        again = EventStore("s8", path=path)
        again.open()
        self.assertEqual([e.seq for e in again.read_all()], list(range(1, again.last_seq() + 1)))
        again.close()

    async def test_resume_after_interrupted_turn(self) -> None:
        path = self.tmp / "s13.jsonl"
        write_store(path, interrupted_events())

        executed: list = []

        async def lookup(args, ctx, signal):
            executed.append(args)
            return "should-not-run"

        runtime = ToolRuntime()
        runtime.register(ToolRegistration("lookup", lookup, owner="cap-c"))

        store = EventStore("s1", path=path)
        store.open()
        session, unresolved, turn = await resume(
            store,
            runtime,
            ScriptedModel([ModelResponse("resumed answer")]),
            InitiatorContext("agent-a"),
            "continue",
        )

        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, TOOL_OUTCOME_UNKNOWN)
        self.assertEqual(executed, [])
        self.assertEqual(len(session.turns), 2)
        self.assertEqual(
            [t.end_reason for t in session.turns],
            ["interrupted", "completed"],
        )
        self.assertEqual(turn.turn_id, "s1/turn-2")
        messages = SurfaceProjection(store).derive_messages()
        self.assertEqual(messages[-1].content, "resumed answer")
        self.assertTrue(
            any(
                m.role == "tool" and "outcome unknown" in m.content
                for m in messages
            ),
        )
        store.close()

        again = EventStore("s1", path=path)
        again.open()
        rebuilt = rebuild_session(again)
        self.assertEqual(
            [t.end_reason for t in rebuilt.turns],
            ["interrupted", "completed"],
        )
        again.close()

    async def test_crash_after_each_boundary(self) -> None:
        cuts = {
            "turn/start": 2,
            "step/start": 3,
            "agent/request": 4,
            "assistant/chunk": 5,
            "tool/call": 7,
        }
        for index, (cut, count) in enumerate(cuts.items()):
            with self.subTest(cut=cut):
                path = self.tmp / f"crash-{index}.jsonl"
                write_store(path, interrupted_events()[:count])

                store = EventStore("s1", path=path)
                store.open()
                unresolved = repair_interrupted_turn(store)
                session = rebuild_session(store)
                self.assertEqual(session.turns[-1].end_reason, "interrupted")
                self.assertEqual(session.turns[-1].status, ENDED)
                self.assertTrue(
                    all(s.status == ENDED for s in session.turns[-1].steps),
                )
                self.assertEqual(len(unresolved), 1 if cut == "tool/call" else 0)

                executed: list = []
                runtime = ToolRuntime()
                runtime.register(
                    ToolRegistration(
                        "lookup",
                        lambda args, ctx, signal: (
                            executed.append(args) or "x"
                        ),
                        owner="cap-c",
                    ),
                )
                session2, _, resumed_turn = await resume(
                    store,
                    runtime,
                    ScriptedModel([ModelResponse("final")]),
                    InitiatorContext("agent-a"),
                    "continue",
                )
                self.assertEqual(resumed_turn.end_reason, "completed")
                self.assertEqual(len(session2.turns), 2)
                self.assertEqual(session2.turns[1].end_reason, "completed")
                if cut == "tool/call":
                    self.assertEqual(executed, [])
                store.close()


if __name__ == "__main__":
    unittest.main()
