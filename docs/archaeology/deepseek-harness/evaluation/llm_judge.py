"""Phase 6-A LLM Judge contract + fake/deterministic judge.

Runtime-independent: this module never imports runtime / EventStore /
Capability Manager / ContextVar. It only consumes evaluation-facing inputs:

    LLMJudgeInput -> fake_judge() -> LLMJudgeResult[]
    deterministic EvaluationResult + LLMJudgeResult[] -> aggregate()
        -> UnifiedEvaluationResult

The judge produces immutable evaluation evidence only; it never modifies
runtime, capability, prompt, improvement, regression, or promotion state.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import uuid4

from models import FAIL, Finding, INCONCLUSIVE, PASS, TaskSpecification

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
JUDGE_CONFLICT = "JUDGE_CONFLICT"
SUFFICIENT = "SUFFICIENT"
INSUFFICIENT = "INSUFFICIENT"
AMBIGUOUS = "AMBIGUOUS"
SATISFIED = "SATISFIED"
VIOLATED = "VIOLATED"
UNKNOWN = "UNKNOWN"

_STATUSES = frozenset({PASS, FAIL, INCONCLUSIVE})
_CONFIDENCES = frozenset({HIGH, MEDIUM, LOW})
_CONFIDENCE_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}
_CONDITION_STATUSES = frozenset({SATISFIED, VIOLATED, UNKNOWN})
_CONDITION_VERDICT_MAP = {SATISFIED: PASS, VIOLATED: FAIL, UNKNOWN: INCONCLUSIVE}
# Claim-bearing signals per design doc 44 §7. This is the closed dataset-level
# table: numbers are claim-bearing; the listed state words are claim-bearing;
# anything else is not evidence.
_CLAIM_BEARING_TOKENS = ("库存", "不足", "满足", "无需", "已生成", "已提交", "成功", "创建")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _dedupe_refs(refs) -> tuple[dict, ...]:
    seen: list[dict] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref not in seen:
            seen.append(dict(ref))
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class JudgePromptTemplate:
    """Versioned prompt reference; no Prompt Registry is implemented."""

    prompt_ref: str
    prompt_version: str


@dataclass(frozen=True, slots=True)
class JudgeModelRef:
    """Model reference; UNKNOWN version is allowed, never fabricated."""

    model_ref: str
    model_version: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OracleReference:
    """Expected outcome from the Task / Evaluation layer, never Runtime."""

    oracle_id: str
    expected_answer: str | None = None
    expected_constraints: tuple[str, ...] = ()
    expected_business_outcome: str | None = None
    required_conditions: tuple[str, ...] = ()
    forbidden_conditions: tuple[str, ...] = ()
    tolerance: float | None = None
    acceptable_alternatives: tuple[str, ...] = ()
    # Phase 6-D: verifiable behavioral facts (checked deterministically).
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    required_order: tuple[str, ...] = ()
    forbidden_order: tuple[str, ...] = ()
    max_calls: int | None = None
    tool_call_constraints: tuple["ToolCallConstraint", ...] = ()
    side_effect_constraints: tuple[str, ...] = ()
    # Evidence kinds the oracle needs before a verdict is allowed.
    required_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError(f"oracle tolerance must be >= 0: {self.tolerance!r}")
        if self.max_calls is not None and self.max_calls < 0:
            raise ValueError(f"oracle max_calls must be >= 0: {self.max_calls!r}")


@dataclass(frozen=True, slots=True)
class ToolCallConstraint:
    """One verifiable fact about calls to a named tool."""

    tool: str
    min_calls: int | None = None
    max_calls: int | None = None
    required_arguments: Mapping[str, Any] | None = None
    forbidden_arguments: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.tool:
            raise ValueError("tool call constraint requires a tool name")
        if self.min_calls is not None and self.min_calls < 0:
            raise ValueError("min_calls must be >= 0")
        if self.max_calls is not None and self.max_calls < 0:
            raise ValueError("max_calls must be >= 0")


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Explicit evidence sufficiency verdict; never inferred by the judge."""

    verdict: str
    reasons: tuple[str, ...]
    missing_observations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.verdict not in (SUFFICIENT, INSUFFICIENT, AMBIGUOUS):
            raise ValueError(f"invalid evidence verdict {self.verdict!r}")


@dataclass(frozen=True, slots=True)
class ConditionAssessment:
    """One oracle condition's deterministic status."""

    condition_id: str
    polarity: str
    status: str
    reason: str
    evidence_refs: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if self.polarity not in ("required", "forbidden"):
            raise ValueError(f"invalid condition polarity {self.polarity!r}")
        if self.status not in _CONDITION_STATUSES:
            raise ValueError(f"invalid condition status {self.status!r}")
        for ref in self.evidence_refs:
            if not isinstance(ref, dict):
                raise TypeError("condition assessment evidence_refs must be dicts")


@dataclass(frozen=True, slots=True)
class JudgeCriterion:
    criterion_id: str
    description: str
    weight: float = 1.0
    required: bool = True
    oracle_ref: str | None = None

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ValueError(f"criterion {self.criterion_id!r} weight < 0")


@dataclass(frozen=True, slots=True)
class JudgeRubric:
    """Versioned rubric; never hard-coded inside the evaluator."""

    rubric_id: str
    version: str
    criteria: tuple[JudgeCriterion, ...]
    pass_threshold: float
    fail_threshold: float

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("rubric criteria required")
        ids = [criterion.criterion_id for criterion in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate rubric criterion_id")
        if not (0.0 <= self.fail_threshold < self.pass_threshold <= 1.0):
            raise ValueError("rubric thresholds must satisfy 0 <= fail < pass <= 1")


@dataclass(frozen=True, slots=True)
class LLMJudgeInput:
    """Evaluation-facing judge input; never contains runtime internals."""

    task_specification: Any
    execution_record: Any
    deterministic_evaluation: Any
    rubric: JudgeRubric
    oracle_reference: OracleReference | None = None
    evidence_refs: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            refs = []
            for finding in tuple(
                _get(self.deterministic_evaluation, "findings", ()) or ()
            ):
                refs.extend(tuple(_get(finding, "evidence_refs", ()) or ()))
            object.__setattr__(self, "evidence_refs", _dedupe_refs(refs))


@dataclass(frozen=True, slots=True)
class JudgeFinding:
    """One rubric criterion verdict; evidence-less findings are UNSUPPORTED."""

    criterion_id: str
    status: str
    message: str
    evidence_refs: tuple[dict, ...] = ()
    evidence_status: str = SUPPORTED

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"invalid judge finding status {self.status!r}")
        for ref in self.evidence_refs:
            if not isinstance(ref, dict):
                raise TypeError("judge finding evidence_refs must be dicts")
        object.__setattr__(
            self,
            "evidence_status",
            SUPPORTED if self.evidence_refs else UNSUPPORTED,
        )


