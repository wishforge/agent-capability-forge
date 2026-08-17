"""Phase 7.5 feasibility tests: static trace + minimal contract validation."""

from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "phase7.4"))

import pytest  # noqa: E402

import trace_adoption_path as tap  # noqa: E402
from validate_adoption_guard_design import validate  # noqa: E402


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


def blocked_codes(state: dict) -> set[str]:
    report = validate(state)
    return {
        v["message"].split()[0]
        for v in report["violations"]
        if v["code"] == "ADOPTION_BLOCKED"
    }


def test_trace_facts_all_ok() -> None:
    report = tap.build_report()
    assert report["verdict"] == "PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN", [
        f for f in report["facts"] if not f["ok"]
    ]
    assert all(f["ok"] for f in report["facts"])


def test_adoption_points_covered() -> None:
    ids = {p["id"] for p in tap.build_report()["adoption_points"]}
    assert {
        "pilot_registry_promote",
        "pilot_runtime_execute",
        "capability_manager_install",
        "tool_runtime_register",
        "langfuse_label_active",
    } <= ids


def test_bypass_inventory_covered() -> None:
    ids = {b["id"] for b in tap.build_report()["bypasses"]}
    assert {f"B{i}" for i in range(1, 9)} <= ids


def test_valid_adoption_allowed() -> None:
    report = validate(valid_state())
    assert report["pass"], report
    assert report["adoptions_allowed"] is True


def test_minimal_contract_blocks_required_codes() -> None:
    def set_decision(key: str, value):
        def mutate(state):
            state["decisions"][0][key] = value

        return mutate

    mutations = [
        ("MISSING_DECISION", lambda s: s["adoptions"][0].update(promotion_decision_id="dec-missing")),
        ("DECISION_NOT_PROMOTE", set_decision("value", "HOLD")),
        ("CANDIDATE_ID_MISMATCH", lambda s: s["adoptions"][0].update(candidate_id="cand-2")),
        ("CANDIDATE_VERSION_MISMATCH", lambda s: s["adoptions"][0].update(candidate_version="v2")),
        ("RUN_MISSING", set_decision("run_id", "run-missing")),
        ("RUN_MISMATCH", lambda s: s["adoptions"][0].update(evaluation_run_id="run-other")),
        ("POLICY_NOT_REGISTERED", set_decision("policy_ref", "pol-missing")),
        ("POLICY_NOT_FROZEN", lambda s: s["policies"]["pol-1"].update(frozen=False)),
        ("RUN_POLICY_MISMATCH", lambda s: s["runs"][0].update(policy_ref="pol-2", policy_version="2")),
        ("ARTIFACT_DIGEST_MISMATCH", lambda s: s["adoptions"][0].update(artifact_digest="a2")),
        (
            "PROVENANCE_INCOMPLETE",
            lambda s: (
                s["adoptions"][0].pop("provenance"),
                s["provenance"]["cand-1"].update(policy=False),
            ),
        ),
        ("INVALID_LIFECYCLE", lambda s: s["lifecycle"]["cand-1"].update(status="DRAFT")),
        ("CANDIDATE_REJECTED", lambda s: s["lifecycle"]["cand-1"].update(status="REJECTED")),
        (
            "STALE_DECISION",
            lambda s: s["decisions"].append(
                {
                    "decision_id": "dec-2",
                    "candidate_id": "cand-1",
                    "candidate_version": "v1",
                    "run_id": "run-1",
                    "policy_ref": "pol-1",
                    "policy_version": "1",
                    "artifact_digest": "a1",
                    "value": "PROMOTE",
                    "gate_result": "PASS",
                    "created_at": "2026-08-17T02:00:00Z",
                    "recorded_hash": "d2",
                    "current_hash": "d2",
                }
            ),
        ),
        ("MISSING_DECISION_TIMESTAMP", lambda s: s["decisions"][0].pop("created_at")),
    ]
    for code, mutate in mutations:
        state = valid_state()
        mutate(state)
        assert code in blocked_codes(state), code
        assert validate(state)["adoptions_allowed"] is False, code
