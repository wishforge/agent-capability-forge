#!/usr/bin/env python3
"""Phase 9-A.1.1 - CapabilityCandidate closure design validator (offline, stdlib).

Machine-checks the four Phase 9-A.1 Review hard blockers:
  A. capability_id ownership   (intake mints, Registry consumes, never re-mints)
  B. CANONICAL_ARTIFACT_IDENTITY_V1 (allowlist digest + exact frozen layout)
  C. CANDIDATE_FREEZE_RULES_V1 (Draft -> Intake -> Seal -> Frozen Candidate)
  D. Governance source independence (semantic projection carries no source)

Pure stdlib; imports nothing from src/ or pilot/. Reuses the Phase 9-A.1
contract validator for the base intake checks, then adds closure invariants
that require artifact bytes and test bytes (the v1 validator could not see).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from validate_capability_candidate_contract import intake, DIGEST_RE  # noqa: E402

SEAL_SCHEMA = "frozen-candidate-v1"
SEAL_VERSION = "v1"

# Immutable once sealed. Evidence is deliberately absent from this set:
# validation/evaluation/decision/authority records are separate objects.
FROZEN_CORE_KEYS = (
    "schema_version", "candidate_id", "capability_id", "name", "version",
    "source", "producer", "requester", "artifact", "manifest", "provenance",
    "extensions",
)

# Governance provenance subset that survives projection. source_type /
# source_reference are intake metadata, never governance semantic input.
GOVERNANCE_PROVENANCE_KEYS = (
    "created_at", "source_revision", "build_ref", "request_id", "intake_ref",
)


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


# ---------------------------------------------------------------------------
# B. CANONICAL_ARTIFACT_IDENTITY_V1
# ---------------------------------------------------------------------------
def canonical_artifact_digest(files: dict[str, str]) -> str:
    """sha256(canonical({rel_path: file_sha256})), sorted rel paths.

    Bare-map shape = Phase 8 adoption_authority.dir_digest, the semantics the
    Runtime Guard actually enforces. The old harness {"files": ...} wrapper
    is legacy and is not used for artifact binding.
    """
    return _sha256(_canonical({p: files[p] for p in sorted(files)}))


def artifact_layout(directory: Path, allowlist: list[str]) -> tuple[dict[str, str], list[str]]:
    """Exact-layout check: actual file set must equal the allowlist.

    Returns (allowlist file digests, violations). The digest is computed from
    the allowlist only, so runtime-generated files (__pycache__, *.pyc, logs,
    tmp) can never change it; the exact-layout check rejects those same files
    at seal/activation time (fail-closed, no ignore list).
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
    files = {}
    for rel in sorted(wanted):
        path = directory / rel
        if path.is_file():
            files[rel] = file_sha256(path)
    return files, violations


def frozen_artifact_report(directory: Path, allowlist: list[str]) -> dict:
    files, violations = artifact_layout(directory, allowlist)
    return {
        "ok": not violations,
        "digest": canonical_artifact_digest(files),
        "violations": violations,
    }


def artifact_digest(directory: Path, allowlist: list[str]) -> str:
    """Digest over the allowlist only; identical with/without pycache/log/tmp."""
    files, _ = artifact_layout(directory, allowlist)
    return canonical_artifact_digest(files)


# ---------------------------------------------------------------------------
# A. Identity + intake cross-field closure
# ---------------------------------------------------------------------------
def closure_cross_field_violations(candidate: dict) -> list[dict]:
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
    digest = art.get("artifact_digest")
    ref = art.get("artifact_ref")
    if ref is not None and ref != f"artifact:{digest}":
        block("ARTIFACT_REF_BINDING_MISMATCH",
              f"artifact_ref={ref!r} artifact_digest={digest!r}")
    if not isinstance(art.get("files"), list) or not art.get("files"):
        block("ARTIFACT_ALLOWLIST_MISSING",
              "artifact.files (explicit allowlist) is required and must be non-empty")

    forged = (manifest.get("provenance") or {}).get("forged_artifact_digest")
    if not isinstance(forged, str) or not DIGEST_RE.match(forged):
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
        block("CAPABILITY_ID_FORMAT",
              f"capability_id must start with 'cap-': {cid!r}")
    return violations


def closure_intake(candidate: dict, artifact_dir=None, tests_dir=None) -> dict:
    """Base v1 intake + closure invariants + byte-level artifact verification."""
    result = intake(candidate)
    violations = [dict(v) for v in result["violations"]]
    violations += closure_cross_field_violations(candidate)
    record = None
    if artifact_dir is not None and tests_dir is not None:
        frozen = freeze_candidate(candidate, artifact_dir, tests_dir)
        if not frozen["ok"]:
            violations += frozen["violations"]
        record = frozen["record"]
    return {
        "intake": "INTAKE_ACCEPTED" if not violations else "INTAKE_REJECTED",
        "violations": violations,
        "freeze": record,
    }


