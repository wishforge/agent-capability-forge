"""Offline tests for the Phase 6-E.5 candidate gate logic."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from provider_probe import (  # noqa: E402
    CONTRACT_CASE_IDS,
    REGRESSION_CASE_IDS,
    STABLE_PASS_CASE_IDS,
    classify_change,
    evaluate_gate,
)


def _row(decision: str, verdict: str | None = None, kind: str | None = None) -> dict:
    outcome = {"decision": decision}
    if verdict is not None:
        outcome.update(
            final_verdict=verdict,
            final_confidence="LOW",
            final_score=None,
        )
    if kind is not None:
        outcome["error_kind"] = kind
    return {"case_id": "x", "outcome": outcome}


def test_classify_change():
    assert (
        classify_change(
            _row("REJECT", kind="INVALID_OUTPUT"),
            _row("ACCEPT", "INCONCLUSIVE"),
            "INCONCLUSIVE",
        )[0]
        == "IMPROVEMENT"
    )
    assert (
        classify_change(
            _row("ACCEPT", "PASS"),
            _row("ACCEPT", "FAIL"),
            "PASS",
        )[0]
        == "REGRESSION"
    )
    assert (
        classify_change(
            _row("ACCEPT", "PASS"),
            _row("ACCEPT", "PASS"),
            "PASS",
        )[0]
        == "UNCHANGED"
    )
    assert (
        classify_change(
            _row("REJECT", kind="TIMEOUT"),
            _row("ACCEPT", "INCONCLUSIVE"),
            "INCONCLUSIVE",
        )[0]
        == "UNCLASSIFIED"
    )


def test_gate_accepts_when_target_fixed_and_no_regression():
    target_b = [_row("REJECT", kind="INVALID_OUTPUT")] * 3
    target_c = [_row("ACCEPT", "INCONCLUSIVE")] * 3
    gate = evaluate_gate(
        target_b,
        target_c,
        [{"case_id": "CAL-08", "change_type": "UNCHANGED"}],
    )
    assert gate["decision"] == "CANDIDATE_ACCEPTED_FOR_PROMOTION_REVIEW"


def test_gate_rejects_on_regression():
    target_b = [_row("REJECT", kind="INVALID_OUTPUT")] * 3
    target_c = [_row("ACCEPT", "INCONCLUSIVE")] * 3
    gate = evaluate_gate(
        target_b,
        target_c,
        [{"case_id": "CAL-08", "change_type": "REGRESSION"}],
    )
    assert gate["decision"] == "CANDIDATE_REJECTED"


def test_gate_prioritizes_regression_over_provider_error():
    target_b = [_row("REJECT", kind="TIMEOUT")] * 3
    target_c = [_row("ACCEPT", "INCONCLUSIVE")] * 3
    gate = evaluate_gate(
        target_b,
        target_c,
        [{"case_id": "CAL-08", "change_type": "REGRESSION"}],
    )
    assert gate["decision"] == "CANDIDATE_REJECTED"


def test_gate_insufficient_on_provider_error():
    target_b = [_row("REJECT", kind="TIMEOUT")] * 3
    target_c = [_row("ACCEPT", "INCONCLUSIVE")] * 3
    gate = evaluate_gate(target_b, target_c, [])
    assert gate["decision"] == "INSUFFICIENT_EVIDENCE"


def test_regression_set_covers_required_cases():
    covered = set(REGRESSION_CASE_IDS)
    assert "CAL-26" in covered
    assert set(STABLE_PASS_CASE_IDS) <= covered
    assert set(CONTRACT_CASE_IDS) <= covered
