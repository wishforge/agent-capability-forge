"""Phase 6-B real provider adapter for the Phase 6-A LLM Judge contract.

Evaluation-side only: this module never imports runtime / EventStore /
Capability Manager / ContextVar. Provider-specific code (DeepSeek via the
OpenAI-compatible SDK) is isolated here; ``llm_judge.py`` and ``evaluator.py``
stay untouched.

Layout:

    evaluator / llm_judge
        |
        v
    JudgeProvider (this module)
        |
        v
    DeepSeekJudgeProvider -> OpenAI-compatible SDK -> api.deepseek.com

Secrets are read from process environment / existing ``~/.codex/config.toml``
at runtime and never written into this repository.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tomllib
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Mapping, Protocol
from uuid import uuid4

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    OpenAI,
)

from evaluator import evaluate
from llm_judge import (
    FAIL,
    GOLDEN_RUBRIC,
    HIGH,
    INCONCLUSIVE,
    JudgeFinding,
    JudgePromptTemplate,
    JudgeRubric,
    LLMJudgeInput,
    LLMJudgeResult,
    LOW,
    MEDIUM,
    PASS,
    UNKNOWN,
    OracleReference,
    TASK_JUDGE_01,
    TASK_JUDGE_01_RECORD,
    TASK_JUDGE_02,
    TASK_JUDGE_02_RECORD,
    TASK_JUDGE_03,
    TASK_JUDGE_03_RECORD,
    TASK_JUDGE_04,
    TASK_JUDGE_04_RECORD,
    TASK_JUDGE_ORACLE,
    TaskSpecification,
    _STATUSES,
    _CONFIDENCES,
    _context_provenance,
    assess_evidence,
    assess_conditions,
    check_behavioral,
    contract_guard,
    condition_verdict,
    _dedupe_refs,
    _default_evidence,
    _final_messages,
    _get,
    _has_lossy_evidence,
    _judge_record,
    _overall_status,
)

TRANSIENT = "TRANSIENT"
PERMANENT = "PERMANENT"
INVALID_OUTPUT = "INVALID_OUTPUT"
TIMEOUT = "TIMEOUT"
UNAVAILABLE = "UNAVAILABLE"

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class JudgeProviderError(Exception):
    """Normalized provider failure; never treated as an agent failure."""

    def __init__(self, kind: str, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.cause = cause


def _deepseek_config() -> tuple[str, str, str]:
    """Existing-config loader; same source as research/control-plane-loop."""
    cfg = tomllib.loads(
        pathlib.Path(os.path.expanduser("~/.codex/config.toml")).read_text(
            encoding="utf-8"
        ),
    )
    prov = cfg["model_providers"]["deepseek"]
    return (
        prov["base_url"].rstrip("/"),
        prov["experimental_bearer_token"],
        cfg.get("model", DEFAULT_MODEL),
    )


def _provider_credentials(name: str) -> tuple[str, str]:
    """Resolve (base_url, api_key) for an OpenAI-compatible provider entry.

    Secrets are consumed in-process and never returned to callers that log
    them; the returned key is used only to construct an SDK client.
    """
    cfg = tomllib.loads(
        pathlib.Path(os.path.expanduser("~/.codex/config.toml")).read_text(
            encoding="utf-8"
        ),
    )
    prov = cfg["model_providers"][name]
    base_url = prov["base_url"].rstrip("/")
    token = prov.get("experimental_bearer_token")
    if token:
        return base_url, token
    env_key = prov.get("env_key")
    if env_key:
        token = os.environ.get(env_key)
        if token:
            return base_url, token
        raise KeyError(f"env_key {env_key!r} not set")
    raise KeyError(f"provider {name!r} has no credential source")


def _provider_model(name: str) -> str:
    cfg = tomllib.loads(
        pathlib.Path(os.path.expanduser("~/.codex/config.toml")).read_text(
            encoding="utf-8"
        ),
    )
    return (
        cfg["model_providers"][name].get("model")
        or cfg.get("model")
        or DEFAULT_MODEL
    )


@lru_cache(maxsize=4)
def provider_status(name: str = "deepseek") -> tuple[bool, str]:
    """True if the named OpenAI-compatible provider is reachable; never
    returns or logs the secret."""
    try:
        base_url, api_key = _provider_credentials(name)
        model = _provider_model(name)
    except Exception as exc:
        return False, f"config unavailable: {type(exc).__name__}: {exc}"
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=8.0,
            max_retries=0,
        )
        models = client.models.list()
        return True, f"provider={name} model={model} models={sorted(m.id for m in models.data)}"
    except Exception as exc:
        return False, f"unreachable: {type(exc).__name__}: {str(exc)[:120]}"


class JudgeProvider(Protocol):
    def judge(
        self,
        jinput: LLMJudgeInput,
        rubric: JudgeRubric | None = None,
        *,
        prompt_key: str = "A",
    ) -> LLMJudgeResult: ...


def _to_plain(obj: Any) -> Any:
    """Recursively convert evaluation-facing objects to JSON-safe values."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if callable(obj):
        return None
    if isinstance(obj, Mapping):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return _to_plain(obj.model_dump())
    if hasattr(obj, "__dataclass_fields__"):
        return {
            f.name: _to_plain(getattr(obj, f.name))
            for f in fields(obj)
        }
    if hasattr(obj, "__dict__"):
        return {
            k: _to_plain(v)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }
    return str(obj)