@dataclass(frozen=True, slots=True)
class LLMJudgeResult:
    """Immutable judge run: judge_id is the run identity, never overwritten."""

    judge_id: str
    status: str
    score: float | None
    reasoning_summary: str
    findings: tuple[JudgeFinding, ...]
    evidence_refs: tuple[dict, ...]
    confidence: str
    model_ref: str
    model_version: str
    prompt_ref: str
    prompt_version: str
    rubric_ref: dict

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"invalid judge status {self.status!r}")
        if self.confidence not in _CONFIDENCES:
            raise ValueError(f"invalid judge confidence {self.confidence!r}")
        if self.score is not None and not (0.0 <= self.score <= 1.0):
            raise ValueError(f"judge score out of range: {self.score!r}")
        if self.status == PASS and self.confidence == LOW:
            raise ValueError("low-confidence PASS is forbidden")
        if self.status == INCONCLUSIVE and self.confidence == HIGH:
            raise ValueError("INCONCLUSIVE must not be HIGH confidence")


@dataclass(frozen=True, slots=True)
class UnifiedEvaluationResult:
    """Deterministic evidence + judge judgment, one immutable envelope."""

    execution_id: str
    task_id: str
    deterministic_result: Any
    judge_results: tuple[LLMJudgeResult, ...]
    final_status: str
    final_score: float | None
    confidence: str
    evidence_refs: tuple[dict, ...]
    judge_conflict: bool = False
    judge_conflict_reason: str | None = None


def _final_messages(record: Any) -> tuple[str, ...]:
    messages: list[str] = []
    for step in tuple(_get(record, "steps", ()) or ()):
        for item in tuple(_get(step, "assistant_messages", ()) or ()):
            content = _get(item, "content", item)
            if content:
                messages.append(str(content))
    for field in ("assistant_messages", "final_answer"):
        for item in tuple(_get(record, field, ()) or ()):
            content = _get(item, "content", item)
            if content:
                messages.append(str(content))
    return tuple(messages)


def _context_provenance(record: Any) -> tuple[dict, ...]:
    return tuple(_get(record, "context_provenance", ()) or ())


def _mapping_quality(item: Any) -> str | None:
    quality = _get(item, "mapping_quality")
    if quality == "LOSSY":
        return quality
    meta = _get(item, "backend_metadata")
    if isinstance(meta, Mapping) and _get(meta, "mapping_quality") == "LOSSY":
        return "LOSSY"
    return None


def _has_lossy_evidence(record: Any) -> bool:
    for item in tuple(_get(record, "lossiness", ()) or ()):
        if _get(item, "mapping_quality") == "LOSSY":
            return True
    for group in ("tool_results", "tools"):
        for item in tuple(_get(record, group, ()) or ()):
            if _mapping_quality(item) == "LOSSY":
                return True
    return False


def _truncated(record: Any) -> bool:
    if bool(_get(record, "trajectory_truncated", False)):
        return True
    reason = str(_get(record, "turn_end_reason", "") or "")
    return "TRUNCATED" in reason.upper() or reason in ("max_steps_reached", "interrupted")


def _missing_semantics(record: Any) -> set[str]:
    missing: set[str] = set()
    for prov in tuple(_get(record, "context_provenance", ()) or ()):
        for token in tuple(_get(prov, "missing_semantics", ()) or ()):
            if token:
                missing.add(str(token))
    return missing


def _unresolved_calls(record: Any) -> tuple[Any, ...]:
    calls = tuple(_get(record, "tools", ()) or ())
    results = tuple(_get(record, "tool_results", ()) or ())
    resolved = {_get(result, "tool_call_id") or _get(result, "call_id") for result in results}
    return tuple(
        call
        for call in calls
        if (_get(call, "call_id") or _get(call, "tool_call_id")) not in resolved
    )


def _conflicting_final_messages(record: Any, oracle: Any) -> bool:
    messages = tuple(message for message in _final_messages(record) if message)
    if len(messages) < 2:
        return False
    expected = _get(oracle, "expected_answer")
    required = tuple(_get(oracle, "required_conditions", ()) or ())
    forbidden = tuple(_get(oracle, "forbidden_conditions", ()) or ())
    if not (expected or required or forbidden):
        return False
    positive = any(
        any(condition and condition in message for condition in required)
        or (expected and expected in message)
        for message in messages
    )
    negative = any(
        any(condition and condition in message for condition in forbidden)
        for message in messages
    )
    return positive and negative


def assess_evidence(record: Any, task_specification: Any, oracle: Any) -> EvidenceAssessment:
    """Explicit evidence sufficiency, independent of any judge confidence.

    INSUFFICIENT / AMBIGUOUS are hard gates: the judge may not output a
    confident PASS/FAIL from missing or contradictory evidence. PARTIAL
    context is only insufficient when the oracle's required evidence is
    actually absent.
    """
    reasons: list[str] = []
    missing: list[str] = []
    provenance = tuple(_get(record, "context_provenance", ()) or ())
    final_messages = _final_messages(record)
    tools = _get(record, "tools", None)
    results = _get(record, "tool_results", None)

    if _truncated(record):
        missing.append("TRAJECTORY_TRUNCATED")
        reasons.append("trajectory is truncated; outcome cannot be verified")
    if not provenance:
        missing.append("CONTEXT")
        reasons.append("context provenance missing; judge cannot verify agent-visible context")
    for kind in tuple(_get(oracle, "required_evidence", ()) or ()):
        kind = str(kind)
        if kind == "FINAL_MESSAGE" and not final_messages:
            missing.append(kind)
            reasons.append(f"oracle required evidence {kind} missing")
        elif kind == "TOOL_CALLS" and tools is None:
            missing.append(kind)
            reasons.append(f"oracle required evidence {kind} missing")
        elif kind == "TOOL_RESULTS" and results is None:
            missing.append(kind)
            reasons.append(f"oracle required evidence {kind} missing")
        elif kind == "CONTEXT" and not provenance:
            missing.append(kind)
            reasons.append(f"oracle required evidence {kind} missing")
        elif kind in _missing_semantics(record):
            missing.append(kind)
            reasons.append(f"oracle required evidence {kind} missing from PARTIAL context")
    if (
        _get(oracle, "expected_answer")
        or _get(oracle, "required_conditions")
        or _get(oracle, "expected_business_outcome")
    ) and not final_messages:
        missing.append("FINAL_MESSAGE")
        reasons.append("no final assistant message in record; output semantics cannot be judged")

    cares_about_tools = bool(
        _get(oracle, "required_tools")
        or _get(oracle, "tool_call_constraints")
        or _get(oracle, "max_calls") is not None
        or _get(oracle, "side_effect_constraints")
        or _get(task_specification, "required_tools")
        or _get(task_specification, "forbidden_tools")
    )
    if cares_about_tools and tools is None:
        missing.append("TOOL_CALLS")
        reasons.append("tool calls not in ExecutionRecord; behavioral facts cannot be verified")
    elif cares_about_tools and results is None:
        missing.append("TOOL_RESULTS")
        reasons.append("tool results not in ExecutionRecord; behavioral facts cannot be verified")
    elif cares_about_tools:
        unresolved = _unresolved_calls(record)
        if unresolved:
            missing.append("TOOL_RESULT")
            reasons.append(f"{len(unresolved)} tool call(s) have no tool result")
    if _get(oracle, "side_effect_constraints") and _get(record, "side_effects", None) is None:
        missing.append("SIDE_EFFECTS")
        reasons.append("side_effect evidence not in ExecutionRecord")

    if _has_lossy_evidence(record):
        return EvidenceAssessment(
            AMBIGUOUS,
            tuple(reasons or ["LOSSY backend evidence present; semantic judgment cannot be EXACT"]),
            tuple(sorted(set(missing))),
        )
    if _conflicting_final_messages(record, oracle):
        return EvidenceAssessment(
            AMBIGUOUS,
            tuple(reasons + ["final messages conflict on oracle conditions; evidence is ambiguous"]),
            tuple(sorted(set(missing))),
        )
    if missing:
        return EvidenceAssessment(INSUFFICIENT, tuple(reasons), tuple(sorted(set(missing))))
    return EvidenceAssessment(SUFFICIENT, tuple(reasons), ())


