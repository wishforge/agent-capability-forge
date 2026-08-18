"""M10 - experimental registry. EXPERIMENT_ONLY: flat two-state dir, no SQLite,
no multi-version, no revoke. P4/P5 implement the production registry later.
Phase 8: promote() fail-closes on AdoptionAuthority (pilot/adoption_authority.py).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pilot.adoption_authority import (
    HARDENED_MODE,
    authority_id_for,
    dir_digest,
    load_authority_record,
    load_store,
    store_integrity_mode,
    validate,
)

BINDING_KEYS = (
    "candidate_id",
    "candidate_version",
    "promotion_decision_id",
    "evaluation_run_id",
    "policy_version",
    "artifact_digest",
    "provenance",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AdoptionBlocked(Exception):
    """Fail-closed promotion refusal; registry state is never changed."""

    def __init__(self, violations: list[dict]):
        self.violations = violations
        self.report = {"verdict": "ADOPTION_BLOCKED", "violations": violations}
        super().__init__(json.dumps(self.report, ensure_ascii=False, indent=2))


def _same_binding(entry: dict, authority: dict) -> bool:
    adopted = entry.get("adoption") or {}
    return entry.get("state") == "promoted" and all(
        adopted.get(k) == authority.get(k) for k in BINDING_KEYS
    )


def promote(family: str, name: str, candidate_dir: Path, evaluation: dict,
            registry_root: Path, *, adoption_authority: dict | None = None) -> dict:
    registry_root = Path(registry_root)
    entry_path = registry_root / family / f"{name}.json"

    if adoption_authority is None:
        raise AdoptionBlocked(
            [{"code": "MISSING_AUTHORITY", "message": "promote() requires an AdoptionAuthority"}]
        )
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

    cand = Path(candidate_dir)
    artifact = cand / "implementation" / "artifact"
    actual_digest = dir_digest(artifact) if artifact.is_dir() else None
    report = validate(adoption_authority, store, actual_digest, registry_root)
    if not report["allowed"]:
        raise AdoptionBlocked(report["violations"])
    if store_integrity_mode(store) == HARDENED_MODE:
        if not (registry_root / "authorities").is_dir():
            raise AdoptionBlocked(
                [
                    {
                        "code": "INTEGRITY_STORE_CORRUPTED",
                        "message": "hardened store missing authorities/ ledger directory",
                    }
                ]
            )
        aid = authority_id_for(
            adoption_authority.get("candidate_id"),
            adoption_authority.get("candidate_version"),
            adoption_authority.get("promotion_decision_id"),
        )
        if load_authority_record(registry_root, aid) is None:
            raise AdoptionBlocked(
                [
                    {
                        "code": "UNISSUED_AUTHORITY",
                        "message": f"no immutable ledger record for authority {aid}",
                    }
                ]
            )

    if entry_path.exists():
        existing = json.loads(entry_path.read_text())
        if _same_binding(existing, adoption_authority):
            return existing  # idempotent repeat of the same valid adoption
        raise AdoptionBlocked(
            [
                {
                    "code": "ENTRY_BINDING_CONFLICT",
                    "message": f"{entry_path} exists with a different adoption binding",
                }
            ]
        )

    manifest = json.loads((cand / "manifest.json").read_text())
    artifact_dst = registry_root / family / name / "artifact"
    try:
        shutil.copytree(artifact, artifact_dst)
    except FileExistsError:
        pass  # concurrent same-name promote; exclusive entry create below decides
    entry = {
        "schema_version": "experimental_registry_v1",
        "capability_id": "cap-" + uuid.uuid4().hex[:12],
        "name": name,
        "version": 1,
        "family": family,
        "artifact_dir": str(artifact_dst),
        "manifest": manifest,
        "evaluation": evaluation,
        "state": "promoted",
        "promoted_at": _now(),
        "adoption": {
            "candidate_id": adoption_authority.get("candidate_id"),
            "candidate_version": adoption_authority.get("candidate_version"),
            "promotion_decision_id": adoption_authority.get("promotion_decision_id"),
            "evaluation_run_id": adoption_authority.get("evaluation_run_id"),
            "policy_version": adoption_authority.get("policy_version"),
            "artifact_digest": adoption_authority.get("artifact_digest"),
            "provenance": adoption_authority.get("provenance"),
            "adopted_at": _now(),
        },
    }
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = entry_path.with_name(f".{name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(entry, indent=2) + "\n")
    try:
        # ponytail: exclusive create via hard link; flat JSON has no CAS,
        # so store records read before this write can still race (UNKNOWN).
        os.link(tmp, entry_path)
    except FileExistsError:
        existing = json.loads(entry_path.read_text())
        if not _same_binding(existing, adoption_authority):
            raise AdoptionBlocked(
                [
                    {
                        "code": "ENTRY_BINDING_CONFLICT",
                        "message": f"{entry_path} exists with a different adoption binding",
                    }
                ]
            )
        return existing
    finally:
        tmp.unlink(missing_ok=True)
    return entry


def reject(family: str, name: str, candidate_dir: Path, evaluation: dict,
           registry_root: Path) -> dict:
    registry_root = Path(registry_root)
    entry_path = registry_root / family / f"{name}.json"
    if entry_path.exists():
        raise FileExistsError(f"duplicate capability name: {name}")
    entry = {
        "schema_version": "experimental_registry_v1",
        "capability_id": "cap-" + uuid.uuid4().hex[:12],
        "name": name, "version": 1, "family": family,
        "candidate_dir": str(candidate_dir),
        "evaluation": evaluation,
        "state": "rejected",
        "rejected_at": _now(),
    }
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")
    return entry


def discover(registry_root: Path, family: str, name: str) -> dict | None:
    entry_path = Path(registry_root) / family / f"{name}.json"
    if not entry_path.exists():
        return None
    entry = json.loads(entry_path.read_text())
    if entry["state"] != "promoted":
        return None
    return entry
