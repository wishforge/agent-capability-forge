"""Phase 8.1 AdoptionAuthority producer tests (offline, temp dirs only)."""

from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from pilot.adoption_authority import authority_id_for, dir_digest, load_store  # noqa: E402
from pilot.adoption_authority_producer import DEFAULT_POLICY, DEFAULT_POLICY_REF, issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"
CAND_ID = "cand-1"
VER = "v1"
RUN_ID = "run-1"
DEC_ID = "dec-1"
CREATED_AT = "2026-08-17T01:00:00Z"


@pytest.fixture
def candidate(tmp_path) -> pathlib.Path:
    cand = tmp_path / "candidate"
    (cand / "implementation" / "artifact").mkdir(parents=True)
    (cand / "implementation" / "artifact" / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(json.dumps({
        "capability": {"name": NAME, "version": 1},
        "provenance": {"forge_timestamp": "2026-08-17T00:00:00Z"},
    }))
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": CAND_ID, "name": NAME, "state": "candidate"}))
    return cand


@pytest.fixture
def evaluation() -> dict:
    return {
        "evaluation_id": RUN_ID,
        "candidate_id": CAND_ID,
        "verdict": "PASS",
        "regression": "PASS",
        "novel_input_test": "PASS",
        "independent_reuse": "PASS",
        "evaluated_at": CREATED_AT,
    }


@pytest.fixture
def confirm() -> dict:
    return {"operator": "test", "confirm": True}


@pytest.fixture
def registry_root(tmp_path) -> pathlib.Path:
    root = tmp_path / "registry"
    root.mkdir()
    return root


def base_decision(candidate: pathlib.Path, **overrides) -> dict:
    decision = {
        "decision_id": DEC_ID,
        "candidate_id": CAND_ID,
        "candidate_version": VER,
        "run_id": RUN_ID,
        "policy_ref": DEFAULT_POLICY_REF,
        "policy_version": "1",
        "artifact_digest": dir_digest(candidate / "implementation" / "artifact"),
        "value": "PROMOTE",
        "gate_result": "PASS",
        "created_at": CREATED_AT,
    }
    decision.update(overrides)
    return decision


def store_snapshot(registry_root: pathlib.Path) -> bytes | None:
    path = registry_root / "adoption_store.json"
    return path.read_bytes() if path.exists() else None


def write_store(registry_root: pathlib.Path, store: dict) -> None:
    (registry_root / "adoption_store.json").write_text(json.dumps(store, indent=2))


def assert_blocked(result: dict, expected_code: str) -> None:
    assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
    codes = {v["code"] for v in result["violations"]}
    assert expected_code in codes, codes


def test_confirm_required_blocks(registry_root, candidate, evaluation) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(registry_root, candidate, evaluation, confirm=None)
    assert_blocked(result, "HUMAN_CONFIRM_MISSING")
    assert store_snapshot(registry_root) == before


def test_promote_issues_authority(registry_root, candidate, evaluation, confirm) -> None:
    result = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    assert result["verdict"] == "AUTHORITY_ISSUED"
    authority = result["authority"]
    assert authority["authority_id"] == authority_id_for(
        CAND_ID, VER, authority["promotion_decision_id"])
    assert authority["candidate_id"] == CAND_ID
    assert authority["candidate_version"] == VER
    assert authority["evaluation_run_id"] == RUN_ID
    assert authority["policy_version"] == "1"
    assert authority["artifact_digest"].startswith("sha256:")
    assert authority["provenance"]["run_ids"] == [RUN_ID]
    assert authority["issued_at"] == CREATED_AT
    assert authority["status"] == "ISSUED"

    store = load_store(registry_root)
    assert store["decisions"][0]["value"] == "PROMOTE"
    assert store["runs"][0]["run_id"] == RUN_ID
    assert store["policies"][DEFAULT_POLICY_REF]["frozen"] is True
    assert store["candidates"][CAND_ID]["version"] == VER
    assert store["lifecycle"][CAND_ID]["status"] == "PROMOTABLE"
    assert store["provenance"][CAND_ID]["run_ids"] == [RUN_ID]
    assert store["evidence"][0]["run_id"] == RUN_ID
    assert store["authorities"][0] == authority


@pytest.mark.parametrize("value", ["HOLD", "REJECT"])
def test_non_promote_decision_blocked(
    registry_root, candidate, evaluation, confirm, value
) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, value=value))
    assert_blocked(result, "DECISION_NOT_PROMOTE")
    assert store_snapshot(registry_root) == before


def test_evaluation_fail_defaults_blocked(registry_root, candidate, confirm) -> None:
    ev = {"evaluation_id": RUN_ID, "candidate_id": CAND_ID, "verdict": "FAIL"}
    result = issue_authority(registry_root, candidate, ev, confirm=confirm)
    assert_blocked(result, "EVALUATION_NOT_PASS")


def test_missing_policy_blocked(registry_root, candidate, evaluation, confirm) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, policy_ref="pol-missing"))
    assert_blocked(result, "POLICY_NOT_REGISTERED")
    assert store_snapshot(registry_root) == before


def test_unfrozen_policy_blocked(registry_root, candidate, evaluation, confirm) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        policy={**DEFAULT_POLICY, "frozen": False})
    assert_blocked(result, "POLICY_NOT_FROZEN")
    assert store_snapshot(registry_root) == before


