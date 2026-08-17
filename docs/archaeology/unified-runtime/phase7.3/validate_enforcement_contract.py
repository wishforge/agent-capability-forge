#!/usr/bin/env python3
"""Phase 7.3 enforcement boundary validator (offline, minimal).

Composes the Phase 7.2 protocol validator (G1-G7) with the adoption gate:
every Registry write / Runtime adoption must be backed by a valid PROMOTE
Decision bound to the exact candidate_version + policy_version.

Snapshot = Phase 7.2 snapshot plus:
    candidates[id].version / created_at
    decisions[] .candidate_version / .policy_version / .created_at
    adoptions[] {adoption_id, candidate_id, candidate_version,
                 decision_id, policy_version}

Failure codes:
    ADOPTION_BLOCKED      adoption attempt rejected by the contract
    (Phase 7.2 codes preserved: GOVERNANCE_BLOCK / PROVENANCE_INCOMPLETE /
     INVALID_TRANSITION / IMMUTABILITY_VIOLATION / CONTRACT_VIOLATION /
     EXTENSION_SCHEMA_ERROR)

Verdicts:
    ENFORCEMENT_BOUNDARY_VALID     no violations; adoption exercised
    ENFORCEMENT_BOUNDARY_PARTIAL   no adoption, extension-only violations, or
                                   an adoption attempt blocked by the offline
                                   guard (offline contract works; runtime /
                                   registry guard still absent)
    ENFORCEMENT_BOUNDARY_INVALID   protocol-level core violation
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "phase7.2"))

from validate_protocol_contract import (  # noqa: E402
    Violation,
    _missing_provenance,
    validate as validate_protocol,
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


def validate_adoption_contract(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    decisions = state.get("decisions", []) or []
    for adoption in state.get("adoptions", []) or []:
        aid = adoption.get("adoption_id", "?")
        cand_id = adoption.get("candidate_id")
        cand_ver = adoption.get("candidate_version")
        decision = _decision(state, adoption.get("decision_id"))
        if decision is None:
            violations.append(
                Violation("ADOPTION_BLOCKED", "GATE", f"DECISION_MISSING adoption={aid}")
            )
            continue
        candidate = (state.get("candidates", {}) or {}).get(cand_id, {})
        run = _run(state, decision.get("run_id"))
        policy = _policy(state, decision.get("policy_ref"))
        prov = (state.get("provenance", {}) or {}).get(cand_id, {})

        def block(invariant: str, message: str) -> None:
            violations.append(
                Violation("ADOPTION_BLOCKED", invariant, f"{message} adoption={aid}")
            )

        if decision.get("value") != "PROMOTE":
            block("GATE", f"DECISION_NOT_PROMOTE decision={decision.get('decision_id')} value={decision.get('value')}")
        if decision.get("gate_result") != "PASS":
            block("GATE", f"GATE_NOT_PASS decision={decision.get('decision_id')} gate_result={decision.get('gate_result')}")
        if run is None:
            block("RUN", f"RUN_MISSING decision={decision.get('decision_id')} run_id={decision.get('run_id')}")
        if cand_id != decision.get("candidate_id") or (
            run is not None
            and (
                cand_id != run.get("candidate_id")
                or decision.get("candidate_id") != run.get("candidate_id")
            )
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
        if adoption.get("policy_version") != decision.get("policy_version"):
            block(
                "POLICY",
                f"POLICY_VERSION_MISMATCH adoption={adoption.get('policy_version')} "
                f"decision={decision.get('policy_version')}",
            )
        if not policy or not policy.get("registered"):
            block("G1", f"POLICY_NOT_REGISTERED policy={decision.get('policy_ref')}")
        if policy and not policy.get("frozen"):
            block("G2", f"POLICY_NOT_FROZEN policy={decision.get('policy_ref')}")
        if run and policy and (
            run.get("policy_ref") != decision.get("policy_ref")
            or run.get("policy_version") != policy.get("version")
            or decision.get("policy_version") != policy.get("version")
        ):
            block("G3", f"RUN_POLICY_MISMATCH run={run.get('run_id')}")
        missing = _missing_provenance(prov, decision.get("run_id"))
        if missing:
            block("G4", f"PROVENANCE_INCOMPLETE missing={','.join(missing)}")
        for ev in state.get("evidence", []) or []:
            if ev.get("run_id") == decision.get("run_id") and ev.get("recorded_hash") != ev.get("current_hash"):
                block("G5", f"EVIDENCE_TAMPERED evidence={ev.get('evidence_id')}")
        if decision.get("recorded_hash") != decision.get("current_hash"):
            block("G5", f"DECISION_TAMPERED decision={decision.get('decision_id')}")

        lifecycle = (state.get("lifecycle", {}) or {}).get(cand_id)
        if not lifecycle:
            block("LIFECYCLE", f"MISSING_LIFECYCLE candidate={cand_id}")
        else:
            status = lifecycle.get("status")
            has_adoption_transition = any(
                t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
                for t in (lifecycle.get("transitions", []) or [])
            )
            if status != "PROMOTABLE":
                block(
                    "LIFECYCLE",
                    f"INVALID_ADOPTION_LIFECYCLE candidate={cand_id} status={status}",
                )
            elif not has_adoption_transition:
                block(
                    "LIFECYCLE",
                    f"INVALID_ADOPTION_LIFECYCLE candidate={cand_id} missing=PROMOTABLE->PROMOTED",
                )

        latest = max(
            (
                d
                for d in decisions
                if d.get("candidate_version") == cand_ver and d.get("value") == "PROMOTE"
            ),
            key=lambda d: str(d.get("created_at", "")),
            default=None,
        )
        stale = latest is not None and latest.get("decision_id") != decision.get("decision_id")
        if candidate.get("created_at") and decision.get("created_at") < candidate.get("created_at"):
            stale = True
        if stale:
            block(
                "GATE",
                f"STALE_DECISION decision={decision.get('decision_id')} "
                f"latest={latest.get('decision_id') if latest else None}",
            )
    return violations


def validate(state: dict) -> dict:
    protocol = validate_protocol(state)
    violations = list(protocol["violations"])
    violations += [v.as_dict() for v in validate_adoption_contract(state)]

    core_bad = any(
        v["code"] not in ("EXTENSION_SCHEMA_ERROR", "ADOPTION_BLOCKED")
        for v in violations
    )
    extension_bad = any(v["code"] == "EXTENSION_SCHEMA_ERROR" for v in violations)
    adoption_blocked = any(v["code"] == "ADOPTION_BLOCKED" for v in violations)
    adoptions = state.get("adoptions", []) or []
    if core_bad:
        verdict = "ENFORCEMENT_BOUNDARY_INVALID"
    elif extension_bad or adoption_blocked or not adoptions:
        verdict = "ENFORCEMENT_BOUNDARY_PARTIAL"
    else:
        verdict = "ENFORCEMENT_BOUNDARY_VALID"

    counts: dict[str, int] = {}
    for v in violations:
        counts[v["code"]] = counts.get(v["code"], 0) + 1
    return {
        "pass": not violations,
        "verdict": verdict,
        "violations": violations,
        "counts": counts,
        "adoption_ids": [a.get("adoption_id") for a in adoptions],
        "adoptions_allowed": all(
            not any(v["code"] == "ADOPTION_BLOCKED" and f"adoption={a.get('adoption_id')}" in v["message"]
                    for v in violations)
            for a in adoptions
        ),
    }


ADOPTION_BLOCK_CODES = (
    "DECISION_MISSING",
    "DECISION_NOT_PROMOTE",
    "GATE_NOT_PASS",
    "CANDIDATE_ID_MISMATCH",
    "CANDIDATE_VERSION_MISMATCH",
    "RUN_MISSING",
    "POLICY_VERSION_MISMATCH",
    "POLICY_NOT_REGISTERED",
    "POLICY_NOT_FROZEN",
    "RUN_POLICY_MISMATCH",
    "PROVENANCE_INCOMPLETE",
    "EVIDENCE_TAMPERED",
    "DECISION_TAMPERED",
    "MISSING_LIFECYCLE",
    "INVALID_ADOPTION_LIFECYCLE",
    "STALE_DECISION",
)


__all__ = [
    "ADOPTION_BLOCK_CODES",
    "validate",
    "validate_adoption_contract",
]
