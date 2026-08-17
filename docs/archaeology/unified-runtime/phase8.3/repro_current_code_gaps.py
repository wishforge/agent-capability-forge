#!/usr/bin/env python3
"""Phase 8.3 - current flat-JSON gap reproduction (offline, temp dirs only).

Each probe pins a CURRENT pilot-code behavior that the 8.3 hardening design
closes. If a probe's insecure outcome stops reproducing, the hardening has
landed and this script must be updated.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from pilot.adoption_authority import authority_id_for, dir_digest  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402

FAMILY = "F+"
NAME = "cap-x"
CREATED_AT = "2026-08-17T01:00:00Z"


def make_candidate(tmp: pathlib.Path) -> pathlib.Path:
    cand = tmp / "candidate"
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_text("print('hi')\n")
    (cand / "manifest.json").write_text(json.dumps({
        "capability": {"name": NAME, "version": 1},
        "provenance": {"forge_timestamp": "2026-08-17T00:00:00Z"},
    }))
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": "cand-1", "name": NAME, "state": "candidate"}))
    return cand


def evaluation() -> dict:
    return {"evaluation_id": "run-1", "candidate_id": "cand-1",
            "verdict": "PASS", "evaluated_at": CREATED_AT}


def store_for(authority: dict) -> dict:
    d = authority["artifact_digest"]
    return {
        "policies": {"pol-1": {"version": "1", "registered": True, "frozen": True}},
        "candidates": {"cand-1": {
            "version": "v1", "created_at": "2026-08-17T00:00:00Z",
            "forged_artifact_digest": d}},
        "runs": [{"run_id": "run-1", "candidate_id": "cand-1",
                  "candidate_version": "v1", "artifact_digest": d,
                  "policy_ref": "pol-1", "policy_version": "1",
                  "status": "EVALUATED", "created_at": CREATED_AT}],
        "evidence": [{"evidence_id": "ev-1", "run_id": "run-1",
                      "recorded_hash": "e1", "current_hash": "e1"}],
        "provenance": {"cand-1": {"policy": True, "evidence_manifest": True,
                                  "run_ids": ["run-1"],
                                  "immutable_artifact_refs": ["art-1"]}},
        "decisions": [{"decision_id": "dec-1", "candidate_id": "cand-1",
                       "candidate_version": "v1", "run_id": "run-1",
                       "policy_ref": "pol-1", "policy_version": "1",
                       "artifact_digest": d, "value": "PROMOTE",
                       "gate_result": "PASS", "created_at": CREATED_AT,
                       "recorded_hash": "d1", "current_hash": "d1"}],
        "lifecycle": {"cand-1": {"status": "PROMOTABLE",
                                 "transitions": [{"from": "PROMOTABLE",
                                                  "to": "PROMOTED"}]}},
        "revocations": [],
    }


def authority_for(artifact_dir: pathlib.Path, **overrides) -> dict:
    authority = {
        "authority_id": authority_id_for("cand-1", "v1", "dec-1"),
        "candidate_id": "cand-1",
        "candidate_version": "v1",
        "promotion_decision_id": "dec-1",
        "evaluation_run_id": "run-1",
        "policy_version": "1",
        "artifact_digest": dir_digest(artifact_dir),
        "provenance": {"policy": True, "evidence_manifest": True,
                       "run_ids": ["run-1"], "immutable_artifact_refs": ["art-1"]},
        "issued_at": CREATED_AT,
        "status": "ISSUED",
    }
    authority.update(overrides)
    return authority


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="phase8.3-gaps-"))
    try:
        cand = make_candidate(tmp)
        ev = evaluation()
        art = cand / "implementation" / "artifact"

        # G1: Registry promotes an authority that was never issued
        # (store has no "authorities" record at all).
        root1 = tmp / "r1"
        root1.mkdir()
        auth1 = authority_for(art)
        (root1 / "adoption_store.json").write_text(
            json.dumps(store_for(auth1)))
        promote(FAMILY, NAME, cand, ev, root1, adoption_authority=auth1)
        print("G1 unissued_authority_accepted_by_registry = ALLOW "
              "(store has no authorities record)")

        # G2: Registry ignores authority.status=REVOKED when the
        # revocations list is empty.
        root2 = tmp / "r2"
        root2.mkdir()
        auth2 = authority_for(art, status="REVOKED")
        (root2 / "adoption_store.json").write_text(
            json.dumps(store_for(auth2)))
        promote(FAMILY, NAME, cand, ev, root2, adoption_authority=auth2)
        print("G2 registry_promote_with_status_REVOKED_no_revocation = ALLOW")

        # G3: delete + recreate of the whole store is undetected.
        root3 = tmp / "r3"
        root3.mkdir()
        assert issue_authority(root3, cand, ev,
                               confirm={"operator": "test", "confirm": True}
                               )["verdict"] == "AUTHORITY_ISSUED"
        (root3 / "adoption_store.json").unlink()
        again = issue_authority(root3, cand, ev,
                                confirm={"operator": "test", "confirm": True})
        assert again["verdict"] == "AUTHORITY_ISSUED"
        print("G3 authority_store_delete_recreate = AUTHORITY_ISSUED (undetected)")

        # G4: adopt() validates digest A, then the artifact is replaced
        # before docker_launch mounts the same path.
        root4 = tmp / "r4"
        root4.mkdir()
        issued = issue_authority(root4, cand, ev,
                                 confirm={"operator": "test", "confirm": True})
        entry = promote(FAMILY, NAME, cand, ev, root4,
                        adoption_authority=issued["authority"])
        guard.mark_promoted(root4, entry)
        artifact_dir = pathlib.Path(entry["artifact_dir"])
        report = guard.adopt(root4, entry, artifact_dir)
        (artifact_dir / "main.py").write_text("print('evil')\n")
        assert report["artifact_digest"] != dir_digest(artifact_dir)
        print("G4 adopt_allowed_digest=" + report["artifact_digest"]
              + " post_replace_digest=" + dir_digest(artifact_dir)
              + " (mount would use the replaced bytes)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("CURRENT_GAPS_REPRODUCED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
