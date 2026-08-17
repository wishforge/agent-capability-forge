"""Phase 7.6 tests: inventory classification + unified authority fail-closed."""

from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

import inventory_adoption_paths as iap  # noqa: E402
from validate_adoption_authority import (  # noqa: E402
    combine,
    post_state,
    valid_authority,
    valid_state,
)


def blocked_codes(report: dict) -> set[str]:
    return {v["code"] for v in report["violations"]}


def test_inventory_every_path_classified() -> None:
    report = iap.build_report()
    assert report["verdict"] == "ADOPTION_PATH_INVENTORY_VALID"
    assert not report["problems"]
    assert all(
        entry["classification"] in iap.CLASSIFICATIONS for entry in report["inventory"]
    )


def test_inventory_adoption_paths_have_authority_requirement() -> None:
    report = iap.build_report()
    adoption = [e for e in report["inventory"] if e["classification"] == "ADOPTION"]
    assert adoption, "at least one real adoption path must exist"
    assert all(e["target_authority_requirement"] for e in adoption)


def test_inventory_facts_all_ok() -> None:
    assert all(f["ok"] for f in iap.build_report()["facts"])


def test_valid_authority_allowed_across_all_systems() -> None:
    report = combine(valid_authority(), valid_state(), post_state(valid_state()))
    assert report["allowed"] is True, report
    assert report["verdict"] == "ALLOW"
    assert report["system_verdicts"] == {
        "registry": "ALLOW",
        "runtime": "ALLOW",
        "external": "ALLOW",
    }


def test_candidate_binding_mismatch_blocked() -> None:
    authority = valid_authority()
    authority["candidate_id"] = "cand-2"
    report = combine(authority, valid_state(), post_state(valid_state()))
    assert report["allowed"] is False
    assert "CANDIDATE_ID_MISMATCH" in blocked_codes(report)


def test_version_mismatch_blocked() -> None:
    authority = valid_authority()
    authority["candidate_version"] = "v2"
    report = combine(authority, valid_state(), post_state(valid_state()))
    assert report["allowed"] is False
    assert "CANDIDATE_VERSION_MISMATCH" in blocked_codes(report)


def test_policy_mismatch_blocked() -> None:
    authority = valid_authority()
    authority["policy_version"] = "2"
    report = combine(authority, valid_state(), post_state(valid_state()))
    assert report["allowed"] is False
    assert "POLICY_VERSION_MISMATCH" in blocked_codes(report)


def test_artifact_mismatch_blocked() -> None:
    authority = valid_authority()
    authority["artifact_digest"] = "a2"
    report = combine(authority, valid_state(), post_state(valid_state()))
    assert report["allowed"] is False
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(report)


def test_missing_decision_blocked() -> None:
    authority = valid_authority()
    authority["promotion_decision_id"] = "dec-missing"
    report = combine(authority, valid_state(), post_state(valid_state()))
    assert report["allowed"] is False
    assert "MISSING_DECISION" in blocked_codes(report)


def test_registry_allow_runtime_block_blocked() -> None:
    report = combine(
        valid_authority(),
        valid_state(),
        post_state(valid_state()),
        system_verdicts={"registry": "ALLOW", "runtime": "BLOCK", "external": "ALLOW"},
    )
    assert report["allowed"] is False
    assert "SYSTEM_RUNTIME_BLOCKED" in blocked_codes(report)


def test_registry_block_runtime_allow_blocked() -> None:
    report = combine(
        valid_authority(),
        valid_state(),
        post_state(valid_state()),
        system_verdicts={"registry": "BLOCK", "runtime": "ALLOW", "external": "ALLOW"},
    )
    assert report["allowed"] is False
    assert "SYSTEM_REGISTRY_BLOCKED" in blocked_codes(report)


def test_external_allow_registry_block_blocked() -> None:
    report = combine(
        valid_authority(),
        valid_state(),
        post_state(valid_state()),
        system_verdicts={"registry": "BLOCK", "runtime": "ALLOW", "external": "ALLOW"},
    )
    assert report["allowed"] is False
    assert "SYSTEM_REGISTRY_BLOCKED" in blocked_codes(report)


def test_missing_system_verdict_fail_closed() -> None:
    report = combine(
        valid_authority(),
        valid_state(),
        post_state(valid_state()),
        system_verdicts={"registry": "ALLOW", "runtime": "ALLOW", "external": "UNKNOWN"},
    )
    assert report["allowed"] is False
    assert "SYSTEM_EXTERNAL_UNKNOWN" in blocked_codes(report)


@pytest.mark.parametrize("flag", ["use_latest", "use_previous", "use_active", "use_manual"])
def test_fallback_never_grants_allow(flag: str) -> None:
    report = combine(
        valid_authority(),
        valid_state(),
        post_state(valid_state()),
        **{flag: True},
    )
    assert report["allowed"] is False
    assert "FALLBACK_NOT_AUTHORITY" in blocked_codes(report)

    broken = valid_authority()
    broken["promotion_decision_id"] = "dec-missing"
    report = combine(
        broken,
        valid_state(),
        post_state(valid_state()),
        **{flag: True},
    )
    assert report["allowed"] is False
    assert "MISSING_DECISION" in blocked_codes(report)
