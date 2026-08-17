#!/usr/bin/env python3
"""Phase 7.6 unified AdoptionAuthority contract validator (offline only).

Validates one AdoptionAuthority binding against the same records Phase
7.4/7.4.1 machine-checked (decision / run / policy / candidate / lifecycle /
digest / provenance), then combines per-system verdicts fail-closed:

    ALLOW only if every system says ALLOW for the same authority.
    Any BLOCK / UNKNOWN / missing verdict -> ADOPTION_BLOCKED.
    Fallback flags never grant ALLOW.

This is an offline contract proof, not production enforcement.
"""

from __future__ import annotations

import copy
import json
import sys

AUTHORITY_FIELDS = (
    "candidate_id",
    "candidate_version",
    "promotion_decision_id",
    "evaluation_run_id",
    "policy_version",
    "artifact_digest",
    "provenance",
)

OPTIONAL_AUTHORITY_FIELDS = ("expires_at", "revocation_reference")
SYSTEMS = ("registry", "runtime", "external")
FALLBACK_FLAGS = ("use_latest", "use_previous", "use_active", "use_manual")
NON_PROMOTE_VALUES = {"HOLD", "REJECTED", "REJECT", "CANARY", "PENDING"}
PROVENANCE_KEYS = ("policy", "evidence_manifest", "run_ids", "immutable_artifact_refs")


def valid_state() -> dict:
    """Pre-adoption snapshot: lifecycle PROMOTABLE, matching decision/run."""
    return {
        "policies": {
            "pol-1": {
                "version": "1",
                "registered": True,
                "frozen": True,
                "content_hash": "p1",
                "commit_ref": "c1",
            }
        },
        "candidates": {
            "cand-1": {
                "version": "v1",
                "created_at": "2026-08-17T00:00:00Z",
                "forged_artifact_digest": "a1",
            }
        },
        "runs": [
            {
                "run_id": "run-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "artifact_digest": "a1",
                "policy_ref": "pol-1",
                "policy_version": "1",
                "status": "EVALUATED",
                "created_at": "2026-08-17T00:30:00Z",
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "run_id": "run-1",
                "recorded_hash": "e1",
                "current_hash": "e1",
            }
        ],
        "provenance": {
            "cand-1": {
                "policy": True,
                "evidence_manifest": True,
                "run_ids": ["run-1"],
                "immutable_artifact_refs": ["art-1"],
            }
        },
        "decisions": [
            {
                "decision_id": "dec-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "run_id": "run-1",
                "policy_ref": "pol-1",
                "policy_version": "1",
                "artifact_digest": "a1",
                "value": "PROMOTE",
                "gate_result": "PASS",
                "created_at": "2026-08-17T01:00:00Z",
                "recorded_hash": "d1",
                "current_hash": "d1",
            }
        ],
        "lifecycle": {
            "cand-1": {
                "status": "PROMOTABLE",
                "transitions": [
                    {"from": "PROMOTABLE", "to": "PROMOTED"},
                ],
            }
        },
        "revocations": [],
        "registry_promoted": [],
    }


def post_state(pre: dict) -> dict:
    """Post-registry snapshot: lifecycle PROMOTED + recorded transition."""
    state = copy.deepcopy(pre)
    state["lifecycle"]["cand-1"]["status"] = "PROMOTED"
    state["registry_promoted"] = [
        {
            "entry_id": "F+/foo",
            "candidate_id": "cand-1",
            "candidate_version": "v1",
            "decision_id": "dec-1",
        }
    ]
    return state


def valid_authority() -> dict:
    return {
        "authority_id": "auth-1",
        "candidate_id": "cand-1",
        "candidate_version": "v1",
        "promotion_decision_id": "dec-1",
        "evaluation_run_id": "run-1",
        "policy_version": "1",
        "artifact_digest": "a1",
        "provenance": {
            "policy": True,
            "evidence_manifest": True,
            "run_ids": ["run-1"],
            "immutable_artifact_refs": ["art-1"],
        },
        "issued_at": "2026-08-17T01:00:00Z",
    }


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


def _missing_provenance(prov, run_id: str | None) -> list[str]:
    if not isinstance(prov, dict):
        return ["provenance"]
    missing = [k for k in PROVENANCE_KEYS if not prov.get(k)]
    if run_id is not None and run_id not in (prov.get("run_ids") or []):
        missing.append(f"run_ids:{run_id}")
    return missing


def _revoked(state: dict, cand_id: str | None, cand_ver: str | None,
             decision_id: str | None, ref: str | None = None) -> bool:
    revocations = state.get("revocations")
    if revocations is None:
        return False  # no revocation store: UNKNOWN, not fabricated
    for r in revocations or []:
        if (
            r.get("candidate_id") == cand_id
            and r.get("candidate_version") == cand_ver
            and r.get("decision_id") == decision_id
        ):
            return True
    if ref:
        return not any(r.get("revocation_id") == ref for r in revocations or [])
    return False


