"""Phase 5-N tests: Promotion/Rollback decision contract.

Decision semantics only: no deployment, no canary routing, no rollback
execution, no Runtime / Evaluator change.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

from improvement_candidate import (  # noqa: E402
    PROMPT,
    PROPOSED,
    VALIDATED,
    ImprovementCandidate,
)
from models import FAIL, INCONCLUSIVE, PASS  # noqa: E402
from promotion import (  # noqa: E402
    CANARY,
    GATE_FAIL,
    GATE_INCONCLUSIVE,
    GATE_NOT_APPLICABLE,
    GATE_PASS,
    PENDING,
    PROMOTED,
    REJECTED,
    REQUESTED,
    decide,
    request_rollback,
)
from regression import (  # noqa: E402
    EXACT,
    IMPROVED,
    INCONCLUSIVE as REG_INCONCLUSIVE,
    LOSSY,
    REGRESSED,
    CriticalRegression,
    RegressionRun,
    TaskSet,
)


def _candidate(
    status: str = VALIDATED,
    baseline_ref: str = "prompt:agent.system_prompt.v2",
    owner_ref: dict | None = None,
) -> ImprovementCandidate:
    return ImprovementCandidate(
        candidate_id="cand-1",
        source_failure_ids=("fail-1",),
        source_evaluation_ids=("eval-1",),
        source_execution_ids=("exec-1",),
        target_type="capability",
        target_ref="inventory.lookup",
        change_type=PROMPT,
        change_ref="prompt:agent.system_prompt.v3",
        baseline_ref=baseline_ref,
        hypothesis="explicit tool policy raises required tool invocation",
        expected_effect="reduce missing tool calls",
        status=status,
        owner_ref=owner_ref,
        source_mapping_quality="EXACT",
    )


def _run(
    decision: str = IMPROVED,
    quality: str = EXACT,
    critical: tuple[CriticalRegression, ...] = (),
    candidate_statuses: tuple[str, ...] = (PASS,),
    evidence: tuple[dict, ...] = ({"kind": "regression-evidence", "ref": "reg-ev-1"},),
    baseline_ref: str = "prompt:agent.system_prompt.v2",
    candidate_ref: str = "cand-1",
    regression_id: str = "reg-1",
) -> RegressionRun:
    return RegressionRun(
        regression_id=regression_id,
        baseline_ref=baseline_ref,
        candidate_ref=candidate_ref,
        task_set_ref=TaskSet("ts-1", "v1", ("T",)),
        baseline_run_id="base-run-1",
        candidate_run_id="cand-run-1",
        baseline_results=(SimpleNamespace(execution_id="b", task_id="T", status=PASS),),
        candidate_results=tuple(
            SimpleNamespace(execution_id="c", task_id="T", status=status)
            for status in candidate_statuses
        ),
        task_comparisons=(SimpleNamespace(task_id="T", outcome="UNCHANGED"),),
        aggregate_comparison=SimpleNamespace(success_rate=(1.0, 1.0)),
        critical_regressions=critical,
        decision=decision,
        evidence_refs=evidence,
        comparison_quality=quality,
    )


def _decide(**kwargs):
    base = dict(
        candidate=_candidate(),
        regression=_run(),
        target_version="prompt:agent.system_prompt.v3",
        rollback_to_version="prompt:agent.system_prompt.v2",
        created_at="2026-08-16T00:00:00Z",
    )
    base.update(kwargs)
    return decide(**base)


def _gate(decision, gate_id: str):
    return next(gate for gate in decision.gate_results if gate.gate_id == gate_id)


class PromotionContractTests(unittest.TestCase):
    def test_promotion_requires_validated_candidate(self) -> None:
        with self.assertRaises(ValueError):
            _decide(candidate=_candidate(status=PROPOSED))
        with self.assertRaises(ValueError):
            _decide(candidate=_candidate(status="REJECTED"))
        self.assertEqual(_decide().decision, PROMOTED)

    def test_inconclusive_evaluation_blocks_promotion(self) -> None:
        run = _run(decision=IMPROVED, candidate_statuses=(INCONCLUSIVE,))
        rejected = _decide(regression=run)
        self.assertEqual(rejected.decision, REJECTED)
        self.assertEqual(_gate(rejected, "evaluation").status, GATE_INCONCLUSIVE)
        allowed = _decide(
            regression=run,
            evaluation_exception_ref="policy:allow-inconclusive-eval",
        )
        self.assertEqual(allowed.decision, PROMOTED)
        self.assertEqual(_gate(allowed, "evaluation").status, GATE_PASS)

    def test_regressed_blocks_promotion(self) -> None:
        rejected = _decide(regression=_run(decision=REGRESSED))
        self.assertEqual(rejected.decision, REJECTED)
        self.assertEqual(_gate(rejected, "regression").status, GATE_FAIL)

    def test_critical_regression_blocks_promotion(self) -> None:
        critical = (
            CriticalRegression(
                task_id="T",
                category="security",
                baseline_status=PASS,
                candidate_status=FAIL,
                evidence_refs=({"kind": "critical-regression"},),
            ),
        )
        rejected = _decide(regression=_run(decision=IMPROVED, critical=critical))
        self.assertEqual(rejected.decision, REJECTED)
        self.assertEqual(_gate(rejected, "regression").status, GATE_FAIL)

    def test_no_baseline_blocks_promotion(self) -> None:
        for ref in ("", "UNKNOWN", "latest"):
            with self.assertRaises(ValueError):
                _decide(candidate=_candidate(baseline_ref=ref))

    def test_unstable_version_blocks_promotion(self) -> None:
        for version in ("latest", "candidate", "current"):
            with self.assertRaises(ValueError):
                _decide(target_version=version)
        for version in ("previous", "last good", "上一次部署"):
            with self.assertRaises(ValueError):
                _decide(rollback_to_version=version)

    def test_promotion_decision(self) -> None:
        decision = _decide()
        self.assertEqual(decision.decision, PROMOTED)
        self.assertEqual(decision.candidate_ref, "cand-1")
        self.assertEqual(decision.regression_ref, "reg-1")
        self.assertEqual(decision.target_version, "prompt:agent.system_prompt.v3")
        self.assertEqual(decision.rollback_to_version, "prompt:agent.system_prompt.v2")
        self.assertTrue(decision.reason)
        self.assertTrue(decision.evidence_refs)
        self.assertTrue(decision.gate_results)

    def test_canary_state(self) -> None:
        pending = _decide(canary=True)
        self.assertEqual(pending.decision, PENDING)
        self.assertEqual(pending.rollback_to_version, "prompt:agent.system_prompt.v2")
        canary = _decide(
            canary=True,
            canary_observations=({"observation_id": "obs-1"},),
            observation_window="2026-08-01/2026-08-07",
        )
        self.assertEqual(canary.decision, CANARY)
        self.assertEqual(canary.observation_window, "2026-08-01/2026-08-07")
        self.assertTrue(any(ref.get("observation_id") == "obs-1" for ref in canary.evidence_refs))

    def test_promoted_version(self) -> None:
        decision = _decide()
        self.assertEqual(decision.target_version, "prompt:agent.system_prompt.v3")
        self.assertEqual(decision.rollback_to_version, "prompt:agent.system_prompt.v2")
        self.assertTrue(
            any(ref.get("target_version") == decision.target_version for ref in decision.evidence_refs)
        )

    def test_rollback_target_required(self) -> None:
        with self.assertRaises(ValueError):
            _decide(rollback_to_version="")
        with self.assertRaises(ValueError):
            _decide(rollback_to_version="previous")

    def test_rollback_decision(self) -> None:
        rollback = request_rollback(
            from_version="prompt:agent.system_prompt.v3",
            to_version="prompt:agent.system_prompt.v2",
            reason="regression after promotion",
            evidence_refs=({"observation_id": "obs-1"},),
            created_at="2026-08-16T01:00:00Z",
            trigger="regression_after_promotion",
        )
        self.assertEqual(rollback.status, REQUESTED)
        self.assertEqual(rollback.from_version, "prompt:agent.system_prompt.v3")
        self.assertEqual(rollback.to_version, "prompt:agent.system_prompt.v2")
        self.assertEqual(rollback.trigger, "regression_after_promotion")
        self.assertTrue(rollback.rollback_id)
        with self.assertRaises(ValueError):
            request_rollback(
                from_version="prompt:agent.system_prompt.v3",
                to_version="prompt:agent.system_prompt.v2",
                reason="operator decision",
                evidence_refs=({"observation_id": "obs-1"},),
                created_at="2026-08-16T01:00:00Z",
                trigger="not-a-trigger",
            )
        with self.assertRaises(ValueError):
            request_rollback(
                from_version="prompt:agent.system_prompt.v2",
                to_version="prompt:agent.system_prompt.v2",
                reason="same version",
                evidence_refs=({"observation_id": "obs-1"},),
                created_at="2026-08-16T01:00:00Z",
            )

    def test_rollback_reason_required(self) -> None:
        with self.assertRaises(ValueError):
            request_rollback(
                from_version="prompt:agent.system_prompt.v3",
                to_version="prompt:agent.system_prompt.v2",
                reason="",
                evidence_refs=({"observation_id": "obs-1"},),
                created_at="2026-08-16T01:00:00Z",
            )

    def test_lossy_evidence_not_exact(self) -> None:
        run = _run(decision=REG_INCONCLUSIVE, quality=LOSSY)
        rejected = _decide(regression=run)
        self.assertEqual(rejected.decision, REJECTED)
        self.assertEqual(rejected.promotion_evidence_quality, LOSSY)
        allowed = _decide(regression=run, lossy_exception_ref="policy:allow-lossy")
        self.assertEqual(allowed.decision, PROMOTED)
        self.assertEqual(allowed.promotion_evidence_quality, LOSSY)  # never upgraded

    def test_policy_gate(self) -> None:
        decision = _decide(policy_ref="promotion-policy-v3")
        self.assertEqual(_gate(decision, "policy").status, GATE_PASS)
        self.assertTrue(
            any(ref.get("policy_ref") == "promotion-policy-v3" for ref in decision.evidence_refs)
        )
        without = _decide()
        self.assertEqual(_gate(without, "policy").status, GATE_NOT_APPLICABLE)
        self.assertEqual(without.decision, PROMOTED)

    def test_safety_gate(self) -> None:
        critical = (
            CriticalRegression(
                task_id="T",
                category="security",
                baseline_status=PASS,
                candidate_status=FAIL,
                evidence_refs=({"kind": "safety-regression"},),
            ),
        )
        rejected = _decide(regression=_run(decision=IMPROVED, critical=critical))
        self.assertEqual(_gate(rejected, "safety").status, GATE_FAIL)
        self.assertEqual(rejected.decision, REJECTED)
        outside = _decide(
            regression=_run(decision=IMPROVED, critical=critical),
            safety_categories=("data_integrity",),
        )
        self.assertEqual(_gate(outside, "safety").status, GATE_PASS)
        self.assertEqual(outside.decision, REJECTED)  # regression gate still blocks

    def test_cross_backend_shape(self) -> None:
        codex = _decide(regression=_run(evidence=({"backend": "codex", "event_id": "e1"},)))
        agentscope = _decide(
            regression=_run(evidence=({"backend": "agentscope", "event_id": "e2"},)),
        )
        self.assertEqual(
            {field.name for field in fields(codex)},
            {field.name for field in fields(agentscope)},
        )
        self.assertEqual(codex.decision, agentscope.decision)
        self.assertEqual(codex.decision, PROMOTED)
        self.assertEqual(codex.candidate_ref, agentscope.candidate_ref)

    def test_decision_audit_trail(self) -> None:
        decision = _decide(
            initiator_ref={"id": "operator-1"},
            created_at="2026-08-16T00:00:00Z",
        )
        self.assertTrue(decision.decision_id)
        self.assertTrue(decision.candidate_ref)
        self.assertTrue(decision.regression_ref)
        self.assertTrue(decision.evidence_refs)
        self.assertTrue(decision.gate_results)
        self.assertTrue(decision.target_version)
        self.assertTrue(decision.rollback_to_version)
        self.assertTrue(decision.reason)
        self.assertEqual(decision.created_at, "2026-08-16T00:00:00Z")

    def test_owner_not_authorization(self) -> None:
        decision = _decide(candidate=_candidate(owner_ref={"id": "owner-1"}))
        self.assertEqual(decision.owner_ref, {"id": "owner-1"})
        self.assertIsNone(decision.authorized_principal)
        self.assertEqual(decision.authorization, "PARTIAL")

    def test_initiator_not_authorization(self) -> None:
        decision = _decide(
            initiator_ref={"id": "initiator-1"},
            authorized_principal={"id": "principal-1"},
        )
        self.assertEqual(decision.initiator_ref, {"id": "initiator-1"})
        self.assertEqual(decision.authorized_principal, {"id": "principal-1"})
        self.assertEqual(decision.authorization, "AUTHORIZED")
        without = _decide(initiator_ref={"id": "initiator-1"})
        self.assertIsNone(without.authorized_principal)
        self.assertEqual(without.authorization, "PARTIAL")

    def test_decision_replay_stable(self) -> None:
        first = _decide(created_at="2026-08-16T00:00:00Z")
        second = _decide(created_at="2026-08-16T00:00:00Z")
        self.assertEqual(first, second)
        self.assertEqual(first.decision_id, second.decision_id)


if __name__ == "__main__":
    unittest.main()
