#!/usr/bin/env python3
"""Phase 9-D.3 live Docker probe: O1 attack matrix against E(D).

Builds a throwaway canonical environment, then replays the Phase 9-D.1
attack set against the immutable execution snapshot and observes what a
real container sees. Honest owner-isolation finding is included (local
store owner == harness user is reported as SAME_OWNER).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from forge.capabilityizer import artifact_digest, bind_evaluation, freeze_candidate_dir
from forge.sandbox import launch as docker_launch
from pilot.adoption_authority_producer import issue_authority
from pilot.registry import AdoptionBlocked, promote
from pilot import runtime_adoption_guard as guard

IMAGE = "python:3.12-slim"
RUNTIME_UID = 65534
CONFIRM = {"operator": "live-probe", "confirm": True}


def sha256_file(path: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_candidate(tmp: pathlib.Path, cand_id: str, name: str, marker: str) -> pathlib.Path:
    cand = tmp / cand_id
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_text(f"print('{marker}')\n")
    forged = artifact_digest(art, ["main.py"])
    (cand / "tests" / "t1").mkdir(parents=True)
    (cand / "tests" / "t1" / "data.csv").write_text("id\n")
    (cand / "tests" / "t1" / "expected.json").write_text("{}")
    manifest = {
        "manifest_version": "0.1",
        "capability": {"name": name, "description": "demo", "version": 1},
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
        "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                    "limits": {"timeout_seconds": 60, "output_bytes": 1048576}},
        "provenance": {
            "source_bundle_id": "bundle-1",
            "source_artifact_digest": "sha256:" + "a" * 64,
            "forged_artifact_digest": forged,
            "forge_timestamp": "2026-08-19T00:00:00Z",
        },
    }
    (cand / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": cand_id, "name": name, "state": "candidate",
         "source_bundle_ids": ["bundle-1"]}, indent=2) + "\n")
    return cand


def canonical_env(tmp: pathlib.Path) -> dict:
    state = tmp / "state"
    registry_root = state / "registry"
    frozen_root = state / "frozen_candidates"
    registry_root.mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, "cand-A", "foo", "ARTIFACT_A")
    frozen = freeze_candidate_dir(cand, frozen_root, namespace="F+",
                                  registry_root=registry_root)
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        {"evaluation_id": "eval-live", "verdict": "PASS",
         "evaluated_at": "2026-08-19T00:00:00Z"},
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM,
                             frozen_root=frozen_root)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote("F+", "foo", cand, evaluation, registry_root,
                    adoption_authority=issued["authority"],
                    frozen_root=frozen_root)
    guard.mark_promoted(registry_root, entry)
    candidate_id = entry["adoption"]["candidate_id"]
    snapshot = frozen_root / "frozen" / candidate_id / "artifact"
    return {
        "registry_root": registry_root,
        "frozen_root": frozen_root,
        "entry": entry,
        "artifact_dir": pathlib.Path(entry["artifact_dir"]),
        "snapshot": snapshot,
        "main": snapshot / "main.py",
        "identity": {
            "candidate_id": candidate_id,
            "candidate_version": entry["adoption"]["candidate_version"],
            "artifact_digest": entry["adoption"]["artifact_digest"],
            "seal_digest": issued["authority"]["seal_digest"],
        },
        "file_sha256": sha256_file(snapshot / "main.py"),
    }


def verify_and_observe(env: dict, tag: str) -> dict:
    report = guard.verify_at_mount(
        env["registry_root"], env["entry"], env["snapshot"],
        expected_digest=env["identity"]["artifact_digest"],
        expected_identity=env["identity"],
        mount_source=env["snapshot"], runtime_uid=RUNTIME_UID)
    assert report["verdict"] == "ALLOW", report
    cmd = ["python", "-c",
           "import hashlib;print(hashlib.sha256(open('/artifact/main.py','rb').read()).hexdigest())"]
    res = docker_launch(IMAGE, [(env["snapshot"], "/artifact", True)], cmd,
                        {"timeout_seconds": 60, "output_bytes": 4096})
    observed = (res["stdout"] or "").strip()
    ok = observed == env["file_sha256"]
    print(json.dumps({"tag": tag, "exit_code": res["exit_code"],
                      "observed_sha256": observed,
                      "expected_sha256": env["file_sha256"], "observed_a": ok}))
    return {"tag": tag, "exit_code": res["exit_code"], "observed_a": ok,
            "observed_sha256": observed, "expected_sha256": env["file_sha256"]}


def main() -> int:
    results = {"attacks": [], "race": None, "post_mount": None,
               "owner_isolation": None, "registry_a_to_b": None}
    with tempfile.TemporaryDirectory(prefix="phase9d3-live-") as td:
        env = canonical_env(pathlib.Path(td))
        snap = env["snapshot"]
        main = env["main"]
        evil_dir = pathlib.Path(td) / "evil_dir"
        evil_dir.mkdir()
        (evil_dir / "main.py").write_text("print('ARTIFACT_B')\n")
        evil_file = pathlib.Path(td) / "evil.py"
        evil_file.write_text("print('ARTIFACT_B')\n")

        same_owner = guard.execution_snapshot_isolation_violations(
            env["frozen_root"], env["identity"]["candidate_id"],
            runtime_uid=os.getuid())
        isolated = guard.execution_snapshot_isolation_violations(
            env["frozen_root"], env["identity"]["candidate_id"],
            runtime_uid=RUNTIME_UID)
        results["owner_isolation"] = {
            "store_owner_uid": snap.stat().st_uid,
            "local_runtime_uid": os.getuid(),
            "deployment_runtime_uid": RUNTIME_UID,
            "same_owner_codes": [v["code"] for v in same_owner],
            "deployment_isolated": isolated == [],
        }

        attacks = [
            ("directory replacement", lambda: os.replace(evil_dir, snap)),
            ("atomic rename", lambda: os.rename(snap, snap.with_name(snap.name + ".old"))),
            ("symlink replacement", lambda: os.symlink(evil_file, snap / "evil.py")),
            ("in-place mutation", lambda: main.write_bytes(b"print('ARTIFACT_B')\n")),
            ("atomic file replacement", lambda: os.replace(evil_file, main)),
        ]
        for tag, attack in attacks:
            try:
                attack()
                results["attacks"].append({"attack": tag, "blocked": False,
                                           "error": "mutation unexpectedly succeeded"})
                print(json.dumps({"attack": tag, "blocked": False}))
            except PermissionError:
                results["attacks"].append({"attack": tag, "blocked": True})
                print(json.dumps({"attack": tag, "blocked": True}))
            obs = verify_and_observe(env, tag)
            if not obs["observed_a"]:
                results["attacks"][-1]["container_observed_a"] = False

        # Registry live artifact A -> B must not affect the execution snapshot.
        (env["artifact_dir"] / "main.py").write_bytes(b"print('ARTIFACT_B')\n")
        obs = verify_and_observe(env, "registry-a-to-b")
        results["registry_a_to_b"] = obs

        # Natural race: same-user mutations are denied by modes/ownership, so
        # every attempt fails and every container still observes A.
        attempts = {"tried": 0, "succeeded": 0}
        stop = threading.Event()

        def attacker() -> None:
            while not stop.is_set():
                for fn in (lambda: main.write_bytes(b"print('ARTIFACT_B')\n"),
                           lambda: os.replace(evil_dir, snap),
                           lambda: os.replace(evil_file, main),
                           lambda: os.symlink(evil_file, snap / "evil.py")):
                    attempts["tried"] += 1
                    try:
                        fn()
                        attempts["succeeded"] += 1
                    except PermissionError:
                        pass

        thread = threading.Thread(target=attacker, daemon=True)
        thread.start()
        race = [verify_and_observe(env, f"race-{i}") for i in range(18)]
        stop.set()
        thread.join(timeout=5)
        results["race"] = {
            "attempts": attempts,
            "containers": len(race),
            "observed_b": sum(1 for r in race if not r["observed_a"]),
            "all_a": all(r["observed_a"] for r in race),
        }

        # Post-mount host mutation while a container is running.
        name = "cbx-9d3-postmount"
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        started = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name, "--network", "none",
             "-v", f"{snap}:/artifact:ro", IMAGE, "sleep", "30"],
            capture_output=True, text=True)
        if started.returncode != 0:
            results["post_mount"] = {"error": started.stderr.strip()}
        else:
            post_results = []
            for tag, attack in attacks:
                try:
                    attack()
                    post_results.append({"attack": tag, "blocked": False})
                except PermissionError:
                    post_results.append({"attack": tag, "blocked": True})
            exec_res = subprocess.run(
                ["docker", "exec", name, "python", "-c",
                 "import hashlib;print(hashlib.sha256(open('/artifact/main.py','rb').read()).hexdigest())"],
                capture_output=True, text=True)
            observed = exec_res.stdout.strip()
            results["post_mount"] = {
                "mutations": post_results,
                "container_observed_a": observed == env["file_sha256"],
                "observed_sha256": observed,
                "expected_sha256": env["file_sha256"],
            }
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    ok = (
        all(a["blocked"] for a in results["attacks"])
        and results["registry_a_to_b"]["observed_a"]
        and results["race"]["all_a"]
        and results["race"]["attempts"]["succeeded"] == 0
        and results["post_mount"] is not None
        and results["post_mount"]["container_observed_a"]
        and all(m["blocked"] for m in results["post_mount"]["mutations"])
    )
    print(json.dumps({"summary": results, "overall_ok": ok}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
