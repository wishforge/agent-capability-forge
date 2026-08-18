"""M8 - B3 Capabilityizer: Bundle + LLM Proposal + confirm -> Candidate.

Runtime-neutral: consumes VerifiedTaskArtifactBundle + immutable artifacts +
proposal + confirm only. Deterministic transform; static scan rejects
task-private state (original workspace paths / session refs / temp refs).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .bundle_producer import canonical_json, now_iso, sha256_bytes

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FORBIDDEN_PATTERNS = [
    "/Users/", "/private/", "/tmp/", "/home/", "/root/",
    ".codex", "sessions/", "rollout-", "data/input.csv", "data/cleaned.csv",
]


class CapabilityizeError(Exception):
    pass


# ---------------------------------------------------------------------------
# CANONICAL_ARTIFACT_IDENTITY_V1 + Candidate Seal (Phase 9-B.1)
# ---------------------------------------------------------------------------
CANONICAL_ARTIFACT_IDENTITY_V1 = "CANONICAL_ARTIFACT_IDENTITY_V1"
SEAL_SCHEMA_V1 = "frozen-candidate-v1"
SEAL_VERSION_V1 = "v1"
SEAL_SCHEMA = "frozen-candidate-v2"
SEAL_VERSION = "v2"
FROZEN_CORE_KEYS = (
    "schema_version", "candidate_id", "capability_id", "name", "version",
    "source", "producer", "requester", "artifact", "manifest", "provenance",
    "extensions",
)


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _chmod_tree(root: Path, dir_mode: int, file_mode: int) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(Path(dirpath) / name, file_mode)
        for name in dirnames:
            os.chmod(Path(dirpath) / name, dir_mode)
    os.chmod(root, dir_mode)


def _fsync_tree(root: Path) -> None:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            with p.open("rb") as fh:
                os.fsync(fh.fileno())


def canonical_artifact_digest(files: dict[str, str]) -> str:
    """sha256(canonical({rel_posix_path: sha256(file_bytes)})), sorted paths."""
    return sha256_bytes(canonical_json({p: files[p] for p in sorted(files)}))


def artifact_layout(directory: Path, allowlist) -> tuple[dict[str, str], list[str]]:
    """Exact-layout check: actual file set must equal the explicit allowlist.

    Digest uses the allowlist only; the layout check rejects any actual -
    wanted or wanted - actual file. No ignore lists, no glob fallback.
    """
    violations: list[str] = []
    if not isinstance(allowlist, list) or not allowlist:
        return {}, ["ARTIFACT_ALLOWLIST_MISSING"]
    if len(set(allowlist)) != len(allowlist):
        violations.append("ARTIFACT_ALLOWLIST_DUPLICATE")
    actual = {
        p.relative_to(directory).as_posix()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    wanted = set()
    for rel in allowlist:
        p = Path(rel)
        if not rel or p.is_absolute() or ".." in p.parts:
            violations.append(f"ARTIFACT_ALLOWLIST_PATH_INVALID:{rel}")
            continue
        wanted.add(rel)
        if not (directory / rel).is_file():
            violations.append(f"ARTIFACT_ALLOWLIST_FILE_MISSING:{rel}")
    for rel in sorted(actual - wanted):
        violations.append(f"UNDECLARED_ARTIFACT_FILE:{rel}")
    files = {
        rel: file_digest(directory / rel)
        for rel in sorted(wanted)
        if (directory / rel).is_file()
    }
    return files, violations


def frozen_artifact_report(directory: Path, allowlist) -> dict:
    files, violations = artifact_layout(directory, allowlist)
    return {"ok": not violations, "digest": canonical_artifact_digest(files),
            "violations": violations}


def artifact_digest(directory: Path, allowlist) -> str:
    """CANONICAL_ARTIFACT_IDENTITY_V1 digest: allowlist only, exact layout."""
    files, _ = artifact_layout(directory, allowlist)
    return canonical_artifact_digest(files)


def manifest_digest(manifest: dict) -> str:
    return sha256_bytes(canonical_json(manifest))


def tests_digest(tests_dir: Path) -> str:
    files = {
        p.relative_to(tests_dir).as_posix(): file_digest(p)
        for p in sorted(tests_dir.rglob("*"))
        if p.is_file()
    }
    return sha256_bytes(canonical_json(files))


def seal_digest(candidate: dict, artifact_digest_value: str,
                tests_digest_value: str, *,
                seal_version: str = SEAL_VERSION) -> str:
    """Canonical hash of frozen core + artifact/manifest/tests digests.

    v2+ includes SEAL_SCHEMA / SEAL_VERSION in the payload (DSSE PAE
    equivalent); v1 keeps the historical payload so existing records verify.
    evaluation/validation/promotion/decision/authority are deliberately
    excluded: they are append-only evidence referencing this digest.
    """
    payload = {k: candidate[k] for k in FROZEN_CORE_KEYS if k in candidate}
    payload["artifact_digest"] = artifact_digest_value
    payload["manifest_digest"] = manifest_digest(candidate.get("manifest", {}))
    payload["tests_digest"] = tests_digest_value
    if seal_version != SEAL_VERSION_V1:
        payload["seal_schema"] = SEAL_SCHEMA
        payload["seal_version"] = seal_version
    return sha256_bytes(canonical_json(payload))


def seal_violations(candidate: dict) -> list[dict]:
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    manifest = candidate.get("manifest") or {}
    cap = manifest.get("capability") or {}
    if isinstance(candidate.get("version"), int) and cap.get("version") != candidate.get("version"):
        block("VERSION_BINDING_MISMATCH",
              f"version={candidate.get('version')} manifest.capability.version={cap.get('version')}")
    if candidate.get("name") != cap.get("name"):
        block("NAME_BINDING_MISMATCH",
              f"name={candidate.get('name')!r} manifest.capability.name={cap.get('name')!r}")

    art = candidate.get("artifact") or {}
    if not isinstance(candidate.get("candidate_id"), str) or not candidate.get("candidate_id"):
        block("CANDIDATE_ID_MISSING", "candidate_id is required")
    digest = art.get("artifact_digest")
    ref = art.get("artifact_ref")
    if ref is not None and ref != f"artifact:{digest}":
        block("ARTIFACT_REF_BINDING_MISMATCH",
              f"artifact_ref={ref!r} artifact_digest={digest!r}")
    if not isinstance(art.get("files"), list) or not art.get("files"):
        block("ARTIFACT_ALLOWLIST_MISSING",
              "artifact.files (explicit allowlist) is required and must be non-empty")

    forged = (manifest.get("provenance") or {}).get("forged_artifact_digest")
    if not isinstance(forged, str):
        block("MANIFEST_FORGED_DIGEST_MISSING",
              "manifest.provenance.forged_artifact_digest is required")
    elif forged != digest:
        block("ARTIFACT_DIGEST_SEMANTICS_CONFLICT",
              "manifest.provenance.forged_artifact_digest must equal artifact.artifact_digest")

    requester = candidate.get("requester")
    prov = candidate.get("provenance") or {}
    req_id = (requester or {}).get("request_id") if isinstance(requester, dict) else None
    if req_id is not None and prov.get("request_id") not in (None, req_id):
        block("REQUEST_ID_BINDING_MISMATCH",
              f"requester.request_id={req_id!r} provenance.request_id={prov.get('request_id')!r}")

    src = candidate.get("source") or {}
    source_artifact = (manifest.get("provenance") or {}).get("source_artifact_digest")
    if source_artifact is not None and src.get("resolved_revision") != source_artifact:
        block("SOURCE_REVISION_BINDING_MISMATCH",
              "manifest.provenance.source_artifact_digest must equal source.resolved_revision")

    cid = candidate.get("capability_id")
    if not (isinstance(cid, str) and cid.startswith("cap-")):
        block("CAPABILITY_ID_FORMAT", f"capability_id must start with 'cap-': {cid!r}")
    return violations


def capability_id_derivation(namespace: str, name: str) -> str:
    """Deterministic, replayable intake-level capability id."""
    return "cap-" + sha256_bytes(
        canonical_json({"namespace": namespace, "name": name}))[len("sha256:"):][:16]


def _record_identity(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "sealed_at"}


def _conflict_result(existing: dict, record: dict, snap_dir: Path) -> dict:
    if not snap_dir.is_dir():
        return {"ok": False, "verdict": "FROZEN_CANDIDATE_INCOMPLETE", "record": None,
                "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                "message": f"frozen record exists but snapshot missing: {snap_dir}"}]}
    if _record_identity(existing) == _record_identity(record):
        return {"ok": True, "verdict": "ALLOW", "record": existing, "violations": []}
    return {"ok": False, "verdict": "FROZEN_CANDIDATE_CONFLICT", "record": None,
            "violations": [{"code": "FROZEN_CANDIDATE_CONFLICT",
                            "message": f"candidate_id={record.get('candidate_id')} "
                                       "already sealed with different content"}]}


def freeze_candidate(candidate: dict, artifact_dir: Path, tests_dir: Path,
                     store_root=None, *, sealed_at: str | None = None,
                     referenced_ids=()) -> dict:
    """Seal point: write-once Frozen Candidate (identity + manifest + tests
    + artifact snapshot). Existing identical record -> ALLOW; different
    content -> FROZEN_CANDIDATE_CONFLICT. Missing metadata for an identity
    already referenced by evidence/authority/registry -> BLOCK (re-seal is
    never allowed). store_root=None computes only.
    """
    violations = seal_violations(candidate)
    art = frozen_artifact_report(Path(artifact_dir), candidate.get("artifact", {}).get("files"))
    if not art["ok"]:
        for v in art["violations"]:
            violations.append({"code": v.split(":")[0], "message": v})
    if art["digest"] != candidate.get("artifact", {}).get("artifact_digest"):
        violations.append({"code": "ARTIFACT_DIGEST_MISMATCH",
                           "message": f"bytes={art['digest']} "
                                      f"candidate={candidate.get('artifact', {}).get('artifact_digest')}"})
    td_path = Path(tests_dir)
    if not td_path.is_dir():
        violations.append({"code": "TESTS_DIR_MISSING",
                           "message": f"tests directory missing: {td_path}"})
    td = tests_digest(td_path)
    record = {
        "schema": SEAL_SCHEMA,
        "seal_version": SEAL_VERSION,
        "candidate_id": candidate.get("candidate_id"),
        "capability_id": candidate.get("capability_id"),
        "name": candidate.get("name"),
        "version": candidate.get("version"),
        "artifact_digest": art["digest"],
        "manifest_digest": manifest_digest(candidate.get("manifest", {})),
        "tests_digest": td,
        "seal_digest": seal_digest(candidate, art["digest"], td),
        "sealed_at": sealed_at or now_iso(),
    }
    if violations:
        return {"ok": False, "verdict": "BLOCK", "record": None,
                "violations": violations}
    if store_root is None:
        return {"ok": True, "verdict": "COMPUTED", "record": record,
                "violations": []}

    store_root = Path(store_root)
    frozen_dir = store_root / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = candidate.get("candidate_id")
    record_path = frozen_dir / f"{candidate_id}.json"
    snap_dir = frozen_dir / candidate_id
    if record_path.exists():
        existing = json.loads(record_path.read_text())
        return _conflict_result(existing, record, snap_dir)
    if snap_dir.is_dir():
        return {"ok": False, "verdict": "NEW_CANDIDATE_REQUIRED", "record": None,
                "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                "message": f"frozen snapshot exists but record missing: "
                                           f"{record_path}"}]}
    if candidate_id in referenced_ids:
        return {"ok": False, "verdict": "NEW_CANDIDATE_REQUIRED", "record": None,
                "violations": [{"code": "FROZEN_CANDIDATE_DELETED",
                                "message": f"candidate_id={candidate_id} is referenced by "
                                           "evaluation/decision/authority/registry but its "
                                           "frozen record is missing; re-seal is forbidden"}]}

    tmp_snap = frozen_dir / f".{candidate_id}.{uuid.uuid4().hex}.tmp"
    # Owner-writable spine only for this publish transaction; hardened back
    # to 0555 immediately after the atomic rename (no post-publish writes).
    store_root.chmod(0o755)
    frozen_dir.chmod(0o755)
    tmp_snap.mkdir(parents=True)
    try:
        (tmp_snap / "candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
        shutil.copytree(tests_dir, tmp_snap / "tests")
        shutil.copytree(artifact_dir, tmp_snap / "artifact")
        materialized = frozen_artifact_report(
            tmp_snap / "artifact", candidate.get("artifact", {}).get("files"))
        if not materialized["ok"]:
            return {"ok": False, "verdict": "BLOCK", "record": None,
                    "violations": [{"code": v.split(":")[0], "message": v}
                                   for v in materialized["violations"]]}
        if materialized["digest"] != art["digest"]:
            return {"ok": False, "verdict": "BLOCK", "record": None,
                    "violations": [{"code": "ARTIFACT_DIGEST_MISMATCH",
                                    "message": f"materialized={materialized['digest']} "
                                               f"expected={art['digest']}"}]}
        if tests_digest(tmp_snap / "tests") != td:
            return {"ok": False, "verdict": "BLOCK", "record": None,
                    "violations": [{"code": "TESTS_DIGEST_MISMATCH",
                                    "message": "materialized tests differ from record"}]}
        tmp_rec = frozen_dir / f".{candidate_id}.{uuid.uuid4().hex}.json.tmp"
        tmp_rec.write_text(json.dumps(record, indent=2) + "\n")
        try:
            os.link(tmp_rec, record_path)  # atomic create-if-absent
        except FileExistsError:
            existing = json.loads(record_path.read_text())
            return _conflict_result(existing, record, snap_dir)
        finally:
            tmp_rec.unlink(missing_ok=True)
        _fsync_tree(tmp_snap)
        _chmod_tree(tmp_snap, 0o555, 0o444)
        try:
            os.replace(tmp_snap, snap_dir)
        except OSError:
            return {"ok": False, "verdict": "FROZEN_CANDIDATE_INCOMPLETE", "record": None,
                    "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                    "message": f"snapshot could not be committed: {snap_dir}"}]}
        record_path.chmod(0o444)
        frozen_dir.chmod(0o555)
        store_root.chmod(0o555)
        return {"ok": True, "verdict": "FROZEN", "record": record, "violations": []}
    finally:
        if tmp_snap.exists():
            _chmod_tree(tmp_snap, 0o755, 0o644)
        shutil.rmtree(tmp_snap, ignore_errors=True)


def load_frozen_candidate(store_root, candidate_id: str) -> dict | None:
    path = Path(store_root) / "frozen" / f"{candidate_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def get_artifact_digest(store_root, candidate_id: str) -> str | None:
    record = load_frozen_candidate(store_root, candidate_id)
    return record.get("artifact_digest") if record else None


def get_seal_digest(store_root, candidate_id: str) -> str | None:
    record = load_frozen_candidate(store_root, candidate_id)
    return record.get("seal_digest") if record else None


def load_frozen_candidate_snapshot(store_root, candidate_id: str) -> dict | None:
    path = Path(store_root) / "frozen" / candidate_id / "candidate.json"
    return json.loads(path.read_text()) if path.exists() else None


def verify_frozen(store_root, candidate_id: str) -> dict:
    """Post-seal verification: any frozen identity/byte change is detected."""
    record_path = Path(store_root) / "frozen" / f"{candidate_id}.json"
    snap_dir = Path(store_root) / "frozen" / candidate_id
    if not record_path.exists():
        return {"ok": False, "verdict": "MISSING_FROZEN_CANDIDATE",
                "violations": [{"code": "MISSING_FROZEN_CANDIDATE",
                                "message": f"candidate_id={candidate_id}"}]}
    if not snap_dir.is_dir():
        return {"ok": False, "verdict": "NEW_CANDIDATE_REQUIRED",
                "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                "message": f"frozen snapshot missing: {snap_dir}"}]}
    try:
        record = json.loads(record_path.read_text())
        candidate = json.loads((snap_dir / "candidate.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "verdict": "NEW_CANDIDATE_REQUIRED",
                "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                "message": "frozen record/snapshot unreadable"}]}

    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    seal_version = record.get("seal_version")
    if (record.get("schema"), seal_version) not in (
        (SEAL_SCHEMA, SEAL_VERSION),
        (SEAL_SCHEMA_V1, SEAL_VERSION_V1),
    ):
        block("SEAL_SCHEMA_MISMATCH", "frozen record schema/seal_version mismatch")
    for key in ("candidate_id", "capability_id", "name", "version"):
        if record.get(key) != candidate.get(key):
            block("FROZEN_FIELD_CHANGED", f"{key} changed after seal")
    art = frozen_artifact_report(snap_dir / "artifact",
                                 candidate.get("artifact", {}).get("files"))
    if not art["ok"]:
        for v in art["violations"]:
            block(v.split(":")[0], v)
    if art["digest"] != record.get("artifact_digest"):
        block("ARTIFACT_DIGEST_MISMATCH", "artifact bytes changed after seal")
    if manifest_digest(candidate.get("manifest", {})) != record.get("manifest_digest"):
        block("MANIFEST_CHANGED_AFTER_SEAL", "manifest changed after seal")
    if not (snap_dir / "tests").is_dir():
        block("TESTS_DIR_MISSING", "frozen tests directory missing")
    elif tests_digest(snap_dir / "tests") != record.get("tests_digest"):
        block("TESTS_CHANGED_AFTER_SEAL", "tests changed after seal")
    payload_version = SEAL_VERSION_V1 if seal_version == SEAL_VERSION_V1 else SEAL_VERSION
    if seal_digest(candidate, art["digest"], tests_digest(snap_dir / "tests"),
                   seal_version=payload_version) != record.get("seal_digest"):
        block("SEAL_DIGEST_MISMATCH", "frozen core changed after seal")
    return {"ok": not violations,
            "verdict": "FROZEN_CANDIDATE_UNCHANGED" if not violations
            else "NEW_CANDIDATE_REQUIRED",
            "violations": violations}


def frozen_checks(store_root, candidate_id: str) -> dict:
    """Fail-closed load + integrity verification of a Frozen Candidate."""
    try:
        record = load_frozen_candidate(store_root, candidate_id)
        if record is None:
            return {"ok": False, "verdict": "MISSING_FROZEN_CANDIDATE",
                    "record": None, "candidate": None,
                    "violations": [{"code": "MISSING_FROZEN_CANDIDATE",
                                    "message": f"candidate_id={candidate_id}"}]}
        verify = verify_frozen(store_root, candidate_id)
        if not verify["ok"]:
            return {"ok": False, "verdict": verify["verdict"],
                    "record": record, "candidate": None,
                    "violations": verify["violations"]}
        candidate = load_frozen_candidate_snapshot(store_root, candidate_id)
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "verdict": "NEW_CANDIDATE_REQUIRED",
                "record": None, "candidate": None,
                "violations": [{"code": "FROZEN_CANDIDATE_INCOMPLETE",
                                "message": f"frozen record/snapshot unreadable: "
                                           f"candidate_id={candidate_id}"}]}
    return {"ok": True, "verdict": "FROZEN_CANDIDATE_UNCHANGED",
            "record": record, "candidate": candidate, "violations": []}


def evaluation_binding_violations(evaluation: dict, frozen_record: dict) -> list[dict]:
    """Single binding semantics: evaluation must reference exactly the
    frozen candidate_id / artifact_digest / seal_digest."""
    violations = []
    for field in ("candidate_id", "artifact_digest", "seal_digest"):
        actual = evaluation.get(field)
        expected = frozen_record.get(field)
        if actual != expected:
            violations.append({
                "code": "EVALUATION_BINDING_MISMATCH",
                "message": f"evaluation.{field}={actual!r} "
                           f"frozen.{field}={expected!r}",
            })
    return violations


def frozen_artifact_violations(frozen_record: dict, frozen_candidate: dict,
                               artifact_dir) -> list[dict]:
    """Exact layout + canonical digest of a live artifact against the frozen
    allowlist. This is the check used right before runtime bind-mount."""
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    allowlist = (frozen_candidate.get("artifact") or {}).get("files")
    report = frozen_artifact_report(Path(artifact_dir), allowlist)
    if not report["ok"]:
        for v in report["violations"]:
            block(v.split(":")[0], v)
    if report["digest"] != frozen_record.get("artifact_digest"):
        block("ARTIFACT_DIGEST_MISMATCH",
              f"live={report['digest']} frozen={frozen_record.get('artifact_digest')}")
    return violations


def live_candidate_violations(frozen_record: dict, frozen_candidate: dict,
                              live_candidate_dir) -> list[dict]:
    """Live candidate dir must still match the frozen candidate: identity
    metadata, manifest, tests and the exact artifact layout/digest."""
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    live = Path(live_candidate_dir)
    try:
        meta = json.loads((live / "candidate.json").read_text())
    except (OSError, json.JSONDecodeError):
        meta = {}
    if meta.get("candidate_id") != frozen_record.get("candidate_id"):
        block("FROZEN_CANDIDATE_MISMATCH",
              f"live candidate_id={meta.get('candidate_id')!r} "
              f"frozen={frozen_record.get('candidate_id')!r}")
    if meta.get("name") != frozen_candidate.get("name"):
        block("FROZEN_CANDIDATE_MISMATCH",
              f"live name={meta.get('name')!r} frozen={frozen_candidate.get('name')!r}")
    try:
        manifest = json.loads((live / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if manifest != frozen_candidate.get("manifest"):
        block("FROZEN_CANDIDATE_MISMATCH", "live manifest differs from frozen candidate")
    td_path = live / "tests"
    if not td_path.is_dir():
        block("TESTS_DIR_MISSING", f"live tests directory missing: {td_path}")
    elif tests_digest(td_path) != frozen_record.get("tests_digest"):
        block("TESTS_CHANGED_AFTER_SEAL", "live tests differ from frozen candidate")
    violations += frozen_artifact_violations(
        frozen_record, frozen_candidate, live / "implementation" / "artifact")
    return violations


def bind_evaluation(evaluation: dict, candidate_id: str, artifact_digest_value: str,
                    seal_digest_value: str) -> dict:
    """Evidence adapter: evaluation records must reference candidate + bytes
    + seal, never candidate_id alone. Any conflict on the three identity
    fields is EVALUATION_BINDING_CONFLICT; never a silent overwrite."""
    conflicts = []
    existing = evaluation.get("candidate_id")
    if existing not in (None, candidate_id):
        conflicts.append(f"candidate_id={existing!r} != {candidate_id!r}")
    existing_artifact = evaluation.get("artifact_digest")
    if existing_artifact not in (None, artifact_digest_value):
        conflicts.append(
            f"artifact_digest={existing_artifact!r} != {artifact_digest_value!r}")
    existing_seal = evaluation.get("seal_digest")
    if existing_seal not in (None, seal_digest_value):
        conflicts.append(f"seal_digest={existing_seal!r} != {seal_digest_value!r}")
    if conflicts:
        raise ValueError("EVALUATION_BINDING_CONFLICT: " + "; ".join(conflicts))
    bound = dict(evaluation)
    bound["candidate_id"] = candidate_id
    bound["artifact_digest"] = artifact_digest_value
    bound["seal_digest"] = seal_digest_value
    return bound


def referenced_candidate_ids(registry_root) -> set[str]:
    """Every candidate_id referenced by Evaluation / Decision / Authority /
    Registry entries. Used to make delete -> re-seal fail closed."""
    ids: set[str] = set()
    root = Path(registry_root)
    store_path = root / "adoption_store.json"
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text())
        except (OSError, json.JSONDecodeError):
            store = {}
        if isinstance(store, dict):
            candidates = store.get("candidates")
            if isinstance(candidates, dict):
                ids.update(k for k in candidates if isinstance(k, str))
            for section in ("runs", "decisions", "authorities"):
                for rec in store.get(section, []) or []:
                    if isinstance(rec, dict) and isinstance(rec.get("candidate_id"), str):
                        ids.add(rec["candidate_id"])
            for section in ("lifecycle", "provenance"):
                mapping = store.get(section)
                if isinstance(mapping, dict):
                    ids.update(k for k in mapping if isinstance(k, str))
    for family in root.iterdir():
        if not family.is_dir():
            continue
        for entry_path in sorted(family.glob("*.json")):
            try:
                entry = json.loads(entry_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(entry, dict):
                continue
            evaluation = entry.get("evaluation")
            if isinstance(evaluation, dict) and isinstance(
                    evaluation.get("candidate_id"), str):
                ids.add(evaluation["candidate_id"])
            adoption = entry.get("adoption")
            if isinstance(adoption, dict) and isinstance(
                    adoption.get("candidate_id"), str):
                ids.add(adoption["candidate_id"])
    return ids


def freeze_candidate_dir(candidate_dir: Path, store_root,
                         *, namespace: str = "F+", sealed_at: str | None = None,
                         registry_root=None) -> dict:
    """Pilot adapter: freeze a prototype candidate directory as a v2 Frozen
    Candidate (canonical artifact identity, write-once record)."""
    cand = Path(candidate_dir)
    meta = json.loads((cand / "candidate.json").read_text())
    manifest = json.loads((cand / "manifest.json").read_text())
    artifact_dir = cand / "implementation" / "artifact"
    allowlist = ["main.py"]
    d = artifact_digest(artifact_dir, allowlist)
    prov = manifest.get("provenance") or {}
    revision = prov.get("source_artifact_digest")
    candidate_v1 = {
        "schema_version": "capability-candidate-v1",
        "candidate_id": meta["candidate_id"],
        "capability_id": capability_id_derivation(namespace, meta["name"]),
        "name": meta["name"],
        "version": manifest.get("capability", {}).get("version"),
        "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
        "source": {"source_type": "agent",
                   "source_reference": "rollout:" + str(prov.get("source_execution_id") or "unknown"),
                   "resolved_revision": revision},
        "artifact": {"artifact_digest": d, "artifact_ref": f"artifact:{d}",
                     "files": allowlist},
        "manifest": manifest,
        "provenance": {"created_at": prov.get("forge_timestamp"),
                       "source_revision": revision,
                       "build_ref": "bundle:" + str(prov.get("source_bundle_id") or "unknown")},
        "extensions": {},
    }
    return freeze_candidate(
        candidate_v1, artifact_dir, cand / "tests", store_root,
        sealed_at=sealed_at,
        referenced_ids=referenced_candidate_ids(registry_root)
        if registry_root is not None else ())


def static_scan(text: str, forbidden_roots: list[str]) -> list[str]:
    hits = [p for p in FORBIDDEN_PATTERNS if p in text]
    hits += [r for r in forbidden_roots if r and r in text]
    return sorted(set(hits))


def _check_proposal(proposal: dict) -> None:
    required = ("name", "description", "skill_md", "implementation", "entrypoint", "contract")
    for k in required:
        if not proposal.get(k):
            raise CapabilityizeError(f"proposal missing {k!r}")
    if not NAME_RE.match(proposal["name"]):
        raise CapabilityizeError(f"proposal name invalid: {proposal['name']!r}")
    impl = proposal["implementation"]
    if not isinstance(impl, dict) or "main.py" not in impl:
        raise CapabilityizeError("proposal implementation.main.py missing")
    ep = proposal["entrypoint"]
    if not (isinstance(ep, dict) and isinstance(ep.get("command"), list) and ep.get("workdir")):
        raise CapabilityizeError("proposal entrypoint invalid")
    c = proposal["contract"]
    if not (isinstance(c, dict) and c.get("input") and c.get("output")):
        raise CapabilityizeError("proposal contract invalid")


def capabilityize(bundles: list[dict], proposal: dict, confirm: dict,
                  golden_dir: Path, out_dir: Path) -> dict:
    """bundles: [{"bundle_id","bundle_dir","bundle_digest","task_id","arm","cwd"}]
    golden_dir: dir with t1/..tn/, each containing data.csv + expected.json."""
    _check_proposal(proposal)
    if not (isinstance(confirm, dict) and confirm.get("confirm") is True):
        raise CapabilityizeError("operator confirm required (confirm.json)")

    forbidden_roots = [b.get("cwd") for b in bundles if b.get("cwd")]
    all_text = "\n".join(list(proposal["implementation"].values()) + [proposal["skill_md"]])
    hits = static_scan(all_text, forbidden_roots)
    if hits:
        raise CapabilityizeError("task-private state references: " + ", ".join(hits))

    name = proposal["name"]
    out_dir = Path(out_dir)
    cand = out_dir / name
    if cand.exists():
        raise FileExistsError(f"candidate exists: {cand}")
    artifact_dir = cand / "implementation" / "artifact"
    tests_dir = cand / "tests"
    artifact_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    (artifact_dir / "main.py").write_text(proposal["implementation"]["main.py"])
    for tdir in sorted(Path(golden_dir).glob("t*")):
        if not tdir.is_dir():
            continue
        dst = tests_dir / tdir.name
        dst.mkdir()
        (dst / "data.csv").write_bytes((tdir / "data.csv").read_bytes())
        (dst / "expected.json").write_bytes((tdir / "expected.json").read_bytes())

    forged_digest = artifact_digest(artifact_dir, ["main.py"])
    source_artifact_digest = sha256_bytes(canonical_json(
        {"bundle_digests": sorted(b["bundle_digest"] for b in bundles)}))
    tests = [{"id": t.name, "input": {"files": ["data/data.csv"], "args": {}},
              "expected": {"files": ["report.md"]}}
             for t in sorted(Path(golden_dir).glob("t*")) if t.is_dir()]
    first = bundles[0]
    manifest = {
        "manifest_version": "0.1",
        "capability": {"name": name, "description": proposal["description"], "version": 1},
        "entrypoint": proposal["entrypoint"],
        "contract": proposal["contract"],
        "env": {},
        "secrets": [],
        "tests": tests,
        "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                    "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
        "provenance": {
            "source_bundle_id": first["bundle_id"],
            "source_artifact_digest": source_artifact_digest,
            "source_task_id": ",".join(b["task_id"] for b in bundles),
            "source_execution_id": first.get("source_execution_id"),
            "forged_artifact_digest": forged_digest,
            "forge_timestamp": now_iso(),
        },
    }
    (cand / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    candidate_id = "cand-" + uuid.uuid4().hex[:12]
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": candidate_id, "name": name, "state": "candidate",
         "source_bundle_ids": [b["bundle_id"] for b in bundles]}, indent=2) + "\n")
    return {"candidate_id": candidate_id, "candidate_dir": str(cand), "manifest": manifest,
            "forged_artifact_digest": forged_digest}
