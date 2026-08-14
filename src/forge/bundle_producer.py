"""M5 - VerifiedTaskArtifactBundle v0 producer + validator.

Implements the frozen P0 contract:
research/artifact-contract/verified-task-artifact-bundle-v0.md
Strict schema (unknown keys rejected), canonical bundle_digest (sorted keys,
compact, no trailing newline, digest computed with itself null), 13 rules,
content-addressed store layout.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "verified-task-artifact-bundle-v0"
BUILDER_PRODUCER = "codex-artifact-builder-v0"


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def uuidv7() -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp + version/variant + random."""
    ts = int(time.time() * 1000)
    b = bytearray(ts.to_bytes(6, "big") + secrets.token_bytes(10))
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# schema spec: {type, nullable, enum, literal, children, items, required}
# ---------------------------------------------------------------------------
def _s(t, **kw):
    return {"type": t, **kw}


SCHEMA = {
    "schema_version": _s(str, literal=SCHEMA_VERSION),
    "bundle_id": _s(str),
    "identity": _s(dict, required=[
        "bundle_id", "source_task_id", "source_execution_id", "session_id",
        "thread_id", "turn_id", "producer", "producer_commit", "generated_at"], children={
        "bundle_id": _s(str),
        "source_task_id": _s(str, nullable=True),
        "source_execution_id": _s(str, nullable=True),
        "session_id": _s(str),
        "thread_id": _s(str),
        "turn_id": _s(str, nullable=True),
        "producer": _s(str),
        "producer_commit": _s(str),
        "generated_at": _s(str),
    }),
    "execution": _s(dict, required=["rollout_ref", "phases", "final_phase", "root_synthesis"], children={
        "rollout_ref": _s(dict, required=["path", "digest", "source"], children={
            "path": _s(str), "digest": _s(str), "source": _s(str, literal="runtime_capture")}),
        "phases": _s(list, items=_s(dict, required=[
            "phase", "sequence", "packet", "packet_ref", "truncated", "status", "owner", "source"], children={
            "phase": _s(str, enum=["task-contract", "explorer", "worker-plan", "plan-review",
                                   "plan-evidence", "worker", "result-review"]),
            "sequence": _s(int),
            "packet": _s(str),
            "packet_ref": _s(type(None), nullable=True),
            "truncated": _s(bool),
            "status": _s(str, enum=["complete", "incomplete", "invalid", "approved",
                                    "revise", "direct", "evidence-needed", "unknown"]),
            "owner": _s(str, nullable=True, enum=["worker", "explorer", "root", "user"]),
            "source": _s(str, literal="rollout"),
        })),
        "final_phase": _s(dict, nullable=True, required=[
            "phase", "outcome", "worker_status", "worker_packet_sequence",
            "result_review_status", "correction_owner", "authority", "truncated",
            "retry_count", "captured_at"], children={
            "phase": _s(str, enum=["worker", "result-review"]),
            "outcome": _s(str, enum=["completed", "stopped", "skipped"]),
            "worker_status": _s(str, enum=["complete", "incomplete", "invalid"]),
            "worker_packet_sequence": _s(int, nullable=True),
            "result_review_status": _s(str, enum=["approved", "revise", "none"]),
            "correction_owner": _s(str, nullable=True, enum=["worker", "explorer", "root", "user"]),
            "authority": _s(str, literal="runtime_capture"),
            "truncated": _s(bool),
            "retry_count": _s(int),
            "captured_at": _s(str, nullable=True),
        }),
        "root_synthesis": _s(dict, nullable=True, required=["text", "truncated", "source"], children={
            "text": _s(str), "truncated": _s(bool), "source": _s(str)}),
    }),
    "artifacts": _s(dict, required=["unified_diff", "files"], children={
        "unified_diff": _s(str),
        "files": _s(list, items=_s(dict, required=[
            "path", "previous_path", "status", "digest", "content_ref",
            "media_type", "size_bytes", "executable"], children={
            "path": _s(str),
            "previous_path": _s(str, nullable=True),
            "status": _s(str, enum=["added", "modified", "deleted", "renamed"]),
            "digest": _s(str, nullable=True),
            "content_ref": _s(str, nullable=True),
            "media_type": _s(str, nullable=True),
            "size_bytes": _s(int, nullable=True),
            "executable": _s(bool, nullable=True),
        })),
    }),
    "review": _s(dict, required=["worker_status", "result_review_status", "correction_owner", "interpretation"], children={
        "worker_status": _s(str, enum=["complete", "incomplete", "invalid"]),
        "result_review_status": _s(str, enum=["approved", "revise", "none"]),
        "correction_owner": _s(str, nullable=True, enum=["worker", "explorer", "root", "user"]),
        "interpretation": _s(str),
    }),
    "verification_evidence": _s(dict, required=[
        "status", "command", "exit_code", "stdout_ref", "stderr_ref", "checker_result",
        "evidence_digest", "evidence_refs", "gaps", "captured_at"], children={
        "status": _s(str, enum=["unknown", "complete"]),
        "command": _s(str, nullable=True),
        "exit_code": _s(int, nullable=True),
        "stdout_ref": _s(dict, nullable=True, required=["path", "digest"], children={
            "path": _s(str), "digest": _s(str)}),
        "stderr_ref": _s(dict, nullable=True, required=["path", "digest"], children={
            "path": _s(str), "digest": _s(str)}),
        "checker_result": _s(dict, nullable=True),
        "evidence_digest": _s(str, nullable=True),
        "evidence_refs": _s(list, items=_s(dict, required=["path", "digest", "role"], children={
            "path": _s(str), "digest": _s(str), "role": _s(str)})),
        "gaps": _s(list, items=_s(str)),
        "captured_at": _s(str, nullable=True),
    }),
    "environment": _s(dict, required=[
        "cwd", "workspace_roots", "network", "permission_policy",
        "environment_snapshot_ref", "dependency_manifest_ref"], children={
        "cwd": _s(str),
        "workspace_roots": _s(list, nullable=True, items=_s(str)),
        "network": _s(dict, nullable=True, required=["allowed_domains", "denied_domains"], children={
            "allowed_domains": _s(list, items=_s(str)),
            "denied_domains": _s(list, items=_s(str))}),
        "permission_policy": _s(dict, nullable=True, required=[
            "approval_policy", "sandbox_policy", "permission_profile"], children={
            "approval_policy": _s(str), "sandbox_policy": _s(str), "permission_profile": _s(str)}),
        "environment_snapshot_ref": _s(dict, nullable=True, required=["path", "digest"], children={
            "path": _s(str), "digest": _s(str)}),
        "dependency_manifest_ref": _s(dict, nullable=True),
    }),
    "replay_reference": _s(dict, nullable=True, required=["kind", "ref", "description"], children={
        "kind": _s(str, enum=["rollout", "command_sequence", "environment_reconstruction"]),
        "ref": _s(dict, required=["path", "digest"], children={"path": _s(str), "digest": _s(str)}),
        "description": _s(str, nullable=True),
    }),
    "security": _s(dict, required=["secrets_policy", "scan_status", "scan_ref", "scan_digest"], children={
        "secrets_policy": _s(str),
        "scan_status": _s(str, enum=["not_scanned", "scanned"]),
        "scan_ref": _s(str, nullable=True),
        "scan_digest": _s(str, nullable=True),
    }),
    "provenance": _s(dict, required=[
        "source_artifact_digest", "source_rollout_digest", "workspace_snapshot_digest",
        "bundle_digest", "producer", "producer_commit", "generated_at", "gaps"], children={
        "source_artifact_digest": _s(str),
        "source_rollout_digest": _s(str),
        "workspace_snapshot_digest": _s(str),
        "bundle_digest": _s(str),
        "producer": _s(str),
        "producer_commit": _s(str, nullable=True),
        "generated_at": _s(str),
        "gaps": _s(list, items=_s(str)),
    }),
}