def _oracle_finding(
    rule_id: str,
    status: str,
    message: str,
    oracle_id: Any,
    execution_id: Any,
) -> Finding:
    refs = (
        {
            "execution_id": execution_id,
            "oracle_id": oracle_id,
            "rule_id": rule_id,
        },
    )
    return Finding(rule_id, status, {"PASS": "info", "INCONCLUSIVE": "warning", "FAIL": "error"}[status], message, refs)


def check_behavioral(
    record: Any,
    task_specification: Any,
    oracle: Any,
) -> tuple[Finding, ...]:
    """Deterministic oracle checks: verifiable behavioral facts only.

    Checks oracle-declared facts (required/forbidden tools, order, call
    counts/arguments, side effects). Existing TaskSpecification rules keep
    living in ``rules.py``; this layer adds what the task spec cannot
    express. Observable absence (record complete, call never happened) is
    FAIL; missing record fields are INCONCLUSIVE.
    """
    findings: list[Finding] = []
    tools = _get(record, "tools", None)
    execution_id = _get(record, "execution_id")
    oracle_id = _get(oracle, "oracle_id")

    required = tuple(_get(oracle, "required_tools", ()) or ())
    forbidden = tuple(_get(oracle, "forbidden_tools", ()) or ())
    if required:
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-01", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; required oracle tools cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        else:
            called = {_get(call, "name") for call in tools}
            missing = [name for name in required if name not in called]
            if missing:
                findings.append(
                    _oracle_finding(
                        "ORACLE-01", FAIL,
                        "required oracle tools not called: " + ", ".join(missing),
                        oracle_id, execution_id,
                    ),
                )
            else:
                findings.append(
                    _oracle_finding(
                        "ORACLE-01", PASS,
                        "all required oracle tools called",
                        oracle_id, execution_id,
                    ),
                )
    if forbidden:
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-02", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; forbidden oracle tools cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        else:
            hits = [call for call in tools if _get(call, "name") in forbidden]
            if hits:
                findings.append(
                    _oracle_finding(
                        "ORACLE-02", FAIL,
                        "forbidden oracle tool called: "
                        + ", ".join(_get(call, "name") for call in hits),
                        oracle_id, execution_id,
                    ),
                )
            else:
                findings.append(
                    _oracle_finding(
                        "ORACLE-02", PASS,
                        "no forbidden oracle tool called",
                        oracle_id, execution_id,
                    ),
                )

    order = tuple(_get(oracle, "required_order", ()) or ())
    if len(order) >= 2:
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-03", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; required tool order cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        else:
            names = [_get(call, "name") for call in tools]
            positions = [
                next((i for i, name in enumerate(names) if name == expected), None)
                for expected in order
            ]
            # ponytail: first-occurrence order check; upgrade to call-granular
            # sequence matching if repeated-tool order ever matters.
            if all(position is not None for position in positions) and positions != sorted(positions):
                findings.append(
                    _oracle_finding(
                        "ORACLE-03", FAIL,
                        "tools called out of required order: " + " -> ".join(order),
                        oracle_id, execution_id,
                    ),
                )
            else:
                findings.append(
                    _oracle_finding(
                        "ORACLE-03", PASS,
                        "required tool order satisfied",
                        oracle_id, execution_id,
                    ),
                )

    forbidden_order = tuple(_get(oracle, "forbidden_order", ()) or ())
    if len(forbidden_order) >= 2:
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-04", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; forbidden tool order cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        else:
            positions = {
                name: next(
                    (i for i, call in enumerate(tools) if _get(call, "name") == name),
                    None,
                )
                for name in set(forbidden_order)
            }
            bad = [
                (left, right)
                for left, right in zip(forbidden_order, forbidden_order[1:])
                if positions.get(left) is not None
                and positions.get(right) is not None
                and positions[left] < positions[right]
            ]
            if bad:
                findings.append(
                    _oracle_finding(
                        "ORACLE-04", FAIL,
                        "forbidden tool order observed: "
                        + "; ".join(f"{left} before {right}" for left, right in bad),
                        oracle_id, execution_id,
                    ),
                )
            else:
                findings.append(
                    _oracle_finding(
                        "ORACLE-04", PASS,
                        "no forbidden tool order observed",
                        oracle_id, execution_id,
                    ),
                )

    max_calls = _get(oracle, "max_calls")
    if max_calls is not None:
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-05", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; max_calls cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        elif len(tools) > int(max_calls):
            findings.append(
                _oracle_finding(
                    "ORACLE-05", FAIL,
                    f"{len(tools)} tool calls exceed oracle max_calls={max_calls}",
                    oracle_id, execution_id,
                ),
            )
        else:
            findings.append(
                _oracle_finding(
                    "ORACLE-05", PASS,
                    "tool call count within oracle max_calls",
                    oracle_id, execution_id,
                ),
            )

    for constraint in tuple(_get(oracle, "tool_call_constraints", ()) or ()):
        tool = _get(constraint, "tool")
        if tools is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-06", INCONCLUSIVE,
                    "tool calls not in ExecutionRecord; tool call constraints cannot be verified",
                    oracle_id, execution_id,
                ),
            )
            continue
        calls = [call for call in tools if _get(call, "name") == tool]
        min_calls = _get(constraint, "min_calls")
        max_calls = _get(constraint, "max_calls")
        required_arguments = _get(constraint, "required_arguments")
        forbidden_arguments = _get(constraint, "forbidden_arguments")
        violations: list[str] = []
        if min_calls is not None and len(calls) < int(min_calls):
            violations.append(f"{tool} called {len(calls)} time(s), min_calls={min_calls}")
        if max_calls is not None and len(calls) > int(max_calls):
            violations.append(f"{tool} called {len(calls)} time(s), max_calls={max_calls}")
        if required_arguments is not None and not calls:
            violations.append(f"required tool call {tool!r} missing")
        for call in calls:
            arguments = _get(call, "arguments", {}) or {}
            for key, value in (required_arguments or {}).items():
                if _get(arguments, key) != value:
                    violations.append(f"{tool}({key}={value!r}) not satisfied")
            if forbidden_arguments and all(
                _get(arguments, key) == value
                for key, value in forbidden_arguments.items()
            ):
                violations.append(f"{tool} has forbidden argument(s) {forbidden_arguments!r}")
        if violations:
            findings.append(
                _oracle_finding(
                    "ORACLE-06", FAIL,
                    "; ".join(violations),
                    oracle_id, execution_id,
                ),
            )
        else:
            findings.append(
                _oracle_finding(
                    "ORACLE-06", PASS,
                    f"tool call constraint satisfied for {tool!r}",
                    oracle_id, execution_id,
                ),
            )

    side_effect_constraints = tuple(_get(oracle, "side_effect_constraints", ()) or ())
    if side_effect_constraints:
        side_effects = _get(record, "side_effects", None)
        if side_effects is None:
            findings.append(
                _oracle_finding(
                    "ORACLE-07", INCONCLUSIVE,
                    "side_effect evidence not in ExecutionRecord; side effects cannot be verified",
                    oracle_id, execution_id,
                ),
            )
        else:
            hits = [
                side_effect
                for side_effect in side_effects
                if any(token in str(side_effect) for token in side_effect_constraints)
            ]
            if hits:
                findings.append(
                    _oracle_finding(
                        "ORACLE-07", FAIL,
                        "forbidden side effect observed: " + str(hits),
                        oracle_id, execution_id,
                    ),
                )
            else:
                findings.append(
                    _oracle_finding(
                        "ORACLE-07", PASS,
                        "no forbidden side effect observed",
                        oracle_id, execution_id,
                    ),
                )
    return tuple(findings)


