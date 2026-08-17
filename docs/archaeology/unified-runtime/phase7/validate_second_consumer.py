#!/usr/bin/env python3
"""Phase 7 second-consumer protocol replay (offline, read-only).

Replays the swe-planner plan-writer evaluation (control-plane-loop S7.3)
through the generic protocol semantics frozen in doc 57
(Candidate -> Evaluation -> Evidence -> Outcome -> Regression -> Attribution
-> Promotion Gate -> Provenance). Reads only
research/control-plane-loop/data, writes only under
docs/archaeology/deepseek-harness/evaluation/artifacts/phase7-second-consumer.

No live provider call. No modification of consumer-1 or consumer-2 code.
The policy used here is a REPLAY_ONLY policy: it does not retroactively
certify the original S7.3 experiment (which calibrated its noise threshold
after the runs).

Usage:
  python3 validate_second_consumer.py [--out <dir>] [--self-check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[4]
CPL_DATA = REPO / "research" / "control-plane-loop" / "data"
DEFAULT_OUT = (
    REPO
    / "docs"
    / "archaeology"
    / "deepseek-harness"
    / "evaluation"
    / "artifacts"
    / "phase7-second-consumer"
)

BASELINE = "baseline-planwriter-v1"
CANDIDATES = [
    "candidate_bad_v1",
    "candidate_bad_v2",
    "candidate_good_v1",
    "candidate_neutral_v1",
]
ERROR_STATUSES = {
    "INVALID_INPUT",
    "JUDGE_ERROR",
    "JUDGE_PARSE_ERROR",
    "JUDGE_TRUNCATED",
    "INSUFFICIENT_JUDGE_EVIDENCE",
}

# Consumer-1-specific tokens that must never appear in the generic protocol
# layer. The replay tool emits protocol objects only; this list is the audit
# vocabulary, not protocol data.
CONSUMER1_TOKENS = (
    "cal-26",
    "task-judge",
    "b-prime",
    "prompt-b-v2",
    "wilson",
    "model_studio",
    "qwen3.7-plus",
    "promotion-policy-e7",
    "system_prompt_snapshot",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def load_run(run_dir: pathlib.Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "run.json").read_text())
    rows = read_jsonl(run_dir / "results.jsonl")
    return meta, rows


def s73_runs() -> dict[str, dict[int, tuple[dict, list[dict]]]]:
    runs: dict[str, dict[int, tuple[dict, list[dict]]]] = {}
    for d in sorted((CPL_DATA / "evals").iterdir()):
        if not d.is_dir() or not (d / "run.json").exists():
            continue
        meta, rows = load_run(d)
        if (
            meta.get("experiment") == "S7.3"
            and meta.get("dataset_version") == "gold-v2"
            and meta.get("candidate_version") in (BASELINE, *CANDIDATES)
        ):
            runs.setdefault(meta["candidate_version"], {})[int(meta["repeat"])] = (
                meta,
                rows,
            )
    return runs


def candidate_objects() -> list[dict]:
    out = []
    for version in (BASELINE, *CANDIDATES):
        path = CPL_DATA / "candidates" / f"{version}.jsonl"
        rows = read_jsonl(path)
        instruction = rows[0]["instruction"]
        out.append(
            {
                "object": "Candidate",
                "candidate_id": version,
                "baseline_ref": None if version == BASELINE else BASELINE,
                "change_type": "PROMPT",
                "change_ref": f"sha256:{sha256_bytes(instruction.encode())}",
                "artifact_ref": str(path.relative_to(REPO)),
                "artifact_sha256": sha256_file(path),
                "dataset_id": "gold-v2",
                "dataset_version": "gold-v2",
                "n_samples": len(rows),
                "n_l0_success": sum(r["l0_outcome"] == "SUCCESS" for r in rows),
                "status": "EVALUATED",
            }
        )
    return out


def map_outcome(row: dict) -> dict:
    status = row["evaluation_status"]
    if status == "OK":
        return {"class": "ACCEPT", "verdict": "PASS", "error_kind": None}
    if status == "SKIPPED":
        return {"class": "REJECT", "verdict": "FAIL", "error_kind": "DETERMINISTIC"}
    if status == "INVALID_INPUT":
        return {"class": "REJECT", "verdict": "INCONCLUSIVE", "error_kind": "INVALID_INPUT"}
    if status == "INSUFFICIENT_JUDGE_EVIDENCE":
        return {"class": "REJECT", "verdict": "INCONCLUSIVE", "error_kind": "INSUFFICIENT_EVIDENCE"}
    if status == "JUDGE_ERROR":
        return {"class": "REJECT", "verdict": None, "error_kind": "TRANSPORT"}
    return {"class": "REJECT", "verdict": None, "error_kind": "CONTRACT"}


def protocol_objects(runs: dict) -> list[dict]:
    objects = []
    for version, repeats in runs.items():
        for repeat, (meta, rows) in sorted(repeats.items()):
            objects.append(
                {
                    "object": "EvaluationRun",
                    "run_id": meta["run_id"],
                    "candidate_id": version,
                    "dataset_version": meta["dataset_version"],
                    "repeat": repeat,
                    "fixed_conditions": {
                        "evaluation_contract_version": meta.get("evaluation_contract_version"),
                        "judge_version": meta.get("judge_version"),
                        "judge_n": meta.get("judge_n"),
                        "aggregation": meta.get("aggregation"),
                        "temperature": meta.get("temperature"),
                    },
                    "policy_ref": "phase7-second-consumer-replay-v1",
                }
            )
            for row in rows:
                objects.append(
                    {
                        "object": "Evidence",
                        "evidence_id": f"{meta['run_id']}:{row['sample_id']}",
                        "run_id": meta["run_id"],
                        "case_id": row["sample_id"],
                        "arm": version,
                        "outcome": map_outcome(row),
                        "score": row.get("score"),
                        "failure_categories": row.get("failure_categories", []),
                        "judge_attempts": row.get("judge_attempts"),
                        "artifact_ref": f"research/control-plane-loop/data/evals/{meta['run_id']}/results.jsonl",
                    }
                )
    return objects


def regression_findings(runs: dict) -> list[dict]:
    findings = []
    for candidate in CANDIDATES:
        for repeat in sorted(runs[BASELINE]):
            b_meta, b_rows = runs[BASELINE][repeat]
            c_meta, c_rows = runs[candidate][repeat]
            b_by_sample = {r["sample_id"]: r for r in b_rows}
            for c_row in c_rows:
                b_row = b_by_sample.get(c_row["sample_id"])
                b_score = b_row.get("score") if b_row else None
                c_score = c_row.get("score")
                if b_row is None or b_score is None or c_score is None:
                    change_class = "UNCLASSIFIED"
                    delta = None
                else:
                    delta = round(c_score - b_score, 6)
                    change_class = (
                        "IMPROVED"
                        if delta > 0
                        else "REGRESSED"
                        if delta < 0
                        else "UNCHANGED"
                    )
                findings.append(
                    {
                        "object": "RegressionFinding",
                        "finding_id": f"{BASELINE}:{candidate}:r{repeat}:{c_row['sample_id']}",
                        "case_id": c_row["sample_id"],
                        "baseline_ref": BASELINE,
                        "candidate_ref": candidate,
                        "repeat": repeat,
                        "baseline_score": b_score,
                        "candidate_score": c_score,
                        "delta": delta,
                        "change_class": change_class,
                        "classification_scheme_version": "score-level-v1",
                        "evidence_refs": [
                            f"{b_meta['run_id']}:{c_row['sample_id']}",
                            f"{c_meta['run_id']}:{c_row['sample_id']}",
                        ],
                    }
                )
    return findings


def attribution_objects(gate: dict) -> list[dict]:
    return [
        {
            "object": "Attribution",
            "attribution_id": f"phase7:{candidate}",
            "candidate_ref": candidate,
            "policy_ref": "phase7-second-consumer-replay-v1",
            "decision": value["attribution"]["primary"],
            "expressible": value["attribution"]["expressible"],
            "evidence_refs": {
                "runs": sorted(value["pairs"]),
            },
        }
        for candidate, value in gate.items()
    ]


def pair_gate(b_meta: dict, b_rows: list[dict], c_meta: dict, c_rows: list[dict],
              noise: float) -> dict:
    """Generic gate for one paired repeat (protocol doc 57 sections 8-9)."""
    bs, cs = b_meta["summary"], c_meta["summary"]
    reasons: list[str] = []
    if bs.get("dataset_version") != cs.get("dataset_version") or bs.get("sample_ids") != cs.get("sample_ids"):
        return {"mechanical": "INCONCLUSIVE", "protocol": "HOLD", "reasons": ["dataset_mismatch"]}
    b_err = [r for r in b_rows if r["evaluation_status"] in ERROR_STATUSES]
    c_err = [r for r in c_rows if r["evaluation_status"] in ERROR_STATUSES]
    if b_err or c_err:
        reasons = [
            "insufficient_evidence",
            f"baseline_errors={len(b_err)}",
            f"candidate_errors={len(c_err)}",
        ]
        return {"mechanical": "INCONCLUSIVE", "protocol": "HOLD", "reasons": reasons}
    b_med = bs["score_stats"]["median"] if bs.get("score_stats") else None
    c_med = cs["score_stats"]["median"] if cs.get("score_stats") else None
    if b_med is None or c_med is None:
        return {"mechanical": "INCONCLUSIVE", "protocol": "HOLD", "reasons": ["missing_scores"]}
    b_l0 = bs.get("l0_failure_rate") or 0.0
    c_l0 = cs.get("l0_failure_rate") or 0.0
    b_fail = bs.get("agent_failure_rate") or 0.0
    c_fail = cs.get("agent_failure_rate") or 0.0
    if c_l0 > b_l0 or c_fail > b_fail:
        return {"mechanical": "FAIL", "protocol": "REJECT", "reasons": ["critical_regression"]}
    delta = round(c_med - b_med, 6)
    if delta < -noise:
        return {
            "mechanical": "FAIL",
            "protocol": "REJECT",
            "reasons": ["stable_lower_score"],
            "delta_median": delta,
        }
    if abs(delta) <= noise:
        return {
            "mechanical": "INCONCLUSIVE",
            "protocol": "HOLD",
            "reasons": ["variance_too_large"],
            "delta_median": delta,
        }
    return {
        "mechanical": "PASS",
        # PROMOTE requires governance (registered policy + manifest) and
        # consumer-declared target effectiveness in addition to delta > noise.
        "protocol": "HOLD",
        "reasons": ["stable_improvement", "governance_missing"],
        "delta_median": delta,
        "effectiveness_met": True,
    }


def combined_decision(pairs: list[dict]) -> dict:
    protocols = [p["protocol"] for p in pairs]
    if "REJECT" in protocols:
        return {
            "decision": "REJECT",
            "rule": "any REJECT pair -> REJECT",
            "counts": {k: protocols.count(k) for k in ("PROMOTE", "HOLD", "REJECT")},
        }
    if all(p == "PROMOTE" for p in protocols):
        return {"decision": "PROMOTE", "rule": "all pairs PROMOTE", "counts": {"PROMOTE": len(protocols), "HOLD": 0, "REJECT": 0}}
    return {
        "decision": "HOLD",
        "rule": "no REJECT and not all PROMOTE -> HOLD",
        "counts": {k: protocols.count(k) for k in ("PROMOTE", "HOLD", "REJECT")},
    }


def attribution(candidate: str, runs: dict, pairs: dict[int, dict], noise: float) -> dict:
    base_medians = [
        runs[BASELINE][r][0]["summary"]["score_stats"]["median"]
        for r in sorted(runs[BASELINE])
        if runs[BASELINE][r][0]["summary"].get("score_stats")
    ]
    cand_medians = [
        runs[candidate][r][0]["summary"]["score_stats"]["median"]
        for r in sorted(runs[candidate])
        if runs[candidate][r][0]["summary"].get("score_stats")
    ]
    regression_pairs = [r for r, p in pairs.items() if "stable_lower_score" in p["reasons"]]
    insufficient_pairs = [r for r, p in pairs.items() if "insufficient_evidence" in p["reasons"]]
    expressible = {
        "BASELINE_INSTABILITY": len(base_medians) > 1 and statistics.stdev(base_medians) > 0,
        "PROVIDER_NONDETERMINISM": len(cand_medians) > 1 and statistics.stdev(cand_medians) > 0,
        "INSUFFICIENT_EVIDENCE": bool(insufficient_pairs),
        "CANDIDATE_REGRESSION_SCORE_LEVEL": bool(regression_pairs),
        "CANDIDATE_REGRESSION_VERDICT_LEVEL": False,
    }
    if regression_pairs and not insufficient_pairs:
        primary = "CANDIDATE_REGRESSION (score-level strict)"
    elif regression_pairs:
        primary = "CANDIDATE_REGRESSION (score-level strict) + INSUFFICIENT_EVIDENCE"
    elif insufficient_pairs:
        primary = "INSUFFICIENT_EVIDENCE"
    else:
        primary = "PROVIDER_NONDETERMINISM / BASELINE_INSTABILITY"
    return {
        "candidate_id": candidate,
        "primary": primary,
        "expressible": expressible,
        "baseline_repeat_medians": base_medians,
        "candidate_repeat_medians": cand_medians,
        "regression_pairs": regression_pairs,
        "insufficient_pairs": insufficient_pairs,
        "note": (
            "verdict-level strict-stability requires per-case binary verdicts; "
            "consumer-2 facts are continuous scores, so that rule is UNKNOWN/"
            "not-applicable and score-level strictness is used."
        ),
    }


def provenance(runs: dict) -> dict:
    hashes = {}
    for version, repeats in runs.items():
        for repeat, (meta, rows) in sorted(repeats.items()):
            run_dir = CPL_DATA / "evals" / f"run-{meta['run_id']}"
            hashes[f"{version}:r{repeat}:run.json"] = sha256_file(run_dir / "run.json")
            hashes[f"{version}:r{repeat}:results.jsonl"] = sha256_file(run_dir / "results.jsonl")
    for version in (BASELINE, *CANDIDATES):
        path = CPL_DATA / "candidates" / f"{version}.jsonl"
        hashes[f"candidate:{version}"] = sha256_file(path)
    hashes["dataset:gold-v2"] = sha256_file(CPL_DATA / "gold-v2.jsonl")
    return {
        "source_hashes": hashes,
        "registered_policy": {
            "status": "MISSING",
            "note": "original S7.3 experiment has no frozen policy file or commit ref; replay policy is validation-only",
        },
        "manifest": {"status": "MISSING"},
        "git_anchor": None,
        "recompute": "python3 docs/archaeology/unified-runtime/phase7/validate_second_consumer.py",
    }


def binding_audit(objects: list[dict], gate: dict) -> dict:
    text = json.dumps(objects, ensure_ascii=False).lower() + json.dumps(gate, ensure_ascii=False).lower()
    hits = {token: text.count(token) for token in CONSUMER1_TOKENS if token in text}
    return {
        "scanned": "protocol objects + replay gate",
        "forbidden_tokens": list(CONSUMER1_TOKENS),
        "hits": hits,
        "pass": not hits,
    }


def run(out_dir: pathlib.Path) -> dict:
    runs = s73_runs()
    if set(runs) != {BASELINE, *CANDIDATES}:
        raise SystemExit(f"expected 5 candidate versions, got {sorted(runs)}")
    base_medians = [
        runs[BASELINE][r][0]["summary"]["score_stats"]["median"]
        for r in sorted(runs[BASELINE])
    ]
    noise = round(statistics.stdev(base_medians), 4)
    policy = {
        "policy_id": "phase7-second-consumer-replay-v1",
        "pre_registration_ref": "REPLAY_ONLY (not the original S7.3 experiment)",
        "dataset": "gold-v2",
        "baseline_ref": BASELINE,
        "target": "gold-v2 median plan quality",
        "effectiveness_rule": "median delta > noise",
        "safety_rule": "no L0/agent failure increase; no stable negative delta beyond noise",
        "governance_rule": "registered policy bytes + manifest + source hashes (consumer-2 original run: MISSING)",
        "noise": noise,
        "noise_source": "baseline repeat medians only (std of 5 baseline runs)",
        "decision_semantics": "PROMOTE / HOLD / REJECT (doc 57 section 9)",
    }

    gate: dict[str, dict] = {}
    for candidate in CANDIDATES:
        pairs = {}
        for repeat in sorted(runs[BASELINE]):
            b_meta, b_rows = runs[BASELINE][repeat]
            c_meta, c_rows = runs[candidate][repeat]
            pairs[repeat] = pair_gate(b_meta, b_rows, c_meta, c_rows, noise)
        gate[candidate] = {
            "pairs": pairs,
            "combined": combined_decision(list(pairs.values())),
            "attribution": attribution(candidate, runs, pairs, noise),
        }

    objects = [
        *candidate_objects(),
        *protocol_objects(runs),
        *regression_findings(runs),
        *attribution_objects(gate),
    ]
    prov = provenance(runs)
    audit = binding_audit(objects, {"policy": policy, "gate": gate, "provenance": prov})

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "protocol-objects.jsonl", "w") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    with open(out_dir / "replay-gate.json", "w") as f:
        json.dump({"policy": policy, "gate": gate, "provenance": prov}, f, indent=2, ensure_ascii=False)
    with open(out_dir / "binding-audit.json", "w") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)

    summary = {
        "consumer": "swe-planner plan-writer (control-plane-loop S7.3)",
        "policy_ref": policy["policy_id"],
        "noise": noise,
        "combined_decisions": {c: gate[c]["combined"]["decision"] for c in CANDIDATES},
        "mechanical_counts": {
            c: {
                k: sum(1 for p in gate[c]["pairs"].values() if p["mechanical"] == k)
                for k in ("PASS", "FAIL", "INCONCLUSIVE")
            }
            for c in CANDIDATES
        },
        "binding_audit_pass": audit["pass"],
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def self_check() -> int:
    # outcome mapping
    assert map_outcome({"evaluation_status": "OK"}) == {"class": "ACCEPT", "verdict": "PASS", "error_kind": None}
    assert map_outcome({"evaluation_status": "JUDGE_ERROR"})["error_kind"] == "TRANSPORT"
    assert map_outcome({"evaluation_status": "JUDGE_TRUNCATED"})["error_kind"] == "CONTRACT"
    assert map_outcome({"evaluation_status": "INSUFFICIENT_JUDGE_EVIDENCE"})["verdict"] == "INCONCLUSIVE"
    # gate: stable lower score -> REJECT; evidence error first -> HOLD
    def fake(med, errors):
        return {
            "summary": {
                "dataset_version": "gold-v2",
                "sample_ids": ["a"],
                "score_stats": {"median": med},
                "l0_failure_rate": 0.0,
                "agent_failure_rate": 0.0,
            },
            "rows": [{"evaluation_status": s} for s in errors],
        }

    b_meta = fake(0.2, [])
    c_meta = fake(0.0, [])
    assert pair_gate(b_meta, b_meta["rows"], c_meta, c_meta["rows"], 0.04)["protocol"] == "REJECT"
    assert pair_gate(
        b_meta,
        b_meta["rows"],
        fake(0.1, ["JUDGE_ERROR"]),
        [{"evaluation_status": "JUDGE_ERROR"}],
        0.04,
    )["protocol"] == "HOLD"
    # forbidden audit catches planted tokens
    assert binding_audit([{"x": "cal-26"}], {})["hits"] == {"cal-26": 1}
    assert binding_audit([{"x": "gold-v2"}], {})["pass"] is True
    print("self-check OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    run(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