# ---------------------------------------------------------------------------
# C. CANDIDATE_FREEZE_RULES_V1
# ---------------------------------------------------------------------------
def manifest_digest(manifest: dict) -> str:
    return _sha256(_canonical(manifest))


def tests_digest(tests_dir: Path) -> str:
    """Canonical digest over the tests directory (all files, sorted)."""
    files = {
        p.relative_to(tests_dir).as_posix(): file_sha256(p)
        for p in sorted(tests_dir.rglob("*"))
        if p.is_file()
    }
    return _sha256(_canonical(files))


def seal_digest(candidate: dict, artifact_digest_value: str,
                tests_digest_value: str) -> str:
    """Digest over frozen core + computed identity digests.

    evaluation.json / validation.json / decisions / authority records are NOT
    inputs; they are append-only evidence that reference this digest.
    """
    payload = {k: candidate[k] for k in FROZEN_CORE_KEYS if k in candidate}
    payload["artifact_digest"] = artifact_digest_value
    payload["manifest_digest"] = manifest_digest(candidate["manifest"])
    payload["tests_digest"] = tests_digest_value
    return _sha256(_canonical(payload))


def governance_digest(candidate: dict, artifact_digest_value: str,
                      tests_digest_value: str) -> str:
    """Source-independent semantic digest for governance consumers.

    Deliberately excludes the source sub-object (and anything derived from it)
    so source_type / source_reference can never change governance semantics.
    The full seal_digest still covers source for audit-grade immutability.
    """
    payload = {
        "candidate_id": candidate.get("candidate_id"),
        "capability_id": candidate.get("capability_id"),
        "name": candidate.get("name"),
        "version": candidate.get("version"),
        "artifact_digest": artifact_digest_value,
        "manifest_digest": manifest_digest(candidate.get("manifest", {})),
        "tests_digest": tests_digest_value,
        "producer": candidate.get("producer"),
        "requester": candidate.get("requester"),
        "provenance": {k: v for k, v in (candidate.get("provenance") or {}).items()
                       if k in GOVERNANCE_PROVENANCE_KEYS},
    }
    return _sha256(_canonical(payload))


def freeze_candidate(candidate: dict, artifact_dir, tests_dir,
                     *, sealed_at: str = "2026-08-18T00:00:00.000Z") -> dict:
    """Seal point: write-once Frozen Candidate after every check passes."""
    violations: list[dict] = []
    for v in closure_cross_field_violations(candidate):
        violations.append(v)
    art = frozen_artifact_report(Path(artifact_dir), candidate.get("artifact", {}).get("files"))
    if not art["ok"]:
        for v in art["violations"]:
            violations.append({"code": v.split(":")[0], "message": v})
    if art["digest"] != candidate.get("artifact", {}).get("artifact_digest"):
        violations.append({"code": "ARTIFACT_DIGEST_MISMATCH",
                           "message": f"bytes={art['digest']} "
                                      f"candidate={candidate.get('artifact', {}).get('artifact_digest')}"})
    td = tests_digest(Path(tests_dir))
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
        "governance_digest": governance_digest(candidate, art["digest"], td),
        "sealed_at": sealed_at,
    }
    return {"ok": not violations, "violations": violations, "record": record if not violations else None}


def verify_frozen(record: dict, candidate: dict, artifact_dir, tests_dir) -> dict:
    """Post-seal verification: every immutable input must still match."""
    violations: list[dict] = []

    def block(code: str, message: str) -> None:
        violations.append({"code": code, "message": message})

    if record.get("schema") != SEAL_SCHEMA or record.get("seal_version") != SEAL_VERSION:
        block("SEAL_SCHEMA_MISMATCH", "frozen record schema/seal_version mismatch")
    for key in ("candidate_id", "capability_id", "name", "version"):
        if record.get(key) != candidate.get(key):
            block("FROZEN_FIELD_CHANGED", f"{key} changed after seal")
    art = frozen_artifact_report(Path(artifact_dir), candidate.get("artifact", {}).get("files"))
    if not art["ok"]:
        for v in art["violations"]:
            block(v.split(":")[0], v)
    if art["digest"] != record.get("artifact_digest"):
        block("ARTIFACT_DIGEST_MISMATCH", "artifact bytes changed after seal")
    if manifest_digest(candidate.get("manifest", {})) != record.get("manifest_digest"):
        block("MANIFEST_CHANGED_AFTER_SEAL", "manifest changed after seal")
    if tests_digest(Path(tests_dir)) != record.get("tests_digest"):
        block("TESTS_CHANGED_AFTER_SEAL", "tests changed after seal")
    if seal_digest(candidate, art["digest"], tests_digest(Path(tests_dir))) != record.get("seal_digest"):
        block("SEAL_DIGEST_MISMATCH", "frozen core changed after seal")
    return {"ok": not violations, "violations": violations}


