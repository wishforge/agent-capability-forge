#!/usr/bin/env python3
"""Minimal Agent Learning Control Plane driver — read-only S1/S2 seams.

Pulls real traces from Langfuse, reconstructs trajectories from observation
snapshots, and writes FailureSample candidates as JSONL.

Usage:
  LANGFUSE_BASE_URL=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... \
    python3 loop.py --limit 3 --names swe_planner
  python3 loop.py --self-check
"""

import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PROBE_NAMES = ("trunc-probe", "size-probe")


class LangfuseAPI:
    def __init__(self):
        self.base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
        token = base64.b64encode(
            (
                os.environ["LANGFUSE_PUBLIC_KEY"]
                + ":"
                + os.environ["LANGFUSE_SECRET_KEY"]
            ).encode()
        ).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    def get(self, path, params=None, retries=3):
        url = f"{self.base}/api/public{path}"
        for attempt in range(retries):
            resp = requests.get(url, params=params, headers=self.headers, timeout=90)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (404, 400, 401):
                resp.raise_for_status()
            time.sleep(2 * (attempt + 1))
        resp.raise_for_status()

    def list_traces(self, limit=100, names=None):
        traces = []
        page = 1
        while len(traces) < limit:
            data = self.get("/traces", {"limit": 100, "page": page})["data"]
            if not data:
                break
            for t in data:
                if t["name"] and not t["name"].startswith(PROBE_NAMES):
                    if not names or t["name"] in names:
                        traces.append(t)
                        if len(traces) >= limit:
                            return traces
            page += 1
        return traces

    def get_observations(self, trace, workers=8, last=0):
        obs_ids = json.loads(trace["observations"])
        if last:
            obs_ids = obs_ids[-last:]
        results = {}
        failed = []

        def fetch(obs_id):
            return obs_id, self.get(f"/observations/{obs_id}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, i): i for i in obs_ids}
            for future in as_completed(futures):
                obs_id = futures[future]
                try:
                    results[obs_id] = future.result()[1]
                except Exception as exc:  # keep partial traces
                    results[obs_id] = {"error": str(exc)}
                    failed.append(obs_id)
        return [results[i] for i in obs_ids if i in results], failed


def reconstruct(trace, obs):
    """Pick the deepest message snapshot; keep a compact step list."""
    snapshots = []
    for o in obs:
        snapshots.extend(_message_lists(o))
    messages = max(snapshots, key=len, default=[])

    steps = []
    for o in sorted(obs, key=lambda x: x.get("startTime") or ""):
        steps.append(
            {
                "id": o.get("id"),
                "type": o.get("type"),
                "name": o.get("name"),
                "parent": o.get("parentObservationId"),
                "status": o.get("statusMessage"),
                "input": _brief(o.get("input")),
                "output": _brief(o.get("output")),
                "error": o.get("error"),
            }
        )
    return messages, steps


def _message_lists(o):
    """Every message-list snapshot in an observation: input.state.messages and output.messages."""
    found = []
    inp, out = o.get("input"), o.get("output")
    if isinstance(inp, dict):
        state = inp.get("state")
        if isinstance(state, dict) and isinstance(state.get("messages"), list):
            found.append(state["messages"])
    if isinstance(out, dict) and isinstance(out.get("messages"), list):
        found.append(out["messages"])
    return found


def _brief(value, limit=200):
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def build_sample(trace, obs, failed_ids=()):
    messages, steps = reconstruct(trace, obs)
    task = ""
    for m in messages:
        if m.get("type") == "human" and m.get("content"):
            task = str(m["content"])[:500]
            break
    return {
        "trace_id": trace["id"],
        "name": trace["name"],
        "timestamp": trace["timestamp"],
        "task": task,
        "message_count": len(messages),
        "observation_count": len(obs),
        "failed_observation_fetches": len(failed_ids),
        "failed_observation_ids": failed_ids,
        "has_final_answer": any(
            m.get("type") == "ai" and str(m.get("content") or "").strip()
            for m in messages
        ),
        "steps": steps,
        "trajectory": messages,
    }


def self_check():
    trace = {"id": "t1", "name": "swe_planner", "timestamp": "2026-01-01T00:00:00Z",
             "observations": json.dumps(["a", "b"])}
    msgs1 = [{"type": "human", "content": "hi"}]
    msgs2 = msgs1 + [{"type": "ai", "content": None}, {"type": "tool", "content": "x"}]
    obs = [
        {"id": "a", "startTime": "2026-01-01T00:00:00Z", "input": {"state": {"messages": msgs1}}},
        {"id": "b", "startTime": "2026-01-01T00:00:01Z", "input": {"state": {"messages": msgs2}}},
    ]
    messages, _ = reconstruct(trace, obs)
    assert messages == msgs2, "must pick deepest snapshot"
    plan = {"type": "ai", "content": "## Plan"}
    out_obs = [
        {"id": "c", "startTime": "2026-01-01T00:00:02Z",
         "output": {"messages": msgs2 + [plan]}}
    ]
    sample = build_sample(trace, obs + out_obs)
    assert sample["message_count"] == 4
    assert sample["has_final_answer"] is True
    print("self-check OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--last", type=int, default=0,
                        help="fetch only the last N observations per trace")
    parser.add_argument("--names", default="swe_planner,swe_execution,reviewer,agent")
    parser.add_argument("--out", default="research/control-plane-loop/data")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        return self_check()

    api = LangfuseAPI()
    traces = api.list_traces(limit=args.limit, names={n for n in args.names.split(",") if n})
    if not traces:
        print("no matching traces", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    samples = []
    for trace in traces:
        print(f"trace {trace['id']} ({trace['name']}): fetching observations...", flush=True)
        obs, failed = api.get_observations(trace, last=args.last)
        sample = build_sample(trace, obs, failed)
        samples.append(sample)
        print(
            f"  {sample['observation_count']} obs, {sample['message_count']} messages, "
            f"{sample['failed_observation_fetches']} failed",
            flush=True,
        )

    with open(os.path.join(args.out, "samples.jsonl"), "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    summary = {
        "trace_count": len(samples),
        "total_observations": sum(s["observation_count"] for s in samples),
        "total_messages": sum(s["message_count"] for s in samples),
        "trace_ids": [s["trace_id"] for s in samples],
    }
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
