#!/usr/bin/env python3
"""S7.2 Reliable Evaluation v1: contract, L0, judge handling, aggregation, append-only runs, compare.

No production file is modified. Judge failures never become score=0.

Usage:
  python evaluation_result.py freeze-gold-v1
  python evaluation_result.py self-check
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from noise_attribution import judge_prompt, load_llm

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
GOLD_V0 = DATA / "gold-v0.jsonl"
GOLD_V1 = DATA / "gold-v1.jsonl"
EVALS_DIR = DATA / "evals"

ERROR_STATUSES = {
    "INVALID_INPUT",
    "JUDGE_ERROR",
    "JUDGE_PARSE_ERROR",
    "JUDGE_TRUNCATED",
    "INSUFFICIENT_JUDGE_EVIDENCE",
}


class EvaluationStatus(str, Enum):
    OK = "OK"
    JUDGE_ERROR = "JUDGE_ERROR"
    JUDGE_PARSE_ERROR = "JUDGE_PARSE_ERROR"
    JUDGE_TRUNCATED = "JUDGE_TRUNCATED"
    INVALID_INPUT = "INVALID_INPUT"
    SKIPPED = "SKIPPED"
    INSUFFICIENT_JUDGE_EVIDENCE = "INSUFFICIENT_JUDGE_EVIDENCE"


class AgentOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    NO_PLAN = "NO_PLAN"
    EMPTY_PLAN = "EMPTY_PLAN"
    INVALID_FORMAT = "INVALID_FORMAT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    OTHER_FAILURE = "OTHER_FAILURE"


@dataclass(frozen=True)
class JudgeConfig:
    """Explicit judge settings; no implicit defaults. Every field is recorded."""

    model: str
    temperature: float = 0.0
    max_tokens: int = 800
    judge_n: int = 5
    min_success: int = 3
    max_attempts: int = 3
    judge_prompt_version: str = "plan-vs-reference-v1"
    parser_version: str = "s72-v1"

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "judge_n": self.judge_n,
            "min_success": self.min_success,
            "max_attempts": self.max_attempts,
            "judge_prompt_version": self.judge_prompt_version,
            "parser_version": self.parser_version,
        }


@dataclass
class EvaluationResult:
    """One sample's full evaluation evidence. score is None whenever evaluation failed."""

    run_id: str
    sample_id: str
    candidate_version: str
    dataset_version: str
    agent_outcome: str | None
    evaluation_status: str
    l0: dict
    l1: dict | None
    l2: dict | None
    score: float | None
    failure_categories: list[str]
    judge_attempts: int
    raw_judge_responses: list[dict] = field(default_factory=list)
    model: str = ""
    temperature: float | None = None
    timestamp: str = ""
    all_scores: list[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    judge_skipped_reason: str | None = None
    judge_config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "sample_id": self.sample_id,
            "candidate_version": self.candidate_version,
            "dataset_version": self.dataset_version,
            "agent_outcome": self.agent_outcome,
            "evaluation_status": self.evaluation_status,
            "l0": self.l0,
            "l1": self.l1,
            "l2": self.l2,
            "score": self.score,
            "failure_categories": self.failure_categories,
            "judge_attempts": self.judge_attempts,
            "raw_judge_responses": self.raw_judge_responses,
            "model": self.model,
            "temperature": self.temperature,
            "timestamp": self.timestamp,
            "all_scores": self.all_scores,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "judge_skipped_reason": self.judge_skipped_reason,
            "judge_config": self.judge_config,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationResult":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def new_run_id(now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def l0_evaluate(task, plan) -> dict:
    """Deterministic checks, run before any LLM judge."""
    has_task = isinstance(task, str) and bool(task.strip())
    has_plan = plan is not None
    non_empty_plan = has_plan and isinstance(plan, str) and bool(plan.strip())
    valid_plan_format = non_empty_plan and plan.lstrip().startswith("#")
    if not has_task:
        outcome = AgentOutcome.MISSING_REQUIRED_FIELD.value
    elif not has_plan:
        outcome = AgentOutcome.NO_PLAN.value
    elif not non_empty_plan:
        outcome = AgentOutcome.EMPTY_PLAN.value
    elif not valid_plan_format:
        outcome = AgentOutcome.INVALID_FORMAT.value
    else:
        outcome = AgentOutcome.SUCCESS.value
    return {
        "has_task": has_task,
        "has_plan": has_plan,
        "non_empty_plan": non_empty_plan,
        "valid_plan_format": valid_plan_format,
        "required_fields_present": has_task and non_empty_plan,
        "outcome": outcome,
    }


def l1_evaluate(plan) -> dict:
    """Minimal structural/coverage checks. Not a quality score, only evidence."""
    text = plan or ""
    checks = {
        "has_markdown_heading": bool(re.search(r"(?m)^#{1,6}\s", text)),
        "has_code_fence": "```" in text,
        "min_length_200": len(text.strip()) >= 200,
    }
    return {
        "structure": checks,
        "coverage": {
            "required_elements_present": sum(checks.values()),
            "required_elements_total": len(checks),
            "coverage_ratio": round(sum(checks.values()) / len(checks), 4),
        },
    }


def classify_judge_response(content, finish_reason=None) -> dict:
    """Classify one raw judge response. Never returns score=0 on failure."""
    content = content or ""
    if not content.strip():
        return {"category": "JUDGE_EMPTY_RESPONSE", "status": "JUDGE_ERROR",
                "score": None, "reasoning": None}
    match = re.search(r"\{.*\}", content, re.DOTALL)
    payload = None
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        truncated = finish_reason == "length" or content.rfind("{") > content.rfind("}")
        category = "JUDGE_TRUNCATED" if truncated else "JUDGE_INVALID_JSON"
        status = "JUDGE_TRUNCATED" if truncated else "JUDGE_PARSE_ERROR"
        return {"category": category, "status": status, "score": None, "reasoning": None}
    if "score" not in payload:
        return {"category": "JUDGE_MISSING_SCORE", "status": "JUDGE_PARSE_ERROR",
                "score": None, "reasoning": payload.get("reasoning")}
    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not (0 <= score <= 1):
        return {"category": "JUDGE_INVALID_SCORE", "status": "JUDGE_PARSE_ERROR",
                "score": None, "reasoning": payload.get("reasoning")}
    return {"category": "OK", "status": "OK", "score": float(score),
            "reasoning": payload.get("reasoning")}


def judge_round(client, config: JudgeConfig, task: str, reference: str,
                candidate: str, round_index: int) -> dict:
    """One judge observation: up to max_attempts tries; first valid score wins."""
    attempts = []
    for attempt in range(1, config.max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": judge_prompt(task, reference, candidate)}],
                response_format={"type": "json_object"},
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            )
            content = response.choices[0].message.content or ""
            finish_reason = getattr(response.choices[0], "finish_reason", None)
        except Exception as exc:
            attempts.append({
                "round": round_index, "attempt": attempt, "category": "JUDGE_ERROR",
                "status": "JUDGE_ERROR", "raw_response": None,
                "finish_reason": None, "error": f"{type(exc).__name__}: {exc}",
                "score": None, "reasoning": None,
            })
            if attempt < config.max_attempts:
                time.sleep(1)
            continue
        parsed = classify_judge_response(content, finish_reason)
        attempts.append({
            "round": round_index, "attempt": attempt, "category": parsed["category"],
            "status": parsed["status"], "raw_response": content, "finish_reason": finish_reason,
            "error": None, "score": parsed["score"], "reasoning": parsed["reasoning"],
        })
        if parsed["category"] == "OK":
            return {"success": True, "score": parsed["score"],
                    "reasoning": parsed["reasoning"], "attempts": attempts}
    statuses = {a["status"] for a in attempts}
    if "JUDGE_ERROR" in statuses:
        status = "JUDGE_ERROR"
    elif "JUDGE_TRUNCATED" in statuses:
        status = "JUDGE_TRUNCATED"
    else:
        status = "JUDGE_PARSE_ERROR"
    return {"success": False, "score": None, "reasoning": None,
            "attempts": attempts, "status": status}


def aggregate(scores) -> dict | None:
    """Minimal aggregation: mean/median/std/min/max. Median is the primary value."""
    vals = [float(s) for s in scores if s is not None]
    if not vals:
        return None
    n = len(vals)
    return {
        "n": n,
        "mean": round(statistics.fmean(vals), 6),
        "median": round(statistics.median(vals), 6),
        "std": round(statistics.stdev(vals), 6) if n > 1 else None,
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
    }


def _empty_result(sample, run_id, config, dataset_version, candidate_version,
                  agent_outcome, status, l0, timestamp, reason=None) -> EvaluationResult:
    return EvaluationResult(
        run_id=run_id, sample_id=sample.get("sample_id", ""),
        candidate_version=candidate_version, dataset_version=dataset_version,
        agent_outcome=agent_outcome, evaluation_status=status,
        l0=l0, l1=l1_evaluate(sample.get("plan")) if sample.get("plan") is not None else None,
        l2=None, score=None, failure_categories=[],
        judge_attempts=0, raw_judge_responses=[], model=config.model,
        temperature=config.temperature, timestamp=timestamp,
        judge_skipped_reason=reason, judge_config=config.as_dict(),
    )


def evaluate_sample(sample: dict, config: JudgeConfig, run_id: str, client=None,
                    candidate_version: str = "baseline-v1",
                    dataset_version: str = "gold-v1") -> EvaluationResult:
    """Full L0 -> (skip) -> judge_n rounds -> aggregate pipeline for one sample."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    reference = sample.get("reference")
    if (not isinstance(sample.get("sample_id"), str) or not isinstance(sample.get("task"), str)
            or not isinstance(reference, str) or not reference.strip()):
        return _empty_result(sample, run_id, config, dataset_version, candidate_version,
                             None, EvaluationStatus.INVALID_INPUT.value,
                             {"outcome": "INVALID_INPUT"}, timestamp,
                             reason="dataset_invalid")
    l0 = l0_evaluate(sample.get("task"), sample.get("plan"))
    if l0["outcome"] != AgentOutcome.SUCCESS.value:
        return _empty_result(sample, run_id, config, dataset_version, candidate_version,
                             l0["outcome"], EvaluationStatus.SKIPPED.value, l0, timestamp,
                             reason="deterministic_failure")
    if client is None:
        raise ValueError("client required when L0 passes")
    rounds = [judge_round(client, config, sample["task"], reference, sample["plan"], i)
              for i in range(config.judge_n)]
    attempts = [a for r in rounds for a in r["attempts"]]
    successes = [r["score"] for r in rounds if r["success"]]
    failures = [r for r in rounds if not r["success"]]
    failed_categories = [a["category"] for r in failures for a in r["attempts"]]
    categories = list(dict.fromkeys(c for c in failed_categories if c != "OK"))
    l2 = {"success_count": len(successes), "failure_count": len(failures),
          "all_scores": successes}
    if len(successes) >= config.min_success:
        status = EvaluationStatus.OK.value
        agg = aggregate(successes)
        l2 = {**agg, "success_count": len(successes), "failure_count": len(failures)}
    elif not successes:
        status = failures[0]["status"] if failures else EvaluationStatus.JUDGE_ERROR.value
        agg = None
    else:
        status = EvaluationStatus.INSUFFICIENT_JUDGE_EVIDENCE.value
        agg = None
    return EvaluationResult(
        run_id=run_id, sample_id=sample["sample_id"],
        candidate_version=candidate_version, dataset_version=dataset_version,
        agent_outcome=AgentOutcome.SUCCESS.value, evaluation_status=status,
        l0=l0, l1=l1_evaluate(sample["plan"]), l2=l2,
        score=agg["median"] if agg else None,
        failure_categories=categories, judge_attempts=len(attempts),
        raw_judge_responses=attempts, model=config.model,
        temperature=config.temperature, timestamp=timestamp,
        all_scores=successes, success_count=len(successes), failure_count=len(failures),
        judge_config=config.as_dict(),
    )


def replay_result(result: dict | EvaluationResult) -> EvaluationResult:
    """Recompute status/score from saved raw responses; no model calls."""
    data = result.to_dict() if isinstance(result, EvaluationResult) else result
    if not data.get("raw_judge_responses") or data.get("judge_skipped_reason"):
        return EvaluationResult.from_dict(data)
    config = JudgeConfig(**{k: v for k, v in data["judge_config"].items()
                            if k in JudgeConfig.__dataclass_fields__})
    by_round = {}
    for a in data["raw_judge_responses"]:
        by_round.setdefault(a["round"], []).append(a)
    rounds = []
    for round_index in sorted(by_round):
        score = next((a["score"] for a in by_round[round_index] if a["category"] == "OK"), None)
        rounds.append({"success": score is not None, "score": score})
    successes = [r["score"] for r in rounds if r["success"]]
    agg = aggregate(successes) if len(successes) >= config.min_success else None
    if len(successes) >= config.min_success:
        status = "OK"
    elif not successes:
        statuses = {a["status"] for a in data["raw_judge_responses"]}
        status = ("JUDGE_ERROR" if "JUDGE_ERROR" in statuses
                  else "JUDGE_TRUNCATED" if "JUDGE_TRUNCATED" in statuses
                  else "JUDGE_PARSE_ERROR")
    else:
        status = "INSUFFICIENT_JUDGE_EVIDENCE"
    replayed = EvaluationResult.from_dict(data)
    replayed.evaluation_status = status
    replayed.score = agg["median"] if agg else None
    replayed.l2 = {**agg, "success_count": len(successes),
                   "failure_count": len(rounds) - len(successes)} if agg else {
        "success_count": len(successes), "failure_count": len(rounds) - len(successes),
        "all_scores": successes}
    replayed.all_scores = successes
    replayed.success_count = len(successes)
    replayed.failure_count = len(rounds) - len(successes)
    return replayed


def summarize_results(results) -> dict:
    rows = [r.to_dict() if isinstance(r, EvaluationResult) else r for r in results]
    scores = [r["score"] for r in rows if r.get("score") is not None]
    agent_outcomes = [r["agent_outcome"] for r in rows if r.get("agent_outcome") is not None]
    return {
        "n": len(rows),
        "score_stats": aggregate(scores),
        "judge_error_rate": round(sum(1 for r in rows
                                      if r["evaluation_status"] in ERROR_STATUSES) / len(rows), 4)
        if rows else None,
        "insufficient_evidence_rate": round(
            sum(1 for r in rows
                if r["evaluation_status"] == "INSUFFICIENT_JUDGE_EVIDENCE") / len(rows), 4)
        if rows else None,
        "agent_failure_rate": round(
            sum(1 for o in agent_outcomes if o != "SUCCESS") / len(agent_outcomes), 4)
        if agent_outcomes else None,
        "l0_failure_rate": round(
            sum(1 for r in rows if r.get("judge_skipped_reason") == "deterministic_failure")
            / len(rows), 4) if rows else None,
        "dataset_version": rows[0]["dataset_version"] if rows else None,
        "sample_ids": [r["sample_id"] for r in rows],
        "by_sample": [{
            "sample_id": r["sample_id"],
            "agent_outcome": r["agent_outcome"],
            "evaluation_status": r["evaluation_status"],
            "score": r["score"],
            "judge_skipped_reason": r.get("judge_skipped_reason"),
        } for r in rows],
    }


def save_run(results, metadata: dict, evals_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Append-only: create a unique run-<run_id> directory, never overwrite."""
    evals_dir = evals_dir or EVALS_DIR
    evals_dir.mkdir(parents=True, exist_ok=True)
    rows = [r.to_dict() if isinstance(r, EvaluationResult) else r for r in results]
    run_id = metadata.get("run_id") or new_run_id()
    run_dir = evals_dir / f"run-{run_id}"
    while run_dir.exists():
        run_id = new_run_id()
        run_dir = evals_dir / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **metadata,
        "summary": summarize_results(rows),
    }
    with open(run_dir / "run.json", "x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(run_dir / "results.jsonl", "x", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return run_dir


def load_run(run_dir: pathlib.Path | str) -> tuple[dict, list[dict]]:
    run_dir = pathlib.Path(run_dir)
    metadata = json.loads((run_dir / "run.json").read_text())
    results = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    return metadata, results


def compare_baseline_candidate(baseline_results, candidate_results) -> dict:
    """Reliable comparison only: never PASS just because candidate >= baseline."""
    b = summarize_results(baseline_results)
    c = summarize_results(candidate_results)
    reasons = []
    if b["dataset_version"] != c["dataset_version"] or b["sample_ids"] != c["sample_ids"]:
        reasons.append("dataset_mismatch")
    if any(r["evaluation_status"] in ERROR_STATUSES for r in b["by_sample"] + c["by_sample"]):
        reasons.append("insufficient_evidence")
    b_fail = b["agent_failure_rate"] or 0.0
    c_fail = c["agent_failure_rate"] or 0.0
    if b_fail or c_fail:
        reasons.append("critical_failure_rate_nonzero")
    b_med = b["score_stats"]["median"] if b["score_stats"] else None
    c_med = c["score_stats"]["median"] if c["score_stats"] else None
    delta_median = round(c_med - b_med, 6) if (b_med is not None and c_med is not None) else None
    noise = max(b["score_stats"]["std"] or 0.0, c["score_stats"]["std"] or 0.0) \
        if (b["score_stats"] and c["score_stats"]) else None
    if reasons:
        verdict = "INCONCLUSIVE"
    elif delta_median is None or noise is None:
        reasons.append("missing_scores")
        verdict = "INCONCLUSIVE"
    elif abs(delta_median) <= noise:
        reasons.append("variance_too_large")
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS" if delta_median > 0 else "FAIL"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "baseline": b,
        "candidate": c,
        "delta": {
            "median": delta_median,
            "mean": round(c["score_stats"]["mean"] - b["score_stats"]["mean"], 6)
            if b["score_stats"] and c["score_stats"] else None,
            "agent_failure_rate": round(c_fail - b_fail, 4),
            "judge_error_rate": round((c["judge_error_rate"] or 0.0)
                                      - (b["judge_error_rate"] or 0.0), 4),
        },
    }