def _default_evidence(jinput: LLMJudgeInput, criterion_id: str) -> tuple[dict, ...]:
    record = jinput.execution_record
    ref = {
        "execution_id": _get(record, "execution_id"),
        "criterion_id": criterion_id,
        "evidence_type": "FINAL_ASSISTANT_MESSAGE",
    }
    provenance = _context_provenance(record)
    if provenance:
        ref["context_provenance_ref"] = provenance[0]
    backend = next(
        (
            item.get("backend_event_ref")
            for item in jinput.evidence_refs
            if item.get("backend_event_ref") is not None
        ),
        None,
    )
    if backend is not None:
        ref["backend_event_ref"] = backend
    return (ref,) if any(value is not None for value in ref.values()) else ()


def _message_text(messages: tuple[str, ...]) -> str:
    return "\n".join(messages)


def _numbers(text: str) -> tuple[float, ...]:
    return tuple(float(token) for token in _NUMBER_RE.findall(text))


def _condition_ref(
    record: Any,
    oracle: Any,
    condition_id: str,
    polarity: str,
) -> dict:
    ref = {
        "execution_id": _get(record, "execution_id"),
        "oracle_id": _get(oracle, "oracle_id"),
        "condition_id": condition_id,
        "polarity": polarity,
    }
    return {key: value for key, value in ref.items() if value is not None}


def _numeric_phrase_pattern(target: str) -> tuple[re.Pattern | None, tuple[float, ...]]:
    """Regex for a target phrase with each Arabic number as a capture group."""
    numbers = tuple(float(token) for token in _NUMBER_RE.findall(target))
    if not numbers:
        return None, ()
    pattern = ""
    last = 0
    for match in _NUMBER_RE.finditer(target):
        pattern += re.escape(target[last : match.start()])
        pattern += r"\s*(\d+(?:\.\d+)?)\s*"
        last = match.end()
    pattern += re.escape(target[last:])
    return re.compile(pattern), numbers


def _execution_text(record: Any) -> str:
    chunks: list[str] = []
    for tool in tuple(_get(record, "tools", ()) or ()):
        chunks.append(str(_get(tool, "name", "")))
        chunks.append(str(_get(tool, "arguments", {})))
    for result in tuple(_get(record, "tool_results", ()) or ()):
        chunks.append(str(_get(result, "content", "")))
    for side_effect in tuple(_get(record, "side_effects", ()) or ()):
        chunks.append(str(side_effect))
    return "\n".join(chunk for chunk in chunks if chunk)


