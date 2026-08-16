"""Phase 5-L ImprovementCandidate: proposal metadata, not an applied change.

Semantics are frozen here (dataclass + ``propose()``); no storage format, no
auto-apply, no promotion, no Runtime mutation.

    FailureAttribution
        -> ImprovementCandidate (PROPOSED / REQUIRES_DISAMBIGUATION /
                                 INVALID_FOR_REGRESSION)
        -> (future) Regression -> Validated Improvement -> Promotion
"""

from __future__ import annotations

from dataclasses import dataclass

from failure_attribution import MULTIPLE_CANDIDATES, FailureAttribution

PROMPT = "PROMPT"
SKILL = "SKILL"
TOOL_POLICY = "TOOL_POLICY"
CAPABILITY_CONFIG = "CAPABILITY_CONFIG"
MODEL_CONFIG = "MODEL_CONFIG"
RUNTIME_POLICY = "RUNTIME_POLICY"
BACKEND_SPECIFIC = "BACKEND_SPECIFIC"

# v1 allowed change types. ARBITRARY_CODE is deliberately absent: a candidate
# must change prompt/skill/policy/config, never arbitrary runtime code.
CHANGE_TYPES = frozenset(
    {
        PROMPT,
        SKILL,
        TOOL_POLICY,
        CAPABILITY_CONFIG,
        MODEL_CONFIG,
        RUNTIME_POLICY,
        BACKEND_SPECIFIC,
    },
)

PROPOSED = "PROPOSED"
UNDER_VALIDATION = "UNDER_VALIDATION"
REJECTED = "REJECTED"
VALIDATED = "VALIDATED"
PROMOTED = "PROMOTED"
ROLLED_BACK = "ROLLED_BACK"
REQUIRES_DISAMBIGUATION = "REQUIRES_DISAMBIGUATION"
INVALID_FOR_REGRESSION = "INVALID_FOR_REGRESSION"
STATUSES = frozenset(
    {
        PROPOSED,
        UNDER_VALIDATION,
        REJECTED,
        VALIDATED,
        PROMOTED,
        ROLLED_BACK,
        REQUIRES_DISAMBIGUATION,
        INVALID_FOR_REGRESSION,
    },
)

QUALITATIVE_ONLY = "QUALITATIVE_ONLY"
METRIC_DRIVEN = "METRIC_DRIVEN"

ATTRIBUTION_COMPLETE = "ATTRIBUTION_COMPLETE"
ATTRIBUTION_INCOMPLETE = "ATTRIBUTION_INCOMPLETE"

CONTEXT_EVIDENCE_PARTIAL = "CONTEXT_EVIDENCE_PARTIAL"


@dataclass(frozen=True, slots=True)
class ImprovementCandidate:
    """Immutable proposal metadata tied to evidence-backed failures."""

    candidate_id: str
    source_failure_ids: tuple[str, ...]
    source_evaluation_ids: tuple[str, ...]
    source_execution_ids: tuple[str, ...]
    target_type: str
    target_ref: str
    change_type: str
    change_ref: str
    baseline_ref: str
    hypothesis: str
    expected_effect: str
    constraints: tuple[str, ...] = ()
    evidence_refs: tuple[dict, ...] = ()
    status: str = PROPOSED
    created_at: str | None = None
    expected_metric: str | None = None
    expected_delta: float | None = None
    expected_effect_quality: str = QUALITATIVE_ONLY
    source_mapping_quality: str = "UNKNOWN"
    initiator_ref: dict | None = None
    owner_ref: dict | None = None
    context_provenance_ref: dict | None = None
    context_evidence_status: str | None = None
    attribution_status: str = ATTRIBUTION_COMPLETE


def _require(value: object, message: str) -> None:
    if not value:
        raise ValueError(message)