def violations_for_authority(
    authority: dict,
    state: dict,
    expected_lifecycle: str = "PROMOTABLE",
) -> list[dict]:
    """All ADOPTION_BLOCKED reasons for one authority at one system boundary."""
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    missing = [f for f in AUTHORITY_FIELDS if authority.get(f) in (None, "", {})]
    if missing:
        block("REQUEST_METADATA_MISSING", f"missing={','.join(missing)}")

    cand_id = authority.get("candidate_id")
    cand_ver = authority.get("candidate_version")
    decision = _decision(state, authority.get("promotion_decision_id"))
    if decision is None:
        block("MISSING_DECISION", f"decision={authority.get('promotion_decision_id')}")
        return violations

    run = _run(state, decision.get("run_id"))
    policy = _policy(state, decision.get("policy_ref"))
    candidate = (state.get("candidates", {}) or {}).get(cand_id, {})
    lifecycle = _lifecycle(state, cand_id)

    if decision.get("value") != "PROMOTE":
        block(
            "DECISION_NOT_PROMOTE",
            f"decision={decision.get('decision_id')} value={decision.get('value')}",
        )
    if decision.get("gate_result") != "PASS":
        block(
            "GATE_NOT_PASS",
            f"decision={decision.get('decision_id')} gate_result={decision.get('gate_result')}",
        )
    if authority.get("evaluation_run_id") != decision.get("run_id"):
        block(
            "RUN_MISMATCH",
            f"authority={authority.get('evaluation_run_id')} decision={decision.get('run_id')}",
        )
    if run is None:
        block("RUN_MISSING", f"run_id={decision.get('run_id')}")

    if cand_id != decision.get("candidate_id") or (
        run is not None and cand_id != run.get("candidate_id")
    ):
        block(
            "CANDIDATE_ID_MISMATCH",
            f"authority={cand_id} decision={decision.get('candidate_id')} "
            f"run={run.get('candidate_id') if run else None}",
        )
    if (
        cand_ver != decision.get("candidate_version")
        or cand_ver != candidate.get("version")
        or (run is not None and cand_ver != run.get("candidate_version"))
    ):
        block(
            "CANDIDATE_VERSION_MISMATCH",
            f"authority={cand_ver} decision={decision.get('candidate_version')} "
            f"run={run.get('candidate_version') if run else None} "
            f"candidate={candidate.get('version')}",
        )

    if authority.get("policy_version") != decision.get("policy_version"):
        block(
            "POLICY_VERSION_MISMATCH",
            f"authority={authority.get('policy_version')} "
            f"decision={decision.get('policy_version')}",
        )
    if not policy or not policy.get("registered"):
        block("POLICY_NOT_REGISTERED", f"policy={decision.get('policy_ref')}")
    if policy and not policy.get("frozen"):
        block("POLICY_NOT_FROZEN", f"policy={decision.get('policy_ref')}")
    if run and policy and (
        run.get("policy_ref") != decision.get("policy_ref")
        or run.get("policy_version") != decision.get("policy_version")
        or run.get("policy_version") != policy.get("version")
    ):
        block("RUN_POLICY_MISMATCH", f"run={run.get('run_id')}")

    digests = {
        "authority": authority.get("artifact_digest"),
        "decision": decision.get("artifact_digest"),
        "run": run.get("artifact_digest") if run else None,
        "candidate": candidate.get("forged_artifact_digest"),
    }
    if len(set(digests.values())) != 1 or not next(iter(digests.values())):
        block(
            "ARTIFACT_DIGEST_MISMATCH",
            " ".join(f"{k}={v}" for k, v in digests.items()),
        )

    missing_prov = _missing_provenance(
        authority.get("provenance") or (state.get("provenance", {}) or {}).get(cand_id, {}),
        decision.get("run_id"),
    )
    if missing_prov:
        block("PROVENANCE_INCOMPLETE", f"missing={','.join(missing_prov)}")
    if decision.get("recorded_hash") != decision.get("current_hash"):
        block("DECISION_TAMPERED", f"decision={decision.get('decision_id')}")
    for ev in state.get("evidence", []) or []:
        if (
            ev.get("run_id") == decision.get("run_id")
            and ev.get("recorded_hash") != ev.get("current_hash")
        ):
            block("EVIDENCE_TAMPERED", f"evidence={ev.get('evidence_id')}")
            break

    if not lifecycle:
        block("MISSING_LIFECYCLE", f"candidate={cand_id}")
    elif lifecycle.get("status") == "REJECTED":
        block("CANDIDATE_REJECTED", f"candidate={cand_id}")
    elif lifecycle.get("status") != expected_lifecycle:
        block(
            "INVALID_LIFECYCLE",
            f"candidate={cand_id} expected={expected_lifecycle} "
            f"actual={lifecycle.get('status')}",
        )
    elif not any(
        t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
        for t in (lifecycle.get("transitions", []) or [])
    ):
        block(
            "INVALID_LIFECYCLE",
            f"candidate={cand_id} missing=PROMOTABLE->PROMOTED",
        )

    if expected_lifecycle == "PROMOTED":
        promoted = [
            e
            for e in (state.get("registry_promoted", []) or [])
            if e.get("candidate_id") == cand_id
            and e.get("candidate_version") == cand_ver
            and e.get("decision_id") == decision.get("decision_id")
        ]
        if not promoted:
            block(
                "PROMOTED_WITHOUT_DECISION",
                f"candidate={cand_id} version={cand_ver} decision={decision.get('decision_id')}",
            )

    if _revoked(
        state,
        cand_id,
        cand_ver,
        decision.get("decision_id"),
        authority.get("revocation_reference"),
    ):
        block("REVOKED_DECISION", f"decision={decision.get('decision_id')}")

    if authority.get("issued_at") is not None and authority.get("issued_at") != decision.get("created_at"):
        block(
            "AUTHORITY_ISSUED_AT_MISMATCH",
            f"authority={authority.get('issued_at')} decision={decision.get('created_at')}",
        )
    if authority.get("expires_at") is not None and not isinstance(authority.get("expires_at"), str):
        block("REQUEST_METADATA_MISSING", "expires_at must be a string when present")

    if not decision.get("created_at"):
        block("MISSING_DECISION_TIMESTAMP", f"decision={decision.get('decision_id')}")
        return violations
    stale = bool(
        candidate.get("created_at")
        and decision.get("created_at") < candidate.get("created_at")
    )
    later_promote = any(
        d.get("decision_id") != decision.get("decision_id")
        and d.get("candidate_id") == cand_id
        and d.get("candidate_version") == cand_ver
        and d.get("value") == "PROMOTE"
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        for d in (state.get("decisions", []) or [])
    )
    later_non_promote = any(
        d.get("decision_id") != decision.get("decision_id")
        and d.get("candidate_id") == cand_id
        and d.get("candidate_version") == cand_ver
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        and d.get("value") in NON_PROMOTE_VALUES
        for d in (state.get("decisions", []) or [])
    )
    if stale or later_promote or later_non_promote:
        block("STALE_DECISION", f"decision={decision.get('decision_id')}")
    return violations


