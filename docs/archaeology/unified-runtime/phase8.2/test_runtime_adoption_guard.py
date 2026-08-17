"""Phase 8.2 real runtime-path adoption guard tests (offline, temp dirs only)."""

from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from pilot.adoption_authority import authority_id_for, dir_digest  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"
CAND_ID = "cand-1"
VER = "v1"
RUN_ID = "run-1"
DEC_ID = "dec-1"
CREATED_AT = "2026-08-17T01:00:00Z"


def make_authority(artifact_dir: Path, **overrides) -> dict:
    digest = dir_digest(artifact_dir)
    authority = {
        "authority_id": authority_id_for(CAND_ID, VER, DEC_ID),
        "candidate_id": CAND_ID,
        "candidate_version": VER,
        "promotion_decision_id": DEC_ID,
        "evaluation_run_id": RUN_ID,
        "policy_version": "1",
        "artifact_digest": digest,
        "provenance": {
            "policy": True,
            "evidence_manifest": True,
            "run_ids": [RUN_ID],
            "immutable_artifact_refs": [f"artifact:{digest}"],
        },
        "issued_at": CREATED_AT,
        "status": "ISSUED",
    }
    authority.update(overrides)
    return authority


def make_store(authority: dict) -> dict:
    digest = authority["artifact_digest"]
    return {
        "policies": {
            "pol-1": {"version": "1", "registered": True, "frozen": True, "content_hash": "p1"}
        },
        "candidates": {
            CAND_ID: {
                "version": VER,
                "created_at": "2026-08-17T00:00:00Z",
                "forged_artifact_digest": digest,
            }
        },
        "runs": [
            {
                "run_id": RUN_ID,
                "candidate_id": CAND_ID,
                "candidate_version": VER,
                "artifact_digest": digest,
                "policy_ref": "pol-1",
                "policy_version": "1",
                "status": "EVALUATED",
                "created_at": CREATED_AT,
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "run_id": RUN_ID,
                "recorded_hash": "e1",
                "current_hash": "e1",
            }
        ],
        "provenance": {
            CAND_ID: {
                "policy": True,
                "evidence_manifest": True,
                "run_ids": [RUN_ID],
                "immutable_artifact_refs": [f"artifact:{digest}"],
            }
        },
        "decisions": [
            {
                "decision_id": DEC_ID,
                "candidate_id": CAND_ID,
                "candidate_version": VER,
                "run_id": RUN_ID,
                "policy_ref": "pol-1",
                "policy_version": "1",
                "artifact_digest": digest,
                "value": "PROMOTE",
                "gate_result": "PASS",
                "created_at": CREATED_AT,
                "recorded_hash": "d1",
                "current_hash": "d1",
            }
        ],
        "lifecycle": {
            CAND_ID: {
                "status": "PROMOTED",
                "transitions": [{"from": "PROMOTABLE", "to": "PROMOTED"}],
            }
        },
        "revocations": [],
        "authorities": [authority],
    }


def make_entry(authority: dict, artifact_dir: Path) -> dict:
    return {
        "schema_version": "experimental_registry_v1",
        "capability_id": "cap-" + NAME,
        "name": NAME,
        "version": 1,
        "family": FAMILY,
        "artifact_dir": str(artifact_dir),
        "manifest": {"capability": {"name": NAME, "version": 1}},
        "evaluation": {"verdict": "PASS"},
        "state": "promoted",
        "promoted_at": CREATED_AT,
        "adoption": {
            "candidate_id": authority["candidate_id"],
            "candidate_version": authority["candidate_version"],
            "promotion_decision_id": authority["promotion_decision_id"],
            "evaluation_run_id": authority["evaluation_run_id"],
            "policy_version": authority["policy_version"],
            "artifact_digest": authority["artifact_digest"],
            "provenance": authority["provenance"],
            "adopted_at": CREATED_AT,
        },
    }


def build_env(tmp_path, *, mutate_store=None, mutate_entry=None, tamper=False) -> dict:
    root = tmp_path / "registry"
    artifact_dir = root / FAMILY / NAME / "artifact"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "main.py").write_text("print('hi')\n")
    authority = make_authority(artifact_dir)
    store = make_store(authority)
    entry = make_entry(authority, artifact_dir)
    if mutate_store is not None:
        mutate_store(store)
    if mutate_entry is not None:
        mutate_entry(entry)
    (root / "adoption_store.json").write_text(json.dumps(store, indent=2))
    entry_path = root / FAMILY / f"{NAME}.json"
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(json.dumps(entry, indent=2))
    if tamper:
        (artifact_dir / "main.py").write_text("print('tampered')\n")
    return {"root": root, "artifact_dir": artifact_dir, "authority": authority,
            "store": store, "entry": entry}


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def assert_blocked(env: dict, expected_code: str) -> None:
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert expected_code in blocked_codes(ei.value)


