#!/usr/bin/env python3
"""S7.1 Evaluation noise attribution experiments.

Steps (from repo root):
  python research/control-plane-loop/noise_attribution.py dataset      # exp4: freeze gold-v0.jsonl + reproducibility
  python research/control-plane-loop/noise_attribution.py judge        # exp1: judge variance (needs network)
  python research/control-plane-loop/noise_attribution.py agent        # exp2: agent plan variance (needs network)
  python research/control-plane-loop/noise_attribution.py aggregation  # exp3: from saved raw scores, no model calls
  python research/control-plane-loop/noise_attribution.py pipeline     # exp5: parse/aggregation determinism + edge cases
  python research/control-plane-loop/noise_attribution.py l0           # exp6: deterministic failure baseline
  python research/control-plane-loop/noise_attribution.py self-check

No existing loop file is modified; results land in research/control-plane-loop/data/exp/.
"""

import hashlib
import itertools
import json
import pathlib
import re
import statistics
import sys
import time
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
EXP = DATA / "exp"
GOLD = DATA / "gold-v0.jsonl"
MODEL = None
CLIENT = None


def load_llm():
    cfg = tomllib.loads(pathlib.Path("/Users/david/.codex/config.toml").read_text())
    prov = cfg["model_providers"]["deepseek"]
    return (
        prov["base_url"].rstrip("/"),
        prov["experimental_bearer_token"],
        cfg.get("model", "deepseek-v4-flash"),
    )


def parse_judge(content):
    """Same regex+json.loads as evaluate.py/_parse_judge and optimize.py."""
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    payload = {}
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = {}
    score = payload.get("score")
    ok = isinstance(score, (int, float)) and not isinstance(score, bool)
    return (score if ok else None, payload.get("reasoning"), ok)


def judge_prompt(task, reference, candidate):
    return (
        "You are grading whether a candidate implementation plan is accurate and "
        "useful for the task, compared against the reference plan written by an "
        "agent that inspected the codebase.\n\n"
        f"TASK:\n{task}\n\n"
        f"REFERENCE PLAN:\n{reference}\n\n"
        f"CANDIDATE PLAN:\n{candidate}\n\n"
        'Respond in JSON: {"score": <0-1 number>, "reasoning": "<brief comparison>"}'
    )


def judge_call(task, reference, candidate, temperature, max_tokens=800):
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "user", "content": judge_prompt(task, reference, candidate)}],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    for attempt in range(3):
        try:
            response = CLIENT.chat.completions.create(**kwargs)
            break
        except Exception as exc:
            if attempt == 2:
                raise
            print(f"  retry {attempt + 1}: {exc}", flush=True)
            time.sleep(2)
    content = response.choices[0].message.content or ""
    score, reasoning, ok = parse_judge(content)
    return {
        "raw_response": content,
        "parse_success": ok,
        "score": score,
        "reasoning": reasoning,
    }


def gold_records():
    return [json.loads(line) for line in GOLD.read_text().splitlines()]


def stats(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "std": round(statistics.stdev(values), 4) if len(values) > 1 else None,
        "min": min(values),
        "max": max(values),
    }


def write_json(name, obj):
    EXP.mkdir(exist_ok=True)
    with open(EXP / name, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"wrote {EXP / name}")


def make_planner():
    """Baseline PlanWriter with the same dspy.LM config as optimize.py (temperature unset)."""
    import dspy

    base_url, api_key, model = load_llm()
    lm = dspy.LM(
        model=f"openai/{model}",
        api_base=base_url,
        api_key=api_key,
        max_tokens=8192,
        cache=False,  # dspy default cache=True would replay the first plan inside one process
    )
    dspy.configure(lm=lm)

    class PlanWriter(dspy.Signature):
        """Write a concrete, codebase-grounded implementation plan for the given software task."""

        task: str = dspy.InputField()
        plan: str = dspy.OutputField(desc="Markdown implementation plan")

    return dspy.Predict(PlanWriter)


