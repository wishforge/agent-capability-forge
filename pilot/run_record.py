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
    "sandbox_elapsed_s", "notes", "treatment",
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


def validate_treatment(record: dict) -> list[str]:
    """Treatment Attribution Gate. [] = VALID, otherwise INVALID_TREATMENT."""
    errors = []
    t = record.get("treatment")
    if not isinstance(t, dict):
        return ["treatment missing"]
    arm = record.get("arm")
    if arm == "b0":
        if t.get("type") != "none":
            errors.append("B0 treatment.type must be none")
        if t.get("used") is not False:
            errors.append("B0 treatment.used must be false")
    elif arm in ("b1", "b2"):
        if t.get("type") != "skill":
            errors.append(f"{arm.upper()} treatment.type must be skill")
        if t.get("used") is not True:
            errors.append(f"{arm.upper()} skill_used must be true")
        if not t.get("ref"):
            errors.append(f"{arm.upper()} treatment.ref (skill ref) missing")
        digest = t.get("digest")
        if not digest:
            errors.append(f"{arm.upper()} treatment.digest missing")
        ev = t.get("evidence")
        if not isinstance(ev, dict):
            errors.append(f"{arm.upper()} missing skill evidence")
        elif digest and ev.get("mounted_digest") != digest:
            errors.append(f"{arm.upper()} mounted skill digest does not match treatment.digest")
        elif digest and ev.get("expected_digest") != digest:
            errors.append(f"{arm.upper()} frozen skill digest does not match treatment.digest")
    elif arm == "b3":
        if t.get("type") != "capability":
            errors.append("B3 treatment.type must be capability")
        if t.get("used") is not True:
            errors.append("B3 capability_used must be true")
        ref = t.get("ref")
        if not ref:
            errors.append("B3 treatment.ref (capability_id) missing")
        digest = t.get("digest")
        if not digest and not t.get("version"):
            errors.append("B3 treatment.digest/version missing")
        ev = t.get("evidence")
        if not isinstance(ev, dict):
            errors.append("B3 missing capability invoke evidence")
        else:
            if ref and ev.get("capability_id") != ref:
                errors.append("B3 invoke evidence capability_id does not match treatment.ref")
            if not ev.get("sandbox_id"):
                errors.append("B3 invoke evidence sandbox_id missing")
            if digest and ev.get("artifact_digest") != digest:
                errors.append("B3 artifact digest does not match treatment.digest")
    else:
        errors.append(f"unknown arm {arm!r}")
    return errors
