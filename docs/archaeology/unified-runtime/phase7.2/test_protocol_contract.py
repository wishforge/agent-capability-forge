"""Offline tests for the Phase 7.2 protocol contract validator."""

from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from validate_protocol_contract import (  # noqa: E402
    CONTRACTS,
    validate,
    validate_extension_isolation,
)


def valid_state() -> dict:
    return {
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
                "policy_ref": "pol-1",
                "policy_version": "1",
                "status": "EVALUATED",
                "created_at": "2026-08-17T00:00:00Z",
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
                "run_id": "run-1",
                "policy_ref": "pol-1",
                "value": "PROMOTE",
                "gate_result": "PASS",
                "recorded_hash": "d1",
                "current_hash": "d1",
            }
        ],
        "lifecycle": {
            "cand-1": {
                "status": "PROMOTED",
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
    }


def assert_ok(state: dict) -> dict:
    report = validate(state)
    assert report["pass"], report
    return report


def assert_violations(state: dict, expected: set[tuple[str, str]]) -> dict:
    report = validate(state)
    got = {(v["code"], v["invariant"]) for v in report["violations"]}
    assert expected <= got, report
    return report


def hold_reentry_lifecycle() -> dict:
    return {
        "status": "EVALUATING",
        "transitions": [
            {"from": "DRAFT", "to": "EVALUATING"},
            {"from": "EVALUATING", "to": "EVALUATED"},
            {"from": "EVALUATED", "to": "REGRESSION_CHECKED"},
            {"from": "REGRESSION_CHECKED", "to": "PROMOTION_REVIEW"},
            {"from": "PROMOTION_REVIEW", "to": "HOLD"},
            {"from": "HOLD", "to": "EVALUATING"},
        ],
    }


def test_valid_core_state_passes() -> None:
    report = assert_ok(valid_state())
    assert report["verdict"] == "CONTRACT_VALID"


def test_g1_missing_policy_blocks_promote() -> None:
    state = valid_state()
    del state["policies"]["pol-1"]
    assert_violations(state, {("GOVERNANCE_BLOCK", "G1")})


def test_g1_unregistered_policy_blocks_promote() -> None:
    state = valid_state()
    state["policies"]["pol-1"]["registered"] = False
    assert_violations(state, {("GOVERNANCE_BLOCK", "G1")})


def test_g2_unfrozen_policy_blocks_promote() -> None:
    state = valid_state()
    state["policies"]["pol-1"]["frozen"] = False
    report = assert_violations(state, {("GOVERNANCE_BLOCK", "G2")})
    assert any("POLICY_NOT_FROZEN" in v["message"] for v in report["violations"])


def test_g3_run_policy_mismatch_blocks_promote() -> None:
    state = valid_state()
    state["runs"][0]["policy_version"] = "2"
    report = assert_violations(state, {("GOVERNANCE_BLOCK", "G3")})
    assert any("RUN_POLICY_MISMATCH" in v["message"] for v in report["violations"])


@pytest.mark.parametrize("missing_key", ["policy", "evidence_manifest"])
def test_g4_missing_provenance_flag_blocks_promote(missing_key: str) -> None:
    state = valid_state()
    del state["provenance"]["cand-1"][missing_key]
    report = assert_violations(state, {("PROVENANCE_INCOMPLETE", "G4")})
    assert any("PROVENANCE_INCOMPLETE" in v["message"] for v in report["violations"])


@pytest.mark.parametrize("missing_field", ["run_ids", "immutable_artifact_refs"])
def test_g4_missing_provenance_list_blocks_promote(missing_field: str) -> None:
    state = valid_state()
    state["provenance"]["cand-1"][missing_field] = []
    assert_violations(state, {("PROVENANCE_INCOMPLETE", "G4")})


def test_g5_evidence_content_change_detected() -> None:
    state = valid_state()
    state["evidence"][0]["current_hash"] = "tampered"
    report = assert_violations(state, {("IMMUTABILITY_VIOLATION", "G5")})
    assert any("EVIDENCE_TAMPERED" in v["message"] for v in report["violations"])


def test_g5_artifact_hash_change_detected() -> None:
    state = valid_state()
    state["candidates"]["cand-1"]["current_artifact_hashes"]["prompt"] = "changed"
    assert_violations(state, {("IMMUTABILITY_VIOLATION", "G5")})


def test_g5_manifest_change_detected() -> None:
    state = valid_state()
    state["runs"][0]["manifest_current_hash"] = "changed"
    report = assert_violations(state, {("IMMUTABILITY_VIOLATION", "G5")})
    assert any("MANIFEST_TAMPERED" in v["message"] for v in report["violations"])


def test_g6_hold_reentry_without_new_run_rejected() -> None:
    state = valid_state()
    state["decisions"] = []
    state["runs"][0]["status"] = "HOLD"
    state["lifecycle"]["cand-1"] = hold_reentry_lifecycle()
    report = assert_violations(state, {("CONTRACT_VIOLATION", "G6")})
    assert any("HOLD_REENTRY_WITHOUT_NEW_RUN" in v["message"] for v in report["violations"])


def test_g6_hold_reentry_with_new_run_passes() -> None:
    state = valid_state()
    state["decisions"] = []
    state["runs"][0]["status"] = "HOLD"
    state["runs"].append(
        {
            "run_id": "run-2",
            "candidate_id": "cand-1",
            "policy_ref": "pol-1",
            "policy_version": "1",
            "status": "EVALUATED",
            "created_at": "2026-08-17T01:00:00Z",
            "evidence_ids": [],
            "manifest_recorded_hash": "m2",
            "manifest_current_hash": "m2",
        }
    )
    state["lifecycle"]["cand-1"] = hold_reentry_lifecycle()
    assert_ok(state)


def test_g6_hold_reentry_reusing_run_rejected() -> None:
    state = valid_state()
    state["decisions"] = []
    state["runs"][0]["status"] = "HOLD"
    state["runs"].append(dict(state["runs"][0], created_at="2026-08-17T01:00:00Z", status="EVALUATED"))
    state["lifecycle"]["cand-1"] = hold_reentry_lifecycle()
    report = assert_violations(state, {("CONTRACT_VIOLATION", "G6")})
    assert any("RUN_REUSE_AFTER_HOLD" in v["message"] for v in report["violations"])


def test_g7_new_run_does_not_modify_old() -> None:
    state = valid_state()
    state["runs"].append(
        {
            "run_id": "run-2",
            "candidate_id": "cand-1",
            "policy_ref": "pol-1",
            "policy_version": "1",
            "status": "EVALUATED",
            "created_at": "2026-08-17T01:00:00Z",
            "evidence_ids": ["ev-2"],
            "manifest_recorded_hash": "m2",
            "manifest_current_hash": "m2",
        }
    )
    state["evidence"].append(
        {
            "evidence_id": "ev-2",
            "run_id": "run-2",
            "recorded_hash": "e2",
            "current_hash": "e2",
            "artifact_ref": "art-2",
        }
    )
    assert_ok(state)


def test_g7_duplicate_run_overwrite_detected() -> None:
    state = valid_state()
    state["runs"].append(dict(state["runs"][0], evidence_ids=["ev-2"]))
    report = assert_violations(state, {("IMMUTABILITY_VIOLATION", "G7")})
    assert any("EVALUATIONRUN_OVERWRITTEN" in v["message"] for v in report["violations"])


def test_g7_duplicate_decision_overwrite_detected() -> None:
    state = valid_state()
    state["decisions"].append(dict(state["decisions"][0], value="HOLD"))
    report = assert_violations(state, {("IMMUTABILITY_VIOLATION", "G7")})
    assert any("DECISION_OVERWRITTEN" in v["message"] for v in report["violations"])


def test_illegal_transition_rejected() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["transitions"].append({"from": "DRAFT", "to": "PROMOTED"})
    report = assert_violations(state, {("INVALID_TRANSITION", "LIFECYCLE")})
    assert any("ILLEGAL_TRANSITION" in v["message"] for v in report["violations"])


def test_rejected_is_terminal() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"] = {
        "status": "REJECTED",
        "transitions": [{"from": "REJECTED", "to": "PROMOTED"}],
    }
    report = assert_violations(state, {("INVALID_TRANSITION", "LIFECYCLE")})
    assert any("REJECTED_IS_TERMINAL" in v["message"] for v in report["violations"])


