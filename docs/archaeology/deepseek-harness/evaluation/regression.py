"""Phase 5-M RegressionRun contract: deterministic baseline vs candidate compare.

Contract only: consumes EvaluationResult + ExecutionRecord already produced;
never re-executes model/tool, never mutates Runtime / Evaluator, never
promotes. Backend-neutral: no ``if codex`` / ``if agentscope`` branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from improvement_candidate import (
    INVALID_FOR_REGRESSION,
    REQUIRES_DISAMBIGUATION,
    ImprovementCandidate,
)
from models import FAIL, INCONCLUSIVE, PASS

IMPROVED = "IMPROVED"
NO_CHANGE = "NO_CHANGE"
REGRESSED = "REGRESSED"
UNCHANGED = "UNCHANGED"

EXACT = "EXACT"
PARTIAL = "PARTIAL"
LOSSY = "LOSSY"

NOT_AVAILABLE = "NOT_AVAILABLE"

UNSTABLE_BASELINE_REFS = frozenset(
    {"", "UNKNOWN", "latest", "last-run", "last-successful-run", "previous"},
)

CRITICAL_CATEGORIES = frozenset(
    {
        "security",
        "authorization",
        "unsafe_tool_use",
        "policy_violation",
        "data_integrity",
    },
)


@dataclass(frozen=True, slots=True)
class TaskSet:
    """Versioned task set; baseline and candidate share one instance."""

    task_set_id: str
    version: str
    task_ids: tuple[str, ...]
    task_specs: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskComparison:
    task_id: str
    baseline_status: str
    candidate_status: str
    delta: tuple[str, str]
    outcome: str
    baseline_evidence_refs: tuple[dict, ...]
    candidate_evidence_refs: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class AggregateComparison:
    success_rate: tuple[float, float]
    failure_rate: tuple[float, float]
    timeout_rate: tuple[float, float] | str
    unsafe_retry_rate: tuple[float, float] | str
    unresolved_tool_rate: tuple[float, float] | str
    usage: Any = NOT_AVAILABLE


@dataclass(frozen=True, slots=True)
class CriticalRegression:
    task_id: str
    category: str
    baseline_status: str
    candidate_status: str
    evidence_refs: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class RegressionRun:
    regression_id: str
    baseline_ref: str
    candidate_ref: str
    task_set_ref: TaskSet
    baseline_run_id: str
    candidate_run_id: str
    baseline_results: tuple[Any, ...]
    candidate_results: tuple[Any, ...]
    task_comparisons: tuple[TaskComparison, ...]
    aggregate_comparison: AggregateComparison
    critical_regressions: tuple[CriticalRegression, ...]
    decision: str
    evidence_refs: tuple[dict, ...]
    comparison_quality: str


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _status(result: Any) -> str:
    status = _get(result, "status")
    return status if status in (PASS, FAIL, INCONCLUSIVE) else INCONCLUSIVE


def _stable_baseline(ref: str) -> bool:
    normalized = str(ref or "").strip().lower()
    return bool(normalized) and normalized not in UNSTABLE_BASELINE_REFS


def _record_quality(record: Any) -> str:
    lossiness = tuple(_get(record, "lossiness", ()) or ())
    qualities = {
        str(_get(item, "mapping_quality"))
        for item in lossiness
        if _get(item, "mapping_quality") is not None
    }
    if qualities:
        return LOSSY if LOSSY in qualities else EXACT if qualities == {EXACT} else PARTIAL
    direct = _get(record, "mapping_quality")
    if direct == LOSSY:
        return LOSSY
    if direct == EXACT:
        return EXACT
    return PARTIAL  # lossiness container absent


def _execution_ref(record: Any) -> dict:
    ref = {
        "execution_id": _get(record, "execution_id"),
        "replay_ref": _get(record, "replay_ref"),
        "mapping_quality": _record_quality(record),
    }
    backend_refs = tuple(_get(record, "backend_refs", ()) or ())
    if backend_refs:
        ref["backend_refs"] = backend_refs
    return {key: value for key, value in ref.items() if value is not None}


def _evaluation_ref(result: Any) -> dict:
    ref = {
        "execution_id": _get(result, "execution_id"),
        "task_id": _get(result, "task_id"),
        "status": _get(result, "status"),
    }
    return {key: value for key, value in ref.items() if value is not None}


def _rate(statuses: tuple[str, ...], target: str) -> float:
    return sum(1 for status in statuses if status == target) / len(statuses)


def _finding_fail_rate(results: tuple[Any, ...], rule_id: str) -> float | str:
    counts: list[bool] = []
    for result in results:
        findings = tuple(_get(result, "findings", ()) or ())
        if not findings:
            return NOT_AVAILABLE
        counts.append(
            any(
                _get(finding, "rule_id") == rule_id
                and _get(finding, "status") == FAIL
                for finding in findings
            ),
        )
    return sum(counts) / len(counts)


def _paired_rate(
    baseline_results: tuple[Any, ...],
    candidate_results: tuple[Any, ...],
    rule_id: str,
) -> tuple[float, float] | str:
    baseline_rate = _finding_fail_rate(baseline_results, rule_id)
    candidate_rate = _finding_fail_rate(candidate_results, rule_id)
    if baseline_rate == NOT_AVAILABLE or candidate_rate == NOT_AVAILABLE:
        return NOT_AVAILABLE
    return (baseline_rate, candidate_rate)


def _task_comparison(
    task_id: str,
    baseline_result: Any,
    candidate_result: Any,
    baseline_record: Any,
    candidate_record: Any,
    baseline_attributions: tuple[dict, ...],
    candidate_attributions: tuple[dict, ...],
) -> TaskComparison:
    baseline_status = _status(baseline_result)
    candidate_status = _status(candidate_result)
    if baseline_status == INCONCLUSIVE or candidate_status == INCONCLUSIVE:
        outcome = INCONCLUSIVE
    elif baseline_status == PASS and candidate_status == FAIL:
        outcome = REGRESSED
    elif baseline_status == FAIL and candidate_status == PASS:
        outcome = IMPROVED
    else:
        outcome = UNCHANGED
    return TaskComparison(
        task_id=task_id,
        baseline_status=baseline_status,
        candidate_status=candidate_status,
        delta=(baseline_status, candidate_status),
        outcome=outcome,
        baseline_evidence_refs=(
            _execution_ref(baseline_record),
            _evaluation_ref(baseline_result),
            *baseline_attributions,
        ),
        candidate_evidence_refs=(
            _execution_ref(candidate_record),
            _evaluation_ref(candidate_result),
            *candidate_attributions,
        ),
    )


def _critical_regressions(
    task_ids: tuple[str, ...],
    baseline_results: Mapping[str, Any],
    candidate_results: Mapping[str, Any],
    baseline_records: Mapping[str, Any],
    candidate_records: Mapping[str, Any],
    critical_categories: Mapping[str, str],
) -> tuple[CriticalRegression, ...]:
    found = []
    for task_id, category in (critical_categories or {}).items():
        if category not in CRITICAL_CATEGORIES:
            raise ValueError(f"unknown critical regression category {category!r}")
        if task_id not in task_ids:
            raise ValueError(f"critical task {task_id!r} not in task set")
        baseline_status = _status(baseline_results[task_id])
        candidate_status = _status(candidate_results[task_id])
        if baseline_status == PASS and candidate_status == FAIL:
            found.append(
                CriticalRegression(
                    task_id=task_id,
                    category=category,
                    baseline_status=baseline_status,
                    candidate_status=candidate_status,
                    evidence_refs=(
                        _execution_ref(baseline_records[task_id]),
                        _evaluation_ref(baseline_results[task_id]),
                        _execution_ref(candidate_records[task_id]),
                        _evaluation_ref(candidate_results[task_id]),
                    ),
                ),
            )
    return tuple(found)


def _comparison_quality(
    task_comparisons: tuple[TaskComparison, ...],
    records: tuple[Any, ...],
) -> str:
    if any(comparison.outcome == INCONCLUSIVE for comparison in task_comparisons):
        return INCONCLUSIVE
    qualities = {_record_quality(record) for record in records}
    if LOSSY in qualities:
        return LOSSY
    if PARTIAL in qualities:
        return PARTIAL
    return EXACT


def _decision(
    task_comparisons: tuple[TaskComparison, ...],
    aggregate: AggregateComparison,
    comparison_quality: str,
    critical: tuple[CriticalRegression, ...],
) -> str:
    if critical:
        return REGRESSED
    if comparison_quality in (LOSSY, INCONCLUSIVE):
        return INCONCLUSIVE
    baseline_rate, candidate_rate = aggregate.success_rate
    if candidate_rate > baseline_rate:
        return IMPROVED
    if candidate_rate < baseline_rate:
        return REGRESSED
    return NO_CHANGE


def compare(
    *,
    baseline_ref: str,
    candidate: ImprovementCandidate,
    task_set: TaskSet,
    baseline_run_id: str,
    candidate_run_id: str,
    baseline_results: Mapping[str, Any],
    candidate_results: Mapping[str, Any],
    baseline_records: Mapping[str, Any],
    candidate_records: Mapping[str, Any],
    critical_categories: Mapping[str, str] | None = None,
    usage: Any = NOT_AVAILABLE,
    baseline_attributions: Mapping[str, tuple[dict, ...]] | None = None,
    candidate_attributions: Mapping[str, tuple[dict, ...]] | None = None,
) -> RegressionRun:
    """Build one deterministic RegressionRun from already-evaluated evidence."""
    if not _stable_baseline(baseline_ref):
        raise ValueError(f"BLOCKED: unstable baseline_ref {baseline_ref!r}")
    if candidate.status in (INVALID_FOR_REGRESSION, REQUIRES_DISAMBIGUATION):
        raise ValueError(f"BLOCKED: candidate status {candidate.status!r}")
    if candidate.baseline_ref != baseline_ref:
        raise ValueError(
            f"BLOCKED: candidate baseline_ref {candidate.baseline_ref!r} "
            f"!= run baseline_ref {baseline_ref!r}",
        )
    if not task_set.task_set_id or not task_set.version or not task_set.task_ids:
        raise ValueError("BLOCKED: task set identity incomplete")
    if not baseline_run_id or not candidate_run_id:
        raise ValueError("BLOCKED: baseline/candidate run ids required")

    task_ids = tuple(task_set.task_ids)
    missing = [
        task_id
        for task_id in task_ids
        if task_id not in baseline_results
        or task_id not in candidate_results
        or task_id not in baseline_records
        or task_id not in candidate_records
    ]
    if missing:
        raise ValueError(
            "BLOCKED: missing results/records for tasks: " + ", ".join(missing),
        )
    known = set(task_ids)
    supplied = (
        set(baseline_results)
        | set(candidate_results)
        | set(baseline_records)
        | set(candidate_records)
    )
    extra = sorted(supplied - known)
    if extra:
        raise ValueError(
            "BLOCKED: results/records for tasks outside task set: "
            + ", ".join(extra),
        )

    baseline_attributions = baseline_attributions or {}
    candidate_attributions = candidate_attributions or {}
    task_comparisons = tuple(
        _task_comparison(
            task_id,
            baseline_results[task_id],
            candidate_results[task_id],
            baseline_records[task_id],
            candidate_records[task_id],
            tuple(baseline_attributions.get(task_id, ()) or ()),
            tuple(candidate_attributions.get(task_id, ()) or ()),
        )
        for task_id in task_ids
    )

    baseline_statuses = tuple(_status(baseline_results[t]) for t in task_ids)
    candidate_statuses = tuple(_status(candidate_results[t]) for t in task_ids)
    baseline_tuple = tuple(baseline_results[t] for t in task_ids)
    candidate_tuple = tuple(candidate_results[t] for t in task_ids)
    aggregate = AggregateComparison(
        success_rate=(_rate(baseline_statuses, PASS), _rate(candidate_statuses, PASS)),
        failure_rate=(_rate(baseline_statuses, FAIL), _rate(candidate_statuses, FAIL)),
        timeout_rate=_paired_rate(baseline_tuple, candidate_tuple, "RULE-07"),
        unsafe_retry_rate=_paired_rate(baseline_tuple, candidate_tuple, "RULE-03"),
        unresolved_tool_rate=_paired_rate(baseline_tuple, candidate_tuple, "RULE-02"),
        usage=usage,
    )

    critical = _critical_regressions(
        task_ids,
        baseline_results,
        candidate_results,
        baseline_records,
        candidate_records,
        critical_categories or {},
    )
    comparison_quality = _comparison_quality(
        task_comparisons,
        tuple(baseline_records[t] for t in task_ids)
        + tuple(candidate_records[t] for t in task_ids),
    )
    evidence_refs = tuple(
        dict(ref)
        for comparison in task_comparisons
        for refs in (
            comparison.baseline_evidence_refs,
            comparison.candidate_evidence_refs,
        )
        for ref in refs
        if isinstance(ref, dict)
    ) + tuple(
        dict(ref)
        for regression in critical
        for ref in regression.evidence_refs
        if isinstance(ref, dict)
    )

    return RegressionRun(
        regression_id="|".join(
            (
                baseline_ref,
                candidate.candidate_id,
                f"{task_set.task_set_id}@{task_set.version}",
                baseline_run_id,
                candidate_run_id,
            ),
        ),
        baseline_ref=baseline_ref,
        candidate_ref=candidate.candidate_id,
        task_set_ref=task_set,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        baseline_results=baseline_tuple,
        candidate_results=candidate_tuple,
        task_comparisons=task_comparisons,
        aggregate_comparison=aggregate,
        critical_regressions=critical,
        decision=_decision(task_comparisons, aggregate, comparison_quality, critical),
        evidence_refs=evidence_refs,
        comparison_quality=comparison_quality,
    )


__all__ = [
    "AggregateComparison",
    "CRITICAL_CATEGORIES",
    "CriticalRegression",
    "EXACT",
    "IMPROVED",
    "INCONCLUSIVE",
    "LOSSY",
    "NO_CHANGE",
    "NOT_AVAILABLE",
    "PARTIAL",
    "REGRESSED",
    "RegressionRun",
    "TaskComparison",
    "TaskSet",
    "UNCHANGED",
    "UNSTABLE_BASELINE_REFS",
    "compare",
]
