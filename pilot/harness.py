#!/usr/bin/env python3
"""M1 - Experiment Harness. EXPERIMENT_ONLY.

F+ single-family rehearsal orchestration:
  codex exec (black box) -> oracle -> codex-adapter build -> Bundle
  -> shared generation input -> LLM proposal -> B2 skill freeze / B3 pipeline
  -> future invoke -> run records -> cost/NV -> rehearsal gate.

Boundary: this module NEVER parses Codex native format. Rollouts are passed
byte-for-byte to `forge.codex_adapter.main` CLI. It consumes only run metadata,
Bundle outputs and arm-specific results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from forge.sandbox import launch as docker_launch  # noqa: E402
from forge.capabilityizer import capabilityize, CapabilityizeError, static_scan  # noqa: E402
from forge.validator import validate as validate_candidate  # noqa: E402
from forge.evaluator import evaluate as evaluate_candidate  # noqa: E402
import pilot.cost as cost_mod  # noqa: E402
import pilot.generate as gen_mod  # noqa: E402
import pilot.registry as registry  # noqa: E402
import pilot.run_record as rr  # noqa: E402
import pilot.adoption_authority_producer as producer  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _dir_digest(directory: Path) -> str:
    files = {p.relative_to(directory).as_posix(): _file_sha256(p)
             for p in sorted(directory.rglob("*")) if p.is_file()}
    return _sha256(_canonical({"files": files}))


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _ref_stats(csv_text: str) -> dict:
    """Reference implementation of the F+ cleaning rules (used by oracle self-check)."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    seen, keep = set(), []
    for r in rows:
        key = tuple(sorted(r.items()))
        if key in seen:
            continue
        seen.add(key)
        if not (r["id"].strip() and r["customer"].strip() and r["category"].strip()):
            continue
        try:
            r["date"] = "-".join(f"{int(x):02d}" for x in r["date"].replace("/", "-").split("-"))
        except Exception:
            continue
        r["amount"] = r["amount"].strip() or "0"
        keep.append(r)
    keep.sort(key=lambda r: int(r["id"]))
    amounts = [float(r["amount"]) for r in keep]
    return {
        "total_rows": len(keep),
        "total_amount": round(sum(amounts), 2),
        "unique_customers": len({r["customer"] for r in keep}),
        "mean_amount": round(sum(amounts) / len(amounts), 2),
    }


