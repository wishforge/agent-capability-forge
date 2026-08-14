"""M12 - cost collector + NV / V-delta sensitivity. Formulas per frozen design."""

from __future__ import annotations

import json
from pathlib import Path


def _usd(record: dict, prices: dict) -> dict:
    m = record.get("runtime_metrics") or {}
    tokens = m.get("tokens") or {}
    inp = tokens.get("input_tokens") or 0
    out = tokens.get("output_tokens") or 0
    sandbox_min = (record.get("sandbox_elapsed_s") or 0) / 60.0
    human_min = record.get("human_min", 0)
    return {
        "input_tokens": inp, "output_tokens": out, "human_min": human_min,
        "sandbox_min": sandbox_min,
        "usd": (inp * prices["input_token_usd"] + out * prices["output_token_usd"]
                + human_min * prices["human_minute_usd"] + sandbox_min * prices["sandbox_minute_usd"]),
    }


def collect(run_records: list[dict], prices: dict, family: dict,
            cost_events: list[dict], values: dict) -> dict:
    future_ids = {t["task_id"] for t in family["future_tasks"]}
    formation_ids = {t["task_id"] for t in family["formation_tasks"]}
    costs = {}
    formation_arm_cost = {"b2": 0.0, "b3": 0.0}
    for rec in run_records:
        c = _usd(rec, prices)
        costs[rec["run_id"]] = c
        if rec["arm"] in ("b2", "b3") and rec["task_id"] in formation_ids:
            formation_arm_cost[rec["arm"]] += c["usd"]

    # non-run events: generation LLM call, freeze human time, validation/evaluation sandbox
    generation_usd = 0.0
    freeze_human_min = 0.0
    validation_usd = 0.0
    for ev in cost_events:
        kind = ev.get("kind")
        if kind == "generation":
            tokens = (ev.get("runtime_metrics") or {}).get("tokens") or {}
            generation_usd += ((tokens.get("input_tokens") or 0) * prices["input_token_usd"]
                               + (tokens.get("output_tokens") or 0) * prices["output_token_usd"])
        elif kind == "freeze":
            freeze_human_min += ev.get("human_min", 0)
            generation_usd += (ev.get("human_min", 0) * prices["human_minute_usd"])
        elif kind in ("validation", "evaluation"):
            validation_usd += (ev.get("sandbox_min", 0) * prices["sandbox_minute_usd"])

    nv = {}
    for arm in ("b2", "b3"):
        future = [r for r in run_records if r["arm"] == arm and r["task_id"] in future_ids]
        exec_usd = sum(costs[r["run_id"]]["usd"] for r in future)
        task_value = {v: sum(values[v] for r in future if (r.get("oracle") or {}).get("verdict") == "PASS")
                      for v in ("low", "mid", "high")}
        formation_usd = formation_arm_cost[arm] + (generation_usd if arm == "b2" else generation_usd)
        validation = validation_usd if arm == "b3" else 0.0
        nv[arm] = {
            "future_runs": len(future),
            "future_success": sum(1 for r in future if (r.get("oracle") or {}).get("verdict") == "PASS"),
            "task_value": task_value,
            "future_execution_usd": exec_usd,
            "formation_usd": formation_usd + (freeze_human_min * prices["human_minute_usd"]),
            "validation_usd": validation,
            "maintenance_usd": 0.0,
            "wrong_capability_usd": 0.0,
            "nv": {v: task_value[v] - exec_usd - formation_usd - validation for v in ("low", "mid", "high")},
        }

    tco_b2 = nv["b2"]["formation_usd"] + nv["b2"]["future_execution_usd"]
    sensitivity = []
    for v in ("low", "mid", "high"):
        for d in family["deltas"]:
            delta = d * tco_b2
            verdict = "B3_superior" if nv["b3"]["nv"][v] - nv["b2"]["nv"][v] > delta else "not_superior"
            sensitivity.append({"v": v, "delta": d, "delta_usd": round(delta, 6),
                                "nv_delta": round(nv["b3"]["nv"][v] - nv["b2"]["nv"][v], 6),
                                "verdict": verdict})
    verdicts = {s["verdict"] for s in sensitivity}
    return {
        "schema_version": "cost_v1",
        "per_run_usd": costs,
        "formation_arm_usd": formation_arm_cost,
        "generation_usd": generation_usd,
        "validation_usd": validation_usd,
        "b0_baseline_note": "rehearsal runs B2/B3 only; NV reported without TaskValue_B0 delta",
        "nv": nv,
        "sensitivity": sensitivity,
        "value_sensitive": len(verdicts) > 1,
    }
