#!/usr/bin/env python3
"""S4+S5: DSPy MIPROv2 prompt optimization + same-valset regression.

Dataset: data/dataset.jsonl (task, reference plan) from production traces.
Judge metric: DeepSeek LLM comparing candidate plan to the reference plan.
Reads the DeepSeek key from ~/.codex/config.toml at runtime, never prints it.
Writes data/candidate_program.json, data/candidate.json, data/regression.json.
"""

import json
import pathlib
import re
import sys
import tomllib

import dspy
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent
JUDGE_CLIENT = None
JUDGE_MODEL = None


def load_llm():
    cfg = tomllib.loads(pathlib.Path("/Users/david/.codex/config.toml").read_text())
    prov = cfg["model_providers"]["deepseek"]
    return (
        prov["base_url"].rstrip("/"),
        prov["experimental_bearer_token"],
        cfg.get("model", "deepseek-v4-flash"),
    )


class PlanWriter(dspy.Signature):
    """Write a concrete, codebase-grounded implementation plan for the given software task."""

    task: str = dspy.InputField()
    plan: str = dspy.OutputField(desc="Markdown implementation plan")


def judge_metric(example, prediction, trace=None):
    prompt = (
        "You are grading whether a candidate implementation plan is accurate and "
        "useful for the task, compared against the reference plan written by an "
        "agent that inspected the codebase.\n\n"
        f"TASK:\n{example.task}\n\n"
        f"REFERENCE PLAN:\n{example.plan}\n\n"
        f"CANDIDATE PLAN:\n{prediction.plan}\n\n"
        'Respond in JSON: {"score": <0-1 number>, "reasoning": "<brief comparison>"}'
    )
    response = JUDGE_CLIENT.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=800,
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        payload = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        payload = {}
    return payload.get("score", 0.0)


def main():
    global JUDGE_CLIENT, JUDGE_MODEL
    base_url, api_key, model = load_llm()
    lm = dspy.LM(
        model=f"openai/{model}",
        api_base=base_url,
        api_key=api_key,
        max_tokens=8192,  # reasoning model spends tokens before emitting text
    )
    dspy.configure(lm=lm)
    JUDGE_CLIENT = OpenAI(api_key=api_key, base_url=base_url)
    JUDGE_MODEL = model

    records = [
        json.loads(line)
        for line in (ROOT / "data" / "dataset.jsonl").read_text().splitlines()
    ]
    records.sort(key=lambda r: len(r["plan"]), reverse=True)
    trainset = [
        dspy.Example(task=r["task"], plan=r["plan"]).with_inputs("task")
        for r in records[:4]
    ]
    valset = [
        dspy.Example(task=r["task"], plan=r["plan"]).with_inputs("task")
        for r in records[4:6]
    ]
    print(f"trainset={len(trainset)} valset={len(valset)}", flush=True)

    student = dspy.Predict(PlanWriter)
    baseline = dspy.Evaluate(metric=judge_metric, devset=valset, num_threads=1)
    baseline_result = baseline(student)
    baseline_score, baseline_results = baseline_result.score, baseline_result.results

    teleprompter = dspy.MIPROv2(
        metric=judge_metric,
        auto=None,
        num_candidates=2,
        max_bootstrapped_demos=1,
        max_labeled_demos=1,
        num_threads=1,
        verbose=True,
    )
    compiled = teleprompter.compile(
        student,
        trainset=trainset,
        valset=valset,
        teacher=student,
        num_trials=4,
        max_bootstrapped_demos=1,
        max_labeled_demos=1,
        minibatch_size=2,
    )
    candidate_result = dspy.Evaluate(
        metric=judge_metric, devset=valset, num_threads=1
    )(compiled)
    candidate_score, candidate_results = candidate_result.score, candidate_result.results

    artifact = ROOT / "data" / "candidate_program.json"
    compiled.save(artifact)
    candidate = {
        "artifact": str(artifact),
        "prompt": compiled.demos[-1].get("instructions") if compiled.demos else None,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "baseline_examples": [
            {"task": e.task[:200], "score": s} for e, _, s in baseline_results
        ],
        "candidate_examples": [
            {"task": e.task[:200], "score": s} for e, _, s in candidate_results
        ],
    }
    with open(ROOT / "data" / "candidate.json", "w") as f:
        json.dump(candidate, f, indent=2, ensure_ascii=False)
    with open(ROOT / "data" / "regression.json", "w") as f:
        json.dump(
            {
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "gate": candidate_score >= baseline_score,
            },
            f,
            indent=2,
        )
    print(
        json.dumps(
            {
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "gate": candidate_score >= baseline_score,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    sys.exit(main())
