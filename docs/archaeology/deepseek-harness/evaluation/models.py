"""Phase 5-I minimal evaluation models (runtime-independent).

These types never import runtime / EventStore / Session / Capability.
TaskSpecification carries task semantics only; deterministic rules consume
ExecutionRecord fields via duck typing, so the same evaluator works for any
record shape that satisfies the documented minimal surface (5-G/5-H).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class TaskSpecification:
    task_id: str
    natural_language_goal: str
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    terminal_condition: Callable[[Any], bool] | None = None
    terminal_condition_desc: str | None = None
    policy_constraints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    status: str
    severity: str
    message: str
    evidence_refs: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    execution_id: str
    task_id: str
    status: str
    score: float | None = None
    findings: tuple[Finding, ...] = ()


__all__ = [
    "FAIL",
    "INCONCLUSIVE",
    "PASS",
    "EvaluationResult",
    "Finding",
    "TaskSpecification",
]
