"""S7.2 tests: contract, L0, judge failure handling, aggregation, append-only runs, compare.

Run from research/control-plane-loop:
  .venv/bin/python -m unittest test_evaluation_result -v
No network needed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import evaluation_result as er
from evaluation_result import (
    JudgeConfig,
    aggregate,
    classify_judge_response,
    compare_baseline_candidate,
    evaluate_sample,
    new_run_id,
    replay_result,
    save_run,
)


class FakeCompletions:
    """actions: list of ("response", content) or ("raise", exception)."""

    def __init__(self, actions):
        self.actions = list(actions)

    def create(self, **kwargs):
        action = self.actions.pop(0) if self.actions else ("response", "")
        if action[0] == "raise":
            raise action[1]
        choice = SimpleNamespace(
            message=SimpleNamespace(content=action[1]), finish_reason=None
        )
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, actions):
        self.chat = SimpleNamespace(completions=FakeCompletions(actions))


def valid(content="0.7"):
    return ("response", f'{{"score": {content}, "reasoning": "ok"}}')


SAMPLE = {
    "sample_id": "gold-v1-000",
    "task": "fix the bug",
    "reference": "# Reference plan\n\n```python\nprint(1)\n```",
    "plan": "# Plan\n\n```python\nprint(2)\n```",
}


def sample_with_plan(plan):
    s = dict(SAMPLE)
    s["plan"] = plan
    return s


def tiny_result(sample_id="gold-v1-000", status="OK", score=0.5,
                outcome="SUCCESS", dataset_version="gold-v1"):
    return {
        "sample_id": sample_id,
        "dataset_version": dataset_version,
        "agent_outcome": outcome,
        "evaluation_status": status,
        "score": score,
        "judge_skipped_reason": None,
    }


class TestJudgeClassification(unittest.TestCase):
    def test_empty_judge_response_is_error_not_zero(self):
        parsed = classify_judge_response("")
        self.assertEqual(parsed["category"], "JUDGE_EMPTY_RESPONSE")
        self.assertIsNone(parsed["score"])

    def test_invalid_json_is_parse_error(self):
        parsed = classify_judge_response("not json at all")
        self.assertEqual(parsed["category"], "JUDGE_INVALID_JSON")
        self.assertEqual(parsed["status"], "JUDGE_PARSE_ERROR")
        self.assertIsNone(parsed["score"])

    def test_truncated_response_is_truncated(self):
        parsed = classify_judge_response('{"score": 0.7, "reasoning": "x"',
                                         finish_reason="length")
        self.assertEqual(parsed["category"], "JUDGE_TRUNCATED")
        self.assertEqual(parsed["status"], "JUDGE_TRUNCATED")
        self.assertIsNone(parsed["score"])

    def test_missing_score_classified(self):
        parsed = classify_judge_response('{"reasoning": "ok"}')
        self.assertEqual(parsed["category"], "JUDGE_MISSING_SCORE")
        self.assertIsNone(parsed["score"])


class TestJudgeEvidence(unittest.TestCase):
    def test_insufficient_judge_evidence_no_formal_score(self):
        # 2 valid rounds + 3 rounds that each fail 3 attempts (empty responses)
        actions = [valid()] * 2 + [("response", "")] * 9
        result = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                 client=FakeClient(actions))
        self.assertEqual(result.evaluation_status, "INSUFFICIENT_JUDGE_EVIDENCE")
        self.assertIsNone(result.score)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failure_count, 3)

    def test_judge_error_is_not_agent_failure(self):
        result = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                 client=FakeClient([("response", "")] * 15))
        self.assertEqual(result.evaluation_status, "JUDGE_ERROR")
        self.assertIsNone(result.score)
        self.assertEqual(result.agent_outcome, "SUCCESS")
        self.assertIn("JUDGE_EMPTY_RESPONSE", result.failure_categories)

    def test_retry_recovers_within_max_attempts(self):
        actions = [("raise", RuntimeError("boom")), valid()] + [valid()] * 4
        result = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                 client=FakeClient(actions))
        self.assertEqual(result.evaluation_status, "OK")
        self.assertEqual(result.success_count, 5)
        self.assertGreater(result.judge_attempts, 5)
        self.assertTrue(any(a["error"] for a in result.raw_judge_responses))


class TestL0(unittest.TestCase):
    def test_l0_no_plan_skips_judge(self):
        result = evaluate_sample(sample_with_plan(None), JudgeConfig(model="m"), "run-x")
        self.assertEqual(result.agent_outcome, "NO_PLAN")
        self.assertEqual(result.evaluation_status, "SKIPPED")
        self.assertEqual(result.judge_skipped_reason, "deterministic_failure")
        self.assertEqual(result.judge_attempts, 0)
        self.assertIsNone(result.score)

    def test_l0_invalid_format_skips_judge(self):
        result = evaluate_sample(sample_with_plan("no markdown heading here"),
                                 JudgeConfig(model="m"), "run-x")
        self.assertEqual(result.agent_outcome, "INVALID_FORMAT")
        self.assertEqual(result.evaluation_status, "SKIPPED")
        self.assertIsNone(result.score)

    def test_l0_empty_plan_skips_judge(self):
        result = evaluate_sample(sample_with_plan("   "), JudgeConfig(model="m"), "run-x")
        self.assertEqual(result.agent_outcome, "EMPTY_PLAN")
        self.assertEqual(result.evaluation_status, "SKIPPED")

    def test_missing_reference_is_dataset_invalid_not_agent_failure(self):
        s = dict(SAMPLE)
        s["reference"] = "  "
        result = evaluate_sample(s, JudgeConfig(model="m"), "run-x")
        self.assertEqual(result.evaluation_status, "INVALID_INPUT")
        self.assertIsNone(result.agent_outcome)


class TestAggregation(unittest.TestCase):
    def test_median_is_primary_score(self):
        actions = [valid("0.1"), valid("0.4"), valid("0.9"), valid("0.5"), valid("0.3")]
        result = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                 client=FakeClient(actions))
        self.assertEqual(result.evaluation_status, "OK")
        self.assertEqual(result.score, 0.4)
        self.assertEqual(result.all_scores, [0.1, 0.4, 0.9, 0.5, 0.3])

    def test_deterministic_aggregation_and_classification(self):
        scores = [0.2, 0.7, 0.4]
        self.assertEqual(aggregate(scores), aggregate(scores))
        raw = '{"score": 0.55, "reasoning": "x"}'
        self.assertEqual(classify_judge_response(raw), classify_judge_response(raw))


class TestRuns(unittest.TestCase):
    def test_run_id_uniqueness(self):
        self.assertNotEqual(new_run_id(), new_run_id())

    def test_result_append_only_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            evals = Path(td)
            d1 = save_run([tiny_result()], {"run_id": "same", "experiment": "t"},
                          evals_dir=evals)
            d2 = save_run([tiny_result()], {"run_id": "same", "experiment": "t"},
                          evals_dir=evals)
            self.assertNotEqual(d1, d2)
            self.assertEqual(sorted(p.name for p in evals.iterdir()),
                             sorted([d1.name, d2.name]))
            self.assertTrue((d1 / "run.json").exists())
            self.assertTrue((d1 / "results.jsonl").exists())

    def test_same_input_and_recorded_scores_replay_identically(self):
        actions = [valid("0.2"), valid("0.6"), valid("0.8"), valid("0.5"), valid("0.7")]
        original = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                   client=FakeClient(actions)).to_dict()
        replayed = replay_result(original)
        self.assertEqual(replayed.score, original["score"])
        self.assertEqual(replayed.evaluation_status, original["evaluation_status"])
        self.assertEqual(replayed.agent_outcome, original["agent_outcome"])
        self.assertEqual(replayed.l2["median"], original["l2"]["median"])
        again = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                client=FakeClient(actions)).to_dict()
        self.assertEqual(again["score"], original["score"])
        self.assertEqual(again["all_scores"], original["all_scores"])

    def test_freeze_gold_v1_is_idempotent_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            v0 = Path(td) / "gold-v0.jsonl"
            v1 = Path(td) / "gold-v1.jsonl"
            v0.write_text(json.dumps({
                "sample_id": "gold-v0-000",
                "task": "task",
                "reference": "## plan",
                "metadata": {"source_trace_id": "t1"},
            }, ensure_ascii=False) + "\n")
            with mock.patch.object(er, "GOLD_V0", v0), \
                    mock.patch.object(er, "GOLD_V1", v1):
                er.freeze_gold_v1()
                first = v1.read_bytes()
                er.freeze_gold_v1()
                self.assertEqual(v1.read_bytes(), first)


class TestCompare(unittest.TestCase):
    def test_dataset_mismatch_is_inconclusive(self):
        baseline = [tiny_result("gold-v1-000", dataset_version="gold-v1")]
        candidate = [tiny_result("gold-v1-000", dataset_version="gold-v2")]
        out = compare_baseline_candidate(baseline, candidate)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("dataset_mismatch", out["reasons"])

    def test_insufficient_evidence_is_inconclusive(self):
        baseline = [tiny_result("gold-v1-000", status="OK", score=0.4)]
        candidate = [tiny_result("gold-v1-000",
                                 status="INSUFFICIENT_JUDGE_EVIDENCE", score=None)]
        out = compare_baseline_candidate(baseline, candidate)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("insufficient_evidence", out["reasons"])

    def test_variance_within_noise_is_inconclusive(self):
        baseline = [tiny_result("gold-v1-000", score=s)
                    for s in (0.4, 0.5, 0.6, 0.4, 0.5, 0.6)]
        candidate = [tiny_result("gold-v1-000", score=s)
                     for s in (0.45, 0.55, 0.65, 0.45, 0.55, 0.65)]
        out = compare_baseline_candidate(baseline, candidate)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("variance_too_large", out["reasons"])


if __name__ == "__main__":
    unittest.main()
