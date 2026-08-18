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
import sys
import uuid
from pathlib import Path

from pilot.adoption_authority import (
    AUTHORITY_FIELDS,
    HARDENED_MODE,
    PROVENANCE_KEYS,
    REVOCABLE_STATUSES,
    authority_id_for,
    dir_digest as legacy_dir_digest,
    integrity_anchor_violations,
    issuer_allowed,
    load_authority_events,
    load_authority_record,
    load_store,
    revocation_violations,
    store_integrity_mode,
    write_trust_anchor,
)
from pilot.registry import BINDING_KEYS, AdoptionBlocked
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from forge.capabilityizer import (  # noqa: E402
    CANONICAL_ARTIFACT_IDENTITY_V1,
    evaluation_binding_violations,
    frozen_artifact_violations,
    frozen_checks,
)

IDENTITY_FIELDS = ("candidate_id", "candidate_version", "artifact_digest", "seal_digest")
IDENTITY_MISMATCH_CODES = {
    "candidate_id": "CANDIDATE_ID_MISMATCH",
    "candidate_version": "CANDIDATE_VERSION_MISMATCH",
    "artifact_digest": "ARTIFACT_DIGEST_MISMATCH",
    "seal_digest": "SEAL_DIGEST_MISMATCH",
}


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
    registry_root=None,
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
    if authority.get("decision_id") not in (None, authority.get("promotion_decision_id")):
        block(
            "AUTHORITY_BINDING_MISMATCH",
            f"decision_id={authority.get('decision_id')} "
            f"promotion_decision_id={authority.get('promotion_decision_id')}",
        )
    if not issuer_allowed(authority.get("issuer_id")):
        block("UNTRUSTED_ISSUER", f"issuer={authority.get('issuer_id')}")
    if registry_root is not None and authority.get("authority_id"):
        try:
            events = load_authority_events(
                registry_root, authority["authority_id"])
        except (OSError, json.JSONDecodeError):
            block("AUTHORITY_BINDING_MISMATCH", "authority event log unreadable")
            events = []
        if any(e.get("status") in REVOCABLE_STATUSES for e in events):
            block("REVOKED_DECISION", f"authority={authority.get('authority_id')}")
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

    if authority.get("status") in ("REVOKED", "SUPERSEDED"):
        block("REVOKED_DECISION", f"decision={decision.get('decision_id')}")
    for v in revocation_violations(
        store,
        authority.get("candidate_id"),
        authority.get("candidate_version"),
        decision.get("decision_id"),
    ):
        block(v["code"], v["message"])

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


def identity_violations(expected: dict, actual: dict) -> list[dict]:
    """Unified four-field identity comparison. No partial match: a missing
    expected/actual component or any mismatch is a violation."""
    violations: list[dict] = []
    for field in IDENTITY_FIELDS:
        exp = expected.get(field)
        act = actual.get(field)
        if exp in (None, ""):
            violations.append({"code": "MISSING_IDENTITY",
                               "message": f"expected.{field} missing"})
        elif act in (None, ""):
            violations.append({"code": "MISSING_IDENTITY",
                               "message": f"actual.{field} missing"})
        elif exp != act:
            violations.append({
                "code": IDENTITY_MISMATCH_CODES[field],
                "message": f"{field}={exp!r} actual={act!r}",
            })
    return violations


