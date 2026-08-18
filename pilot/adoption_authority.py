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
import os
import uuid
from datetime import datetime, timezone
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
REVOCABLE_STATUSES = ("REVOKED", "SUPERSEDED")
STORE_FILENAME = "adoption_store.json"
AUTHORITY_DIR_NAME = "authorities"
STORE_METADATA_KEY = "store_metadata"
HARDENED_MODE = "hardened"
LEGACY_MODE = "legacy"
HARDENED_SCHEMA_VERSION = "adoption_store_v2"
DEFAULT_ISSUER_ID = "pilot-rehearsal"
TRUSTED_ISSUERS_ENV = "PILOT_TRUSTED_ISSUERS"


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


def store_integrity_mode(store: dict) -> str:
    """Explicit hardened marker; authorities/ directory existence is NOT the marker."""
    metadata = store.get(STORE_METADATA_KEY) or {}
    return HARDENED_MODE if metadata.get("integrity_mode") == HARDENED_MODE else LEGACY_MODE


def mark_store_hardened(store: dict) -> None:
    """Persisted once when a store is initialized/upgraded with the authority ledger."""
    store.setdefault(STORE_METADATA_KEY, {})
    store[STORE_METADATA_KEY]["schema_version"] = HARDENED_SCHEMA_VERSION
    store[STORE_METADATA_KEY]["integrity_mode"] = HARDENED_MODE


def trusted_issuers() -> frozenset[str]:
    raw = os.environ.get(TRUSTED_ISSUERS_ENV, "")
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def issuer_allowed(issuer_id: str | None) -> bool:
    """Unset allowlist = legacy deterministic-binding mode (issuer UNKNOWN);
    set allowlist = strict app-layer trust boundary."""
    trusted = trusted_issuers()
    return not trusted or issuer_id in trusted


def authority_record_path(registry_root, authority_id: str) -> Path:
    return Path(registry_root) / AUTHORITY_DIR_NAME / f"{authority_id}.json"


