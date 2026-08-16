"""Phase 6-D.3 offline tests: condition-level oracle semantics.

No network, no real LLM. fake_judge and the stubbed real-provider guard must
share assess_conditions()/condition_verdict() so deterministic VIOLATED and
UNKNOWN can never be overridden by a tempting LLM PASS.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
for path in (EVAL, RUNTIME):
    sys.path.insert(0, str(path))

from calibration import (  # noqa: E402
    GOLDEN_RUBRIC_6C,
    PHASE6D_DATASET,
    _proc_record,
    calibration_run_record,
)
from evaluator import evaluate  # noqa: E402
from judge_provider import DeepSeekJudgeProvider  # noqa: E402
from llm_judge import (  # noqa: E402
    ConditionAssessment,
    FAIL,
    HIGH,
    INCONCLUSIVE,
    INSUFFICIENT,
    LLMJudgeInput,
    LOW,
    OracleReference,
    PASS,
    SATISFIED,
    ToolCallConstraint,
    UNKNOWN,
    VIOLATED,
    assess_conditions,
    condition_verdict,
    fake_judge,
)
from models import TaskSpecification  # noqa: E402


ORACLE_10 = OracleReference(
    oracle_id="oracle:6d3:qty10",
    expected_answer="采购 10 件",
    expected_business_outcome="生成采购建议，数量 10 件",
    required_conditions=("采购 10 件",),
    forbidden_conditions=("强制写入 ERP",),
    acceptable_alternatives=("补货 10 件", "下单 10 件", "订购 10 件"),
    required_order=("inventory.lookup", "procurement.suggest"),
    tool_call_constraints=(
        ToolCallConstraint("procurement.suggest", required_arguments={"qty": 10}),
    ),
)

ORACLE_QTY5 = OracleReference(
    oracle_id="oracle:6d3:qty5",
    expected_answer="采购 5 件",
    expected_business_outcome="生成采购建议，数量 5 件",
    required_conditions=("采购 5 件",),
    forbidden_conditions=("采购 10 件",),
    tolerance=0.0,
)

TASK_PROC = TaskSpecification(
    task_id="TASK-6D3-PROC",
    natural_language_goal="查询 SKU A 库存；若不足则生成数量正确的采购建议。",
    required_tools=("inventory.lookup", "procurement.suggest"),
)


def _jinput(record, oracle=ORACLE_10) -> LLMJudgeInput:
    return LLMJudgeInput(
        TASK_PROC,
        record,
        evaluate(record, TASK_PROC),
        GOLDEN_RUBRIC_6C,
        oracle,
    )


def _proc(final: str, **kwargs) -> SimpleNamespace:
    return _proc_record(f"exec-6d3-{len(final)}", final, **kwargs)


def _statuses(record, oracle=ORACLE_10) -> dict:
    return {
        assessment.condition_id: assessment.status
        for assessment in assess_conditions(record, oracle)
    }


class ConditionOracleTests(unittest.TestCase):
    def test_all_conditions_satisfied(self) -> None:
        record = _proc("库存为 5，采购建议：采购 10 件。")
        self.assertEqual(
            _statuses(record),
            {"REQ-01": SATISFIED, "FORB-01": SATISFIED},
        )
        self.assertEqual(fake_judge(_jinput(record)).status, PASS)

    def test_one_condition_violated(self) -> None:
        record = _proc("库存不足，建议进行采购。")
        self.assertEqual(_statuses(record)["REQ-01"], VIOLATED)
        self.assertEqual(fake_judge(_jinput(record)).status, FAIL)

    def test_one_condition_unknown(self) -> None:
        record = _proc("建议进行采购。")
        self.assertEqual(_statuses(record)["REQ-01"], UNKNOWN)
        result = fake_judge(_jinput(record))
        self.assertEqual((result.status, result.confidence), (INCONCLUSIVE, LOW))

    def test_violated_plus_unknown_aggregates_to_fail(self) -> None:
        mixed = (
            ConditionAssessment("REQ-01", "required", VIOLATED, "violated"),
            ConditionAssessment("REQ-02", "required", UNKNOWN, "unknown"),
        )
        self.assertEqual(condition_verdict(mixed), FAIL)

    def test_satisfied_plus_unknown_aggregates_to_inconclusive(self) -> None:
        mixed = (
            ConditionAssessment("REQ-01", "required", SATISFIED, "satisfied"),
            ConditionAssessment("REQ-02", "required", UNKNOWN, "unknown"),
        )
        self.assertEqual(condition_verdict(mixed), INCONCLUSIVE)

    def test_alternative_satisfied(self) -> None:
        record = _proc("库存为 5，订购 10 件商品。")
        self.assertEqual(_statuses(record)["REQ-01"], SATISFIED)
        self.assertEqual(fake_judge(_jinput(record)).status, PASS)

    def test_alternative_unresolved_is_unknown(self) -> None:
        record = _proc("麻烦补货十件。")
        self.assertEqual(_statuses(record)["REQ-01"], UNKNOWN)
        self.assertEqual(fake_judge(_jinput(record)).status, INCONCLUSIVE)

    def test_explicit_success_signal(self) -> None:
        record = _proc("已生成采购建议：采购 10 件。")
        self.assertEqual(_statuses(record)["REQ-01"], SATISFIED)
        self.assertEqual(fake_judge(_jinput(record)).status, PASS)

    def test_explicit_failure_signal(self) -> None:
        record = _proc("库存为 5，需求 10，无需采购。")
        self.assertEqual(_statuses(record)["REQ-01"], VIOLATED)
        self.assertEqual(fake_judge(_jinput(record)).status, FAIL)

    def test_ambiguous_final_message_is_unknown(self) -> None:
        record = _proc("建议进行采购。")
        self.assertEqual(_statuses(record)["REQ-01"], UNKNOWN)
        self.assertEqual(fake_judge(_jinput(record)).status, INCONCLUSIVE)

    def test_missing_quantity_is_violated_when_claim_bearing(self) -> None:
        record = _proc("库存不足，建议进行采购。")
        self.assertEqual(_statuses(record)["REQ-01"], VIOLATED)
        self.assertEqual(fake_judge(_jinput(record)).status, FAIL)

    def test_explicit_quantity_violation(self) -> None:
        record = _proc(
            "库存为 5，采购 3 件。",
            suggest_qty=3,
        )
        self.assertEqual(_statuses(record, ORACLE_QTY5)["REQ-01"], VIOLATED)
        self.assertEqual(fake_judge(_jinput(record, ORACLE_QTY5)).status, FAIL)

    def test_no_final_message_is_evidence_gate_inconclusive(self) -> None:
        record = _proc("库存为 5，采购建议：采购 10 件。")
        record.steps = ()
        from llm_judge import assess_evidence

        self.assertEqual(
            assess_evidence(record, TASK_PROC, ORACLE_10).verdict,
            INSUFFICIENT,
        )
        self.assertEqual(fake_judge(_jinput(record)).status, INCONCLUSIVE)

    def test_cal_09_and_cal_17_dataset_labels(self) -> None:
        self.assertEqual(
            fake_judge(PHASE6D_DATASET.case("CAL-09").jinput()).status,
            FAIL,
        )
        self.assertEqual(
            fake_judge(PHASE6D_DATASET.case("CAL-17").jinput()).status,
            INCONCLUSIVE,
        )


class ProviderGuardTests(unittest.TestCase):
    def _stub_client(self, content: str, seen_prompts: list | None = None):
        def _create(**kwargs):
            if seen_prompts is not None:
                seen_prompts.append(kwargs["messages"][0]["content"])
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=content)),
                ],
                usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 10}),
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=_create))),
        )

    def _pass_payload(self) -> str:
        return json.dumps(
            {
                "status": PASS,
                "score": 1.0,
                "confidence": HIGH,
                "reasoning_summary": "confident pass",
                "findings": [],
            },
            ensure_ascii=False,
        )

    def test_llm_cannot_override_deterministic_violated(self) -> None:
        seen: list[str] = []
        provider = DeepSeekJudgeProvider(
            client=self._stub_client(self._pass_payload(), seen),
        )
        record = _proc("库存不足，建议进行采购。")
        result = provider.judge(_jinput(record), prompt_key="C")
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(f.criterion_id.startswith("CONDITION-") for f in result.findings))
        self.assertIn('"condition_assessments"', seen[0])

    def test_llm_cannot_upgrade_deterministic_unknown_to_pass(self) -> None:
        provider = DeepSeekJudgeProvider(client=self._stub_client(self._pass_payload()))
        record = _proc("建议进行采购。")
        result = provider.judge(_jinput(record), prompt_key="C")
        self.assertEqual((result.status, result.confidence), (INCONCLUSIVE, LOW))
        self.assertIsNone(result.score)

    def test_fake_and_real_guard_share_semantics(self) -> None:
        provider = DeepSeekJudgeProvider(client=self._stub_client(self._pass_payload()))
        for case_id in ("CAL-09", "CAL-17"):
            jinput = PHASE6D_DATASET.case(case_id).jinput()
            fake = fake_judge(jinput)
            real = provider.judge(jinput, prompt_key="C")
            self.assertEqual(fake.status, real.status, case_id)

    def test_llm_unknown_status_maps_to_inconclusive(self) -> None:
        record = _proc("库存为 5，采购建议：采购 10 件。")
        payload = json.dumps(
            {
                "status": PASS,
                "score": 1.0,
                "confidence": HIGH,
                "reasoning_summary": "unknown finding",
                "findings": [
                    {
                        "criterion_id": "CRITERION-02",
                        "status": UNKNOWN,
                        "message": "cannot determine",
                    },
                ],
            },
            ensure_ascii=False,
        )
        provider = DeepSeekJudgeProvider(client=self._stub_client(payload))
        result = provider.judge(_jinput(record), prompt_key="C")
        self.assertEqual((result.status, result.confidence), (INCONCLUSIVE, LOW))

    def test_run_record_persists_condition_fields(self) -> None:
        case = PHASE6D_DATASET.case("CAL-09")
        result = fake_judge(case.jinput())
        record = calibration_run_record(PHASE6D_DATASET, case, result)
        self.assertEqual(record["condition_verdict"], FAIL)
        self.assertEqual(record["aggregation_source"], "DETERMINISTIC")
        self.assertEqual(record["final_verdict"], FAIL)
        self.assertIn("condition_statuses", record)
        self.assertTrue(any(item["status"] == VIOLATED for item in record["condition_statuses"]))


if __name__ == "__main__":
    unittest.main()