def make_harness(tmp_path, env: dict, monkeypatch) -> harness_mod.Harness:
    h = harness_mod.Harness(force=True)
    h.state = tmp_path / "state"
    h.state.mkdir(parents=True, exist_ok=True)
    h.bundle_store = h.state / "bundle_store"
    h.records_path = h.state / "run_records.jsonl"
    h.events_path = h.state / "cost_events.jsonl"
    h.registry_root = env["root"]
    h.family = dict(h.family, future_tasks=[h.family["future_tasks"][0]])
    h._check_docker = lambda: None
    h._make_codex_home = lambda run_dir, skills=None: run_dir / "codex_home"
    h._oracle = lambda task, out: {"verdict": "PASS", "reason": "ok", "stable": True, "runs": []}
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: {
        "sandbox_id": "cbx-test", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    return h


def test_valid_authority_allows(tmp_path) -> None:
    env = build_env(tmp_path)
    report = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert report["verdict"] == "ALLOW"
    assert report["artifact_digest"] == env["authority"]["artifact_digest"]


def test_missing_authority_blocks(tmp_path) -> None:
    env = build_env(tmp_path, mutate_store=lambda s: s.pop("authorities"))
    assert_blocked(env, "MISSING_AUTHORITY")


def test_wrong_candidate_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(candidate_id="cand-2"))
    assert_blocked(env, "CANDIDATE_ID_MISMATCH")


def test_wrong_version_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(candidate_version="v2"))
    assert_blocked(env, "CANDIDATE_VERSION_MISMATCH")


def test_wrong_policy_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(policy_version="2"))
    assert_blocked(env, "POLICY_VERSION_MISMATCH")


def test_missing_run_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["decisions"][0].update(run_id="run-missing"))
    assert_blocked(env, "RUN_MISSING")


def test_run_mismatch_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(evaluation_run_id="run-other"))
    assert_blocked(env, "RUN_MISMATCH")


def test_artifact_digest_mismatch_blocks(tmp_path) -> None:
    env = build_env(tmp_path, tamper=True)
    assert_blocked(env, "ARTIFACT_DIGEST_MISMATCH")


def test_missing_provenance_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(provenance={}))
    assert_blocked(env, "PROVENANCE_INCOMPLETE")


def test_policy_not_frozen_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["policies"]["pol-1"].update(frozen=False))
    assert_blocked(env, "POLICY_NOT_FROZEN")


@pytest.mark.parametrize("status", [
    "DRAFT", "EVALUATING", "EVALUATED", "REGRESSION_CHECKED",
    "PROMOTION_REVIEW", "PROMOTABLE", "HOLD"])
def test_lifecycle_not_promoted_blocks(tmp_path, status) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s, st=status: s["lifecycle"][CAND_ID].update(status=st))
    assert_blocked(env, "INVALID_LIFECYCLE")


def test_rejected_lifecycle_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["lifecycle"][CAND_ID].update(status="REJECTED"))
    assert_blocked(env, "CANDIDATE_REJECTED")


@pytest.mark.parametrize("status", ["REVOKED", "SUPERSEDED"])
def test_revoked_or_superseded_blocks(tmp_path, status) -> None:
    def mutate(s, st=status) -> None:
        s["revocations"].append({
            "revocation_id": "rev-1", "candidate_id": CAND_ID,
            "candidate_version": VER, "decision_id": DEC_ID, "status": st, "reason": "test"})
    env = build_env(tmp_path, mutate_store=mutate)
    assert_blocked(env, "REVOKED_DECISION")


def test_authority_status_revoked_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(status="REVOKED"))
    assert_blocked(env, "REVOKED_DECISION")


def test_stale_authority_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["candidates"][CAND_ID].update(
            created_at="2026-08-17T02:00:00Z"))
    assert_blocked(env, "STALE_DECISION")


def test_later_decision_makes_authority_stale(tmp_path) -> None:
    def mutate(s) -> None:
        later = copy.deepcopy(s["decisions"][0])
        later.update(decision_id="dec-2", created_at="2026-08-17T02:00:00Z",
                     recorded_hash="d2", current_hash="d2")
        s["decisions"].append(later)
    env = build_env(tmp_path, mutate_store=mutate)
    assert_blocked(env, "STALE_DECISION")


@pytest.mark.parametrize("value", ["HOLD", "REJECTED", "REJECT", "CANARY", "PENDING", "PROMOTED"])
def test_decision_not_promote_blocks(tmp_path, value) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s, v=value: s["decisions"][0].update(value=v))
    assert_blocked(env, "DECISION_NOT_PROMOTE")