def step_dataset():
    """Exp4: freeze the 6 real samples as gold-v0.jsonl, never overwrite."""
    records = [json.loads(line) for line in (DATA / "dataset.jsonl").read_text().splitlines()]
    frozen = []
    for i, r in enumerate(records):
        body = json.dumps({"task": r["task"], "reference": r["plan"]}, ensure_ascii=False, sort_keys=True)
        frozen.append(
            {
                "sample_id": f"gold-v0-{i:03d}",
                "task": r["task"],
                "reference": r["plan"],
                "metadata": {
                    "source_trace_id": r["trace_id"],
                    "source": "data/dataset.jsonl",
                    "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                },
            }
        )
    if GOLD.exists():
        before = hashlib.sha256(GOLD.read_bytes()).hexdigest()
        assert json.loads(GOLD.read_text()) == frozen, "gold-v0.jsonl exists but differs from current dataset.jsonl"
        after = hashlib.sha256(GOLD.read_bytes()).hexdigest()
        assert before == after
        print("gold-v0.jsonl already exists; not overwritten")
    else:
        GOLD.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in frozen) + "\n")
        print(f"wrote {GOLD}")

    hashes = []
    for _ in range(5):
        rows = gold_records()
        assert len(rows) == 6
        assert [r["sample_id"] for r in rows] == [r["sample_id"] for r in frozen]
        assert [json.dumps(r["task"]) for r in rows] == [json.dumps(r["task"]) for r in frozen]
        assert [json.dumps(r["reference"]) for r in rows] == [json.dumps(r["reference"]) for r in frozen]
        assert [set(r) for r in rows] == [{"sample_id", "task", "reference", "metadata"} for _ in rows]
        hashes.append(hashlib.sha256(GOLD.read_bytes()).hexdigest())
    assert len(set(hashes)) == 1
    write_json("dataset_reproducibility.json", {
        "loads": 5,
        "count_stable": True,
        "order_stable": True,
        "content_stable": True,
        "fields_stable": True,
        "not_overwritten": True,
        "file_sha256": hashes[0],
        "sample_ids": [r["sample_id"] for r in frozen],
    })