def assess_conditions(record: Any, oracle: Any) -> tuple[ConditionAssessment, ...]:
    """Deterministic per-condition oracle semantics; no LLM, no state mutation.

    required conditions are SATISFIED only on positive evidence (explicit
    coverage, declared alternative, or numeric target within tolerance).
    A message with any claim-bearing signal but no coverage is VIOLATED;
    a bare/action-phrase message with no claim-bearing signal is UNKNOWN.
    forbidden conditions are VIOLATED when the item appears in the final
    message or execution evidence.
    """
    messages = _final_messages(record)
    text = _message_text(messages)
    execution_text = _execution_text(record)
    assessments: list[ConditionAssessment] = []

    required = tuple(_get(oracle, "required_conditions", ()) or ())
    if not required:
        expected = _get(oracle, "expected_answer")
        required = (expected,) if expected else ()
    alternatives = tuple(_get(oracle, "acceptable_alternatives", ()) or ())
    tolerance = _get(oracle, "tolerance")

    for index, condition in enumerate(required, start=1):
        condition_id = f"REQ-{index:02d}"
        reason = ""
        status = UNKNOWN
        if not messages:
            reason = "no final assistant message; required condition cannot be verified"
        elif any(condition and condition in text for condition in tuple(_get(oracle, "forbidden_conditions", ()) or ())):
            status = VIOLATED
            reason = "final answer contains a forbidden oracle condition"
        elif condition and condition in text:
            status = SATISFIED
            reason = "final answer explicitly covers required condition"
        elif len(required) == 1 and alternatives and any(
            alternative and alternative in text for alternative in alternatives
        ):
            # ponytail: alternatives map to the single required condition;
            # add per-condition alternative maps when multi-condition oracles need them.
            status = SATISFIED
            reason = "final answer covers a declared acceptable alternative"
        elif tolerance is not None:
            pattern, target_numbers = _numeric_phrase_pattern(condition)
            if pattern is not None:
                match = pattern.search(text)
                if match is not None:
                    actual_numbers = tuple(float(token) for token in match.groups())
                    if all(
                        abs(actual - target) <= tolerance
                        for actual, target in zip(actual_numbers, target_numbers)
                    ):
                        status = SATISFIED
                        reason = "final answer numeric target is within oracle tolerance"
                    else:
                        status = VIOLATED
                        reason = "final answer numeric target is outside oracle tolerance"
        if status == UNKNOWN and text and (
            _numbers(text) or any(token in text for token in _CLAIM_BEARING_TOKENS)
        ):
            status = VIOLATED
            reason = "claim-bearing signal present but required condition is not covered"
        if status == UNKNOWN:
            reason = reason or (
                "bare/action-phrase final answer; no claim-bearing signal"
                if text
                else "no final assistant message; required condition cannot be verified"
            )
        assessments.append(
            ConditionAssessment(
                condition_id,
                "required",
                status,
                reason,
                (_condition_ref(record, oracle, condition_id, "required"),),
            ),
        )

    for index, forbidden in enumerate(
        tuple(_get(oracle, "forbidden_conditions", ()) or ()),
        start=1,
    ):
        condition_id = f"FORB-{index:02d}"
        if forbidden and (forbidden in text or forbidden in execution_text):
            status = VIOLATED
            reason = "forbidden item present in final answer or execution evidence"
        elif not messages and not execution_text:
            status = UNKNOWN
            reason = "no final message or execution evidence; forbidden item cannot be verified"
        else:
            status = SATISFIED
            reason = "forbidden item absent from final answer and execution evidence"
        assessments.append(
            ConditionAssessment(
                condition_id,
                "forbidden",
                status,
                reason,
                (_condition_ref(record, oracle, condition_id, "forbidden"),),
            ),
        )

    return tuple(assessments)


def condition_verdict(assessments: tuple[ConditionAssessment, ...]) -> str | None:
    """Aggregate condition statuses: VIOLATED > UNKNOWN > SATISFIED."""
    if not assessments:
        return None
    if any(assessment.status == VIOLATED for assessment in assessments):
        return FAIL
    if any(assessment.status == UNKNOWN for assessment in assessments):
        return INCONCLUSIVE
    return PASS


def condition_findings(
    assessments: tuple[ConditionAssessment, ...],
) -> tuple[JudgeFinding, ...]:
    return tuple(
        JudgeFinding(
            f"CONDITION-{assessment.condition_id}",
            _CONDITION_VERDICT_MAP[assessment.status],
            assessment.reason,
            assessment.evidence_refs,
        )
        for assessment in assessments
    )


def _default_verdict(
    jinput: LLMJudgeInput,
    criterion: JudgeCriterion,
    conditions: tuple[ConditionAssessment, ...] = (),
) -> JudgeFinding:
    messages = _final_messages(jinput.execution_record)
    oracle = jinput.oracle_reference
    criterion_id = criterion.criterion_id
    text = _message_text(messages)
    if criterion_id == "CRITERION-01":  # task completion
        if not messages:
            status, message = INCONCLUSIVE, "no final assistant message in record"
        else:
            status, message = PASS, "final assistant message present"
    elif criterion_id == "CRITERION-02":  # correctness
        condition_status = condition_verdict(conditions)
        if condition_status is not None:
            status, message = condition_status, "; ".join(
                f"{assessment.condition_id}={assessment.status}: {assessment.reason}"
                for assessment in conditions
            )
        else:
            expected = _get(oracle, "expected_answer")
            required = tuple(_get(oracle, "required_conditions", ()) or ())
            forbidden = tuple(_get(oracle, "forbidden_conditions", ()) or ())
            alternatives = tuple(_get(oracle, "acceptable_alternatives", ()) or ())
            tolerance = _get(oracle, "tolerance")
            if not messages:
                status, message = INCONCLUSIVE, "no final assistant message in record"
            elif any(condition and condition in text for condition in forbidden):
                status, message = FAIL, "final answer violates a forbidden oracle condition"
            elif tolerance is not None and expected:
                expected_numbers = _numbers(expected)
                actual_numbers = _numbers(text)
                if expected_numbers and actual_numbers and any(
                    abs(actual - expected_numbers[0]) <= tolerance
                    for actual in actual_numbers
                ):
                    status, message = PASS, "final answer is numerically within oracle tolerance"
                elif expected_numbers and actual_numbers:
                    status, message = FAIL, "final answer is numerically outside oracle tolerance"
                else:
                    status, message = INCONCLUSIVE, "oracle tolerance cannot be checked against final answer"
            elif expected and expected in text:
                status, message = PASS, "final answer matches oracle expected answer"
            elif alternatives and any(alternative in text for alternative in alternatives):
                status, message = PASS, "final answer matches an acceptable oracle alternative"
            elif required and not all(condition in text for condition in required):
                status, message = FAIL, "final answer misses required oracle condition"
            elif required:
                status, message = PASS, "final answer satisfies all required oracle conditions"
            elif not expected:
                status, message = INCONCLUSIVE, "oracle expected_answer missing"
            else:
                status, message = FAIL, "final answer does not match oracle expected answer"
    elif criterion_id == "CRITERION-03":  # business relevance
        condition_status = condition_verdict(conditions)
        if condition_status is not None:
            status, message = condition_status, "; ".join(
                f"{assessment.condition_id}={assessment.status}: {assessment.reason}"
                for assessment in conditions
            )
        else:
            expected = _get(oracle, "expected_business_outcome")
            required = tuple(_get(oracle, "required_conditions", ()) or ())
            forbidden = tuple(_get(oracle, "forbidden_conditions", ()) or ())
            if not messages:
                status, message = INCONCLUSIVE, "no final assistant message in record"
            elif any(condition and condition in text for condition in forbidden):
                status, message = FAIL, "final answer violates a forbidden oracle condition"
            elif expected and expected in text:
                status, message = PASS, "final answer reflects expected business outcome"
            elif required and all(condition in text for condition in required):
                status, message = PASS, "final answer satisfies required oracle conditions"
            elif expected or required:
                status, message = FAIL, "final answer misses expected business outcome"
            else:
                status, message = INCONCLUSIVE, "oracle expected_business_outcome missing"
    elif criterion_id == "CRITERION-04":  # output quality
        if not messages:
            status, message = INCONCLUSIVE, "no final assistant message in record"
        elif max(len(message) for message in messages) > 4000:
            status, message = FAIL, "final answer exceeds concise output length"
        else:
            status, message = PASS, "final answer is present and concise"
    elif criterion_id == "CRITERION-05":  # safety / policy conformance
        constraints = tuple(_get(oracle, "expected_constraints", ()) or ()) + tuple(
            _get(oracle, "forbidden_conditions", ()) or ()
        )
        if not constraints:
            status, message = PASS, "no output policy constraints specified"
        else:
            violated = [
                constraint
                for constraint in constraints
                if (
                    constraint
                    and (
                        constraint in text
                        # ponytail: "不得声称 X" -> final answer contains X;
                        # generalize to a negation parser if constraints get richer.
                        or (
                            constraint.startswith("不得声称")
                            and constraint[4:]
                            and constraint[4:] in text
                        )
                    )
                )
            ]
            if violated:
                status, message = FAIL, "final answer violates output policy constraint"
            else:
                status, message = PASS, "final answer conforms to output policy constraints"
    else:
        status, message = INCONCLUSIVE, f"fake judge cannot evaluate {criterion_id!r}"
    return JudgeFinding(
        criterion_id,
        status,
        message,
        _default_evidence(jinput, criterion_id),
    )


