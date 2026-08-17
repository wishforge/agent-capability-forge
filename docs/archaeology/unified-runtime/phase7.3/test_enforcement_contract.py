"""Offline tests for the Phase 7.3 enforcement boundary validator."""

from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from validate_enforcement_contract import (  # noqa: E402
    ADOPTION_BLOCK_CODES,
    validate,
)


def valid_state() -> dict:
    state = {
        "policies": {
            "pol-1": {
                "version": "1",
                "registered": True,
                "frozen": True,
                "content_hash": "p1",
                "commit_ref": "c1",
            }
        },
        "candidates": {
            "cand-1": {
                "version": "v1",
                "created_at": "2026-08-17T00:00:00Z",
                "baseline_ref": "base-1",
                "change_ref": "change-1",
                "dataset_ref": "ds-1",
                "git_commit": "g1",
                "recorded_artifact_hashes": {"prompt": "a1"},
                "current_artifact_hashes": {"prompt": "a1"},
            }
        },
        "runs": [
            {
                "run_id": "run-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "policy_ref": "pol-1",
                "policy_version": "1",
                "status": "EVALUATED",
                "created_at": "2026-08-17T00:30:00Z",
                "evidence_ids": ["ev-1"],
                "manifest_recorded_hash": "m1",
                "manifest_current_hash": "m1",
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "run_id": "run-1",
                "recorded_hash": "e1",
                "current_hash": "e1",
                "artifact_ref": "art-1",
            }
        ],
        "provenance": {
            "cand-1": {
                "policy": True,
                "evidence_manifest": True,
                "run_ids": ["run-1"],
                "immutable_artifact_refs": ["art-1"],
            }
        },
        "decisions": [
            {
                "decision_id": "dec-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "run_id": "run-1",
                "policy_ref": "pol-1",
                "policy_version": "1",
                "value": "PROMOTE",
                "gate_result": "PASS",
                "created_at": "2026-08-17T01:00:00Z",
                "recorded_hash": "d1",
                "current_hash": "d1",
            }
        ],
        "lifecycle": {
            "cand-1": {
                "status": "PROMOTABLE",
                "transitions": [
                    {"from": "DRAFT", "to": "EVALUATING"},
                    {"from": "EVALUATING", "to": "EVALUATED"},
                    {"from": "EVALUATED", "to": "REGRESSION_CHECKED"},
                    {"from": "REGRESSION_CHECKED", "to": "PROMOTION_REVIEW"},
                    {"from": "PROMOTION_REVIEW", "to": "PROMOTABLE"},
                    {"from": "PROMOTABLE", "to": "PROMOTED"},
                ],
            }
        },
        "extensions": {},
        "adoptions": [
            {
                "adoption_id": "adopt-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "decision_id": "dec-1",
                "policy_version": "1",
            }
        ],
    }
    return state


def blocked_codes(state: dict) -> set[str]:
    report = validate(state)
    return {
        v["message"].split()[0]
        for v in report["violations"]
        if v["code"] == "ADOPTION_BLOCKED"
    }


def _add_second_candidate(state: dict) -> None:
    state["candidates"]["cand-2"] = {
        "version": "v1",
        "created_at": "2026-08-17T00:00:00Z",
        "baseline_ref": "base-1",
        "change_ref": "change-1",
        "dataset_ref": "ds-1",
        "git_commit": "g1",
        "recorded_artifact_hashes": {"prompt": "a1"},
        "current_artifact_hashes": {"prompt": "a1"},
    }
    state["provenance"]["cand-2"] = copy.deepcopy(state["provenance"]["cand-1"])


def test_valid_promote_adoption_allowed() -> None:
    report = validate(valid_state())
    assert report["pass"], report
    assert report["verdict"] == "ENFORCEMENT_BOUNDARY_VALID"
    assert report["adoptions_allowed"] is True


def test_no_policy_blocks_adoption() -> None:
    state = valid_state()
    del state["policies"]["pol-1"]
    assert "POLICY_NOT_REGISTERED" in blocked_codes(state)
    assert validate(state)["verdict"] == "ENFORCEMENT_BOUNDARY_INVALID"


def test_unfrozen_policy_blocks_adoption() -> None:
    state = valid_state()
    state["policies"]["pol-1"]["frozen"] = False
    assert "POLICY_NOT_FROZEN" in blocked_codes(state)


def test_policy_mismatch_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["policy_version"] = "2"
    assert "RUN_POLICY_MISMATCH" in blocked_codes(state)
    state = valid_state()
    state["adoptions"][0]["policy_version"] = "2"
    assert "POLICY_VERSION_MISMATCH" in blocked_codes(state)


