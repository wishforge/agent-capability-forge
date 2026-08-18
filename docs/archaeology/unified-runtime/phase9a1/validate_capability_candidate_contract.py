#!/usr/bin/env python3
"""Phase 9-A.1 - CapabilityCandidate v1 offline contract validator.

Machine-checks docs/architecture/capability-candidate-contract-v1.md.
Pure stdlib; intentionally imports nothing from src/ or pilot/ so the
contract layer never depends on production code or source adapters.

Intake rule: a raw input is INTAKE_ACCEPTED only when every REQUIRED core
field and binding invariant holds; anything else is INTAKE_REJECTED. An
invalid raw input can never become a CapabilityCandidate.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "capability-candidate-v1"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# Core key vocabulary (source-agnostic). Unknown top-level keys are rejected
# so source-specific data can never leak into Core.
CORE_KEYS = frozenset({
    "schema_version", "candidate_id", "capability_id", "name", "version",
    "requester", "producer", "source", "artifact", "manifest", "provenance",
    "extensions",
})

# Governance objects are separate records; embedding them in a Candidate is
# an object-boundary violation.
FORBIDDEN_CORE_KEYS = frozenset({
    "evidence", "policy", "decision", "promotion_decision",
    "adoption_authority", "promotion_gate",
})

# Initial source vocabulary (documented, NOT a closed enum: a future source
# type must pass without any Core change).
SOURCE_TYPES = frozenset({
    "git", "oci", "artifact_registry", "agent", "marketplace",
    "internal", "external", "local",
})


def _add(violations: list[dict], code: str, message: str) -> None:
    violations.append({"code": code, "message": message})


def _nonempty_str(obj: Any, key: str) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get(key), str) and bool(obj[key])


def check_core_keys(cand: dict, violations: list[dict]) -> None:
    for key in sorted(FORBIDDEN_CORE_KEYS & set(cand)):
        _add(violations, "OBJECT_BOUNDARY_VIOLATION",
             f"{key} is a separate governance object; embedding it in Candidate core is forbidden")
    for key in sorted(set(cand) - CORE_KEYS):
        _add(violations, "UNKNOWN_CORE_FIELD",
             f"unknown core field {key!r}; source-specific data belongs in extensions")


def check_identity(cand: dict, violations: list[dict]) -> None:
    for key in ("schema_version", "candidate_id", "capability_id", "name"):
        if not _nonempty_str(cand, key):
            _add(violations, "MISSING_CORE_FIELD",
                 f"required core field {key} missing or empty")
    if _nonempty_str(cand, "schema_version") and cand["schema_version"] != SCHEMA_VERSION:
        _add(violations, "INVALID_SCHEMA_VERSION",
             f"expected {SCHEMA_VERSION}, got {cand.get('schema_version')!r}")
    if _nonempty_str(cand, "name") and not NAME_RE.match(cand["name"]):
        _add(violations, "INVALID_NAME",
             f"name must be kebab-case: {cand.get('name')!r}")
    version = cand.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        _add(violations, "INVALID_VERSION",
             f"version must be an int >= 1: {version!r}")


def check_source(cand: dict, violations: list[dict]) -> None:
    src = cand.get("source")
    if not isinstance(src, dict):
        _add(violations, "SOURCE_MISSING", "source object required")
        return
    for key in ("source_type", "source_reference", "resolved_revision"):
        if not _nonempty_str(src, key):
            _add(violations, f"SOURCE_{key.upper()}_MISSING",
                 f"source.{key} required")


def check_artifact(cand: dict, violations: list[dict]) -> None:
    art = cand.get("artifact")
    if not isinstance(art, dict):
        _add(violations, "ARTIFACT_MISSING", "artifact object required")
        return
    digest = art.get("artifact_digest")
    if not isinstance(digest, str) or not DIGEST_RE.match(digest):
        _add(violations, "ARTIFACT_DIGEST_MISSING",
             "artifact.artifact_digest must be sha256:<64 hex>")
    if "artifact_ref" in art and not (
        isinstance(art["artifact_ref"], str) and art["artifact_ref"]
    ):
        _add(violations, "ARTIFACT_REF_INVALID",
             "artifact.artifact_ref must be a non-empty string when present")


def check_party(cand: dict, key: str, violations: list[dict], *, optional: bool = False) -> None:
    party = cand.get(key)
    if party is None and optional:
        return
    if not isinstance(party, dict):
        _add(violations, f"{key.upper()}_MISSING", f"{key} object required")
        return
    for field in ("kind", "id"):
        if not _nonempty_str(party, field):
            _add(violations, f"{key.upper()}_{field.upper()}_MISSING",
                 f"{key}.{field} required")


def check_provenance(cand: dict, violations: list[dict]) -> None:
    prov = cand.get("provenance")
    if not isinstance(prov, dict):
        _add(violations, "PROVENANCE_MISSING", "provenance object required")
        return
    if not _nonempty_str(prov, "created_at"):
        _add(violations, "PROVENANCE_CREATED_AT_MISSING",
             "provenance.created_at required")
    src = cand.get("source") or {}
    if not _nonempty_str(prov, "source_revision"):
        _add(violations, "PROVENANCE_SOURCE_REVISION_MISSING",
             "provenance.source_revision required")
    elif _nonempty_str(src, "resolved_revision") and prov["source_revision"] != src["resolved_revision"]:
        _add(violations, "PROVENANCE_SOURCE_MISMATCH",
             "provenance.source_revision must equal source.resolved_revision")
    for key in ("build_ref", "request_id", "intake_ref"):
        if key in prov and not (isinstance(prov[key], str) and prov[key]):
            _add(violations, "PROVENANCE_FIELD_INVALID",
                 f"provenance.{key} must be a non-empty string when present")


def check_manifest(cand: dict, violations: list[dict]) -> None:
    manifest = cand.get("manifest")
    if not isinstance(manifest, dict):
        _add(violations, "MANIFEST_MISSING", "manifest object required")
        return
    if not _nonempty_str(manifest, "manifest_version"):
        _add(violations, "MANIFEST_VERSION_MISSING",
             "manifest.manifest_version required")
    cap = manifest.get("capability")
    if not (isinstance(cap, dict) and _nonempty_str(cap, "name")):
        _add(violations, "MANIFEST_CAPABILITY_MISSING",
             "manifest.capability.name required")
    if not isinstance(manifest.get("entrypoint"), dict):
        _add(violations, "MANIFEST_ENTRYPOINT_MISSING",
             "manifest.entrypoint object required")
    if not isinstance(manifest.get("contract"), dict):
        _add(violations, "MANIFEST_CONTRACT_MISSING",
             "manifest.contract object required")
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests:
        _add(violations, "MANIFEST_TESTS_MISSING",
             "manifest.tests must be a non-empty list")
    prov = manifest.get("provenance")
    prov = prov if isinstance(prov, dict) else {}
    forged = prov.get("forged_artifact_digest")
    if forged is not None:
        if not isinstance(forged, str) or not DIGEST_RE.match(forged):
            _add(violations, "MANIFEST_FORGED_DIGEST_INVALID",
                 "manifest.provenance.forged_artifact_digest must be sha256:<64 hex>")
        elif forged != (cand.get("artifact") or {}).get("artifact_digest"):
            _add(violations, "ARTIFACT_DIGEST_SEMANTICS_CONFLICT",
                 "manifest.provenance.forged_artifact_digest must equal "
                 "artifact.artifact_digest; Candidate v1 defines exactly one "
                 "artifact digest (Phase 8 dir-digest semantics)")


def check_extensions(cand: dict, violations: list[dict]) -> None:
    ext = cand.get("extensions")
    if ext is None:
        return
    if not isinstance(ext, dict):
        _add(violations, "EXTENSIONS_INVALID",
             "extensions must be an object")
        return
    for name, payload in ext.items():
        if not isinstance(payload, dict):
            _add(violations, "EXTENSION_INVALID",
                 f"extensions.{name} must be an object")


def intake(raw: Any) -> dict:
    """Raw input -> INTAKE_ACCEPTED / INTAKE_REJECTED (fail-closed)."""
    if not isinstance(raw, dict):
        return {"intake": "INTAKE_REJECTED",
                "violations": [{"code": "NOT_AN_OBJECT",
                                "message": "raw input must be an object"}]}
    violations: list[dict] = []
    check_core_keys(raw, violations)
    check_identity(raw, violations)
    check_source(raw, violations)
    check_artifact(raw, violations)
    check_party(raw, "producer", violations)
    check_party(raw, "requester", violations, optional=True)
    check_provenance(raw, violations)
    check_manifest(raw, violations)
    check_extensions(raw, violations)
    return {"intake": "INTAKE_ACCEPTED" if not violations else "INTAKE_REJECTED",
            "violations": violations}


def governance_projection(candidate: dict) -> dict:
    """Phase 8 binding keys consumed by AdoptionAuthority / Registry / Runtime
    Guard. Source-agnostic by construction: never inspects source.source_type.
    """
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_version": f"v{candidate['version']}",
        "capability_id": candidate["capability_id"],
        "name": candidate["name"],
        "artifact_digest": candidate["artifact"]["artifact_digest"],
        "manifest": candidate["manifest"],
        "producer": candidate["producer"],
        "source": candidate["source"],
        "requester": candidate.get("requester"),
    }


def phase8_compatibility(candidate: dict) -> dict:
    """Subset of AdoptionAuthority AUTHORITY_FIELDS that a Candidate supplies."""
    projection = governance_projection(candidate)
    return {
        "supplies_authority_fields": [
            "candidate_id", "candidate_version", "artifact_digest",
        ],
        "projection": projection,
    }


def validate_candidate(raw: Any) -> dict:
    """Full contract check: intake + governance projection + Phase 8 mapping."""
    result = intake(raw)
    if result["intake"] != "INTAKE_ACCEPTED":
        return {
            "schema": "capability-candidate-contract-v1",
            "verdict": "CANDIDATE_CONTRACT_INVALID",
            "intake": "INTAKE_REJECTED",
            "violations": result["violations"],
            "governance_projection": None,
        }
    return {
        "schema": "capability-candidate-contract-v1",
        "verdict": "CANDIDATE_CONTRACT_VALID",
        "intake": "INTAKE_ACCEPTED",
        "violations": [],
        "governance_projection": governance_projection(raw),
        "phase8_compatibility": phase8_compatibility(raw),
    }


EXAMPLE = {
    "schema_version": SCHEMA_VERSION,
    "candidate_id": "cand-deb537a46e21",
    "capability_id": "cap-fplus-csv-clean-statistical-report",
    "name": "csv-clean-statistical-report",
    "version": 1,
    "requester": {"kind": "human", "id": "operator-david", "request_id": "req-fplus-1"},
    "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
    "source": {
        "source_type": "agent",
        "source_reference": "rollout:bd8491b7-f5ab-4ec4-bec2-bb07e0c45e6b",
        "resolved_revision": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2",
    },
    "artifact": {
        "artifact_digest": "sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592",
        "artifact_ref": "artifact:sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592",
    },
    "manifest": {
        "manifest_version": "0.1",
        "capability": {
            "name": "csv-clean-statistical-report",
            "description": "Cleans an order/sales CSV and writes a Markdown statistical report.",
            "version": 1,
        },
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {
            "input": {"files": ["data/*.csv"], "args": {"freeform": ""}},
            "output": {"files": ["report.md"], "stdout": "string", "exit_code": 0},
        },
        "env": {},
        "secrets": [],
        "tests": [
            {"id": "t1", "input": {"files": ["data/data.csv"], "args": {}},
             "expected": {"files": ["report.md"]}},
        ],
        "sandbox": {
            "permissions": {"network": False, "fs_write": ["/output"]},
            "limits": {"timeout_seconds": 120, "output_bytes": 1048576},
        },
        "provenance": {
            "source_bundle_id": "01a0002b-6723-70b5-836d-6bd7af2af4dc",
            "source_artifact_digest": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2",
            "source_task_id": "fplus-cal-1",
            "source_execution_id": "bd8491b7-f5ab-4ec4-bec2-bb07e0c45e6b",
            "forged_artifact_digest": "sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592",
            "forge_timestamp": "2026-08-14T12:11:46.275Z",
        },
    },
    "provenance": {
        "created_at": "2026-08-14T12:11:46.275Z",
        "source_revision": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2",
        "build_ref": "bundle:01a0002b-6723-70b5-836d-6bd7af2af4dc",
        "request_id": "req-fplus-1",
    },
    "extensions": {
        "codex": {
            "applicability": "agent source produced from a Codex rollout",
            "session_id": "sess-01a0002b",
            "thread_id": "thread-01a0002b",
            "turn_id": "turn-01a0002b",
        },
    },
}


def main() -> int:
    report = validate_candidate(EXAMPLE)
    print(report["verdict"], report["intake"])
    for v in report["violations"]:
        print(f"  {v['code']}: {v['message']}")
    return 0 if report["verdict"] == "CANDIDATE_CONTRACT_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
