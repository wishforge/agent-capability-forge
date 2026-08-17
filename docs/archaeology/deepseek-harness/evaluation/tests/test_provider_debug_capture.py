"""Phase 6-E.3 diagnostic capture tests (offline, stubbed client).

Covers: PASS capture, rejection capture, unchanged decisions, non-empty raw
payload, and no secret leakage into debug artifacts.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[1]
for path in (EVAL, EVAL.parent / "runtime"):
    sys.path.insert(0, str(path))

from calibration import PHASE6D_DATASET  # noqa: E402
from judge_provider import (  # noqa: E402
    PROMPT_TEMPLATES,
    INVALID_OUTPUT,
    DeepSeekJudgeProvider,
    JudgeProviderError,
)
from llm_judge import HIGH, INCONCLUSIVE, LOW, PASS, contract_guard  # noqa: E402
from phase6e_matrix import _error_record, write_debug_evidence  # noqa: E402


def _stub_client(content: str) -> SimpleNamespace:
    def _create(**kwargs):
        return SimpleNamespace(
            id="chatcmpl-test",
            model="qwen3.7-plus",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 10}),
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=_create))),
    )


def _payload(status: str, confidence: str) -> str:
    return json.dumps(
        {
            "status": status,
            "score": 1.0 if status == PASS else None,
            "confidence": confidence,
            "reasoning_summary": "stub reasoning",
            "findings": [],
        },
        ensure_ascii=False,
    )


class ProviderDebugCaptureTests(unittest.TestCase):
    def test_pass_capture(self) -> None:
        content = _payload(PASS, HIGH)
        provider = DeepSeekJudgeProvider(
            client=_stub_client(content),
            api_key="sk-test-secret-123",
        )
        jinput = PHASE6D_DATASET.case("CAL-18").jinput()
        result = provider.judge(jinput, prompt_key="B")
        self.assertEqual(result.status, PASS)
        self.assertEqual(provider.last_raw_content, content)
        self.assertEqual(
            provider.last_raw_response["choices"][0]["message"]["content"],
            content,
        )
        evidence = provider._evidence(
            stage="contract",
            reason=None,
            raw_payload=provider.last_payload,
            parsed={"status": PASS, "confidence": HIGH, "score": 1.0},
        )
        self.assertEqual(evidence["contract"]["decision"], "ACCEPT")
        self.assertEqual(evidence["parsed"]["status"], PASS)
        self.assertEqual(len(evidence["prompt_hash"]), 64)

    def test_rejection_capture_preserves_raw_payload(self) -> None:
        content = _payload(PASS, LOW)
        provider = DeepSeekJudgeProvider(client=_stub_client(content))
        jinput = PHASE6D_DATASET.case("CAL-16").jinput()
        with self.assertRaises(JudgeProviderError) as ctx:
            provider.judge(jinput, prompt_key="B")
        self.assertEqual(ctx.exception.kind, INVALID_OUTPUT)
        evidence = ctx.exception.evidence
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["parsed"]["status"], PASS)
        self.assertEqual(evidence["parsed"]["confidence"], LOW)
        self.assertEqual(evidence["contract"]["decision"], "REJECT")
        self.assertEqual(
            evidence["contract"]["reason"],
            "low-confidence PASS is forbidden",
        )
        self.assertEqual(evidence["raw_content"], content)
        self.assertEqual(evidence["raw_payload"]["status"], PASS)
        self.assertTrue(evidence["raw_content"])
        self.assertEqual(evidence["prompt_id"], "prompt:phase6b:judge:B:v1")

    def test_capture_does_not_change_decision_semantics(self) -> None:
        content = _payload(PASS, HIGH)
        provider = DeepSeekJudgeProvider(client=_stub_client(content))
        jinput = PHASE6D_DATASET.case("CAL-16").jinput()
        result = provider.judge(jinput, prompt_key="B")
        raw = provider._parse(jinput, jinput.rubric, provider.last_payload, PROMPT_TEMPLATES["B"])
        expected = replace(contract_guard(jinput, raw), judge_id=result.judge_id)
        self.assertEqual(result, expected)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        # Rejection path still raises the same kind and message.
        with self.assertRaises(JudgeProviderError) as ctx:
            _raise_low_pass(provider, jinput)
        self.assertEqual(ctx.exception.kind, INVALID_OUTPUT)
        self.assertEqual(str(ctx.exception), "low-confidence PASS is forbidden")

    def test_no_secret_in_artifact(self) -> None:
        secret = "sk-test-secret-abc123"
        provider = DeepSeekJudgeProvider(
            client=_stub_client(_payload(PASS, LOW)),
            api_key=secret,
        )
        jinput = PHASE6D_DATASET.case("CAL-16").jinput()
        with self.assertRaises(JudgeProviderError) as ctx:
            provider.judge(jinput, prompt_key="B")
        evidence = dict(ctx.exception.evidence)
        evidence.update(
            case_id="CAL-16",
            prompt_key="B",
            timestamp="2026-08-17T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory(prefix="phase6e3-debug-") as td:
            path = Path(td) / "CAL-16-model_studio-B.json"
            write_debug_evidence(evidence, path)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, text)
            self.assertNotIn("api_key", text)
            self.assertIn("raw_content", json.loads(text))

    def test_error_record_writes_debug_artifact(self) -> None:
        provider = DeepSeekJudgeProvider(client=_stub_client(_payload(PASS, LOW)))
        jinput = PHASE6D_DATASET.case("CAL-16").jinput()
        with self.assertRaises(JudgeProviderError) as ctx:
            provider.judge(jinput, prompt_key="B")
        with tempfile.TemporaryDirectory(prefix="phase6e3-debug-") as td:
            with patch("phase6e_matrix.DEBUG_DIR", Path(td)):
                record = _error_record(
                    "CAL-16",
                    "B",
                    "model_studio",
                    ctx.exception,
                    provider=provider,
                )
            self.assertIn("debug_artifact", record)
            artifact = Path(td) / "CAL-16-model_studio-B.json"
            self.assertTrue(artifact.exists())
            data = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(data["case_id"], "CAL-16")
            self.assertEqual(data["contract"]["decision"], "REJECT")


def _raise_low_pass(provider: DeepSeekJudgeProvider, jinput) -> None:
    provider.last_raw_content = _payload(PASS, LOW)
    payload = json.loads(provider.last_raw_content)
    provider._parse(jinput, jinput.rubric, payload, PROMPT_TEMPLATES["B"])


if __name__ == "__main__":
    unittest.main()