def _check(spec, value, path, errors):
    t = spec["type"]
    if value is None:
        if spec.get("nullable"):
            return
        errors.append(f"{path}: required (null not allowed)")
        return
    if t is bool:
        ok = isinstance(value, bool)
    elif t is type(None):
        ok = value is None
    elif t is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = isinstance(value, t)
    if not ok:
        errors.append(f"{path}: expected {t.__name__}, got {type(value).__name__}")
        return
    if spec.get("literal") is not None and value != spec["literal"]:
        errors.append(f"{path}: must be literal {spec['literal']!r}")
    if spec.get("enum") and value not in spec["enum"]:
        errors.append(f"{path}: {value!r} not in {spec['enum']}")
    if t is dict:
        children = spec.get("children") or {}
        for key, child in children.items():
            if key in value:
                _check(child, value[key], f"{path}.{key}", errors)
        for key in value:
            if key not in children:
                errors.append(f"{path}: unknown key {key!r}")
        for key in spec.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
    elif t is list:
        items = spec.get("items")
        if items:
            for i, item in enumerate(value):
                _check(items, item, f"{path}[{i}]", errors)


def validate_schema(bundle: dict) -> list[str]:
    errors = []
    for key, spec in SCHEMA.items():
        if key in bundle:
            _check(spec, bundle[key], key, errors)
        else:
            errors.append(f"{key}: missing")
    for key in bundle:
        if key not in SCHEMA:
            errors.append(f"unknown top-level key {key!r}")
    return errors