def propose(
    attribution: FailureAttribution,
    *,
    target_type: str,
    target_ref: str,
    change_type: str,
    change_ref: str,
    baseline_ref: str,
    hypothesis: str,
    expected_effect: str,
    evaluation_ids: tuple[str, ...] = (),
    execution_ids: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    expected_metric: str | None = None,
    expected_delta: float | None = None,
    created_at: str | None = None,
) -> ImprovementCandidate:
    """Assemble one proposal from a FailureAttribution (read-only, no apply)."""
    _require(
        attribution.failure_id
        and not attribution.failure_id.endswith("NO_FAILURE"),
        "ImprovementCandidate requires failure evidence (failure_id)",
    )
    _require(
        attribution.evidence_refs,
        "ImprovementCandidate requires failure evidence (evidence_refs)",
    )
    _require(target_type, "target_type required (e.g. capability / prompt)")
    _require(target_ref, "target_ref required (e.g. inventory.lookup)")
    if change_type not in CHANGE_TYPES:
        raise ValueError(
            f"change_type {change_type!r} not allowed; ARBITRARY_CODE is forbidden",
        )
    _require(change_ref, "change_ref required")
    _require(baseline_ref, "baseline_ref required (UNKNOWN is not enough)")
    _require(
        hypothesis and hypothesis != "VERIFIED",
        "hypothesis required and must not be marked VERIFIED",
    )
    _require(expected_effect, "expected_effect required")

    source_evaluation_ids = tuple(evaluation_ids or ())
    _require(
        source_evaluation_ids,
        "source_evaluation_ids required (EvaluationResult reference)",
    )
    source_execution_ids = tuple(execution_ids or ())
    if not source_execution_ids:
        source_execution_ids = (
            (attribution.execution_id,) if attribution.execution_id else ()
        )
    _require(
        source_execution_ids,
        "source_execution_ids required (ExecutionRecord reference)",
    )
    if baseline_ref == "UNKNOWN" and (
        expected_metric is not None or expected_delta is not None
    ):
        raise ValueError("no fabricated metric without a historical baseline")

    effect_quality = (
        METRIC_DRIVEN
        if (expected_metric is not None or expected_delta is not None)
        else QUALITATIVE_ONLY
    )
    if attribution.failure_kind == MULTIPLE_CANDIDATES:
        status = REQUIRES_DISAMBIGUATION
    elif baseline_ref == "UNKNOWN":
        status = INVALID_FOR_REGRESSION
    else:
        status = PROPOSED

    provenance = attribution.context_provenance_ref
    context_evidence = (
        CONTEXT_EVIDENCE_PARTIAL
        if isinstance(provenance, dict) and provenance.get("quality") == "PARTIAL"
        else None
    )
    attribution_status = (
        ATTRIBUTION_COMPLETE
        if attribution.initiator_ref is not None
        and attribution.owner_ref is not None
        else ATTRIBUTION_INCOMPLETE
    )
    return ImprovementCandidate(
        candidate_id="|".join(
            (
                attribution.failure_id,
                target_type,
                target_ref,
                change_type,
                change_ref,
                baseline_ref,
            ),
        ),
        source_failure_ids=(attribution.failure_id,),
        source_evaluation_ids=source_evaluation_ids,
        source_execution_ids=source_execution_ids,
        target_type=target_type,
        target_ref=target_ref,
        change_type=change_type,
        change_ref=change_ref,
        baseline_ref=baseline_ref,
        hypothesis=hypothesis,
        expected_effect=expected_effect,
        constraints=tuple(constraints or ()),
        evidence_refs=tuple(attribution.evidence_refs),
        status=status,
        created_at=created_at,
        expected_metric=expected_metric,
        expected_delta=expected_delta,
        expected_effect_quality=effect_quality,
        source_mapping_quality=attribution.mapping_quality,
        initiator_ref=attribution.initiator_ref,
        owner_ref=attribution.owner_ref,
        context_provenance_ref=provenance,
        context_evidence_status=context_evidence,
        attribution_status=attribution_status,
    )


__all__ = [
    "ATTRIBUTION_COMPLETE",
    "ATTRIBUTION_INCOMPLETE",
    "BACKEND_SPECIFIC",
    "CAPABILITY_CONFIG",
    "CHANGE_TYPES",
    "CONTEXT_EVIDENCE_PARTIAL",
    "ImprovementCandidate",
    "INVALID_FOR_REGRESSION",
    "METRIC_DRIVEN",
    "MODEL_CONFIG",
    "PROMPT",
    "PROMOTED",
    "PROPOSED",
    "QUALITATIVE_ONLY",
    "REJECTED",
    "REQUIRES_DISAMBIGUATION",
    "ROLLED_BACK",
    "RUNTIME_POLICY",
    "SKILL",
    "STATUSES",
    "TOOL_POLICY",
    "UNDER_VALIDATION",
    "VALIDATED",
    "propose",
]