def modification_verdict(verify: dict) -> str:
    """Freeze rule: any immutable-field change -> new candidate_id, never edit."""
    return "FROZEN_CANDIDATE_UNCHANGED" if verify["ok"] else "NEW_CANDIDATE_REQUIRED"


# ---------------------------------------------------------------------------
# D. Governance source independence
# ---------------------------------------------------------------------------
def governance_projection(candidate: dict, record: dict) -> dict:
    """Semantic projection consumed by Evaluation/Promotion/Adoption/Registry/
    Runtime. No source sub-object, no source_type, no source_reference.
    """
    prov = candidate.get("provenance") or {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "candidate_version": f"v{candidate.get('version')}",
        "capability_id": candidate.get("capability_id"),
        "name": candidate.get("name"),
        "artifact_digest": record.get("artifact_digest"),
        "manifest_digest": record.get("manifest_digest"),
        "tests_digest": record.get("tests_digest"),
        "governance_digest": record.get("governance_digest"),
        "producer": candidate.get("producer"),
        "requester": candidate.get("requester"),
        "provenance": {k: prov[k] for k in GOVERNANCE_PROVENANCE_KEYS if k in prov},
    }


def source_leak_violations(projection: dict) -> list[str]:
    """Deep scan: any source_type / source_reference in the projection is a
    GOVERNANCE_SOURCE_LEAK, regardless of which nested consumer reads it."""
    leaks: list[str] = []
    stack = [projection]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("source_type", "source_reference"):
                    leaks.append(f"GOVERNANCE_SOURCE_LEAK:{k}")
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
    return sorted(set(leaks))


def registry_capability_id_conflict(candidate_capability_id: str | None,
                                    registry_capability_id: str | None) -> str | None:
    """Registry consumes Candidate's capability_id; it never mints one.

    None = reuse allowed (new entry or identical id). A different id on an
    existing entry is a hard conflict; reject() also never creates an id.
    """
    if registry_capability_id is None or candidate_capability_id is None:
        return None
    if registry_capability_id != candidate_capability_id:
        return "CAPABILITY_ID_CONFLICT"
    return None


def capability_id_derivation(namespace: str, name: str) -> str:
    """Deterministic, replayable intake-level derivation (Phase 9-B adapter).

    Same (namespace, name) -> same capability_id across sources and retries.
    Legacy cap-<uuid> entries keep their id until an operator re-binds them.
    """
    return "cap-" + _sha256(_canonical({"namespace": namespace, "name": name}))[len("sha256:"):][:16]


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "artifact" / "main.py").parent.mkdir()
        (root / "artifact" / "main.py").write_text("print('ok')\n")
        (root / "tests" / "t1").mkdir(parents=True)
        (root / "tests" / "t1" / "data.csv").write_text("id\n")
        (root / "tests" / "t1" / "expected.json").write_text("{}")
        art_digest = artifact_digest(root / "artifact", ["main.py"])
        from validate_capability_candidate_contract import SCHEMA_VERSION
        candidate = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": "cand-1",
            "capability_id": capability_id_derivation("F+", "csv-clean-report"),
            "name": "csv-clean-report",
            "version": 1,
            "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
            "source": {"source_type": "agent", "source_reference": "rollout:r1",
                       "resolved_revision": "sha256:" + "d" * 64},
            "artifact": {"artifact_digest": art_digest, "artifact_ref": f"artifact:{art_digest}",
                         "files": ["main.py"]},
            "manifest": {
                "manifest_version": "0.1",
                "capability": {"name": "csv-clean-report", "version": 1},
                "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
                "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
                "tests": [{"id": "t1"}],
                "provenance": {"forged_artifact_digest": art_digest,
                               "source_artifact_digest": "sha256:" + "d" * 64},
            },
            "provenance": {"created_at": "2026-08-18T00:00:00.000Z",
                           "source_revision": "sha256:" + "d" * 64},
        }
        result = closure_intake(candidate, root / "artifact", root / "tests")
        print("CANDIDATE_CONTRACT_CLOSED" if result["intake"] == "INTAKE_ACCEPTED"
              else "CANDIDATE_CONTRACT_INVALID", result["intake"])
        for v in result["violations"]:
            print(f"  {v['code']}: {v['message']}")
        return 0 if result["intake"] == "INTAKE_ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
