"""Parse Codex rollout JSONL into normalized execution/identity/review data.

This module (with metrics.py and main.py) is the ONLY place that reads the
Codex native runtime format. Everything downstream consumes Bundle only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

PHASES = ("task-contract", "explorer", "worker-plan", "plan-review",
          "plan-evidence", "worker", "result-review")
PREFIXES = ("worker:", "result-review:", "plan-review:", "explorer:",
            "task-contract:", "worker-plan:", "plan-evidence:")
ROLLOUT_NAME = re.compile(r"rollout-\d+T\d+-(?P<thread_id>[0-9a-f-]+)\.jsonl$")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                out.append(str(part.get("text") or part.get("type") or ""))
        return "\n".join(out)
    return str(content)


def _first(lines, line_type, payload_type=None):
    for line in lines:
        if line.get("type") != line_type:
            continue
        pl = line.get("payload", {})
        if payload_type is None or pl.get("type") == payload_type:
            return pl
    return None


def _last(lines, line_type, payload_type=None):
    found = None
    for line in lines:
        if line.get("type") != line_type:
            continue
        pl = line.get("payload", {})
        if payload_type is None or pl.get("type") == payload_type:
            found = pl
    return found


def parse_rollout(path: Path, thread_id_fallback: str | None = None) -> dict:
    lines = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    meta = _first(lines, "session_meta") or {}
    tc = _first(lines, "turn_context") or {}
    started = _first(lines, "event_msg", "task_started") or {}
    completed = _last(lines, "event_msg", "task_complete") or {}
    m = ROLLOUT_NAME.search(Path(path).name)
    thread_id = m.group("thread_id") if m else (meta.get("id") or thread_id_fallback or "unknown")

    phases = []
    for line in lines:
        if line.get("type") != "response_item":
            continue
        pl = line.get("payload", {})
        if pl.get("type") != "message":
            continue
        text = _text(pl.get("content"))
        first_line = text.splitlines()[0] if text else ""
        for prefix in PREFIXES:
            if first_line.startswith(prefix):
                status = "unknown"
                body = first_line[len(prefix):].strip()
                if prefix == "worker:":
                    status = body if body in ("complete", "incomplete") else "invalid"
                elif prefix in ("result-review:", "plan-review:"):
                    status = body if body in ("approved", "revise") else "unknown"
                owner = None
                if status == "revise":
                    for ln in text.splitlines()[1:]:
                        if ln.startswith("owner:"):
                            owner = ln.split(":", 1)[1].strip()
                            break
                phases.append({
                    "phase": prefix[:-1], "sequence": len(phases) + 1,
                    "packet": text[:8192], "packet_ref": None,
                    "truncated": "[packet truncated" in text,
                    "status": status, "owner": owner, "source": "rollout",
                })

    worker_status = "invalid"
    for p in reversed(phases):
        if p["phase"] == "worker":
            worker_status = p["status"]
            break
    review_status, owner = "none", None
    for p in reversed(phases):
        if p["phase"] == "result-review":
            review_status = p["status"]
            owner = p["owner"]
            break

    root_synthesis = None
    last_agent = completed.get("last_agent_message")
    if last_agent:
        root_synthesis = {"text": str(last_agent), "truncated": False, "source": "rollout"}

    return {
        "identity": {
            "session_id": meta.get("session_id") or meta.get("id") or "unknown",
            "thread_id": thread_id,
            "turn_id": tc.get("turn_id") or started.get("turn_id"),
            "model_provider": meta.get("model_provider"),
            "completed_at": datetime.fromtimestamp(completed["completed_at"], tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z") if completed.get("completed_at") else None,
        },
        "execution": {
            "phases": phases,
            "final_phase": None,  # no runtime capture point in v0 -> null + gap
            "root_synthesis": root_synthesis,
        },
        "review": {
            "worker_status": worker_status,
            "result_review_status": review_status,
            "correction_owner": owner,
            "interpretation": "model_review_only",
        },
        "environment": {
            "cwd": tc.get("cwd"),
            "workspace_roots": tc.get("workspace_roots"),
            "network": {"allowed_domains": [], "denied_domains": []},
            "permission_policy": {
                "approval_policy": tc.get("approval_policy"),
                "sandbox_policy": (tc.get("sandbox_policy") or {}).get("type"),
                "permission_profile": (tc.get("permission_profile") or {}).get("type"),
            },
        },
        "metrics": _metrics(lines),
    }


def _metrics(lines) -> dict:
    tok = _last(lines, "event_msg", "token_count")
    completed = _last(lines, "event_msg", "task_complete")
    usage = (tok or {}).get("info", {}).get("total_token_usage", {})
    tool_calls = 0
    for line in lines:
        if line.get("type") == "event_msg":
            t = line.get("payload", {}).get("type", "")
            if t in ("exec_command_begin", "exec_command_end", "tool_use", "tool_call",
                     "function_call", "function_call_output"):
                tool_calls += 1
    return {
        "tokens": {
            "input_tokens": usage.get("input_tokens"),
            "cached_input_tokens": usage.get("cached_input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "tool_calls": tool_calls,
        "latency_ms": completed.get("duration_ms"),
    }
