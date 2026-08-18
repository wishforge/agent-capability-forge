"""Phase 8.4.3 - external Integrity Trust Anchor tests.

Covers:
  - operator-sealed external anchor (create-only, never auto-repaired)
  - sealed store: valid anchor ALLOWs; missing/corrupted/mutated anchors BLOCK
  - authority / revocation / store tampering fail closed on a sealed store
  - legacy (unsealed) stores keep Phase 8.4.2 semantics
"""

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

from pilot.adoption_authority import (  # noqa: E402
    authority_events_path,
    authority_record_path,
    integrity_anchor_path,
    load_store,
    revoke_authority,
    seal_trust_anchor,
    write_trust_anchor,
)
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402

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


def sealed_env(tmp_path, candidate, evaluation, confirm) -> dict:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    assert seal_trust_anchor(root) is None
    entry = promote(FAMILY, NAME, candidate, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    return {"root": root, "entry": entry, "authority": issued["authority"],
            "artifact_dir": Path(entry["artifact_dir"])}


def _rewrite_store(root, store: dict) -> None:
    (root / "adoption_store.json").write_text(json.dumps(store, indent=2) + "\n")


def _revoke(env) -> str:
    aid = env["authority"]["authority_id"]
    assert revoke_authority(env["root"], aid, status="REVOKED",
                            issuer_id="test")["verdict"] == "REVOKED"
    return aid


# --- valid / legacy / seal semantics ---------------------------------------

def test_sealed_store_valid_anchor_allows(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = sealed_env(tmp_path, candidate, evaluation, confirm)
    assert integrity_anchor_path(env["root"]).exists()
    assert load_store(env["root"])["store_metadata"]["trust_anchor_sealed"] is True
    assert guard.adopt(env["root"], env["entry"], env["artifact_dir"])["verdict"] == "ALLOW"
    assert guard.verify_at_mount(
        env["root"], env["entry"], env["artifact_dir"])["verdict"] == "ALLOW"


def test_unsealed_store_keeps_legacy_semantics(
    tmp_path, candidate, evaluation, confirm
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    assert not integrity_anchor_path(root).exists()
    entry = promote(FAMILY, NAME, candidate, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    assert guard.adopt(root, entry, Path(entry["artifact_dir"]))["verdict"] == "ALLOW"


def test_seal_is_create_only(tmp_path, candidate, evaluation, confirm) -> None:
    env = sealed_env(tmp_path, candidate, evaluation, confirm)
    assert seal_trust_anchor(env["root"]) == "TRUST_ANCHOR_ALREADY_EXISTS"


def test_anchor_inside_store_dir_fails_closed(
    tmp_path, candidate, evaluation, confirm, monkeypatch
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    monkeypatch.setenv("PILOT_INTEGRITY_ANCHOR", str(root / "inner-anchor.json"))
    assert write_trust_anchor(root, create_only=True) == "TRUST_ANCHOR_CONFIG_INVALID"
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, root,
                adoption_authority=issued["authority"])
    assert "INTEGRITY_STORE_CORRUPTED" in blocked_codes(ei.value)


def test_anchor_env_path_is_external(
    tmp_path, candidate, evaluation, confirm, monkeypatch
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    issued = issue_authority(root, candidate, evaluation, confirm=confirm)
    anchor = tmp_path / "external-anchor.json"
    monkeypatch.setenv("PILOT_INTEGRITY_ANCHOR", str(anchor))
    assert seal_trust_anchor(root) is None
    assert anchor.exists()
    assert not (root.parent / "registry.integrity-anchor.json").exists()
    entry = promote(FAMILY, NAME, candidate, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    assert guard.adopt(root, entry, Path(entry["artifact_dir"]))["verdict"] == "ALLOW"


def test_revoke_refreshes_anchor(
    tmp_path, candidate, evaluation, confirm
) -> None:
    env = sealed_env(tmp_path, candidate, evaluation, confirm)
    before = json.loads(integrity_anchor_path(env["root"]).read_text())
    _revoke(env)
    after = json.loads(integrity_anchor_path(env["root"]).read_text())
    assert after["anchor_revision"] == before["anchor_revision"] + 1
    assert after["revocation_manifest_digest"] != before["revocation_manifest_digest"]
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "REVOKED_DECISION" in blocked_codes(ei.value)


# --- adversarial attacks on a sealed store ---------------------------------

def _attack_delete_store_metadata(env) -> None:
    store = load_store(env["root"])
    store.pop("store_metadata", None)
    _rewrite_store(env["root"], store)


def _attack_mutate_integrity_mode(env) -> None:
    store = load_store(env["root"])
    store["store_metadata"]["integrity_mode"] = "legacy"
    _rewrite_store(env["root"], store)


def _attack_delete_authorities_dir(env) -> None:
    shutil.rmtree(env["root"] / "authorities")


def _attack_mutate_authority_record(env) -> None:
    p = authority_record_path(env["root"], env["authority"]["authority_id"])
    record = json.loads(p.read_text())
    record["candidate_id"] = "cand-2"
    p.write_text(json.dumps(record, indent=2) + "\n")


def _attack_replace_authority_record(env) -> None:
    p = authority_record_path(env["root"], env["authority"]["authority_id"])
    replacement = copy.deepcopy(env["authority"])
    replacement["candidate_version"] = "v9"
    p.write_text(json.dumps(replacement, indent=2) + "\n")


def _attack_delete_revocation_event(env) -> None:
    authority_events_path(env["root"], _revoke(env)).unlink()


def _attack_mutate_revocation_copy(env) -> None:
    aid = _revoke(env)
    store = load_store(env["root"])
    next(r for r in store["revocations"] if r["authority_id"] == aid)["status"] = "ISSUED"
    _rewrite_store(env["root"], store)


def _attack_mutate_both_revocation_ids(env) -> None:
    aid = _revoke(env)
    events = authority_events_path(env["root"], aid)
    event = json.loads(events.read_text().splitlines()[0])
    event["decision_id"] = "dec-evil"
    event["promotion_decision_id"] = "dec-evil"
    events.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    store = load_store(env["root"])
    rec = next(r for r in store["revocations"] if r["authority_id"] == aid)
    rec["decision_id"] = "dec-evil"
    rec["promotion_decision_id"] = "dec-evil"
    _rewrite_store(env["root"], store)


def _attack_delete_revocation(env) -> None:
    aid = _revoke(env)
    authority_events_path(env["root"], aid).unlink()
    store = load_store(env["root"])
    store["revocations"] = [r for r in store["revocations"] if r["authority_id"] != aid]
    _rewrite_store(env["root"], store)


def _attack_delete_trust_anchor(env) -> None:
    integrity_anchor_path(env["root"]).unlink()


def _attack_mutate_trust_anchor(env) -> None:
    p = integrity_anchor_path(env["root"])
    anchor = json.loads(p.read_text())
    anchor["authority_manifest_digest"] = "sha256:evil"
    p.write_text(json.dumps(anchor, indent=2) + "\n")


def _attack_store_hash_mismatch(env) -> None:
    store = load_store(env["root"])
    store["decisions"][0]["recorded_hash"] = "sha256:evil"
    _rewrite_store(env["root"], store)


def _attack_authority_manifest_mismatch(env) -> None:
    (env["root"] / "authorities" / "extra.json").write_text("{}\n")


def _attack_revocation_manifest_mismatch(env) -> None:
    p = authority_events_path(env["root"], _revoke(env))
    p.write_text(p.read_text() + "\n")  # raw byte change -> digest mismatch


ATTACKS = {
    "1_delete_store_metadata": _attack_delete_store_metadata,
    "2_mutate_integrity_mode": _attack_mutate_integrity_mode,
    "3_delete_authorities_dir": _attack_delete_authorities_dir,
    "4_mutate_authority_record": _attack_mutate_authority_record,
    "5_replace_authority_record": _attack_replace_authority_record,
    "6_delete_revocation_event": _attack_delete_revocation_event,
    "7_mutate_revocation_copy": _attack_mutate_revocation_copy,
    "8_mutate_both_revocation_ids": _attack_mutate_both_revocation_ids,
    "9_delete_revocation": _attack_delete_revocation,
    "10_delete_trust_anchor": _attack_delete_trust_anchor,
    "11_mutate_trust_anchor": _attack_mutate_trust_anchor,
    "12_store_hash_mismatch": _attack_store_hash_mismatch,
    "13_authority_manifest_mismatch": _attack_authority_manifest_mismatch,
    "14_revocation_manifest_mismatch": _attack_revocation_manifest_mismatch,
}


@pytest.mark.parametrize("attack", sorted(ATTACKS))
def test_anchored_store_fails_closed_on_attack(
    tmp_path, candidate, evaluation, confirm, attack
) -> None:
    env = sealed_env(tmp_path, candidate, evaluation, confirm)
    ATTACKS[attack](env)
    with pytest.raises(AdoptionBlocked) as ei:
        guard.adopt(env["root"], env["entry"], env["artifact_dir"])
    assert "INTEGRITY_STORE_CORRUPTED" in blocked_codes(ei.value), attack
    with pytest.raises(AdoptionBlocked) as ei:
        promote(FAMILY, NAME, candidate, evaluation, env["root"],
                adoption_authority=env["authority"])
    assert "INTEGRITY_STORE_CORRUPTED" in blocked_codes(ei.value), attack