def test_promoted_requires_promotable() -> None:
    state = valid_state()
    state["lifecycle"]["cand-1"]["transitions"] = state["lifecycle"]["cand-1"]["transitions"][:-1]
    report = assert_violations(state, {("INVALID_TRANSITION", "LIFECYCLE")})
    assert any("PROMOTED_WITHOUT_PROMOTABLE" in v["message"] for v in report["violations"])


def test_promotable_requires_policy_and_provenance() -> None:
    state = valid_state()
    state["decisions"] = []
    state["lifecycle"]["cand-1"] = {
        "status": "PROMOTABLE",
        "transitions": [
            {"from": "DRAFT", "to": "EVALUATING"},
            {"from": "EVALUATING", "to": "EVALUATED"},
            {"from": "EVALUATED", "to": "REGRESSION_CHECKED"},
            {"from": "REGRESSION_CHECKED", "to": "PROMOTION_REVIEW"},
            {"from": "PROMOTION_REVIEW", "to": "PROMOTABLE"},
        ],
    }
    without_policy = copy.deepcopy(state)
    del without_policy["policies"]["pol-1"]
    report = assert_violations(without_policy, {("GOVERNANCE_BLOCK", "G1-G4")})
    assert any("PROMOTABLE_WITHOUT_GOVERNANCE" in v["message"] for v in report["violations"])
    without_provenance = copy.deepcopy(state)
    without_provenance["provenance"]["cand-1"]["immutable_artifact_refs"] = []
    assert_violations(without_provenance, {("GOVERNANCE_BLOCK", "G1-G4")})