def recompute_bundle_digest(bundle: dict) -> str:
    b = json.loads(json.dumps(bundle))
    b["provenance"]["bundle_digest"] = None
    return sha256_bytes(canonical_json(b))


def seal_bundle(store: Path, *, bundle_id: str | None = None, identity: dict, execution: dict,
                artifacts: dict, review: dict, verification_evidence: dict, environment: dict,
                security: dict, rollout_bytes: bytes, environment_snapshot: dict,
                file_contents: dict[str, bytes], producer_commit: str | None,
                gaps_extra: list[str] | None = None) -> tuple[Path, dict]:
    """Write a sealed bundle into `store/bundles/<bundle_id>` and return (dir, bundle)."""
    store = Path(store)
    bundle_id = bundle_id or uuidv7()
    identity["bundle_id"] = bundle_id
    bdir = store / "bundles" / bundle_id
    if bdir.exists():
        raise FileExistsError(f"bundle already exists: {bdir}")

    rollout_digest = sha256_bytes(rollout_bytes)
    env_digest = sha256_bytes(canonical_json(environment_snapshot))
    snapshot = sorted(
        ({"path": f["path"], "digest": f["digest"]} for f in artifacts.get("files", []) if f.get("digest")),
        key=lambda x: x["path"])
    snapshot_manifest = {"files": snapshot}
    snapshot_digest = sha256_bytes(canonical_json(snapshot_manifest))

    evidence_digest = verification_evidence.get("evidence_digest")
    source_artifact_digest = sha256_bytes(canonical_json({
        "source_rollout_digest": rollout_digest,
        "workspace_snapshot_digest": snapshot_digest,
        "environment_snapshot_digest": env_digest,
        "evidence_digest": evidence_digest,
    }))

    execution["rollout_ref"] = {"path": "execution/rollout.jsonl", "digest": rollout_digest,
                                "source": "runtime_capture"}
    environment["environment_snapshot_ref"] = {"path": "environment/snapshot.json", "digest": env_digest}

    gaps = [
        "task_id",
        "final_phase_authority",
        "verification_evidence",
        "dependency_manifest",
        "replay_reference",
        "secrets_scan",
    ]
    if producer_commit is None:
        gaps.append("producer_commit: builder commit unknown (P0 allows null)")
    gaps += gaps_extra or []
    gaps = sorted(set(gaps))

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": bundle_id,
        "identity": identity,
        "execution": execution,
        "artifacts": artifacts,
        "review": review,
        "verification_evidence": verification_evidence,
        "environment": environment,
        "replay_reference": None,
        "security": security,
        "provenance": {
            "source_artifact_digest": source_artifact_digest,
            "source_rollout_digest": rollout_digest,
            "workspace_snapshot_digest": snapshot_digest,
            "bundle_digest": None,
            "producer": BUILDER_PRODUCER,
            "producer_commit": producer_commit,
            "generated_at": now_iso(),
            "gaps": gaps,
        },
    }
    bundle_digest = recompute_bundle_digest(bundle)
    bundle["provenance"]["bundle_digest"] = bundle_digest

    bdir.mkdir(parents=True)
    (bdir / "execution").mkdir()
    (bdir / "artifacts" / "files").mkdir(parents=True)
    (bdir / "environment").mkdir()
    (bdir / "verification").mkdir()
    (bdir / "replay").mkdir()
    (bdir / "execution" / "rollout.jsonl").write_bytes(rollout_bytes)
    (bdir / "environment" / "snapshot.json").write_bytes(canonical_json(environment_snapshot))
    (bdir / "artifacts" / "snapshot_manifest.json").write_bytes(canonical_json(snapshot_manifest))
    for digest, content in file_contents.items():
        (bdir / "artifacts" / "files" / digest).write_bytes(content)
    (bdir / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    return bdir, bundle


def _resolve(bdir: Path, ref: str) -> Path | None:
    p = Path(ref)
    if p.is_absolute() or ".." in p.parts or ref.startswith("file://"):
        return None
    return bdir / p


def validate_bundle(bdir: Path) -> dict:
    """Execute the 13 frozen validation rules. Returns {ok, errors}."""
    errors = []
    bdir = Path(bdir)
    bundle = json.loads((bdir / "bundle.json").read_text())

    # Rule 1
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append("Rule 1: schema_version mismatch")
    # Rule 2 (format; uniqueness is checked by seal refusing existing dirs)
    bid = bundle.get("bundle_id", "")
    parts = bid.split("-")
    if len(parts) != 5 or len(parts[0]) != 8 or len(parts[1]) != 4 or len(parts[2]) != 4 or len(parts[3]) != 4 or len(parts[4]) != 12:
        errors.append("Rule 2: bundle_id is not UUIDv7-shaped")
    elif parts[2][0] != "7":
        errors.append("Rule 2: bundle_id version is not 7")
    # Rule 3
    errors += [f"Rule 3: {e}" for e in validate_schema(bundle)]
    # Rule 4
    digest_ok = True
    for ref in ("provenance.source_artifact_digest", "provenance.source_rollout_digest",
                "provenance.workspace_snapshot_digest", "provenance.bundle_digest",
                "execution.rollout_ref.digest", "environment.environment_snapshot_ref.digest"):
        node = bundle
        for k in ref.split("."):
            node = node.get(k) if isinstance(node, dict) else None
        if not (isinstance(node, str) and node.startswith("sha256:") and len(node) == 7 + 64):
            errors.append(f"Rule 4: bad digest format at {ref}")
            digest_ok = False
    if digest_ok and recompute_bundle_digest(bundle) != bundle["provenance"]["bundle_digest"]:
        errors.append("Rule 4: bundle_digest recompute mismatch")
    # Rule 5/6/12: refs relative, resolve, no live paths
    refs = [bundle["execution"]["rollout_ref"]["path"]]
    if bundle["environment"]["environment_snapshot_ref"]:
        refs.append(bundle["environment"]["environment_snapshot_ref"]["path"])
    for f in bundle["artifacts"]["files"]:
        if f.get("content_ref"):
            refs.append(f["content_ref"])
    for r in refs:
        resolved = _resolve(bdir, r)
        if resolved is None:
            errors.append(f"Rule 5/12: ref not store-relative: {r}")
        elif not resolved.exists():
            errors.append(f"Rule 6: ref missing: {r}")
    # Rule 7: file digests
    for f in bundle["artifacts"]["files"]:
        if f.get("digest") and f.get("content_ref"):
            p = _resolve(bdir, f["content_ref"])
            if p and p.exists() and sha256_file(p) != f["digest"]:
                errors.append(f"Rule 7: digest mismatch {f['path']}")
        if f.get("digest") and f.get("content_ref") and f["content_ref"] != f"artifacts/files/{f['digest']}":
            errors.append(f"Rule 7: content_ref not named by digest {f['path']}")
    for ref in ("rollout_ref", "environment_snapshot_ref"):
        node = bundle["execution"][ref] if ref == "rollout_ref" else bundle["environment"][ref]
        if node and _resolve(bdir, node["path"]):
            if sha256_file(bdir / node["path"]) != node["digest"]:
                errors.append(f"Rule 7: digest mismatch {ref}")
    # Rule 8: phase ordering + final-phase authority
    seqs = [p["sequence"] for p in bundle["execution"]["phases"]]
    if seqs != list(range(1, len(seqs) + 1)):
        errors.append("Rule 8: phases sequence not 1..n")
    fp = bundle["execution"]["final_phase"]
    if fp is not None:
        if fp.get("authority") != "runtime_capture":
            errors.append("Rule 8: final_phase without runtime_capture authority")
        wps = fp.get("worker_packet_sequence")
        if wps is not None:
            phases = bundle["execution"]["phases"]
            if not (1 <= wps <= len(phases) and phases[wps - 1]["phase"] == "worker"):
                errors.append("Rule 8: worker_packet_sequence does not point to a worker phase")
    # Rule 9: review grammar vs packet text
    for p in bundle["execution"]["phases"]:
        text = p["packet"]
        if p["phase"] == "worker":
            if text.startswith("worker: complete") and bundle["review"]["worker_status"] != "complete":
                errors.append("Rule 9: worker packet says complete, review disagrees")
            if text.startswith("worker: incomplete") and bundle["review"]["worker_status"] != "incomplete":
                errors.append("Rule 9: worker packet says incomplete, review disagrees")
        if p["phase"] == "result-review":
            if text.startswith("result-review: approved") and bundle["review"]["result_review_status"] != "approved":
                errors.append("Rule 9: result-review packet says approved, review disagrees")
            if text.startswith("result-review: revise") and bundle["review"]["result_review_status"] != "revise":
                errors.append("Rule 9: result-review packet says revise, review disagrees")
    # Rule 10: verification grammar
    ve = bundle["verification_evidence"]
    if ve["status"] == "unknown":
        for k in ("command", "exit_code", "stdout_ref", "stderr_ref", "checker_result", "evidence_digest", "captured_at"):
            if ve.get(k) is not None:
                errors.append(f"Rule 10: status=unknown but {k} is set")
        if ve["evidence_refs"]:
            errors.append("Rule 10: status=unknown but evidence_refs non-empty")
        if not ve["gaps"]:
            errors.append("Rule 10: status=unknown but gaps empty")
    elif ve["status"] == "complete":
        if not ve["evidence_refs"] or not ve["evidence_digest"]:
            errors.append("Rule 10: status=complete without evidence_refs/evidence_digest")
    # Rule 11: security marker
    sec = bundle["security"]
    if sec["scan_status"] == "not_scanned":
        if "secrets_scan" not in bundle["provenance"]["gaps"]:
            errors.append("Rule 11: not_scanned but gaps lacks secrets_scan")
    else:
        if not sec.get("scan_ref") or not sec.get("scan_digest"):
            errors.append("Rule 11: scanned without scan_ref/scan_digest")
    # Rule 13: no Candidate/Capability/Promotion state
    forbidden_keys = {"candidate", "manifest", "promotion", "evaluation", "capability",
                      "forged_artifact_digest", "revoked", "promoted", "instance_id"}
    stack = [bundle]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in forbidden_keys:
                    errors.append(f"Rule 13: forbidden key {k!r} inside bundle")
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)

    return {"ok": not errors, "errors": errors}