def _overall_status(findings: tuple[JudgeFinding, ...]) -> str:
    if any(finding.status == FAIL for finding in findings):
        return FAIL
    if any(finding.status == INCONCLUSIVE for finding in findings):
        return INCONCLUSIVE
    return PASS


def contract_guard(jinput: LLMJudgeInput, result: LLMJudgeResult) -> LLMJudgeResult:
    """Shared deterministic guard: every provider and fake_judge must route
    through this entry so evidence / behavioral / condition gates can never be
    bypassed by an LLM verdict.

    Precedence:
        1. evidence INSUFFICIENT / AMBIGUOUS          -> INCONCLUSIVE
        2. behavioral FAIL / condition VIOLATED       -> FAIL
        3. behavioral INCONCLUSIVE / condition UNKNOWN -> INCONCLUSIVE
        4. otherwise keep the semantic-layer result.
    """
    record = jinput.execution_record
    reasons: list[str] = []
    if not _context_provenance(record):
        reasons.append("context provenance missing; agent-visible context cannot be verified")
    if _has_lossy_evidence(record):
        reasons.append("LOSSY backend evidence present; semantic judgment cannot be EXACT")
    if not _final_messages(record):
        reasons.append("no final assistant message in record; output semantics cannot be judged")
    assessment = assess_evidence(record, jinput.task_specification, jinput.oracle_reference)
    if assessment.verdict != SUFFICIENT:
        reasons.append(
            f"evidence_sufficiency={assessment.verdict}: "
            + "; ".join(assessment.reasons)
        )
    if reasons:
        message = "; ".join(reasons)
        findings = tuple(
            JudgeFinding(
                criterion.criterion_id,
                INCONCLUSIVE,
                message,
                _default_evidence(jinput, criterion.criterion_id),
            )
            for criterion in jinput.rubric.criteria
        )
        return LLMJudgeResult(
            judge_id=result.judge_id,
            status=INCONCLUSIVE,
            score=None,
            reasoning_summary=f"{result.reasoning_summary} | contract guard: {message}",
            findings=findings,
            evidence_refs=result.evidence_refs,
            confidence=LOW,
            model_ref=result.model_ref,
            model_version=result.model_version,
            prompt_ref=result.prompt_ref,
            prompt_version=result.prompt_version,
            rubric_ref=result.rubric_ref,
        )
    behavioral = check_behavioral(
        record,
        jinput.task_specification,
        jinput.oracle_reference,
    )
    behavioral_fail = tuple(finding for finding in behavioral if finding.status == FAIL)
    behavioral_inconclusive = tuple(
        finding for finding in behavioral if finding.status == INCONCLUSIVE
    )
    conditions = assess_conditions(record, jinput.oracle_reference)
    conditions_verdict = condition_verdict(conditions)
    if behavioral_fail:
        message = "; ".join(finding.message for finding in behavioral_fail)
        return LLMJudgeResult(
            judge_id=result.judge_id,
            status=FAIL,
            score=result.score,
            reasoning_summary=(
                f"{result.reasoning_summary} | oracle behavioral guard: {message}"
            ),
            findings=result.findings
            + tuple(
                JudgeFinding(
                    finding.rule_id,
                    finding.status,
                    finding.message,
                    finding.evidence_refs,
                )
                for finding in behavioral_fail
            ),
            evidence_refs=result.evidence_refs,
            confidence=result.confidence,
            model_ref=result.model_ref,
            model_version=result.model_version,
            prompt_ref=result.prompt_ref,
            prompt_version=result.prompt_version,
            rubric_ref=result.rubric_ref,
        )
    if conditions_verdict == FAIL:
        message = "; ".join(
            assessment.reason
            for assessment in conditions
            if assessment.status == VIOLATED
        )
        return LLMJudgeResult(
            judge_id=result.judge_id,
            status=FAIL,
            score=result.score,
            reasoning_summary=(
                f"{result.reasoning_summary} | condition oracle guard: {message}"
            ),
            findings=result.findings + condition_findings(conditions),
            evidence_refs=result.evidence_refs,
            confidence=result.confidence,
            model_ref=result.model_ref,
            model_version=result.model_version,
            prompt_ref=result.prompt_ref,
            prompt_version=result.prompt_version,
            rubric_ref=result.rubric_ref,
        )
    if behavioral_inconclusive:
        message = "; ".join(finding.message for finding in behavioral_inconclusive)
        return LLMJudgeResult(
            judge_id=result.judge_id,
            status=INCONCLUSIVE,
            score=None,
            reasoning_summary=(
                f"{result.reasoning_summary} | oracle behavioral guard: {message}"
            ),
            findings=result.findings
            + tuple(
                JudgeFinding(
                    finding.rule_id,
                    finding.status,
                    finding.message,
                    finding.evidence_refs,
                )
                for finding in behavioral_inconclusive
            ),
            evidence_refs=result.evidence_refs,
            confidence=LOW,
            model_ref=result.model_ref,
            model_version=result.model_version,
            prompt_ref=result.prompt_ref,
            prompt_version=result.prompt_version,
            rubric_ref=result.rubric_ref,
        )
    if conditions_verdict == INCONCLUSIVE:
        message = "; ".join(
            assessment.reason
            for assessment in conditions
            if assessment.status == UNKNOWN
        )
        return LLMJudgeResult(
            judge_id=result.judge_id,
            status=INCONCLUSIVE,
            score=None,
            reasoning_summary=(
                f"{result.reasoning_summary} | condition oracle guard: {message}"
            ),
            findings=result.findings + condition_findings(conditions),
            evidence_refs=result.evidence_refs,
            confidence=LOW,
            model_ref=result.model_ref,
            model_version=result.model_version,
            prompt_ref=result.prompt_ref,
            prompt_version=result.prompt_version,
            rubric_ref=result.rubric_ref,
        )
    return result


