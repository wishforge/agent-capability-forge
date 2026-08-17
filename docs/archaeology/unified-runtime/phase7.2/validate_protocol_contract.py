#!/usr/bin/env python3
"""Phase 7.2 protocol contract validator (offline, minimal).

Machine-checks the Core + Extension + Governance invariants (doc 61)
against an explicit protocol snapshot. Plain JSON shapes; no schema
platform, no service, no runtime, no provider.

Snapshot shape (all keys optional at the top level; checks degrade to
CONTRACT_VIOLATION when required data is absent):

    policies    {policy_id: {version, registered, frozen, content_hash,
                             commit_ref}}
    candidates  {candidate_id: {baseline_ref, change_ref, dataset_ref,
                                git_commit, recorded_artifact_hashes,
                                current_artifact_hashes}}
    runs        [{run_id, candidate_id, policy_ref, policy_version,
                  status, created_at, evidence_ids,
                  manifest_recorded_hash, manifest_current_hash}]
    evidence    [{evidence_id, run_id, recorded_hash, current_hash,
                  artifact_ref}]
    provenance  {candidate_id: {policy, evidence_manifest, run_ids,
                                immutable_artifact_refs}}
    decisions   [{decision_id, candidate_id, run_id, policy_ref, value,
                  gate_result, recorded_hash, current_hash}]
    lifecycle   {candidate_id: {status, transitions: [{from, to}]}}
    extensions  {consumer: {applicability, provenance_ref, fields}}

Failure codes:
    CONTRACT_VIOLATION      structural / gate / G6 violations
    GOVERNANCE_BLOCK        G1-G3 missing on PROMOTE or PROMOTABLE
    PROVENANCE_INCOMPLETE   G4 missing provenance elements
    INVALID_TRANSITION      illegal lifecycle edge / terminal violation
    IMMUTABILITY_VIOLATION  G5/G7 recorded content changed or overwritten
    EXTENSION_SCHEMA_ERROR  malformed extension or Core requiring one
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATUSES = {
    "DRAFT",
    "EVALUATING",
    "EVALUATED",
    "REGRESSION_CHECKED",
    "PROMOTION_REVIEW",
    "PROMOTABLE",
    "HOLD",
    "REJECTED",
    "PROMOTED",
}

TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"EVALUATING"},
    "EVALUATING": {"EVALUATED"},
    "EVALUATED": {"REGRESSION_CHECKED"},
    "REGRESSION_CHECKED": {"PROMOTION_REVIEW"},
    "PROMOTION_REVIEW": {"PROMOTABLE", "HOLD", "REJECTED"},
    "HOLD": {"EVALUATING"},
    "PROMOTABLE": {"PROMOTED"},
    "REJECTED": set(),
    "PROMOTED": set(),
}

# Fields owned by consumer extensions; Core contracts must never require
# them (61 section 4 / 5.5).
EXTENSION_OWNED_KEYS = frozenset(
    {"confidence", "score", "judge_findings", "plan_metrics", "consumer_outcome_labels"},
)

# Minimal conceptual contract table (doc 62 section 3). Used by the
# extension-isolation check; the remaining invariants are enforced by the
# validate_* functions below.
CONTRACTS: dict[str, dict[str, list[str]]] = {
    "Candidate": {
        "required_invariants": [
            "stable identity",
            "recorded artifact hashes",
            "git_commit present",
        ],
        "extension_points": ["consumer change metadata"],
        "forbidden": ["artifact hash change after EVALUATED", "REJECTED version re-promoted"],
    },
    "EvaluationRun": {
        "required_invariants": [
            "unique run_id",
            "candidate ref",
            "policy ref and version binding",
            "recorded manifest hash",
            "evidence refs",
        ],
        "extension_points": ["consumer run metadata"],
        "forbidden": ["HOLD re-entry reusing run_id", "overwriting completed run"],
    },
    "Attempt": {
        "required_invariants": [
            "attempt/run/case refs",
            "prompt hash",
            "raw/parsed/contract",
            "failure_kind",
            "artifact ref",
        ],
        "extension_points": ["consumer attempt metrics"],
        "forbidden": ["mutating raw after write"],
    },
    "Evidence": {
        "required_invariants": [
            "evidence/run/case refs",
            "outcome ref",
            "prompt hash",
            "policy_ref",
            "recorded content hash",
        ],
        "extension_points": ["consumer outcome fields"],
        "forbidden": ["content change after completion", "reassigning run"],
    },
    "Outcome": {
        "required_invariants": [
            "outcome_id",
            "attempt/round ref",
            "ACCEPT/REJECT status",
            "verdict semantics",
            "contract vs transport error separation",
        ],
        "extension_points": ["confidence", "score", "judge findings"],
        "forbidden": ["core requiring extension fields"],
    },
    "RegressionFinding": {
        "required_invariants": [
            "finding_id/case_id",
            "baseline and candidate evidence refs",
            "delta",
            "change class",
        ],
        "extension_points": ["verdict-level or score-level criteria"],
        "forbidden": ["classifying without both evidence refs"],
    },
    "Attribution": {
        "required_invariants": [
            "attribution_id",
            "evidence set refs",
            "four-class decision set",
            "policy_ref",
        ],
        "extension_points": ["score-level judgement thresholds"],
        "forbidden": ["attributing candidate regression without evidence"],
    },
    "PromotionPolicy": {
        "required_invariants": [
            "policy_id/version",
            "registered",
            "frozen",
            "content_hash",
            "commit_ref",
        ],
        "extension_points": ["consumer thresholds and scope values"],
        "forbidden": ["unregistered or unfrozen policy used for PROMOTE"],
    },
    "PromotionGate": {
        "required_invariants": [
            "gate_id",
            "policy_ref",
            "evidence refs",
            "precondition status",
            "rule results",
            "blockers",
            "decision",
        ],
        "extension_points": ["consumer rule values"],
        "forbidden": ["PROMOTE with blockers"],
    },
    "Decision": {
        "required_invariants": [
            "decision_id/type/value",
            "policy_ref",
            "evidence refs",
            "reason",
            "created_at",
            "artifact ref",
        ],
        "extension_points": ["consumer reason fields"],
        "forbidden": ["PROMOTE without prerequisites", "rewriting historical decision"],
    },
    "Provenance": {
        "required_invariants": [
            "provenance_id",
            "registered policy bytes and hash and commit",
            "evidence refs and hashes",
            "fixed conditions",
            "audit trail",
            "recompute",
        ],
        "extension_points": ["consumer source refs"],
        "forbidden": ["incomplete provenance", "retroactive rewrite"],
    },
}


@dataclass(frozen=True)
class Violation:
    code: str
    invariant: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "invariant": self.invariant, "message": self.message}


def _get(state: dict, key: str, default: Any = None) -> Any:
    return state.get(key, default)


def _runs(state: dict) -> list[dict]:
    return list(_get(state, "runs", []) or [])


def _run(state: dict, run_id: str | None) -> dict | None:
    return next((r for r in _runs(state) if r.get("run_id") == run_id), None)


def _missing_provenance(prov: dict, run_id: str | None) -> list[str]:
    missing: list[str] = []
    if not prov.get("policy"):
        missing.append("policy_provenance")
    if not prov.get("evidence_manifest"):
        missing.append("evidence_manifest")
    if not prov.get("run_ids") or run_id not in prov.get("run_ids", []):
        missing.append("run_id")
    if not prov.get("immutable_artifact_refs"):
        missing.append("immutable_artifact_reference")
    return missing


def _governance_missing(state: dict, candidate_id: str) -> list[str]:
    runs = [r for r in _runs(state) if r.get("candidate_id") == candidate_id]
    if not runs:
        return ["run_id"]
    run = max(runs, key=lambda r: str(r.get("created_at", "")))
    policy = _get(_get(state, "policies", {}), run.get("policy_ref"))
    missing: list[str] = []
    if not policy or not policy.get("registered"):
        missing.append("policy_registered")
    if policy and not policy.get("frozen"):
        missing.append("policy_frozen")
    if run.get("policy_version") != (policy or {}).get("version"):
        missing.append("run_policy_match")
    if _missing_provenance(_get(_get(state, "provenance", {}), candidate_id, {}), run.get("run_id")):
        missing.append("provenance_complete")
    return missing


def validate_references(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    policies = _get(state, "policies", {}) or {}
    candidates = _get(state, "candidates", {}) or {}
    run_ids = {r.get("run_id") for r in _runs(state)}

    for cand_id, cand in (candidates or {}).items():
        if not cand.get("git_commit"):
            violations.append(
                Violation("CONTRACT_VIOLATION", "Candidate", f"GIT_COMMIT_MISSING candidate={cand_id}")
            )
        if not cand.get("recorded_artifact_hashes") or not cand.get("current_artifact_hashes"):
            violations.append(
                Violation("CONTRACT_VIOLATION", "Candidate", f"ARTIFACT_HASHES_MISSING candidate={cand_id}")
            )

    evidence_by_id: dict[str, list[dict]] = {}
    for ev in _get(state, "evidence", []) or []:
        evidence_by_id.setdefault(ev.get("evidence_id"), []).append(ev)
        if ev.get("run_id") not in run_ids:
            violations.append(
                Violation("CONTRACT_VIOLATION", "Evidence", f"UNKNOWN_RUN_REF evidence={ev.get('evidence_id')}")
            )
        if not ev.get("recorded_hash") or not ev.get("current_hash"):
            violations.append(
                Violation("CONTRACT_VIOLATION", "Evidence", f"RECORDED_HASH_MISSING evidence={ev.get('evidence_id')}")
            )

    for run in _runs(state):
        if run.get("candidate_id") not in candidates:
            violations.append(
                Violation("CONTRACT_VIOLATION", "EvaluationRun", f"UNKNOWN_CANDIDATE_REF run={run.get('run_id')}")
            )
        if run.get("policy_ref") not in policies:
            violations.append(
                Violation("CONTRACT_VIOLATION", "EvaluationRun", f"UNKNOWN_POLICY_REF run={run.get('run_id')}")
            )
        if not run.get("manifest_recorded_hash") or not run.get("manifest_current_hash"):
            violations.append(
                Violation("CONTRACT_VIOLATION", "EvaluationRun", f"RECORDED_HASH_MISSING run={run.get('run_id')}")
            )
        for ev_id in run.get("evidence_ids", []) or []:
            evs = evidence_by_id.get(ev_id, [])
            if not evs or any(ev.get("run_id") != run.get("run_id") for ev in evs):
                violations.append(
                    Violation(
                        "CONTRACT_VIOLATION",
                        "EvaluationRun",
                        f"EVIDENCE_RUN_MISMATCH run={run.get('run_id')} evidence={ev_id}",
                    )
                )

    for decision in _get(state, "decisions", []) or []:
        if decision.get("candidate_id") not in candidates:
            violations.append(
                Violation("CONTRACT_VIOLATION", "Decision", f"UNKNOWN_CANDIDATE_REF decision={decision.get('decision_id')}")
            )
        if decision.get("run_id") not in run_ids:
            violations.append(
                Violation("CONTRACT_VIOLATION", "Decision", f"UNKNOWN_RUN_REF decision={decision.get('decision_id')}")
            )
        if decision.get("policy_ref") not in policies:
            violations.append(
                Violation("CONTRACT_VIOLATION", "Decision", f"UNKNOWN_POLICY_REF decision={decision.get('decision_id')}")
            )
        if not decision.get("recorded_hash") or not decision.get("current_hash"):
            violations.append(
                Violation("CONTRACT_VIOLATION", "Decision", f"RECORDED_HASH_MISSING decision={decision.get('decision_id')}")
            )

    for cand_id, prov in (_get(state, "provenance", {}) or {}).items():
        if cand_id not in candidates:
            violations.append(
                Violation("CONTRACT_VIOLATION", "Provenance", f"UNKNOWN_CANDIDATE_REF provenance={cand_id}")
            )
        for rid in prov.get("run_ids", []) or []:
            if rid not in run_ids:
                violations.append(
                    Violation("CONTRACT_VIOLATION", "Provenance", f"UNKNOWN_RUN_REF provenance={cand_id} run={rid}")
                )
    return violations


def validate_promotion(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    policies = _get(state, "policies", {}) or {}
    provenance = _get(state, "provenance", {}) or {}
    for decision in _get(state, "decisions", []) or []:
        if decision.get("value") != "PROMOTE":
            continue
        policy = policies.get(decision.get("policy_ref"))
        run = _run(state, decision.get("run_id"))
        if not policy or not policy.get("registered"):
            violations.append(
                Violation(
                    "GOVERNANCE_BLOCK",
                    "G1",
                    f"POLICY_NOT_REGISTERED decision={decision.get('decision_id')}",
                )
            )
        if policy and not policy.get("frozen"):
            violations.append(
                Violation(
                    "GOVERNANCE_BLOCK",
                    "G2",
                    f"POLICY_NOT_FROZEN decision={decision.get('decision_id')}",
                )
            )
        if run and policy and (
            run.get("policy_ref") != decision.get("policy_ref")
            or run.get("policy_version") != policy.get("version")
        ):
            violations.append(
                Violation(
                    "GOVERNANCE_BLOCK",
                    "G3",
                    f"RUN_POLICY_MISMATCH decision={decision.get('decision_id')}",
                )
            )
        if decision.get("gate_result") != "PASS":
            violations.append(
                Violation(
                    "CONTRACT_VIOLATION",
                    "GATE",
                    f"PROMOTE_WITHOUT_GATE_PASS decision={decision.get('decision_id')}",
                )
            )
        missing = _missing_provenance(provenance.get(decision.get("candidate_id"), {}), decision.get("run_id"))
        if missing:
            violations.append(
                Violation(
                    "PROVENANCE_INCOMPLETE",
                    "G4",
                    f"PROVENANCE_INCOMPLETE decision={decision.get('decision_id')} missing={','.join(missing)}",
                )
            )
    return violations


def validate_lifecycle(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    for cand_id, lc in (_get(state, "lifecycle", {}) or {}).items():
        transitions = lc.get("transitions", []) or []
        for transition in transitions:
            source = transition.get("from")
            target = transition.get("to")
            if target not in TRANSITIONS.get(source, set()):
                violations.append(
                    Violation(
                        "INVALID_TRANSITION",
                        "LIFECYCLE",
                        f"ILLEGAL_TRANSITION candidate={cand_id} {source}->{target}",
                    )
                )
        status = lc.get("status")
        if status == "REJECTED" and transitions:
            violations.append(
                Violation("INVALID_TRANSITION", "LIFECYCLE", f"REJECTED_IS_TERMINAL candidate={cand_id}")
            )
        if status == "PROMOTED" and not any(
            t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED" for t in transitions
        ):
            violations.append(
                Violation("INVALID_TRANSITION", "LIFECYCLE", f"PROMOTED_WITHOUT_PROMOTABLE candidate={cand_id}")
            )
        if status == "PROMOTABLE":
            missing = _governance_missing(state, cand_id)
            if missing:
                violations.append(
                    Violation(
                        "GOVERNANCE_BLOCK",
                        "G1-G4",
                        f"PROMOTABLE_WITHOUT_GOVERNANCE candidate={cand_id} missing={','.join(missing)}",
                    )
                )
    return violations


def validate_immutability(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    for ev in _get(state, "evidence", []) or []:
        if ev.get("recorded_hash") != ev.get("current_hash"):
            violations.append(
                Violation(
                    "IMMUTABILITY_VIOLATION",
                    "G5",
                    f"EVIDENCE_TAMPERED evidence={ev.get('evidence_id')}",
                )
            )
    for cand_id, cand in (_get(state, "candidates", {}) or {}).items():
        if cand.get("recorded_artifact_hashes") != cand.get("current_artifact_hashes"):
            violations.append(
                Violation(
                    "IMMUTABILITY_VIOLATION",
                    "G5",
                    f"ARTIFACT_HASH_CHANGED candidate={cand_id}",
                )
            )
    for run in _runs(state):
        if run.get("manifest_recorded_hash") != run.get("manifest_current_hash"):
            violations.append(
                Violation(
                    "IMMUTABILITY_VIOLATION",
                    "G5",
                    f"MANIFEST_TAMPERED run={run.get('run_id')}",
                )
            )

    def differing(items: list[dict], kind: str, fields: tuple[str, ...]) -> list[Violation]:
        out: list[Violation] = []
        seen: dict[Any, dict] = {}
        for item in items:
            if kind == "Evidence":
                key = item.get("evidence_id")
            elif kind == "Decision":
                key = item.get("decision_id")
            else:
                key = item.get("run_id")
            if key in seen and any(seen[key].get(f) != item.get(f) for f in fields):
                out.append(
                    Violation(
                        "IMMUTABILITY_VIOLATION",
                        "G7",
                        f"{kind.upper()}_OVERWRITTEN id={key}",
                    )
                )
            seen.setdefault(key, item)
        return out

    violations += differing(
        _get(state, "evidence", []) or [],
        "Evidence",
        ("run_id", "recorded_hash", "current_hash"),
    )
    violations += differing(
        _runs(state),
        "EvaluationRun",
        ("candidate_id", "policy_ref", "policy_version", "evidence_ids", "manifest_recorded_hash"),
    )
    violations += differing(
        _get(state, "decisions", []) or [],
        "Decision",
        ("candidate_id", "run_id", "policy_ref", "value", "recorded_hash"),
    )
    return violations


def validate_hold_reentry(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    for cand_id, lc in (_get(state, "lifecycle", {}) or {}).items():
        reentry = any(
            t.get("from") == "HOLD" and t.get("to") == "EVALUATING"
            for t in (lc.get("transitions", []) or [])
        )
        if not reentry:
            continue
        runs = [r for r in _runs(state) if r.get("candidate_id") == cand_id]
        hold_runs = [r for r in runs if r.get("status") == "HOLD"]
        later = [r for r in runs if r.get("status") != "HOLD"]
        if not hold_runs or not later:
            violations.append(
                Violation(
                    "CONTRACT_VIOLATION",
                    "G6",
                    f"HOLD_REENTRY_WITHOUT_NEW_RUN candidate={cand_id}",
                )
            )
            continue
        for hold in hold_runs:
            after = [r for r in runs if str(r.get("created_at", "")) > str(hold.get("created_at", ""))]
            if any(r.get("run_id") == hold.get("run_id") for r in after):
                violations.append(
                    Violation(
                        "CONTRACT_VIOLATION",
                        "G6",
                        f"RUN_REUSE_AFTER_HOLD candidate={cand_id} run={hold.get('run_id')}",
                    )
                )
            if not any(r.get("run_id") != hold.get("run_id") for r in after):
                violations.append(
                    Violation(
                        "CONTRACT_VIOLATION",
                        "G6",
                        f"HOLD_REENTRY_WITHOUT_NEW_RUN candidate={cand_id} run={hold.get('run_id')}",
                    )
                )
    return violations


def validate_extension_isolation(state: dict, contracts: dict | None = None) -> list[Violation]:
    violations: list[Violation] = []
    table = CONTRACTS if contracts is None else contracts
    for contract_name, spec in table.items():
        overlap = sorted(EXTENSION_OWNED_KEYS & set(spec.get("required_invariants", [])))
        if overlap:
            violations.append(
                Violation(
                    "EXTENSION_SCHEMA_ERROR",
                    "EXT",
                    f"CORE_REQUIRES_EXTENSION_FIELD contract={contract_name} fields={','.join(overlap)}",
                )
            )
    for consumer, block in (_get(state, "extensions", {}) or {}).items():
        if not isinstance(block, dict):
            violations.append(
                Violation("EXTENSION_SCHEMA_ERROR", "EXT", f"EXTENSION_NOT_OBJECT consumer={consumer}")
            )
            continue
        if not block.get("applicability"):
            violations.append(
                Violation("EXTENSION_SCHEMA_ERROR", "EXT", f"EXTENSION_MISSING_APPLICABILITY consumer={consumer}")
            )
        if not block.get("provenance_ref"):
            violations.append(
                Violation("EXTENSION_SCHEMA_ERROR", "EXT", f"EXTENSION_MISSING_PROVENANCE consumer={consumer}")
            )
    return violations


def validate(state: dict) -> dict:
    """Validate one protocol snapshot; returns pass, violations, verdict."""
    violations: list[Violation] = []
    violations += validate_references(state)
    violations += validate_promotion(state)
    violations += validate_lifecycle(state)
    violations += validate_immutability(state)
    violations += validate_hold_reentry(state)
    violations += validate_extension_isolation(state)

    core_bad = any(v.code != "EXTENSION_SCHEMA_ERROR" for v in violations)
    extension_bad = any(v.code == "EXTENSION_SCHEMA_ERROR" for v in violations)
    if core_bad:
        verdict = "CONTRACT_INVALID"
    elif extension_bad:
        verdict = "CONTRACT_PARTIAL"
    elif _get(state, "extensions"):
        verdict = "CONTRACT_VALID_WITH_EXTENSIONS"
    else:
        verdict = "CONTRACT_VALID"

    counts: dict[str, int] = {}
    for v in violations:
        counts[v.code] = counts.get(v.code, 0) + 1
    return {
        "pass": not violations,
        "verdict": verdict,
        "violations": [v.as_dict() for v in violations],
        "counts": counts,
    }


__all__ = [
    "CONTRACTS",
    "EXTENSION_OWNED_KEYS",
    "STATUSES",
    "TRANSITIONS",
    "Violation",
    "validate",
    "validate_extension_isolation",
    "validate_hold_reentry",
    "validate_immutability",
    "validate_lifecycle",
    "validate_promotion",
    "validate_references",
]