def test_missing_run_blocked(registry_root, candidate, evaluation, confirm) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, run_id="run-missing"))
    assert_blocked(result, "RUN_MISSING")
    assert store_snapshot(registry_root) == before


def test_missing_provenance_blocked(registry_root, candidate, evaluation, confirm) -> None:
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm, provenance={})
    assert_blocked(result, "PROVENANCE_INCOMPLETE")
    assert store_snapshot(registry_root) == before


def test_missing_artifact_digest_blocked(registry_root, candidate, evaluation, confirm) -> None:
    import shutil
    shutil.rmtree(candidate / "implementation" / "artifact")
    before = store_snapshot(registry_root)
    result = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    assert_blocked(result, "ARTIFACT_DIGEST_MISMATCH")
    assert store_snapshot(registry_root) == before


def test_candidate_id_mismatch_blocked(registry_root, candidate, evaluation, confirm) -> None:
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, candidate_id="cand-2"))
    assert_blocked(result, "CANDIDATE_ID_MISMATCH")


def test_candidate_version_mismatch_blocked(
    registry_root, candidate, evaluation, confirm
) -> None:
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, candidate_version="v2"))
    assert_blocked(result, "CANDIDATE_VERSION_MISMATCH")


def test_policy_version_mismatch_blocked(registry_root, candidate, evaluation, confirm) -> None:
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, policy_version="2"))
    assert_blocked(result, "RUN_POLICY_MISMATCH")


def test_run_mismatch_blocked_by_registry(
    registry_root, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    forged = copy.deepcopy(issued["authority"])
    forged["evaluation_run_id"] = "run-other"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, registry_root,
                adoption_authority=forged)
    codes = {v["code"] for v in ei.value.violations}
    assert "RUN_MISMATCH" in codes
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()


def test_artifact_digest_mismatch_blocked(registry_root, candidate, evaluation, confirm) -> None:
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, artifact_digest="sha256:bad"))
    assert_blocked(result, "ARTIFACT_DIGEST_MISMATCH")


def test_forged_authority_id_blocked_by_registry(
    registry_root, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    forged = copy.deepcopy(issued["authority"])
    forged["authority_id"] = "auth-forged"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, registry_root,
                adoption_authority=forged)
    codes = {v["code"] for v in ei.value.violations}
    assert "AUTHORITY_ID_MISMATCH" in codes
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()


def test_same_decision_twice_is_idempotent(
    registry_root, candidate, evaluation, confirm
) -> None:
    first = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    second = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    assert first["authority"] == second["authority"]
    store = load_store(registry_root)
    assert len(store["authorities"]) == 1
    assert len(store["decisions"]) == 1


def test_existing_conflicting_decision_blocked(
    registry_root, candidate, evaluation, confirm
) -> None:
    issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    decision_id = load_store(registry_root)["decisions"][0]["decision_id"]
    before = store_snapshot(registry_root)
    result = issue_authority(
        registry_root, candidate, evaluation, confirm=confirm,
        decision=base_decision(candidate, decision_id=decision_id, value="HOLD"))
    assert_blocked(result, "AUTHORITY_BINDING_MISMATCH")
    assert store_snapshot(registry_root) == before


@pytest.mark.parametrize("status", ["REVOKED", "SUPERSEDED"])
def test_revoked_or_superseded_blocks(
    registry_root, candidate, evaluation, confirm, status
) -> None:
    issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    store = load_store(registry_root)
    decision_id = store["decisions"][0]["decision_id"]
    store["revocations"].append({
        "revocation_id": "rev-1",
        "candidate_id": CAND_ID,
        "candidate_version": VER,
        "decision_id": decision_id,
        "status": status,
        "reason": "test",
    })
    write_store(registry_root, store)
    before = store_snapshot(registry_root)
    result = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    assert_blocked(result, "REVOKED_DECISION")
    assert store_snapshot(registry_root) == before


def test_stale_decision_blocks(registry_root, candidate, evaluation, confirm) -> None:
    issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    store = load_store(registry_root)
    later = copy.deepcopy(store["decisions"][0])
    later.update(
        decision_id="dec-2",
        created_at="2026-08-17T02:00:00Z",
        recorded_hash="d2",
        current_hash="d2",
    )
    store["decisions"].append(later)
    write_store(registry_root, store)
    before = store_snapshot(registry_root)
    result = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    assert_blocked(result, "STALE_DECISION")
    assert store_snapshot(registry_root) == before


def test_issue_then_registry_promotes(
    registry_root, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    entry = promote(FAMILY, NAME, candidate, evaluation, registry_root,
                    adoption_authority=issued["authority"])
    assert entry["state"] == "promoted"
    assert entry["adoption"]["promotion_decision_id"] == issued["authority"]["promotion_decision_id"]
    assert (registry_root / FAMILY / NAME / "artifact" / "main.py").exists()


def test_registry_rejects_tampered_authority(
    registry_root, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(registry_root, candidate, evaluation, confirm=confirm)
    bad = copy.deepcopy(issued["authority"])
    bad["artifact_digest"] = "sha256:bad"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, registry_root,
                adoption_authority=bad)
    codes = {v["code"] for v in ei.value.violations}
    assert "ARTIFACT_DIGEST_MISMATCH" in codes
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()


def test_legacy_promote_without_authority_blocked(
    registry_root, candidate, evaluation
) -> None:
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, registry_root)
    assert "MISSING_AUTHORITY" in {v["code"] for v in ei.value.violations}
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()