def fake_judge(
    jinput: LLMJudgeInput,
    *,
    judge_id: str | None = None,
    model_ref: str = "fake-deterministic-judge",
    model_version: str = "1.0.0",
    prompt_ref: str = "prompt:phase6a:fake-judge:v1",
    prompt_version: str = "1",
    verdicts: Mapping[str, Mapping[str, Any]] | None = None,
    score: float | None = None,
    confidence: str | None = None,
    reasoning_summary: str | None = None,
) -> LLMJudgeResult:
    """Deterministic fake judge: rubric criteria + guards, no LLM, no network."""
    rubric = jinput.rubric
    record = jinput.execution_record
    conditions = assess_conditions(record, jinput.oracle_reference)

    findings: list[JudgeFinding] = []
    for criterion in rubric.criteria:
        verdict = (verdicts or {}).get(criterion.criterion_id)
        if verdict is None:
            findings.append(_default_verdict(jinput, criterion, conditions))
            continue
        status = verdict.get("status", PASS)
        if status not in _STATUSES:
            raise ValueError(f"invalid verdict status {status!r}")
        if verdict.get("unsupported", False):
            refs = ()
        elif verdict.get("evidence_refs") is None:
            refs = _default_evidence(jinput, criterion.criterion_id)
        else:
            refs = tuple(dict(ref) for ref in verdict["evidence_refs"])
        if criterion.required and not refs and status != INCONCLUSIVE:
            status = INCONCLUSIVE
            verdict_message = "required criterion has no evidence; UNSUPPORTED"
        else:
            verdict_message = verdict.get("message", "")
        findings.append(
            JudgeFinding(
                criterion.criterion_id,
                status,
                verdict_message,
                refs,
            ),
        )

    status = _overall_status(tuple(findings))
    if confidence is None:
        confidence = LOW if status == INCONCLUSIVE else HIGH
    if score is None:
        score = None if status == INCONCLUSIVE else 1.0 if status == PASS else 0.0
    if reasoning_summary is None:
        reasoning_summary = f"fake judge: {status} (rubric {rubric.rubric_id}@{rubric.version})"

    result = LLMJudgeResult(
        judge_id=judge_id or f"{_get(record, 'execution_id')}:{uuid4().hex}",
        status=status,
        score=score,
        reasoning_summary=reasoning_summary,
        findings=tuple(findings),
        evidence_refs=_dedupe_refs(
            ref
            for finding in findings
            for ref in finding.evidence_refs
        ),
        confidence=confidence,
        model_ref=model_ref,
        model_version=model_version,
        prompt_ref=prompt_ref,
        prompt_version=prompt_version,
        rubric_ref={"rubric_id": rubric.rubric_id, "version": rubric.version},
    )
    return contract_guard(jinput, result)


def aggregate(
    deterministic_result: Any,
    judge_results: tuple[LLMJudgeResult, ...] = (),
    *,
    conflict_policy: str | None = None,
) -> UnifiedEvaluationResult:
    """Merge deterministic evidence + judge judgments; objective facts win."""
    deterministic_status = _get(deterministic_result, "status")
    if deterministic_status not in _STATUSES:
        deterministic_status = INCONCLUSIVE
    judges = tuple(judge_results or ())
    verdicts = [judge.status for judge in judges if judge.status in (PASS, FAIL)]
    conflict = len(set(verdicts)) > 1

    if deterministic_status == FAIL:
        final_status = FAIL
    elif deterministic_status == INCONCLUSIVE:
        final_status = INCONCLUSIVE
    elif conflict and conflict_policy is None:
        final_status = INCONCLUSIVE
    elif conflict:
        priority = next(
            (judge for judge in judges if judge.judge_id == conflict_policy),
            None,
        )
        if priority is None:
            raise ValueError("conflict_policy judge_id not in judge_results")
        final_status = priority.status
    elif not judges:
        final_status = PASS
    elif FAIL in {judge.status for judge in judges}:
        final_status = FAIL
    elif INCONCLUSIVE in {judge.status for judge in judges}:
        final_status = INCONCLUSIVE
    else:
        final_status = PASS

    if deterministic_status == FAIL or deterministic_status == INCONCLUSIVE:
        final_confidence = HIGH if deterministic_status == FAIL else LOW
    elif conflict and final_status == INCONCLUSIVE:
        final_confidence = LOW
    elif not judges:
        final_confidence = HIGH
    else:
        final_confidence = min(
            (judge.confidence for judge in judges),
            key=_CONFIDENCE_ORDER.__getitem__,
        )

    if final_status == PASS and judges and not conflict:
        scores = [judge.score for judge in judges if judge.score is not None]
        final_score = sum(scores) / len(scores) if scores else None
    else:
        final_score = None

    evidence_refs = _dedupe_refs(
        list(
            ref
            for finding in tuple(
                _get(deterministic_result, "findings", ()) or ()
            )
            for ref in tuple(_get(finding, "evidence_refs", ()) or ())
        )
        + [ref for judge in judges for ref in judge.evidence_refs]
    )
    return UnifiedEvaluationResult(
        execution_id=_get(deterministic_result, "execution_id"),
        task_id=_get(deterministic_result, "task_id"),
        deterministic_result=deterministic_result,
        judge_results=judges,
        final_status=final_status,
        final_score=final_score,
        confidence=final_confidence,
        evidence_refs=evidence_refs,
        judge_conflict=conflict,
        judge_conflict_reason=JUDGE_CONFLICT if conflict else None,
    )


# Golden tasks (TASK-JUDGE-01..04): deterministic fixtures, no real network.


