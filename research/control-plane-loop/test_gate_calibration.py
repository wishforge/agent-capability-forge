"""S7.3 gate calibration tests: three-state gate + required semantics.

Run from research/control-plane-loop:
  .venv/bin/python -m unittest test_gate_calibration -v
No network needed.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import evaluation_result as er
from evaluation_result import JudgeConfig, evaluate_sample
from gate_calibration import gate_decide, tiny_result


class FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        choice = SimpleNamespace(
            message=SimpleNamespace(content=self.content), finish_reason=None
        )
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, content=""):
        self.chat = SimpleNamespace(completions=FakeCompletions(content))


SAMPLE = {
    "sample_id": "gold-v2-000",
    "task": "Task: fix a bug\n\nWrite the implementation plan as Markdown.",
    "reference": "# Reference\n\n## Change\n\n```python\nx = 1\n```\n",
    "plan": "# Plan\n\n## Change\n\n```python\nx = 2\n```\n",
}


def scores(values):
    return [tiny_result(score=s) for s in values]


class TestGateSemantics(unittest.TestCase):
    def test_clearly_better_is_pass(self):
        b = scores([0.45, 0.5, 0.55, 0.45, 0.5, 0.55])
        c = scores([0.75, 0.8, 0.85, 0.75, 0.8, 0.85])
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "PASS")
        self.assertIn("stable_delta", out["reasons"])

    def test_clearly_worse_is_fail(self):
        b = scores([0.75, 0.8, 0.85, 0.75, 0.8, 0.85])
        c = scores([0.45, 0.5, 0.55, 0.45, 0.5, 0.55])
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "FAIL")
        self.assertIn("stable_delta", out["reasons"])

    def test_near_equal_is_inconclusive(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        c = scores([0.42, 0.52, 0.62, 0.42, 0.52, 0.62])
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("variance_too_large", out["reasons"])

    def test_insufficient_evidence_is_inconclusive(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        c = scores([0.45, 0.55, 0.65, 0.45, 0.55, 0.65])
        c[0]["evaluation_status"] = "JUDGE_ERROR"
        c[0]["score"] = None
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("insufficient_evidence", out["reasons"])

    def test_critical_regression_is_fail_even_with_higher_score(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        c = scores([0.8, 0.85, 0.9, 0.8, 0.85, 0.9])
        c[0]["agent_outcome"] = "NO_PLAN"
        c[0]["evaluation_status"] = "SKIPPED"
        c[0]["score"] = None
        c[0]["judge_skipped_reason"] = "deterministic_failure"
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "FAIL")
        self.assertIn("critical_regression", out["reasons"])

    def test_l0_regression_is_fail(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        c = scores([0.8, 0.85, 0.9, 0.8, 0.85, 0.9])
        c[0]["judge_skipped_reason"] = "deterministic_failure"
        c[0]["evaluation_status"] = "SKIPPED"
        c[0]["score"] = None
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "FAIL")
        self.assertIn("critical_regression", out["reasons"])

    def test_judge_error_is_not_treated_as_zero(self):
        result = evaluate_sample(SAMPLE, JudgeConfig(model="m"), "run-x",
                                 client=FakeClient(""))
        self.assertEqual(result.agent_outcome, "SUCCESS")
        self.assertEqual(result.evaluation_status, "JUDGE_ERROR")
        self.assertIsNone(result.score)
        out = gate_decide([tiny_result(score=0.5)], [result.to_dict()])
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("insufficient_evidence", out["reasons"])

    def test_same_input_same_evidence_same_gate_result(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        c = scores([0.75, 0.8, 0.85, 0.75, 0.8, 0.85])
        self.assertEqual(gate_decide(b, c), gate_decide(list(b), list(c)))

    def test_small_perturbation_does_not_flip_decision(self):
        b = scores([0.4, 0.5, 0.6, 0.4, 0.5, 0.6])
        near = scores([0.42, 0.52, 0.62, 0.42, 0.52, 0.62])
        base = gate_decide(b, near)["verdict"]
        for delta in (-0.02, 0.02, -0.05, 0.05):
            shifted = [dict(r, score=None if r["score"] is None
                            else round(r["score"] + delta, 6)) for r in near]
            self.assertEqual(gate_decide(b, shifted)["verdict"], base)

    def test_dataset_mismatch_is_inconclusive(self):
        b = [tiny_result("gold-v2-000", dataset_version="gold-v2", score=0.4)]
        c = [tiny_result("gold-v2-000", dataset_version="gold-v3", score=0.9)]
        out = gate_decide(b, c)
        self.assertEqual(out["verdict"], "INCONCLUSIVE")
        self.assertIn("dataset_mismatch", out["reasons"])


if __name__ == "__main__":
    unittest.main()
