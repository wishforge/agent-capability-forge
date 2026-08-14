"""M10 - experimental registry. EXPERIMENT_ONLY: flat two-state dir, no SQLite,
no multi-version, no revoke. P4/P5 implement the production registry later."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def promote(family: str, name: str, candidate_dir: Path, evaluation: dict,
            registry_root: Path) -> dict:
    registry_root = Path(registry_root)
    entry_path = registry_root / family / f"{name}.json"
    if entry_path.exists():
        raise FileExistsError(f"duplicate capability name: {name}")
    cand = Path(candidate_dir)
    manifest = json.loads((cand / "manifest.json").read_text())
    artifact_dst = registry_root / family / name / "artifact"
    shutil.copytree(cand / "implementation" / "artifact", artifact_dst)
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
    }
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")
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