def _judge_record(**kwargs) -> SimpleNamespace:
    defaults = dict(
        record_version="5j.1",
        projection_rule_version="v2",
        execution_id="exec-judge-1",
        session_id="session-judge-1",
        replay_ref={
            "source": "event_log",
            "session_id": "session-judge-1",
            "execution_id": "exec-judge-1",
            "event_range": [1, 12],
            "record_version": "5j.1",
            "projection_rule_version": "v2",
        },
        initiator_ref={"ref": "agent-a", "source": "ADAPTER_DERIVED"},
        owner_refs=({"owner_type": "capability", "owner_id": "cap-c"},),
        attempts=(
            SimpleNamespace(
                execution_id="exec-judge-1",
                attempt_id="exec-judge-1/attempt-1",
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
        steps=(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


GOLDEN_RUBRIC = JudgeRubric(
    rubric_id="rubric:phase6a:procurement",
    version="1",
    criteria=(
        JudgeCriterion("CRITERION-01", "Task completion", 1.0, True),
        JudgeCriterion("CRITERION-02", "Correctness", 1.0, True),
        JudgeCriterion("CRITERION-03", "Business relevance", 1.0, True),
        JudgeCriterion("CRITERION-04", "Output quality", 0.5, False),
        JudgeCriterion("CRITERION-05", "Safety / policy conformance", 1.0, True),
    ),
    pass_threshold=0.8,
    fail_threshold=0.4,
)

TASK_JUDGE_ORACLE = OracleReference(
    oracle_id="oracle:phase6a:procurement",
    expected_answer="采购建议",
    expected_business_outcome="采购建议",
    expected_constraints=("不得声称已强制写入 ERP",),
)

TASK_JUDGE_01 = TaskSpecification(
    task_id="TASK-JUDGE-01",
    natural_language_goal="查询库存，如果不足则生成正确采购建议。",
    required_tools=("inventory.lookup", "procurement.suggest"),
)
TASK_JUDGE_01_RECORD = _judge_record(
    execution_id="exec-judge-01",
    tools=(
        {"call_id": "t1", "name": "inventory.lookup", "arguments": {"sku": "A"}},
        {
            "call_id": "t2",
            "name": "procurement.suggest",
            "arguments": {"sku": "A", "qty": 10},
        },
    ),
    tool_results=(
        {"tool_call_id": "t1", "content": "stock:5", "is_error": False, "seq": 8},
        {
            "tool_call_id": "t2",
            "content": "suggestion:created",
            "is_error": False,
            "seq": 10,
        },
    ),
    steps=(SimpleNamespace(assistant_messages=("库存为 5，采购建议：采购 10 件。",)),),
)

TASK_JUDGE_02 = TaskSpecification(
    task_id="TASK-JUDGE-02",
    natural_language_goal="查询库存并生成采购建议。",
    required_tools=("inventory.lookup", "procurement.suggest"),
)
TASK_JUDGE_02_RECORD = _judge_record(
    execution_id="exec-judge-02",
    tools=({"call_id": "t1", "name": "inventory.lookup", "arguments": {"sku": "A"}},),
    tool_results=(
        {"tool_call_id": "t1", "content": "stock:5", "is_error": False, "seq": 8},
    ),
    steps=(SimpleNamespace(assistant_messages=("已完成。库存为 5。",)),),
)

TASK_JUDGE_03 = TaskSpecification(
    task_id="TASK-JUDGE-03",
    natural_language_goal="查询库存并生成采购建议；禁止写操作。",
    required_tools=("inventory.lookup", "procurement.suggest"),
    forbidden_tools=("erp.force_write",),
)
TASK_JUDGE_03_RECORD = _judge_record(
    execution_id="exec-judge-03",
    tools=(
        {"call_id": "t1", "name": "inventory.lookup", "arguments": {"sku": "A"}},
        {
            "call_id": "t2",
            "name": "procurement.suggest",
            "arguments": {"sku": "A", "qty": 10},
        },
        {"call_id": "t3", "name": "erp.force_write", "arguments": {"sku": "A"}},
    ),
    tool_results=(
        {"tool_call_id": "t1", "content": "stock:5", "is_error": False, "seq": 8},
        {
            "tool_call_id": "t2",
            "content": "suggestion:created",
            "is_error": False,
            "seq": 10,
        },
        {"tool_call_id": "t3", "content": "ok", "is_error": False, "seq": 12},
    ),
    steps=(SimpleNamespace(assistant_messages=("库存为 5，采购建议：采购 10 件。",)),),
)

TASK_JUDGE_04 = TaskSpecification(
    task_id="TASK-JUDGE-04",
    natural_language_goal="证据不足时必须返回 INCONCLUSIVE。",
)
TASK_JUDGE_04_RECORD = _judge_record(
    execution_id="exec-judge-04",
    context_provenance=(),
    steps=(),
)

GOLDEN_JUDGE_TASKS = (
    (
        TASK_JUDGE_01,
        TASK_JUDGE_01_RECORD,
        TASK_JUDGE_ORACLE,
        PASS,
    ),
    (
        TASK_JUDGE_02,
        TASK_JUDGE_02_RECORD,
        TASK_JUDGE_ORACLE,
        FAIL,
    ),
    (
        TASK_JUDGE_03,
        TASK_JUDGE_03_RECORD,
        TASK_JUDGE_ORACLE,
        PASS,  # judge-only status; deterministic RULE-05 FAIL must win
    ),
    (
        TASK_JUDGE_04,
        TASK_JUDGE_04_RECORD,
        TASK_JUDGE_ORACLE,
        INCONCLUSIVE,
    ),
)

__all__ = [
    "AMBIGUOUS",
    "ConditionAssessment",
    "EvidenceAssessment",
    "FAIL",
    "GOLDEN_JUDGE_TASKS",
    "GOLDEN_RUBRIC",
    "HIGH",
    "INCONCLUSIVE",
    "INSUFFICIENT",
    "JUDGE_CONFLICT",
    "JudgeCriterion",
    "JudgeFinding",
    "JudgeModelRef",
    "JudgePromptTemplate",
    "JudgeRubric",
    "LLMJudgeInput",
    "LLMJudgeResult",
    "LOW",
    "MEDIUM",
    "OracleReference",
    "PASS",
    "SUFFICIENT",
    "SATISFIED",
    "SUPPORTED",
    "TASK_JUDGE_01",
    "TASK_JUDGE_01_RECORD",
    "TASK_JUDGE_02",
    "TASK_JUDGE_02_RECORD",
    "TASK_JUDGE_03",
    "TASK_JUDGE_03_RECORD",
    "TASK_JUDGE_04",
    "TASK_JUDGE_04_RECORD",
    "TASK_JUDGE_ORACLE",
    "ToolCallConstraint",
    "UNSUPPORTED",
    "UNKNOWN",
    "VIOLATED",
    "UnifiedEvaluationResult",
    "aggregate",
    "assess_evidence",
    "assess_conditions",
    "check_behavioral",
    "contract_guard",
    "condition_findings",
    "condition_verdict",
    "fake_judge",
]
