#!/usr/bin/env python3
"""Phase 7.4 Adoption Guard design validator (offline, minimal).

Machine-checks the conceptual AdoptionRequest -> AdoptionResult contract
defined in 66-adoption-guard-design.md. Snapshot shape = Phase 7.2/7.3
protocol snapshot plus:

    adoptions[]          AdoptionRequest objects (see doc section 4)
    registry_promoted[]  observed "state == promoted" registry entries
    revocations[]        optional explicit revocation records (UNKNOWN
                         in production until a revocation store exists)

Every failure is ADOPTION_BLOCKED with a machine-readable reason code.
This is an offline contract proof, not production enforcement.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "phase7.2"))

from validate_protocol_contract import Violation, _missing_provenance  # noqa: E402

# Minimal AdoptionRequest fields (66 section 4). adoption_id is required in
# the snapshot for audit; the rest are the conceptual contract fields.
REQUIRED_REQUEST_FIELDS = (
    "candidate_id",
    "candidate_version",
    "promotion_decision_id",
    "evaluation_run_id",
    "policy_version",
    "requested_by",
    "requested_at",
)

# Decision values that supersede an earlier PROMOTE for the same immutable
# candidate_version (66 section 8/9).
NON_PROMOTE_VALUES = {"HOLD", "REJECTED", "REJECT", "CANARY", "PENDING"}

BLOCK_CODES = (
    "REQUEST_METADATA_MISSING",
    "MISSING_DECISION",
    "DECISION_NOT_PROMOTE",
    "GATE_NOT_PASS",
    "RUN_MISSING",
    "RUN_MISMATCH",
    "CANDIDATE_ID_MISMATCH",
    "CANDIDATE_VERSION_MISMATCH",
    "POLICY_VERSION_MISMATCH",
    "POLICY_NOT_REGISTERED",
    "POLICY_NOT_FROZEN",
    "RUN_POLICY_MISMATCH",
    "PROVENANCE_INCOMPLETE",
    "DECISION_TAMPERED",
    "EVIDENCE_TAMPERED",
    "MISSING_LIFECYCLE",
    "INVALID_LIFECYCLE",
    "CANDIDATE_REJECTED",
    "REVOKED_DECISION",
    "STALE_DECISION",
    "PROMOTED_WITHOUT_DECISION",
    "ARTIFACT_DIGEST_MISMATCH",
    "MISSING_DECISION_TIMESTAMP",
)


def _decision(state: dict, decision_id: str | None) -> dict | None:
    return next(
        (d for d in (state.get("decisions", []) or []) if d.get("decision_id") == decision_id),
        None,
    )


def _run(state: dict, run_id: str | None) -> dict | None:
    return next(
        (r for r in (state.get("runs", []) or []) if r.get("run_id") == run_id),
        None,
    )


def _policy(state: dict, policy_ref: str | None) -> dict | None:
    return (state.get("policies", {}) or {}).get(policy_ref)


def _lifecycle(state: dict, candidate_id: str | None) -> dict | None:
    return (state.get("lifecycle", {}) or {}).get(candidate_id)


def _revocation(state: dict, candidate_id: str | None, candidate_version: str | None,
                decision_id: str | None) -> dict | None:
    return next(
        (
            r
            for r in (state.get("revocations", []) or [])
            if r.get("candidate_id") == candidate_id
            and r.get("candidate_version") == candidate_version
            and r.get("decision_id") == decision_id
        ),
        None,
    )


def _latest_promote(state: dict, candidate_id: str | None, candidate_version: str | None) -> dict | None:
    return max(
        (
            d
            for d in (state.get("decisions", []) or [])
            if d.get("candidate_id") == candidate_id
            and d.get("candidate_version") == candidate_version
            and d.get("value") == "PROMOTE"
        ),
        key=lambda d: str(d.get("created_at", "")),
        default=None,
    )


def validate_adoption_guard(state: dict) -> list[Violation]:
    """One AdoptionResult per AdoptionRequest; all failures ADOPTION_BLOCKED."""
    violations: list[Violation] = []
    for request in state.get("adoptions", []) or []:
        aid = request.get("adoption_id", "?")

        def block(invariant: str, message: str) -> None:
            violations.append(
                Violation("ADOPTION_BLOCKED", invariant, f"{message} adoption={aid}")
            )

        missing = [f for f in REQUIRED_REQUEST_FIELDS if not request.get(f)]
        if missing:
            block("REQUEST", f"REQUEST_METADATA_MISSING missing={','.join(missing)}")

        cand_id = request.get("candidate_id")
        cand_ver = request.get("candidate_version")
        decision = _decision(state, request.get("promotion_decision_id"))
        if decision is None:
            block("GATE", f"MISSING_DECISION decision={request.get('promotion_decision_id')}")
            continue

        run = _run(state, decision.get("run_id"))
        policy = _policy(state, decision.get("policy_ref"))
        candidate = (state.get("candidates", {}) or {}).get(cand_id, {})
        prov = request.get("provenance") or (state.get("provenance", {}) or {}).get(cand_id, {})
        lifecycle = _lifecycle(state, cand_id)

        artifact_digests = {
            "adoption": request.get("artifact_digest"),
            "decision": decision.get("artifact_digest"),
            "run": run.get("artifact_digest") if run is not None else None,
            "candidate": candidate.get("forged_artifact_digest"),
        }
        if len(set(artifact_digests.values())) != 1 or not next(iter(artifact_digests.values())):
            block(
                "ARTIFACT",
                "ARTIFACT_DIGEST_MISMATCH "
                + " ".join(f"{k}={v}" for k, v in artifact_digests.items()),
            )

        if decision.get("value") != "PROMOTE":
            block(
                "GATE",
                f"DECISION_NOT_PROMOTE decision={decision.get('decision_id')} "
                f"value={decision.get('value')}",
            )
        if decision.get("gate_result") != "PASS":
            block(
                "GATE",
                f"GATE_NOT_PASS decision={decision.get('decision_id')} "
                f"gate_result={decision.get('gate_result')}",
            )
        if request.get("evaluation_run_id") != decision.get("run_id"):
            block(
                "RUN",
                f"RUN_MISMATCH request={request.get('evaluation_run_id')} "
                f"decision={decision.get('run_id')}",
            )
        if run is None:
            block(
                "RUN",
                f"RUN_MISSING decision={decision.get('decision_id')} run_id={decision.get('run_id')}",
            )
        if cand_id != decision.get("candidate_id") or (
            run is not None and cand_id != run.get("candidate_id")
        ):
            block(
                "CANDIDATE",
                f"CANDIDATE_ID_MISMATCH adoption={cand_id} "
                f"decision={decision.get('candidate_id')} run={run.get('candidate_id') if run else None}",
            )
        if (
            cand_ver != decision.get("candidate_version")
            or cand_ver != candidate.get("version")
            or (run is not None and cand_ver != run.get("candidate_version"))
        ):
            block(
                "CANDIDATE",
                f"CANDIDATE_VERSION_MISMATCH candidate={cand_id} "
                f"adoption={cand_ver} decision={decision.get('candidate_version')} "
                f"run={run.get('candidate_version') if run else None}",
            )
        if request.get("policy_version") != decision.get("policy_version"):
            block(
                "POLICY",
                f"POLICY_VERSION_MISMATCH adoption={request.get('policy_version')} "
                f"decision={decision.get('policy_version')}",
            )
        if not policy or not policy.get("registered"):
            block("G1", f"POLICY_NOT_REGISTERED policy={decision.get('policy_ref')}")
        if policy and not policy.get("frozen"):
            block("G2", f"POLICY_NOT_FROZEN policy={decision.get('policy_ref')}")
        if run and policy and (
            run.get("policy_ref") != decision.get("policy_ref")
            or run.get("policy_version") != request.get("policy_version")
            or run.get("policy_version") != policy.get("version")
        ):
            block("G3", f"RUN_POLICY_MISMATCH run={run.get('run_id')}")
        missing_prov = _missing_provenance(prov, decision.get("run_id"))
        if missing_prov:
            block("G4", f"PROVENANCE_INCOMPLETE missing={','.join(missing_prov)}")
        if decision.get("recorded_hash") != decision.get("current_hash"):
            block("G5", f"DECISION_TAMPERED decision={decision.get('decision_id')}")
        for ev in state.get("evidence", []) or []:
            if ev.get("run_id") == decision.get("run_id") and ev.get("recorded_hash") != ev.get("current_hash"):
                block("G5", f"EVIDENCE_TAMPERED evidence={ev.get('evidence_id')}")
                break

        if not lifecycle:
            block("LIFECYCLE", f"MISSING_LIFECYCLE candidate={cand_id}")
        elif lifecycle.get("status") == "REJECTED":
            block("LIFECYCLE", f"CANDIDATE_REJECTED candidate={cand_id}")
        elif lifecycle.get("status") != "PROMOTABLE":
            block(
                "LIFECYCLE",
                f"INVALID_LIFECYCLE candidate={cand_id} status={lifecycle.get('status')}",
            )
        elif not any(
            t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
            for t in (lifecycle.get("transitions", []) or [])
        ):
            block(
                "LIFECYCLE",
                f"INVALID_LIFECYCLE candidate={cand_id} missing=PROMOTABLE->PROMOTED",
            )
        if _revocation(state, cand_id, cand_ver, decision.get("decision_id")):
            block("LIFECYCLE", f"REVOKED_DECISION decision={decision.get('decision_id')}")

        if not decision.get("created_at"):
            block(
                "GATE",
                f"MISSING_DECISION_TIMESTAMP decision={decision.get('decision_id')}",
            )
        stale = False
        if (
            candidate.get("created_at")
            and decision.get("created_at")
            and decision.get("created_at") < candidate.get("created_at")
        ):
            stale = True
        latest = _latest_promote(state, cand_id, cand_ver)
        if latest is not None and latest.get("decision_id") != decision.get("decision_id"):
            stale = True
        later_non_promote = any(
            d.get("decision_id") != decision.get("decision_id")
            and d.get("candidate_id") == cand_id
            and d.get("candidate_version") == cand_ver
            and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
            and d.get("value") in NON_PROMOTE_VALUES
            for d in (state.get("decisions", []) or [])
        )
        if later_non_promote:
            stale = True
        if stale:
            block("GATE", f"STALE_DECISION decision={decision.get('decision_id')}")
    return violations


def validate_registry_promoted(state: dict, allowed: set[tuple]) -> list[Violation]:
    """state-only 'promoted' trust is forbidden; every promoted registry
    entry must map to an AdoptionRequest that passed the guard."""
    violations: list[Violation] = []
    for entry in state.get("registry_promoted", []) or []:
        key = (entry.get("candidate_id"), entry.get("candidate_version"), entry.get("decision_id"))
        if key not in allowed:
            violations.append(
                Violation(
                    "ADOPTION_BLOCKED",
                    "REGISTRY",
                    f"PROMOTED_WITHOUT_DECISION registry={entry.get('entry_id')} "
                    f"candidate={entry.get('candidate_id')} version={entry.get('candidate_version')}",
                )
            )
    for cand_id, lc in (state.get("lifecycle", {}) or {}).items():
        if lc.get("status") != "PROMOTED":
            continue
        version = (state.get("candidates", {}) or {}).get(cand_id, {}).get("version")
        if not any(
            a[0] == cand_id and a[1] == version
            for a in allowed
        ):
            violations.append(
                Violation(
                    "ADOPTION_BLOCKED",
                    "REGISTRY",
                    f"PROMOTED_WITHOUT_DECISION candidate={cand_id} version={version}",
                )
            )
    return violations


def validate(state: dict) -> dict:
    violations = validate_adoption_guard(state)
    adoptions = state.get("adoptions", []) or []
    allowed: set[tuple] = set()
    for request in adoptions:
        aid = request.get("adoption_id", "?")
        if not any(
            v.code == "ADOPTION_BLOCKED" and f"adoption={aid}" in v.message
            for v in violations
        ):
            allowed.add(
                (
                    request.get("candidate_id"),
                    request.get("candidate_version"),
                    request.get("promotion_decision_id"),
                )
            )
    violations += validate_registry_promoted(state, allowed)
    violations = [v.as_dict() for v in violations]

    blocked = any(v["code"] == "ADOPTION_BLOCKED" for v in violations)
    revocations_absent = "revocations" not in state
    if blocked or not adoptions:
        verdict = "ADOPTION_GUARD_DESIGN_PARTIAL"
    elif revocations_absent:
        verdict = "ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN"
    else:
        verdict = "ADOPTION_GUARD_DESIGN_VALID"

    counts: dict[str, int] = {}
    for v in violations:
        counts[v["code"]] = counts.get(v["code"], 0) + 1
    return {
        "pass": not violations,
        "verdict": verdict,
        "violations": violations,
        "counts": counts,
        "adoptions_allowed": all(
            not any(
                v["code"] == "ADOPTION_BLOCKED" and f"adoption={request.get('adoption_id', '?')}" in v["message"]
                for v in violations
            )
            for request in adoptions
        ),
        "unknowns": {"revocation": "UNKNOWN" if revocations_absent else "NONE"},
    }


__all__ = [
    "BLOCK_CODES",
    "REQUIRED_REQUEST_FIELDS",
    "validate",
    "validate_adoption_guard",
    "validate_registry_promoted",
]
