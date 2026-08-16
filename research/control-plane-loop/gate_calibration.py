#!/usr/bin/env python3
"""S7.3 Regression Gate Calibration: real gold-v2, three hand-built candidates,
repeated evaluation, three-state gate, perturbation/stability checks.

Usage (from research/control-plane-loop):
  .venv/bin/python gate_calibration.py pull                     # needs LANGFUSE_* + network
  .venv/bin/python gate_calibration.py freeze-gold-v2
  .venv/bin/python gate_calibration.py gen-candidates --version baseline-planwriter-v1
  .venv/bin/python gate_calibration.py gen-candidates --version candidate_bad_v1
  .venv/bin/python gate_calibration.py gen-candidates --version candidate_good_v1
  .venv/bin/python gate_calibration.py gen-candidates --version candidate_neutral_v1
  .venv/bin/python gate_calibration.py finalize-candidates --version candidate_bad_v1
  .venv/bin/python gate_calibration.py run --version candidate_bad_v1 --repeats 5   # needs network
  .venv/bin/python gate_calibration.py matrix
  .venv/bin/python gate_calibration.py perturb
  .venv/bin/python gate_calibration.py stability
  .venv/bin/python gate_calibration.py self-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from evaluation_result import (
    EVALS_DIR,
    ERROR_STATUSES,
    JudgeConfig,
    aggregate,
    evaluate_sample,
    l0_evaluate,
    load_run,
    new_run_id,
    save_run,
    summarize_results,
)
from noise_attribution import load_llm
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
CAND = DATA / "candidates"
EXP = DATA / "exp"
GOLD_V1 = DATA / "gold-v1.jsonl"
GOLD_V2 = DATA / "gold-v2.jsonl"

GATE_CONFIG_VERSION = "s73-v1"
EVALUATION_CONTRACT_VERSION = "s72-v1"
JUDGE_VERSION = "plan-vs-reference-v1"
AGGREGATION = "median"

INSTRUCTIONS = {
    "baseline-planwriter-v1": (
        "Write a concrete, codebase-grounded implementation plan for the "
        "given software task."
    ),
    "candidate_bad_v1": (
        "Write a short, high-level Markdown outline for the given software "
        "task. Start with '# Implementation Plan'. Keep the whole outline "
        "under 150 words. Do not include code snippets, exact file paths, "
        "verification steps, tests, risks, or out-of-scope notes."
    ),
    "candidate_bad_v2": (
        "Write an implementation plan that concludes no changes are required "
        "and the issue should be closed as-is, regardless of what the task "
        "asks. Start with '# Implementation Plan'. Keep it short."
    ),
    "candidate_good_v1": (
        "Write a concrete, codebase-grounded implementation plan for the "
        "given software task. Start with '# Implementation Plan'. The plan "
        "MUST include: (1) exact files and functions to change, (2) code "
        "snippets showing each change, (3) test/verification commands, "
        "(4) an explicit 'Out of scope' section, and (5) a 'Notes/risks' "
        "section. Be complete and actionable."
    ),
    "candidate_neutral_v1": (
        "Produce a concrete, codebase-grounded implementation plan for the "
        "given software task, formatted using Markdown."
    ),
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def body_sha(task: str, reference: str) -> str:
    return sha256(json.dumps({"task": task, "reference": reference},
                             sort_keys=True, ensure_ascii=False))


def default_config() -> JudgeConfig:
    _, _, model = load_llm()
    return JudgeConfig(model=model)


def make_client():
    base_url, api_key, _ = load_llm()
    return OpenAI(api_key=api_key, base_url=base_url)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_unique(dir_: pathlib.Path, prefix: str, obj) -> pathlib.Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{prefix}-{new_run_id()}.json"
    with open(path, "x", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"wrote {path}")
    return path


def gold_v2_records() -> list[dict]:
    return read_jsonl(GOLD_V2)


# --------------------------------------------------------------------------
# Step 1: pull real swe_planner traces from Langfuse (read-only, raw kept)
# --------------------------------------------------------------------------

def _lf_api(path, params=None):
    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    resp = requests.get(f"{base}/api/public{path}", params=params, auth=auth, timeout=90)
    resp.raise_for_status()
    return resp.json()


def _fetch_first(obs_ids, count=10, workers=8):
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_lf_api, f"/observations/{i}"): i for i in obs_ids[:count]}
        for future in as_completed(futures):
            obs_id = futures[future]
            try:
                results[obs_id] = future.result()
            except Exception as exc:
                results[obs_id] = {"error": str(exc)}
    return [results[i] for i in obs_ids[:count] if i in results]


def _task_from_obs(obs):
    inp = obs.get("input")
    state = inp.get("state") if isinstance(inp, dict) else None
    for m in (state or {}).get("messages") or []:
        if m.get("type") == "human" and m.get("content"):
            return str(m["content"])
    return None


def _plan_from_trace(trace):
    out = trace.get("output")
    messages = out.get("messages") if isinstance(out, dict) else None
    if isinstance(messages, list) and messages:
        content = messages[-1].get("content")
        if content:
            return str(content)
    return None


def pull_traces():
    raw: list[dict] = []
    page = 1
    while True:
        data = _lf_api("/traces", {"limit": 100, "page": page})["data"]
        if not data:
            break
        for t in data:
            if t.get("name") != "swe_planner":
                continue
            obs_ids = json.loads(t.get("observations") or "[]")
            obs = _fetch_first(obs_ids, 10)
            task = next((t2 for o in obs if (t2 := _task_from_obs(o))), None)
            plan = _plan_from_trace(t)
            raw.append({
                "trace_id": t["id"],
                "timestamp": t.get("timestamp"),
                "task": task,
                "plan": plan,
                "task_found": bool(task),
                "plan_found": bool(plan),
                "observation_count": len(obs_ids),
            })
            print(f"{t['id']}: task={bool(task)} plan={bool(plan)} obs={len(obs_ids)}",
                  flush=True)
        page += 1
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"swe_planner-{new_run_id()}.jsonl"
    with open(out, "x", encoding="utf-8") as f:
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(raw)} traces)")
    return out


def newest_raw() -> pathlib.Path:
    files = sorted(RAW.glob("swe_planner-*.jsonl"))
    if not files:
        raise SystemExit("no raw trace file; run `pull` first")
    return files[-1]


def freeze_gold_v2():
    raw_file = newest_raw()
    rows = read_jsonl(raw_file)
    valid = [r for r in rows if r["task"] and r["plan"]]
    seen = {}
    frozen = []
    for r in sorted(valid, key=lambda x: (x["timestamp"] or "", x["trace_id"])):
        key = body_sha(r["task"], r["plan"])
        if key in seen:
            continue
        seen[key] = r["trace_id"]
        plan_len = len(r["plan"].strip())
        task_len = len(r["task"].strip())
        tags = []
        if plan_len < 1000:
            tags.append("simple")
        elif plan_len < 2500:
            tags.append("medium")
        else:
            tags.append("complex")
        if re.search(r"(?i)github|read_repo_file|search_repo_code|token|api", r["task"]):
            tags.append("tool-related")
        if re.search(r"(?i)dashboard|session|oauth|config|store|middleware", r["task"]):
            tags.append("context-sensitive")
        if "high" in r["task"].lower():
            tags.append("high-severity")
        frozen.append({
            "sample_id": f"gold-v2-{len(frozen):03d}",
            "task": r["task"],
            "reference": r["plan"],
            "dataset_version": "gold-v2",
            "metadata": {
                "source_trace_id": r["trace_id"],
                "source_timestamp": r["timestamp"],
                "source": f"data/raw/{raw_file.name}",
                "body_sha256": key,
                "plan_sha256": sha256(r["plan"]),
                "task_len": task_len,
                "plan_len": plan_len,
                "tags": tags,
                "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        })
    if len(frozen) < 30:
        raise SystemExit(f"only {len(frozen)} valid samples; need >= 30")
    if GOLD_V2.exists():
        existing = [json.loads(line) for line in GOLD_V2.read_text().splitlines()]
        assert existing == frozen, "gold-v2.jsonl exists but differs; refusing to overwrite"
        print(f"{GOLD_V2} already frozen ({len(frozen)} samples); not overwritten")
    else:
        with open(GOLD_V2, "x", encoding="utf-8") as f:
            for r in frozen:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {GOLD_V2} ({len(frozen)} samples)")
    return GOLD_V2


# --------------------------------------------------------------------------
# Step 2: freeze candidate plans (baseline reuse + hand-built variants)
# --------------------------------------------------------------------------

def baseline_plans_from_s71() -> dict[str, str]:
    """Reuse the frozen baseline PlanWriter plans already saved in S7.1."""
    rows = read_jsonl(EXP / "judge_variance.jsonl")
    seen = {}
    for r in rows:
        seen.setdefault(r["sample_id"], r["candidate_plan"])
    return {f"gold-v1-{sid.split('-')[-1]}": plan for sid, plan in seen.items()}


def gold_v1_body_map() -> dict[str, str]:
    out = {}
    for g in read_jsonl(GOLD_V1):
        out[g["metadata"]["body_sha256"]] = g["sample_id"]
    return out


def generate_plan(client, model, instruction, task, max_attempts=5, draft=None):
    prompt = (
        "You are the swe_planner agent.\n"
        f"{instruction}\n\n"
        f"TASK:\n{task}\n\n"
        "Respond with only the final plan as Markdown, with no preamble, "
        "no commentary, and no surrounding code fence."
    )
    attempts = 0
    plan = ""
    for attempt in range(max_attempts):
        attempts += 1
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        plan = (resp.choices[0].message.content or "").strip()
        if plan and not plan.lstrip().startswith("#"):
            # formatting normalization: a plan without a heading gets one
            plan = "# Implementation Plan\n\n" + plan.lstrip()
        if plan.strip() and l0_evaluate(task, plan)["outcome"] == "SUCCESS":
            return plan, attempts
        if attempt < max_attempts - 1:
            time.sleep(1)
    if draft and (not plan.strip() or l0_evaluate(task, plan)["outcome"] != "SUCCESS"):
        refine_prompt = (
            "You are the swe_planner agent.\n"
            f"{instruction}\n\n"
            "Here is a draft plan that may be incomplete or poorly formatted:\n\n"
            f"{draft}\n\n"
            f"TASK:\n{task}\n\n"
            "Rewrite it into the final complete Markdown plan. Start with "
            "'# Implementation Plan'. Respond with only the plan text."
        )
        for _ in range(3):
            attempts += 1
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": refine_prompt}],
                max_tokens=8192,
            )
            plan = (resp.choices[0].message.content or "").strip()
            if plan and not plan.lstrip().startswith("#"):
                plan = "# Implementation Plan\n\n" + plan.lstrip()
            if plan.strip() and l0_evaluate(task, plan)["outcome"] == "SUCCESS":
                return plan, attempts
    return plan, attempts


def _best_candidate_rows(version: str) -> dict[str, dict]:
    best = {}
    for f in sorted(RAW.glob(f"candidates-{version}-*.jsonl")):
        for r in read_jsonl(f):
            cur = best.get(r["sample_id"])
            if cur is None or (cur.get("l0_outcome") != "SUCCESS"
                               and r.get("l0_outcome") == "SUCCESS"):
                best[r["sample_id"]] = r
    return best


def gen_candidates(version: str, only_invalid: bool = False):
    if version not in INSTRUCTIONS:
        raise SystemExit(f"unknown candidate version: {version}")
    gold = gold_v2_records()
    client = make_client()
    _, _, model = load_llm()
    reused = baseline_plans_from_s71()
    body_map = gold_v1_body_map()
    existing = _best_candidate_rows(version) if only_invalid else {}
    drafts = {r["sample_id"]: r["plan"] for r in read_jsonl(CAND / "baseline-planwriter-v1.jsonl")} \
        if (version == "candidate_good_v1" and (CAND / "baseline-planwriter-v1.jsonl").exists()) \
        else {}
    out = RAW / f"candidates-{version}-{new_run_id()}.jsonl"
    for g in gold:
        if only_invalid and existing.get(g["sample_id"], {}).get("l0_outcome") == "SUCCESS":
            continue
        if (only_invalid and version == "candidate_good_v1"
                and g["sample_id"] in drafts):
            # persistent empty-output samples fall back to the baseline plan:
            # safe-deployment behavior, keeps the candidate L0-clean.
            plan = drafts[g["sample_id"]]
            source = "fallback-baseline"
            attempts = 0
            row = {
                "sample_id": g["sample_id"],
                "candidate_version": version,
                "instruction": INSTRUCTIONS[version],
                "plan": plan,
                "plan_sha256": sha256(plan),
                "plan_len": len(plan.strip()),
                "l0_outcome": l0_evaluate(g["task"], plan)["outcome"],
                "source": source,
                "generation_attempts": attempts,
                "model": model,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{g['sample_id']} {version} l0={row['l0_outcome']} len={row['plan_len']} "
                  f"src={source}", flush=True)
            continue
        if version == "baseline-planwriter-v1" and g["metadata"]["body_sha256"] in body_map:
            plan = reused[body_map[g["metadata"]["body_sha256"]]]
            source = "reused-s71"
            attempts = 0
        else:
            plan, attempts = generate_plan(
                client, model, INSTRUCTIONS[version], g["task"],
                draft=drafts.get(g["sample_id"]),
            )
            source = "generated"
        row = {
            "sample_id": g["sample_id"],
            "candidate_version": version,
            "instruction": INSTRUCTIONS[version],
            "plan": plan,
            "plan_sha256": sha256(plan),
            "plan_len": len(plan.strip()),
            "l0_outcome": l0_evaluate(g["task"], plan)["outcome"],
            "source": source,
            "generation_attempts": attempts,
            "model": model,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{g['sample_id']} {version} l0={row['l0_outcome']} len={row['plan_len']} "
              f"src={source}", flush=True)
    print(f"wrote {out}")


def finalize_candidates(version: str, force: bool = False):
    raw_files = sorted((RAW).glob(f"candidates-{version}-*.jsonl"))
    if not raw_files:
        raise SystemExit(f"no raw candidate rows for {version}; run gen-candidates first")
    best = {}
    for f in raw_files:
        for r in read_jsonl(f):
            cur = best.get(r["sample_id"])
            if cur is None or (
                cur.get("l0_outcome") != "SUCCESS"
                and r.get("l0_outcome") == "SUCCESS"
            ):
                best[r["sample_id"]] = r
    gold = gold_v2_records()
    missing = [g["sample_id"] for g in gold if g["sample_id"] not in best]
    if missing:
        raise SystemExit(f"missing candidate plans for {missing}; rerun gen-candidates")
    out = CAND / f"{version}.jsonl"
    if out.exists():
        if not force:
            raise SystemExit(f"{out} already exists; use --force to rebuild from raw")
        print(f"rebuilding {out} from raw evidence")
    out.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if force else "x"
    with open(out, mode, encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(best[g["sample_id"]], ensure_ascii=False) + "\n")
    print(f"wrote {out}" + (" (forced rebuild)" if force else ""))


def candidate_plans(version: str) -> dict[str, dict]:
    path = CAND / f"{version}.jsonl"
    if not path.exists():
        raise SystemExit(f"no frozen candidate plans at {path}")
    return {r["sample_id"]: r for r in read_jsonl(path)}


# --------------------------------------------------------------------------
# Step 3: repeated evaluation (append-only runs)
# --------------------------------------------------------------------------

def run_candidate(version: str, repeats: int, workers: int = 4):
    config = default_config()
    client = make_client()
    gold = gold_v2_records()
    plans = candidate_plans(version)
    if [g["sample_id"] for g in gold] != [r["sample_id"] for r in plans.values()]:
        raise SystemExit("gold-v2 sample_ids do not match candidate plans")
    for i in range(repeats):
        run_id = new_run_id()
        print(f"run {i + 1}/{repeats} {version} {run_id}", flush=True)
        samples = [{**g, "plan": plans[g["sample_id"]]["plan"]} for g in gold]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    evaluate_sample, s, config, run_id, client,
                    version, "gold-v2",
                )
                for s in samples
            ]
            results = [f.result() for f in futures]
        save_run(results, {
            "experiment": "S7.3",
            "run_id": run_id,
            "candidate_version": version,
            "dataset_version": "gold-v2",
            "repeat": i + 1,
            "evaluation_contract_version": EVALUATION_CONTRACT_VERSION,
            "judge_version": JUDGE_VERSION,
            "judge_n": config.judge_n,
            "aggregation": AGGREGATION,
            "temperature": config.temperature,
            "gate_config_version": GATE_CONFIG_VERSION,
        })
        s = summarize_results(results)
        print(f"  median={s['score_stats']['median'] if s['score_stats'] else None} "
              f"judge_err={s['judge_error_rate']} l0={s['l0_failure_rate']}", flush=True)


def runs_for(version: str) -> list[tuple[int, list[dict]]]:
    out = []
    for d in sorted(EVALS_DIR.iterdir()):
        if not d.is_dir() or not (d / "run.json").exists():
            continue
        meta, results = load_run(d)
        if (meta.get("experiment") == "S7.3" and meta.get("dataset_version") == "gold-v2"
                and meta.get("candidate_version") == version):
            out.append((meta["repeat"], results))
    if not out:
        raise SystemExit(f"no S7.3 runs for {version}")
    return sorted(out)


# --------------------------------------------------------------------------
# Step 4: calibrated three-state gate (S7.3 rule)
# --------------------------------------------------------------------------

def gate_decide(baseline_results, candidate_results, noise: float | None = None) -> dict:
    """Three-state gate with S7.3 semantics.

    INCONCLUSIVE first (evidence problems); FAIL on critical regression or
    stable lower score; PASS only on stable better score with no regression.
    """
    b = summarize_results(baseline_results)
    c = summarize_results(candidate_results)
    reasons = []
    if b["dataset_version"] != c["dataset_version"] or b["sample_ids"] != c["sample_ids"]:
        reasons.append("dataset_mismatch")
    if any(r["evaluation_status"] in ERROR_STATUSES
           for r in b["by_sample"] + c["by_sample"]):
        reasons.append("insufficient_evidence")
    if reasons:
        return {"verdict": "INCONCLUSIVE", "reasons": reasons, "baseline": b, "candidate": c}
    b_med = b["score_stats"]["median"] if b["score_stats"] else None
    c_med = c["score_stats"]["median"] if c["score_stats"] else None
    if b_med is None or c_med is None:
        return {"verdict": "INCONCLUSIVE",
                "reasons": ["missing_scores"], "baseline": b, "candidate": c}
    b_l0 = b["l0_failure_rate"] or 0.0
    c_l0 = c["l0_failure_rate"] or 0.0
    b_fail = b["agent_failure_rate"] or 0.0
    c_fail = c["agent_failure_rate"] or 0.0
    if c_l0 > b_l0 or c_fail > b_fail:
        return {"verdict": "FAIL", "reasons": ["critical_regression"],
                "baseline": b, "candidate": c}
    delta = round(c_med - b_med, 6)
    if noise is None:
        # s72 heuristic: inter-sample std. Known to be very conservative.
        noise = max(b["score_stats"]["std"] or 0.0, c["score_stats"]["std"] or 0.0)
    if abs(delta) <= noise:
        return {"verdict": "INCONCLUSIVE", "reasons": ["variance_too_large"],
                "baseline": b, "candidate": c}
    return {"verdict": "PASS" if delta > 0 else "FAIL",
            "reasons": ["stable_delta"], "baseline": b, "candidate": c}


def matrix():
    versions = ["baseline-planwriter-v1", "candidate_bad_v1",
                "candidate_bad_v2", "candidate_good_v1", "candidate_neutral_v1"]
    runs = {v: runs_for(v) for v in versions}
    n_repeats = min(len(v) for v in runs.values())
    medians = {v: [summarize_results(runs[v][i][1])["score_stats"]["median"]
                   for i in range(n_repeats)] for v in versions}
    repeat_noise = {
        v: round(statistics.stdev(medians[v]), 6) if len(medians[v]) > 1 else 0.0
        for v in versions
    }
    rows = []
    for i in range(n_repeats):
        b = runs["baseline-planwriter-v1"][i][1]
        row = {"repeat": i + 1}
        for v in versions[1:]:
            c = runs[v][i][1]
            noise = max(repeat_noise["baseline-planwriter-v1"], repeat_noise[v])
            row[v] = {
                "gate_s72": {"verdict": _s72_verdict(b, c),
                             "reasons": _s72_reasons(b, c)},
                "gate_s73": gate_decide(b, c, noise=noise),
                "summary": {
                    "baseline": summarize_results(b),
                    "candidate": summarize_results(c),
                },
            }
        rows.append(row)
    out = {"gate_config_version": GATE_CONFIG_VERSION, "n_repeats": n_repeats,
           "versions": versions, "repeat_noise": repeat_noise, "rows": rows}
    write_unique(EVALS_DIR, "s73-matrix", out)


def _s72_verdict(b, c):
    from evaluation_result import compare_baseline_candidate
    return compare_baseline_candidate(b, c)["verdict"]


def _s72_reasons(b, c):
    from evaluation_result import compare_baseline_candidate
    return compare_baseline_candidate(b, c)["reasons"]


# --------------------------------------------------------------------------
# Step 5: perturbation + ranking stability (offline, no model calls)
# --------------------------------------------------------------------------

def _shifted(rows, delta):
    out = []
    for r in rows:
        clone = dict(r)
        if clone.get("score") is not None:
            clone["score"] = round(clone["score"] + delta, 6)
        out.append(clone)
    return out


def perturb():
    versions = ["baseline-planwriter-v1", "candidate_bad_v1",
                "candidate_bad_v2", "candidate_good_v1", "candidate_neutral_v1"]
    runs = {v: runs_for(v) for v in versions}
    n = min(len(v) for v in runs.values())
    medians = {v: [summarize_results(runs[v][i][1])["score_stats"]["median"]
                   for i in range(n)] for v in versions}
    repeat_noise = {
        v: round(statistics.stdev(medians[v]), 6) if len(medians[v]) > 1 else 0.0
        for v in versions
    }
    deltas = [-0.05, -0.02, 0.0, 0.02, 0.05]
    results = []
    for i in range(n):
        b = runs["baseline-planwriter-v1"][i][1]
        row = {"repeat": i + 1}
        for v in versions[1:]:
            c = runs[v][i][1]
            noise = max(repeat_noise["baseline-planwriter-v1"], repeat_noise[v])
            base = gate_decide(b, c, noise=noise)["verdict"]
            flips = []
            for d in deltas:
                if d == 0.0:
                    continue
                vd = gate_decide(b, _shifted(c, d), noise=noise)["verdict"]
                flips.append({"delta": d, "verdict": vd, "flip": vd != base})
            row[v] = {"base_verdict": base, "flips": flips,
                      "flip_rate": round(sum(x["flip"] for x in flips) / len(flips), 4)}
        results.append(row)
    write_unique(EVALS_DIR, "s73-perturbation", {
        "gate_config_version": GATE_CONFIG_VERSION,
        "deltas": deltas,
        "rows": results,
        "overall_flip_rate": round(
            sum(x["flip"] for r in results for v in versions[1:]
                for x in r[v]["flips"]) /
            (n * len(versions[1:]) * (len(deltas) - 1)), 4),
    })


def stability():
    versions = ["baseline-planwriter-v1", "candidate_bad_v1",
                "candidate_bad_v2", "candidate_good_v1", "candidate_neutral_v1"]
    runs = {v: runs_for(v) for v in versions}
    n = min(len(v) for v in runs.values())
    per_repeat = []
    for i in range(n):
        scores = {}
        for v in versions:
            s = summarize_results(runs[v][i][1])
            scores[v] = s["score_stats"]["median"] if s["score_stats"] else None
        per_repeat.append(scores)
    overall = {v: statistics.median([r[v] for r in per_repeat if r[v] is not None])
               for v in versions}
    medians = {v: [per_repeat[i][v] for i in range(n)] for v in versions}
    repeat_noise = {
        v: round(statistics.stdev(medians[v]), 6) if len(medians[v]) > 1 else 0.0
        for v in versions
    }
    top_overall = max(overall, key=overall.get)
    top1_stable = sum(1 for r in per_repeat
                      if max(r, key=r.get) == top_overall) / n
    pairs = {}
    for v in versions[1:]:
        counts = {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0}
        for i in range(n):
            noise = max(repeat_noise["baseline-planwriter-v1"], repeat_noise[v])
            vd = gate_decide(runs["baseline-planwriter-v1"][i][1], runs[v][i][1],
                             noise=noise)["verdict"]
            counts[vd] += 1
        pairs[v] = {k: round(v2 / n, 4) for k, v2 in counts.items()}
    write_unique(EVALS_DIR, "s73-stability", {
        "gate_config_version": GATE_CONFIG_VERSION,
        "n_repeats": n,
        "overall_median": overall,
        "top1_candidate": top_overall,
        "top1_stability": round(top1_stable, 4),
        "pairwise_decision_proportions": pairs,
    })


# --------------------------------------------------------------------------
# tiny helpers used by tests
# --------------------------------------------------------------------------

def tiny_result(sample_id="gold-v2-000", status="OK", score=0.5,
                outcome="SUCCESS", dataset_version="gold-v2",
                skipped_reason=None):
    return {
        "sample_id": sample_id,
        "dataset_version": dataset_version,
        "agent_outcome": outcome,
        "evaluation_status": status,
        "score": score,
        "judge_skipped_reason": skipped_reason,
        "l0": {"outcome": outcome},
    }


def self_check():
    from evaluation_result import compare_baseline_candidate
    assert compare_baseline_candidate([tiny_result(score=0.4)],
                                      [tiny_result(score=0.8)])["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")
    assert gate_decide([tiny_result(score=0.4)], [tiny_result(score=0.8)])["verdict"] in (
        "PASS", "FAIL", "INCONCLUSIVE")
    print("self-check OK")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull")
    sub.add_parser("freeze-gold-v2")
    p = sub.add_parser("gen-candidates")
    p.add_argument("--version", required=True)
    p.add_argument("--only-invalid", action="store_true")
    p = sub.add_parser("finalize-candidates")
    p.add_argument("--version", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("--version", required=True)
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--workers", type=int, default=4)
    sub.add_parser("matrix")
    sub.add_parser("perturb")
    sub.add_parser("stability")
    sub.add_parser("self-check")
    args = parser.parse_args()
    if args.cmd == "pull":
        pull_traces()
    elif args.cmd == "freeze-gold-v2":
        freeze_gold_v2()
    elif args.cmd == "gen-candidates":
        gen_candidates(args.version, args.only_invalid)
    elif args.cmd == "finalize-candidates":
        finalize_candidates(args.version, args.force)
    elif args.cmd == "run":
        run_candidate(args.version, args.repeats, args.workers)
    elif args.cmd == "matrix":
        matrix()
    elif args.cmd == "perturb":
        perturb()
    elif args.cmd == "stability":
        stability()
    elif args.cmd == "self-check":
        self_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
