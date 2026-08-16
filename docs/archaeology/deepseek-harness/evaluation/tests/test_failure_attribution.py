"""Phase 5-K tests: deterministic Failure Attribution layer.

Pure deterministic attribution over ExecutionRecord + EvaluationResult.
No LLM, no runtime mutation, no RCA.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TESTS = Path(__file__).resolve().parent
FIXTURES = RUNTIME / "tests" / "fixtures"
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from evaluator import evaluate  # noqa: E402
from failure_attribution import (  # noqa: E402
    EXECUTION_ABORTED,
    MODEL_FAILURE,
    MULTIPLE_CANDIDATES,
    STEP_FAILURE,
    TIMEOUT,
    TOOL_FAILURE,
    TURN_FAILURE,
    UNRESOLVED_TOOL,
    UNSAFE_RETRY,
    attribute,
)
from golden import TASK_02, TASK_02_RECORD, TASK_03, TASK_03_RECORD, _record  # noqa: E402
from models import TaskSpecification  # noqa: E402

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
from model_adapter import ModelRequestError  # noqa: E402
from recovery import build_execution_record, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from turn_step import Session  # noqa: E402

from test_evaluator import (  # noqa: E402
    DeterministicAgentScopeModel,
    basic_runtime,
)

SPEC_TOOL = TaskSpecification(
    task_id="s5k-tool",
    natural_language_goal="调用必选工具并成功。",
    required_tools=("inventory.lookup",),
)
SPEC_NONE = TaskSpecification(
    task_id="s5k-none",
    natural_language_goal="无必选工具。",
)

DEFAULT_INITIATOR = {
    "ref": "agent-a",
    "source": "ADAPTER_DERIVED",
    "parent_ref": None,
}
DEFAULT_PROVENANCE = {
    "request_ref": 3,
    "source_event_refs": (1,),
    "surface_refs": (1,),
    "current_input_ref": 1,
    "runtime_context_ref": None,
    "quality": "PARTIAL",
    "missing_semantics": ("SYSTEM_PROMPT_SNAPSHOT",),
}


def _plain(obj):
    """Canonicalize dataclasses/dicts/tuples for replay-equality comparison."""
    if isinstance(obj, dict):
        return {key: _plain(value) for key, value in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_plain(value) for value in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return _plain(
            {
                name: _plain(getattr(obj, name))
                for name in obj.__dataclass_fields__
            },
        )
    return obj


def _append(
    store: EventStore,
    event_type: str,
    *,
    turn_id: str = "turn-1",
    step_id: str = "step-1",
    payload: dict | None = None,
    source_event_seqs: tuple[int, ...] = (),
) -> SessionEvent:
    return store.append(
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


def _log(
    *,
    turn_reason: str = "completed",
    attempt_status: str = "SUCCEEDED",
    attempt_reason: str = "model_request",
    attempt_error: str | None = None,
    calls: tuple[dict, ...] = (),
    results: tuple[dict, ...] = (),
    path: Path | None = None,
) -> EventStore:
    store = (
        EventStore("s5k-failure", path=path)
        if path is not None
        else EventStore("s5k-failure")
    )
    if path is not None:
        store.open()
    _append(store, TURN_START)
    _append(store, STEP_START)
    attempt = {
        "execution_id": "step-1",
        "attempt_id": "step-1/attempt-1",
        "attempt_number": 1,
        "parent_execution_id": None,
        "reason": attempt_reason,
        "status": "RUNNING",
        "started_at": "2026-01-01T00:00:00+00:00",
        "initiator_ref": DEFAULT_INITIATOR,
        "context_provenance": DEFAULT_PROVENANCE,
    }
    _append(store, EXECUTION_ATTEMPT_START, payload=attempt)
    call_seqs = {}
    for call in calls:
        event = _append(store, TOOL_CALL, payload=dict(call))
        call_seqs[call["call_id"]] = event.seq
    for result in results:
        _append(
            store,
            TOOL_RESULT,
            payload=dict(result),
            source_event_seqs=(call_seqs[result["tool_call_id"]],),
        )
    _append(
        store,
        EXECUTION_ATTEMPT_END,
        payload={
            **attempt,
            "status": attempt_status,
            "reason": attempt_reason,
            "error": attempt_error,
            "ended_at": "2026-01-01T00:00:01+00:00",
        },
    )
    _append(store, STEP_END)
    _append(store, TURN_END, payload={"reason": turn_reason})
    return store


class FailureAttributionTests(unittest.TestCase):
    def test_tool_failure_attribution(self) -> None:
        store = _log(
            calls=(
                {
                    "call_id": "t1",
                    "name": "inventory.lookup",
                    "arguments": {"sku": "A"},
                    "owner_ref": {"owner_type": "capability", "owner_id": "cap-c"},
                },
            ),
            results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        record = build_execution_record(store, "step-1")
        attr = attribute(record, evaluate(record, SPEC_TOOL))
        self.assertEqual(attr.failure_kind, TOOL_FAILURE)
        self.assertEqual(attr.execution_id, "step-1")
        self.assertEqual(attr.turn_id, "turn-1")
        self.assertEqual(attr.step_id, "step-1")
        self.assertEqual(attr.attempt_id, "step-1/attempt-1")
        self.assertEqual(attr.primary_failure.rule_id, "RULE-06")
        self.assertTrue(
            any(ref.get("tool_call_id") == "t1" for ref in attr.evidence_refs)
        )

    def test_timeout_attribution(self) -> None:
        store = _log(
            calls=({"call_id": "t1", "name": "lookup", "arguments": {}},),
            results=(
                {
                    "tool_call_id": "t1",
                    "content": "slow",
                    "is_error": True,
                    "error_code": "TOOL_TIMEOUT",
                },
            ),
        )
        record = build_execution_record(store, "step-1")
        attr = attribute(record, evaluate(record, SPEC_NONE))
        self.assertEqual(attr.failure_kind, TIMEOUT)
        self.assertEqual(attr.primary_failure.rule_id, "RULE-07")
        self.assertEqual(attr.attempt_id, "step-1/attempt-1")

    def test_unresolved_tool_attribution(self) -> None:
        store = _log(
            calls=({"call_id": "t1", "name": "lookup", "arguments": {}},),
        )
        record = build_execution_record(store, "step-1")
        attr = attribute(record, evaluate(record, SPEC_NONE))
        self.assertEqual(attr.failure_kind, UNRESOLVED_TOOL)
        self.assertEqual(attr.primary_failure.rule_id, "RULE-02")
        self.assertEqual(attr.attempt_id, "step-1/attempt-1")
        self.assertTrue(
            any(ref.get("tool_call_id") == "t1" for ref in attr.evidence_refs)
        )

    def test_unsafe_retry_attribution(self) -> None:
        result = evaluate(TASK_03_RECORD, TASK_03)
        attr = attribute(TASK_03_RECORD, result)
        self.assertEqual(attr.failure_kind, UNSAFE_RETRY)
        self.assertEqual(attr.primary_failure.rule_id, "RULE-03")
        self.assertEqual(attr.attempt_id, "exec-1/attempt-2")
        self.assertEqual(attr.step_id, "step-1")

    def test_attempt_failure_attribution(self) -> None:
        record = _record(
            turns=(
                {
                    "turn_id": "turn-1",
                    "end_reason": "completed",
                    "outcome": "COMPLETED",
                    "derived": True,
                },
            ),
            attempts=(
                SimpleNamespace(
                    execution_id="exec-1",
                    attempt_id="exec-1/attempt-1",
                    attempt_number=1,
                    parent_execution_id=None,
                    reason="model_request",
                    status="ABORTED",
                    step_id="step-1",
                ),
            ),
            turn_end_reason="completed",
        )
        attr = attribute(record, evaluate(record, SPEC_NONE))
        self.assertEqual(attr.failure_kind, EXECUTION_ABORTED)
        self.assertEqual(attr.primary_failure.rule_id, "RULE-08")
        self.assertEqual(attr.attempt_id, "exec-1/attempt-1")
        self.assertEqual(attr.step_id, "step-1")

    def test_step_failure_attribution(self) -> None:
        record = _record(
            turns=(
                {
                    "turn_id": "turn-1",
                    "end_reason": "error",
                    "outcome": "FAILED",
                    "derived": True,
                },
            ),
            steps=(
                {
                    "step_id": "step-1",
                    "turn_id": "turn-1",
                    "outcome": "FAILED",
                    "derived": True,
                    "attempt_ids": ("exec-1/attempt-1",),
                },
            ),
            attempts=(
                SimpleNamespace(
                    execution_id="exec-1",
                    attempt_id="exec-1/attempt-1",
                    attempt_number=1,
                    parent_execution_id=None,
                    reason="model_request",
                    status="FAILED",
                    step_id="step-1",
                ),
            ),
            turn_end_reason="error",
        )
        attr = attribute(record, evaluate(record, SPEC_NONE))
        self.assertEqual(attr.failure_kind, STEP_FAILURE)
        self.assertEqual(attr.step_id, "step-1")
        self.assertEqual(attr.attempt_id, "exec-1/attempt-1")
        self.assertEqual(attr.primary_failure.rule_id, "RULE-08")
        self.assertIn(
            TURN_FAILURE,
            {failure.failure_kind for failure in attr.secondary_failures},
        )

    def test_turn_failure_attribution(self) -> None:
        record = _record(
            turns=(
                {
                    "turn_id": "turn-1",
                    "end_reason": "interrupted",
                    "outcome": "ABORTED",
                    "derived": True,
                },
            ),
            steps=(
                {
                    "step_id": "step-1",
                    "turn_id": "turn-1",
                    "outcome": "COMPLETED",
                    "derived": True,
                    "attempt_ids": ("exec-1/attempt-1",),
                },
            ),
            attempts=(
                SimpleNamespace(
                    execution_id="exec-1",
                    attempt_id="exec-1/attempt-1",
                    attempt_number=1,
                    parent_execution_id=None,
                    reason="model_request",
                    status="SUCCEEDED",
                    step_id="step-1",
                ),
            ),
            turn_end_reason="interrupted",
        )
        attr = attribute(record, evaluate(record, SPEC_NONE))
        self.assertEqual(attr.failure_kind, TURN_FAILURE)
        self.assertEqual(attr.primary_failure.rule_id, "RULE-01")
        self.assertEqual(attr.turn_id, "turn-1")

    def test_initiator_attribution(self) -> None:
        attr = attribute(TASK_02_RECORD, evaluate(TASK_02_RECORD, TASK_02))
        self.assertEqual(attr.initiator_ref["ref"], "agent-a")
        self.assertNotEqual(attr.initiator_ref["ref"], attr.owner_ref["owner_id"])

    def test_owner_attribution(self) -> None:
        attr = attribute(TASK_02_RECORD, evaluate(TASK_02_RECORD, TASK_02))
        self.assertEqual(
            attr.owner_ref,
            {"owner_type": "capability", "owner_id": "cap-c"},
        )
        missing = _record(
            owner_refs=(),
            initiator_ref=DEFAULT_INITIATOR,
            tools=({"call_id": "t2", "name": "lookup", "arguments": {}},),
            tool_results=(
                {
                    "tool_call_id": "t2",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        attr_missing = attribute(missing, evaluate(missing, TASK_02))
        self.assertIsNone(attr_missing.owner_ref)
        self.assertEqual(attr_missing.ownership, "INCONCLUSIVE")

    def test_context_provenance(self) -> None:
        record = _record(context_provenance=(DEFAULT_PROVENANCE,))
        attr = attribute(record, evaluate(record, TASK_02))
        self.assertEqual(attr.context_provenance_ref, DEFAULT_PROVENANCE)

    def test_backend_reference(self) -> None:
        backend_ref = {
            "backend": "codex",
            "event_type": "custom_tool_call",
            "reference": {"rollout_path": "codex_error.jsonl", "line": 6},
            "quality": "EXACT",
        }
        record = _record(
            tools=(
                {
                    "call_id": "t2",
                    "name": "lookup",
                    "arguments": {},
                    "backend_event_ref": backend_ref,
                },
            ),
            tool_results=(
                {
                    "tool_call_id": "t2",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        attr = attribute(record, evaluate(record, TASK_02))
        self.assertIn(backend_ref, attr.backend_event_refs)
        self.assertTrue(attr.evidence_refs)

    def test_lossy_mapping(self) -> None:
        record = _record(
            lossiness=(
                {
                    "backend": "codex",
                    "mapping_quality": "LOSSY",
                    "missing_semantics": ("EXEC_FAILURE_STRUCTURED_SUCCESS",),
                },
            ),
        )
        attr = attribute(record, evaluate(record, TASK_02))
        self.assertEqual(attr.mapping_quality, "LOSSY")

    def test_multiple_failure_candidates(self) -> None:
        record = _record(
            tools=(
                {"call_id": "t1", "name": "lookup", "arguments": {}},
                {"call_id": "t2", "name": "other", "arguments": {}},
            ),
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        attr = attribute(record, evaluate(record, TASK_02))
        self.assertEqual(attr.failure_kind, MULTIPLE_CANDIDATES)
        self.assertIsNone(attr.primary_failure)
        self.assertEqual(len(attr.secondary_failures), 2)
        self.assertEqual(
            {failure.failure_kind for failure in attr.secondary_failures},
            {TOOL_FAILURE, UNRESOLVED_TOOL},
        )

    def test_replay_stable_attribution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5k-") as td:
            path = Path(td) / "record.jsonl"
            store = _log(
                path=path,
                calls=(
                    {
                        "call_id": "t1",
                        "name": "inventory.lookup",
                        "arguments": {"sku": "A"},
                        "owner_ref": {
                            "owner_type": "capability",
                            "owner_id": "cap-c",
                        },
                    },
                ),
                results=(
                    {
                        "tool_call_id": "t1",
                        "content": "boom",
                        "is_error": True,
                        "error_code": "EXECUTION_ERROR",
                    },
                ),
            )
            record_a = build_execution_record(store, "step-1")
            attr_a = attribute(record_a, evaluate(record_a, SPEC_TOOL))
            store.close()

            reopened = EventStore("s5k-failure", path=path)
            reopened.open()
            replay(reopened)
            record_b = build_execution_record(reopened, "step-1")
            reopened.close()
            attr_b = attribute(record_b, evaluate(record_b, SPEC_TOOL))

        self.assertEqual(_plain(attr_a), _plain(attr_b))


class RaisingAgentScopeModel(DeterministicAgentScopeModel):
    def __init__(self) -> None:
        super().__init__([])

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **kwargs,
    ):
        raise RuntimeError("backend down")


class CrossBackendAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_backend_attribution_shape(self) -> None:
        runtime = basic_runtime()
        session = Session("s5k-agentscope-err")
        agent = AgentRuntime(
            session,
            runtime,
            AgentScopeModelAdapter(
                RaisingAgentScopeModel(),
                runtime,
                name="agent-a",
                max_iters=2,
            ),
            InitiatorContext("agent-a"),
        )
        with self.assertRaises(ModelRequestError):
            await agent.run_turn("go")
        execution_a = next(iter(agent.executions))
        record_a = build_execution_record(session.store, execution_a)
        attr_a = attribute(record_a, evaluate(record_a, SPEC_TOOL))

        runtime = basic_runtime()
        session = Session("s5k-codex-err")
        agent = AgentRuntime(
            session,
            runtime,
            CodexAdapter(FIXTURES / "codex_error.jsonl"),
            InitiatorContext("agent-c"),
        )
        with self.assertRaises(ModelRequestError):
            await agent.run_turn("go")
        execution_b = next(
            event.payload["execution_id"]
            for event in session.store.events()
            if event.event_type == EXECUTION_ATTEMPT_END
            and event.payload.get("error") == "MODEL_ERROR"
        )
        record_b = build_execution_record(session.store, execution_b)
        attr_b = attribute(record_b, evaluate(record_b, SPEC_TOOL))

        self.assertEqual(attr_a.failure_kind, MODEL_FAILURE)
        self.assertEqual(attr_b.failure_kind, MODEL_FAILURE)
        for attr in (attr_a, attr_b):
            self.assertTrue(attr.execution_id)
            self.assertTrue(attr.turn_id)
            self.assertTrue(attr.step_id)
            self.assertTrue(attr.attempt_id)
            self.assertIsInstance(attr.mapping_quality, str)
            self.assertIsNotNone(attr.initiator_ref)
        self.assertNotEqual(attr_a.execution_id, attr_b.execution_id)


if __name__ == "__main__":
    unittest.main()
