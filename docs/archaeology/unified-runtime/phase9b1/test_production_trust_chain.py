"""Phase 9-B.1 closure RED tests: Frozen Candidate must be the production
trust source for issue_authority -> promote -> runtime activation, with one
canonical digest and fail-closed evaluation binding.

These tests target the real production call chain:
  src/forge/capabilityizer.py
  pilot/adoption_authority_producer.py
  pilot/registry.py
  pilot/runtime_adoption_guard.py
  pilot/harness.py
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from forge.capabilityizer import (  # noqa: E402
    CANONICAL_ARTIFACT_IDENTITY_V1,
    artifact_digest,
    bind_evaluation,
    freeze_candidate_dir,
    load_frozen_candidate,
)
from pilot.adoption_authority import dir_digest as legacy_dir_digest  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402

NAME = "cap-x"
CAND_ID = "cand-9b1"
CONFIRM = {"operator": "test", "confirm": True}


def build_candidate(tmp_path: pathlib.Path, *, main: bytes = b"print('hi')\n",
                    new: bool = True) -> pathlib.Path:
    cand = tmp_path / "candidate"
    (cand / "implementation" / "artifact").mkdir(parents=True)
    (cand / "implementation" / "artifact" / "main.py").write_bytes(main)
    forged = artifact_digest(cand / "implementation" / "artifact", ["main.py"])
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


def build_env(tmp_path: pathlib.Path, *, promote_entry: bool = True) -> dict:
    """Freeze a candidate, bind evaluation, issue authority, optionally promote."""
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


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def make_harness(tmp_path: pathlib.Path, env: dict, monkeypatch) -> harness_mod.Harness:
    h = harness_mod.Harness(force=True)
    h.state = env["state"]
    h.state.mkdir(parents=True, exist_ok=True)
    h.bundle_store = h.state / "bundle_store"
    h.records_path = h.state / "run_records.jsonl"
    h.events_path = h.state / "cost_events.jsonl"
    h.registry_root = env["registry_root"]
    h.family = dict(h.family, future_tasks=[h.family["future_tasks"][0]])
    h._check_docker = lambda: None
    h._make_codex_home = lambda run_dir, skills=None: run_dir / "codex_home"
    h._oracle = lambda task, out: {"verdict": "PASS", "reason": "ok",
                                   "stable": True, "runs": []}
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: {
        "sandbox_id": "cbx-9b1", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    return h


def test_evaluation_artifact_digest_mismatch_blocks_issue() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        env["evaluation"]["artifact_digest"] = "sha256:" + "f" * 64
        result = issue_authority(env["registry_root"], env["candidate"],
                                 env["evaluation"], confirm=CONFIRM,
                                 frozen_root=env["frozen_root"])
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert {v["code"] for v in result["violations"]} == {
            "EVALUATION_BINDING_MISMATCH"}


def test_evaluation_artifact_digest_mismatch_blocks_promote() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        bad_eval = dict(env["evaluation"], artifact_digest="sha256:" + "f" * 64)
        with pytest.raises(AdoptionBlocked) as ei:
            promote("F+", NAME, env["candidate"], bad_eval, env["registry_root"],
                    adoption_authority=env["authority"], frozen_root=env["frozen_root"])
        assert "EVALUATION_BINDING_MISMATCH" in blocked_codes(ei.value)


def test_evaluation_artifact_digest_mismatch_blocks_runtime() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        env["entry"]["evaluation"]["artifact_digest"] = "sha256:" + "f" * 64
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "EVALUATION_BINDING_MISMATCH" in blocked_codes(ei.value)


def test_live_manifest_swap_blocks_issue() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        manifest = json.loads((env["candidate"] / "manifest.json").read_text())
        manifest["capability"]["version"] = 2
        (env["candidate"] / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n")
        result = issue_authority(env["registry_root"], env["candidate"],
                                 env["evaluation"], confirm=CONFIRM,
                                 frozen_root=env["frozen_root"])
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert "FROZEN_CANDIDATE_MISMATCH" in {
            v["code"] for v in result["violations"]}


def test_live_tests_swap_blocks_issue() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        (env["candidate"] / "tests" / "t1" / "data.csv").write_text("id,tampered\n")
        result = issue_authority(env["registry_root"], env["candidate"],
                                 env["evaluation"], confirm=CONFIRM,
                                 frozen_root=env["frozen_root"])
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert "TESTS_CHANGED_AFTER_SEAL" in {
            v["code"] for v in result["violations"]}


def test_evaluation_seal_digest_mismatch_blocks() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        env["evaluation"]["seal_digest"] = "sha256:" + "e" * 64
        result = issue_authority(env["registry_root"], env["candidate"],
                                 env["evaluation"], confirm=CONFIRM,
                                 frozen_root=env["frozen_root"])
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert "EVALUATION_BINDING_MISMATCH" in {
            v["code"] for v in result["violations"]}


def test_frozen_candidate_mutation_blocks_runtime() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        snap = env["frozen_root"] / "frozen" / CAND_ID / "artifact" / "main.py"
        snap.write_bytes(b"print('tampered')\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_undeclared_file_before_issue_blocks() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        (env["candidate"] / "implementation" / "artifact" / "extra.py").write_text("x=1\n")
        result = issue_authority(env["registry_root"], env["candidate"],
                                 env["evaluation"], confirm=CONFIRM,
                                 frozen_root=env["frozen_root"])
        assert result["verdict"] == "AUTHORITY_ISSUANCE_BLOCKED"
        assert "UNDECLARED_ARTIFACT_FILE" in {v["code"] for v in result["violations"]}


def test_undeclared_file_before_promote_blocks() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp, promote_entry=False)
        (env["candidate"] / "implementation" / "artifact" / "extra.py").write_text("x=1\n")
        with pytest.raises(AdoptionBlocked) as ei:
            promote("F+", NAME, env["candidate"], env["evaluation"],
                    env["registry_root"], adoption_authority=env["authority"],
                    frozen_root=env["frozen_root"])
        assert "UNDECLARED_ARTIFACT_FILE" in blocked_codes(ei.value)


def test_undeclared_file_before_runtime_blocks() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        (env["artifact_dir"] / "malicious_extra.py").write_text("x=1\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "UNDECLARED_ARTIFACT_FILE" in blocked_codes(ei.value)


def test_runtime_generated_files_cannot_enter_bind_mount() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for rel in ("__pycache__/main.cpython-313.pyc", "run.log",
                    "scratch.tmp", "generated/out.txt", "malicious_extra.py"):
            env = build_env(tmp / rel.replace("/", "_"))
            (env["artifact_dir"] / rel).parent.mkdir(parents=True, exist_ok=True)
            (env["artifact_dir"] / rel).write_bytes(b"noise")
            with pytest.raises(AdoptionBlocked) as ei:
                guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                            frozen_root=env["frozen_root"])
            assert "UNDECLARED_ARTIFACT_FILE" in blocked_codes(ei.value)


def test_phase_future_b3_reads_frozen_candidate_and_blocks(tmp_path, monkeypatch) -> None:
    env = build_env(tmp_path)
    frozen_dir = env["frozen_root"] / "frozen" / CAND_ID
    shutil.rmtree(frozen_dir)
    (env["frozen_root"] / "frozen" / f"{CAND_ID}.json").unlink()
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append(a) or {})
    (h.state / "b3_entry.json").write_text(json.dumps(
        {
            "name": NAME,
            "capability_id": env["entry"]["capability_id"],
            "candidate_id": env["entry"]["adoption"]["candidate_id"],
            "candidate_version": env["entry"]["adoption"]["candidate_version"],
            "artifact_digest": env["entry"]["adoption"]["artifact_digest"],
            "seal_digest": env["authority"]["seal_digest"],
        }))
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    assert "MISSING_FROZEN_CANDIDATE" in blocked_codes(ei.value)
    assert calls == []


def test_delete_frozen_record_and_attempt_re_seal_blocks() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        frozen_dir = env["frozen_root"] / "frozen" / CAND_ID
        record = env["frozen_root"] / "frozen" / f"{CAND_ID}.json"
        # partial deletion: record gone, snapshot remains
        record.unlink()
        re_seal = freeze_candidate_dir(env["candidate"], env["frozen_root"],
                                       registry_root=env["registry_root"])
        assert not re_seal["ok"]
        assert "FROZEN_CANDIDATE_INCOMPLETE" in {
            v["code"] for v in re_seal["violations"]}
        # full deletion after references exist
        shutil.rmtree(frozen_dir)
        re_seal = freeze_candidate_dir(env["candidate"], env["frozen_root"],
                                       registry_root=env["registry_root"])
        assert not re_seal["ok"]
        assert "FROZEN_CANDIDATE_DELETED" in {
            v["code"] for v in re_seal["violations"]}


def test_bind_evaluation_conflict_blocks() -> None:
    ev = bind_evaluation(
        base_evaluation(), "cand-a", "sha256:" + "a" * 64, "sha256:" + "s" * 64)
    with pytest.raises(ValueError, match="EVALUATION_BINDING_CONFLICT"):
        bind_evaluation(ev, "cand-a", "sha256:" + "b" * 64, "sha256:" + "s" * 64)


def test_canonical_vs_legacy_digest_mismatch_blocks_runtime() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        # A clean single-file artifact has identical canonical and legacy
        # digests, so use a deliberately different digest to prove the
        # canonical chain never accepts a legacy-bound store.
        legacy = "sha256:" + "0" * 64
        store = json.loads((env["registry_root"] / "adoption_store.json").read_text())
        store["runs"][0]["artifact_digest"] = legacy
        store["candidates"][CAND_ID]["forged_artifact_digest"] = legacy
        (env["registry_root"] / "adoption_store.json").write_text(
            json.dumps(store, indent=2))
        env["entry"]["adoption"]["artifact_digest"] = legacy
        (env["registry_root"] / "F+" / f"{NAME}.json").write_text(
            json.dumps(env["entry"], indent=2))
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_new_candidate_never_falls_back_to_legacy_binding() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        (env["artifact_dir"] / "extra.py").write_text("x=1\n")
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                        frozen_root=env["frozen_root"])
        codes = blocked_codes(ei.value)
        assert "UNDECLARED_ARTIFACT_FILE" in codes
        assert "ARTIFACT_DIGEST_MISMATCH" not in codes


def test_historical_legacy_candidate_still_works() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        registry_root = tmp / "registry"
        registry_root.mkdir(parents=True)
        cand = build_candidate(tmp, new=False)
        evaluation = {"evaluation_id": "run-legacy", "candidate_id": CAND_ID,
                      "verdict": "PASS", "regression": "PASS",
                      "novel_input_test": "PASS", "independent_reuse": "PASS",
                      "evaluated_at": "2026-08-18T01:00:00Z"}
        issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM)
        assert issued["verdict"] == "AUTHORITY_ISSUED"
        entry = promote("F+", NAME, cand, evaluation, registry_root,
                        adoption_authority=issued["authority"])
        guard.mark_promoted(registry_root, entry)
        report = guard.adopt(registry_root, entry, pathlib.Path(entry["artifact_dir"]))
        assert report["verdict"] == "ALLOW"


def test_phase_future_b3_activates_with_frozen_candidate(tmp_path, monkeypatch) -> None:
    env = build_env(tmp_path)
    h = make_harness(tmp_path, env, monkeypatch)
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append(a) or {
        "sandbox_id": "cbx-9b1", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    (h.state / "b3_entry.json").write_text(json.dumps(
        {
            "name": NAME,
            "capability_id": env["entry"]["capability_id"],
            "candidate_id": env["entry"]["adoption"]["candidate_id"],
            "candidate_version": env["entry"]["adoption"]["candidate_version"],
            "artifact_digest": env["entry"]["adoption"]["artifact_digest"],
            "seal_digest": env["authority"]["seal_digest"],
        }))
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    records = rr.load_records(h.records_path)
    assert records[0]["capability_used"] == env["entry"]["capability_id"]


def test_promoted_entry_marks_canonical_identity() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env = build_env(tmp)
        assert env["entry"]["artifact_identity"] == CANONICAL_ARTIFACT_IDENTITY_V1
        record = load_frozen_candidate(env["frozen_root"], CAND_ID)
        assert record["artifact_digest"] == env["entry"]["adoption"]["artifact_digest"]
