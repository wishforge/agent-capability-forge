#!/usr/bin/env python3
"""S6: write the optimized candidate as a non-production Langfuse prompt.

Reads LANGFUSE_* env vars. The candidate instruction comes from
data/candidate_program.json. Uses label control-plane-candidate (never
production) so the runtime keeps serving the current prompt.
"""

import json
import os
import pathlib
import sys

import requests

ROOT = pathlib.Path(__file__).resolve().parent


def candidate_instruction():
    program = json.loads((ROOT / "data" / "candidate_program.json").read_text())
    for node in _walk(program):
        if isinstance(node, dict) and "instructions" in node:
            return node["instructions"]
    return None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def main():
    instruction = candidate_instruction()
    if not instruction:
        print("no candidate instruction found", file=sys.stderr)
        return 1

    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    name = "swe-planner-control-plane-candidate"
    resp = requests.post(
        f"{base}/api/public/prompts",
        auth=auth,
        json={
            "name": name,
            "labels": ["control-plane-candidate"],
            "type": "text",
            "prompt": instruction,
            "config": {},
            "isActive": False,
        },
        timeout=60,
    )
    print(resp.status_code, resp.text[:300])
    resp.raise_for_status()
    created = resp.json()
    print(json.dumps({"name": created.get("name"), "version": created.get("version"),
                      "labels": created.get("labels"), "isActive": created.get("isActive")}))


if __name__ == "__main__":
    sys.exit(main())
