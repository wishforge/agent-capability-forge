"""Phase 8 real-path registry enforcement tests (offline, temp dirs only)."""

from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from pilot.adoption_authority import authority_id_for, dir_digest  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"


@pytest.fixture
def candidate(tmp_path) -> pathlib.Path:
    cand = tmp_path / "candidate"
    (cand / "implementation" / "artifact").mkdir(parents=True)
    (cand / "implementation" / "artifact" / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(
        json.dumps({"capability": {"name": NAME, "version": 1}})
    )
    return cand


@pytest.fixture
def store(candidate: pathlib.Path) -> dict:
    digest = dir_digest(candidate / "implementation" / "artifact")
    return {
        "policies": {
            "pol-1": {"version": "1", "registered": True, "frozen": True, "content_hash": "p1"}
        },
        "candidates": {
            "cand-1": {
                "version": "v1",
                "created_at": "2026-08-17T00:00:00Z",
                "forged_artifact_digest": digest,
            }
        },
        "runs": [
            {
                "run_id": "run-1",
                "candidate_id": "cand-1",
                "candidate_version": "v1",
                "artifact_digest": digest,
                "policy_ref": "pol-1",
                "policy_version": "1",
                "status": "EVALUATED",
                "created_at": "2026-08-17T00:30:00Z",
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "run_id": "run-1",
                "recorded_hash": "e1",
                "current_hash": "e1",
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
                "artifact_digest": digest,
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
                "transitions": [{"from": "PROMOTABLE", "to": "PROMOTED"}],
            }
        },
        "revocations": [],
    }


@pytest.fixture
def authority(candidate: pathlib.Path) -> dict:
    return {
        "authority_id": authority_id_for("cand-1", "v1", "dec-1"),
        "candidate_id": "cand-1",
        "candidate_version": "v1",
        "promotion_decision_id": "dec-1",
        "evaluation_run_id": "run-1",
        "policy_version": "1",
        "artifact_digest": dir_digest(candidate / "implementation" / "artifact"),
        "provenance": {
            "policy": True,
            "evidence_manifest": True,
            "run_ids": ["run-1"],
            "immutable_artifact_refs": ["art-1"],
        },
        "issued_at": "2026-08-17T01:00:00Z",
    }


@pytest.fixture
def registry_root(tmp_path, store: dict) -> pathlib.Path:
    root = tmp_path / "registry"
    root.mkdir()
    (root / "adoption_store.json").write_text(json.dumps(store, indent=2))
    return root


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def assert_blocked(
    candidate: pathlib.Path,
    registry_root: pathlib.Path,
    authority: dict,
    expected_code: str,
    **overrides,
) -> None:
    auth = copy.deepcopy(authority)
    auth.update(overrides)
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                adoption_authority=auth)
    assert expected_code in blocked_codes(ei.value)
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()
    assert not (registry_root / FAMILY / NAME / "artifact").exists()


def write_store(registry_root: pathlib.Path, store: dict, **decision_overrides) -> dict:
    s = copy.deepcopy(store)
    s["decisions"][0].update(decision_overrides)
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    return s


def test_valid_authority_promotes(candidate, registry_root, authority) -> None:
    entry = promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                    adoption_authority=authority)
    assert entry["state"] == "promoted"
    adopted = entry["adoption"]
    assert adopted["candidate_id"] == "cand-1"
    assert adopted["candidate_version"] == "v1"
    assert adopted["promotion_decision_id"] == "dec-1"
    assert adopted["evaluation_run_id"] == "run-1"
    assert adopted["policy_version"] == "1"
    assert adopted["artifact_digest"] == authority["artifact_digest"]
    assert adopted["provenance"]["run_ids"] == ["run-1"]
    assert adopted["adopted_at"]
    assert (registry_root / FAMILY / NAME / "artifact" / "main.py").exists()


def test_missing_decision_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "MISSING_DECISION",
                   promotion_decision_id="dec-missing")


def test_wrong_candidate_id_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "CANDIDATE_ID_MISMATCH",
                   candidate_id="cand-2")


def test_wrong_candidate_version_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "CANDIDATE_VERSION_MISMATCH",
                   candidate_version="v2")


def test_missing_run_blocks(candidate, registry_root, store, authority) -> None:
    write_store(registry_root, store, run_id="run-missing")
    assert_blocked(candidate, registry_root, authority, "RUN_MISSING")


