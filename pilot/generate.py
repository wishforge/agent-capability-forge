"""M7 - B2/B3 shared LLM proposal generation (one call per family).

Uses `codex exec --output-schema` with the SAME model/config as formation runs,
so the model/config lock is shared. Output: llm_proposal.json + digest.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROPOSAL_SCHEMA = {
    "type": "object",
    "required": ["name", "description", "skill_md", "implementation", "entrypoint", "contract", "tests"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "skill_md": {"type": "string"},
        "implementation": {"type": "object", "required": ["main.py"],
                            "properties": {"main.py": {"type": "string"}}},
        "entrypoint": {
            "type": "object", "required": ["command", "workdir"],
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}},
                "workdir": {"type": "string"}}},
        "contract": {
            "type": "object", "required": ["input", "output"],
            "properties": {
                "input": {"type": "object", "required": ["files", "args"],
                          "properties": {"files": {"type": "array", "items": {"type": "string"}},
                                         "args": {"type": "object",
                                                  "required": ["freeform"],
                                                  "properties": {"freeform": {"type": "string"}}}}},
                "output": {"type": "object", "required": ["files", "stdout", "exit_code"],
                           "properties": {"files": {"type": "array", "items": {"type": "string"}},
                                          "stdout": {"type": "string"},
                                          "exit_code": {"type": "integer"}}}}},
        "tests": {"type": "array", "items": {"type": "string"}},
    },
}

PROMPT = """You are generating ONE reusable capability proposal for the F+ task family: CSV cleaning + statistical report.
Read generation_input.json in this workspace. It contains 4 verified task bundles from 2 calibration tasks (input CSVs, cleaned CSVs, reports) and the task prompts.
Write llm_proposal.json in this workspace with EXACTLY this shape (all fields required):
- name: kebab-case capability name
- description: one sentence
- skill_md: complete SKILL.md text for a Codex skill (frontmatter with name and description, instructions, and a usage example that references scripts/main.py)
- implementation: {"main.py": "<complete python3 stdlib-only script>"}. The script MUST take the input CSV path as sys.argv[1] and the output directory as sys.argv[2]. It cleans per the rules in generation_input.json (remove exact duplicate rows; drop rows missing id/customer/category; fill missing amount with 0; normalize dates to YYYY-MM-DD and drop unparseable dates; sort by id) and writes report.md into the output directory with exactly these lines (floats with 2 decimals): total_rows, total_amount, unique_customers, mean_amount. It MUST NOT hardcode any absolute path, any original workspace path, or any fixture filename like data/input.csv.
- entrypoint: {"command": ["python", "main.py"], "workdir": "artifact"}
- contract: {"input": {"files": ["data/*.csv"], "args": {"freeform": ""}}, "output": {"files": ["report.md"], "stdout": "string", "exit_code": 0}}
- tests: list of golden test case ids
Write the file. Do not write any other files."""


def run(codex_home: Path, workdir: Path, schema_path: Path, model: dict,
        timeout_s: int, last_msg_path: Path, stdout_log: Path) -> int:
    cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write",
           "-c", f"model_provider={model['provider']}",
           "-c", f"model={model['name']}",
           "-c", f"model_reasoning_effort={model['reasoning_effort']}",
           "--output-schema", str(schema_path), "-o", str(last_msg_path), PROMPT]
    env = {"CODEX_HOME": str(codex_home), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
    with stdout_log.open("w") as fh:
        proc = subprocess.run(cmd, cwd=workdir, env=env, timeout=timeout_s,
                              stdout=fh, stderr=subprocess.STDOUT)
    return proc.returncode


def validate_proposal(proposal: dict) -> list[str]:
    errors = []
    for k in ("name", "description", "skill_md", "implementation", "entrypoint", "contract"):
        if not proposal.get(k):
            errors.append(f"missing {k}")
    if proposal.get("implementation") and "main.py" not in proposal["implementation"]:
        errors.append("implementation.main.py missing")
    return errors
