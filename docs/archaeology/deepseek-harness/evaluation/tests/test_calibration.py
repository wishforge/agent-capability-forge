"""Phase 6-C calibration tests.

All fixture-based tests are OFFLINE: no network, no real LLM, no runtime
mutation. Real provider tests skip with BLOCKED when DeepSeek is unreachable
and never substitute a fake judge as "real" evidence.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TESTS = Path(__file__).resolve().parent
for path in (EVAL, RUNTIME, TESTS):
    sys.path.insert(0, str(path))

from calibration import (  # noqa: E402
    CALIBRATION_DATASET,
    CalibrationMetrics,
    CalibrationOutcome,
    GOLDEN_RUBRIC_6C,
    append_calibration_run,
    calibration_metrics,
    calibration_run_record,
    compare_backends,
    compare_prompts,
    run_calibration,
)
from evaluator import evaluate  # noqa: E402
from llm_judge import (  # noqa: E402
    FAIL,
    HIGH,
    INCONCLUSIVE,
    LLMJudgeInput,
    LOW,
    MEDIUM,
    PASS,
    OracleReference,
    fake_judge,
)


class OfflineJudge:
    """Deterministic fake-judge provider; never a real calibration."""

    def __init__(
        self,
        prompt_ref: str = "prompt:phase6c:offline:A:v1",
        prompt_version: str = "1",
        model_ref: str = "offline-fake-judge",
        model_version: str = "1.0.0",
        *,
        context_policy: bool = False,
    ) -> None:
        self.prompt_ref = prompt_ref
        self.prompt_version = prompt_version
        self.model_ref = model_ref
        self.model_version = model_version
        self.context_policy = context_policy

    def judge(self, jinput: LLMJudgeInput, *, prompt_key: str = "A") -> object:
        kwargs = dict(
            prompt_ref=self.prompt_ref,
            prompt_version=self.prompt_version,
            model_ref=self.model_ref,
            model_version=self.model_version,
        )
        provenance = tuple(getattr(jinput.execution_record, "context_provenance", ()) or ())
        if self.context_policy and provenance and provenance[0].get("quality") != "EXACT":
            verdicts = {
                criterion.criterion_id: {
                    "status": INCONCLUSIVE,
                    "message": "PARTIAL context; abstaining",
                    "unsupported": True,
                }
                for criterion in jinput.rubric.criteria
            }
            return fake_judge(jinput, verdicts=verdicts, confidence=LOW, **kwargs)
        return fake_judge(jinput, **kwargs)


def _outcome(
    case_id: str,
    expected: str,
    actual: str,
    confidence: str = HIGH,
    *,
    tags: tuple[str, ...] = (),
    context_quality: str = "EXACT",
    lossy: bool = False,
) -> CalibrationOutcome:
    return CalibrationOutcome(
        case_id=case_id,
        expected_status=expected,
        actual_status=actual,
        actual_confidence=confidence,
        tags=tags,
        context_quality=context_quality,
        lossy=lossy,
    )


class CalibrationDatasetTests(unittest.TestCase):
    def test_dataset_version(self) -> None:
        ds = CALIBRATION_DATASET
        self.assertEqual(ds.version, "2")
        self.assertEqual(ds.dataset_id, "calibration:phase6c:procurement")
        self.assertTrue(ds.created_at)
        self.assertGreaterEqual(len(ds.cases), 30)
        self.assertEqual(len({case.case_id for case in ds.cases}), len(ds.cases))
        for case in ds.cases:
            self.assertEqual(
                case.rubric_ref,
                {"rubric_id": "rubric:phase6c:procurement", "version": "1"},
            )

    def test_case_balance(self) -> None:
        ds = CALIBRATION_DATASET
        balance = {status: 0 for status in (PASS, FAIL, INCONCLUSIVE)}
        for case in ds.cases:
            balance[case.expected_status] += 1
        for status, count in balance.items():
            self.assertGreater(count, 0, status)
        self.assertLess(balance[PASS] / len(ds.cases), 0.5)
        self.assertEqual(sum(balance.values()), len(ds.cases))

    def test_oracle_constraints(self) -> None:
        case = CALIBRATION_DATASET.case("TASK-JUDGE-05")
        weak = OracleReference(
            oracle_id="oracle:phase6b:procurement",
            expected_answer="采购建议",
            expected_business_outcome="采购建议",
        )
        strong = case.oracle_reference
        weak_result = fake_judge(replace(case.jinput(), oracle_reference=weak))
        strong_result = fake_judge(case.jinput())
        self.assertEqual(weak_result.status, PASS)
        self.assertEqual(strong_result.status, FAIL)
        forbidden = replace(
            strong,
            required_conditions=(),
            forbidden_conditions=("采购 3 件",),
        )
        forbidden_result = fake_judge(replace(case.jinput(), oracle_reference=forbidden))
        self.assertEqual(forbidden_result.status, FAIL)
        with self.assertRaises(ValueError):
            OracleReference("bad", tolerance=-1.0)

    def test_rubric_version(self) -> None:
        rubric = GOLDEN_RUBRIC_6C
        self.assertEqual(rubric.version, "1")
        for criterion in rubric.criteria:
            self.assertTrue(criterion.oracle_ref)
        result = fake_judge(CALIBRATION_DATASET.case("TASK-JUDGE-01").jinput())
        self.assertEqual(
            result.rubric_ref,
            {"rubric_id": "rubric:phase6c:procurement", "version": "1"},
        )

    def test_agreement(self) -> None:
        outcomes = (
            _outcome("a", PASS, PASS),
            _outcome("b", FAIL, FAIL),
            _outcome("c", PASS, INCONCLUSIVE, LOW),
            _outcome("d", INCONCLUSIVE, PASS),
        )
        metrics = calibration_metrics(outcomes)
        self.assertEqual(metrics.sample_size, 4)
        self.assertEqual(metrics.agreement_rate, 0.5)

    def test_false_pass(self) -> None:
        metrics = calibration_metrics(
            (
                _outcome("unsafe", FAIL, PASS, HIGH),
                _outcome("abstain", INCONCLUSIVE, PASS, HIGH),
            ),
        )
        self.assertEqual(metrics.false_pass_rate, 0.5)
        self.assertEqual(metrics.false_fail_rate, 0.0)
        self.assertIn("unsafe", metrics.mis_calibrated)
        self.assertIn("abstain", metrics.mis_calibrated)

    def test_false_fail(self) -> None:
        metrics = calibration_metrics(
            (_outcome("ok", PASS, FAIL, HIGH),),
        )
        self.assertEqual(metrics.false_fail_rate, 1.0)
        self.assertEqual(metrics.false_pass_rate, 0.0)

    def test_inconclusive(self) -> None:
        metrics = calibration_metrics(
            (
                _outcome("a", PASS, INCONCLUSIVE, LOW),
                _outcome("b", INCONCLUSIVE, INCONCLUSIVE, LOW),
                _outcome("c", FAIL, PASS, HIGH),
            ),
        )
        self.assertEqual(metrics.inconclusive_rate, 2 / 3)
        self.assertEqual(metrics.abstention_rate, 1 / 2)

    def test_small_sample_flag(self) -> None:
        small = calibration_metrics(
            tuple(_outcome(f"c{i}", PASS, PASS) for i in range(7)),
        )
        self.assertFalse(small.statistically_meaningful)
        self.assertEqual(small.significance, "NOT_STATISTICALLY_MEANINGFUL")
        self.assertEqual(small.sample_flag, "INSUFFICIENT_SAMPLE")
        large = calibration_metrics(
            tuple(_outcome(f"c{i}", PASS, PASS) for i in range(30)),
        )
        self.assertTrue(large.statistically_meaningful)
        self.assertEqual(large.sample_flag, "SUFFICIENT_SAMPLE")

    def test_confidence_calibration(self) -> None:
        metrics = calibration_metrics(
            (
                _outcome("a", PASS, PASS, HIGH),
                _outcome("b", FAIL, FAIL, HIGH),
                _outcome("c", PASS, FAIL, MEDIUM),
            ),
        )
        self.assertEqual(metrics.confidence_accuracy[HIGH], 1.0)
        self.assertEqual(metrics.confidence_accuracy[MEDIUM], 0.0)
        self.assertEqual(metrics.confidence_accuracy[LOW], 0.0)

    def test_high_confidence_wrong(self) -> None:
        metrics = calibration_metrics(
            (
                _outcome("wrong", FAIL, PASS, HIGH),
                _outcome("right", PASS, PASS, HIGH),
            ),
        )
        self.assertEqual(metrics.mis_calibrated, ("wrong",))

    def test_abstention(self) -> None:
        run = run_calibration(
            OfflineJudge(),
            CALIBRATION_DATASET,
            case_ids=("CAL-15",),
        )
        case_id, result = run.results[0]
        self.assertEqual(case_id, "CAL-15")
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIsNone(result.score)
        metrics = calibration_metrics(
            (_outcome("decidable", PASS, INCONCLUSIVE, LOW),),
        )
        self.assertEqual(metrics.abstention_rate, 1.0)
        self.assertEqual(run.metrics.by_context["MISSING"].inconclusive_rate, 1.0)
        self.assertEqual(run.metrics.actual_balance[INCONCLUSIVE], 1)

    def test_prompt_comparison(self) -> None:
        subset = ("TASK-JUDGE-01", "TASK-JUDGE-02", "TASK-JUDGE-05")
        run_a = run_calibration(
            OfflineJudge("prompt:phase6c:judge:A:v1"),
            CALIBRATION_DATASET,
            case_ids=subset,
        )
        run_b = run_calibration(
            OfflineJudge("prompt:phase6c:judge:B:v1"),
            CALIBRATION_DATASET,
            case_ids=subset,
        )
        comparison = compare_prompts(run_a, run_b)
        self.assertNotEqual(comparison.prompt_a_ref, comparison.prompt_b_ref)
        self.assertEqual(comparison.status_agreement_rate, 1.0)
        self.assertEqual(comparison.false_pass_delta, 0.0)

    def test_context_calibration(self) -> None:
        subset = ("TASK-JUDGE-01", "CAL-15", "CAL-25")
        run = run_calibration(
            OfflineJudge(context_policy=True),
            CALIBRATION_DATASET,
            case_ids=subset,
        )
        self.assertEqual(run.metrics.by_context["EXACT"].sample_size, 1)
        self.assertEqual(run.metrics.by_context["EXACT"].inconclusive_rate, 0.0)
        self.assertEqual(run.metrics.by_context["MISSING"].inconclusive_rate, 1.0)
        self.assertEqual(run.metrics.by_context["PARTIAL"].inconclusive_rate, 1.0)

    def test_lossy_calibration(self) -> None:
        run = run_calibration(
            OfflineJudge(),
            CALIBRATION_DATASET,
            case_ids=("CAL-16",),
        )
        self.assertEqual(run.results[0][1].status, INCONCLUSIVE)
        self.assertEqual(run.results[0][1].confidence, LOW)
        self.assertEqual(run.metrics.by_lossiness["LOSSY"].inconclusive_rate, 1.0)
        self.assertEqual(run.metrics.by_lossiness["EXACT_EVIDENCE"].sample_size, 0)

    def test_cross_backend_calibration(self) -> None:
        subset = ("TASK-JUDGE-01", "TASK-JUDGE-02", "CAL-16")
        run_a = run_calibration(
            OfflineJudge(model_ref="agentscope-probe"),
            CALIBRATION_DATASET,
            case_ids=subset,
        )
        run_b = run_calibration(
            OfflineJudge(model_ref="codex-probe"),
            CALIBRATION_DATASET,
            case_ids=subset,
        )
        comparison = compare_backends(run_a, run_b)
        self.assertEqual(comparison.status_agreement_rate, 1.0)
        self.assertEqual(comparison.score_agreement_rate, 1.0)
        self.assertEqual(len(comparison.pairs), 3)

    def test_task_judge_05_oracle_strength(self) -> None:
        case = CALIBRATION_DATASET.case("TASK-JUDGE-05")
        weak = OracleReference(
            oracle_id="oracle:phase6b:procurement",
            expected_answer="采购建议",
            expected_business_outcome="采购建议",
        )
        self.assertEqual(fake_judge(replace(case.jinput(), oracle_reference=weak)).status, PASS)
        self.assertEqual(fake_judge(case.jinput()).status, FAIL)

    def test_metrics_deterministic(self) -> None:
        subset = ("TASK-JUDGE-01", "TASK-JUDGE-02", "CAL-15", "CAL-16")
        first = run_calibration(OfflineJudge(), CALIBRATION_DATASET, case_ids=subset)
        second = run_calibration(OfflineJudge(), CALIBRATION_DATASET, case_ids=subset)
        self.assertEqual(first.metrics, second.metrics)
        self.assertIsInstance(first.metrics, CalibrationMetrics)

    def test_run_persistence_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6c-") as td:
            path = Path(td) / "runs.jsonl"
            run_calibration(
                OfflineJudge(),
                CALIBRATION_DATASET,
                case_ids=("TASK-JUDGE-01",),
                persist_path=path,
            )
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            for field in (
                "judge_run_id",
                "dataset_version",
                "case_id",
                "rubric_version",
                "prompt_ref",
                "model_ref",
                "result",
                "confidence",
                "timestamp",
            ):
                self.assertIn(field, record)
            self.assertNotIn("secret", record)
            self.assertEqual(record["dataset_version"], "2")
            self.assertEqual(record["result"], PASS)


class FixtureWordingTests(unittest.TestCase):
    """Phase 6-E.1-A2: qty=10 / qty=5 task texts are split per family."""

    def test_qty10_family_uses_purchase_quantity_wording(self) -> None:
        goal = CALIBRATION_DATASET.case("TASK-JUDGE-01").task_specification.natural_language_goal
        self.assertIn("目标采购数量 10，当前库存 5", goal)
        self.assertNotIn("目标库存 10，当前库存 5", goal)

    def test_qty5_family_explicit_gap_wording(self) -> None:
        for case_id in ("CAL-20", "CAL-26", "CAL-29"):
            goal = CALIBRATION_DATASET.case(case_id).task_specification.natural_language_goal
            self.assertIn("目标库存 10，当前库存 5，采购缺口 5 件", goal)

    def test_labels_oracles_and_deterministic_status_unchanged(self) -> None:
        expectations = (
            ("TASK-JUDGE-01", PASS, "oracle:phase6c:procurement:qty10", PASS),
            ("CAL-20", FAIL, "oracle:phase6c:numeric:qty5", FAIL),
            ("CAL-26", INCONCLUSIVE, "oracle:phase6c:numeric:qty5", INCONCLUSIVE),
            ("CAL-29", FAIL, "oracle:phase6c:numeric:qty5", FAIL),
        )
        for case_id, expected_status, oracle_id, offline_status in expectations:
            case = CALIBRATION_DATASET.case(case_id)
            self.assertEqual(case.expected_status, expected_status, case_id)
            self.assertEqual(case.oracle_reference.oracle_id, oracle_id, case_id)
            self.assertEqual(
                evaluate(case.execution_record, case.task_specification).status,
                PASS,
                case_id,
            )
            self.assertEqual(
                fake_judge(case.jinput()).status,
                offline_status,
                case_id,
            )

    def test_append_calibration_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6c-") as td:
            path = Path(td) / "runs.jsonl"
            append_calibration_run(path, {"judge_run_id": "x"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").splitlines()[0]),
                {"judge_run_id": "x"},
            )


class RealCalibrationTests(unittest.TestCase):
    """Real provider calibration; BLOCKED-skip offline, never fake."""

    @classmethod
    def setUpClass(cls) -> None:
        from judge_provider import DeepSeekJudgeProvider, provider_status

        available, reason = provider_status()
        if not available:
            raise unittest.SkipTest(f"BLOCKED: {reason}")
        cls.provider = DeepSeekJudgeProvider()

    def test_real_provider_calibration_subset(self) -> None:
        subset = (
            "TASK-JUDGE-01",
            "TASK-JUDGE-02",
            "TASK-JUDGE-03",
            "TASK-JUDGE-04",
            "TASK-JUDGE-05",
            "TASK-JUDGE-07",
            "CAL-10",
            "CAL-12",
            "CAL-15",
            "CAL-16",
            "CAL-20",
            "CAL-25",
        )
        run = run_calibration(
            self.provider,
            CALIBRATION_DATASET,
            case_ids=subset,
            prompt_key="A",
        )
        self.assertEqual(run.metrics.sample_size, len(subset))
        self.assertFalse(run.metrics.statistically_meaningful)


if __name__ == "__main__":
    unittest.main()
