"""Offline tests for the Phase 6-E.6 attribution policy (no provider calls)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from provider_probe import (  # noqa: E402
    ATTRIBUTION_CASE_IDS,
    _attribution_gate,
    classify_attribution,
)


def _classify(baseline, candidate, **kwargs):
    return classify_attribution(
        list(baseline),
        list(candidate),
        **kwargs,
    )[0]


def test_stable_divergence_is_candidate_regression():
    assert (
        _classify(["PASS"] * 5, ["INCONCLUSIVE"] * 5)
        == "CANDIDATE_REGRESSION"
    )


def test_candidate_swing_is_provider_nondeterminism():
    assert (
        _classify(
            ["PASS"] * 5,
            ["PASS", "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE"],
        )
        == "PROVIDER_NONDETERMINISM"
    )


def test_baseline_instability_wins_over_candidate_swing():
    assert (
        _classify(
            ["PASS", "INCONCLUSIVE", "PASS", "PASS", "PASS"],
            ["INCONCLUSIVE"] * 5,
        )
        == "BASELINE_INSTABILITY"
    )


def test_incomplete_matrix_is_insufficient():
    assert (
        _classify(
            ["PASS"] * 4,
            ["INCONCLUSIVE"] * 5,
            matrix_complete=False,
            failure_kinds=("TIMEOUT",),
        )
        == "INSUFFICIENT_EVIDENCE"
    )


def test_unreproduced_anomaly_is_nondeterminism():
    assert _classify(["PASS"] * 5, ["PASS"] * 5) == "PROVIDER_NONDETERMINISM"


def test_gate_mapping():
    safe = _attribution_gate(
        {
            "TASK-JUDGE-01": "PROVIDER_NONDETERMINISM",
            "CAL-08": "BASELINE_INSTABILITY",
            "CAL-18": "PROVIDER_NONDETERMINISM",
        }
    )
    assert safe["decision"] == "REGRESSION_SAFETY_CONFIRMED"
    confirmed = _attribution_gate(
        {
            "TASK-JUDGE-01": "CANDIDATE_REGRESSION",
            "CAL-08": "PROVIDER_NONDETERMINISM",
            "CAL-18": "PROVIDER_NONDETERMINISM",
        }
    )
    assert confirmed["decision"] == "REGRESSION_CONFIRMED"
    insufficient = _attribution_gate(
        {
            "TASK-JUDGE-01": "INSUFFICIENT_EVIDENCE",
            "CAL-08": "PROVIDER_NONDETERMINISM",
            "CAL-18": "PROVIDER_NONDETERMINISM",
        }
    )
    assert insufficient["decision"] == "INSUFFICIENT_EVIDENCE"


def test_attribution_cases_match_e5_anomalies():
    assert set(ATTRIBUTION_CASE_IDS) == {"TASK-JUDGE-01", "CAL-08", "CAL-18"}