def test_tampered_authority_id_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["authorities"][0].update(authority_id="auth-forged"))
    assert_blocked(env, "AUTHORITY_ID_MISMATCH")


def test_tampered_decision_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["decisions"][0].update(current_hash="tampered"))
    assert_blocked(env, "DECISION_TAMPERED")


def test_tampered_evidence_blocks(tmp_path) -> None:
    env = build_env(
        tmp_path,
        mutate_store=lambda s: s["evidence"][0].update(current_hash="tampered"))
    assert_blocked(env, "EVIDENCE_TAMPERED")


def test_registry_promoted_but_authority_missing_blocks(tmp_path) -> None:
    env = build_env(tmp_path, mutate_store=lambda s: s.__setitem__("authorities", []))
    assert_blocked(env, "MISSING_AUTHORITY")


def test_missing_store_blocks(tmp_path) -> None:
    env = build_env(tmp_path)
    (env["root"] / "adoption_store.json").unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "MISSING_ADOPTION_STORE" in blocked_codes(ei.value)


def test_missing_runtime_artifact_blocks(tmp_path) -> None:
    env = build_env(tmp_path)
    shutil.rmtree(env["artifact_dir"])
    assert_blocked(env, "ARTIFACT_DIGEST_MISMATCH")


def test_repeat_valid_activation_is_idempotent(tmp_path) -> None:
    env = build_env(tmp_path)
    first = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    store_before = (env["root"] / "adoption_store.json").read_bytes()
    second = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert second == first
    assert (env["root"] / "adoption_store.json").read_bytes() == store_before


def test_blocked_request_does_not_activate(tmp_path, monkeypatch) -> None:
    env = build_env(tmp_path, tamper=True)
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append((a, k)) or {})
    (h.state / "b3_entry.json").write_text(
        json.dumps({"name": NAME, "capability_id": "cap-1"}))
    with pytest.raises(AdoptionBlocked):
        h.phase_future("b3")
    assert calls == []


def test_blocked_request_does_not_execute(tmp_path, monkeypatch) -> None:
    env = build_env(tmp_path)
    env["store"]["authorities"] = []
    (env["root"] / "adoption_store.json").write_text(json.dumps(env["store"], indent=2))
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append((a, k)) or {})
    (h.state / "b3_entry.json").write_text(
        json.dumps({"name": NAME, "capability_id": "cap-1"}))
    with pytest.raises(AdoptionBlocked):
        h.phase_future("b3")
    assert calls == []
    assert not h.records_path.exists()


def test_valid_request_activates_exactly_once(tmp_path, monkeypatch) -> None:
    env = build_env(tmp_path)
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append((a, k)) or {
        "sandbox_id": "cbx-test", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    (h.state / "b3_entry.json").write_text(
        json.dumps({"name": NAME, "capability_id": "cap-1"}))
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    args, _kwargs = calls[0]
    assert args[0] == h.cfg["sandbox"]["image"]
    assert any(
        str(env["artifact_dir"]) == str(m[0]) and m[2] is True for m in args[1])
    assert args[2] == ["python", "/artifact/main.py", "/input/data.csv", "/output"]
    records = rr.load_records(h.records_path)
    assert len(records) == 1
    assert records[0]["capability_used"] == "cap-" + NAME


def test_producer_promote_mark_then_runtime_allows(tmp_path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    cand = tmp_path / "candidate"
    (cand / "implementation" / "artifact").mkdir(parents=True)
    (cand / "implementation" / "artifact" / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(json.dumps({
        "capability": {"name": NAME, "version": 1},
        "provenance": {"forge_timestamp": "2026-08-17T00:00:00Z"}}))
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": CAND_ID, "name": NAME, "state": "candidate"}))
    confirm = {"operator": "test", "confirm": True}
    evaluation = {"evaluation_id": RUN_ID, "candidate_id": CAND_ID, "verdict": "PASS",
                  "evaluated_at": CREATED_AT}
    issued = issue_authority(root, cand, evaluation, confirm=confirm)
    assert issued["verdict"] == "AUTHORITY_ISSUED"
    entry = promote(FAMILY, NAME, cand, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    report = guard.adopt(root, entry, Path(entry["artifact_dir"]))
    assert report["verdict"] == "ALLOW"
    store_before = (root / "adoption_store.json").read_bytes()
    guard.mark_promoted(root, entry)
    assert (root / "adoption_store.json").read_bytes() == store_before
    assert guard.adopt(root, entry, Path(entry["artifact_dir"]))["verdict"] == "ALLOW"
