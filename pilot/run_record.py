"""M11 - run_record_v1 writer. One line per run in state/run_records.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

FIELDS = [
    "run_id", "task_id", "family", "arm", "formation_id", "model", "model_config_hash",
    "seed", "order", "sandbox_id", "started_at", "ended_at", "oracle", "bundle_id",
    "bundle_ids", "skill_used", "capability_used", "invoke_result", "trap",
    "regression", "false_promotion", "cost", "generation_input_digest",
    "proposal_digest", "runtime_metrics", "output_dir", "last_message",
    "sandbox_elapsed_s", "notes",
]


def write_record(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    missing = [f for f in FIELDS if f not in record]
    if missing:
        raise ValueError(f"run record missing fields: {missing}")
    with path.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def update_record(path: Path, run_id: str, **fields) -> None:
    path = Path(path)
    lines = path.read_text().splitlines() if path.exists() else []
    out = []
    found = False
    for line in lines:
        rec = json.loads(line)
        if rec.get("run_id") == run_id:
            rec.update(fields)
            found = True
        out.append(rec)
    if not found:
        raise KeyError(f"run record not found: {run_id}")
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in out) + "\n")


def load_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def validate_record(record: dict) -> list[str]:
    return [f for f in FIELDS if f not in record]
