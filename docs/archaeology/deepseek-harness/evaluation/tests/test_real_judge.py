"""Phase 6-B real LLM Judge integration + calibration tests.

Provider-error mapping and contract guards run offline with stubbed clients.
Real E2E tests call DeepSeek through ``DeepSeekJudgeProvider``; if the
provider is unreachable they skip with ``BLOCKED`` rather than substituting a
fake judge.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    RateLimitError,
)

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
TESTS = Path(__file__).resolve().parent
for path in (EVAL, RUNTIME, TESTS):
    sys.path.insert(0, str(path))

from evaluator import evaluate  # noqa: E402
from judge_provider import (  # noqa: E402
    GOLDEN_CALIBRATION_CASES,
    INVALID_OUTPUT,
    PERMANENT,
    TIMEOUT,
    TRANSIENT,
    UNAVAILABLE,
    CalibrationMetrics,
    DeepSeekJudgeProvider,
    JudgeProviderError,
    calibration_metrics,
    provider_status,
    run_calibration,
)
from llm_judge import (  # noqa: E402
    FAIL,
    GOLDEN_RUBRIC,
    HIGH,
    INCONCLUSIVE,
    LLMJudgeInput,
    LOW,
    PASS,
    TASK_JUDGE_01,
    TASK_JUDGE_ORACLE,
    aggregate,
)
from models import EvaluationResult, Finding  # noqa: E402
from test_control_plane_e2e import PROC_001, _run_agentscope, _run_codex  # noqa: E402


def _record(**kwargs) -> SimpleNamespace:
    defaults = dict(
        record_version="5j.1",
        projection_rule_version="v2",
        execution_id="exec-6b",
        session_id="session-6b",
        replay_ref={
            "source": "event_log",
            "session_id": "session-6b",
            "execution_id": "exec-6b",
            "event_range": [1, 12],
            "record_version": "5j.1",
            "projection_rule_version": "v2",
        },
        initiator_ref={"ref": "agent-a", "source": "ADAPTER_DERIVED"},
        owner_refs=({"owner_type": "capability", "owner_id": "cap-c"},),
        attempts=(
            SimpleNamespace(
                execution_id="exec-6b",
                attempt_id="exec-6b/attempt-1",
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
        steps=(SimpleNamespace(assistant_messages=("库存为 5，采购建议：采购 10 件。",)),),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _det(
    status: str = PASS,
    *,
    task_id: str = "TASK-JUDGE-01",
    findings: tuple[Finding, ...] = (),
) -> EvaluationResult:
    return EvaluationResult("exec-6b", task_id, status, findings=tuple(findings))


def _jinput(
    record: SimpleNamespace | None = None,
    det: EvaluationResult | None = None,
) -> LLMJudgeInput:
    return LLMJudgeInput(
        task_specification=TASK_JUDGE_01,
        execution_record=record or _record(),
        deterministic_evaluation=det or _det(),
        rubric=GOLDEN_RUBRIC,
        oracle_reference=TASK_JUDGE_ORACLE,
    )


def _payload(
    status: str,
    *,
    score: float | None = 1.0,
    confidence: str = HIGH,
    reasoning: str = "stub reasoning",
    findings: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "status": status,
            "score": score,
            "confidence": confidence,
            "reasoning_summary": reasoning,
            "findings": findings or [],
        },
        ensure_ascii=False,
    )


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 10}),
    )


def _stub_client(content: str | None = None, error: BaseException | None = None):
    if error is not None:
        create = Mock(side_effect=error)
    else:
        create = Mock(return_value=_completion(content or _payload(PASS)))
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def _provider(**kwargs):
    return DeepSeekJudgeProvider(client=kwargs.pop("client", None), **kwargs)


class ProviderErrorMappingTests(unittest.TestCase):
    def test_provider_timeout(self) -> None:
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        provider = _provider(client=_stub_client(error=APITimeoutError(request=request)))
        with self.assertRaises(JudgeProviderError) as ctx:
            provider.judge(_jinput())
        self.assertEqual(ctx.exception.kind, TIMEOUT)

    def test_provider_invalid_output(self) -> None:
        provider = _provider(client=_stub_client(content="not json at all"))
        with self.assertRaises(JudgeProviderError) as ctx:
            provider.judge(_jinput())
        self.assertEqual(ctx.exception.kind, INVALID_OUTPUT)

    def test_provider_schema_mismatch(self) -> None:
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        cases = (
            _payload("MAYBE"),
            _payload(PASS, score="high"),
            _payload(PASS, confidence=LOW),
            _payload(INCONCLUSIVE, confidence=HIGH),
            _payload(PASS, findings=[{"status": PASS}]),
        )
        for content in cases:
            with self.subTest(content=content):
                provider = _provider(client=_stub_client(content=content))
                with self.assertRaises(JudgeProviderError) as ctx:
                    provider.judge(_jinput())
                self.assertEqual(ctx.exception.kind, INVALID_OUTPUT)
        self.assertIsInstance(request, httpx.Request)

    def test_provider_error_mapping(self) -> None:
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        cases = (
            (RateLimitError("slow down", response=httpx.Response(429, request=request), body=None), TRANSIENT),
            (APIConnectionError(message="down", request=request), UNAVAILABLE),
            (BadRequestError("bad", response=httpx.Response(400, request=request), body=None), PERMANENT),
        )
        for error, expected_kind in cases:
            with self.subTest(error=type(error).__name__):
                provider = _provider(client=_stub_client(error=error))
                with self.assertRaises(JudgeProviderError) as ctx:
                    provider.judge(_jinput())
                self.assertEqual(ctx.exception.kind, expected_kind)


class ContractGuardTests(unittest.TestCase):
    def test_missing_context_inconclusive(self) -> None:
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        result = provider.judge(_jinput(record=_record(context_provenance=())))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIsNone(result.score)

    def test_lossy_evidence_inconclusive(self) -> None:
        record = _record(
            lossiness=(
                {
                    "backend": "codex",
                    "mapping_quality": "LOSSY",
                    "missing_semantics": ["EXEC_SUCCESS"],
                },
            ),
        )
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        result = provider.judge(_jinput(record=record))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIsNone(result.score)

    def test_missing_final_message_inconclusive(self) -> None:
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        result = provider.judge(_jinput(record=_record(steps=())))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIn("final assistant message", result.reasoning_summary)

    def test_deterministic_fail_overrides_judge_pass(self) -> None:
        det = _det(
            FAIL,
            findings=(
                Finding(
                    "RULE-05",
                    FAIL,
                    "forbidden tool called: erp.force_write",
                    ({"execution_id": "exec-6b", "tool_call_id": "t3"},),
                ),
            ),
        )
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        judge = provider.judge(_jinput(det=det))
        unified = aggregate(det, (judge,))
        self.assertEqual(unified.final_status, FAIL)
        self.assertEqual(unified.confidence, HIGH)

    def test_judge_run_id_unique(self) -> None:
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        first = provider.judge(_jinput())
        second = provider.judge(_jinput())
        self.assertNotEqual(first.judge_id, second.judge_id)

    def test_result_immutable(self) -> None:
        provider = _provider(client=_stub_client(content=_payload(PASS)))
        result = provider.judge(_jinput())
        with self.assertRaises(FrozenInstanceError):
            result.status = FAIL  # type: ignore[misc]

    def test_no_runtime_import(self) -> None:
        source = Path(EVAL / "judge_provider.py").read_text(encoding="utf-8")
        for forbidden in (
            "import runtime",
            "from runtime",
            "import event_store",
            "from event_store",
            "import capability",
            "from capability",
            "import contextvars",
        ):
            self.assertNotIn(forbidden, source)


def _provider_or_skip() -> DeepSeekJudgeProvider:
    available, reason = provider_status()
    if not available:
        raise unittest.SkipTest(f"BLOCKED: {reason}")
    return DeepSeekJudgeProvider()


def _case(case_id: str):
    return next(case for case in GOLDEN_CALIBRATION_CASES if case.case_id == case_id)


class RealProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.provider = _provider_or_skip()

    def test_real_provider_pass(self) -> None:
        result = self.provider.judge(_case("TASK-JUDGE-01").jinput)
        self.assertEqual(result.status, PASS)
        self.assertIsNotNone(result.score)

    def test_real_provider_fail(self) -> None:
        result = self.provider.judge(_case("TASK-JUDGE-02").jinput)
        self.assertEqual(result.status, FAIL)

    def test_real_provider_inconclusive(self) -> None:
        result = self.provider.judge(_case("TASK-JUDGE-04").jinput)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)

    def test_real_deterministic_fail_overrides_judge_pass(self) -> None:
        det = _det(
            FAIL,
            findings=(
                Finding(
                    "RULE-05",
                    FAIL,
                    "forbidden tool called: erp.force_write",
                    ({"execution_id": "exec-6b", "tool_call_id": "t3"},),
                ),
            ),
        )
        judge = self.provider.judge(_jinput(det=det))
        unified = aggregate(det, (judge,))
        self.assertEqual(unified.final_status, FAIL)

    def test_prompt_sensitivity(self) -> None:
        case = _case("TASK-JUDGE-05")
        a = self.provider.judge(case.jinput, prompt_key="A")
        b = self.provider.judge(case.jinput, prompt_key="B")
        self.assertEqual(a.prompt_ref, "prompt:phase6b:judge:A:v1")
        self.assertEqual(b.prompt_ref, "prompt:phase6b:judge:B:v1")
        self.assertNotEqual(a.judge_id, b.judge_id)
        differs = (a.status, a.score, a.confidence) != (b.status, b.score, b.confidence)
        self.assertIn(differs, (True, False))

    def test_model_variance(self) -> None:
        provider = DeepSeekJudgeProvider(temperature=0.7, seed=None)
        case = _case("TASK-JUDGE-01")
        results = [provider.judge(case.jinput) for _ in range(3)]
        self.assertEqual(len({result.judge_id for result in results}), 3)
        self.assertIsNone(provider.seed)
        statuses = {result.status for result in results}
        scores = [result.score for result in results if result.score is not None]
        confidences = {result.confidence for result in results}
        self.assertTrue(statuses)
        self.assertTrue(confidences)
        self.assertLessEqual(len(scores), len(results))

    def test_context_sensitivity(self) -> None:
        full = self.provider.judge(_case("TASK-JUDGE-01").jinput)
        missing = self.provider.judge(
            _jinput(record=_record(context_provenance=())),
        )
        self.assertEqual(full.status, PASS)
        self.assertEqual(missing.status, INCONCLUSIVE)
        self.assertEqual(missing.confidence, LOW)
        self.assertEqual(full.confidence, HIGH)

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
        result = self.provider.judge(_jinput(record=record))
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(result.confidence, LOW)
        self.assertIn("LOSSY", result.reasoning_summary)

    def test_calibration_metrics(self) -> None:
        metrics, results = run_calibration(self.provider)
        self.assertIsInstance(metrics, CalibrationMetrics)
        self.assertEqual(metrics.sample_size, len(GOLDEN_CALIBRATION_CASES))
        self.assertEqual(len(results), len(GOLDEN_CALIBRATION_CASES))
        self.assertFalse(metrics.statistically_meaningful)
        self.assertEqual(metrics.significance, "NOT_STATISTICALLY_MEANINGFUL")
        for value in (
            metrics.agreement_rate,
            metrics.false_pass_rate,
            metrics.false_fail_rate,
            metrics.inconclusive_rate,
        ):
            self.assertTrue(0.0 <= value <= 1.0)


class RealProviderCrossBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.provider = _provider_or_skip()

    async def test_cross_backend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6b-cross-") as td:
            tmp = Path(td)
            results = {}
            for backend in ("agentscope", "codex"):
                session_id = f"phase6b-{backend}-judge"
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
                jinput = LLMJudgeInput(
                    PROC_001,
                    record,
                    evaluate(record, PROC_001),
                    GOLDEN_RUBRIC,
                    TASK_JUDGE_ORACLE,
                )
                results[backend] = self.provider.judge(jinput)
        agentscope, codex = results["agentscope"], results["codex"]
        self.assertEqual(agentscope.status, codex.status)
        self.assertEqual(agentscope.score, codex.score)
        for field in (
            "confidence",
            "model_ref",
            "model_version",
            "prompt_ref",
            "prompt_version",
            "rubric_ref",
        ):
            self.assertEqual(
                getattr(agentscope, field),
                getattr(codex, field),
            )
        self.assertNotEqual(agentscope.judge_id, codex.judge_id)
        self.assertTrue(agentscope.evidence_refs)
        self.assertTrue(codex.evidence_refs)
        self.assertNotEqual(agentscope.evidence_refs, codex.evidence_refs)


class CalibrationCaseTests(unittest.TestCase):
    def test_golden_calibration_cases(self) -> None:
        self.assertEqual(
            tuple(case.case_id for case in GOLDEN_CALIBRATION_CASES),
            tuple(f"TASK-JUDGE-{i:02d}" for i in range(1, 8)),
        )
        for case in GOLDEN_CALIBRATION_CASES:
            self.assertEqual(case.rubric_version, GOLDEN_RUBRIC.version)
            self.assertIn(case.expected_status, (PASS, FAIL, INCONCLUSIVE))
            self.assertIn(case.expected_confidence, (HIGH, "MEDIUM", LOW))
            if case.expected_score_range is not None:
                low, high = case.expected_score_range
                self.assertTrue(0.0 <= low <= high <= 1.0)
            self.assertTrue(case.jinput.execution_record is not None)

    def test_calibration_metrics_math(self) -> None:
        metrics = calibration_metrics(
            (
                (PASS, PASS),
                (FAIL, PASS),
                (PASS, FAIL),
                (FAIL, INCONCLUSIVE),
                (INCONCLUSIVE, INCONCLUSIVE),
            ),
        )
        self.assertEqual(metrics.sample_size, 5)
        self.assertEqual(metrics.agreement_rate, 0.4)
        self.assertEqual(metrics.false_pass_rate, 0.2)
        self.assertEqual(metrics.false_fail_rate, 0.2)
        self.assertEqual(metrics.inconclusive_rate, 0.4)
        self.assertFalse(metrics.statistically_meaningful)


if __name__ == "__main__":
    unittest.main()
