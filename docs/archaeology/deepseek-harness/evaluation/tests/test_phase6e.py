"""Phase 6-E offline tests: shared guard entry + semantic probes.

No network, no real LLM. The deterministic guard must be one shared entry
(``llm_judge.contract_guard``) used by both fake_judge and provider adapters;
the two synthetic probes isolate the semantic (LLM) layer from the
deterministic layer.
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
for path in (EVAL, RUNTIME):
    sys.path.insert(0, str(path))

from calibration import (  # noqa: E402
    PHASE6D_DATASET,
    PHASE6E_PROBES,
    calibration_run_record,
    probe_run_record,
)
from judge_provider import (  # noqa: E402
    PROMPT_TEMPLATES,
    DeepSeekJudgeProvider,
    provider_status,
)
from llm_judge import (  # noqa: E402
    FAIL,
    HIGH,
    INCONCLUSIVE,
    LLMJudgeResult,
    PASS,
    contract_guard,
    fake_judge,
)


def _stub_client(content: str) -> SimpleNamespace:
    def _create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 10}),
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=_create))),
    )


def _pass_payload() -> str:
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


def _raw_pass(jinput, *, prompt_ref="prompt:phase6e:raw:v1") -> LLMJudgeResult:
    return LLMJudgeResult(
        judge_id=f"{jinput.execution_record.execution_id}:raw",
        status=PASS,
        score=1.0,
        reasoning_summary="raw LLM says PASS",
        findings=(),
        evidence_refs=(),
        confidence=HIGH,
        model_ref="stub-llm",
        model_version="1",
        prompt_ref=prompt_ref,
        prompt_version="1",
        rubric_ref={"rubric_id": jinput.rubric.rubric_id, "version": jinput.rubric.version},
    )


class SharedGuardTests(unittest.TestCase):
    def test_provider_result_equals_shared_guard_on_raw_parse(self) -> None:
        jinput = PHASE6D_DATASET.case("CAL-09").jinput()
        provider = DeepSeekJudgeProvider(client=_stub_client(_pass_payload()))
        result = provider.judge(jinput, prompt_key="C")
        payload = json.loads(_pass_payload())
        raw = provider._parse(jinput, jinput.rubric, payload, PROMPT_TEMPLATES["C"])
        expected = replace(contract_guard(jinput, raw), judge_id=result.judge_id)
        self.assertEqual(result, expected)
        self.assertEqual(result.status, FAIL)

    def test_shared_guard_distinguishes_deterministic_and_semantic_layers(
        self,
    ) -> None:
        # Deterministic gates: LLM PASS cannot survive.
        for case_id in ("CAL-09", "CAL-17"):
            jinput = PHASE6D_DATASET.case(case_id).jinput()
            guarded = contract_guard(jinput, _raw_pass(jinput))
            self.assertNotEqual(guarded.status, PASS, case_id)
        # Semantic-only probes: raw LLM PASS passes through the guard.
        for probe in PHASE6E_PROBES:
            guarded = contract_guard(probe.jinput, _raw_pass(probe.jinput))
            self.assertEqual(guarded.status, PASS, probe.case_id)

    def test_fake_judge_and_stub_provider_share_guard_semantics(self) -> None:
        provider = DeepSeekJudgeProvider(client=_stub_client(_pass_payload()))
        for case_id in ("CAL-09", "CAL-17"):
            jinput = PHASE6D_DATASET.case(case_id).jinput()
            self.assertEqual(fake_judge(jinput).status, provider.judge(jinput, prompt_key="C").status)


class ProbeTests(unittest.TestCase):
    def test_s1_fake_fails_but_guard_does_not_force(self) -> None:
        probe = PHASE6E_PROBES[0]
        self.assertEqual(probe.case_id, "PROBE-S1")
        self.assertEqual(probe.expected_status, FAIL)
        # fake semantic layer catches the expected_constraints violation.
        self.assertEqual(fake_judge(probe.jinput).status, FAIL)
        # deterministic guard has no hold on expected_constraints (oracle gap E).
        self.assertEqual(contract_guard(probe.jinput, _raw_pass(probe.jinput)).status, PASS)

    def test_s2_is_observational_semantic_only(self) -> None:
        probe = PHASE6E_PROBES[1]
        self.assertEqual(probe.case_id, "PROBE-S2")
        self.assertIsNone(probe.expected_status)
        # no deterministic verdict: raw PASS passes through unchanged.
        self.assertEqual(contract_guard(probe.jinput, _raw_pass(probe.jinput)).status, PASS)


class ArtifactSchemaTests(unittest.TestCase):
    def test_phase6e_record_fields(self) -> None:
        case = PHASE6D_DATASET.case("CAL-09")
        result = fake_judge(case.jinput())
        record = calibration_run_record(
            PHASE6D_DATASET,
            case,
            result,
            backend_ref="fake",
            raw_payload={"status": PASS},
        )
        for field in (
            "backend_ref",
            "provider_ref",
            "prompt_ref",
            "deterministic_verdict",
            "unified_final_verdict",
            "unified_confidence",
            "llm_fallback_used",
            "raw_payload_normalized",
            "aggregation_source",
        ):
            self.assertIn(field, record)
        self.assertEqual(record["backend_ref"], "fake")
        self.assertEqual(record["deterministic_verdict"], FAIL)
        self.assertEqual(record["unified_final_verdict"], FAIL)
        self.assertFalse(record["llm_fallback_used"])
        self.assertEqual(record["raw_payload_normalized"]["status"], PASS)

    def test_judge_layer_and_unified_layer_are_separate(self) -> None:
        case = PHASE6D_DATASET.case("TASK-JUDGE-03")
        result = fake_judge(case.jinput())
        self.assertEqual(result.status, PASS)
        record = calibration_run_record(PHASE6D_DATASET, case, result, backend_ref="fake")
        self.assertEqual(record["final_verdict"], PASS)
        self.assertEqual(record["unified_final_verdict"], FAIL)

    def test_probe_record_uses_same_schema(self) -> None:
        probe = PHASE6E_PROBES[0]
        record = probe_run_record(
            probe,
            fake_judge(probe.jinput),
            backend_ref="fake",
        )
        self.assertEqual(record["dataset_id"], "calibration:phase6e:probes")
        self.assertEqual(record["dataset_version"], "2")
        self.assertEqual(record["case_id"], "PROBE-S1")
        self.assertEqual(record["final_verdict"], FAIL)


class ProviderMetadataTests(unittest.TestCase):
    def test_provider_status_prefers_provider_model_over_global(self) -> None:
        cfg = {
            "model": "deepseek-v4-flash",
            "model_providers": {
                "deepseek": {"base_url": "https://api.deepseek.com"},
                "Model_Studio_Token_Plan_Personal": {
                    "base_url": "https://example.invalid/v1",
                    "model": "qwen3.7-plus",
                },
            },
        }
        provider_status.cache_clear()
        with (
            patch("judge_provider.tomllib.loads", return_value=cfg),
            patch("judge_provider._provider_credentials", return_value=("https://example.invalid/v1", "sk-test")),
            patch("judge_provider.OpenAI") as openai_cls,
        ):
            openai_cls.return_value.models.list.return_value = SimpleNamespace(
                data=[SimpleNamespace(id="qwen3.7-plus")]
            )
            ok, reason = provider_status("Model_Studio_Token_Plan_Personal")
            deepseek_ok, deepseek_reason = provider_status("deepseek")
        self.assertTrue(ok)
        self.assertIn("provider=Model_Studio_Token_Plan_Personal model=qwen3.7-plus", reason)
        self.assertNotIn("model=deepseek-v4-flash", reason)
        # DeepSeek keeps its global model when the provider entry has none.
        self.assertTrue(deepseek_ok)
        self.assertIn("provider=deepseek model=deepseek-v4-flash", deepseek_reason)
        provider_status.cache_clear()


if __name__ == "__main__":
    unittest.main()
