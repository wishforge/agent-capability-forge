"""Phase 5-J tests: complete ExecutionRecord projection.

Builds real records from the existing deterministic runtimes and fixtures,
then verifies the projected fields and that RULE-01/02/06/07/10 now resolve
instead of staying INCONCLUSIVE. No LLM, no evaluator changes.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from evaluator import evaluate  # noqa: E402
from models import FAIL, PASS, TaskSpecification  # noqa: E402

from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from backend.adapters.codex import CodexAdapter  # noqa: E402
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    EXECUTION_ATTEMPT_END,
    EXECUTION_ATTEMPT_START,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    SessionEvent,
)
from initiator import InitiatorContext  # noqa: E402
from recovery import build_execution_record, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from turn_step import Session  # noqa: E402

from test_evaluator import (  # noqa: E402
    ScriptedAdapter,
    basic_runtime,
    run_agentscope,
    run_codex,
)

SPEC = TaskSpecification(
    task_id="phase5j",
    natural_language_goal="查询库存",
    required_tools=("inventory.lookup",),
)


def finding_map(result) -> dict[str, object]:
    return {finding.rule_id: finding for finding in result.findings}


def _append(
    store: EventStore,
    event_type: str,
    *,
    turn_id: str | None = None,
    step_id: str | None = None,
    payload: dict | None = None,
    source_event_seqs: tuple[int, ...] = (),
) -> None:
    store.append(
        SessionEvent(
            0,
            event_type,
            store.session_id,
            turn_id=turn_id,
            step_id=step_id,
            payload=payload or {},
            source_event_seqs=source_event_seqs,
        ),
    )


def _attempt_log(
    status: str,
    turn_reason: str,
    *,
    with_result: bool = False,
) -> EventStore:
    """Minimal single-step log whose attempt ends with the given status."""
    store = EventStore("s5j-manual")
    _append(store, TURN_START, turn_id="turn-1")
    _append(store, STEP_START, turn_id="turn-1", step_id="step-1")
    attempt = {
        "execution_id": "step-1",
        "attempt_id": "step-1/attempt-1",
        "attempt_number": 1,
        "parent_execution_id": None,
        "reason": "model_request",
        "status": "RUNNING",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    _append(
        store,
        EXECUTION_ATTEMPT_START,
        turn_id="turn-1",
        step_id="step-1",
        payload=attempt,
    )
    _append(
        store,
        TOOL_CALL,
        turn_id="turn-1",
        step_id="step-1",
        payload={"call_id": "t1", "name": "lookup", "arguments": {}},
    )
    if with_result:
        _append(
            store,
            TOOL_RESULT,
            turn_id="turn-1",
            step_id="step-1",
            payload={
                "tool_call_id": "t1",
                "content": "ok",
                "is_error": False,
                "error_code": None,
            },
            source_event_seqs=(4,),
        )
    _append(
        store,
        EXECUTION_ATTEMPT_END,
        turn_id="turn-1",
        step_id="step-1",
        payload={
            **attempt,
            "status": status,
            "ended_at": "2026-01-01T00:00:01+00:00",
        },
    )
    _append(store, STEP_END, turn_id="turn-1", step_id="step-1")
    _append(store, TURN_END, turn_id="turn-1", payload={"reason": turn_reason})
    return store


class ExecutionRecordProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def _success_record(self):
        session = Session("s5j-success")
        agent = AgentRuntime(
            session,
            basic_runtime(),
            ScriptedAdapter(
                [("calling", [("c1", "inventory.lookup", {})]), "done"],
            ),
            InitiatorContext("agent-a"),
        )
        await agent.run_turn("go")
        return build_execution_record(
            session.store,
            next(iter(agent.executions)),
        )

    async def test_tool_result_projected(self) -> None:
        record = await self._success_record()
        self.assertEqual(len(record.tool_results), 1)
        result = record.tool_results[0]
        self.assertEqual(result["call_id"], "c1")
        self.assertEqual(result["tool_call_id"], "c1")
        self.assertEqual(result["content"], "stock:5")
        self.assertFalse(result["is_error"])
        self.assertEqual(result["execution_id"], record.execution_id)
        self.assertEqual(result["step_id"], record.attempts[0].step_id)
        self.assertEqual(result["attempt_id"], record.attempts[0].attempt_id)
        self.assertIn("seq", result)

    async def test_tool_call_result_pairing(self) -> None:
        record = await self._success_record()
        call = record.tools[0]
        result = record.tool_results[0]
        self.assertEqual(result["call_id"], call["call_id"])
        self.assertEqual(result["source_event_seqs"], (call["seq"],))
        self.assertEqual(result["attempt_id"], call["attempt_id"])

    def test_missing_tool_result(self) -> None:
        store = _attempt_log("FAILED", "error")
        record = build_execution_record(store, "step-1")
        self.assertEqual(len(record.tools), 1)
        self.assertEqual(record.tool_results, ())
        self.assertEqual(record.unresolved_tools[0]["call_id"], "t1")
        self.assertEqual(
            record.unresolved_tools[0]["status"],
            "TOOL_OUTCOME_UNKNOWN",
        )
        result = evaluate(record, SPEC)
        self.assertEqual(finding_map(result)["RULE-02"].status, FAIL)

    def test_step_outcome(self) -> None:
        completed = build_execution_record(
            _attempt_log("SUCCEEDED", "completed", with_result=True),
            "step-1",
        )
        self.assertEqual(completed.steps[0]["outcome"], "COMPLETED")
        self.assertTrue(completed.steps[0]["derived"])
        self.assertEqual(
            completed.steps[0]["attempt_ids"],
            ("step-1/attempt-1",),
        )
        failed = build_execution_record(
            _attempt_log("FAILED", "error"),
            "step-1",
        )
        self.assertEqual(failed.steps[0]["outcome"], "FAILED")
        aborted = build_execution_record(
            _attempt_log("ABORTED", "error"),
            "step-1",
        )
        self.assertEqual(aborted.steps[0]["outcome"], "ABORTED")

    def test_turn_outcome(self) -> None:
        record = build_execution_record(
            _attempt_log("SUCCEEDED", "completed", with_result=True),
            "step-1",
        )
        self.assertEqual(record.turn_end_reason, "completed")
        self.assertEqual(record.turn_outcome, "COMPLETED")
        turn = record.turns[0]
        self.assertEqual(turn["turn_id"], "turn-1")
        self.assertEqual(turn["end_reason"], "completed")
        self.assertEqual(turn["outcome"], "COMPLETED")
        self.assertEqual(len(turn["event_refs"]), 2)

    def test_execution_outcome(self) -> None:
        record = build_execution_record(
            _attempt_log("SUCCEEDED", "completed", with_result=True),
            "step-1",
        )
        outcome = record.execution_outcome
        self.assertEqual(outcome["status"], "SUCCESS")
        self.assertTrue(outcome["derived"])
        self.assertIn("step-1/attempt-1:SUCCEEDED", outcome["basis"])

    def test_replay_ref(self) -> None:
        record = build_execution_record(
            _attempt_log("SUCCEEDED", "completed", with_result=True),
            "step-1",
        )
        ref = record.replay_ref
        self.assertEqual(ref["session_id"], "s5j-manual")
        self.assertEqual(ref["execution_id"], "step-1")
        self.assertEqual(ref["record_version"], "5j.1")
        self.assertEqual(ref["projection_rule_version"], "v2")
        self.assertEqual(ref["event_range"], [1, 8])

    async def test_replay_projection_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5j-") as td:
            path = Path(td) / "record.jsonl"
            store = EventStore("s5j-stable", path=path)
            store.open()
            session = Session("s5j-stable")
            session.store = store
            agent = AgentRuntime(
                session,
                basic_runtime(),
                ScriptedAdapter(
                    [("calling", [("c1", "inventory.lookup", {})]), "done"],
                ),
                InitiatorContext("agent-a"),
            )
            await agent.run_turn("go")
            execution_id = next(iter(agent.executions))
            record_a = build_execution_record(store, execution_id)
            store.close()

            reopened = EventStore("s5j-stable", path=path)
            reopened.open()
            replay(reopened)
            record_b = build_execution_record(reopened, execution_id)
            reopened.close()

        self.assertIsNot(record_a, record_b)
        for field in (
            "execution_id",
            "session_id",
            "turn_end_reason",
            "turn_outcome",
            "replay_ref",
            "execution_outcome",
            "tools",
            "tool_results",
            "unresolved_tools",
            "steps",
            "turns",
            "lossiness",
        ):
            self.assertEqual(
                getattr(record_a, field),
                getattr(record_b, field),
                field,
            )
        self.assertEqual(
            [attempt.attempt_id for attempt in record_a.attempts],
            [attempt.attempt_id for attempt in record_b.attempts],
        )
        self.assertEqual(
            [attempt.status for attempt in record_a.attempts],
            [attempt.status for attempt in record_b.attempts],
        )

    async def test_agent_scope_execution_record(self) -> None:
        record = await run_agentscope()
        self.assertTrue(record.tools)
        self.assertTrue(record.tool_results)
        self.assertEqual(record.turn_end_reason, "completed")
        self.assertEqual(record.steps[0]["outcome"], "COMPLETED")
        self.assertEqual(record.execution_outcome["status"], "SUCCESS")
        self.assertTrue(record.replay_ref)
        self.assertEqual(
            record.tool_results[0]["call_id"],
            record.tools[0]["call_id"],
        )

    async def test_codex_execution_record(self) -> None:
        record = await run_codex()
        self.assertEqual(record.tools[0]["name"], "inventory.lookup")
        self.assertEqual(
            record.tools[0]["backend_event_ref"]["backend"],
            "codex",
        )
        self.assertEqual(record.tools[0]["attempt_id"], record.attempts[0].attempt_id)
        self.assertTrue(record.tool_results)
        self.assertEqual(record.turn_end_reason, "completed")
        self.assertEqual(record.steps[0]["outcome"], "COMPLETED")
        self.assertTrue(record.replay_ref)
        self.assertTrue(record.lossiness)

    async def _assert_rules_resolved(self, record) -> None:
        result = evaluate(record, SPEC)
        findings = finding_map(result)
        for rule_id in (
            "RULE-01",
            "RULE-02",
            "RULE-06",
            "RULE-07",
            "RULE-10",
        ):
            self.assertEqual(findings[rule_id].status, PASS, rule_id)

    async def test_evaluation_rule_01_now_resolvable(self) -> None:
        await self._assert_rules_resolved(await run_agentscope())
        await self._assert_rules_resolved(await run_codex())

    async def test_evaluation_rule_02_now_resolvable(self) -> None:
        await self._assert_rules_resolved(await run_agentscope())
        await self._assert_rules_resolved(await run_codex())

    async def test_evaluation_rule_06_now_resolvable(self) -> None:
        await self._assert_rules_resolved(await run_agentscope())
        await self._assert_rules_resolved(await run_codex())

    async def test_evaluation_rule_07_now_resolvable(self) -> None:
        await self._assert_rules_resolved(await run_agentscope())
        await self._assert_rules_resolved(await run_codex())

    async def test_evaluation_rule_10_now_resolvable(self) -> None:
        await self._assert_rules_resolved(await run_agentscope())
        await self._assert_rules_resolved(await run_codex())


if __name__ == "__main__":
    unittest.main()
