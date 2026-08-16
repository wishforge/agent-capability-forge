"""Phase 5-L tests: ImprovementCandidate proposal metadata.

Deterministic, read-only, no auto-apply / promotion / Runtime mutation.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import fields
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

from evaluator import evaluate  # noqa: E402
from failure_attribution import (  # noqa: E402
    MULTIPLE_CANDIDATES,
    FailureAttribution,
    attribute,
)
from golden import TASK_02, _record  # noqa: E402
from improvement_candidate import (  # noqa: E402
    ATTRIBUTION_COMPLETE,
    ATTRIBUTION_INCOMPLETE,
    CHANGE_TYPES,
    INVALID_FOR_REGRESSION,
    METRIC_DRIVEN,
    PROMPT,
    PROPOSED,
    QUALITATIVE_ONLY,
    REQUIRES_DISAMBIGUATION,
    propose,
)


def _failure_attr(**record_kwargs) -> FailureAttribution:
    record = _record(**record_kwargs)
    return attribute(record, evaluate(record, TASK_02))


def _no_failure_attr() -> FailureAttribution:
    return FailureAttribution(
        failure_id="exec-1:NO_FAILURE",
        execution_id="exec-1",
        turn_id=None,
        step_id=None,
        attempt_id=None,
        failure_kind=None,
        evidence_refs=(),
        initiator_ref=None,
        owner_ref=None,
        context_provenance_ref=None,
        backend_event_refs=(),
        mapping_quality="UNKNOWN",
        parent_ref=None,
        ownership="INCONCLUSIVE",
    )


def _no_evidence_attr() -> FailureAttribution:
    attr = _no_failure_attr()
    return FailureAttribution(
        failure_id="exec-1:TOOL_FAILURE:RULE-06",
        execution_id="exec-1",
        turn_id="turn-1",
        step_id="step-1",
        attempt_id="exec-1/attempt-1",
        failure_kind="TOOL_FAILURE",
        evidence_refs=(),
        initiator_ref=None,
        owner_ref=None,
        context_provenance_ref=None,
        backend_event_refs=(),
        mapping_quality="EXACT",
        parent_ref=None,
        ownership="INCONCLUSIVE",
    )


def _proposal(**kwargs) -> dict:
    base = dict(
        target_type="capability",
        target_ref="inventory.lookup",
        change_type=PROMPT,
        change_ref="prompt:agent.system_prompt.v3",
        baseline_ref="prompt:agent.system_prompt.v2",
        hypothesis=(
            "adding an inventory-check policy raises required tool invocation"
        ),
        expected_effect="reduce missing tool calls",
        evaluation_ids=("eval-1",),
    )
    base.update(kwargs)
    return base


class ImprovementCandidateTests(unittest.TestCase):
    def test_candidate_created_from_failure(self) -> None:
        attr = _failure_attr(
            tools=(
                {
                    "call_id": "t1",
                    "name": "lookup",
                    "arguments": {},
                    "backend_event_ref": {
                        "backend": "codex",
                        "event_type": "custom_tool_call",
                        "reference": {"line": 6},
                        "quality": "EXACT",
                    },
                },
            ),
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        candidate = propose(attr, **_proposal())
        self.assertEqual(candidate.source_failure_ids, (attr.failure_id,))
        self.assertEqual(candidate.source_execution_ids, ("exec-1",))
        self.assertEqual(candidate.source_evaluation_ids, ("eval-1",))
        self.assertTrue(candidate.evidence_refs)
        self.assertEqual(candidate.status, PROPOSED)

    def test_candidate_requires_failure_evidence(self) -> None:
        with self.assertRaises(ValueError):
            propose(_no_failure_attr(), **_proposal())
        with self.assertRaises(ValueError):
            propose(_no_evidence_attr(), **_proposal())

    def test_candidate_requires_baseline(self) -> None:
        attr = _failure_attr()
        with self.assertRaises(ValueError):
            propose(attr, **_proposal(baseline_ref=""))
        unknown = propose(attr, **_proposal(baseline_ref="UNKNOWN"))
        self.assertEqual(unknown.status, INVALID_FOR_REGRESSION)

    def test_candidate_target_explicit(self) -> None:
        attr = _failure_attr()
        with self.assertRaises(ValueError):
            propose(attr, **_proposal(target_type=""))
        with self.assertRaises(ValueError):
            propose(attr, **_proposal(target_ref=""))

    def test_candidate_hypothesis_marked(self) -> None:
        attr = _failure_attr()
        candidate = propose(attr, **_proposal())
        self.assertEqual(candidate.hypothesis, _proposal()["hypothesis"])
        self.assertEqual(candidate.status, PROPOSED)
        with self.assertRaises(ValueError):
            propose(attr, **_proposal(hypothesis="VERIFIED"))

    def test_candidate_expected_effect(self) -> None:
        attr = _failure_attr()
        qualitative = propose(attr, **_proposal())
        self.assertEqual(qualitative.expected_effect, "reduce missing tool calls")
        self.assertEqual(qualitative.expected_effect_quality, QUALITATIVE_ONLY)
        self.assertIsNone(qualitative.expected_metric)
        self.assertIsNone(qualitative.expected_delta)

        metric = propose(
            attr,
            **_proposal(
                expected_metric="required_tool_call_rate",
                expected_delta=0.1,
            ),
        )
        self.assertEqual(metric.expected_effect_quality, METRIC_DRIVEN)
        with self.assertRaises(ValueError):
            propose(
                attr,
                **_proposal(
                    baseline_ref="UNKNOWN",
                    expected_metric="required_tool_call_rate",
                ),
            )

    def test_candidate_evidence_refs(self) -> None:
        candidate = propose(
            _failure_attr(
                tools=({"call_id": "t1", "name": "lookup", "arguments": {}},),
                tool_results=(
                    {
                        "tool_call_id": "t1",
                        "content": "boom",
                        "is_error": True,
                        "error_code": "EXECUTION_ERROR",
                    },
                ),
            ),
            **_proposal(),
        )
        self.assertEqual(candidate.source_evaluation_ids, ("eval-1",))
        self.assertEqual(candidate.source_execution_ids, ("exec-1",))
        self.assertTrue(
            any(ref.get("tool_call_id") == "t1" for ref in candidate.evidence_refs)
        )

    def test_lossy_candidate_visible(self) -> None:
        attr = _failure_attr(
            lossiness=(
                {
                    "backend": "codex",
                    "mapping_quality": "LOSSY",
                    "missing_semantics": ("EXEC_FAILURE_STRUCTURED_SUCCESS",),
                },
            ),
        )
        candidate = propose(attr, **_proposal())
        self.assertEqual(candidate.source_mapping_quality, "LOSSY")

    def test_missing_owner_allowed_but_incomplete(self) -> None:
        attr = _failure_attr(owner_refs=())
        candidate = propose(attr, **_proposal())
        self.assertIsNone(candidate.owner_ref)
        self.assertEqual(candidate.attribution_status, ATTRIBUTION_INCOMPLETE)

    def test_missing_initiator_allowed_but_incomplete(self) -> None:
        attr = _failure_attr(initiator_ref=None)
        candidate = propose(attr, **_proposal())
        self.assertIsNone(candidate.initiator_ref)
        self.assertEqual(candidate.attribution_status, ATTRIBUTION_INCOMPLETE)

    def test_multiple_failure_requires_disambiguation(self) -> None:
        attr = _failure_attr(
            tools=(
                {"call_id": "t1", "name": "lookup", "arguments": {}},
                {"call_id": "t2", "name": "other", "arguments": {}},
            ),
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        self.assertEqual(attr.failure_kind, MULTIPLE_CANDIDATES)
        candidate = propose(attr, **_proposal())
        self.assertEqual(candidate.status, REQUIRES_DISAMBIGUATION)
        self.assertEqual(candidate.source_failure_ids, (attr.failure_id,))

    def test_no_arbitrary_code_change(self) -> None:
        self.assertNotIn("ARBITRARY_CODE", CHANGE_TYPES)
        with self.assertRaises(ValueError):
            propose(
                _failure_attr(),
                **_proposal(change_type="ARBITRARY_CODE"),
            )

    def test_candidate_not_auto_applied(self) -> None:
        candidate = propose(_failure_attr(), **_proposal())
        self.assertEqual(candidate.status, PROPOSED)
        self.assertFalse(hasattr(candidate, "apply"))
        self.assertFalse(hasattr(candidate, "promote"))
        self.assertFalse(hasattr(candidate, "rollback"))

    def test_cross_backend_candidate_shape(self) -> None:
        agentscope_ref = {
            "backend": "agentscope",
            "event_type": "tool_result",
            "reference": {"event_id": "e1"},
            "quality": "EXACT",
        }
        codex_ref = {
            "backend": "codex",
            "event_type": "custom_tool_call",
            "reference": {"rollout_path": "codex_error.jsonl", "line": 6},
            "quality": "EXACT",
        }
        attr_a = _failure_attr(
            tools=(
                {
                    "call_id": "t1",
                    "name": "lookup",
                    "arguments": {},
                    "backend_event_ref": agentscope_ref,
                },
            ),
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
        )
        attr_b = _failure_attr(
            tools=(
                {
                    "call_id": "t1",
                    "name": "lookup",
                    "arguments": {},
                    "backend_event_ref": codex_ref,
                },
            ),
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "boom",
                    "is_error": True,
                    "error_code": "EXECUTION_ERROR",
                },
            ),
            lossiness=(
                {
                    "backend": "codex",
                    "mapping_quality": "LOSSY",
                    "missing_semantics": ("EXEC_FAILURE_STRUCTURED_SUCCESS",),
                },
            ),
        )
        candidate_a = propose(attr_a, **_proposal())
        candidate_b = propose(attr_b, **_proposal())
        self.assertEqual(
            {field.name for field in fields(candidate_a)},
            {field.name for field in fields(candidate_b)},
        )
        self.assertEqual(candidate_a.source_mapping_quality, "EXACT")
        self.assertEqual(candidate_b.source_mapping_quality, "LOSSY")
        self.assertIn(agentscope_ref, attr_a.backend_event_refs)
        self.assertIn(codex_ref, attr_b.backend_event_refs)
        self.assertTrue(candidate_a.evidence_refs)
        self.assertTrue(candidate_b.evidence_refs)

    def test_candidate_replay_stable(self) -> None:
        kwargs = _proposal(created_at="2026-01-01T00:00:00Z")
        first = propose(_failure_attr(), **kwargs)
        second = propose(_failure_attr(), **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.source_failure_ids, second.source_failure_ids)


if __name__ == "__main__":
    unittest.main()
