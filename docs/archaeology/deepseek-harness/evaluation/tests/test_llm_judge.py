"""Phase 6-A LLM Judge layer tests.

All fixtures are deterministic; the judge is the fake/deterministic judge in
``llm_judge.py``. No network, no real LLM, no runtime mutation.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TESTS = Path(__file__).resolve().parent
for path in (EVAL, RUNTIME, TESTS):
    sys.path.insert(0, str(path))

from evaluator import evaluate  # noqa: E402
from golden import GOLDEN_TASKS  # noqa: E402
from llm_judge import (  # noqa: E402
    FAIL,
    GOLDEN_JUDGE_TASKS,
    GOLDEN_RUBRIC,
    HIGH,
    INCONCLUSIVE,
    JUDGE_CONFLICT,
    JudgeModelRef,
    JudgePromptTemplate,
    JudgeRubric,
    LLMJudgeInput,
    LOW,
    MEDIUM,
    PASS,
    SUPPORTED,
    TASK_JUDGE_01,
    TASK_JUDGE_ORACLE,
    UNSUPPORTED,
    aggregate,
    fake_judge,
)
from models import EvaluationResult, Finding, TaskSpecification  # noqa: E402
from recovery import build_execution_record, replay  # noqa: E402
from rules import RULES  # noqa: E402
from test_control_plane_e2e import PROC_001, _run_agentscope, _run_codex  # noqa: E402


def _record(**kwargs) -> SimpleNamespace:
    defaults = dict(
        record_version="5j.1",
        projection_rule_version="v2",
        execution_id="exec-6a",
        session_id="session-6a",
        replay_ref={
            "source": "event_log",
            "session_id": "session-6a",
            "execution_id": "exec-6a",
            "event_range": [1, 12],
            "record_version": "5j.1",
            "projection_rule_version": "v2",
        },
        initiator_ref={"ref": "agent-a", "source": "ADAPTER_DERIVED"},
        owner_refs=({"owner_type": "capability", "owner_id": "cap-c"},),
        attempts=(
            SimpleNamespace(
                execution_id="exec-6a",
                attempt_id="exec-6a/attempt-1",
                attempt_number=1,
                parent_execution_id=None,
                reason="model_request",
                status="SUCCEEDED",
                step_id="step-1",
            ),
        ),
        tools=(),
        tool_results=(),
        turn_end_reason="completed",
        context_provenance=(
            {
                "request_ref": 2,
                "source_event_refs": [1],
                "surface_refs": [1],
                "current_input_ref": 1,
                "runtime_context_ref": None,
                "quality": "PARTIAL",
                "missing_semantics": ["SYSTEM_PROMPT_SNAPSHOT"],
            },
        ),
        lossiness=(),
        steps=(
            SimpleNamespace(
                assistant_messages=("库存为 5，采购建议：采购 10 件。",),
            ),
        ),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _det(
    status: str = PASS,
    *,
    task_id: str = "TASK-JUDGE-01",
    findings: tuple[Finding, ...] = (),
) -> EvaluationResult:
    return EvaluationResult("exec-6a", task_id, status, findings=tuple(findings))


def _jinput(
    record: SimpleNamespace | None = None,
    det: EvaluationResult | None = None,
    rubric: JudgeRubric | None = None,
    oracle=None,
) -> LLMJudgeInput:
    return LLMJudgeInput(
        task_specification=TASK_JUDGE_01,
        execution_record=record or _record(),
        deterministic_evaluation=det or _det(),
        rubric=rubric or GOLDEN_RUBRIC,
        oracle_reference=oracle if oracle is not None else TASK_JUDGE_ORACLE,
    )


def _verdicts(status: str) -> dict:
    return {
        criterion.criterion_id: {"status": status, "message": f"scripted {status}"}
        for criterion in GOLDEN_RUBRIC.criteria
    }


class LLMJudgeContractTests(unittest.TestCase):
    def test_judge_input_is_runtime_independent(self) -> None:
        import llm_judge

        source = Path(llm_judge.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import runtime",
            "import event_store",
            "import capability",
            "import contextvars",
        ):
            self.assertNotIn(forbidden, source)
        record = _record(store="RUNTIME_INTERNAL_SENTINEL")
        result = fake_judge(_jinput(record=record))
        self.assertEqual(result.status, PASS)
        self.assertNotIn("store", result.evidence_refs[0])

    def test_judge_pass(self) -> None:
        result = fake_judge(_jinput())
        self.assertEqual(result.status, PASS)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.confidence, HIGH)
        self.assertTrue(all(finding.status == PASS for finding in result.findings))

    def test_judge_fail(self) -> None:
        result = fake_judge(_jinput(), verdicts=_verdicts(FAIL))
        self.assertEqual(result.status, FAIL)
        self.assertEqual(result.score, 0.0)
        self.assertTrue(all(finding.status == FAIL for finding in result.findings))

    def test_judge_inconclusive(self) -> None:
        result = fake_judge(_jinput(), verdicts=_verdicts(INCONCLUSIVE))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertIsNone(result.score)
        self.assertEqual(result.confidence, LOW)

    def test_low_confidence(self) -> None:
        result = fake_judge(
            _jinput(),
            verdicts=_verdicts(FAIL),
            confidence=LOW,
        )
        self.assertEqual((result.status, result.confidence), (FAIL, LOW))
        with self.assertRaises(ValueError):
            fake_judge(_jinput(), verdicts=_verdicts(PASS), confidence=LOW)
        with self.assertRaises(ValueError):
            fake_judge(_jinput(), verdicts=_verdicts(INCONCLUSIVE), confidence=HIGH)

    def test_rubric_version(self) -> None:
        result = fake_judge(_jinput())
        self.assertEqual(
            result.rubric_ref,
            {"rubric_id": "rubric:phase6a:procurement", "version": "1"},
        )
        rubric_v2 = replace(GOLDEN_RUBRIC, rubric_id="rubric:phase6a:procurement:v2", version="2")
        result_v2 = fake_judge(_jinput(rubric=rubric_v2))
        self.assertEqual(result_v2.rubric_ref["version"], "2")
        self.assertNotEqual(result.rubric_ref, result_v2.rubric_ref)

    def test_model_ref(self) -> None:
        result = fake_judge(_jinput(), model_ref="llama-judge", model_version="3.1")
        self.assertEqual((result.model_ref, result.model_version), ("llama-judge", "3.1"))
        unknown = fake_judge(
            _jinput(),
            model_ref="provider-no-version",
            model_version="UNKNOWN",
        )
        self.assertEqual(unknown.model_version, "UNKNOWN")
        self.assertEqual(JudgeModelRef("m").model_version, "UNKNOWN")
        self.assertEqual(JudgePromptTemplate("p", "2").prompt_version, "2")

    def test_prompt_ref(self) -> None:
        result = fake_judge(
            _jinput(),
            prompt_ref="prompt:judge:v2",
            prompt_version="2",
        )
        self.assertEqual(
            (result.prompt_ref, result.prompt_version),
            ("prompt:judge:v2", "2"),
        )

    def test_evidence_refs(self) -> None:
        full_ref = {
            "execution_id": "exec-6a",
            "step_id": "step-1",
            "tool_call_id": "t2",
            "tool_result_id": "r2",
            "context_provenance_ref": {"quality": "PARTIAL"},
            "backend_event_ref": {"backend": "codex", "event_id": "e9"},
        }
        verdicts = {
            criterion.criterion_id: {
                "status": PASS,
                "evidence_refs": (full_ref,),
            }
            for criterion in GOLDEN_RUBRIC.criteria
        }
        result = fake_judge(_jinput(), verdicts=verdicts)
        self.assertEqual(result.findings[0].evidence_status, SUPPORTED)
        self.assertIn(full_ref, result.evidence_refs)
        unsupported = {
            criterion.criterion_id: {
                "status": INCONCLUSIVE,
                "message": "no evidence",
                "unsupported": True,
            }
            for criterion in GOLDEN_RUBRIC.criteria
        }
        result_unsupported = fake_judge(_jinput(), verdicts=unsupported)
        self.assertEqual(result_unsupported.findings[0].evidence_status, UNSUPPORTED)
        self.assertEqual(result_unsupported.status, INCONCLUSIVE)

    def test_lossy_evidence(self) -> None:
        record = _record(
            lossiness=(
                {
                    "backend": "codex",
                    "mapping_quality": "LOSSY",
                    "missing_semantics": ["EXEC_SUCCESS"],
                },
            ),
        )
        result = fake_judge(_jinput(record=record), verdicts=_verdicts(PASS))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        unified = aggregate(_det(PASS), (result,))
        self.assertEqual(unified.final_status, INCONCLUSIVE)

    def test_missing_context_inconclusive(self) -> None:
        record = _record(context_provenance=())
        result = fake_judge(_jinput(record=record))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIn("context provenance", result.reasoning_summary.lower())
        unified = aggregate(_det(PASS), (result,))
        self.assertEqual(unified.final_status, INCONCLUSIVE)

    def test_deterministic_failure_overrides_judge_pass(self) -> None:
        det = _det(
            FAIL,
            findings=(
                Finding(
                    "RULE-05",
                    FAIL,
                    "forbidden tool called: erp.force_write",
                    ({"execution_id": "exec-6a", "tool_call_id": "t3"},),
                ),
            ),
        )
        judge = fake_judge(_jinput(det=det), verdicts=_verdicts(PASS))
        unified = aggregate(det, (judge,))
        self.assertEqual(unified.final_status, FAIL)
        self.assertEqual(unified.judge_results[0].status, PASS)
        self.assertEqual(unified.confidence, HIGH)

    def test_judge_failure_reduces_final_result(self) -> None:
        det = _det(PASS)
        judge_fail = fake_judge(_jinput(det=det), verdicts=_verdicts(FAIL))
        unified = aggregate(det, (judge_fail,))
        self.assertEqual(unified.final_status, FAIL)
        self.assertIsNone(unified.final_score)
        judge_inconclusive = fake_judge(
            _jinput(det=det),
            verdicts=_verdicts(INCONCLUSIVE),
        )
        self.assertEqual(aggregate(det, (judge_inconclusive,)).final_status, INCONCLUSIVE)

    def test_multiple_judges_conflict(self) -> None:
        j1 = fake_judge(_jinput(), judge_id="judge-a", verdicts=_verdicts(PASS))
        j2 = fake_judge(_jinput(), judge_id="judge-b", verdicts=_verdicts(FAIL))
        unified = aggregate(_det(PASS), (j1, j2))
        self.assertEqual(unified.final_status, INCONCLUSIVE)
        self.assertTrue(unified.judge_conflict)
        self.assertEqual(unified.judge_conflict_reason, JUDGE_CONFLICT)
        self.assertEqual(unified.confidence, LOW)
        with_policy = aggregate(_det(PASS), (j1, j2), conflict_policy="judge-b")
        self.assertEqual(with_policy.final_status, FAIL)
        self.assertTrue(with_policy.judge_conflict)

    def test_judge_result_immutable(self) -> None:
        result = fake_judge(_jinput())
        with self.assertRaises(FrozenInstanceError):
            result.status = FAIL  # type: ignore[misc]
        unified = aggregate(_det(PASS), (result,))
        self.assertIs(unified.judge_results[0], result)
        self.assertEqual(unified.judge_results[0].status, result.status)

    def test_judge_rerun_new_run_id(self) -> None:
        first = fake_judge(_jinput())
        second = fake_judge(_jinput())
        self.assertNotEqual(first.judge_id, second.judge_id)
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.judge_id, first.judge_id)  # old result untouched

    def test_existing_deterministic_rules_unchanged(self) -> None:
        self.assertEqual(
            tuple(rule_id for rule_id, _ in RULES),
            tuple(f"RULE-{i:02d}" for i in range(1, 14)),
        )
        statuses = tuple(
            evaluate(record, spec).status for spec, record in GOLDEN_TASKS
        )
        self.assertEqual(statuses, (PASS, FAIL, FAIL, FAIL))

    def test_golden_judge_tasks(self) -> None:
        for task, record, oracle, expected_judge_status in GOLDEN_JUDGE_TASKS:
            det = evaluate(record, task)
            judge = fake_judge(
                LLMJudgeInput(task, record, det, GOLDEN_RUBRIC, oracle),
            )
            self.assertEqual(judge.status, expected_judge_status, task.task_id)
            unified = aggregate(det, (judge,))
            if task.task_id == "TASK-JUDGE-03":
                self.assertEqual(unified.final_status, FAIL)
            else:
                self.assertEqual(unified.final_status, expected_judge_status)


class LLMJudgeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_does_not_rerun_judge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6a-replay-") as td:
            record_a, store = await _run_agentscope(
                "v2",
                "procurement-001",
                "phase6a-replay",
            )
            replay(store)
            record_b = build_execution_record(store, record_a.execution_id)
            self.assertEqual(record_a.execution_id, record_b.execution_id)
            self.assertFalse(hasattr(record_b, "judge_results"))
            input_a = LLMJudgeInput(
                PROC_001,
                record_a,
                evaluate(record_a, PROC_001),
                GOLDEN_RUBRIC,
                TASK_JUDGE_ORACLE,
            )
            input_b = LLMJudgeInput(
                PROC_001,
                record_b,
                evaluate(record_b, PROC_001),
                GOLDEN_RUBRIC,
                TASK_JUDGE_ORACLE,
            )
            result_a = fake_judge(input_a)
            result_b = fake_judge(input_b)
            self.assertNotEqual(result_a.judge_id, result_b.judge_id)

    async def test_cross_backend_judge_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6a-cross-") as td:
            tmp = Path(td)
            unified_by_backend = {}
            for backend in ("agentscope", "codex"):
                session_id = f"phase6a-{backend}-judge"
                if backend == "agentscope":
                    record, _ = await _run_agentscope(
                        "v2",
                        "procurement-001",
                        session_id,
                    )
                else:
                    record = await _run_codex(
                        "v2",
                        "procurement-001",
                        session_id,
                        tmp,
                    )
                det = evaluate(record, PROC_001)
                judge = fake_judge(
                    LLMJudgeInput(
                        PROC_001,
                        record,
                        det,
                        GOLDEN_RUBRIC,
                        TASK_JUDGE_ORACLE,
                    ),
                    verdicts=_verdicts(PASS),
                )
                unified_by_backend[backend] = aggregate(det, (judge,))
        agentscope = unified_by_backend["agentscope"]
        codex = unified_by_backend["codex"]
        self.assertEqual(agentscope.final_status, codex.final_status)
        self.assertEqual(agentscope.final_score, codex.final_score)
        for field in (
            "status",
            "score",
            "confidence",
            "model_ref",
            "model_version",
            "prompt_ref",
            "prompt_version",
            "rubric_ref",
        ):
            self.assertEqual(
                getattr(agentscope.judge_results[0], field),
                getattr(codex.judge_results[0], field),
            )
        self.assertNotEqual(
            agentscope.judge_results[0].judge_id,
            codex.judge_results[0].judge_id,
        )
        self.assertTrue(agentscope.evidence_refs)
        self.assertTrue(codex.evidence_refs)
        self.assertNotEqual(agentscope.evidence_refs, codex.evidence_refs)


if __name__ == "__main__":
    unittest.main()