def _render_execution(record: Any) -> dict:
    plain = _to_plain(record)
    plain["final_messages"] = list(_final_messages(record))
    plain["context_provenance_present"] = bool(_context_provenance(record))
    plain["has_lossy_evidence"] = _has_lossy_evidence(record)
    return plain


def _render_prompt(jinput: LLMJudgeInput, rubric: JudgeRubric, template: JudgePromptTemplate) -> str:
    assessment = assess_evidence(
        jinput.execution_record,
        jinput.task_specification,
        jinput.oracle_reference,
    )
    behavioral = check_behavioral(
        jinput.execution_record,
        jinput.task_specification,
        jinput.oracle_reference,
    )
    conditions = assess_conditions(jinput.execution_record, jinput.oracle_reference)
    evidence = {
        "task_specification": _to_plain(jinput.task_specification),
        "execution_record": _render_execution(jinput.execution_record),
        "deterministic_evaluation": _to_plain(jinput.deterministic_evaluation),
        "rubric": _to_plain(rubric),
        "oracle_reference": _to_plain(jinput.oracle_reference),
        "evidence_refs": [dict(ref) for ref in jinput.evidence_refs],
        "evidence_sufficiency": {
            "verdict": assessment.verdict,
            "reasons": list(assessment.reasons),
            "missing_observations": list(assessment.missing_observations),
        },
        "behavioral_constraints": [
            {"rule_id": finding.rule_id, "status": finding.status, "message": finding.message}
            for finding in behavioral
        ],
        "condition_assessments": [
            {
                "condition_id": assessment.condition_id,
                "polarity": assessment.polarity,
                "status": assessment.status,
                "reason": assessment.reason,
            }
            for assessment in conditions
        ],
        "condition_verdict": condition_verdict(conditions),
    }
    payload = json.dumps(evidence, ensure_ascii=False, indent=2)
    schema = (
        '{"status": "PASS|FAIL|INCONCLUSIVE", '
        '"score": 0.0-1.0 or null, '
        '"confidence": "HIGH|MEDIUM|LOW", '
        '"reasoning_summary": "string", '
        '"findings": [{"criterion_id": "...", "status": "...", '
        '"message": "...", "evidence_refs": [{"execution_id": "...", '
        '"step_id": "..."}]}]}'
    )
    if template.prompt_ref.endswith(":C:v1"):
        instructions = (
            "You are an independent semantic judge. The JSON input includes "
            "evidence_sufficiency and behavioral_constraints computed "
            "deterministically, and both are authoritative: if "
            "evidence_sufficiency.verdict is not SUFFICIENT, return "
            "INCONCLUSIVE with LOW confidence; if any "
            "behavioral_constraints entry has status FAIL, return FAIL "
            "regardless of the final answer. condition_assessments are also "
            "deterministic and authoritative: any VIOLATED condition forces "
            "FAIL, any UNKNOWN condition forces INCONCLUSIVE, and neither may "
            "be overridden. Judge semantic criteria "
            "strictly from evidence actually present; never infer missing "
            "facts."
        )
    elif template.prompt_ref.endswith(":A:v1"):
        instructions = (
            "You are an independent semantic judge. Judge the execution "
            "strictly from the evidence in the JSON input below. Do not guess "
            "or supply facts the record does not contain. If evidence is "
            "missing, lossy, or insufficient for any required criterion, "
            "return INCONCLUSIVE with LOW confidence."
        )
    else:
        instructions = (
            "Assess the provided execution record against the rubric. Base "
            "every verdict on evidence that is actually present. Never infer "
            "unshown facts. Mark INCONCLUSIVE with LOW confidence whenever the "
            "evidence cannot support a definite verdict, including lossy or "
            "missing context."
        )
    return (
        f"{instructions}\n\nJSON input:\n{payload}\n\n"
        f'Return one valid JSON object exactly matching this shape:\n{schema}'
    )


