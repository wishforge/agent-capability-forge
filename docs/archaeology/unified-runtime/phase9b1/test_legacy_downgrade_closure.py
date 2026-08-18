"""Phase 9-B.1.1 adversarial closure: canonical candidates cannot downgrade.

Covers A-J from the Phase 9-B.1.1 closure spec:
  A fresh candidate + frozen_root omitted at issue / promote
  B canonical proof missing
  C frozen record deletion
  D artifact_identity stripping
  E frozen_root stripping
  F undeclared artifact
  G digest ambiguity
  H legacy compatibility
  I production B3 regression
  J rejected cases create no legacy binding
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from forge.capabilityizer import (  # noqa: E402
    CANONICAL_ARTIFACT_IDENTITY_V1,
    artifact_digest,
    bind_evaluation,
    freeze_candidate_dir,
)
from pilot.adoption_authority import dir_digest as legacy_dir_digest  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402

NAME = "cap-x"
CAND_ID = "cand-9b1"
CONFIRM = {"operator": "test", "confirm": True}


def build_candidate(tmp_path: pathlib.Path, *, main: bytes = b"print('hi')\n",
                    new: bool = True) -> pathlib.Path:
    cand = tmp_path / "candidate"
    artifact = cand / "implementation" / "artifact"
    artifact.mkdir(parents=True)
    (artifact / "main.py").write_bytes(main)
    forged = artifact_digest(artifact, ["main.py"])
    (cand / "tests" / "t1").mkdir(parents=True)
    (cand / "tests" / "t1" / "data.csv").write_text("id\n")
    (cand / "tests" / "t1" / "expected.json").write_text("{}")
    manifest = {
        "manifest_version": "0.1",
        "capability": {"name": NAME, "description": "demo", "version": 1},
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
        "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                    "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
        "provenance": {
            "source_bundle_id": "bundle-1",
            "source_artifact_digest": "sha256:" + "a" * 64,
            "forged_artifact_digest": forged,
            "forge_timestamp": "2026-08-18T00:00:00Z",
        },
    }
    (cand / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    meta = {"candidate_id": CAND_ID, "name": NAME, "state": "candidate"}
    if new:
        meta["source_bundle_ids"] = ["bundle-1"]
    (cand / "candidate.json").write_text(json.dumps(meta, indent=2) + "\n")
    return cand


def base_evaluation() -> dict:
    return {"evaluation_id": "run-1", "verdict": "PASS",
            "regression": "PASS", "novel_input_test": "PASS",
            "independent_reuse": "PASS",
            "evaluated_at": "2026-08-18T01:00:00Z"}


def canonical_env(tmp_path: pathlib.Path, *, promote_entry: bool = True) -> dict:
    state = tmp_path / "state"
    registry_root = state / "registry"
    frozen_root = state / "frozen_candidates"
    registry_root.mkdir(parents=True)
    cand = build_candidate(tmp_path)
    frozen = freeze_candidate_dir(cand, frozen_root, registry_root=registry_root)
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation(),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM,
                             frozen_root=frozen_root)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    env = {"state": state, "registry_root": registry_root,
           "frozen_root": frozen_root, "candidate": cand,
           "evaluation": evaluation, "authority": issued["authority"]}
    if not promote_entry:
        return env
    entry = promote("F+", NAME, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"], frozen_root=frozen_root)
    guard.mark_promoted(registry_root, entry)
    env["entry"] = entry
    env["artifact_dir"] = pathlib.Path(entry["artifact_dir"])
    return env


def legacy_env(tmp_path: pathlib.Path) -> dict:
    state = tmp_path / "state"
    registry_root = state / "registry"
    registry_root.mkdir(parents=True)
    cand = build_candidate(tmp_path, new=False)
    evaluation = dict(base_evaluation(), evaluation_id="run-legacy")
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote("F+", NAME, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(registry_root, entry)
    return {"registry_root": registry_root, "entry": entry,
            "artifact_dir": pathlib.Path(entry["artifact_dir"])}


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def entry_path(env: dict) -> pathlib.Path:
    return env["registry_root"] / "F+" / f"{NAME}.json"


def test_a_fresh_candidate_omit_frozen_root_at_issue_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        registry_root = tmp / "registry"
        registry_root.mkdir(parents=True)
        cand = build_candidate(tmp)
        result = issue_authority(registry_root, cand, base_evaluation(),
                                 confirm=CONFIRM)
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert "CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT" in {
            v["code"] for v in result["violations"]}
        assert not (registry_root / "F+" / f"{NAME}.json").exists()


def test_a_fresh_candidate_omit_frozen_root_at_promote_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp, promote_entry=False)
        with pytest.raises(AdoptionBlocked) as ei:
            promote("F+", NAME, env["candidate"], env["evaluation"],
                    env["registry_root"], adoption_authority=env["authority"],
                    frozen_root=None)
        assert "CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT" in blocked_codes(ei.value)
        assert not entry_path(env).exists()


def test_b_canonical_proof_missing_blocks() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        store_path = env["registry_root"] / "adoption_store.json"
        store = json.loads(store_path.read_text())
        store_auth = next(a for a in store["authorities"]
                          if a["authority_id"] == env["authority"]["authority_id"])
        del store_auth["seal_digest"]
        store_path.write_text(json.dumps(store, indent=2) + "\n")
        file_path = env["registry_root"] / "authorities" / f"{env['authority']['authority_id']}.json"
        file_auth = json.loads(file_path.read_text())
        del file_auth["seal_digest"]
        file_path.write_text(json.dumps(file_auth, indent=2) + "\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "CANONICAL_IDENTITY_MISMATCH" in blocked_codes(ei.value)


def test_c_frozen_record_deletion_blocks() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        (env["frozen_root"] / "frozen" / f"{CAND_ID}.json").unlink()
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "MISSING_FROZEN_CANDIDATE" in blocked_codes(ei.value)


def test_d_artifact_identity_stripping_blocks() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        path = entry_path(env)
        entry = json.loads(path.read_text())
        del entry["artifact_identity"]
        path.write_text(json.dumps(entry, indent=2) + "\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], entry, env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "ARTIFACT_IDENTITY_MISMATCH" in blocked_codes(ei.value)


def test_e_frozen_root_stripping_blocks() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        path = entry_path(env)
        entry = json.loads(path.read_text())
        del entry["frozen_root"]
        path.write_text(json.dumps(entry, indent=2) + "\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], entry, env["artifact_dir"])
        assert "MISSING_FROZEN_CANDIDATE" in blocked_codes(ei.value)


def test_f_undeclared_artifact_blocks_not_legacy() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        (env["artifact_dir"] / "extra.py").write_text("x=1\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "UNDECLARED_ARTIFACT_FILE" in blocked_codes(ei.value)
        path = entry_path(env)
        stripped = json.loads(path.read_text())
        stripped.pop("artifact_identity", None)
        stripped.pop("frozen_root", None)
        path.write_text(json.dumps(stripped, indent=2) + "\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], stripped, env["artifact_dir"])
        assert "ARTIFACT_IDENTITY_MISMATCH" in blocked_codes(ei.value)


def test_g_digest_equality_does_not_decide_canonical() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        assert legacy_dir_digest(env["artifact_dir"]) == \
            env["entry"]["adoption"]["artifact_digest"]
        path = entry_path(env)
        entry = json.loads(path.read_text())
        del entry["artifact_identity"]
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], entry, env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "ARTIFACT_IDENTITY_MISMATCH" in blocked_codes(ei.value)
        lenv = legacy_env(tmp / "legacy")
        assert lenv["entry"]["adoption"]["artifact_digest"] == \
            env["entry"]["adoption"]["artifact_digest"]
        assert guard.adopt(
            lenv["registry_root"], lenv["entry"], lenv["artifact_dir"]
        )["verdict"] == "ALLOW"


def test_h_legacy_compatibility_preserved() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = legacy_env(tmp)
        report = guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"])
        assert report["verdict"] == "ALLOW"


def test_i_production_b3_canonical_regression() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        report = guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                             frozen_root=env["frozen_root"])
        assert report["verdict"] == "ALLOW"
        mount = guard.verify_at_mount(
            env["registry_root"], env["entry"], env["artifact_dir"],
            report["artifact_digest"], frozen_root=env["frozen_root"])
        assert mount["verdict"] == "ALLOW"
        assert env["entry"]["artifact_identity"] == CANONICAL_ARTIFACT_IDENTITY_V1
        assert env["authority"]["artifact_identity"] == CANONICAL_ARTIFACT_IDENTITY_V1


def test_j_rejected_cases_create_no_legacy_binding() -> None:
    def assert_no_writes(env, *, frozen_root_kwarg):
        store_path = env["registry_root"] / "adoption_store.json"
        store_before = store_path.read_bytes()
        with pytest.raises(AdoptionBlocked):
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        **frozen_root_kwarg)
        assert store_path.read_bytes() == store_before
        assert entry_path(env).exists()

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = canonical_env(tmp)
        (env["frozen_root"] / "frozen" / f"{CAND_ID}.json").unlink()
        assert_no_writes(env, frozen_root_kwarg={"frozen_root": env["frozen_root"]})

    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td))
        path = entry_path(env)
        entry = {k: v for k, v in json.loads(path.read_text()).items()
                 if k != "artifact_identity"}
        path.write_text(json.dumps(entry, indent=2) + "\n")
        env["entry"] = entry
        assert_no_writes(env, frozen_root_kwarg={"frozen_root": env["frozen_root"]})

    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td))
        path = entry_path(env)
        entry = {k: v for k, v in json.loads(path.read_text()).items()
                 if k != "frozen_root"}
        path.write_text(json.dumps(entry, indent=2) + "\n")
        env["entry"] = entry
        assert_no_writes(env, frozen_root_kwarg={})

    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td))
        (env["artifact_dir"] / "extra.py").write_text("x=1\n")
        assert_no_writes(env, frozen_root_kwarg={"frozen_root": env["frozen_root"]})
