"""M8 - B3 Capabilityizer: Bundle + LLM Proposal + confirm -> Candidate.

Runtime-neutral: consumes VerifiedTaskArtifactBundle + immutable artifacts +
proposal + confirm only. Deterministic transform; static scan rejects
task-private state (original workspace paths / session refs / temp refs).
"""

from __future__ import annotations

import hashlib
import json
import re
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

    forged_digest = sha256_bytes(canonical_json({
        "files": [{"path": "main.py", "digest": sha256_bytes((artifact_dir / "main.py").read_bytes())}],
    }))
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