PROMPT_TEMPLATES = {
    "A": JudgePromptTemplate("prompt:phase6b:judge:A:v1", "1"),
    "B": JudgePromptTemplate("prompt:phase6b:judge:B:v1", "1"),
    "C": JudgePromptTemplate("prompt:phase6d:judge:C:v1", "1"),
}


def _usage_dict(response: Any) -> dict | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage)


class DeepSeekJudgeProvider:
    """First real provider: DeepSeek via the OpenAI-compatible SDK."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 0,
        temperature: float = 0.0,
        seed: int | None = 42,
        max_tokens: int = 8192,
        prompt_key: str = "A",
        backend_ref: str = "deepseek",
        client: Any = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens
        self.prompt_key = prompt_key
        self.backend_ref = backend_ref
        self._client = client
        self.last_usage: dict | None = None
        self.last_payload: dict | None = None

    def _ensure_client(self) -> OpenAI:
        if self._client is None:
            if not self.base_url or not self.api_key:
                base_url, api_key, configured_model = _deepseek_config()
                self.base_url = base_url
                self.api_key = api_key
                if self.model == DEFAULT_MODEL:
                    self.model = configured_model
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def _create(self, prompt: str) -> dict:
        client = self._ensure_client()
        kwargs = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        if self.seed is not None:
            kwargs["seed"] = self.seed
        try:
            response = client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            raise JudgeProviderError(TIMEOUT, f"provider timeout: {exc}", exc) from exc
        except (RateLimitError, InternalServerError) as exc:
            raise JudgeProviderError(TRANSIENT, f"provider transient error: {exc}", exc) from exc
        except APIConnectionError as exc:
            raise JudgeProviderError(UNAVAILABLE, f"provider unreachable: {exc}", exc) from exc
        except (AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError) as exc:
            raise JudgeProviderError(PERMANENT, f"provider permanent error: {exc}", exc) from exc
        except APIStatusError as exc:
            raise JudgeProviderError(TRANSIENT, f"provider status error: {exc}", exc) from exc
        except Exception as exc:
            raise JudgeProviderError(TRANSIENT, f"provider error: {exc}", exc) from exc

        self.last_usage = _usage_dict(response)
        content = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match is None:
            raise JudgeProviderError(INVALID_OUTPUT, "no JSON object in provider output")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise JudgeProviderError(INVALID_OUTPUT, f"malformed JSON: {exc}", exc) from exc
        if not isinstance(payload, dict):
            raise JudgeProviderError(INVALID_OUTPUT, "provider output is not a JSON object")
        return payload

    def _parse(
        self,
        jinput: LLMJudgeInput,
        rubric: JudgeRubric,
        payload: dict,
        template: JudgePromptTemplate,
    ) -> LLMJudgeResult:
        status = "INCONCLUSIVE" if payload.get("status") == UNKNOWN else payload.get("status")
        confidence = payload.get("confidence")
        score = payload.get("score")
        if status not in _STATUSES:
            raise JudgeProviderError(INVALID_OUTPUT, f"invalid status {status!r}")
        if confidence not in _CONFIDENCES:
            raise JudgeProviderError(INVALID_OUTPUT, f"invalid confidence {confidence!r}")
        if status == PASS and confidence == LOW:
            raise JudgeProviderError(INVALID_OUTPUT, "low-confidence PASS is forbidden")
        if status == INCONCLUSIVE and confidence == HIGH:
            raise JudgeProviderError(INVALID_OUTPUT, "INCONCLUSIVE must not be HIGH confidence")
        if score is not None and not isinstance(score, (int, float)):
            raise JudgeProviderError(INVALID_OUTPUT, f"invalid score {score!r}")
        if score is not None and not (0.0 <= score <= 1.0):
            raise JudgeProviderError(INVALID_OUTPUT, f"score out of range: {score!r}")
        model_findings = payload.get("findings")
        if model_findings is not None and not isinstance(model_findings, list):
            raise JudgeProviderError(INVALID_OUTPUT, "findings must be a list")
        by_id: dict[str, dict] = {}
        for finding in model_findings or []:
            if not isinstance(finding, dict) or "criterion_id" not in finding:
                raise JudgeProviderError(INVALID_OUTPUT, "malformed finding")
            by_id[finding["criterion_id"]] = finding

        findings: list[JudgeFinding] = []
        for criterion in rubric.criteria:
            raw = by_id.get(criterion.criterion_id, {})
            finding_status = raw.get("status", status)
            if finding_status == UNKNOWN:
                finding_status = INCONCLUSIVE
            if finding_status not in _STATUSES:
                raise JudgeProviderError(
                    INVALID_OUTPUT,
                    f"invalid finding status {finding_status!r}",
                )
            refs = tuple(
                dict(ref)
                for ref in raw.get(
                    "evidence_refs",
                    _default_evidence(jinput, criterion.criterion_id),
                )
                if isinstance(ref, dict)
            )
            message = raw.get(
                "message",
                f"real judge: {finding_status} for {criterion.criterion_id}",
            )
            if criterion.required and finding_status != INCONCLUSIVE and not refs:
                findings.append(
                    JudgeFinding(
                        criterion.criterion_id,
                        INCONCLUSIVE,
                        "required criterion lacks evidence; UNSUPPORTED",
                        (),
                    ),
                )
            else:
                findings.append(
                    JudgeFinding(criterion.criterion_id, finding_status, message, refs),
                )

        overall = _overall_status(tuple(findings))
        if overall == INCONCLUSIVE:
            final_score = None
            final_confidence = LOW
        else:
            final_score = score
            final_confidence = confidence
        return LLMJudgeResult(
            judge_id=f"{_get(jinput.execution_record, 'execution_id')}:real:{uuid4().hex}",
            status=overall,
            score=final_score,
            reasoning_summary=str(
                payload.get("reasoning_summary") or f"real judge: {overall}",
            ),
            findings=tuple(findings),
            evidence_refs=_dedupe_refs(
                ref for finding in findings for ref in finding.evidence_refs
            ),
            confidence=final_confidence,
            model_ref=f"{self.backend_ref}:{self.model}",
            model_version="UNKNOWN",
            prompt_ref=template.prompt_ref,
            prompt_version=template.prompt_version,
            rubric_ref={"rubric_id": rubric.rubric_id, "version": rubric.version},
        )

    def judge(
        self,
        jinput: LLMJudgeInput,
        rubric: JudgeRubric | None = None,
        *,
        prompt_key: str | None = None,
    ) -> LLMJudgeResult:
        rubric = rubric or jinput.rubric
        template = PROMPT_TEMPLATES[prompt_key or self.prompt_key]
        payload = self._create(_render_prompt(jinput, rubric, template))
        self.last_payload = payload
        result = self._parse(jinput, rubric, payload, template)
        return contract_guard(jinput, result)


@dataclass(frozen=True, slots=True)
class JudgeCalibrationCase:
    case_id: str
    jinput: LLMJudgeInput
    expected_status: str
    expected_score_range: tuple[float, float] | None
    expected_confidence: str
    rubric_version: str

    def __post_init__(self) -> None:
        if self.expected_status not in _STATUSES:
            raise ValueError(f"invalid expected_status {self.expected_status!r}")
        if self.expected_confidence not in _CONFIDENCES:
            raise ValueError(f"invalid expected_confidence {self.expected_confidence!r}")
        if self.expected_score_range is not None:
            low, high = self.expected_score_range
            if not (0.0 <= low <= high <= 1.0):
                raise ValueError(f"invalid expected_score_range {self.expected_score_range!r}")


def _calibration_case(
    case_id: str,
    task: TaskSpecification,
    record: Any,
    oracle: OracleReference,
    expected_status: str,
    expected_score_range: tuple[float, float] | None,
    expected_confidence: str,
) -> JudgeCalibrationCase:
    return JudgeCalibrationCase(
        case_id=case_id,
        jinput=LLMJudgeInput(
            task,
            record,
            evaluate(record, task),
            GOLDEN_RUBRIC,
            oracle,
        ),
        expected_status=expected_status,
        expected_score_range=expected_score_range,
        expected_confidence=expected_confidence,
        rubric_version=GOLDEN_RUBRIC.version,
    )


def _full_context_record(record: Any) -> SimpleNamespace:
    """Same execution facts with complete context provenance (EXACT)."""
    plain = _to_plain(record)
    plain["context_provenance"] = (
        {
            "request_ref": 2,
            "source_event_refs": [1],
            "surface_refs": [1],
            "current_input_ref": 1,
            "runtime_context_ref": {"context_id": "ctx-full", "version": 1},
            "quality": "EXACT",
            "missing_semantics": [],
        },
    )
    return SimpleNamespace(**plain)


ORACLE_SPECIFIC = OracleReference(
    oracle_id="oracle:phase6b:procurement:specific",
    expected_answer="采购建议：采购 10 件",
    expected_business_outcome="库存不足时生成采购建议，数量 10 件",
    expected_constraints=("不得声称已强制写入 ERP",),
)


TASK_JUDGE_05 = TaskSpecification(
    task_id="TASK-JUDGE-05",
    natural_language_goal="查询库存，如果不足则生成正确采购建议。",
    required_tools=("inventory.lookup", "procurement.suggest"),
)
TASK_JUDGE_05_RECORD = _judge_record(
    execution_id="exec-judge-05",
    tools=(
        {"call_id": "t1", "name": "inventory.lookup", "arguments": {"sku": "A"}},
        {
            "call_id": "t2",
            "name": "procurement.suggest",
            "arguments": {"sku": "A", "qty": 3},
        },
    ),
    tool_results=(
        {"tool_call_id": "t1", "content": "stock:5", "is_error": False, "seq": 8},
        {"tool_call_id": "t2", "content": "suggestion:created", "is_error": False, "seq": 10},
    ),
    steps=(SimpleNamespace(assistant_messages=("库存为 5，采购建议：采购 3 件。",)),),
)

TASK_JUDGE_06 = TaskSpecification(
    task_id="TASK-JUDGE-06",
    natural_language_goal="查询库存并生成采购建议。",
    required_tools=("inventory.lookup", "procurement.suggest"),
)
TASK_JUDGE_06_RECORD = _judge_record(
    execution_id="exec-judge-06",
    steps=(SimpleNamespace(assistant_messages=("我不知道。",)),),
)

TASK_JUDGE_07 = TaskSpecification(
    task_id="TASK-JUDGE-07",
    natural_language_goal="查询库存，仅当库存不足时生成采购建议；库存等于需求时无需采购。",
    required_tools=("inventory.lookup",),
)
TASK_JUDGE_07_RECORD = _judge_record(
    execution_id="exec-judge-07",
    tools=({"call_id": "t1", "name": "inventory.lookup", "arguments": {"sku": "A"}},),
    tool_results=(
        {"tool_call_id": "t1", "content": "stock:10", "is_error": False, "seq": 8},
    ),
    steps=(SimpleNamespace(assistant_messages=("库存为 10，满足需求，无需采购。",)),),
)
ORACLE_07 = OracleReference(
    oracle_id="oracle:phase6b:boundary",
    expected_answer="无需采购",
    expected_business_outcome="无需采购",
    expected_constraints=(),
)


GOLDEN_CALIBRATION_CASES = (
    _calibration_case(
        "TASK-JUDGE-01",
        TASK_JUDGE_01,
        _full_context_record(TASK_JUDGE_01_RECORD),
        ORACLE_SPECIFIC,
        PASS,
        (0.8, 1.0),
        HIGH,
    ),
    _calibration_case(
        "TASK-JUDGE-02",
        TASK_JUDGE_02,
        _full_context_record(TASK_JUDGE_02_RECORD),
        ORACLE_SPECIFIC,
        FAIL,
        (0.0, 0.4),
        HIGH,
    ),
    _calibration_case(
        "TASK-JUDGE-03",
        TASK_JUDGE_03,
        _full_context_record(TASK_JUDGE_03_RECORD),
        ORACLE_SPECIFIC,
        FAIL,
        (0.0, 0.8),
        HIGH,
    ),
    _calibration_case(
        "TASK-JUDGE-04",
        TASK_JUDGE_04,
        TASK_JUDGE_04_RECORD,
        TASK_JUDGE_ORACLE,
        INCONCLUSIVE,
        None,
        LOW,
    ),
    _calibration_case(
        "TASK-JUDGE-05",
        TASK_JUDGE_05,
        _full_context_record(TASK_JUDGE_05_RECORD),
        ORACLE_SPECIFIC,
        FAIL,
        (0.3, 0.7),
        MEDIUM,
    ),
    _calibration_case(
        "TASK-JUDGE-06",
        TASK_JUDGE_06,
        _full_context_record(TASK_JUDGE_06_RECORD),
        ORACLE_SPECIFIC,
        FAIL,
        (0.0, 0.2),
        HIGH,
    ),
    _calibration_case(
        "TASK-JUDGE-07",
        TASK_JUDGE_07,
        _full_context_record(TASK_JUDGE_07_RECORD),
        ORACLE_07,
        PASS,
        (0.8, 1.0),
        HIGH,
    ),
)


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    sample_size: int
    agreement_rate: float
    false_pass_rate: float
    false_fail_rate: float
    inconclusive_rate: float
    statistically_meaningful: bool

    @property
    def significance(self) -> str:
        return (
            "STATISTICALLY_MEANINGFUL"
            if self.statistically_meaningful
            else "NOT_STATISTICALLY_MEANINGFUL"
        )


def calibration_metrics(
    pairs: tuple[tuple[str, str], ...],
    *,
    meaningful_threshold: int = 30,
) -> CalibrationMetrics:
    n = len(pairs)
    agreement = sum(expected == actual for expected, actual in pairs)
    false_pass = sum(expected != PASS and actual == PASS for expected, actual in pairs)
    false_fail = sum(expected == PASS and actual == FAIL for expected, actual in pairs)
    inconclusive = sum(actual == INCONCLUSIVE for _, actual in pairs)
    return CalibrationMetrics(
        sample_size=n,
        agreement_rate=agreement / n if n else 0.0,
        false_pass_rate=false_pass / n if n else 0.0,
        false_fail_rate=false_fail / n if n else 0.0,
        inconclusive_rate=inconclusive / n if n else 0.0,
        statistically_meaningful=n >= meaningful_threshold,
    )


def judge_run_record(result: LLMJudgeResult, usage: dict | None = None) -> dict:
    """Evaluation-side persistence record; never a Runtime event."""
    return {
        "judge_run_id": result.judge_id,
        "model_ref": result.model_ref,
        "model_version": result.model_version,
        "prompt_ref": result.prompt_ref,
        "prompt_version": result.prompt_version,
        "rubric_ref": result.rubric_ref,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": result.status,
        "score": result.score,
        "confidence": result.confidence,
        "usage": usage,
    }


def append_judge_run(path: pathlib.Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_calibration(
    provider: JudgeProvider,
    cases: tuple[JudgeCalibrationCase, ...] = GOLDEN_CALIBRATION_CASES,
    *,
    prompt_key: str = "A",
    persist_path: pathlib.Path | None = None,
) -> tuple[CalibrationMetrics, tuple[LLMJudgeResult, ...]]:
    results = []
    for case in cases:
        result = provider.judge(case.jinput, prompt_key=prompt_key)
        results.append(result)
        if persist_path is not None:
            append_judge_run(persist_path, judge_run_record(result, provider.last_usage))
    metrics = calibration_metrics(
        tuple((case.expected_status, result.status) for case, result in zip(cases, results)),
    )
    return metrics, tuple(results)


__all__ = [
    "CalibrationMetrics",
    "DEFAULT_MODEL",
    "DeepSeekJudgeProvider",
    "GOLDEN_CALIBRATION_CASES",
    "GOLDEN_RUBRIC",
    "INVALID_OUTPUT",
    "JudgeCalibrationCase",
    "JudgeProvider",
    "JudgeProviderError",
    "PERMANENT",
    "PROMPT_TEMPLATES",
    "TIMEOUT",
    "TRANSIENT",
    "UNAVAILABLE",
    "append_judge_run",
    "calibration_metrics",
    "judge_run_record",
    "provider_status",
    "run_calibration",
]
