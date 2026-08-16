"""Phase 5-I deterministic Evaluator entry point."""

from __future__ import annotations

from typing import Any

from models import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    EvaluationResult,
    TaskSpecification,
)
from rules import RULES


def evaluate(
    execution_record: Any,
    task_specification: TaskSpecification,
) -> EvaluationResult:
    """Evaluate one ExecutionRecord against one TaskSpecification.

    Pure read-only: never imports or mutates runtime / EventStore / Session.
    """
    findings = tuple(
        rule(execution_record, task_specification)
        for _, rule in RULES
    )
    if any(finding.status == FAIL for finding in findings):
        status = FAIL
    elif any(finding.status == INCONCLUSIVE for finding in findings):
        status = INCONCLUSIVE
    else:
        status = PASS
    return EvaluationResult(
        execution_id=getattr(execution_record, "execution_id", None),
        task_id=task_specification.task_id,
        status=status,
        findings=findings,
    )


__all__ = ["evaluate"]