def check_system(system: str, authority: dict, state: dict) -> dict:
    expected = "PROMOTABLE" if system == "registry" else "PROMOTED"
    violations = violations_for_authority(authority, state, expected)
    return {
        "system": system,
        "verdict": "ALLOW" if not violations else "BLOCK",
        "violations": violations,
    }


def combine(
    authority: dict,
    pre_state: dict,
    post_state: dict | None = None,
    system_verdicts: dict[str, str] | None = None,
    **fallback_flags: bool,
) -> dict:
    """One decision for the whole flow; fail-closed across all systems."""
    post_state = post_state if post_state is not None else pre_state
    checks = {
        system: check_system(system, authority, pre_state if system == "registry" else post_state)
        for system in SYSTEMS
    }
    for system, verdict in (system_verdicts or {}).items():
        if system in checks:
            checks[system] = {**checks[system], "verdict": verdict}

    violations: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for system in SYSTEMS:
        result = checks[system]
        for v in result["violations"]:
            key = (v["code"], v["message"])
            if key not in seen:
                seen.add(key)
                violations.append(v)
        verdict = result["verdict"]
        if verdict == "BLOCK" and not any(
            v["code"].startswith("SYSTEM_") for v in result["violations"]
        ):
            violations.append(
                {
                    "code": f"SYSTEM_{system.upper()}_BLOCKED",
                    "message": f"system={system} rejected the authority",
                }
            )
        elif verdict != "ALLOW":
            violations.append(
                {
                    "code": f"SYSTEM_{system.upper()}_UNKNOWN",
                    "message": f"system={system} verdict={verdict} is not ALLOW",
                }
            )

    for flag in FALLBACK_FLAGS:
        if fallback_flags.get(flag):
            violations.append(
                {
                    "code": "FALLBACK_NOT_AUTHORITY",
                    "message": f"{flag}=True is not an adoption authority",
                }
            )

    counts: dict[str, int] = {}
    for v in violations:
        counts[v["code"]] = counts.get(v["code"], 0) + 1
    allowed = all(checks[s]["verdict"] == "ALLOW" for s in SYSTEMS) and not violations
    return {
        "schema": "adoption_authority_v1",
        "authority_id": authority.get("authority_id", "?"),
        "allowed": allowed,
        "verdict": "ALLOW" if allowed else "ADOPTION_BLOCKED",
        "system_verdicts": {s: checks[s]["verdict"] for s in SYSTEMS},
        "violations": violations,
        "counts": counts,
        "unknowns": {
            "revocation": "NONE" if "revocations" in pre_state else "UNKNOWN",
            "expiry": "UNKNOWN",  # no expires_at semantics in this repo
        },
    }


def main() -> int:
    report = combine(valid_authority(), valid_state(), post_state(valid_state()))
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if report["allowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
