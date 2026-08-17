"""Phase 8 - minimal production AdoptionAuthority contract adapter.

Same fail-closed binding semantics as the Phase 7.6 offline validator
(docs/archaeology/unified-runtime/phase7.6/validate_adoption_authority.py),
kept self-contained so production runtime never imports docs/archaeology.

Store: one flat JSON file (adoption_store.json) beside the registry entries:
policies / candidates / runs / decisions / lifecycle / provenance / evidence.
Missing store or any missing/mismatched binding -> ADOPTION_BLOCKED.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

AUTHORITY_FIELDS = (
    "candidate_id",
    "candidate_version",
    "promotion_decision_id",
    "evaluation_run_id",
    "policy_version",
    "artifact_digest",
    "provenance",
)
PROVENANCE_KEYS = ("policy", "evidence_manifest", "run_ids", "immutable_artifact_refs")
NON_PROMOTE_VALUES = {"HOLD", "REJECTED", "REJECT", "CANARY", "PENDING"}
STORE_FILENAME = "adoption_store.json"


def authority_id_for(candidate_id: str | None, candidate_version: str | None,
                     decision_id: str | None) -> str:
    """Deterministic content-bound authority id (no cryptographic issuer)."""
    raw = f"{candidate_id}|{candidate_version}|{decision_id}"
    return "auth-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def dir_digest(directory: Path) -> str:
    """sha256 over sorted relative paths + file bytes (same shape as harness)."""
    files = {
        p.relative_to(directory).as_posix(): "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    canonical = json.dumps(
        files, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def load_store(registry_root: Path) -> dict | None:
    path = Path(registry_root) / STORE_FILENAME
    return json.loads(path.read_text()) if path.exists() else None


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


def _missing_provenance(prov, run_id: str | None) -> list[str]:
    if not isinstance(prov, dict):
        return ["provenance"]
    missing = [k for k in PROVENANCE_KEYS if not prov.get(k)]
    if run_id is not None and run_id not in (prov.get("run_ids") or []):
        missing.append(f"run_ids:{run_id}")
    return missing


def violations_for_authority(
    authority: dict,
    store: dict,
    actual_artifact_digest: str | None = None,
) -> list[dict]:
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    missing = [f for f in AUTHORITY_FIELDS if authority.get(f) in (None, "", {})]
    if missing:
        block("REQUEST_METADATA_MISSING", f"missing={','.join(missing)}")

    cand_id = authority.get("candidate_id")
    cand_ver = authority.get("candidate_version")
    if authority.get("authority_id") != authority_id_for(
        cand_id, cand_ver, authority.get("promotion_decision_id")
    ):
        block(
            "AUTHORITY_ID_MISMATCH",
            "authority_id is not the deterministic producer id for this binding",
        )
    decision = _decision(store, authority.get("promotion_decision_id"))
    if decision is None:
        block("MISSING_DECISION", f"decision={authority.get('promotion_decision_id')}")
        return violations

    run = _run(store, decision.get("run_id"))
    policy = _policy(store, decision.get("policy_ref"))
    candidate = (store.get("candidates", {}) or {}).get(cand_id, {})
    lifecycle = _lifecycle(store, cand_id)

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
        block("MISSING_LIFECYCLE", f"candidate={cand_id}")
    elif lifecycle.get("status") == "REJECTED":
        block("CANDIDATE_REJECTED", f"candidate={cand_id}")
    elif lifecycle.get("status") != "PROMOTABLE":
        block(
            "INVALID_LIFECYCLE",
            f"candidate={cand_id} expected=PROMOTABLE actual={lifecycle.get('status')}",
        )
    elif not any(
        t.get("from") == "PROMOTABLE" and t.get("to") == "PROMOTED"
        for t in (lifecycle.get("transitions", []) or [])
    ):
        block("INVALID_LIFECYCLE", f"candidate={cand_id} missing=PROMOTABLE->PROMOTED")

    if "revocations" in store:
        revoked = any(
            r.get("candidate_id") == cand_id
            and r.get("candidate_version") == cand_ver
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
        and d.get("candidate_id") == cand_id
        and d.get("candidate_version") == cand_ver
        and d.get("value") == "PROMOTE"
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        for d in (store.get("decisions", []) or [])
    )
    later_non_promote = any(
        d.get("decision_id") != decision.get("decision_id")
        and d.get("candidate_id") == cand_id
        and d.get("candidate_version") == cand_ver
        and str(d.get("created_at", "")) > str(decision.get("created_at", ""))
        and d.get("value") in NON_PROMOTE_VALUES
        for d in (store.get("decisions", []) or [])
    )
    if stale or later_promote or later_non_promote:
        block("STALE_DECISION", f"decision={decision.get('decision_id')}")
    return violations


def validate(
    authority: dict,
    store: dict,
    actual_artifact_digest: str | None = None,
) -> dict:
    violations = violations_for_authority(authority, store, actual_artifact_digest)
    return {
        "schema": "adoption_authority_v1",
        "allowed": not violations,
        "verdict": "ALLOW" if not violations else "ADOPTION_BLOCKED",
        "violations": violations,
    }
