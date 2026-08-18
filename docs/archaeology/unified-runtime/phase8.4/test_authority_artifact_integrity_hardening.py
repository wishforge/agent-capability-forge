"""Phase 8.4 - real-code Authority & Artifact Integrity Hardening tests.

Covers the landed hardening (pilot/):
  - write-once immutable authority ledger (authorities/<id>.json, O_EXCL CAS)
  - append-only REVOKED / SUPERSEDED events (authorities/<id>.events.jsonl)
  - opt-in TrustedIssuer allowlist (PILOT_TRUSTED_ISSUERS)
  - registry rejects unissued authorities on hardened stores
  - runtime verify_at_mount() recheck immediately before docker_launch

Every illegal scenario -> ADOPTION_BLOCKED / AUTHORITY_ISSUANCE_BLOCKED.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from pilot.adoption_authority import (  # noqa: E402
    authority_events_path,
    authority_id_for,
    authority_record_path,
    load_authority_record,
    load_store,
    revoke_authority,
    write_authority_record,
)
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"
CAND_ID = "cand-1"
RUN_ID = "run-1"
CREATED_AT = "2026-08-18T01:00:00Z"


@pytest.fixture
def candidate(tmp_path) -> Path:
    cand = tmp_path / "candidate"
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(json.dumps({
        "capability": {"name": NAME, "version": 1},
        "provenance": {"forge_timestamp": "2026-08-18T00:00:00Z"}}))
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": CAND_ID, "name": NAME, "state": "candidate"}))
    return cand


@pytest.fixture
def evaluation() -> dict:
    return {"evaluation_id": RUN_ID, "candidate_id": CAND_ID,
            "verdict": "PASS", "evaluated_at": CREATED_AT}


@pytest.fixture
def confirm() -> dict:
    return {"operator": "test", "confirm": True}


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def issue_and_promote(tmp_path, candidate, evaluation, confirm, **kwargs) -> dict:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation,
                             confirm=confirm, **kwargs)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote(FAMILY, NAME, candidate, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    return {"root": root, "entry": entry,
            "authority": issued["authority"],
            "artifact_dir": Path(entry["artifact_dir"])}


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
    h._oracle = lambda task, out: {"verdict": "PASS", "reason": "ok",
                                   "stable": True, "runs": []}
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: {
        "sandbox_id": "cbx-test", "exit_code": 0, "stdout": "ok",
        "stderr": "", "elapsed_s": 0.1, "timed_out": False})
    return h


# --- Authority integrity ---------------------------------------------------

def test_immutable_ledger_record_written_and_idempotent(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    assert issued["verdict"] == "AUTHORITY_ISSUED"
    root = tmp_path / "registry"
    record = load_authority_record(root, issued["authority"]["authority_id"])
    assert record == issued["authority"]
    assert record["status"] == "ISSUED"
    assert record["issuer_id"] == "test"
    assert record["decision_id"] == record["promotion_decision_id"]
    again = issue_authority(root, candidate, evaluation, confirm=confirm)
    assert again["authority"] == issued["authority"]
    assert load_authority_record(root, issued["authority"]["authority_id"]) == record


def test_authority_overwrite_attempt_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    root = tmp_path / "registry"
    overwrite = copy.deepcopy(issued["authority"])
    overwrite["artifact_digest"] = "sha256:evil"
    assert write_authority_record(root, overwrite) == "AUTHORITY_BINDING_MISMATCH"
    assert load_authority_record(root, issued["authority"]["authority_id"]) \
        == issued["authority"]


def test_binding_mutation_blocked_by_registry(
    tmp_path, candidate, evaluation, confirm
) -> None:
    root = tmp_path / "registry"
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    forged = copy.deepcopy(issued["authority"])
    forged["candidate_id"] = "cand-2"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, root,
                adoption_authority=forged)
    assert "AUTHORITY_BINDING_MISMATCH" in blocked_codes(ei.value)
    assert not (root / FAMILY / f"{NAME}.json").exists()


def test_delete_and_recreate_with_different_binding_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    root = tmp_path / "registry"
    authority_record_path(root, issued["authority"]["authority_id"]).unlink()
    decision = copy.deepcopy(load_store(root)["decisions"][0])
    decision["artifact_digest"] = "sha256:evil"
    result = issue_authority(root, candidate, evaluation, confirm=confirm,
                             decision=decision)
    assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
    assert {v["code"] for v in result["violations"]} & {
        "AUTHORITY_BINDING_MISMATCH"}


def test_stale_version_write_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    root = tmp_path / "registry"
    stale = copy.deepcopy(issued["authority"])
    stale["candidate_version"] = "v2"
    assert write_authority_record(root, stale) == "AUTHORITY_BINDING_MISMATCH"


def test_concurrent_writer_same_authority_one_wins(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    root = tmp_path / "registry"
    other = copy.deepcopy(issued["authority"])
    other["artifact_digest"] = "sha256:other"
    assert write_authority_record(root, other) == "AUTHORITY_BINDING_MISMATCH"
    assert load_authority_record(root, issued["authority"]["authority_id"]) \
        == issued["authority"]


def test_deterministic_id_collision_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    issued = issue_authority(tmp_path / "registry", candidate, evaluation,
                             confirm=confirm)
    root = tmp_path / "registry"
    collision = copy.deepcopy(issued["authority"])
    collision["candidate_version"] = "v2"
    collision["authority_id"] = issued["authority"]["authority_id"]
    assert write_authority_record(root, collision) == "AUTHORITY_BINDING_MISMATCH"


# --- Issuer ----------------------------------------------------------------

def test_unknown_issuer_blocked(
    tmp_path, candidate, evaluation, confirm, monkeypatch
) -> None:
    monkeypatch.setenv("PILOT_TRUSTED_ISSUERS", "trusted-issuer")
    root = tmp_path / "registry"
    result = issue_authority(root, candidate, evaluation, confirm=confirm,
                             issuer_id="mallory")
    assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
    assert {v["code"] for v in result["violations"]} == {"UNTRUSTED_ISSUER"}
    assert not (root / "adoption_store.json").exists()
    assert not (root / "authorities").exists()
    trusted = issue_authority(root, candidate, evaluation, confirm=confirm,
                              issuer_id="trusted-issuer")
    assert trusted["verdict"] == "AUTHORITY_ISSUED"
    revoked = revoke_authority(root, trusted["authority"]["authority_id"],
                               status="REVOKED", issuer_id="mallory")
    assert revoked["verdict"] == "ADOPTION_BLOCKED"
    assert revoked["code"] == "UNTRUSTED_ISSUER"


def test_forged_authority_id_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    forged = copy.deepcopy(env["authority"])
    forged["authority_id"] = "auth-forged"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, env["root"],
                adoption_authority=forged)
    assert "AUTHORITY_ID_MISMATCH" in blocked_codes(ei.value)


def test_wrong_issuer_metadata_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    forged = copy.deepcopy(env["authority"])
    forged["decision_id"] = "dec-other"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, env["root"],
                adoption_authority=forged)
    assert "AUTHORITY_BINDING_MISMATCH" in blocked_codes(ei.value)


def test_unissued_authority_blocked_on_hardened_store(
    tmp_path, candidate, evaluation, confirm
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    forged = copy.deepcopy(issued["authority"])
    authority_record_path(root, issued["authority"]["authority_id"]).unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, root,
                adoption_authority=forged)
    assert "UNISSUED_AUTHORITY" in blocked_codes(ei.value)


# --- Artifact TOCTOU -------------------------------------------------------

def test_artifact_replaced_after_validation_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    first = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert first["verdict"] == "ALLOW"
    (env["artifact_dir"] / "main.py").write_text("print('evil')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"],
                              env["artifact_dir"], first["artifact_digest"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_digest_mismatch_blocks_adopt(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    (env["artifact_dir"] / "main.py").write_text("print('evil')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_path_same_bytes_changed_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    (env["artifact_dir"] / "main.py").write_text("print('evil')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"],
                              env["artifact_dir"], env["authority"]["artifact_digest"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_artifact_path_swap_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    moved = env["artifact_dir"].with_name("artifact_old")
    env["artifact_dir"].rename(moved)
    env["artifact_dir"].mkdir()
    (env["artifact_dir"] / "main.py").write_text("print('evil')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"],
                              env["artifact_dir"], env["authority"]["artifact_digest"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_b3_mounts_artifact_read_only(tmp_path, candidate, evaluation,
                                      confirm, monkeypatch) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k:
                        calls.append((a, k)) or {
                            "sandbox_id": "cbx-test", "exit_code": 0,
                            "stdout": "ok", "stderr": "",
                            "elapsed_s": 0.1, "timed_out": False})
    (h.state / "b3_entry.json").write_text(json.dumps(
        {"name": NAME, "capability_id": env["entry"]["capability_id"]}))
    h.phase_future("b3")
    assert len(calls) == 1
    mounts = calls[0][0][1]
    artifact_mount = next(m for m in mounts
                          if str(env["artifact_dir"]) == str(m[0]))
    assert artifact_mount[2] is True  # read-only bind mount


# --- Revocation / Supersession --------------------------------------------

@pytest.mark.parametrize("status", ["REVOKED", "SUPERSEDED"])
def test_revoked_or_superseded_authority_blocked(
    tmp_path, candidate, evaluation, confirm, status
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    result = revoke_authority(env["root"], env["authority"]["authority_id"],
                              status=status, issuer_id="test", reason="test")
    assert result["verdict"] == "REVOKED"
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"],
                              env["artifact_dir"], env["authority"]["artifact_digest"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


def test_revoked_authority_cannot_be_repromoted(
    tmp_path, candidate, evaluation, confirm
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    assert revoke_authority(root, issued["authority"]["authority_id"],
                            status="REVOKED", issuer_id="test")["verdict"] == "REVOKED"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, root,
                adoption_authority=issued["authority"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


# --- Replay / Double-spend -------------------------------------------------

def test_same_authority_repeated_adoption_is_reusable(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    first = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    second = guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    third = guard.verify_at_mount(env["root"], env["entry"], env["artifact_dir"])
    assert first == second == third


def test_different_authority_same_candidate_version_blocked(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    other = copy.deepcopy(env["authority"])
    other["promotion_decision_id"] = "dec-other"
    other["decision_id"] = "dec-other"
    other["authority_id"] = authority_id_for(CAND_ID, "v1", "dec-other")
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, env["root"],
                adoption_authority=other)
    assert "MISSING_DECISION" in blocked_codes(ei.value)
    entry = json.loads((env["root"] / FAMILY / f"{NAME}.json").read_text())
    assert entry["adoption"]["promotion_decision_id"] \
        == env["authority"]["promotion_decision_id"]


# --- 8.4.1 integrity closure: ledger-anchored runtime + canonical revocation

def _rewrite_store(root, store: dict) -> None:
    (root / "adoption_store.json").write_text(json.dumps(store, indent=2) + "\n")


def test_invariant_g8_missing_ledger_blocks_runtime(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    authority_record_path(env["root"], env["authority"]["authority_id"]).unlink()
    # store authority + candidate + artifact are all unchanged: only the
    # ledger record is missing, so the block must come from the ledger rule
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    codes = blocked_codes(ei.value)
    assert "UNISSUED_AUTHORITY" in codes
    assert "ARTIFACT_DIGEST_MISMATCH" not in codes
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"], env["artifact_dir"])
    assert "UNISSUED_AUTHORITY" in blocked_codes(ei.value)


def test_invariant_g8_ledger_deleted_store_rewritten_still_blocks(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    authority_record_path(env["root"], env["authority"]["authority_id"]).unlink()
    store = load_store(env["root"])
    store["authorities"][0]["candidate_version"] = "v2"
    _rewrite_store(env["root"], store)
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "UNISSUED_AUTHORITY" in blocked_codes(ei.value)


def test_invariant_g9_store_revocation_copy_is_load_bearing(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    aid = env["authority"]["authority_id"]
    assert revoke_authority(env["root"], aid, status="REVOKED",
                            issuer_id="test", reason="test")["verdict"] == "REVOKED"
    store = load_store(env["root"])
    copy = next(r for r in store["revocations"] if r["authority_id"] == aid)
    assert copy["decision_id"] == env["authority"]["promotion_decision_id"]
    authority_events_path(env["root"], aid).unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)
    with pytest.raises(AdoptionBlocked) as ei:
        guard.verify_at_mount(env["root"], env["entry"], env["artifact_dir"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


def test_invariant_g9_registry_does_not_allow_without_events_file(
    tmp_path, candidate, evaluation, confirm
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    assert issued["verdict"] == "AUTHORITY_ISSUED"
    assert revoke_authority(root, issued["authority"]["authority_id"],
                            status="REVOKED", issuer_id="test",
                            reason="test")["verdict"] == "REVOKED"
    authority_events_path(root, issued["authority"]["authority_id"]).unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, root,
                adoption_authority=issued["authority"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


def test_invariant_g10_revocation_schema_uses_canonical_decision_id(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    aid = env["authority"]["authority_id"]
    assert revoke_authority(env["root"], aid, status="REVOKED",
                            issuer_id="test")["verdict"] == "REVOKED"
    event = json.loads(authority_events_path(env["root"], aid).read_text().strip())
    store = load_store(env["root"])
    copy = next(r for r in store["revocations"] if r["authority_id"] == aid)
    assert event["decision_id"] == env["authority"]["decision_id"]
    assert event["decision_id"] == event["promotion_decision_id"]
    assert copy["decision_id"] == env["authority"]["decision_id"]
    # decision_id alone is the canonical matching field: drop the legacy
    # mirror and the events file; the store copy must still block
    authority_events_path(env["root"], aid).unlink()
    copy.pop("promotion_decision_id", None)
    _rewrite_store(env["root"], store)
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


def test_rewritten_store_authority_blocks_runtime(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    store = load_store(env["root"])
    store["authorities"][0]["candidate_id"] = "cand-2"
    _rewrite_store(env["root"], store)
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "AUTHORITY_BINDING_MISMATCH" in blocked_codes(ei.value)


def test_mutated_entry_binding_blocks_runtime(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    env["entry"]["adoption"]["evaluation_run_id"] = "run-other"
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "ENTRY_BINDING_MISMATCH" in blocked_codes(ei.value)


def test_incomplete_adoption_on_hardened_store_blocks(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    env["entry"]["adoption"] = {}
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert blocked_codes(ei.value) & {"UNISSUED_AUTHORITY", "ENTRY_BINDING_MISSING"}


@pytest.mark.parametrize("mutation", [
    "event_status_to_issued",
    "store_copy_decision_id_rewritten",
    "event_log_corrupted",
])
def test_mutated_revocation_artifacts_still_block(
    tmp_path, candidate, evaluation, confirm, mutation
) -> None:
    env = issue_and_promote(tmp_path, candidate, evaluation, confirm)
    aid = env["authority"]["authority_id"]
    assert revoke_authority(env["root"], aid, status="REVOKED",
                            issuer_id="test")["verdict"] == "REVOKED"
    events_path = authority_events_path(env["root"], aid)
    if mutation == "event_status_to_issued":
        events_path.write_text(
            events_path.read_text().replace('"REVOKED"', '"ISSUED"') + "\n")
    elif mutation == "store_copy_decision_id_rewritten":
        store = load_store(env["root"])
        next(r for r in store["revocations"] if r["authority_id"] == aid)[
            "decision_id"] = "dec-other"
        _rewrite_store(env["root"], store)
    elif mutation == "event_log_corrupted":
        events_path.write_text("not-json\n")
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert blocked_codes(ei.value) & {
        "REVOKED_DECISION", "AUTHORITY_BINDING_MISMATCH"}