def test_run_mismatch_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "RUN_MISMATCH",
                   evaluation_run_id="run-other")


def test_wrong_policy_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "POLICY_VERSION_MISMATCH",
                   policy_version="2")


def test_unfrozen_policy_blocks(candidate, registry_root, store, authority) -> None:
    s = copy.deepcopy(store)
    s["policies"]["pol-1"]["frozen"] = False
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    assert_blocked(candidate, registry_root, authority, "POLICY_NOT_FROZEN")


def test_artifact_digest_mismatch_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "ARTIFACT_DIGEST_MISMATCH",
                   artifact_digest="sha256:bad")


def test_tampered_artifact_blocks(candidate, registry_root, authority) -> None:
    (candidate / "implementation" / "artifact" / "main.py").write_text(
        "print('tampered')\n"
    )
    assert_blocked(candidate, registry_root, authority, "ARTIFACT_DIGEST_MISMATCH")


def test_missing_provenance_blocks(candidate, registry_root, authority) -> None:
    assert_blocked(candidate, registry_root, authority, "REQUEST_METADATA_MISSING",
                   provenance=None)


def test_invalid_lifecycle_blocks(candidate, registry_root, store, authority) -> None:
    s = copy.deepcopy(store)
    s["lifecycle"]["cand-1"]["status"] = "DRAFT"
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    assert_blocked(candidate, registry_root, authority, "INVALID_LIFECYCLE")


def test_rejected_candidate_blocks(candidate, registry_root, store, authority) -> None:
    s = copy.deepcopy(store)
    s["lifecycle"]["cand-1"]["status"] = "REJECTED"
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    assert_blocked(candidate, registry_root, authority, "CANDIDATE_REJECTED")


def test_stale_decision_blocks(candidate, registry_root, store, authority) -> None:
    s = copy.deepcopy(store)
    s["decisions"].append(
        {
            "decision_id": "dec-2",
            "candidate_id": "cand-1",
            "candidate_version": "v1",
            "run_id": "run-1",
            "policy_ref": "pol-1",
            "policy_version": "1",
            "artifact_digest": s["decisions"][0]["artifact_digest"],
            "value": "PROMOTE",
            "gate_result": "PASS",
            "created_at": "2026-08-17T02:00:00Z",
            "recorded_hash": "d2",
            "current_hash": "d2",
        }
    )
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    assert_blocked(candidate, registry_root, authority, "STALE_DECISION")


def test_same_valid_adoption_twice_is_idempotent(
    candidate, registry_root, authority
) -> None:
    first = promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                    adoption_authority=authority)
    entry_path = registry_root / FAMILY / f"{NAME}.json"
    before = entry_path.read_text()
    second = promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                     adoption_authority=authority)
    assert second == first
    assert second["state"] == "promoted"
    assert entry_path.read_text() == before


def test_existing_entry_different_binding_blocked(
    candidate, registry_root, store, authority
) -> None:
    promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
            adoption_authority=authority)
    second_decision = copy.deepcopy(store["decisions"][0])
    second_decision.update(
        decision_id="dec-2",
        created_at="2026-08-17T02:00:00Z",
        recorded_hash="d2",
        current_hash="d2",
    )
    s = copy.deepcopy(store)
    s["decisions"].append(second_decision)
    (registry_root / "adoption_store.json").write_text(json.dumps(s, indent=2))
    other = copy.deepcopy(authority)
    other.update(
        promotion_decision_id="dec-2",
        issued_at="2026-08-17T02:00:00Z",
        authority_id=authority_id_for("cand-1", "v1", "dec-2"),
    )
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                adoption_authority=other)
    assert "ENTRY_BINDING_CONFLICT" in blocked_codes(ei.value)
    entry = json.loads((registry_root / FAMILY / f"{NAME}.json").read_text())
    assert entry["state"] == "promoted"
    assert entry["adoption"]["promotion_decision_id"] == "dec-1"


def test_direct_old_promote_without_authority_blocks(
    candidate, registry_root
) -> None:
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root)
    assert "MISSING_AUTHORITY" in blocked_codes(ei.value)
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()


def test_missing_adoption_store_blocks(candidate, registry_root, authority) -> None:
    (registry_root / "adoption_store.json").unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, {"verdict": "PASS"}, registry_root,
                adoption_authority=authority)
    assert "MISSING_ADOPTION_STORE" in blocked_codes(ei.value)
    assert not (registry_root / FAMILY / f"{NAME}.json").exists()
