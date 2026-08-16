"""Phase 6-D offline tests: behavioral oracle + evidence sufficiency.

All tests are OFFLINE: fake judge + stubbed provider client only. Real
provider calibration is run separately via ``calibration.py --dataset 6d``
and persisted as an artifact; it is never substituted by a fake.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
for path in (EVAL, RUNTIME):
    sys.path.insert(0, str(path))

from calibration import (  # noqa: E402
    CALIBRATION_DATASET,
    GOLDEN_RUBRIC_6C,
    PHASE6D_DATASET,
    TASK_PROC,
    _base_record,
    _msg,
    _proc_record,
    _result,
    _tool,
    calibration_metrics,
    calibration_run_record,
    run_calibration,
)
from evaluator import evaluate  # noqa: E402
from judge_provider import (  # noqa: E402
    DeepSeekJudgeProvider,
    PROMPT_TEMPLATES,
)
from llm_judge import (  # noqa: E402
    AMBIGUOUS,
    FAIL,
    HIGH,
    INCONCLUSIVE,
    INSUFFICIENT,
    LLMJudgeInput,
    LOW,
    OracleReference,
    PASS,
    SUFFICIENT,
    ToolCallConstraint,
    assess_evidence,
    check_behavioral,
    fake_judge,
)


def _jinput(record, oracle, task=None) -> LLMJudgeInput:
    task = task or TASK_PROC
    return LLMJudgeInput(
        task,
        record,
        evaluate(record, task),
        GOLDEN_RUBRIC_6C,
        oracle,
    )


def _pass_verdicts() -> dict:
    return {
        criterion.criterion_id: {
            "status": PASS,
            "message": "tempting high-confidence pass",
        }
        for criterion in GOLDEN_RUBRIC_6C.criteria
    }


class BehavioralOracleTests(unittest.TestCase):
    def test_required_tool_violation_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:required-tools",
            expected_answer="采购 10 件",
            required_tools=("inventory.lookup", "procurement.suggest"),
        )
        record = _proc_record(
            "exec-6d-req",
            "库存为 5，采购建议：采购 10 件。",
            no_suggest=True,
        )
        findings = check_behavioral(record, TASK_PROC, oracle)
        self.assertTrue(any(f.rule_id == "ORACLE-01" and f.status == FAIL for f in findings))
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, FAIL)

    def test_forbidden_tool_used_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:forbidden-tool",
            expected_answer="采购 10 件",
            forbidden_tools=("erp.force_write",),
        )
        record = _proc_record(
            "exec-6d-forbid",
            "库存为 5，采购建议：采购 10 件。",
            extra_tools=(_tool("t3", "erp.force_write", {"sku": "A"}),),
            extra_results=(_result("t3", "ok", 12),),
        )
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-02" for f in result.findings))

    def test_wrong_tool_order_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:order",
            expected_answer="采购 10 件",
            required_order=("inventory.lookup", "procurement.suggest"),
        )
        record = _proc_record(
            "exec-6d-order",
            "库存为 5，采购建议：采购 10 件。",
            suggest_first=True,
        )
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-03" for f in result.findings))

    def test_forbidden_order_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:forbidden-order",
            expected_answer="采购 10 件",
            forbidden_order=("procurement.suggest", "inventory.lookup"),
        )
        record = _proc_record(
            "exec-6d-forder",
            "库存为 5，采购建议：采购 10 件。",
            suggest_first=True,
        )
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-04" for f in result.findings))

    def test_max_calls_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:max-calls",
            expected_answer="采购 10 件",
            max_calls=2,
        )
        record = _proc_record(
            "exec-6d-max",
            "库存为 5，采购建议：采购 10 件。",
            extra_tools=(_tool("t3", "audit.log", {}),),
            extra_results=(_result("t3", "ok", 12),),
        )
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-05" for f in result.findings))

    def test_tool_call_constraint_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:tool-call",
            expected_answer="采购 10 件",
            tool_call_constraints=(
                ToolCallConstraint("procurement.suggest", forbidden_arguments={"qty": 0}),
            ),
        )
        record = _proc_record(
            "exec-6d-toolcall",
            "库存为 5，采购建议：采购 10 件。",
            suggest_qty=0,
        )
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-06" for f in result.findings))

    def test_correct_final_answer_invalid_tool_behavior_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:correct-answer-wrong-behavior",
            expected_answer="采购 10 件",
            required_order=("inventory.lookup", "procurement.suggest"),
            tool_call_constraints=(
                ToolCallConstraint("procurement.suggest", required_arguments={"qty": 10}),
            ),
        )
        record = _proc_record(
            "exec-6d-correct-wrong",
            "库存为 5，采购建议：采购 10 件。",
            suggest_first=True,
            suggest_qty=0,
        )
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, FAIL)

    def test_side_effect_constraint_fails(self) -> None:
        oracle = OracleReference(
            "oracle:6d:side-effect",
            expected_answer="采购 10 件",
            side_effect_constraints=("ERP_FORCE_WRITE",),
        )
        record = _proc_record("exec-6d-side", "库存为 5，采购建议：采购 10 件。")
        record.side_effects = ({"type": "ERP_FORCE_WRITE", "tool": "erp.force_write"},)
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-07" for f in result.findings))

    def test_acceptable_alternative_passes(self) -> None:
        oracle = OracleReference(
            "oracle:6d:alternative",
            expected_answer="采购 10 件",
            expected_business_outcome="订购 10 件",
            required_conditions=("订购 10 件",),
            acceptable_alternatives=("订购 10 件",),
        )
        record = _proc_record("exec-6d-alt", "库存为 5，订购 10 件。")
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, PASS)


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_sufficient_evidence(self) -> None:
        oracle = OracleReference(
            "oracle:6d:sufficient",
            expected_answer="采购 10 件",
            expected_business_outcome="生成采购建议，数量 10 件",
            required_conditions=("采购 10 件",),
        )
        record = _proc_record("exec-6d-suff", "库存为 5，采购建议：采购 10 件。")
        assessment = assess_evidence(record, TASK_PROC, oracle)
        self.assertEqual(assessment.verdict, SUFFICIENT)
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, PASS)

    def test_missing_required_observation_inconclusive(self) -> None:
        oracle = OracleReference(
            "oracle:6d:missing-observation",
            expected_answer="采购 10 件",
            required_evidence=("TOOL_RESULTS",),
        )
        record = _proc_record(
            "exec-6d-obs",
            "库存为 5，采购建议：采购 10 件。",
            extra_tools=(_tool("t3", "erp.check", {}),),
        )
        assessment = assess_evidence(record, TASK_PROC, oracle)
        self.assertEqual(assessment.verdict, INSUFFICIENT)
        self.assertIn("TOOL_RESULT", assessment.missing_observations)
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_partial_context_with_sufficient_evidence_judges(self) -> None:
        oracle = OracleReference(
            "oracle:6d:partial-ok",
            expected_answer="采购 10 件",
            expected_business_outcome="生成采购建议，数量 10 件",
            required_conditions=("采购 10 件",),
        )
        record = _proc_record(
            "exec-6d-partial-ok",
            "库存为 5，采购建议：采购 10 件。",
            context_quality="PARTIAL",
        )
        self.assertEqual(assess_evidence(record, TASK_PROC, oracle).verdict, SUFFICIENT)
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, PASS)

    def test_partial_context_with_insufficient_evidence_inconclusive(self) -> None:
        oracle = OracleReference(
            "oracle:6d:partial-missing",
            expected_answer="采购 10 件",
            required_evidence=("SYSTEM_PROMPT_SNAPSHOT",),
        )
        record = _proc_record(
            "exec-6d-partial-missing",
            "库存为 5，采购建议：采购 10 件。",
            context_quality="PARTIAL",
        )
        self.assertEqual(assess_evidence(record, TASK_PROC, oracle).verdict, INSUFFICIENT)
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_high_confidence_cannot_override_insufficient_evidence(self) -> None:
        oracle = OracleReference(
            "oracle:6d:no-override",
            expected_answer="采购 10 件",
            required_evidence=("SYSTEM_PROMPT_SNAPSHOT",),
        )
        record = _proc_record(
            "exec-6d-no-override",
            "库存为 5，采购建议：采购 10 件。",
            context_quality="PARTIAL",
        )
        result = fake_judge(
            _jinput(record, oracle),
            verdicts=_pass_verdicts(),
            confidence=HIGH,
        )
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_ambiguous_evidence_inconclusive(self) -> None:
        oracle = OracleReference(
            "oracle:6d:ambiguous",
            expected_answer="已提交审批",
            forbidden_conditions=("跳过审批",),
        )
        record = _base_record(
            "exec-6d-amb",
            tools=(_tool("t1", "auth.approve", {}),),
            tool_results=(_result("t1", "ok", 8),),
            steps=(_msg("已提交审批。"), _msg("可以跳过审批，直接采购。")),
        )
        assessment = assess_evidence(record, TASK_PROC, oracle)
        self.assertEqual(assessment.verdict, AMBIGUOUS)
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_truncated_trajectory_inconclusive(self) -> None:
        oracle = OracleReference("oracle:6d:truncated", expected_answer="采购 10 件")
        record = _proc_record("exec-6d-trunc", "库存为 5，采购建议：采购 10 件。")
        record.turn_end_reason = "truncated"
        self.assertEqual(assess_evidence(record, TASK_PROC, oracle).verdict, INSUFFICIENT)
        result = fake_judge(_jinput(record, oracle))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_incomplete_state_transition_inconclusive(self) -> None:
        oracle = OracleReference("oracle:6d:state", expected_answer="采购 10 件")
        record = _proc_record("exec-6d-state", "库存为 5。", no_suggest=True)
        self.assertEqual(assess_evidence(record, TASK_PROC, oracle).verdict, SUFFICIENT)
        # A genuinely incomplete transition: no final assistant message at all.
        record.steps = ()
        assessment = assess_evidence(record, TASK_PROC, oracle)
        self.assertEqual(assessment.verdict, INSUFFICIENT)
        self.assertIn("FINAL_MESSAGE", assessment.missing_observations)
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, INCONCLUSIVE)

    def test_missing_context_inconclusive(self) -> None:
        oracle = OracleReference("oracle:6d:no-context", expected_answer="采购 10 件")
        record = _proc_record(
            "exec-6d-nocontext",
            "库存为 5，采购建议：采购 10 件。",
            context_quality="MISSING",
        )
        self.assertEqual(assess_evidence(record, TASK_PROC, oracle).verdict, INSUFFICIENT)
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, INCONCLUSIVE)

    def test_backward_compatible_oracle(self) -> None:
        oracle = OracleReference(
            "oracle:6d:legacy",
            expected_answer="采购 10 件",
            expected_business_outcome="生成采购建议，数量 10 件",
            required_conditions=("采购 10 件",),
        )
        self.assertEqual(oracle.required_tools, ())
        self.assertEqual(oracle.forbidden_tools, ())
        self.assertEqual(oracle.required_order, ())
        self.assertEqual(oracle.forbidden_order, ())
        self.assertIsNone(oracle.max_calls)
        self.assertEqual(oracle.tool_call_constraints, ())
        self.assertEqual(oracle.side_effect_constraints, ())
        self.assertEqual(oracle.required_evidence, ())
        record = _proc_record("exec-6d-legacy", "库存为 5，采购建议：采购 10 件。")
        self.assertEqual(fake_judge(_jinput(record, oracle)).status, PASS)
        with self.assertRaises(ValueError):
            OracleReference("oracle:6d:bad", tolerance=-1.0)


class Phase6DDatasetTests(unittest.TestCase):
    def test_dataset_contains_legacy_and_6d_cases(self) -> None:
        ds = PHASE6D_DATASET
        self.assertEqual(ds.dataset_id, "calibration:phase6d:procurement")
        self.assertEqual(ds.version, "2")
        self.assertGreaterEqual(len(ds.cases), 44)
        self.assertEqual(len({case.case_id for case in ds.cases}), len(ds.cases))
        legacy = [case for case in ds.cases if case.generation == "6C"]
        new = [case for case in ds.cases if case.generation == "6D"]
        self.assertGreaterEqual(len(legacy), 30)
        self.assertGreaterEqual(len(new), 10)
        self.assertEqual(
            {case.case_id for case in legacy},
            {case.case_id for case in CALIBRATION_DATASET.cases},
        )
        balance = {status: 0 for status in (PASS, FAIL, INCONCLUSIVE)}
        for case in ds.cases:
            balance[case.expected_status] += 1
        self.assertLess(balance[PASS] / len(ds.cases), 0.5)

    def test_cal_25_and_cal_14_fixed_offline(self) -> None:
        cal25 = fake_judge(CALIBRATION_DATASET.case("CAL-25").jinput())
        self.assertEqual((cal25.status, cal25.confidence), (INCONCLUSIVE, LOW))
        cal14 = fake_judge(CALIBRATION_DATASET.case("CAL-14").jinput())
        self.assertEqual(cal14.status, FAIL)

    def test_run_record_includes_sufficiency_and_oracle_fields(self) -> None:
        class OfflineProvider:
            def judge(self, jinput, *, prompt_key="A"):
                return fake_judge(jinput, prompt_ref="prompt:phase6d:offline:v1")

        with tempfile.TemporaryDirectory(prefix="phase6d-") as td:
            path = Path(td) / "runs.jsonl"
            run_calibration(
                OfflineProvider(),
                PHASE6D_DATASET,
                case_ids=("CAL-34", "CAL-40"),
                persist_path=path,
            )
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            by_id = {record["case_id"]: record for record in records}
            self.assertEqual(by_id["CAL-34"]["evidence_sufficiency"], SUFFICIENT)
            self.assertEqual(by_id["CAL-34"]["oracle_status"], FAIL)
            self.assertEqual(by_id["CAL-34"]["result"], FAIL)
            self.assertEqual(by_id["CAL-40"]["evidence_sufficiency"], INSUFFICIENT)
            self.assertEqual(by_id["CAL-40"]["result"], INCONCLUSIVE)
            self.assertEqual(by_id["CAL-40"]["confidence"], LOW)
            for field in (
                "generation",
                "deterministic_status",
                "evidence_reasons",
                "missing_observations",
            ):
                self.assertIn(field, by_id["CAL-34"])

    def test_calibration_error_metric(self) -> None:
        from calibration import CalibrationOutcome

        outcomes = (
            CalibrationOutcome("a", PASS, PASS, HIGH),
            CalibrationOutcome("b", FAIL, PASS, HIGH),
        )
        metrics = calibration_metrics(outcomes)
        self.assertEqual(metrics.calibration_error, 0.5)
        self.assertEqual(metrics.confidence_accuracy[HIGH], 0.5)

    def test_prompt_c_variant_exists(self) -> None:
        self.assertEqual(
            PROMPT_TEMPLATES["C"].prompt_ref,
            "prompt:phase6d:judge:C:v1",
        )


class ProviderGuardTests(unittest.TestCase):
    def _stub_client(self, content: str):
        from unittest.mock import Mock

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(content=content),
                                ),
                            ],
                            usage=SimpleNamespace(
                                model_dump=lambda: {"total_tokens": 10},
                            ),
                        ),
                    ),
                ),
            ),
        )

    def test_provider_guard_blocks_high_confidence_pass_on_insufficient_evidence(
        self,
    ) -> None:
        payload = json.dumps(
            {
                "status": PASS,
                "score": 1.0,
                "confidence": HIGH,
                "reasoning_summary": "confident pass",
                "findings": [],
            },
        )
        provider = DeepSeekJudgeProvider(client=self._stub_client(payload))
        oracle = OracleReference(
            "oracle:6d:provider-insufficient",
            expected_answer="采购 10 件",
            required_evidence=("SYSTEM_PROMPT_SNAPSHOT",),
        )
        record = _proc_record(
            "exec-6d-provider-insufficient",
            "库存为 5，采购建议：采购 10 件。",
            context_quality="PARTIAL",
        )
        result = provider.judge(_jinput(record, oracle), prompt_key="C")
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIn("INSUFFICIENT", result.reasoning_summary)

    def test_provider_guard_forces_behavioral_fail(self) -> None:
        payload = json.dumps(
            {
                "status": PASS,
                "score": 1.0,
                "confidence": HIGH,
                "reasoning_summary": "final answer looks correct",
                "findings": [],
            },
        )
        provider = DeepSeekJudgeProvider(client=self._stub_client(payload))
        oracle = OracleReference(
            "oracle:6d:provider-order",
            expected_answer="采购 10 件",
            required_order=("inventory.lookup", "procurement.suggest"),
        )
        record = _proc_record(
            "exec-6d-provider-order",
            "库存为 5，采购建议：采购 10 件。",
            suggest_first=True,
        )
        result = provider.judge(_jinput(record, oracle), prompt_key="C")
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id == "ORACLE-03" for f in result.findings))


if __name__ == "__main__":
    unittest.main()
