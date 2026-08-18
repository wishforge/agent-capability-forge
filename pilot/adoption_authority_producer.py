"""Phase 8.1 - AdoptionAuthority producer: decision -> persistent authority.

The pilot's promotion decision is derived from evaluation PASS + operator
confirm (the only real PromotionDecision source in this repo is offline
archaeology code with no persistence). The producer persists the full
adoption_store records, issues a deterministic AdoptionAuthority, and reuses
pilot.adoption_authority.validate() so Registry enforcement and issuance use
the same fail-closed contract. No store write happens unless issuance is ALLOW.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pilot.adoption_authority import (
    DEFAULT_ISSUER_ID,
    TRUSTED_ISSUERS_ENV,
    authority_id_for,
    dir_digest,
    issuer_allowed,
    load_store,
    mark_store_hardened,
    validate,
    write_authority_record,
)

DEFAULT_POLICY_REF = "pilot-promotion-rule-v1"
DEFAULT_POLICY = {
    "version": "1",
    "registered": True,
    "frozen": True,
    "content_ref": "src/forge/evaluator.py:PROMOTION_RULE",
}


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _decision_id(candidate_id: str, candidate_version: str, run_id: str) -> str:
    return "dec-" + hashlib.sha256(
        f"{candidate_id}|{candidate_version}|{run_id}".encode("utf-8")
    ).hexdigest()[:12]


def _blocked(violations: list[dict]) -> dict:
    return {"verdict": "AUTHORITY_ISSUANCE_BLOCKED", "violations": violations, "authority": None}


def _merge_keyed(mapping: dict, key: str, record: dict) -> str | None:
    """Return a conflict code, or None when the record may be written."""
    existing = mapping.get(key)
    if existing is not None and existing != record:
        return "AUTHORITY_BINDING_MISMATCH"
    mapping[key] = record
    return None


def _merge_record(records: list, record: dict, key_field: str) -> str | None:
    key = record.get(key_field)
    existing = next((r for r in records if r.get(key_field) == key), None)
    if existing is not None and existing != record:
        return "AUTHORITY_BINDING_MISMATCH"
    if existing is None:
        records.append(record)
    return None


def issue_authority(
    registry_root,
    candidate_dir,
    evaluation,
    *,
    confirm=None,
    policy=None,
    decision=None,
    run=None,
    provenance=None,
    evidence=None,
    lifecycle=None,
    issuer_id=None,
    issuer_type="operator",
) -> dict:
    """Persist decision records and issue one deterministic AdoptionAuthority.

    Returns AUTHORITY_ISSUED + authority, or AUTHORITY_ISSUANCE_BLOCKED with
    violations. Blocked issuance never writes the store.
    """
    registry_root = Path(registry_root)
    cand = Path(candidate_dir)

    if not (isinstance(confirm, dict) and confirm.get("confirm") is True):
        return _blocked(
            [{"code": "HUMAN_CONFIRM_MISSING",
              "message": "operator confirm required (confirm.json confirm=true)"}]
        )
    if not isinstance(evaluation, dict) or not evaluation.get("evaluation_id"):
        return _blocked(
            [{"code": "EVALUATION_MISSING",
              "message": "evaluation.evaluation_id required"}]
        )
    issuer_id = (
        issuer_id
        or (confirm.get("issuer_id") if isinstance(confirm, dict) else None)
        or (confirm.get("operator") if isinstance(confirm, dict) else None)
        or DEFAULT_ISSUER_ID
    )
    if not issuer_allowed(issuer_id):
        return _blocked(
            [{"code": "UNTRUSTED_ISSUER",
              "message": f"issuer={issuer_id} not in {TRUSTED_ISSUERS_ENV}"}]
        )
    if decision is None and evaluation.get("verdict") != "PASS":
        return _blocked(
            [{"code": "EVALUATION_NOT_PASS",
              "message": f"verdict={evaluation.get('verdict')} cannot issue PROMOTE"}]
        )

    try:
        candidate_meta = json.loads((cand / "candidate.json").read_text())
        manifest = json.loads((cand / "manifest.json").read_text())
        candidate_id = candidate_meta["candidate_id"]
        candidate_version = f"v{manifest['capability']['version']}"
        candidate_created_at = manifest["provenance"]["forge_timestamp"]
        artifact_dir = cand / "implementation" / "artifact"
        artifact_digest = dir_digest(artifact_dir) if artifact_dir.is_dir() else None
    except Exception as exc:  # noqa: BLE001 - fail-closed on any bad candidate
        return _blocked(
            [{"code": "CANDIDATE_METADATA_MISSING", "message": str(exc)}]
        )

    run_id = evaluation["evaluation_id"]
    created_at = evaluation.get("evaluated_at") or _now()
    if policy is None:
        policy = dict(DEFAULT_POLICY)
    policy_ref = policy.get("policy_id") or DEFAULT_POLICY_REF
    policy_version = str(policy.get("version", "1"))

    if decision is None:
        decision = {
            "decision_id": _decision_id(candidate_id, candidate_version, run_id),
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "run_id": run_id,
            "policy_ref": policy_ref,
            "policy_version": policy_version,
            "artifact_digest": artifact_digest,
            "value": "PROMOTE",
            "gate_result": "PASS",
            "created_at": created_at,
        }
    if "recorded_hash" not in decision:
        content = {k: v for k, v in decision.items()
                   if k not in ("recorded_hash", "current_hash")}
        decision["recorded_hash"] = _sha256(_canonical(content))
        decision["current_hash"] = decision["recorded_hash"]

    if run is None:
        run = {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "artifact_digest": artifact_digest,
            "policy_ref": policy_ref,
            "policy_version": policy_version,
            "status": "EVALUATED",
            "created_at": created_at,
        }
    if provenance is None:
        provenance = {
            "policy": True,
            "evidence_manifest": True,
            "run_ids": [run_id],
            "immutable_artifact_refs": [f"artifact:{artifact_digest}"] if artifact_digest else [],
        }
    if evidence is None:
        h = _sha256(_canonical(evaluation))
        evidence = {
            "evidence_id": "ev-" + h[len("sha256:"):][:12],
            "run_id": run_id,
            "recorded_hash": h,
            "current_hash": h,
        }
    if lifecycle is None:
        lifecycle = {
            "status": "PROMOTABLE",
            "transitions": [{"from": "PROMOTABLE", "to": "PROMOTED"}],
        }

    store = load_store(registry_root) or {}
    store.setdefault("policies", {})
    store.setdefault("candidates", {})
    store.setdefault("runs", [])
    store.setdefault("evidence", [])
    store.setdefault("provenance", {})
    store.setdefault("decisions", [])
    store.setdefault("lifecycle", {})
    store.setdefault("revocations", [])
    store.setdefault("authorities", [])

    candidate = {
        "version": candidate_version,
        "created_at": candidate_created_at,
        "forged_artifact_digest": artifact_digest,
    }
    conflict = (
        _merge_keyed(store["policies"], policy_ref, policy)
        or _merge_keyed(store["candidates"], candidate_id, candidate)
        or _merge_record(store["runs"], run, "run_id")
        or _merge_record(store["evidence"], evidence, "evidence_id")
        or _merge_keyed(store["provenance"], candidate_id, provenance)
        or _merge_record(store["decisions"], decision, "decision_id")
        or _merge_keyed(store["lifecycle"], candidate_id, lifecycle)
    )
    if conflict:
        return _blocked(
            [{"code": conflict,
              "message": f"existing store record conflicts with issuance request"}]
        )

    authority = {
        "authority_id": authority_id_for(
            decision.get("candidate_id"),
            decision.get("candidate_version"),
            decision.get("decision_id"),
        ),
        "candidate_id": decision.get("candidate_id"),
        "candidate_version": decision.get("candidate_version"),
        "promotion_decision_id": decision.get("decision_id"),
        "evaluation_run_id": decision.get("run_id"),
        "policy_version": decision.get("policy_version"),
        "artifact_digest": decision.get("artifact_digest"),
        "provenance": provenance,
        "issued_at": decision.get("created_at"),
        "status": "ISSUED",
        "issuer_id": issuer_id,
        "issuer_type": issuer_type,
        "decision_id": decision.get("decision_id"),
    }
    report = validate(authority, store, artifact_digest, registry_root)
    if not report["allowed"]:
        return _blocked(report["violations"])

    conflict = write_authority_record(registry_root, authority)
    if conflict:
        return _blocked(
            [{"code": conflict,
              "message": "immutable authority ledger already holds a different record"}]
        )

    existing_authority = next(
        (a for a in store["authorities"] if a.get("authority_id") == authority["authority_id"]),
        None,
    )
    if existing_authority is not None and existing_authority != authority:
        return _blocked(
            [{"code": "AUTHORITY_BINDING_MISMATCH",
              "message": "existing issued authority differs from request"}]
        )
    if existing_authority is None:
        store["authorities"].append(authority)

    mark_store_hardened(store)
    path = registry_root / "adoption_store.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".adoption_store.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(store, indent=2) + "\n")
    os.replace(tmp, path)
    return {
        "verdict": "AUTHORITY_ISSUED",
        "authority": authority,
        "store_path": str(path),
    }


__all__ = ["DEFAULT_POLICY", "DEFAULT_POLICY_REF", "issue_authority"]
