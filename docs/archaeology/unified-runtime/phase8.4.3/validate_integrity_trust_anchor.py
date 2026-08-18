#!/usr/bin/env python3
"""Phase 8.4.3 standalone validator: sealed-store adversarial matrix.

Builds a real store with pilot production code, seals it with an external
trust anchor, then runs every Phase 8.4.3 attack. Each attack must yield
INTEGRITY_STORE_CORRUPTED -> ADOPTION_BLOCKED on both registry and runtime
paths. Exits non-zero on the first failure.
"""

from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from pilot.adoption_authority import (  # noqa: E402
    authority_events_path,
    authority_record_path,
    integrity_anchor_path,
    load_store,
    revoke_authority,
    seal_trust_anchor,
)
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"
CAND_ID = "cand-1"
RUN_ID = "run-1"
CREATED_AT = "2026-08-18T01:00:00Z"


def build_candidate(tmp: Path) -> Path:
    cand = tmp / "candidate"
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(json.dumps({
        "capability": {"name": NAME, "version": 1},
        "provenance": {"forge_timestamp": "2026-08-18T00:00:00Z"}}))
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": CAND_ID, "name": NAME, "state": "candidate"}))
    return cand


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def sealed_env(tmp: Path) -> dict:
    cand = build_candidate(tmp)
    evaluation = {"evaluation_id": RUN_ID, "candidate_id": CAND_ID,
                  "verdict": "PASS", "evaluated_at": CREATED_AT}
    confirm = {"operator": "test", "confirm": True}
    root = tmp / "registry"
    root.mkdir()
    issued = issue_authority(root, cand, evaluation, confirm=confirm)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    assert seal_trust_anchor(root) is None
    entry = promote(FAMILY, NAME, cand, evaluation, root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(root, entry)
    return {"root": root, "entry": entry, "authority": issued["authority"],
            "artifact_dir": Path(entry["artifact_dir"]), "candidate": cand}


def rewrite_store(root, store: dict) -> None:
    (root / "adoption_store.json").write_text(json.dumps(store, indent=2) + "\n")


def revoke(env) -> str:
    aid = env["authority"]["authority_id"]
    assert revoke_authority(env["root"], aid, status="REVOKED",
                            issuer_id="test")["verdict"] == "REVOKED"
    return aid


def attack_delete_store_metadata(env) -> None:
    store = load_store(env["root"])
    store.pop("store_metadata", None)
    rewrite_store(env["root"], store)


def attack_mutate_integrity_mode(env) -> None:
    store = load_store(env["root"])
    store["store_metadata"]["integrity_mode"] = "legacy"
    rewrite_store(env["root"], store)


def attack_delete_authorities_dir(env) -> None:
    shutil.rmtree(env["root"] / "authorities")


def attack_mutate_authority_record(env) -> None:
    p = authority_record_path(env["root"], env["authority"]["authority_id"])
    record = json.loads(p.read_text())
    record["candidate_id"] = "cand-2"
    p.write_text(json.dumps(record, indent=2) + "\n")


def attack_replace_authority_record(env) -> None:
    p = authority_record_path(env["root"], env["authority"]["authority_id"])
    replacement = copy.deepcopy(env["authority"])
    replacement["candidate_version"] = "v9"
    p.write_text(json.dumps(replacement, indent=2) + "\n")


def attack_delete_revocation_event(env) -> None:
    authority_events_path(env["root"], revoke(env)).unlink()


def attack_mutate_revocation_copy(env) -> None:
    aid = revoke(env)
    store = load_store(env["root"])
    next(r for r in store["revocations"] if r["authority_id"] == aid)["status"] = "ISSUED"
    rewrite_store(env["root"], store)


def attack_mutate_both_revocation_ids(env) -> None:
    aid = revoke(env)
    events = authority_events_path(env["root"], aid)
    event = json.loads(events.read_text().splitlines()[0])
    event["decision_id"] = "dec-evil"
    event["promotion_decision_id"] = "dec-evil"
    events.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    store = load_store(env["root"])
    rec = next(r for r in store["revocations"] if r["authority_id"] == aid)
    rec["decision_id"] = "dec-evil"
    rec["promotion_decision_id"] = "dec-evil"
    rewrite_store(env["root"], store)


def attack_delete_revocation(env) -> None:
    aid = revoke(env)
    authority_events_path(env["root"], aid).unlink()
    store = load_store(env["root"])
    store["revocations"] = [r for r in store["revocations"] if r["authority_id"] != aid]
    rewrite_store(env["root"], store)


def attack_delete_trust_anchor(env) -> None:
    integrity_anchor_path(env["root"]).unlink()


def attack_mutate_trust_anchor(env) -> None:
    p = integrity_anchor_path(env["root"])
    anchor = json.loads(p.read_text())
    anchor["authority_manifest_digest"] = "sha256:evil"
    p.write_text(json.dumps(anchor, indent=2) + "\n")


def attack_store_hash_mismatch(env) -> None:
    store = load_store(env["root"])
    store["decisions"][0]["recorded_hash"] = "sha256:evil"
    rewrite_store(env["root"], store)


def attack_authority_manifest_mismatch(env) -> None:
    (env["root"] / "authorities" / "extra.json").write_text("{}\n")


def attack_revocation_manifest_mismatch(env) -> None:
    p = authority_events_path(env["root"], revoke(env))
    p.write_text(p.read_text() + "\n")


ATTACKS = {
    "delete_store_metadata": attack_delete_store_metadata,
    "mutate_integrity_mode": attack_mutate_integrity_mode,
    "delete_authorities_dir": attack_delete_authorities_dir,
    "mutate_authority_record": attack_mutate_authority_record,
    "replace_authority_record": attack_replace_authority_record,
    "delete_revocation_event": attack_delete_revocation_event,
    "mutate_revocation_copy": attack_mutate_revocation_copy,
    "mutate_both_revocation_ids": attack_mutate_both_revocation_ids,
    "delete_revocation": attack_delete_revocation,
    "delete_trust_anchor": attack_delete_trust_anchor,
    "mutate_trust_anchor": attack_mutate_trust_anchor,
    "store_hash_mismatch": attack_store_hash_mismatch,
    "authority_manifest_mismatch": attack_authority_manifest_mismatch,
    "revocation_manifest_mismatch": attack_revocation_manifest_mismatch,
}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = sealed_env(tmp)
        if guard.adopt(env["root"], env["entry"], env["artifact_dir"])["verdict"] != "ALLOW":
            print("FAIL valid sealed store does not ALLOW")
            return 1
        print(f"{'attack':34} result")
        for name, fn in ATTACKS.items():
            victim = sealed_env(tmp / f"case-{name}")
            fn(victim)
            for path_name, call in (
                ("runtime", lambda: guard.adopt(
                    victim["root"], victim["entry"], victim["artifact_dir"])),
                ("registry", lambda: promote(
                    FAMILY, NAME, victim["candidate"], {
                        "evaluation_id": RUN_ID, "candidate_id": CAND_ID,
                        "verdict": "PASS", "evaluated_at": CREATED_AT},
                    victim["root"], adoption_authority=victim["authority"])),
            ):
                try:
                    call()
                except AdoptionBlocked as exc:
                    codes = blocked_codes(exc)
                    ok = "INTEGRITY_STORE_CORRUPTED" in codes
                    print(f"{name + '/' + path_name:34} "
                          f"{'PASS' if ok else 'FAIL ' + str(sorted(codes))}")
                    if not ok:
                        return 1
                else:
                    print(f"{name + '/' + path_name:34} FAIL (ALLOW)")
                    return 1
    print("\nTRUST_ANCHOR_PARTIAL: sealed-store adversarial matrix PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
