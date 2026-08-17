"""Phase 8.2 - Runtime Adoption Guard (pilot B3 activation defense).

Secondary/final activation guard for the only real Runtime execution path:
pilot/harness.py phase_future(arm="b3") mounts a promoted artifact into a
sandbox and runs it. This adapter loads the persisted AdoptionAuthority from
adoption_store.json, re-verifies identity / binding / digest / lifecycle /
policy / provenance / revocation / staleness, and raises ADOPTION_BLOCKED
before any activation unless every check passes.

Registry Guard (pilot/registry.py promote) = primary state-transition
enforcement. Runtime Guard = secondary defense; it never trusts
state == "promoted" alone.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from pilot.adoption_authority import (
    AUTHORITY_FIELDS,
    PROVENANCE_KEYS,
    authority_id_for,
    dir_digest,
    load_store,
)
from pilot.registry import BINDING_KEYS, AdoptionBlocked


def _decision(store: dict, decision_id: str | None) -> dict | None:
    return next(
        (d for d in (store.get("decisions", []) or []) if d.get("decision_id") == decision_id),
        None,
    )


def _run(store: dict, run_id: str | None) -> dict | None:
    return next(
        (r for r in (store.get("runs", []) or []) if r.get("run_id") == run_id),
        None,
    )


def _policy(store: dict, policy_ref: str | None) -> dict | None:
    return (store.get("policies", {}) or {}).get(policy_ref)


def _lifecycle(store: dict, candidate_id: str | None) -> dict | None:
    return (store.get("lifecycle", {}) or {}).get(candidate_id)


def _authority(store: dict, decision_id: str | None) -> dict | None:
    return next(
        (a for a in (store.get("authorities", []) or [])
         if a.get("promotion_decision_id") == decision_id),
        None,
    )


def _missing_provenance(prov, run_id: str | None) -> list[str]:
    if not isinstance(prov, dict):
        return ["provenance"]
    missing = [k for k in PROVENANCE_KEYS if not prov.get(k)]
    if run_id is not None and run_id not in (prov.get("run_ids") or []):
        missing.append(f"run_ids:{run_id}")
    return missing


def violations_for_runtime_activation(
    entry: dict,
    authority: dict | None,
    store: dict,
    actual_artifact_digest: str | None,
) -> list[dict]:
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    adoption = entry.get("adoption") or {}
    if entry.get("state") != "promoted":
        block("REGISTRY_STATE_NOT_PROMOTED", f"state={entry.get('state')}")
    missing_binding = [k for k in BINDING_KEYS if adoption.get(k) in (None, "", {})]
    if missing_binding:
        block("ENTRY_BINDING_MISSING", f"missing={','.join(missing_binding)}")
    if authority is None:
        block("MISSING_AUTHORITY", f"decision={adoption.get('promotion_decision_id')}")
        return violations

    missing_fields = [f for f in AUTHORITY_FIELDS if authority.get(f) in (None, "", {})]
    if missing_fields:
        block("REQUEST_METADATA_MISSING", f"missing={','.join(missing_fields)}")
    if authority.get("authority_id") != authority_id_for(
        authority.get("candidate_id"),
        authority.get("candidate_version"),
        authority.get("promotion_decision_id"),
    ):
        block(
            "AUTHORITY_ID_MISMATCH",
            "authority_id is not the deterministic producer id for this binding",
        )
    binding_mismatch = [k for k in BINDING_KEYS if adoption.get(k) != authority.get(k)]
    if binding_mismatch:
        block("ENTRY_BINDING_MISMATCH", f"keys={','.join(binding_mismatch)}")

    decision = _decision(store, authority.get("promotion_decision_id"))
    if decision is None:
        block("MISSING_DECISION", f"decision={authority.get('promotion_decision_id')}")
        return violations
    run = _run(store, decision.get("run_id"))
    policy = _policy(store, decision.get("policy_ref"))
    candidate = (store.get("candidates", {}) or {}).get(authority.get("candidate_id"), {})
    lifecycle = _lifecycle(store, authority.get("candidate_id"))

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
    if authority.get("candidate_id") != decision.get("candidate_id") or (
        run is not None and authority.get("candidate_id") != run.get("candidate_id")
    ):
        block(
            "CANDIDATE_ID_MISMATCH",
            f"authority={authority.get('candidate_id')} decision={decision.get('candidate_id')} "
            f"run={run.get('candidate_id') if run else None}",
        )
    if (
        authority.get("candidate_version") != decision.get("candidate_version")
        or authority.get("candidate_version") != candidate.get("version")
        or (run is not None and authority.get("candidate_version") != run.get("candidate_version"))
    ):
        block(
            "CANDIDATE_VERSION_MISMATCH",
            f"authority={authority.get('candidate_version')} "
            f"decision={decision.get('candidate_version')} "
            f"candidate={candidate.get('version')} "
            f"run={run.get('candidate_version') if run else None}",
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
        "entry": adoption.get("artifact_digest"),
        "artifact": actual_artifact_digest,
    }
    if len(set(digests.values())) != 1 or not next(iter(digests.values())):
        block("ARTIFACT_DIGEST_MISMATCH", " ".join(f"{k}={v}" for k, v in digests.items()))

    missing_prov = _missing_provenance(authority.get("provenance"), decision.get("run_id"))
    if missing_prov:
        block("PROVENANCE_INCOMPLETE", f"missing={','.join(missing_prov)}")
    if decision.get("recorded_hash") != decision.get("current_hash"):
        block("DECISION_TAMPERED", f"decision={decision.get('decision_id')}")
    for ev in store.get("evidence", []) or []:
        if (
            ev.get("run_id") == decision.get("run_id")
            and ev.get("recorded_hash") != ev.get("current_hash")
        ):
            block("EVIDENCE_TAMPERED", f"evidence={ev.get('evidence_id')}")
            break

    if not lifecycle:
        block("MISSING_LIFECYCLE", f"candidate={authority.get('candidate_id')}")
    elif lifecycle.get("status") == "REJECTED":
        block("CANDIDATE_REJECTED", f"candidate={authority.get('candidate_id')}")
    elif lifecycle.get("status") != "PROMOTED":
        block(
            "INVALID_LIFECYCLE",
            f"candidate={authority.get('candidate_id')} expected=PROMOTED "
            f"actual={lifecycle.get('status')}",
        )
    elif not any(
        t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
        for t in (lifecycle.get("transitions", []) or [])
    ):
        block("INVALID_LIFECYCLE", f"candidate={authority.get('candidate_id')} "
                                   "missing=PROMOTABLE->PROMOTED")

    revoked = authority.get("status") in ("REVOKED", "SUPERSEDED") or any(
        r.get("candidate_id") == authority.get("candidate_id")
        and r.get("candidate_version") == authority.get("candidate_version")
        and r.get("decision_id") == decision.get("decision_id")
        for r in (store.get("revocations", []) or [])
    )
    if revoked:
        block("REVOKED_DECISION", f"decision={decision.get('decision_id')}")

    if authority.get("issued_at") is not None and authority.get("issued_at") != decision.get(
        "created_at"
    ):
        block(
            "AUTHORITY_ISSUED_AT_MISMATCH",
            f"authority={authority.get('issued_at')} decision={decision.get('created_at')}",
        )
    if not decision.get("created_at"):
        block("MISSING_DECISION_TIMESTAMP", f"decision={decision.get('decision_id')}")
        return violations
    stale = bool(
        candidate.get("created_at")
        and decision.get("created_at") < candidate.get("created_at")
    )
    later_promote = any(
        d.get("decision_id") != decision.get("decision_id")
        and d.get("candidate_id") == authority.get("candidate_id")
        and d.get("candidate_version") == authority.get("candidate_version")
        and d.get("value") == "PROMOTE"
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        for d in (store.get("decisions", []) or [])
    )
    later_non_promote = any(
        d.get("decision_id") != decision.get("decision_id")
        and d.get("candidate_id") == authority.get("candidate_id")
        and d.get("candidate_version") == authority.get("candidate_version")
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        and d.get("value") in ("HOLD", "REJECTED", "REJECT", "CANARY", "PENDING")
        for d in (store.get("decisions", []) or [])
    )
    if stale or later_promote or later_non_promote:
        block("STALE_DECISION", f"decision={decision.get('decision_id')}")
    return violations


def adopt(registry_root, entry: dict, artifact_dir) -> dict:
    """Validate before the pilot B3 runtime activates/executes an artifact.

    Fail-closed: any missing/mismatch raises AdoptionBlocked
    (ADOPTION_BLOCKED) and nothing is activated.
    """
    registry_root = Path(registry_root)
    store = load_store(registry_root)
    if store is None:
        raise AdoptionBlocked(
            [
                {
                    "code": "MISSING_ADOPTION_STORE",
                    "message": f"missing {registry_root / 'adoption_store.json'}",
                }
            ]
        )
    adoption = entry.get("adoption") or {}
    authority = _authority(store, adoption.get("promotion_decision_id"))
    artifact = Path(artifact_dir)
    actual_digest = dir_digest(artifact) if artifact.is_dir() else None
    violations = violations_for_runtime_activation(entry, authority, store, actual_digest)
    if violations:
        raise AdoptionBlocked(violations)
    return {
        "schema": "runtime_adoption_guard_v1",
        "verdict": "ALLOW",
        "allowed": True,
        "authority_id": authority.get("authority_id"),
        "artifact_digest": actual_digest,
    }


def mark_promoted(registry_root, entry: dict) -> None:
    """Transition store lifecycle PROMOTABLE -> PROMOTED after promote().

    registry.promote() (Phase 8 artifact) writes state="promoted" but cannot
    touch adoption_store lifecycle; this is the pilot runtime's adoption
    wiring and is idempotent (already PROMOTED -> no write).
    """
    registry_root = Path(registry_root)
    store = load_store(registry_root)
    if store is None:
        raise AdoptionBlocked(
            [
                {
                    "code": "MISSING_ADOPTION_STORE",
                    "message": f"missing {registry_root / 'adoption_store.json'}",
                }
            ]
        )
    adoption = entry.get("adoption") or {}
    if entry.get("state") != "promoted":
        raise AdoptionBlocked(
            [{"code": "REGISTRY_STATE_NOT_PROMOTED", "message": f"state={entry.get('state')}"}]
        )
    lifecycle = (store.get("lifecycle", {}) or {}).get(adoption.get("candidate_id"))
    if lifecycle is None:
        raise AdoptionBlocked(
            [{"code": "MISSING_LIFECYCLE", "message": f"candidate={adoption.get('candidate_id')}"}]
        )
    if lifecycle.get("status") == "PROMOTED":
        return
    ok = lifecycle.get("status") == "PROMOTABLE" and any(
        t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
        for t in (lifecycle.get("transitions", []) or [])
    )
    if not ok:
        raise AdoptionBlocked(
            [{"code": "INVALID_LIFECYCLE", "message": f"actual={lifecycle.get('status')}"}]
        )
    lifecycle["status"] = "PROMOTED"
    path = registry_root / "adoption_store.json"
    tmp = path.with_name(f".adoption_store.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(store, indent=2) + "\n")
    os.replace(tmp, path)


__all__ = ["AdoptionBlocked", "adopt", "mark_promoted", "violations_for_runtime_activation"]
