"""Runtime metrics extraction (kept separate so harness/cost never parse rollouts)."""

from __future__ import annotations

from pathlib import Path

from .rollout_parser import parse_rollout


def runtime_metrics(rollout_path: Path) -> dict:
    return parse_rollout(rollout_path)["metrics"]
