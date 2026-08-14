"""M4 CLI: `python -m forge.codex_adapter.main build|metrics`.

build: rollout + workspace + run-meta -> sealed Bundle in store + run_artifacts.json
metrics: rollout -> runtime_metrics.json (used for non-bundled runs / generation)
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/

from forge.bundle_producer import seal_bundle, sha256_bytes, sha256_file, validate_bundle  # noqa: E402
from forge.codex_adapter.rollout_parser import parse_rollout  # noqa: E402
from forge.codex_adapter.metrics import runtime_metrics  # noqa: E402

MEDIA_TYPES = {
    ".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown",
    ".json": "application/json", ".txt": "text/plain", ".toml": "text/x-toml",
    ".yaml": "text/x-yaml", ".yml": "text/x-yaml", ".html": "text/html",
    ".sh": "text/x-shellscript",
}
TEXT_EXTS = {".py", ".csv", ".md", ".json", ".txt", ".toml", ".yaml", ".yml", ".html", ".sh"}


def _snapshot(workspace: Path, baseline_files: dict) -> tuple[dict, dict[str, bytes]]:
    """Final-file snapshot vs harness-recorded baseline. Returns (artifacts, file_contents)."""
    workspace = Path(workspace)
    final: dict[str, bytes] = {}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".codex")]
        for name in files:
            if name.endswith(".pyc"):
                continue
            p = Path(root) / name
            rel = p.relative_to(workspace).as_posix()
            final[rel] = p.read_bytes()

    changed = []
    for rel in sorted(set(list(final) + list(baseline_files))):
        if rel in final and rel in baseline_files and sha256_bytes(final[rel]) == baseline_files[rel]:
            continue  # unchanged
        if rel not in final:
            changed.append({"path": rel, "status": "deleted"})
        elif rel in baseline_files:
            changed.append({"path": rel, "status": "modified"})
        else:
            changed.append({"path": rel, "status": "added"})

    diff_parts = []
    file_contents: dict[str, bytes] = {}
    files = []
    for c in changed:
        path, status = c["path"], c["status"]
        if status == "deleted":
            files.append({"path": path, "previous_path": None, "status": status, "digest": None,
                          "content_ref": None, "media_type": None, "size_bytes": None, "executable": None})
            old = baseline_files.get(path)
            if old:
                diff_parts.append(f"diff --git a/{path} b/{path}\n")
                diff_parts.append("--- a/" + path + "\n+++ b/" + path + "\n")
                # baseline bytes are not stored, only digest; emit a deletion stub
                diff_parts.append("-<deleted file, sha256:" + old.removeprefix("sha256:") + ">\n")
            continue
        content = final[path]
        digest = sha256_bytes(content)
        file_contents[digest] = content
        ext = Path(path).suffix
        files.append({
            "path": path, "previous_path": None, "status": status, "digest": digest,
            "content_ref": f"artifacts/files/{digest}",
            "media_type": MEDIA_TYPES.get(ext),
            "size_bytes": len(content),
            "executable": os.access(Path(workspace) / path, os.X_OK),
        })
        if ext in TEXT_EXTS:
            old_text = ""
            if status == "modified" and path in baseline_files:
                old_text = f"<sha256:{baseline_files[path].removeprefix('sha256:')}>\n"
            diff = difflib.unified_diff(old_text.splitlines(keepends=True),
                                        content.decode("utf-8", "replace").splitlines(keepends=True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="\n")
            diff_parts.append("".join(diff))
    return {"unified_diff": "".join(diff_parts), "files": files}, file_contents


def cmd_build(args) -> int:
    run_meta = json.loads(Path(args.run_meta).read_text())
    rollout = Path(args.rollout)
    parsed = parse_rollout(rollout, thread_id_fallback=run_meta.get("run_id"))
    artifacts, file_contents = _snapshot(Path(args.workspace), run_meta.get("baseline_files", {}))
    identity = parsed["identity"]
    completed_at = identity.pop("completed_at")
    generated_at = completed_at or run_meta.get("ended_at")
    identity = {
        "bundle_id": None,  # seal_bundle fills this before sealing
        "source_task_id": None,
        "source_execution_id": run_meta.get("source_execution_id") or str(uuid.uuid4()),
        "session_id": identity["session_id"],
        "thread_id": identity["thread_id"],
        "turn_id": identity["turn_id"],
        "producer": "codex-cli-" + run_meta.get("runtime_version", "unknown"),
        "producer_commit": run_meta.get("runtime_version", "unknown"),
        "generated_at": generated_at,
    }
    execution = parsed["execution"]
    environment = parsed["environment"]
    environment["dependency_manifest_ref"] = None
    env_snapshot = {
        "cwd": environment["cwd"], "workspace_roots": environment["workspace_roots"],
        "network": environment["network"], "permission_policy": environment["permission_policy"],
        "shell": os.environ.get("SHELL"), "sandbox_image": "host-codex-workspace-write",
        "captured_at": run_meta.get("ended_at"),
    }
    gaps_extra = [
        "phase_packets: no orchestrated phase packets in stock codex root rollout",
        "unified_diff_source: workspace diff vs harness baseline (no TurnDiffEvent in stock rollout)",
        f"task_id={run_meta.get('task_id')} carried in run metadata only",
    ]
    store = Path(args.store)
    bdir, bundle = seal_bundle(
        store, identity=identity, execution=execution, artifacts=artifacts,
        review=parsed["review"],
        verification_evidence={
            "status": "unknown", "command": None, "exit_code": None, "stdout_ref": None,
            "stderr_ref": None, "checker_result": None, "evidence_digest": None,
            "evidence_refs": [],
            "gaps": ["verification_evidence: no structured command-level evidence in Codex v0"],
            "captured_at": None,
        },
        environment=environment,
        security={"secrets_policy": "no_inline_secrets", "scan_status": "not_scanned",
                  "scan_ref": None, "scan_digest": None},
        rollout_bytes=rollout.read_bytes(),
        environment_snapshot=env_snapshot,
        file_contents=file_contents,
        producer_commit=None,
        gaps_extra=gaps_extra,
    )
    (bdir / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    validation = validate_bundle(bdir)
    result = {
        "bundle_id": bundle["bundle_id"],
        "bundle_dir": str(bdir.relative_to(store)) if bdir.is_relative_to(store) else str(bdir),
        "bundle_digest": bundle["provenance"]["bundle_digest"],
        "validation": validation,
        "gaps": bundle["provenance"]["gaps"],
        "runtime_metrics": parsed["metrics"],
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    if not validation["ok"]:
        print(json.dumps({"ok": False, "errors": validation["errors"]}, indent=2))
        return 1
    return 0


def cmd_metrics(args) -> int:
    out = {"runtime_metrics": runtime_metrics(Path(args.rollout))}
    Path(args.out).write_text(json.dumps(out, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--rollout", required=True)
    b.add_argument("--workspace", required=True)
    b.add_argument("--run-meta", required=True)
    b.add_argument("--store", required=True)
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_build)
    m = sub.add_parser("metrics")
    m.add_argument("--rollout", required=True)
    m.add_argument("--out", required=True)
    m.set_defaults(func=cmd_metrics)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