def test_core_does_not_require_confidence_score_or_judge_findings() -> None:
    assert not (
        {"confidence", "score", "judge_findings"}
        & set(CONTRACTS["Outcome"]["required_invariants"])
    )
    assert_ok(valid_state())


def test_core_requiring_extension_field_is_rejected() -> None:
    tampered = copy.deepcopy(CONTRACTS)
    tampered["Outcome"]["required_invariants"].append("confidence")
    violations = validate_extension_isolation(valid_state(), contracts=tampered)
    assert any("CORE_REQUIRES_EXTENSION_FIELD" in v.message for v in violations)


def test_judge_consumer_extension_stays_local() -> None:
    state = valid_state()
    state["extensions"] = {
        "llm_judge": {
            "applicability": "Outcome",
            "provenance_ref": "pol-1",
            "fields": {"confidence": "HIGH", "judge_findings": ["finding-1"]},
        }
    }
    report = assert_ok(state)
    assert report["verdict"] == "CONTRACT_VALID_WITH_EXTENSIONS"


def test_planner_consumer_without_judge_fields_passes() -> None:
    state = valid_state()
    state["extensions"] = {
        "swe_planner": {
            "applicability": "Outcome",
            "provenance_ref": "pol-1",
            "fields": {"score": 0.8, "plan_metrics": {"steps": 3}},
        }
    }
    assert_ok(state)


def test_extension_requires_applicability_and_provenance() -> None:
    state = valid_state()
    state["extensions"] = {"llm_judge": {"fields": {"confidence": "HIGH"}}}
    report = assert_violations(state, {("EXTENSION_SCHEMA_ERROR", "EXT")})
    assert any("EXTENSION_MISSING_APPLICABILITY" in v["message"] for v in report["violations"])
    assert any("EXTENSION_MISSING_PROVENANCE" in v["message"] for v in report["violations"])
    assert report["verdict"] == "CONTRACT_PARTIAL"


def test_promote_requires_all_prerequisites() -> None:
    base = valid_state()
    assert validate(base)["pass"]
    mutators = [
        lambda s: s["policies"]["pol-1"].update(registered=False),
        lambda s: s["policies"]["pol-1"].update(frozen=False),
        lambda s: s["runs"][0].update(policy_version="2"),
        lambda s: s["provenance"]["cand-1"].update(policy=False),
        lambda s: s["decisions"][0].update(gate_result="HOLD"),
    ]
    expected = [
        ("GOVERNANCE_BLOCK", "G1"),
        ("GOVERNANCE_BLOCK", "G2"),
        ("GOVERNANCE_BLOCK", "G3"),
        ("PROVENANCE_INCOMPLETE", "G4"),
        ("CONTRACT_VIOLATION", "GATE"),
    ]
    for mutate, exp in zip(mutators, expected):
        state = copy.deepcopy(base)
        mutate(state)
        assert_violations(state, {exp})


def test_verdicts() -> None:
    assert validate(valid_state())["verdict"] == "CONTRACT_VALID"
    with_ext = valid_state()
    with_ext["extensions"] = {
        "llm_judge": {"applicability": "Outcome", "provenance_ref": "pol-1", "fields": {}}
    }
    assert validate(with_ext)["verdict"] == "CONTRACT_VALID_WITH_EXTENSIONS"
    bad = valid_state()
    bad["evidence"][0]["current_hash"] = "x"
    assert validate(bad)["verdict"] == "CONTRACT_INVALID"
    ext_bad = valid_state()
    ext_bad["extensions"] = {"llm_judge": {}}
    assert validate(ext_bad)["verdict"] == "CONTRACT_PARTIAL"
