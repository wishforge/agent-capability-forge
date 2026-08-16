#!/usr/bin/env python3
"""S7.2 experiments: A baseline repeated evaluation, B judge stability, C L0/L1/L2 comparison.

Usage:
  .venv/bin/python run_s72_experiments.py a [--runs 5]      # needs DeepSeek network
  .venv/bin/python run_s72_experiments.py bc                # offline from saved A runs
  .venv/bin/python run_s72_experiments.py compare <run1> <run2>
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import statistics
import sys
from collections import Counter

from evaluation_result import (
    EVALS_DIR,
    JudgeConfig,
    aggregate,
    compare_baseline_candidate,
    evaluate_sample,
    gold_v1_records,
    l0_evaluate,
    l1_evaluate,
    load_run,
    new_run_id,
    save_run,
    summarize_results,
)
from noise_attribution import load_llm
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent
EXP = ROOT / "data" / "exp"


def default_config() -> JudgeConfig:
    _, _, model = load_llm()
    return JudgeConfig(model=model)


def make_client():
    base_url, api_key, _ = load_llm()
    return OpenAI(api_key=api_key, base_url=base_url)


def baseline_candidates() -> dict[str, str]:
    """Fixed real PlanWriter outputs from S7.1 (first row per gold-v0 sample)."""
    seen = {}
    for line in (EXP / "judge_variance.jsonl").read_text().splitlines():
        row = json.loads(line)
        seen.setdefault(row["sample_id"], row["candidate_plan"])
    return {f"gold-v1-{sid.split('-')[-1]}": plan for sid, plan in seen.items()}


def samples_with_candidates() -> list[dict]:
    candidates = baseline_candidates()
    out = []
    for g in gold_v1_records():
        if g["sample_id"] not in candidates:
            raise SystemExit(f"no fixed candidate for {g['sample_id']}")
        out.append({**g, "plan": candidates[g["sample_id"]]})
    return out


def write_unique(dir_: pathlib.Path, prefix: str, obj: dict) -> pathlib.Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{prefix}-{new_run_id()}.json"
    with open(path, "x", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"wrote {path}")
    return path


def run_a(runs: int) -> list[pathlib.Path]:
    config = default_config()
    client = make_client()
    samples = samples_with_candidates()
    run_dirs = []
    for i in range(runs):
        run_id = new_run_id()
        print(f"run {i + 1}/{runs} {run_id}", flush=True)
        results = [
            evaluate_sample(s, config, run_id=run_id, client=client,
                            candidate_version="baseline-planwriter-v1",
                            dataset_version="gold-v1")
            for s in samples
        ]
        run_dir = save_run(results, {
            "experiment": "A",
            "candidate_version": "baseline-planwriter-v1",
            "dataset_version": "gold-v1",
            "run_id": run_id,
        })
        run_dirs.append(run_dir)
        print("  " + json.dumps(summarize_results(results)["by_sample"], ensure_ascii=False),
              flush=True)
    summaries = []
    for d in run_dirs:
        _, results = load_run(d)
        summaries.append(summarize_results(results))
    per_sample = {}
    for sid in sorted({r["sample_id"] for s in summaries for r in s["by_sample"]}):
        run_scores = []
        for s in summaries:
            row = next(r for r in s["by_sample"] if r["sample_id"] == sid)
            run_scores.append(row["score"])
        per_sample[sid] = {
            "run_scores": run_scores,
            "across_runs": aggregate([x for x in run_scores if x is not None]),
        }
    run_medians = [s["score_stats"]["median"] for s in summaries if s["score_stats"]]
    write_unique(EVALS_DIR, "experiment-a", {
        "runs": runs,
        "run_dirs": [str(d) for d in run_dirs],
        "per_run": summaries,
        "per_sample_across_runs": per_sample,
        "run_median_across_runs": aggregate(run_medians),
        "judge_error_rate_across_runs": [s["judge_error_rate"] for s in summaries],
        "agent_failure_rate_across_runs": [s["agent_failure_rate"] for s in summaries],
        "l0_failure_rate_across_runs": [s["l0_failure_rate"] for s in summaries],
    })
    return run_dirs


def a_run_dirs() -> list[pathlib.Path]:
    if not EVALS_DIR.exists():
        raise SystemExit("no data/evals; run `a` first")
    dirs = []
    for d in sorted(EVALS_DIR.iterdir()):
        if d.is_dir() and (d / "run.json").exists():
            meta = json.loads((d / "run.json").read_text())
            if meta.get("experiment") == "A":
                dirs.append(d)
    if not dirs:
        raise SystemExit("no experiment A runs; run `a` first")
    return dirs


def run_bc():
    dirs = a_run_dirs()
    all_attempts = []
    all_rounds = []
    per_sample_scores: dict[str, list[float]] = {}
    judge_error_rate = []
    insufficient_rate = []
    for d in dirs:
        _, results = load_run(d)
        judge_error_rate.append(summarize_results(results)["judge_error_rate"])
        insufficient_rate.append(summarize_results(results)["insufficient_evidence_rate"])
        for r in results:
            all_attempts.extend(r["raw_judge_responses"])
            by_round = {}
            for a in r["raw_judge_responses"]:
                by_round.setdefault(a["round"], []).append(a)
            all_rounds.extend(by_round.values())
            per_sample_scores.setdefault(r["sample_id"], []).extend(r["all_scores"])
    attempt_categories = Counter(a["category"] for a in all_attempts)
    rounds_success = sum(1 for rd in all_rounds if any(a["category"] == "OK" for a in rd))
    rounds_recovered = sum(
        1 for rd in all_rounds
        if any(a["category"] == "OK" for a in rd) and rd[0]["category"] != "OK"
    )

    # n=2 vs n=5 resampling of the recorded scores (S7.1 methodology, no model calls)
    stability = {}
    for sid, scores in sorted(per_sample_scores.items()):
        if len(scores) < 10:
            continue
        entry = {"n_scores": len(scores)}
        for n in (2, 5):
            combos = list(itertools.combinations(scores, n))
            agg_stds = {"mean": [], "median": []}
            for combo in combos:
                agg_stds["mean"].append(statistics.fmean(combo))
                agg_stds["median"].append(statistics.median(combo))
            entry[f"n{n}"] = {
                "mean_std": round(statistics.stdev(agg_stds["mean"]), 6),
                "median_std": round(statistics.stdev(agg_stds["median"]), 6),
                "combos": len(combos),
            }
        entry["n2_n5_median_std_ratio"] = round(
            entry["n2"]["median_std"] / entry["n5"]["median_std"], 4)
        stability[sid] = entry

    write_unique(EVALS_DIR, "experiment-b", {
        "runs_used": [str(d) for d in dirs],
        "attempt_level": {
            "total_attempts": len(all_attempts),
            "categories": dict(attempt_categories),
            "parse_success_rate": round(attempt_categories.get("OK", 0) / len(all_attempts), 4)
            if all_attempts else None,
        },
        "round_level": {
            "total_rounds": len(all_rounds),
            "success_rate": round(rounds_success / len(all_rounds), 4) if all_rounds else None,
            "recovered_after_retry_rate": round(rounds_recovered / rounds_success, 4)
            if rounds_success else None,
        },
        "n2_vs_n5_stability": stability,
        "judge_error_rate_per_run": judge_error_rate,
        "insufficient_evidence_rate_per_run": insufficient_rate,
    })
    run_c(dirs[0])


def run_c(run_dir: pathlib.Path | None = None):
    run_dir = run_dir or a_run_dirs()[0]
    _, results = load_run(run_dir)
    by_sample = {r["sample_id"]: r for r in results}
    table = []
    for s in samples_with_candidates():
        l0 = l0_evaluate(s["task"], s["plan"])
        row = {
            "sample_id": s["sample_id"],
            "l0_outcome": l0["outcome"],
            "l0": l0,
            "l1": l1_evaluate(s["plan"]),
            "judge_skipped": l0["outcome"] != "SUCCESS",
        }
        r = by_sample.get(s["sample_id"])
        if r:
            row.update({
                "evaluation_status": r["evaluation_status"],
                "l2_median": r["l2"].get("median") if r.get("l2") else None,
                "score": r["score"],
                "judge_attempts": r["judge_attempts"],
                "success_count": r["success_count"],
                "failure_count": r["failure_count"],
            })
        table.append(row)
    failures = [json.loads(line) for line in (ROOT / "data" / "failures.jsonl").read_text().splitlines()]
    failure_l0 = []
    for f in failures:
        if not f["task_found"]:
            outcome = "MISSING_REQUIRED_FIELD"
        elif not f["plan_found"]:
            outcome = "NO_PLAN"
        else:
            outcome = "SUCCESS"
        failure_l0.append({"trace_id": f["trace_id"], "l0_outcome": outcome})
    counts = Counter(row["l0_outcome"] for row in table) + Counter(x["l0_outcome"] for x in failure_l0)
    write_unique(EVALS_DIR, "experiment-c", {
        "run_dir": str(run_dir),
        "gold_l0_l1_l2": table,
        "failures_l0": failure_l0,
        "l0_outcome_counts": dict(counts),
        "deterministic_skips": sum(row["judge_skipped"] for row in table),
        "notes": {
            "reference_format_anomaly": [
                s["sample_id"] for s in gold_v1_records()
                if l0_evaluate(s["task"], s["reference"])["outcome"] != "SUCCESS"
            ],
        },
    })


def cmd_compare(run1: str, run2: str):
    _, b = load_run(run1)
    _, c = load_run(run2)
    print(json.dumps(compare_baseline_candidate(b, c), indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_a = sub.add_parser("a")
    p_a.add_argument("--runs", type=int, default=5)
    sub.add_parser("bc")
    p_c = sub.add_parser("compare")
    p_c.add_argument("run1")
    p_c.add_argument("run2")
    args = parser.parse_args()
    if args.cmd == "a":
        run_a(args.runs)
    elif args.cmd == "bc":
        run_bc()
    elif args.cmd == "compare":
        cmd_compare(args.run1, args.run2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