def freeze_gold_v1() -> pathlib.Path:
    """Freeze gold-v1 from gold-v0 (same 6 samples, fixed ids/order/schema). Never overwrites."""
    gold0 = [json.loads(line) for line in GOLD_V0.read_text().splitlines()]
    frozen = []
    for i, r in enumerate(gold0):
        body = json.dumps({"task": r["task"], "reference": r["reference"]},
                          sort_keys=True, ensure_ascii=False)
        frozen.append({
            "sample_id": f"gold-v1-{i:03d}",
            "task": r["task"],
            "reference": r["reference"],
            "dataset_version": "gold-v1",
            "metadata": {
                "source_sample_id": r["sample_id"],
                "source_trace_id": r["metadata"]["source_trace_id"],
                "source": "data/gold-v0.jsonl",
                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "frozen_at": datetime.now().isoformat(timespec="seconds"),
            },
        })
    if GOLD_V1.exists():
        existing = [json.loads(line) for line in GOLD_V1.read_text().splitlines()]
        existing_core = [
            {**{k: v for k, v in r.items() if k != "metadata"},
             "metadata": {k: v for k, v in r["metadata"].items() if k != "frozen_at"}}
            for r in existing
        ]
        frozen_core = [
            {**{k: v for k, v in r.items() if k != "metadata"},
             "metadata": {k: v for k, v in r["metadata"].items() if k != "frozen_at"}}
            for r in frozen
        ]
        assert existing_core == frozen_core, \
            "gold-v1.jsonl exists but differs from gold-v0; refusing to overwrite"
        print(f"{GOLD_V1} already frozen; not overwritten")
    else:
        GOLD_V1.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in frozen) + "\n")
        print(f"wrote {GOLD_V1}")
    return GOLD_V1


def gold_v1_records() -> list[dict]:
    return [json.loads(line) for line in GOLD_V1.read_text().splitlines()]


def self_check():
    assert classify_judge_response("")["category"] == "JUDGE_EMPTY_RESPONSE"
    assert classify_judge_response("not json")["category"] == "JUDGE_INVALID_JSON"
    assert classify_judge_response('{"score": 0.7', finish_reason="length")["category"] == \
        "JUDGE_TRUNCATED"
    assert classify_judge_response('{"score": 0.7, "reasoning": "ok"}')["score"] == 0.7
    assert l0_evaluate("task", None)["outcome"] == "NO_PLAN"
    assert l0_evaluate("", "## plan")["outcome"] == "MISSING_REQUIRED_FIELD"
    assert aggregate([0.1, 0.4, 0.9])["median"] == 0.4
    assert new_run_id() != new_run_id()
    assert summarize_results([])["n"] == 0
    print("self-check OK")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    if sys.argv[1] == "freeze-gold-v1":
        freeze_gold_v1()
    elif sys.argv[1] == "self-check":
        self_check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
