"""M10 - experimental registry. EXPERIMENT_ONLY: flat two-state dir, no SQLite,
no multi-version, no revoke. P4/P5 implement the production registry later.
Phase 8: promote() fail-closes on AdoptionAuthority (pilot/adoption_authority.py).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pilot.adoption_authority import (
    HARDENED_MODE,
    authority_id_for,
    dir_digest as legacy_dir_digest,
    integrity_anchor_violations,
    load_authority_record,
    load_store,
    store_integrity_mode,
    validate,
)
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from forge.capabilityizer import (  # noqa: E402
    CANONICAL_ARTIFACT_IDENTITY_V1,
    evaluation_binding_violations,
    frozen_checks,
    live_candidate_violations,
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
            registry_root: Path, *, adoption_authority: dict | None = None,
            frozen_root=None) -> dict:
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
    anchor_violations = integrity_anchor_violations(store, registry_root)
    if anchor_violations:
        raise AdoptionBlocked(anchor_violations)

    cand = Path(candidate_dir)
    artifact = cand / "implementation" / "artifact"
    canonical_identity = adoption_authority.get("artifact_identity")
    if canonical_identity == CANONICAL_ARTIFACT_IDENTITY_V1:
        if frozen_root is None:
            raise AdoptionBlocked(
                [{"code": "CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT",
                  "message": "canonical authority requires frozen_root at promote"}])
        if not adoption_authority.get("seal_digest"):
            raise AdoptionBlocked(
                [{"code": "CANONICAL_IDENTITY_MISSING",
                  "message": "canonical authority missing seal_digest"}])
    elif frozen_root is not None:
        raise AdoptionBlocked(
            [{"code": "ARTIFACT_IDENTITY_MISMATCH",
              "message": "frozen_root supplied for legacy authority"}])
    elif frozen_root is None:
        try:
            cand_meta = json.loads((cand / "candidate.json").read_text())
        except (OSError, json.JSONDecodeError):
            cand_meta = {}
        if cand_meta.get("source_bundle_ids"):
            raise AdoptionBlocked(
                [{"code": "CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT",
                  "message": "new capabilityize candidate requires frozen_root at promote"}])
    artifact_identity = canonical_identity
    if frozen_root is not None:
        # New Frozen Candidate path: verify frozen + evaluation binding +
        # live exact layout before any store/registry write.
        frozen = frozen_checks(frozen_root, adoption_authority.get("candidate_id"))
        if not frozen["ok"]:
            raise AdoptionBlocked(frozen["violations"])
        if adoption_authority.get("seal_digest") != frozen["record"]["seal_digest"]:
            raise AdoptionBlocked(
                [{"code": "CANONICAL_IDENTITY_MISMATCH",
                  "message": "authority seal_digest differs from frozen candidate"}])
        violations = evaluation_binding_violations(evaluation, frozen["record"])
        violations += live_candidate_violations(
            frozen["record"], frozen["candidate"], cand)
        if violations:
            raise AdoptionBlocked(violations)
        actual_digest = frozen["record"]["artifact_digest"]
        frozen_root = str(Path(frozen_root))
    else:
        # Legacy Phase 8 path: historical artifacts keep legacy semantics.
        actual_digest = legacy_dir_digest(artifact) if artifact.is_dir() else None
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
        "artifact_identity": artifact_identity,
        "frozen_root": frozen_root if artifact_identity else None,
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