def adopt(registry_root, entry: dict, artifact_dir, *, frozen_root=None) -> dict:
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
    anchor_violations = integrity_anchor_violations(store, registry_root)
    if anchor_violations:
        raise AdoptionBlocked(anchor_violations)
    adoption = entry.get("adoption") or {}
    if frozen_root is None:
        frozen_root = entry.get("frozen_root")
    store_authority = _authority(store, adoption.get("promotion_decision_id"))
    file_authority = None
    aid = None
    if (
        adoption.get("candidate_id")
        and adoption.get("candidate_version")
        and adoption.get("promotion_decision_id")
    ):
        aid = authority_id_for(
            adoption["candidate_id"],
            adoption["candidate_version"],
            adoption["promotion_decision_id"],
        )
        try:
            file_authority = load_authority_record(registry_root, aid)
        except (OSError, json.JSONDecodeError):
            file_authority = {}
    if file_authority == {}:
        raise AdoptionBlocked(
            [{"code": "AUTHORITY_BINDING_MISMATCH",
              "message": "immutable authority record unreadable"}])
    # Explicit store_metadata marker (not directory existence): hardened mode
    # never downgrades to legacy when the ledger directory is deleted.
    if store_integrity_mode(store) == HARDENED_MODE:
        if not (registry_root / "authorities").is_dir():
            raise AdoptionBlocked(
                [{"code": "INTEGRITY_STORE_CORRUPTED",
                  "message": "hardened store missing authorities/ ledger directory"}])
        if file_authority is None:
            raise AdoptionBlocked(
                [{"code": "UNISSUED_AUTHORITY",
                  "message": f"no immutable ledger record for authority {aid}"}])
    if file_authority is not None and store_authority is not None \
            and file_authority != store_authority:
        raise AdoptionBlocked(
            [{"code": "AUTHORITY_BINDING_MISMATCH",
              "message": "immutable authority record differs from store record"}])
    authority = file_authority if file_authority is not None else store_authority
    artifact = Path(artifact_dir)
    is_canonical = (
        authority is not None
        and authority.get("artifact_identity") == CANONICAL_ARTIFACT_IDENTITY_V1
    )
    entry_identity = entry.get("artifact_identity")
    if authority is not None and is_canonical:
        if entry_identity != CANONICAL_ARTIFACT_IDENTITY_V1:
            raise AdoptionBlocked(
                [{"code": "ARTIFACT_IDENTITY_MISMATCH",
                  "message": "canonical authority requires canonical registry entry"}])
        if frozen_root is None:
            raise AdoptionBlocked(
                [{"code": "MISSING_FROZEN_CANDIDATE",
                  "message": "canonical registry entry requires frozen_root"}])
    elif authority is not None and (
        entry_identity == CANONICAL_ARTIFACT_IDENTITY_V1 or frozen_root is not None
    ):
        raise AdoptionBlocked(
            [{"code": "ARTIFACT_IDENTITY_MISMATCH",
              "message": "registry entry claims canonical but authority is legacy"}])
    if is_canonical:
        # New Frozen Candidate path (explicit marker; no legacy fallback):
        # frozen record -> evaluation binding -> canonical digest + exact
        # layout, all before the existing runtime guard.
        frozen = frozen_checks(frozen_root, adoption.get("candidate_id"))
        if not frozen["ok"]:
            raise AdoptionBlocked(frozen["violations"])
        if authority.get("seal_digest") != frozen["record"]["seal_digest"]:
            raise AdoptionBlocked(
                [{"code": "CANONICAL_IDENTITY_MISMATCH",
                  "message": "authority seal_digest differs from frozen candidate"}])
        eval_violations = evaluation_binding_violations(
            entry.get("evaluation") or {}, frozen["record"])
        if eval_violations:
            raise AdoptionBlocked(eval_violations)
        art_violations = frozen_artifact_violations(
            frozen["record"], frozen["candidate"], artifact)
        if art_violations:
            raise AdoptionBlocked(art_violations)
        actual_digest = frozen["record"]["artifact_digest"]
    else:
        # Legacy Phase 8 path: historical artifacts keep legacy semantics.
        actual_digest = legacy_dir_digest(artifact) if artifact.is_dir() else None
    violations = violations_for_runtime_activation(
        entry, authority, store, actual_digest, registry_root)
    if violations:
        raise AdoptionBlocked(violations)
    return {
        "schema": "runtime_adoption_guard_v1",
        "verdict": "ALLOW",
        "allowed": True,
        "authority_id": authority.get("authority_id"),
        "candidate_id": authority.get("candidate_id"),
        "candidate_version": authority.get("candidate_version"),
        "artifact_digest": actual_digest,
        "seal_digest": authority.get("seal_digest"),
        "verified_artifact_dir": str(Path(artifact_dir).resolve()),
    }


def verify_at_mount(registry_root, entry: dict, artifact_dir,
                    expected_digest: str | None = None,
                    *, frozen_root=None, expected_identity: dict | None = None,
                    mount_source=None) -> dict:
    """Fresh adopt() recheck immediately before docker_launch mounts.

    R8 contract: the only legal mount source is the artifact_dir verified
    here (report["verified_artifact_dir"]). Callers must pass the exact
    path they will mount and must not re-resolve/replace it between this
    call and the bind mount. verify -> kernel bind-mount OS race = UNKNOWN.
    """
    report = adopt(registry_root, entry, artifact_dir, frozen_root=frozen_root)
    if expected_identity is not None:
        violations = identity_violations(expected_identity, report)
        if violations:
            raise AdoptionBlocked(violations)
    if expected_digest is not None and report["artifact_digest"] != expected_digest:
        raise AdoptionBlocked(
            [{"code": "ARTIFACT_DIGEST_MISMATCH",
              "message": "artifact changed between activation check and mount"}])
    if mount_source is not None and \
            str(Path(mount_source).resolve()) != report["verified_artifact_dir"]:
        raise AdoptionBlocked(
            [{"code": "RUNTIME_BINDING_MISMATCH",
              "message": "mount_source differs from verified artifact_dir"}])
    return report


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
    anchor_violations = integrity_anchor_violations(store, registry_root)
    if anchor_violations:
        raise AdoptionBlocked(anchor_violations)
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
    anchor_code = write_trust_anchor(registry_root, store)
    if anchor_code:
        raise AdoptionBlocked(
            [{"code": anchor_code, "message": "trust anchor update failed"}]
        )


__all__ = [
    "AdoptionBlocked",
    "adopt",
    "identity_violations",
    "mark_promoted",
    "verify_at_mount",
    "violations_for_runtime_activation",
]