def authority_events_path(registry_root, authority_id: str) -> Path:
    return Path(registry_root) / AUTHORITY_DIR_NAME / f"{authority_id}.events.jsonl"


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_authority_record(registry_root, authority: dict) -> str | None:
    """Write-once immutable authority ledger record (create-if-absent).

    Returns None on success/idempotent repeat, or a conflict code when an
    existing record differs. Never overwrites an existing record.
    """
    path = authority_record_path(registry_root, authority["authority_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return "AUTHORITY_BINDING_MISMATCH"
        return None if existing == authority else "AUTHORITY_BINDING_MISMATCH"
    tmp = path.with_name(f".{authority['authority_id']}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (json.dumps(authority, indent=2) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, path)  # atomic create-if-absent CAS
    except FileExistsError:
        try:
            existing = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return "AUTHORITY_BINDING_MISMATCH"
        return None if existing == authority else "AUTHORITY_BINDING_MISMATCH"
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_directory(path.parent)
    return None


def load_authority_record(registry_root, authority_id: str) -> dict | None:
    path = authority_record_path(registry_root, authority_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_authority_events(registry_root, authority_id: str) -> list[dict]:
    path = authority_events_path(registry_root, authority_id)
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def append_authority_event(registry_root, event: dict) -> None:
    path = authority_events_path(registry_root, event["authority_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    try:
        line = json.dumps(
            event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ) + "\n"
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def revoke_authority(
    registry_root,
    authority_id: str,
    *,
    status: str,
    issuer_id: str,
    reason: str = "",
) -> dict:
    """Append-only REVOKED / SUPERSEDED transition; never rewrites the record."""
    try:
        record = load_authority_record(registry_root, authority_id)
    except (OSError, json.JSONDecodeError):
        return {"verdict": "ADOPTION_BLOCKED", "allowed": False,
                "code": "AUTHORITY_BINDING_MISMATCH",
                "message": "authority record unreadable"}
    if record is None:
        return {"verdict": "ADOPTION_BLOCKED", "allowed": False,
                "code": "MISSING_AUTHORITY", "message": f"authority={authority_id}"}
    if status not in REVOCABLE_STATUSES:
        return {"verdict": "ADOPTION_BLOCKED", "allowed": False,
                "code": "INVALID_AUTHORITY_STATUS",
                "message": f"status={status} expected=REVOKED|SUPERSEDED"}
    if not issuer_allowed(issuer_id):
        return {"verdict": "ADOPTION_BLOCKED", "allowed": False,
                "code": "UNTRUSTED_ISSUER", "message": f"issuer={issuer_id}"}
    event = {
        "event": "authority_" + status.lower(),
        "revocation_id": "rev-" + uuid.uuid4().hex[:12],
        "authority_id": authority_id,
        "candidate_id": record["candidate_id"],
        "candidate_version": record["candidate_version"],
        # canonical decision binding; validation matches on decision_id only
        "decision_id": record["decision_id"],
        # legacy mirror, same value; kept only for old readers
        "promotion_decision_id": record["promotion_decision_id"],
        "status": status,
        "issuer_id": issuer_id,
        "reason": reason,
        "revoked_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    append_authority_event(registry_root, event)
    # Best-effort sync into the legacy flat store; the event file is durable.
    store = load_store(registry_root)
    if store is not None:
        revocations = store.setdefault("revocations", [])
        # explicit normalization layer: legacy copies written before
        # decision_id existed carry only promotion_decision_id
        for old in revocations:
            if not old.get("decision_id") and old.get("promotion_decision_id"):
                old["decision_id"] = old["promotion_decision_id"]
        revocations.append(event)
        path = Path(registry_root) / STORE_FILENAME
        tmp = path.with_name(f".adoption_store.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(store, indent=2) + "\n")
        os.replace(tmp, path)
    return {"verdict": "REVOKED", "allowed": True,
            "revocation_id": event["revocation_id"], "event": event}


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


def normalize_revocation_record(record) -> tuple[str | None, str | None]:
    """Read-side normalization: canonical decision_id, or a fail-closed error code."""
    if not isinstance(record, dict):
        return None, "INVALID_REVOCATION_RECORD"
    decision_id = record.get("decision_id")
    promotion_id = record.get("promotion_decision_id")
    if decision_id is not None and promotion_id is not None and decision_id != promotion_id:
        return None, "REVOCATION_RECORD_CONFLICT"
    if decision_id is None and promotion_id is None:
        return None, "INVALID_REVOCATION_RECORD"
    return (decision_id if decision_id is not None else promotion_id), None


def revocation_violations(store: dict, cand_id: str | None, cand_ver: str | None,
                          decision_id: str | None) -> list[dict]:
    """Normalize every store revocation record; malformed/conflicting records block."""
    violations: list[dict] = []
    for record in store.get("revocations", []) or []:
        canonical, err = normalize_revocation_record(record)
        if err is not None:
            rid = record.get("revocation_id") if isinstance(record, dict) else None
            violations.append({"code": err, "message": f"revocation={rid}"})
            continue
        if (
            record.get("candidate_id") == cand_id
            and record.get("candidate_version") == cand_ver
            and canonical == decision_id
        ):
            violations.append({"code": "REVOKED_DECISION",
                               "message": f"decision={decision_id}"})
    return violations


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
    registry_root=None,
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
    if authority.get("decision_id") not in (None, authority.get("promotion_decision_id")):
        block(
            "AUTHORITY_BINDING_MISMATCH",
            f"decision_id={authority.get('decision_id')} "
            f"promotion_decision_id={authority.get('promotion_decision_id')}",
        )
    if not issuer_allowed(authority.get("issuer_id")):
        block("UNTRUSTED_ISSUER", f"issuer={authority.get('issuer_id')}")
    if registry_root is not None and store_integrity_mode(store) == HARDENED_MODE \
            and not (Path(registry_root) / AUTHORITY_DIR_NAME).is_dir():
        block("INTEGRITY_STORE_CORRUPTED",
              "hardened store missing authorities/ ledger directory")
    if registry_root is not None and authority.get("authority_id"):
        try:
            record = load_authority_record(
                registry_root, authority["authority_id"])
            events = load_authority_events(
                registry_root, authority["authority_id"])
        except (OSError, json.JSONDecodeError):
            block("AUTHORITY_BINDING_MISMATCH", "authority ledger unreadable")
            record = events = None
        if record is not None and record != authority:
            block(
                "AUTHORITY_BINDING_MISMATCH",
                "immutable authority record differs from presented authority",
            )
        if events:
            revoked = any(e.get("status") in REVOCABLE_STATUSES for e in events)
            if revoked:
                block("REVOKED_DECISION", f"authority={authority.get('authority_id')}")
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

    for v in revocation_violations(store, cand_id, cand_ver,
                                   decision.get("decision_id")):
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
    registry_root=None,
) -> dict:
    violations = violations_for_authority(
        authority, store, actual_artifact_digest, registry_root)
    return {
        "schema": "adoption_authority_v1",
        "allowed": not violations,
        "verdict": "ALLOW" if not violations else "ADOPTION_BLOCKED",
        "violations": violations,
    }
