"""Offline tests for the Phase 7.4 Adoption Guard design contract."""

from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from validate_adoption_guard_design import (  # noqa: E402
    BLOCK_CODES,
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
                "forged_artifact_digest": "a1",
            }
        },
        "runs": [
            {
                "run_id": "run-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "artifact_digest": "a1",
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
                "artifact_digest": "a1",
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
        "revocations": [],
        "adoptions": [
            {
                "adoption_id": "adopt-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "promotion_decision_id": "dec-1",
                "evaluation_run_id": "run-1",
                "artifact_digest": "a1",
                "policy_version": "1",
                "requested_by": "control-plane",
                "requested_at": "2026-08-17T01:30:00Z",
                "provenance": {
                    "policy": True,
                    "evidence_manifest": True,
                    "run_ids": ["run-1"],
                    "immutable_artifact_refs": ["art-1"],
                },
            }
        ],
        "registry_promoted": [
            {
                "entry_id": "F+/foo",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "decision_id": "dec-1",
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


def test_valid_adoption_allowed() -> None:
    report = validate(valid_state())
    assert report["pass"], report
    assert report["verdict"] == "ADOPTION_GUARD_DESIGN_VALID"
    assert report["adoptions_allowed"] is True


def test_missing_decision_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["promotion_decision_id"] = "dec-missing"
    assert "MISSING_DECISION" in blocked_codes(state)
    assert validate(state)["adoptions_allowed"] is False


def test_wrong_candidate_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["candidate_id"] = "cand-2"
    assert "CANDIDATE_ID_MISMATCH" in blocked_codes(state)


def test_wrong_version_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["candidate_version"] = "v2"
    assert "CANDIDATE_VERSION_MISMATCH" in blocked_codes(state)


def test_wrong_policy_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["policy_version"] = "2"
    assert "POLICY_VERSION_MISMATCH" in blocked_codes(state)


def test_unfrozen_policy_blocks_adoption() -> None:
    state = valid_state()
    state["policies"]["pol-1"]["frozen"] = False
    assert "POLICY_NOT_FROZEN" in blocked_codes(state)


def test_missing_provenance_blocks_adoption() -> None:
    state = valid_state()
    del state["adoptions"][0]["provenance"]
    state["provenance"]["cand-1"]["policy"] = False
    assert "PROVENANCE_INCOMPLETE" in blocked_codes(state)


def test_invalid_lifecycle_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "DRAFT"
    assert "INVALID_LIFECYCLE" in blocked_codes(state)


def test_missing_lifecycle_blocks_adoption() -> None:
    state = valid_state()
    del state["lifecycle"]["cand-1"]
    assert "MISSING_LIFECYCLE" in blocked_codes(state)


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


def test_superseding_hold_blocks_old_promote() -> None:
    state = valid_state()
    state["decisions"].append(
        {
            "decision_id": "dec-2",
            "candidate_id": "cand-1",
            "candidate_version": "v1",
            "run_id": "run-1",
            "policy_ref": "pol-1",
            "policy_version": "1",
            "value": "HOLD",
            "gate_result": "HOLD",
            "created_at": "2026-08-17T02:00:00Z",
            "recorded_hash": "d2",
            "current_hash": "d2",
        }
    )
    assert "STALE_DECISION" in blocked_codes(state)


def test_rejected_candidate_blocks_adoption() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["status"] = "REJECTED"
    state["lifecycle"]["cand-1"]["transitions"] = []
    assert "CANDIDATE_REJECTED" in blocked_codes(state)


def test_revoked_candidate_blocks_adoption() -> None:
    state = valid_state()
    state["revocations"].append(
        {
            "revocation_id": "rev-1",
            "candidate_id": "cand-1",
            "candidate_version": "v1",
            "decision_id": "dec-1",
            "revoked_at": "2026-08-17T02:30:00Z",
            "reason": "critical incident",
        }
    )
    assert "REVOKED_DECISION" in blocked_codes(state)


def test_direct_promoted_state_without_decision_blocks() -> None:
    state = valid_state()
    state["registry_promoted"][0]["decision_id"] = None
    report = validate(state)
    assert report["pass"] is False
    assert "PROMOTED_WITHOUT_DECISION" in blocked_codes(state)


def test_legacy_promoted_decision_value_blocks() -> None:
    """Phase 5-N promotion.py uses value='PROMOTED' for a decision result;
    the canonical adoption contract requires value='PROMOTE' (66 section 6)."""
    state = valid_state()
    state["decisions"][0]["value"] = "PROMOTED"
    assert "DECISION_NOT_PROMOTE" in blocked_codes(state)


def test_request_metadata_missing_blocks() -> None:
    state = valid_state()
    del state["adoptions"][0]["requested_by"]
    assert "REQUEST_METADATA_MISSING" in blocked_codes(state)


def test_no_revocation_info_is_valid_with_unknown() -> None:
    state = valid_state()
    del state["revocations"]
    report = validate(state)
    assert report["pass"], report
    assert report["verdict"] == "ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN"
    assert report["unknowns"]["revocation"] == "UNKNOWN"


def test_doc_lists_all_block_codes() -> None:
    doc = pathlib.Path(__file__).resolve().parents[1] / "66-adoption-guard-design.md"
    text = doc.read_text(encoding="utf-8")
    missing = [code for code in BLOCK_CODES if code not in text]
    assert not missing, f"doc missing ADOPTION_BLOCKED codes: {missing}"


def test_missing_run_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["run_id"] = "run-missing"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "RUN_MISSING" in blocked_codes(state)


def test_run_mismatch_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["evaluation_run_id"] = "run-2"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "RUN_MISMATCH" in blocked_codes(state)


def test_policy_not_registered_blocks_adoption() -> None:
    state = valid_state()
    state["policies"]["pol-1"]["registered"] = False
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "POLICY_NOT_REGISTERED" in blocked_codes(state)


def test_run_policy_mismatch_blocks_adoption() -> None:
    state = valid_state()
    state["runs"][0]["policy_ref"] = "pol-2"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "RUN_POLICY_MISMATCH" in blocked_codes(state)


def test_gate_not_pass_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["gate_result"] = "HOLD"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "GATE_NOT_PASS" in blocked_codes(state)


def test_tampered_decision_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["current_hash"] = "tampered"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "DECISION_TAMPERED" in blocked_codes(state)


def test_tampered_evidence_blocks_adoption() -> None:
    state = valid_state()
    state["evidence"][0]["current_hash"] = "tampered"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "EVIDENCE_TAMPERED" in blocked_codes(state)


def test_stale_decision_timestamp_blocks_adoption() -> None:
    state = valid_state()
    state["decisions"][0]["created_at"] = "2026-08-16T23:59:59Z"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "STALE_DECISION" in blocked_codes(state)


def test_artifact_digest_mismatch_blocks_adoption() -> None:
    state = valid_state()
    state["adoptions"][0]["artifact_digest"] = "a2"
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(state)


def test_missing_decision_timestamp_blocks_adoption() -> None:
    state = valid_state()
    del state["decisions"][0]["created_at"]
    report = validate(state)
    assert report["adoptions_allowed"] is False
    assert "MISSING_DECISION_TIMESTAMP" in blocked_codes(state)


def test_matching_artifact_digests_allow_adoption() -> None:
    report = validate(valid_state())
    assert report["pass"], report
    assert report["adoptions_allowed"] is True
    assert "ARTIFACT_DIGEST_MISMATCH" not in blocked_codes(valid_state())


def test_hardening_doc_lists_new_codes() -> None:
    doc = pathlib.Path(__file__).resolve().parents[1] / "67-phase7.4-adoption-guard-hardening.md"
    text = doc.read_text(encoding="utf-8")
    for code in ("ARTIFACT_DIGEST_MISMATCH", "MISSING_DECISION_TIMESTAMP"):
        assert code in text
