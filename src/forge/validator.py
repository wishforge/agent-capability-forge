"""M9 - B3 deterministic validation (P2 Validator seed)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .bundle_producer import sha256_bytes
from .capabilityizer import NAME_RE, static_scan

ALLOWED_FS_WRITE = {"/output"}


def _load_candidate(cand: Path) -> dict:
    manifest = json.loads((cand / "manifest.json").read_text())
    errors = []
    if manifest.get("manifest_version") != "0.1":
        errors.append("manifest_version must be 0.1")
    cap = manifest.get("capability", {})
    if not NAME_RE.match(cap.get("name", "")):
        errors.append("capability.name invalid")
    if cap.get("version") != 1:
        errors.append("capability.version must be 1")
    ep = manifest.get("entrypoint", {})
    if not (ep.get("command") and ep.get("workdir") == "artifact"):
        errors.append("entrypoint must be command + workdir=artifact")
    if not manifest.get("tests"):
        errors.append("tests must be non-empty")
    sandbox = manifest.get("sandbox", {})
    perms = sandbox.get("permissions", {})
    if perms.get("network") is not False:
        errors.append("sandbox.permissions.network must be false")
    if not set(perms.get("fs_write", [])).issubset(ALLOWED_FS_WRITE):
        errors.append("sandbox.permissions.fs_write exceeds allowed set")
    prov = manifest.get("provenance", {})
    for k in ("source_bundle_id", "source_artifact_digest", "forged_artifact_digest"):
        if not prov.get(k):
            errors.append(f"provenance.{k} missing")
    return manifest, errors


def _run_test(cand: Path, test_dir: Path, sandbox_launch, oracle_script: Path,
              output_root: Path) -> dict:
    manifest = json.loads((cand / "manifest.json").read_text())
    ep = manifest["entrypoint"]["command"]
    limits = manifest["sandbox"]["limits"]
    out = output_root / test_dir.name
    out.mkdir(parents=True, exist_ok=True)
    artifact = cand / "implementation" / "artifact"
    run = sandbox_launch(limits, [
        (artifact, "/artifact", True),
        (test_dir, "/input", True),
        (out, "/output", False),
    ], ["python", "/artifact/main.py", "/input/data.csv", "/output"])
    if run["exit_code"] != 0:
        return {"test": test_dir.name, "ok": False,
                "reason": f"entrypoint exit={run['exit_code']}: {run['stderr'][:500]}"}
    oracle = sandbox_launch(limits, [
        (test_dir, "/fixture", True),
        (oracle_script, "/oracle/check.py", True),
        (out, "/output", True),
    ], ["python", "/oracle/check.py", "/fixture", "/output"])
    return {"test": test_dir.name, "ok": oracle["exit_code"] == 0,
            "reason": oracle["stdout"].strip() or oracle["stderr"].strip(),
            "exit_code": oracle["exit_code"]}


def validate(cand_dir: Path, sandbox_launch, oracle_script: Path,
             output_root: Path, forbidden_roots: list[str] | None = None) -> dict:
    cand = Path(cand_dir)
    manifest, errors = _load_candidate(cand)
    checks = []
    if not errors:
        cmd = manifest["entrypoint"]["command"]
        impl_file = cmd[1] if len(cmd) > 1 and cmd[0] in ("python", "python3", "bash", "sh") else cmd[0]
        if not (cand / "implementation" / "artifact" / impl_file).exists():
            errors.append(f"entrypoint file missing: {impl_file}")
        all_text = "\n".join(
            p.read_text(errors="replace") for p in (cand / "implementation" / "artifact").rglob("*") if p.is_file())
        hits = static_scan(all_text, forbidden_roots or [])
        if hits:
            errors.append("task-private references: " + ", ".join(hits))
        for t in sorted((cand / "tests").glob("t*")):
            checks.append(_run_test(cand, t, sandbox_launch, oracle_script, output_root))
        if checks:
            for c in checks:
                if not c["ok"]:
                    errors.append(f"golden test {c['test']} FAIL: {c['reason']}")
        else:
            errors.append("no golden tests present")
    result = {"candidate_id": json.loads((cand / "candidate.json").read_text()).get("candidate_id"),
              "ok": not errors, "errors": errors, "checks": checks,
              "validated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
              .isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    (cand / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