def test_candidate_mismatch_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["candidate_version"] = "v2"
    assert "CANDIDATE_VERSION_MISMATCH" in blocked_codes(state)


def test_incomplete_provenance_blocks_adoption() -> None:
    state = valid_state()
    state["provenance"]["cand-1"]["policy"] = False
    assert "PROVENANCE_INCOMPLETE" in blocked_codes(state)


@pytest.mark.parametrize("value", ["HOLD", "REJECTED"])
def test_non_promote_decision_blocks_adoption(value: str) -> None:
    state = valid_state()
    state["decisions"][0]["value"] = value
    assert "DECISION_NOT_PROMOTE" in blocked_codes(state)


def test_hold_lifecycle_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "HOLD"
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)
    assert validate(state)["adoptions_allowed"] is False


def test_rejected_lifecycle_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "REJECTED"
    state["lifecycle"]["cand-1"]["transitions"] = []
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)
    assert validate(state)["adoptions_allowed"] is False


def test_stale_decision_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"].append(
        {
            "decision_id": "dec-2",
            "candidate_id": "cand-1",
            "candidate_version": "v1",
            "run_id": "run-1",
            "policy_ref": "pol-1",
            "policy_version": "1",
            "value": "PROMOTE",
            "gate_result": "PASS",
            "created_at": "2026-08-17T02:00:00Z",
            "recorded_hash": "d2",
            "current_hash": "d2",
        }
    )
    assert "STALE_DECISION" in blocked_codes(state)


def test_gate_not_pass_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["gate_result"] = "HOLD"
    assert "GATE_NOT_PASS" in blocked_codes(state)


def test_tampered_decision_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["current_hash"] = "tampered"
    assert "DECISION_TAMPERED" in blocked_codes(state)


def test_tampered_evidence_blocks_adoption() -> None:
    state = valid_state()
    state["evidence"][0]["current_hash"] = "tampered"
    assert "EVIDENCE_TAMPERED" in blocked_codes(state)


def test_no_adoption_is_partial() -> None:
    state = valid_state()
    state["adoptions"] = []
    assert validate(state)["verdict"] == "ENFORCEMENT_BOUNDARY_PARTIAL"


def test_a_decision_candidate_id_mismatch_blocks_adoption() -> None:
    state = valid_state()
    _add_second_candidate(state)
    state["adoptions"][0]["candidate_id"] = "cand-2"
    report = validate(state)
    assert report["verdict"] == "ENFORCEMENT_BOUNDARY_PARTIAL"
    assert report["adoptions_allowed"] is False
    assert "CANDIDATE_ID_MISMATCH" in blocked_codes(state)


def test_b_decision_run_candidate_id_mismatch_blocks_adoption() -> None:
    state = valid_state()
    _add_second_candidate(state)
    state["decisions"][0]["candidate_id"] = "cand-2"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "CANDIDATE_ID_MISMATCH" in blocked_codes(state)


def test_c_lifecycle_draft_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "DRAFT"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)


def test_d_lifecycle_evaluating_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "EVALUATING"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)


def test_e_lifecycle_promotion_review_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "PROMOTION_REVIEW"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)


def test_f_missing_lifecycle_blocks_adoption() -> None:
    state = valid_state()
    del state["lifecycle"]["cand-1"]
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "MISSING_LIFECYCLE" in blocked_codes(state)


def test_g_promotable_valid_transition_allows_adoption() -> None:
    report = validate(valid_state())
    assert report["adoptions_allowed"] is True
    assert report["verdict"] == "ENFORCEMENT_BOUNDARY_VALID"


def test_h_promote_invalid_transition_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["transitions"] = state["lifecycle"]["cand-1"]["transitions"][:-1]
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "INVALID_ADOPTION_LIFECYCLE" in blocked_codes(state)


def test_i_all_bindings_consistent_allows_adoption() -> None:
    state = valid_state()
    report = validate(state)
    assert report["pass"]
    assert report["violations"] == []
    assert report["adoptions_allowed"] is True
    assert report["verdict"] == "ENFORCEMENT_BOUNDARY_VALID"


def test_missing_run_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["run_id"] = "run-missing"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "RUN_MISSING" in blocked_codes(state)


def test_doc_lists_all_adoption_block_codes() -> None:
    doc = pathlib.Path(__file__).resolve().parents[1] / "64-protocol-enforcement-boundary.md"
    text = doc.read_text(encoding="utf-8")
    missing = [code for code in ADOPTION_BLOCK_CODES if code not in text]
    assert not missing, f"doc missing ADOPTION_BLOCKED codes: {missing}"
