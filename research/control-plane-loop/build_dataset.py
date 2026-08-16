#!/usr/bin/env python3
"""S3: turn production traces into a (task, reference plan) dataset.

Reads LANGFUSE_* env vars (not persisted anywhere). The final plan comes from
the trace list API output; the task text comes from the first observation's
state snapshot. Writes data/dataset.jsonl.
"""

import json
import os
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

ROOT = pathlib.Path(__file__).resolve().parent


def api(path, params=None):
    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    resp = requests.get(f"{base}/api/public{path}", params=params, auth=auth, timeout=90)
    resp.raise_for_status()
    return resp.json()


def list_swe_planner_traces(limit):
    traces = []
    page = 1
    while len(traces) < limit:
        data = api("/traces", {"limit": 100, "page": page})["data"]
        if not data:
            break
        traces.extend(t for t in data if t["name"] == "swe_planner")
        page += 1
    return traces[:limit]


def task_from_observation(obs):
    state = (obs.get("input") or {}).get("state") if isinstance(obs.get("input"), dict) else None
    for m in (state or {}).get("messages") or []:
        if m.get("type") == "human" and m.get("content"):
            return str(m["content"])
    return None


def plan_from_trace(trace):
    output = trace.get("output")
    messages = (output or {}).get("messages") if isinstance(output, dict) else None
    if isinstance(messages, list) and messages:
        content = messages[-1].get("content")
        if content:
            return str(content)
    return None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    traces = list_swe_planner_traces(limit)
    records = []
    failures = []
    for trace in traces:
        obs_ids = json.loads(trace["observations"])
        obs = _fetch_first(obs_ids, 10)
        task = next((t for o in obs if (t := task_from_observation(o))), None)
        plan = plan_from_trace(trace)
        if task and plan:
            records.append(
                {"trace_id": trace["id"], "task": task, "plan": plan}
            )
            print(f"{trace['id']}: task={len(task)} plan={len(plan)}", flush=True)
        else:
            print(f"{trace['id']}: SKIP task={bool(task)} plan={bool(plan)}", flush=True)
            failures.append(
                {
                    "trace_id": trace["id"],
                    "name": trace["name"],
                    "task_found": bool(task),
                    "plan_found": bool(plan),
                    "observation_count": len(json.loads(trace["observations"])),
                }
            )

    out = ROOT / "data" / "dataset.jsonl"
    with open(out, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(ROOT / "data" / "failures.jsonl", "w") as f:
        for r in failures:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)}/{len(traces)} records to {out}")


def _fetch_first(obs_ids, count, workers=8):
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(api, f"/observations/{i}"): i for i in obs_ids[:count]}
        for future in as_completed(futures):
            obs_id = futures[future]
            try:
                results[obs_id] = future.result()
            except Exception as exc:
                results[obs_id] = {"error": str(exc)}
    return [results[i] for i in obs_ids[:count] if i in results]


if __name__ == "__main__":
    main()