def step_judge():
    """Exp1: fixed (task, reference, candidate) x 10 runs x {temperature=0, default}.

    One baseline PlanWriter output per sample is generated first, then held
    fixed for all 20 judge calls.
    """
    student = make_planner()
    gold = gold_records()
    candidates = {}
    for sample in gold:
        candidates[sample["sample_id"]] = student(task=sample["task"]).plan
        print(f"{sample['sample_id']}: fixed candidate plan_len={len(candidates[sample['sample_id']])}", flush=True)
    rows = []
    for sample in gold:
        candidate = candidates[sample["sample_id"]]
        for config, temperature in (("temp0", 0), ("default", None)):
            for run in range(10):
                result = judge_call(sample["task"], sample["reference"], candidate, temperature)
                row = {
                    "sample_id": sample["sample_id"],
                    "run_id": f"{config}-{run + 1:02d}",
                    "model": MODEL,
                    "temperature": temperature,
                    "candidate_plan": candidate,
                    "raw_response": result["raw_response"],
                    "parse_success": result["parse_success"],
                    "score": result["score"],
                }
                rows.append(row)
                print(row["sample_id"], row["run_id"], row["score"], flush=True)
    EXP.mkdir(exist_ok=True)
    with open(EXP / "judge_variance.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"rows": len(rows), "candidate_plan_len": {k: len(v) for k, v in candidates.items()}}
    for config in ("temp0", "default"):
        for sample in gold:
            scores = [
                r["score"]
                for r in rows
                if r["sample_id"] == sample["sample_id"] and r["temperature"] == (0 if config == "temp0" else None)
            ]
            key = f"{sample['sample_id']}:{config}"
            summary[key] = stats(scores)
            summary[key]["parse_success"] = sum(
                1 for r in rows if r["sample_id"] == sample["sample_id"]
                and r["temperature"] == (0 if config == "temp0" else None)
                and r["parse_success"]
            )
            summary[key]["score_as_pipeline"] = stats(
                [r["score"] if r["score"] is not None else 0.0 for r in rows
                 if r["sample_id"] == sample["sample_id"] and r["temperature"] == (0 if config == "temp0" else None)]
            )
    write_json("judge_variance_summary.json", summary)


def step_agent():
    """Exp2: rerun the baseline PlanWriter on the 2 gate valset tasks x 10, judge with temp=0."""
    records = [json.loads(line) for line in (DATA / "dataset.jsonl").read_text().splitlines()]
    records.sort(key=lambda r: len(r["plan"]), reverse=True)
    valset = records[4:6]
    print("valset tasks:", [r["trace_id"] for r in valset])

    student = make_planner()
    base_url, api_key, model = load_llm()
    rows = []
    for record in valset:
        sample_id = next(
            g["sample_id"] for g in gold_records() if g["metadata"]["source_trace_id"] == record["trace_id"]
        )
        for run in range(10):
            prediction = student(task=record["task"])
            plan = prediction.plan
            judged = judge_call(record["task"], record["plan"], plan, temperature=0)
            row = {
                "sample_id": sample_id,
                "source_trace_id": record["trace_id"],
                "run_id": f"agent-{run + 1:02d}",
                "model": model,
                "gen_temperature": None,
                "judge_temperature": 0,
                "plan": plan,
                "plan_sha256": hashlib.sha256(plan.encode()).hexdigest()[:16],
                "plan_len": len(plan),
                "raw_response": judged["raw_response"],
                "parse_success": judged["parse_success"],
                "score": judged["score"],
            }
            rows.append(row)
            print(row["sample_id"], row["run_id"], "plan_len=", row["plan_len"], "score=", row["score"], flush=True)
    EXP.mkdir(exist_ok=True)
    with open(EXP / "agent_variance.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {}
    for sample_id in sorted({r["sample_id"] for r in rows}):
        subset = [r for r in rows if r["sample_id"] == sample_id]
        summary[sample_id] = {
            "plan_len": stats([r["plan_len"] for r in subset]),
            "score": stats([r["score"] for r in subset if r["score"] is not None]),
            "parse_success": sum(r["parse_success"] for r in subset),
        }
    write_json("agent_variance_summary.json", summary)


def step_aggregation():
    """Exp3: resample saved raw scores; no model calls. Gate = round(100*mean(scores), 2)."""
    rows = [json.loads(line) for line in (EXP / "judge_variance.jsonl").read_text().splitlines()]
    out = {}
    for config, temperature in (("temp0", 0), ("default", None)):
        by_sample = {}
        for sample_id in sorted({r["sample_id"] for r in rows}):
            scores = [
                float(r["score"]) if r["score"] is not None else 0.0  # silent-zero semantics of optimize.py
                for r in rows
                if r["sample_id"] == sample_id and r["temperature"] == temperature
            ]
            by_sample[sample_id] = scores

        per_n = {}
        for n in (1, 2, 3, 5, 10):
            combos = list(itertools.combinations(range(10), n)) if n < 10 else [(0, 1, 2, 3, 4, 5, 6, 7, 8, 9)]
            agg_by_sample = {(sid, agg_name): [] for sid in by_sample for agg_name in ("mean", "median")}
            for combo in combos:
                for sid, scores in by_sample.items():
                    picked = [scores[i] for i in combo]
                    for agg_name, fn in (("mean", statistics.fmean), ("median", statistics.median)):
                        agg_by_sample[(sid, agg_name)].append(round(100 * fn(picked), 2))
            per_n[str(n)] = {
                agg_name: {
                    sid: stats(vals) for (sid, a), vals in agg_by_sample.items() if a == agg_name
                }
                for agg_name in ("mean", "median")
            }

            # ranking stability vs n=10 mean ranking
            n10_rank = tuple(
                sid for sid, _ in sorted(
                    ((sid, statistics.fmean(by_sample[sid])) for sid in by_sample),
                    key=lambda x: (-x[1], x[0]),
                )
            )
            top1_agree = exact_agree = 0
            for combo in combos:
                rank = tuple(
                    sid for sid, _ in sorted(
                        ((sid, statistics.fmean([by_sample[sid][i] for i in combo])) for sid in by_sample),
                        key=lambda x: (-x[1], x[0]),
                    )
                )
                top1_agree += rank[0] == n10_rank[0]
                exact_agree += rank == n10_rank
            per_n[str(n)]["ranking"] = {
                "n10_rank": n10_rank,
                "top1_agree_fraction": round(top1_agree / len(combos), 4),
                "exact_rank_agree_fraction": round(exact_agree / len(combos), 4),
            }
        out[config] = per_n
    write_json("aggregation.json", out)


def step_pipeline():
    """Exp5: fixed judge raw outputs -> parse/aggregate 20x, plus edge cases and stale-file checks."""
    rows = [json.loads(line) for line in (EXP / "judge_variance.jsonl").read_text().splitlines()]
    parse_results = [{"sample_id": r["sample_id"], "parse_success": r["parse_success"], "score": r["score"]} for r in rows]
    aggregate_results = None
    for _ in range(20):
        p = [parse_judge(r["raw_response"]) for r in rows]
        assert [x[2] for x in p] == [r["parse_success"] for r in rows]
        assert [x[0] for x in p] == [r["score"] for r in rows]
        gate = {}
        for sample_id in sorted({r["sample_id"] for r in rows}):
            scores = [float(r["score"]) if r["score"] is not None else 0.0 for r in rows if r["sample_id"] == sample_id]
            gate[sample_id] = round(100 * statistics.fmean(scores), 2)
        if aggregate_results is None:
            aggregate_results = gate
        assert gate == aggregate_results

    edge = [
        "",
        "not json",
        "{bad json",
        '{"reasoning": "x"}',
        '{"score": "high", "reasoning": "x"}',
        '{"score": 0.7, "reasoning": "ok"}',
    ]
    edge_rows = []
    for content in edge:
        score, reasoning, ok = parse_judge(content)
        edge_rows.append({
            "input": content,
            "parse_success": ok,
            "score_evaluate_semantics": score,           # None on failure (evaluate.py)
            "score_optimize_semantics": score if score is not None else 0.0,  # silent zero (optimize.py)
        })

    samples = [json.loads(line) for line in (DATA / "samples.jsonl").read_text().splitlines()]
    summary = json.loads((DATA / "summary.json").read_text())
    fresh = {
        "trace_count": len(samples),
        "total_observations": sum(s["observation_count"] for s in samples),
        "total_messages": sum(s["message_count"] for s in samples),
        "trace_ids": [s["trace_id"] for s in samples],
    }
    write_json("pipeline_determinism.json", {
        "parse_reruns": 20,
        "parse_identical": True,
        "aggregation_reruns": 20,
        "aggregation_identical": True,
        "gate_scores_temp0": aggregate_results,
        "edge_cases": edge_rows,
        "summary_json": summary,
        "summary_fresh": fresh,
        "summary_stale": summary != fresh,
        "overwrite_behavior": "loop.py/build_dataset.py/evaluate.py/optimize.py all open output files with mode 'w'; loading-only steps above wrote nothing",
    })


def step_l0():
    """Exp6: deterministic failures visible without any LLM judge."""
    gold = gold_records()
    failures = [json.loads(line) for line in (DATA / "failures.jsonl").read_text().splitlines()]
    classified = []
    for g in gold:
        if not g["task"].strip():
            kind = "MISSING_REQUIRED_FIELD"
        elif not g["reference"].strip():
            kind = "EMPTY_PLAN"
        elif not g["reference"].lstrip().startswith("#"):
            kind = "INVALID_FORMAT"
        else:
            kind = "PASS"
        classified.append({"trace_id": g["metadata"]["source_trace_id"], "kind": kind})
    for f in failures:
        if not f["task_found"]:
            kind = "MISSING_REQUIRED_FIELD"
        elif not f["plan_found"]:
            kind = "NO_PLAN"
        else:
            kind = "PASS"
        classified.append({"trace_id": f["trace_id"], "kind": kind})

    counts = {}
    for c in classified:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    total = len(classified)
    no_plan_by_flag = sum(not f["plan_found"] for f in failures)
    missing_task_by_flag = sum(not f["task_found"] for f in failures)
    write_json("l0.json", {
        "total_traces_sampled": total,
        "gold_records": len(gold),
        "failure_records": len(failures),
        "classification": classified,
        "counts": counts,
        "no_plan_by_flag": no_plan_by_flag,
        "missing_task_by_flag": missing_task_by_flag,
        "hard_failure_count_no_llm": len(failures),
        "hard_failure_rate_no_llm": round(100 * len(failures) / total, 1),
        "deterministic_failure_count": sum(v for k, v in counts.items() if k != "PASS"),
        "deterministic_failure_rate": round(100 * sum(v for k, v in counts.items() if k != "PASS") / total, 1),
        "rule_notes": {
            "NO_PLAN": "plan missing entirely",
            "EMPTY_PLAN": "plan present but blank",
            "MISSING_REQUIRED_FIELD": "task missing/blank",
            "INVALID_FORMAT": "plan does not start with a Markdown heading",
        },
    })


def self_check():
    assert parse_judge('{"score": 0.7, "reasoning": "ok"}') == (0.7, "ok", True)
    assert parse_judge("garbage") == (None, None, False)
    assert parse_judge("") == (None, None, False)
    assert parse_judge('{"score": "high"}') == (None, None, False)
    assert stats([1, 1, 1, 1])["std"] == 0.0
    # silent-zero gate semantics: two samples, one judge each
    assert round(100 * statistics.fmean([0.4, 0.0]), 2) == 20.0
    assert round(100 * statistics.fmean([1.5, 0.0]), 2) == 75.0
    print("self-check OK")


STEPS = {
    "dataset": step_dataset,
    "judge": step_judge,
    "agent": step_agent,
    "aggregation": step_aggregation,
    "pipeline": step_pipeline,
    "l0": step_l0,
    "self-check": self_check,
}


def main():
    global MODEL, CLIENT
    if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
        print(__doc__)
        return 2
    if sys.argv[1] in ("judge", "agent"):
        base_url, api_key, MODEL = load_llm()
        from openai import OpenAI
        CLIENT = OpenAI(api_key=api_key, base_url=base_url)
    STEPS[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
