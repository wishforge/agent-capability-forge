"""Phase 5-M tests: RegressionRun contract (deterministic, read-only).

Contract only: no re-execution, no promotion, no Runtime / Evaluator change.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

from evaluator import evaluate  # noqa: E402
from failure_attribution import attribute  # noqa: E402
from golden import TASK_01, TASK_02, TASK_03, _record  # noqa: E402
from improvement_candidate import PROMPT, propose  # noqa: E402
from models import FAIL, INCONCLUSIVE, PASS  # noqa: E402
from regression import (  # noqa: E402
    EXACT,
    IMPROVED,
    INCONCLUSIVE,
    LOSSY,
    NO_CHANGE,
    NOT_AVAILABLE,
    REGRESSED,
    TaskSet,
    UNCHANGED,
    compare,
)

SPECS = {spec.task_id: spec for spec in (TASK_01, TASK_02, TASK_03)}


def _record_for(
    task_id: str,
    outcome: str,
    execution_id: str,
    lossy: bool = False,
    backend: str = "codex",
) -> SimpleNamespace:
    backend_refs = (
        {
            "backend": backend,
            "event_type": "turn_start",
            "reference": {"id": execution_id},
            "quality": "EXACT",
        },
    )
    lossiness = (
        (
            {
                "backend": backend,
                "mapping_quality": "LOSSY",
                "missing_semantics": ("EXEC_FAILURE_STRUCTURED_SUCCESS",),
            },
        )
        if lossy
        else (
            {
                "backend": backend,
                "mapping_quality": "EXACT",
                "missing_semantics": (),
            },
        )
    )
    if outcome == "PASS":
        name = "inventory.lookup" if task_id == "TASK-01" else "lookup"
        return _record(
            execution_id=execution_id,
            tools=(
                {
                    "call_id": f"{execution_id}-1",
                    "name": name,
                    "arguments": {},
                    "backend_event_ref": {
                        "backend": backend,
                        "event_type": "tool_result",
                        "reference": {"id": execution_id},
                        "quality": "EXACT",
                    },
                },
            ),
            tool_results=(
                {
                    "tool_call_id": f"{execution_id}-1",
                    "content": "ok",
                    "is_error": False,
                    "error_code": None,
                },
            ),
            backend_refs=backend_refs,
            lossiness=lossiness,
        )
    if outcome == "FAIL":
        if task_id == "TASK-03":
            return _record(
                execution_id=execution_id,
                attempts=(
                    SimpleNamespace(
                        execution_id=execution_id,
                        attempt_id=f"{execution_id}/attempt-1",
                        attempt_number=1,
                        parent_execution_id=None,
                        reason="model_request",
                        status="FAILED",
                        step_id="step-1",
                    ),
                    SimpleNamespace(
                        execution_id=execution_id,
                        attempt_id=f"{execution_id}/attempt-2",
                        attempt_number=2,
                        parent_execution_id=execution_id,
                        reason="UNSAFE_RETRY_BLOCKED",
                        status="ABORTED",
                        step_id="step-1",
                    ),
                ),
                turn_end_reason="error",
                backend_refs=backend_refs,
                lossiness=lossiness,
            )
        name = "inventory.lookup" if task_id == "TASK-01" else "lookup"
        return _record(
            execution_id=execution_id,
            tools=(
                {
                    "call_id": f"{execution_id}-1",
                    "name": name,
                    "arguments": {},
                    "backend_event_ref": {
                        "backend": backend,
                        "event_type": "tool_result",
                        "reference": {"id": execution_id},
                        "quality": "EXACT",
                    },
                },
            ),
            tool_results=(
                {
                    "tool_call_id": f"{execution_id}-1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
            backend_refs=backend_refs,
            lossiness=lossiness,
        )
    if outcome == "INCONCLUSIVE":
        return _record(
            execution_id=execution_id,
            tool_results=None,
            backend_refs=backend_refs,
            lossiness=lossiness,
        )
    raise ValueError(f"unknown outcome {outcome!r}")


def _evaluate(task_id: str, record: SimpleNamespace):
    return evaluate(record, SPECS[task_id])


def _candidate(baseline_ref: str = "prompt:agent.system_prompt.v2"):
    record = _record_for("TASK-02", "FAIL", "candidate-source")
    attr = attribute(record, _evaluate("TASK-02", record))
    return propose(
        attr,
        target_type="capability",
        target_ref="inventory.lookup",
        change_type=PROMPT,
        change_ref="prompt:agent.system_prompt.v3",
        baseline_ref=baseline_ref,
        hypothesis="explicit tool policy raises required tool invocation",
        expected_effect="reduce missing tool calls",
        evaluation_ids=("eval-1",),
        created_at="2026-01-01T00:00:00Z",
    )


def _run(
    tasks: tuple[str, ...] = ("TASK-02", "TASK-03"),
    baseline_outcomes: tuple[str, ...] = ("PASS", "FAIL"),
    candidate_outcomes: tuple[str, ...] = ("PASS", "PASS"),
    *,
    baseline_lossy: bool = False,
    candidate_lossy: bool = False,
    baseline_backend: str = "codex",
    candidate_backend: str = "codex",
    critical_categories: dict | None = None,
    baseline_ref: str = "prompt:agent.system_prompt.v2",
    usage=NOT_AVAILABLE,
):
    baseline_records = {
        task_id: _record_for(
            task_id,
            outcome,
            f"base-{task_id}",
            baseline_lossy,
            baseline_backend,
        )
        for task_id, outcome in zip(tasks, baseline_outcomes)
    }
    candidate_records = {
        task_id: _record_for(
            task_id,
            outcome,
            f"cand-{task_id}",
            candidate_lossy,
            candidate_backend,
        )
        for task_id, outcome in zip(tasks, candidate_outcomes)
    }
    return compare(
        baseline_ref=baseline_ref,
        candidate=_candidate(baseline_ref),
        task_set=TaskSet("task-set-1", "v1", tuple(tasks)),
        baseline_run_id="base-run-1",
        candidate_run_id="cand-run-1",
        baseline_results={t: _evaluate(t, r) for t, r in baseline_records.items()},
        candidate_results={t: _evaluate(t, r) for t, r in candidate_records.items()},
        baseline_records=baseline_records,
        candidate_records=candidate_records,
        critical_categories=critical_categories,
        usage=usage,
    )


class RegressionContractTests(unittest.TestCase):
    def test_baseline_candidate_identity(self) -> None:
        run = _run()
        self.assertEqual(run.baseline_ref, "prompt:agent.system_prompt.v2")
        self.assertEqual(run.candidate_ref, _candidate().candidate_id)
        self.assertTrue(run.baseline_ref and run.candidate_ref)
        self.assertEqual(run.baseline_results[0].execution_id, "base-TASK-02")
        self.assertEqual(run.candidate_results[0].execution_id, "cand-TASK-02")

    def test_task_set_identity(self) -> None:
        run = _run()
        self.assertEqual(run.task_set_ref.task_set_id, "task-set-1")
        self.assertEqual(run.task_set_ref.version, "v1")
        self.assertEqual(run.task_set_ref.task_ids, ("TASK-02", "TASK-03"))
        with self.assertRaises(ValueError):
            _run(candidate_outcomes=("PASS",))  # task/result count mismatch

    def test_replay_vs_reexecution(self) -> None:
        replayed = _run()
        replayed_again = _run()
        self.assertEqual(replayed, replayed_again)  # replay is deterministic
        reexec = compare(
            baseline_ref="prompt:agent.system_prompt.v2",
            candidate=_candidate(),
            task_set=TaskSet("task-set-1", "v1", ("TASK-02",)),
            baseline_run_id="re-base-run",
            candidate_run_id="re-cand-run",
            baseline_results={
                "TASK-02": _evaluate("TASK-02", _record_for("TASK-02", "FAIL", "re-base")),
            },
            candidate_results={
                "TASK-02": _evaluate("TASK-02", _record_for("TASK-02", "PASS", "re-cand")),
            },
            baseline_records={"TASK-02": _record_for("TASK-02", "FAIL", "re-base")},
            candidate_records={"TASK-02": _record_for("TASK-02", "PASS", "re-cand")},
        )
        self.assertNotEqual(reexec.regression_id, replayed.regression_id)
        self.assertEqual(reexec.candidate_results[0].execution_id, "re-cand")

    def test_per_task_comparison(self) -> None:
        run = _run(
            tasks=("TASK-01", "TASK-02", "TASK-03"),
            baseline_outcomes=("PASS", "FAIL", "PASS"),
            candidate_outcomes=("PASS", "PASS", "FAIL"),
        )
        outcomes = {tc.task_id: tc.outcome for tc in run.task_comparisons}
        self.assertEqual(
            outcomes,
            {"TASK-01": UNCHANGED, "TASK-02": IMPROVED, "TASK-03": REGRESSED},
        )
        deltas = {tc.task_id: tc.delta for tc in run.task_comparisons}
        self.assertEqual(deltas["TASK-02"], (FAIL, PASS))
        self.assertEqual(deltas["TASK-03"], (PASS, FAIL))
        self.assertTrue(run.task_comparisons[0].baseline_evidence_refs)
        self.assertTrue(run.task_comparisons[0].candidate_evidence_refs)

    def test_improved(self) -> None:
        run = _run(
            baseline_outcomes=("FAIL", "FAIL"),
            candidate_outcomes=("PASS", "PASS"),
        )
        self.assertEqual(run.decision, IMPROVED)
        self.assertEqual(run.aggregate_comparison.success_rate, (0.0, 1.0))

    def test_no_change(self) -> None:
        run = _run(
            baseline_outcomes=("PASS", "FAIL"),
            candidate_outcomes=("PASS", "FAIL"),
        )
        self.assertEqual(run.decision, NO_CHANGE)
        self.assertEqual(run.aggregate_comparison.success_rate, (0.5, 0.5))

    def test_regressed(self) -> None:
        run = _run(
            tasks=("TASK-02", "TASK-03"),
            baseline_outcomes=("PASS", "PASS"),
            candidate_outcomes=("PASS", "FAIL"),
        )
        self.assertEqual(run.decision, REGRESSED)
        self.assertEqual(run.aggregate_comparison.success_rate, (1.0, 0.5))

    def test_inconclusive(self) -> None:
        run = _run(
            candidate_outcomes=("PASS", "INCONCLUSIVE"),
        )
        self.assertEqual(run.comparison_quality, INCONCLUSIVE)
        self.assertEqual(run.decision, INCONCLUSIVE)
        self.assertEqual(run.task_comparisons[1].outcome, INCONCLUSIVE)

    def test_critical_regression(self) -> None:
        run = _run(
            tasks=("TASK-01", "TASK-02", "TASK-03"),
            baseline_outcomes=("PASS", "FAIL", "FAIL"),
            candidate_outcomes=("FAIL", "PASS", "PASS"),
            critical_categories={"TASK-01": "security"},
        )
        self.assertEqual(len(run.critical_regressions), 1)
        self.assertEqual(run.critical_regressions[0].category, "security")
        self.assertEqual(run.critical_regressions[0].task_id, "TASK-01")
        self.assertEqual(run.decision, REGRESSED)
        with self.assertRaises(ValueError):
            _run(critical_categories={"TASK-01": "not-a-category"})

    def test_lossy_evidence(self) -> None:
        run = _run(candidate_lossy=True)
        self.assertEqual(run.comparison_quality, LOSSY)
        self.assertEqual(run.decision, INCONCLUSIVE)  # not IMPROVED
        self.assertEqual(run.aggregate_comparison.success_rate, (0.5, 1.0))

    def test_replay_stability(self) -> None:
        first = _run()
        second = _run()
        self.assertEqual(first, second)
        self.assertEqual(first.regression_id, second.regression_id)
        self.assertEqual(first.decision, second.decision)

    def test_reexecution_identity(self) -> None:
        run = _run()
        self.assertEqual(run.baseline_run_id, "base-run-1")
        self.assertEqual(run.candidate_run_id, "cand-run-1")
        self.assertEqual(run.task_comparisons[0].task_id, "TASK-02")
        old_records = _record_for("TASK-02", "FAIL", "base-TASK-02")
        self.assertEqual(old_records.execution_id, "base-TASK-02")  # untouched
        self.assertEqual(run.baseline_results[0].execution_id, "base-TASK-02")

    def test_cross_backend_shape(self) -> None:
        cross = _run(
            tasks=("TASK-02",),
            baseline_outcomes=("FAIL",),
            candidate_outcomes=("PASS",),
            baseline_backend="agentscope",
            candidate_backend="codex",
        )
        same = _run(
            tasks=("TASK-02",),
            baseline_outcomes=("FAIL",),
            candidate_outcomes=("PASS",),
        )
        self.assertEqual(
            {field.name for field in fields(cross)},
            {field.name for field in fields(same)},
        )
        self.assertEqual(cross.decision, same.decision)
        self.assertEqual(cross.decision, IMPROVED)
        self.assertEqual(cross.comparison_quality, EXACT)
        baseline_refs = cross.task_comparisons[0].baseline_evidence_refs
        candidate_refs = cross.task_comparisons[0].candidate_evidence_refs
        self.assertIn("agentscope", str(baseline_refs))
        self.assertIn("codex", str(candidate_refs))

    def test_missing_baseline_blocked(self) -> None:
        for unstable in ("", "UNKNOWN", "latest", "last-run", "last-successful-run"):
            with self.assertRaises(ValueError):
                _run(baseline_ref=unstable)

    def test_aggregate_does_not_hide_critical_regression(self) -> None:
        run = _run(
            tasks=("TASK-01", "TASK-02", "TASK-03"),
            baseline_outcomes=("PASS", "FAIL", "FAIL"),
            candidate_outcomes=("FAIL", "PASS", "PASS"),
            critical_categories={"TASK-01": "data_integrity"},
        )
        self.assertEqual(run.aggregate_comparison.success_rate, (1 / 3, 2 / 3))
        self.assertEqual(run.decision, REGRESSED)


if __name__ == "__main__":
    unittest.main()
