"""Phase 5-N Promotion/Rollback contract: decision semantics only.

Consumes ImprovementCandidate + RegressionRun. Never deploys, never routes
traffic, never touches Runtime / EventStore / Capability ownership.
Backend-neutral: no ``if codex`` / ``if agentscope`` branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from improvement_candidate import VALIDATED, ImprovementCandidate
from models import FAIL, INCONCLUSIVE, PASS
from regression import EXACT, IMPROVED, LOSSY, NO_CHANGE, REGRESSED

GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_INCONCLUSIVE = "INCONCLUSIVE"
GATE_NOT_APPLICABLE = "NOT_APPLICABLE"

REJECTED = "REJECTED"
CANARY = "CANARY"
PROMOTED = "PROMOTED"
ROLLED_BACK = "ROLLED_BACK"
PENDING = "PENDING"

REQUESTED = "REQUESTED"
APPROVED = "APPROVED"
EXECUTED = "EXECUTED"
ROLLBACK_REJECTED = "REJECTED"
ROLLBACK_STATUSES = frozenset({REQUESTED, APPROVED, EXECUTED, ROLLBACK_REJECTED})

ROLLBACK_TRIGGERS = frozenset(
    {
        "regression_after_promotion",
        "critical_safety_incident",
        "policy_violation",
        "operator_decision",
    },
)

DEFAULT_SAFETY_CATEGORIES = (
    "security",
    "authorization",
    "unsafe_tool_use",
    "data_integrity",
)

# Stable Version Reference, not "candidate" / "latest" / "current" /
# "previous" / "last good". Anything else requires an external version
# registry to resolve; the contract only blocks unstable tokens.
UNSTABLE_VERSION_REFS = frozenset(
    {
        "",
        "unknown",
        "candidate",
        "latest",
        "current",
        "previous",
        "last-good",
        "last-deployed",
        "last-successful",
        "上一次部署",
    },
)


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    """A validated improvement now eligible for promotion consideration."""

    candidate_ref: str
    regression_ref: str
    target_ref: str


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: str
    reason: str
    evidence_refs: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision_id: str
    candidate_ref: str
    regression_ref: str
    decision: str
    evidence_refs: tuple[dict, ...]
    gate_results: tuple[GateResult, ...]
    target_version: str
    rollback_to_version: str
    reason: str
    created_at: str
    promotion_evidence_quality: str = EXACT
    initiator_ref: dict | None = None
    owner_ref: dict | None = None
    authorized_principal: dict | None = None
    authorization: str = "PARTIAL"
    observation_window: str | None = None


@dataclass(frozen=True, slots=True)
class RollbackDecision:
    rollback_id: str
    from_version: str
    to_version: str
    reason: str
    evidence_refs: tuple[dict, ...]
    created_at: str
    status: str = REQUESTED
    trigger: str | None = None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _require(value: object, message: str) -> None:
    if not value:
        raise ValueError(message)


def _stable_version(ref: str) -> bool:
    normalized = str(ref or "").strip().lower().replace(" ", "-")
    return bool(normalized) and normalized not in UNSTABLE_VERSION_REFS


def _evaluation_gate(regression: Any, exception_ref: str | None) -> GateResult:
    statuses = tuple(
        _get(result, "status")
        for result in tuple(_get(regression, "candidate_results", ()) or ())
    )
    if not statuses:
        return GateResult("evaluation", GATE_INCONCLUSIVE, "no candidate evaluation results", ())
    if any(status == INCONCLUSIVE for status in statuses):
        if exception_ref:
            return GateResult(
                "evaluation",
                GATE_PASS,
                f"INCONCLUSIVE accepted under explicit exception {exception_ref!r}",
                ({"evaluation_exception_ref": exception_ref},),
            )
        return GateResult(
            "evaluation",
            GATE_INCONCLUSIVE,
            "candidate evaluation INCONCLUSIVE; no automatic promotion",
            (),
        )
    if all(status == PASS for status in statuses):
        return GateResult("evaluation", GATE_PASS, "all candidate evaluations PASS", ())
    return GateResult("evaluation", GATE_FAIL, "candidate evaluation FAIL present", ())


def _regression_gate(regression: Any, lossy_exception_ref: str | None) -> GateResult:
    critical = tuple(_get(regression, "critical_regressions", ()) or ())
    if critical:
        return GateResult(
            "regression",
            GATE_FAIL,
            f"{len(critical)} critical regression(s) present; REGRESSED blocks promotion",
            (),
        )
    decision = _get(regression, "decision")
    if decision == IMPROVED:
        return GateResult("regression", GATE_PASS, "regression decision IMPROVED", ())
    if decision == NO_CHANGE:
        return GateResult("regression", GATE_FAIL, "NO_CHANGE is not promotion-eligible", ())
    if decision == REGRESSED:
        return GateResult("regression", GATE_FAIL, "REGRESSED blocks promotion", ())
    if decision == INCONCLUSIVE:
        if _get(regression, "comparison_quality") == LOSSY and lossy_exception_ref:
            return GateResult(
                "regression",
                GATE_PASS,
                f"LOSSY evidence accepted under explicit policy {lossy_exception_ref!r}",
                ({"lossy_exception_ref": lossy_exception_ref},),
            )
        return GateResult("regression", GATE_INCONCLUSIVE, "regression INCONCLUSIVE", ())
    return GateResult(
        "regression",
        GATE_INCONCLUSIVE,
        f"unknown regression decision {decision!r}",
        (),
    )


def _safety_gate(
    regression: Any,
    safety_categories: tuple[str, ...],
) -> GateResult:
    categories = set(safety_categories or ())
    overlaps = [
        item
        for item in tuple(_get(regression, "critical_regressions", ()) or ())
        if _get(item, "category") in categories
    ]
    if overlaps:
        refs = tuple(
            dict(ref)
            for item in overlaps
            for ref in tuple(_get(item, "evidence_refs", ()) or ())
            if isinstance(ref, dict)
        )
        return GateResult(
            "safety",
            GATE_FAIL,
            "critical safety regression present",
            refs,
        )
    return GateResult("safety", GATE_PASS, "no critical safety regression", ())


def _policy_gate(policy_ref: str | None) -> GateResult:
    if policy_ref:
        return GateResult(
            "policy",
            GATE_PASS,
            f"external policy result accepted: {policy_ref}",
            ({"policy_ref": policy_ref},),
        )
    return GateResult("policy", GATE_NOT_APPLICABLE, "no policy gate requested", ())


def decide(
    *,
    candidate: ImprovementCandidate,
    regression: Any,
    target_version: str,
    rollback_to_version: str,
    safety_categories: tuple[str, ...] = DEFAULT_SAFETY_CATEGORIES,
    policy_ref: str | None = None,
    evaluation_exception_ref: str | None = None,
    lossy_exception_ref: str | None = None,
    canary: bool = False,
    canary_observations: tuple[dict, ...] = (),
    observation_window: str | None = None,
    initiator_ref: dict | None = None,
    authorized_principal: dict | None = None,
    created_at: str = "",
) -> PromotionDecision:
    """Derive one immutable PromotionDecision from validated evidence."""
    if candidate.status != VALIDATED:
        raise ValueError(f"BLOCKED: candidate status {candidate.status!r} != VALIDATED")
    if not _stable_version(candidate.baseline_ref):
        raise ValueError(
            f"BLOCKED: candidate baseline_ref {candidate.baseline_ref!r} "
            "is not a stable version reference",
        )
    if candidate.baseline_ref != _get(regression, "baseline_ref"):
        raise ValueError("BLOCKED: candidate baseline_ref != regression baseline_ref")
    if candidate.candidate_id != _get(regression, "candidate_ref"):
        raise ValueError("BLOCKED: candidate_id != regression candidate_ref")
    regression_id = _get(regression, "regression_id")
    _require(regression_id, "BLOCKED: regression_id required")
    _require(
        _get(regression, "evidence_refs"),
        "BLOCKED: regression evidence_refs required; decision = PROMOTED is not evidence",
    )
    if not _stable_version(target_version):
        raise ValueError(
            f"BLOCKED: target_version {target_version!r} is not a stable version reference",
        )
    if not _stable_version(rollback_to_version):
        raise ValueError(
            f"BLOCKED: rollback_to_version {rollback_to_version!r} "
            "is not a stable version reference",
        )

    promotion = PromotionCandidate(
        candidate_ref=candidate.candidate_id,
        regression_ref=regression_id,
        target_ref=candidate.target_ref,
    )
    gates = (
        _evaluation_gate(regression, evaluation_exception_ref),
        _regression_gate(regression, lossy_exception_ref),
        _safety_gate(regression, safety_categories),
        _policy_gate(policy_ref),
    )
    required = {gate.gate_id for gate in gates if gate.gate_id != "policy"}
    blocked = [
        gate
        for gate in gates
        if gate.gate_id in required
        and gate.status in (GATE_FAIL, GATE_INCONCLUSIVE)
    ]
    if blocked:
        decision = REJECTED
        reason = "; ".join(f"{gate.gate_id}={gate.status}: {gate.reason}" for gate in blocked)
    elif canary:
        if canary_observations and observation_window:
            decision = CANARY
            reason = "gates PASS; canary observation evidence present"
        else:
            decision = PENDING
            reason = "gates PASS; canary observation window/evidence required before CANARY"
    else:
        decision = PROMOTED
        reason = "gates PASS; promotion eligible"

    evidence_refs = (
        {
            "candidate_ref": promotion.candidate_ref,
            "regression_ref": promotion.regression_ref,
            "target_ref": promotion.target_ref,
            "target_version": target_version,
            "rollback_to_version": rollback_to_version,
        },
        *tuple(
            dict(ref)
            for ref in tuple(_get(regression, "evidence_refs", ()) or ())
            if isinstance(ref, dict)
        ),
        *tuple(
            dict(ref)
            for gate in gates
            for ref in gate.evidence_refs
            if isinstance(ref, dict)
        ),
        *tuple(
            dict(ref)
            for ref in canary_observations
            if isinstance(ref, dict)
        ),
    )
    return PromotionDecision(
        decision_id="|".join((promotion.candidate_ref, promotion.regression_ref, target_version, created_at)),
        candidate_ref=promotion.candidate_ref,
        regression_ref=promotion.regression_ref,
        decision=decision,
        evidence_refs=evidence_refs,
        gate_results=gates,
        target_version=target_version,
        rollback_to_version=rollback_to_version,
        reason=reason,
        created_at=created_at,
        promotion_evidence_quality=_get(regression, "comparison_quality", EXACT),
        initiator_ref=initiator_ref,
        owner_ref=candidate.owner_ref,
        authorized_principal=authorized_principal,
        authorization="AUTHORIZED" if authorized_principal else "PARTIAL",
        observation_window=observation_window,
    )


def request_rollback(
    *,
    from_version: str,
    to_version: str,
    reason: str,
    evidence_refs: tuple[dict, ...],
    created_at: str,
    trigger: str | None = None,
) -> RollbackDecision:
    """Record an immutable rollback decision; never executes rollback."""
    for name, ref in (("from_version", from_version), ("to_version", to_version)):
        if not _stable_version(ref):
            raise ValueError(
                f"BLOCKED: {name} {ref!r} is not a stable version reference",
            )
    if from_version == to_version:
        raise ValueError("BLOCKED: rollback from_version == to_version")
    _require(reason, "rollback reason required")
    _require(evidence_refs, "rollback evidence_refs required")
    if trigger is not None and trigger not in ROLLBACK_TRIGGERS:
        raise ValueError(f"unknown rollback trigger {trigger!r}")
    return RollbackDecision(
        rollback_id="|".join((from_version, to_version, created_at)),
        from_version=from_version,
        to_version=to_version,
        reason=reason,
        evidence_refs=tuple(dict(ref) for ref in evidence_refs if isinstance(ref, dict)),
        created_at=created_at,
        status=REQUESTED,
        trigger=trigger,
    )


__all__ = [
    "APPROVED",
    "CANARY",
    "DEFAULT_SAFETY_CATEGORIES",
    "EXECUTED",
    "GATE_FAIL",
    "GATE_INCONCLUSIVE",
    "GATE_NOT_APPLICABLE",
    "GATE_PASS",
    "GateResult",
    "PENDING",
    "PROMOTED",
    "PromotionCandidate",
    "PromotionDecision",
    "REJECTED",
    "REQUESTED",
    "ROLLBACK_REJECTED",
    "ROLLBACK_STATUSES",
    "ROLLBACK_TRIGGERS",
    "ROLLED_BACK",
    "RollbackDecision",
    "UNSTABLE_VERSION_REFS",
    "decide",
    "request_rollback",
]
