#!/usr/bin/env python3
"""S3: score extracted trajectories with the AgentEvals trajectory rubric.

Reads the DeepSeek credentials from ~/.codex/config.toml at runtime and never
prints them. Writes data/eval.jsonl next to data/samples.jsonl.

ponytail: DeepSeek does not support response_format json_schema (openevals
OpenAI-client path), so the judge call is a plain json_object chat completion
using AgentEvals' prompt and message normalization. Switch back to
create_trajectory_llm_as_judge when the provider supports json_schema.
"""

import json
import pathlib
import re
import sys
import tomllib

from agentevals.trajectory.llm import TRAJECTORY_ACCURACY_PROMPT
from openevals.utils import (
    _chat_completion_messages_to_string,
    _normalize_to_openai_messages_list,
)
from openai import OpenAI

ROOT = pathlib.Path(__file__).resolve().parent


def load_llm():
    cfg = tomllib.loads(pathlib.Path("/Users/david/.codex/config.toml").read_text())
    prov = cfg["model_providers"]["deepseek"]
    return (
        prov["base_url"].rstrip("/"),
        prov["experimental_bearer_token"],
        cfg.get("model", "deepseek-v4-flash"),
    )


def main():
    samples = [
        json.loads(line)
        for line in (ROOT / "data" / "samples.jsonl").read_text().splitlines()
    ]
    base_url, api_key, model = load_llm()
    client = OpenAI(api_key=api_key, base_url=base_url)

    results = []
    for sample in samples:
        print(f"evaluating {sample['trace_id']} ...", flush=True)
        trajectory = _chat_completion_messages_to_string(
            _normalize_to_openai_messages_list(sample["trajectory"])
        )
        prompt = TRAJECTORY_ACCURACY_PROMPT.format(outputs=trajectory)
        prompt += (
            '\n\nRespond in JSON: {"score": <0-1 number>, '
            '"reasoning": "<brief explanation>"}'
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        score, reasoning = _parse_judge(content)
        record = {
            "trace_id": sample["trace_id"],
            "name": sample["name"],
            "score": score,
            "comment": reasoning,
            "model": model,
        }
        results.append(record)
        print(f"  score={record['score']}", flush=True)

    with open(ROOT / "data" / "eval.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps([r["score"] for r in results]))


def _parse_judge(content):
    match = re.search(r"\{.*\}", content, re.DOTALL)
    payload = json.loads(match.group(0)) if match else {}
    return payload.get("score"), payload.get("reasoning")


if __name__ == "__main__":
    sys.exit(main())