class Harness:
    def __init__(self, force: bool = False):
        self.force = force
        self.cfg = json.loads((ROOT / "config.json").read_text())
        self.manifest = json.loads((ROOT / "manifest.json").read_text())
        self.family = self.manifest["families"][0]
        self.state = ROOT / "state"
        self.bundle_store = self.state / "bundle_store"
        self.records_path = self.state / "run_records.jsonl"
        self.events_path = self.state / "cost_events.jsonl"
        self.oracle_script = ROOT / self.family["oracle"]["script"]
        self.registry_root = self.state / "registry"
        for d in (self.state, self.bundle_store, self.registry_root):
            d.mkdir(parents=True, exist_ok=True)
        self.runtime_version = self._codex_version()
        self.model_config_hash = _sha256(_canonical({
            "provider": self.cfg["model"]["provider"], "model": self.cfg["model"]["name"],
            "reasoning_effort": self.cfg["model"]["reasoning_effort"],
            "temperature": self.cfg["model"]["temperature"], "seed": self.cfg["model"]["seed"],
            "timeout_seconds": self.cfg["limits"]["timeout_seconds"],
            "output_bytes": self.cfg["limits"]["output_bytes"],
        }))
        self._sandbox_events: list[dict] = []
        self._sandbox_phase = "sandbox"

    # ------------------------------------------------------------------ utils
    def _codex_version(self) -> str:
        try:
            out = subprocess.run(["codex", "--version"], capture_output=True, text=True,
                                 timeout=10).stdout.splitlines()
            for line in out:
                line = line.strip()
                if line.startswith("codex-cli"):
                    return line.split()[1]
            return "unknown"
        except Exception:
            return "unknown"

    def _check_docker(self) -> None:
        proc = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("docker daemon unavailable; sandbox fail-closed: "
                               + proc.stderr.strip())

    def _task(self, tid: str) -> dict:
        for group in ("formation_tasks", "future_tasks", "evaluation_tasks"):
            for t in self.family.get(group, []):
                if t["task_id"] == tid:
                    return t
        raise KeyError(tid)

    def _fixture(self, tid: str) -> Path:
        return ROOT / self._task(tid)["fixture_ref"]

    def _new_run_id(self) -> str:
        return "run-" + uuid.uuid4().hex[:12]

    def _next_order(self) -> int:
        return len(rr.load_records(self.records_path)) + 1

    def _codex_env(self, codex_home: Path) -> dict:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        return env

    def _make_codex_home(self, run_dir: Path, skills: list[Path] | None = None) -> Path:
        src_raw = self.cfg.get("codex_home_source", "~/.codex")
        src = Path(os.path.expandvars(src_raw)).expanduser()
        if "${" in src_raw:
            src = Path.home() / ".codex"
        home = run_dir / "codex_home"
        home.mkdir(parents=True, exist_ok=True)
        for name in ("config.toml", "auth.json"):
            shutil.copyfile(src / name, home / name)
        for skill_dir in skills or []:
            dst = home / "skills" / skill_dir.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(skill_dir, dst)
        return home

    def _prepare_run(self, run_dir: Path, fixture: Path, task_id: str, arm: str,
                     skills: list[Path] | None = None) -> dict:
        work = run_dir / "work"
        (work / "data").mkdir(parents=True)
        shutil.copyfile(fixture / "input" / "data.csv", work / "data" / "input.csv")
        baseline = {}
        for p in work.rglob("*"):
            if p.is_file():
                baseline[p.relative_to(work).as_posix()] = _file_sha256(p)
        codex_home = self._make_codex_home(run_dir, skills)
        meta = {
            "run_id": run_dir.name, "task_id": task_id, "arm": arm, "family": "F+",
            "model": self.cfg["model"], "model_config_hash": self.model_config_hash,
            "runtime_version": self.runtime_version, "source_execution_id": str(uuid.uuid4()),
            "started_at": _now(), "ended_at": None, "workspace": str(work),
            "baseline_files": baseline,
        }
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2))
        return meta

    def _find_rollout(self, codex_home: Path) -> Path | None:
        hits = sorted(codex_home.glob("sessions/*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime)
        return hits[-1] if hits else None

    def _run_codex(self, run_dir: Path, prompt: str) -> dict:
        work = run_dir / "work"
        codex_home = run_dir / "codex_home"
        last = run_dir / "last.txt"
        log = run_dir / "exec.log"
        m = self.cfg["model"]
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write",
               "-c", f"model_provider={m['provider']}", "-c", f"model={m['name']}",
               "-c", f"model_reasoning_effort={m['reasoning_effort']}",
               "-o", str(last), prompt]
        started = time.monotonic()
        timed_out = False
        try:
            with log.open("w") as fh:
                proc = subprocess.run(cmd, cwd=work, env=self._codex_env(codex_home),
                                      timeout=self.cfg["limits"]["timeout_seconds"],
                                      stdout=fh, stderr=subprocess.STDOUT)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = None
            timed_out = True
        elapsed = round(time.monotonic() - started, 3)
        rollout = self._find_rollout(codex_home)
        rollout_dst = None
        if rollout:
            rollout_dst = run_dir / "rollout.jsonl"
            shutil.copyfile(rollout, rollout_dst)
        last_msg = ""
        if last.exists():
            last_msg = last.read_text().strip()
        meta = json.loads((run_dir / "run.json").read_text())
        meta["ended_at"] = _now()
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2))
        return {"exit_code": exit_code, "timed_out": timed_out, "elapsed_s": elapsed,
                "rollout": rollout_dst, "last_message": last_msg}

    def _oracle(self, task: dict, output_dir: Path) -> dict:
        fixture = self._fixture(task["task_id"])
        limits = task.get("limits", self.cfg["limits"])
        verdicts = []
        for _ in range(2):  # stability: same check twice
            res = docker_launch(self.cfg["sandbox"]["image"], [
                (fixture, "/fixture", True),
                (self.oracle_script, "/oracle/check.py", True),
                (output_dir, "/output", True),
            ], task["oracle"]["command"] + ["/fixture", "/output"], limits)
            verdicts.append({"verdict": "PASS" if res["exit_code"] == 0 else "FAIL",
                             "exit_code": res["exit_code"],
                             "evidence": (res["stdout"] or res["stderr"]).strip()[:2000]})
        stable = verdicts[0]["verdict"] == verdicts[1]["verdict"]
        return {"verdict": verdicts[0]["verdict"], "reason": verdicts[0]["evidence"],
                "stable": stable, "runs": verdicts}

    def _sandbox_launch(self, limits: dict, mounts: list, cmd: list) -> dict:
        res = docker_launch(self.cfg["sandbox"]["image"], mounts, cmd, limits)
        self._sandbox_events.append({"kind": self._sandbox_phase,
                                     "sandbox_min": round(res["elapsed_s"] / 60.0, 6),
                                     "sandbox_id": res["sandbox_id"],
                                     "exit_code": res["exit_code"]})
        return res

    def _base_record(self, run_dir: Path, meta: dict, task_id: str, arm: str,
                     started_at: str) -> dict:
        return {
            "run_id": meta["run_id"], "task_id": task_id, "family": "F+", "arm": arm,
            "formation_id": "F+-rehearsal-1", "model": self.cfg["model"]["name"],
            "model_config_hash": self.model_config_hash,
            "seed": self.cfg["model"]["seed"], "order": self._next_order(),
            "sandbox_id": "codex-workspace-write", "started_at": started_at,
            "ended_at": _now(), "oracle": None, "bundle_id": None, "bundle_ids": None,
            "skill_used": None, "capability_used": None, "invoke_result": None,
            "trap": False, "regression": False, "false_promotion": False, "cost": None,
            "generation_input_digest": None, "proposal_digest": None,
            "runtime_metrics": None, "output_dir": str(run_dir / "work"),
            "last_message": "", "sandbox_elapsed_s": None, "notes": None,
            "treatment": None,
        }

    def _skill_treatment(self, run_dir: Path, skill_dir: Path, name: str) -> dict:
        """Deterministic harness-level injection record: mounted copy + digest match."""
        mounted = run_dir / "codex_home" / "skills" / name
        mounted_digest = _dir_digest(mounted)
        expected_digest = _dir_digest(skill_dir)
        evidence = {
            "kind": "skill_injection",
            "injected_by": "harness",
            "mounted_path": str(mounted),
            "source_path": str(skill_dir),
            "mounted_digest": mounted_digest,
            "expected_digest": expected_digest,
            "digest_match": mounted_digest == expected_digest,
        }
        return {"type": "skill", "used": evidence["digest_match"], "ref": name,
                "digest": mounted_digest, "evidence": evidence}

    def _write_event(self, event: dict) -> None:
        existing = {e.get("sandbox_id") for e in self._load_events()}
        sandbox_id = event.get("sandbox_id")
        if sandbox_id is not None and sandbox_id in existing:
            return
        with self.events_path.open("a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    def _load_events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        return [json.loads(l) for l in self.events_path.read_text().splitlines() if l.strip()]

    def _formation_bundles(self) -> list[dict]:
        records = rr.load_records(self.records_path)
        formation_ids = {t["task_id"] for t in self.family["formation_tasks"]}
        out = []
        for rec in records:
            if rec["arm"] in ("b2", "b3") and rec["task_id"] in formation_ids and rec["bundle_id"]:
                bdir = self.bundle_store / "bundles" / rec["bundle_id"]
                bundle = json.loads((bdir / "bundle.json").read_text())
                out.append({
                    "bundle_id": rec["bundle_id"], "bundle_dir": str(bdir),
                    "bundle_digest": bundle["provenance"]["bundle_digest"],
                    "task_id": rec["task_id"], "arm": rec["arm"],
                    "cwd": (bundle["environment"] or {}).get("cwd"),
                    "source_execution_id": (bundle["identity"] or {}).get("source_execution_id"),
                    "files": bundle["artifacts"]["files"],
                })
        return out

    def _adapter_build(self, run_dir: Path, meta: dict) -> dict:
        out = run_dir / "run_artifacts.json"
        cmd = ["python", "-m", "forge.codex_adapter.main", "build",
               "--rollout", str(run_dir / "rollout.jsonl"),
               "--workspace", str(run_dir / "work"),
               "--run-meta", str(run_dir / "run.json"),
               "--store", str(self.bundle_store),
               "--out", str(out)]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO / "src")
        proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"adapter build failed: {proc.stdout}{proc.stderr}")
        return json.loads(out.read_text())

    def _adapter_metrics(self, run_dir: Path) -> dict:
        out = run_dir / "runtime_metrics.json"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO / "src")
        proc = subprocess.run(
            ["python", "-m", "forge.codex_adapter.main", "metrics",
             "--rollout", str(run_dir / "rollout.jsonl"), "--out", str(out)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"adapter metrics failed: {proc.stdout}{proc.stderr}")
        return json.loads(out.read_text())["runtime_metrics"]

    # ------------------------------------------------------------------ phases
    def phase_oracle_check(self) -> dict:
        """Manifest schema + reference rules + golden/tampered oracle behavior."""
        errors = []
        fam = self.family
        for group in ("formation_tasks", "future_tasks", "evaluation_tasks"):
            for t in fam.get(group, []):
                required = ("task_id", "fixture_ref") + (("oracle",) if group != "evaluation_tasks" else ())
                for k in required:
                    if k not in t:
                        errors.append(f"{group}/{t.get('task_id')} missing {k}")
                fixture = self._fixture(t["task_id"])
                expected = json.loads((fixture / "expected.json").read_text())
                computed = _ref_stats((fixture / "input" / "data.csv").read_text())
                if computed != expected:
                    errors.append(f"{t['task_id']}: reference rules mismatch "
                                  f"expected={expected} computed={computed}")
        if errors:
            raise RuntimeError("manifest/oracle self-check FAIL: " + "; ".join(errors))
        # golden + tampered oracle behavior on cal-1
        fixture = self._fixture("fplus-cal-1")
        expected = json.loads((fixture / "expected.json").read_text())
        with temp_outdir() as tmp:
            golden_report = "\n".join(f"{k}: {v}" for k, v in expected.items())
            (tmp / "report.md").write_text(golden_report + "\n")
            ok = subprocess.run(["python", str(self.oracle_script), str(fixture), str(tmp)],
                                capture_output=True).returncode == 0
            bad = json.loads(json.dumps(expected))
            bad["total_rows"] = int(bad["total_rows"]) + 1
            (tmp / "report.md").write_text("\n".join(f"{k}: {v}" for k, v in bad.items()) + "\n")
            fail = subprocess.run(["python", str(self.oracle_script), str(fixture), str(tmp)],
                                  capture_output=True).returncode != 0
        result = {"schema_ok": not errors, "reference_rules_match": True,
                  "golden_passes": ok, "tampered_fails": fail,
                  "ok": not errors and ok and fail}
        (self.state / "oracle_check.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    def phase_formation(self, arm: str) -> list[str]:
        self._check_docker()
        run_ids = []
        for task in self.family["formation_tasks"]:
            tid = task["task_id"]
            existing = [r for r in rr.load_records(self.records_path)
                        if r["arm"] == arm and r["task_id"] == tid and r.get("bundle_id")]
            if existing and not self.force:
                run_ids.append(existing[0]["run_id"])
                continue
            run_id = self._new_run_id()
            run_dir = self.state / "runs" / run_id
            run_dir.mkdir(parents=True)
            started = _now()
            meta = self._prepare_run(run_dir, self._fixture(tid), tid, arm)
            run = self._run_codex(run_dir, self.family["prompt_template"])
            oracle = self._oracle(task, run_dir / "work")
            rec = self._base_record(run_dir, meta, tid, arm, started)
            rec["ended_at"] = _now()
            rec["oracle"] = oracle
            rec["sandbox_elapsed_s"] = run["elapsed_s"]
            rec["last_message"] = run["last_message"]
            rec["notes"] = [] if run["exit_code"] == 0 else [
                f"codex exit={run['exit_code']}" + (" timed_out" if run["timed_out"] else "")]
            if run["exit_code"] != 0:
                rec["oracle"] = {"verdict": "ERROR", "reason": "codex exec failed",
                                 "stable": False, "runs": []}
            else:
                artifacts = self._adapter_build(run_dir, meta)
                rec["bundle_id"] = artifacts["bundle_id"]
                rec["runtime_metrics"] = artifacts["runtime_metrics"]
                rec["notes"].append("bundle_validation_ok=" + str(artifacts["validation"]["ok"]))
                if not artifacts["validation"]["ok"]:
                    rec["notes"].append("bundle_errors=" + json.dumps(artifacts["validation"]["errors"]))
            rr.write_record(self.records_path, rec)
            run_ids.append(run_id)
        return run_ids

    def phase_generation(self) -> dict:
        if (self.state / "generation_meta.json").exists() and not self.force:
            return json.loads((self.state / "generation_meta.json").read_text())
        bundles = self._formation_bundles()
        if len(bundles) < 4:
            raise RuntimeError(f"need 4 formation bundles, have {len(bundles)}")
        bundles.sort(key=lambda b: (b["arm"], b["task_id"]))
        samples = []
        for b in bundles:
            sample = {}
            for f in b["files"]:
                if f["path"] in ("data/input.csv", "data/cleaned.csv", "report.md") and f.get("digest"):
                    content = (Path(b["bundle_dir"]) / f["content_ref"]).read_bytes().decode("utf-8", "replace")
                    sample[f["path"]] = content
            samples.append({"bundle_id": b["bundle_id"], "task_id": b["task_id"], "arm": b["arm"],
                            "sample": sample})
        gen_input = {
            "schema_version": "generation_input_v1", "family": "F+",
            "model": self.cfg["model"], "model_config_hash": self.model_config_hash,
            "prompt_template": self.family["prompt_template"],
            "bundles": bundles, "samples": samples, "generated_at": _now(),
        }
        gen_bytes = _canonical(gen_input)
        gen_digest = _sha256(gen_bytes)
        (self.state / "generation_input.json").write_bytes(gen_bytes)
        (self.state / "generation_input.sha256").write_text(gen_digest)

        ws = self.state / "generation" / "ws"
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True)
        home = self._make_codex_home(self.state / "generation")
        (ws / "generation_input.json").write_bytes(gen_bytes)
        (ws / "proposal_schema.json").write_text(json.dumps(gen_mod.PROPOSAL_SCHEMA, indent=2))
        prompt = gen_mod.PROMPT
        attempts = 0  # ponytail: fixed 2 retries; track retry cost when LLM spend matters
        while True:
            exit_code = gen_mod.run(home, ws, ws / "proposal_schema.json", self.cfg["model"],
                                    self.cfg["limits"]["timeout_seconds"],
                                    self.state / "generation" / "last.txt",
                                    self.state / "generation" / "exec.log", prompt=prompt)
            rollout = self._find_rollout(home)
            if rollout:
                shutil.copyfile(rollout, self.state / "generation" / "rollout.jsonl")
            if exit_code != 0:
                raise RuntimeError(f"LLM proposal generation failed (codex exit {exit_code})")
            proposal_path = ws / "llm_proposal.json"
            if not proposal_path.exists():
                last = (self.state / "generation" / "last.txt").read_text().strip()
                proposal = json.loads(last)
                (self.state / "llm_proposal.json").write_text(json.dumps(proposal, indent=2) + "\n")
            else:
                shutil.copyfile(proposal_path, self.state / "llm_proposal.json")
            proposal = json.loads((self.state / "llm_proposal.json").read_text())
            errors = gen_mod.validate_proposal(proposal)
            if errors:
                raise RuntimeError("invalid llm_proposal: " + "; ".join(errors))
            hits = static_scan(
                "\n".join(list(proposal["implementation"].values()) + [proposal["skill_md"]]),
                [b.get("cwd") for b in bundles if b.get("cwd")])
            if not hits:
                break
            if attempts >= 2:
                raise RuntimeError("LLM proposal rejected by capabilityizer after retries: "
                                   + ", ".join(hits))
            attempts += 1
            prompt = gen_mod.PROMPT + (
                "\n\nYour previous proposal was REJECTED because it references task-private state: "
                + ", ".join(hits) + ". Rewrite llm_proposal.json without any of these strings; "
                + "use generic placeholders like <input.csv> and <outdir> in examples.")
        proposal_digest = _file_sha256(self.state / "llm_proposal.json")
        (self.state / "llm_proposal.sha256").write_text(proposal_digest)
        metrics = None
        if (self.state / "generation" / "rollout.jsonl").exists():
            gdir = self.state / "generation"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO / "src")
            proc = subprocess.run(
                ["python", "-m", "forge.codex_adapter.main", "metrics",
                 "--rollout", str(gdir / "rollout.jsonl"), "--out", str(gdir / "runtime_metrics.json")],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                metrics = json.loads((gdir / "runtime_metrics.json").read_text())["runtime_metrics"]
        self._write_event({"kind": "generation", "arm": "b2+b3",
                           "runtime_metrics": metrics, "note": "one shared LLM call"})
        bundle_ids = [b["bundle_id"] for b in bundles]
        formation_ids = {t["task_id"] for t in self.family["formation_tasks"]}
        for rec in rr.load_records(self.records_path):
            if rec["arm"] in ("b2", "b3") and rec["task_id"] in formation_ids:
                rr.update_record(self.records_path, rec["run_id"],
                                 generation_input_digest=gen_digest,
                                 proposal_digest=proposal_digest, bundle_ids=bundle_ids)
        meta = {"generation_input_digest": gen_digest, "proposal_digest": proposal_digest,
                "bundle_ids": bundle_ids, "llm_calls": attempts + 1, "runtime_metrics": metrics}
        (self.state / "generation_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        return meta

    def phase_b2_freeze(self) -> dict:
        if (self.state / "skill_ref.json").exists() and not self.force:
            return json.loads((self.state / "skill_ref.json").read_text())
        proposal = json.loads((self.state / "llm_proposal.json").read_text())
        name = proposal["name"]
        frozen = ROOT / "skills" / "frozen" / "F+" / name
        if frozen.exists():
            shutil.rmtree(frozen)
        (frozen / "scripts").mkdir(parents=True)
        (frozen / "SKILL.md").write_text(proposal["skill_md"])
        (frozen / "scripts" / "main.py").write_text(proposal["implementation"]["main.py"])
        files = {p.relative_to(frozen).as_posix(): _file_sha256(p)
                 for p in frozen.rglob("*") if p.is_file()}
        digest = _sha256(_canonical({"files": files}))
        skill_ref = {
            "name": name, "path": str(frozen), "digest": digest,
            "frozen_at": _now(), "human_minutes": 0, "proposal_digest": _file_sha256(
                self.state / "llm_proposal.json"),
        }
        (self.state / "skill_ref.json").write_text(json.dumps(skill_ref, indent=2) + "\n")
        self._write_event({"kind": "freeze", "arm": "b2", "human_min": 0, "note": name})
        return skill_ref

    def phase_b3_build(self) -> dict:
        if (self.state / "b3_entry.json").exists() and not self.force:
            entry = registry.discover(self.registry_root, "F+",
                                      json.loads((self.state / "b3_entry.json").read_text())["name"])
            cand_dir = self.state / "candidates" / "F+" / json.loads(
                (self.state / "b3_entry.json").read_text())["name"]
            return {"candidate": {"candidate_dir": str(cand_dir)},
                    "validation": json.loads((cand_dir / "validation.json").read_text()),
                    "evaluation": entry["evaluation"], "registry_entry": entry}
        bundles = self._formation_bundles()
        proposal = json.loads((self.state / "llm_proposal.json").read_text())
        confirm = json.loads((ROOT / "confirm.json").read_text())
        golden = self.state / "golden"
        if golden.exists():
            shutil.rmtree(golden)
        for i, tid in enumerate(("fplus-cal-1", "fplus-cal-2"), start=1):
            fx = self._fixture(tid)
            td = golden / f"t{i}"
            td.mkdir(parents=True)
            shutil.copyfile(fx / "input" / "data.csv", td / "data.csv")
            shutil.copyfile(fx / "expected.json", td / "expected.json")
        cand_out = self.state / "candidates" / "F+"
        stale_cand = cand_out / proposal["name"]
        if stale_cand.exists():
            shutil.rmtree(stale_cand)  # stale from a previous failed build; no registry entry exists
        try:
            made = capabilityize(bundles, proposal, confirm, golden, cand_out)
        except CapabilityizeError as e:
            raise RuntimeError(f"capabilityize FAIL: {e}")
        cand = Path(made["candidate_dir"])
        self._sandbox_phase = "validation"
        validation = validate_candidate(
            cand, self._sandbox_launch, self.oracle_script,
            self.state / "sandbox_out" / "validation",
            forbidden_roots=[b.get("cwd") for b in bundles])
        if not validation["ok"]:
            raise RuntimeError("B3 validation FAIL: " + "; ".join(validation["errors"]))
        self._sandbox_phase = "evaluation"
        evaluation = evaluate_candidate(
            cand, self._sandbox_launch, self.oracle_script,
            self.state / "sandbox_out" / "evaluation",
            novel_fixtures=[("fplus-novel", self._fixture("fplus-novel"))],
            independent_fixtures=[("fplus-novel2", self._fixture("fplus-novel2"))])
        name = proposal["name"]
        if evaluation["verdict"] == "PASS":
            old_entry = self.registry_root / "F+" / f"{name}.json"
            if self.force and old_entry.exists():
                old_artifact = json.loads(old_entry.read_text()).get("artifact_dir")
                old_entry.unlink()
                if old_artifact:
                    shutil.rmtree(old_artifact, ignore_errors=True)
            issued = producer.issue_authority(
                self.registry_root, cand, evaluation, confirm=confirm)
            if issued["verdict"] != "AUTHORITY_ISSUED":
                raise RuntimeError(
                    "B3 authority issuance BLOCKED: "
                    + json.dumps(issued["violations"], ensure_ascii=False))
            entry = registry.promote(
                "F+", name, cand, evaluation, self.registry_root,
                adoption_authority=issued["authority"])
            (self.state / "b3_entry.json").write_text(
                json.dumps({"name": name, "capability_id": entry["capability_id"]}, indent=2) + "\n")
        else:
            entry = registry.reject("F+", name, cand, evaluation, self.registry_root)
            raise RuntimeError("B3 evaluation FAIL; capability rejected")
        for ev in self._sandbox_events:
            self._write_event(ev)
        return {"candidate": made, "validation": validation, "evaluation": evaluation,
                "registry_entry": entry}

    def phase_b1_freeze(self) -> dict:
        """B1: freeze operator-curated skill -> b1_skill_ref.json (READY/BLOCKED record)."""
        cfg_path = ROOT / "b1_curated_skill.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        name = cfg.get("name")
        src = ROOT / "skills" / "curated" / "F+" / name if name else None
        if not name or not src or not (src / "SKILL.md").exists() \
                or cfg.get("human_minutes") is None:
            blocked = {"status": "BLOCKED",
                       "reason": "pilot/b1_curated_skill.json with name + human_minutes "
                                 "and pilot/skills/curated/F+/<name>/SKILL.md required"}
            (self.state / "b1_readiness.json").write_text(json.dumps(blocked, indent=2) + "\n")
            return blocked
        if (self.state / "b1_skill_ref.json").exists() and not self.force:
            return json.loads((self.state / "b1_skill_ref.json").read_text())
        frozen = ROOT / "skills" / "frozen" / "B1" / name
        if frozen.exists():
            shutil.rmtree(frozen)
        shutil.copytree(src, frozen)
        skill_ref = {
            "name": name, "path": str(frozen), "digest": _dir_digest(frozen),
            "frozen_at": _now(), "human_minutes": cfg["human_minutes"],
        }
        (self.state / "b1_skill_ref.json").write_text(json.dumps(skill_ref, indent=2) + "\n")
        ready = {"status": "READY", "skill_ref": skill_ref}
        (self.state / "b1_readiness.json").write_text(json.dumps(ready, indent=2) + "\n")
        self._write_event({"kind": "freeze", "arm": "b1",
                           "human_min": cfg["human_minutes"], "note": name})
        return ready

    def phase_future(self, arm: str) -> list[str]:
        self._check_docker()
        run_ids = []
        if arm == "b0":
            skill_dir = None
            name = None
        elif arm == "b1":
            ref = json.loads((self.state / "b1_skill_ref.json").read_text())
            skill_dir = Path(ref["path"])
            name = ref["name"]
        elif arm == "b2":
            skill_ref = json.loads((self.state / "skill_ref.json").read_text())
            skill_dir = Path(skill_ref["path"])
            name = skill_ref["name"]
        elif arm == "b3":
            entry_meta = json.loads((self.state / "b3_entry.json").read_text())
            entry = registry.discover(self.registry_root, "F+", entry_meta["name"])
            if entry is None:
                raise RuntimeError("no promoted capability for B3 future runs")
            name = entry["name"]
        else:
            raise RuntimeError(f"unknown arm {arm}")
        for task in self.family["future_tasks"]:
            tid = task["task_id"]
            existing = [r for r in rr.load_records(self.records_path)
                        if r["arm"] == arm and r["task_id"] == tid]
            if existing and not self.force:
                run_ids.append(existing[0]["run_id"])
                continue
            run_id = self._new_run_id()
            run_dir = self.state / "runs" / run_id
            run_dir.mkdir(parents=True)
            started = _now()
            skills = [skill_dir] if arm in ("b1", "b2") else None
            meta = self._prepare_run(run_dir, self._fixture(tid), tid, arm, skills)
            rec = self._base_record(run_dir, meta, tid, arm, started)
            if arm == "b0":
                run = self._run_codex(run_dir, self.family["prompt_template"])
                oracle = self._oracle(task, run_dir / "work")
                rec["oracle"] = oracle
                rec["sandbox_elapsed_s"] = run["elapsed_s"]
                rec["last_message"] = run["last_message"]
                rec["treatment"] = {"type": "none", "used": False,
                                    "ref": None, "digest": None, "evidence": None}
                rec["notes"] = [] if run["exit_code"] == 0 else [f"codex exit={run['exit_code']}"]
                if run["exit_code"] == 0 and run["rollout"]:
                    rec["runtime_metrics"] = self._adapter_metrics(run_dir)
                else:
                    rec["oracle"] = {"verdict": "ERROR", "reason": "codex exec failed",
                                     "stable": False, "runs": []}
            elif arm in ("b1", "b2"):
                prompt = f"Use the skill named {name}. Read its SKILL.md and follow it.\n\n" \
                         + self.family["prompt_template"]
                run = self._run_codex(run_dir, prompt)
                oracle = self._oracle(task, run_dir / "work")
                rec["oracle"] = oracle
                rec["sandbox_elapsed_s"] = run["elapsed_s"]
                rec["last_message"] = run["last_message"]
                treatment = self._skill_treatment(run_dir, skill_dir, name)
                rec["treatment"] = treatment
                rec["skill_used"] = treatment["used"]
                rec["notes"] = [] if run["exit_code"] == 0 else [f"codex exit={run['exit_code']}"]
                if run["exit_code"] == 0 and run["rollout"]:
                    rec["runtime_metrics"] = self._adapter_metrics(run_dir)
                else:
                    rec["oracle"] = {"verdict": "ERROR", "reason": "codex exec failed",
                                     "stable": False, "runs": []}
            elif arm == "b3":
                out = run_dir / "output"
                out.mkdir()
                artifact_dir = Path(entry["artifact_dir"])
                artifact_digest = _dir_digest(artifact_dir)
                invoke = docker_launch(self.cfg["sandbox"]["image"], [
                    (artifact_dir, "/artifact", True),
                    (self._fixture(tid) / "input", "/input", True),
                    (out, "/output", False),
                ], ["python", "/artifact/main.py", "/input/data.csv", "/output"],
                    task.get("limits", self.cfg["limits"]))
                oracle = self._oracle(task, out)
                rec["oracle"] = oracle
                rec["output_dir"] = str(out)
                rec["sandbox_id"] = invoke["sandbox_id"]
                rec["sandbox_elapsed_s"] = invoke["elapsed_s"]
                rec["capability_used"] = entry["capability_id"]
                rec["invoke_result"] = {"exit_code": invoke["exit_code"],
                                        "stdout": invoke["stdout"].strip()[:500],
                                        "stderr": invoke["stderr"].strip()[:500]}
                evidence = {
                    "kind": "capability_invoke",
                    "capability_id": entry["capability_id"],
                    "artifact_dir": str(artifact_dir),
                    "artifact_digest": artifact_digest,
                    "sandbox_id": invoke["sandbox_id"],
                    "command": ["python", "/artifact/main.py", "/input/data.csv", "/output"],
                    "invoke_result": rec["invoke_result"],
                }
                rec["treatment"] = {"type": "capability", "used": True,
                                    "ref": entry["capability_id"], "digest": artifact_digest,
                                    "evidence": evidence}
                rec["notes"] = [] if invoke["exit_code"] == 0 else ["capability invoke failed"]
            rec["ended_at"] = _now()
            rr.write_record(self.records_path, rec)
            run_ids.append(run_id)
        return run_ids

    def phase_cost_report(self) -> dict:
        records = rr.load_records(self.records_path)
        events = self._load_events()
        cost = cost_mod.collect(records, self.cfg["prices"], self.family,
                                events, self.family["values"])
        (self.state / "cost.json").write_text(json.dumps(cost, indent=2) + "\n")
        nv_report = {"schema_version": "nv_report_v1", "nv": cost["nv"],
                     "sensitivity": cost["sensitivity"],
                     "value_sensitive": cost["value_sensitive"],
                     "note": "F+ rehearsal only; B0 baseline not run (user gate scope)"}
        (self.state / "nv_report.json").write_text(json.dumps(nv_report, indent=2) + "\n")
        for rec in records:
            rr.update_record(self.records_path, rec["run_id"],
                             cost={"usd": cost["per_run_usd"].get(rec["run_id"], 0.0)})
        gate = self._gate_report(records, cost)
        (self.state / "fplus_rehearsal_gate.json").write_text(json.dumps(gate, indent=2) + "\n")
        return gate

    def _gate_report(self, records: list[dict], cost: dict) -> dict:
        formation_ids = {t["task_id"] for t in self.family["formation_tasks"]}
        future_ids = {t["task_id"] for t in self.family["future_tasks"]}
        formation = [r for r in records if r["arm"] in ("b2", "b3") and r["task_id"] in formation_ids]
        future = [r for r in records if r["task_id"] in future_ids]
        b1_future = [r for r in future if r["arm"] == "b1"]
        b2_future = [r for r in future if r["arm"] == "b2"]
        b3_future = [r for r in future if r["arm"] == "b3"]
        gen = json.loads((self.state / "generation_meta.json").read_text()) \
            if (self.state / "generation_meta.json").exists() else {}
        skill_ref = json.loads((self.state / "skill_ref.json").read_text()) \
            if (self.state / "skill_ref.json").exists() else {}
        bundles = self._formation_bundles()
        entry = None
        if skill_ref:
            entry = registry.discover(self.registry_root, "F+", skill_ref["name"])

        def verdict(ok: bool, detail: str) -> dict:
            return {"status": "PASS" if ok else "FAIL", "detail": detail}

        p1 = all(r.get("oracle", {}).get("verdict") in ("PASS", "FAIL") and r["oracle"].get("stable")
                 for r in formation) and len(formation) == 4
        p2 = len(bundles) == 4 and all(b["bundle_id"] for b in bundles)
        p3 = len({r.get("generation_input_digest") for r in formation}) == 1 \
            and len({r.get("proposal_digest") for r in formation}) == 1 \
            and all(set((r.get("bundle_ids") or [])) == {b["bundle_id"] for b in bundles} for r in formation)
        p4 = bool(skill_ref.get("digest"))
        p5 = bool((self.state / "candidates" / "F+" / skill_ref.get("name", "") / "manifest.json").exists()) \
            if skill_ref else False
        p6 = bool(entry and entry["state"] == "promoted" and entry["evaluation"]["verdict"] == "PASS")
        p7 = len(b2_future) == 2 and len(b3_future) == 2 \
            and len(b1_future) == 2 \
            and all(r.get("oracle", {}).get("verdict") == "PASS"
                    for r in b1_future + b2_future + b3_future)
        p8 = all(not rr.validate_record(r) for r in records) \
            and (self.state / "cost.json").exists() and (self.state / "nv_report.json").exists()
        attribution = {}
        for r in b1_future + b2_future + b3_future:
            errors = rr.validate_treatment(r)
            attribution[r["run_id"]] = {
                "arm": r["arm"], "task_id": r["task_id"],
                "status": "VALID" if not errors else "INVALID_TREATMENT",
                "errors": errors, "treatment": r.get("treatment"),
            }
        p9 = len(attribution) == 6 and all(v["status"] == "VALID" for v in attribution.values())

        proofs = {
            "1_two_formation_tasks_deterministic": verdict(p1, "4 formation runs, oracle verdicts stable"),
            "2_two_formation_tasks_wrapped_in_bundles": verdict(p2, f"{len(bundles)} sealed bundles"),
            "3_b2_b3_shared_generation_input": verdict(p3, "digest equality + 4 bundle refs on all formation records"),
            "4_b2_generates_one_frozen_skill": verdict(p4, skill_ref.get("name", "missing")),
            "5_b3_generates_one_candidate": verdict(p5, "candidate manifest present"),
            "6_b3_validation_evaluation_promotion": verdict(p6, "validation/evaluation PASS + promoted"),
            "7_skill_capability_invoke_on_future_tasks": verdict(
                p7, f"{len(b1_future)} B1 + {len(b2_future)} B2 + {len(b3_future)} B3 future PASS"),
            "8_run_metrics_in_unified_run_record": verdict(p8, f"{len(records)} complete records + cost/NV"),
            "9_treatment_attribution": verdict(p9, "all future runs carry machine-verified treatment"),
        }
        attribution_gate = {
            "schema_version": "treatment_attribution_gate_v1",
            "gate": "PASS" if p9 else "FAIL",
            "runs": attribution,
            "blockers": [f"{rid}: {v['errors']}" for rid, v in attribution.items()
                         if v["status"] == "INVALID_TREATMENT"],
        }
        (self.state / "treatment_attribution_gate.json").write_text(
            json.dumps(attribution_gate, indent=2) + "\n")
        blockers = [f"{k}: {v['detail']}" for k, v in proofs.items() if v["status"] == "FAIL"]
        return {
            "schema_version": "fplus_rehearsal_gate_v1",
            "gate": "PASS" if not blockers else "FAIL",
            "proofs": proofs,
            "outputs": {
                "formation_runs": [r["run_id"] for r in sorted(formation, key=lambda r: r["order"])],
                "b1_future_runs": [r["run_id"] for r in sorted(b1_future, key=lambda r: r["order"])],
                "b2_future_runs": [r["run_id"] for r in sorted(b2_future, key=lambda r: r["order"])],
                "b3_future_runs": [r["run_id"] for r in sorted(b3_future, key=lambda r: r["order"])],
                "oracle_results": {r["run_id"]: r.get("oracle") for r in formation + future},
                "bundle_refs": [{"bundle_id": b["bundle_id"], "bundle_dir": b["bundle_dir"],
                                 "digest": b["bundle_digest"]} for b in bundles],
                "generation_input_digest": gen.get("generation_input_digest"),
                "proposal_digest": gen.get("proposal_digest"),
                "skill_ref": str(self.state / "skill_ref.json"),
                "candidate": str(self.state / "candidates" / "F+" / skill_ref.get("name", "")),
                "registry_entry": str(self.registry_root / "F+" / f"{skill_ref.get('name', '')}.json"),
                "treatment_attribution_gate": str(self.state / "treatment_attribution_gate.json"),
                "run_records": str(self.records_path),
                "cost_records": str(self.state / "cost.json"),
                "nv_report": str(self.state / "nv_report.json"),
            },
            "blockers": blockers,
        }

    def rehearsal(self) -> dict:
        self._check_docker()
        self.phase_oracle_check()
        self.phase_formation("b2")
        self.phase_formation("b3")
        self.phase_generation()
        self.phase_b2_freeze()
        self.phase_b3_build()
        self.phase_future("b2")
        self.phase_future("b3")
        return self.phase_cost_report()


class temp_outdir:
    """Minimal temp-dir context (stdlib tempfile is enough but this keeps oracle self-check tiny)."""
    def __init__(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()

    def __enter__(self) -> Path:
        return Path(self._tmp.name)

    def __exit__(self, *exc):
        self._tmp.cleanup()


PHASES = {
    "oracle-check": "phase_oracle_check", "formation": "phase_formation",
    "generation": "phase_generation", "b1-freeze": "phase_b1_freeze",
    "b2-freeze": "phase_b2_freeze",
    "b3-build": "phase_b3_build", "future": "phase_future",
    "cost": "phase_cost_report", "rehearsal": "rehearsal",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=list(PHASES), default="rehearsal")
    ap.add_argument("--arm", choices=["b0", "b1", "b2", "b3"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    h = Harness(force=args.force)
    fn = getattr(h, PHASES[args.phase])
    if args.phase in ("formation", "future"):
        if not args.arm:
            ap.error(f"--phase {args.phase} requires --arm b2|b3")
        result = fn(args.arm)
    else:
        result = fn()
    if args.phase == "cost":
        print(json.dumps({"gate": result["gate"], "blockers": result["blockers"]}, indent=2))
    return 0 if (args.phase != "cost" or result["gate"] == "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
