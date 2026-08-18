"""Phase 9-D.3 RED tests: O1 runtime object integrity closure.

Contract under test (frozen in Phase 9-D.2):
  E(D) = frozen_root/frozen/<candidate_id>/artifact
  D    = anchored run_request.artifact_digest

  Run Intent A -> publish immutable E(D) -> verify E(D) -> mount E(D)
  -> container observes A, even when the registry live artifact changes.

  Runtime User must not be able to write / rename / replace / symlink /
  chmod / truncate E(D); owner isolation (store owner != runtime user) is
  the security invariant, not `:ro` and not digest naming alone.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from forge.capabilityizer import (  # noqa: E402
    artifact_digest,
    bind_evaluation,
    freeze_candidate_dir,
    verify_frozen,
)
from pilot.adoption_authority import load_store  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402

CONFIRM = {"operator": "test", "confirm": True}
RUNTIME_UID = 65534  # code-level non-owner identity (nobody)


def build_candidate(tmp: pathlib.Path, cand_id: str, name: str, *,
                    main: bytes = b"print('A')\n", version: int = 1) -> pathlib.Path:
    cand = tmp / cand_id
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_bytes(main)
    forged = artifact_digest(art, ["main.py"])
    (cand / "tests" / "t1").mkdir(parents=True)
    (cand / "tests" / "t1" / "data.csv").write_text("id\n")
    (cand / "tests" / "t1" / "expected.json").write_text("{}")
    manifest = {
        "manifest_version": "0.1",
        "capability": {"name": name, "description": "demo", "version": version},
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
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": cand_id, "name": name, "state": "candidate",
         "source_bundle_ids": ["bundle-1"]}, indent=2) + "\n")
    return cand


def base_evaluation(evaluation_id: str) -> dict:
    return {"evaluation_id": evaluation_id, "verdict": "PASS",
            "evaluated_at": "2026-08-18T01:00:00Z"}


def canonical_env(tmp: pathlib.Path, *, cand_id: str, name: str,
                  main: bytes = b"print('A')\n", version: int = 1,
                  family: str = "F+") -> dict:
    state = tmp / "state"
    registry_root = state / "registry"
    frozen_root = state / "frozen_candidates"
    registry_root.mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, cand_id, name, main=main, version=version)
    frozen = freeze_candidate_dir(cand, frozen_root, namespace=family,
                                  registry_root=registry_root)
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation(f"eval-{cand_id}-{name}"),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM,
                             frozen_root=frozen_root)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote(family, name, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"],
                    frozen_root=frozen_root)
    guard.mark_promoted(registry_root, entry)
    store = load_store(registry_root)
    candidate_id = entry["adoption"]["candidate_id"]
    return {
        "state": state,
        "registry_root": registry_root,
        "frozen_root": frozen_root,
        "entry": entry,
        "artifact_dir": pathlib.Path(entry["artifact_dir"]),
        "snapshot": frozen_root / "frozen" / candidate_id / "artifact",
        "identity": {
            "candidate_id": candidate_id,
            "candidate_version": entry["adoption"]["candidate_version"],
            "artifact_digest": entry["adoption"]["artifact_digest"],
            "seal_digest": issued["authority"]["seal_digest"],
        },
        "run_request": store["run_request"],
    }


def mount(env: dict, expected_identity: dict, *, mount_source=None,
          runtime_uid: int = RUNTIME_UID) -> dict:
    return guard.verify_at_mount(
        env["registry_root"], env["entry"], env["snapshot"],
        expected_identity=expected_identity,
        mount_source=mount_source if mount_source is not None else env["snapshot"],
        runtime_uid=runtime_uid)


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def make_harness(tmp: pathlib.Path, env: dict, monkeypatch) -> harness_mod.Harness:
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
        "sandbox_id": "cbx-9d3", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    monkeypatch.setattr(harness_mod.os, "getuid", lambda: RUNTIME_UID)
    return h


def launch_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append(a) or {
        "sandbox_id": "cbx-9d3", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    return calls


def force_writable(path: pathlib.Path) -> None:
    """Store-owner simulation: chmod is an owner-only operation, so this is
    deliberately NOT available to the runtime user under the contract."""
    if path.is_dir():
        os.chmod(path, 0o755)
    else:
        os.chmod(path, 0o644)


def force_writable_tree(path: pathlib.Path) -> None:
    force_writable(path)
    if path.is_dir():
        for p in sorted(path.rglob("*"), reverse=True):
            force_writable(p)


def force_tamper_file(path: pathlib.Path, data: bytes) -> None:
    force_writable(path)
    path.write_bytes(data)


def force_replace_dir(target: pathlib.Path, replacement: pathlib.Path) -> None:
    force_writable(target.parent)
    force_writable_tree(target)
    shutil.rmtree(target)
    shutil.copytree(replacement, target)


# ---------------------------------------------------------------------------
# A. E(D) is created from the trusted Run Intent, not from mutable locators.
# ---------------------------------------------------------------------------

def test_a_snapshot_created_from_run_intent_and_verified(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    assert snap.is_dir()
    assert artifact_digest(snap, ["main.py"]) == env["run_request"]["artifact_digest"]
    report = guard.adopt(env["registry_root"], env["entry"], env["artifact_dir"],
                         frozen_root=env["frozen_root"], runtime_uid=RUNTIME_UID)
    assert report["verdict"] == "ALLOW"
    assert report["verified_artifact_dir"] == str(snap.resolve())
    assert str(env["artifact_dir"].resolve()) != report["verified_artifact_dir"]


# ---------------------------------------------------------------------------
# B. Runtime user cannot modify the published snapshot.
# ---------------------------------------------------------------------------

def test_b_published_snapshot_rejects_all_mutations(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    main = snap / "main.py"
    assert main.stat().st_mode & 0o777 == 0o444
    assert snap.stat().st_mode & 0o777 == 0o555
    assert snap.parent.stat().st_mode & 0o777 == 0o555
    assert snap.parent.parent.stat().st_mode & 0o777 == 0o555
    assert main.stat().st_uid != RUNTIME_UID

    evil = pathlib.Path(tmp_path) / "evil.py"
    evil.write_bytes(b"print('B')\n")
    evil_dir = pathlib.Path(tmp_path) / "evil_dir"
    evil_dir.mkdir()
    (evil_dir / "main.py").write_bytes(b"print('B')\n")

    with pytest.raises(PermissionError):
        main.write_bytes(b"print('B')\n")
    with pytest.raises(PermissionError):
        main.open("ab").write(b"x")
    with pytest.raises(PermissionError):
        os.truncate(main, 0)
    with pytest.raises(PermissionError):
        os.rename(main, snap / "main.py.bak")
    with pytest.raises(PermissionError):
        main.unlink()
    with pytest.raises(PermissionError):
        os.replace(evil, main)
    with pytest.raises(PermissionError):
        os.symlink(evil, snap / "evil.py")
    with pytest.raises(PermissionError):
        os.mkdir(snap / "sub")
    with pytest.raises(PermissionError):
        os.replace(evil_dir, snap)

    # chmod is owner-only; it succeeds for the store owner, which is exactly
    # why owner != runtime user is the invariant, not modes alone.
    os.chmod(main, 0o644)
    os.chmod(main, 0o444)
    codes = {v["code"] for v in guard.execution_snapshot_isolation_violations(
        env["frozen_root"], env["identity"]["candidate_id"],
        runtime_uid=os.getuid())}
    assert "EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED" in codes
    assert guard.execution_snapshot_isolation_violations(
        env["frozen_root"], env["identity"]["candidate_id"],
        runtime_uid=RUNTIME_UID) == []


# ---------------------------------------------------------------------------
# C. Atomic publish: final path is absent until the complete snapshot exists.
# ---------------------------------------------------------------------------

def test_c_atomic_publish_no_partial_snapshot(tmp_path, monkeypatch) -> None:
    from forge import capabilityizer as cap

    tmp = pathlib.Path(tmp_path)
    frozen_root = tmp / "frozen"
    (tmp / "registry").mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, "cand-A", "foo")
    real_replace = cap.os.replace
    calls = []

    def tracked(src, dst):
        calls.append((pathlib.Path(src).name, pathlib.Path(dst)))
        assert not pathlib.Path(dst).exists()
        return real_replace(src, dst)

    monkeypatch.setattr(cap.os, "replace", tracked)
    frozen = freeze_candidate_dir(cand, frozen_root, registry_root=tmp / "registry")
    assert frozen["ok"], frozen
    snap_dir = frozen_root / "frozen" / "cand-A"
    assert snap_dir.is_dir()
    assert any(name.startswith(".") and name.endswith(".tmp")
               for name, _ in calls)
    assert not list((frozen_root / "frozen").glob(".*.tmp"))
    assert artifact_digest(snap_dir / "artifact", ["main.py"]) == \
        frozen["record"]["artifact_digest"]


# ---------------------------------------------------------------------------
# D. Post-publish mutation attempts leave digest(E(D)) == D.
# ---------------------------------------------------------------------------

def test_d_post_publish_mutation_attempts_preserve_digest(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    before = artifact_digest(snap, ["main.py"])
    evil = pathlib.Path(tmp_path) / "evil.py"
    evil.write_bytes(b"print('B')\n")
    with pytest.raises(PermissionError):
        os.replace(evil, snap / "main.py")
    with pytest.raises(PermissionError):
        (snap / "main.py").write_bytes(b"print('B')\n")
    assert artifact_digest(snap, ["main.py"]) == before
    report = mount(env, env["identity"])
    assert report["verdict"] == "ALLOW"
    assert report["artifact_digest"] == before


# ---------------------------------------------------------------------------
# E. Registry artifact A -> B does not change the execution snapshot.
# ---------------------------------------------------------------------------

def test_e_registry_a_to_b_runtime_still_observes_a(tmp_path, monkeypatch) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo",
                        main=b"print('A')\n")
    (env["artifact_dir"] / "main.py").write_bytes(b"print('B')\n")
    h = make_harness(pathlib.Path(tmp_path), env, monkeypatch)
    calls = launch_calls(monkeypatch)
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    mounts = calls[0][1]
    assert pathlib.Path(mounts[0][0]).resolve() == env["snapshot"].resolve()
    records = rr.load_records(h.records_path)
    assert records[0]["treatment"]["digest"] == env["identity"]["artifact_digest"]


# ---------------------------------------------------------------------------
# F-H. Same-path / different-inode, in-place mutation, atomic file replace.
# ---------------------------------------------------------------------------

def test_f_same_path_different_inode_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    evil_dir = pathlib.Path(tmp_path) / "evil_dir"
    evil_dir.mkdir()
    (evil_dir / "main.py").write_bytes(b"print('B')\n")
    with pytest.raises(PermissionError):
        os.replace(evil_dir, snap)
    force_replace_dir(snap, evil_dir)
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_g_in_place_content_mutation_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    main = env["snapshot"] / "main.py"
    with pytest.raises(PermissionError):
        main.write_bytes(b"print('B')\n")
    force_tamper_file(main, b"print('B')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_h_atomic_file_replace_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    main = env["snapshot"] / "main.py"
    evil = pathlib.Path(tmp_path) / "evil.py"
    evil.write_bytes(b"print('B')\n")
    with pytest.raises(PermissionError):
        os.replace(evil, main)
    force_writable(env["snapshot"])
    os.replace(evil, main)
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# I. Symlink attack: snapshot contract forbids symlinks.
# ---------------------------------------------------------------------------

def test_i_symlink_attack_forbidden(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    evil = pathlib.Path(tmp_path) / "evil.py"
    evil.write_bytes(b"print('B')\n")
    assert not any(p.is_symlink() for p in snap.rglob("*"))
    with pytest.raises(PermissionError):
        os.symlink(evil, snap / "evil.py")
    force_writable(snap)
    (snap / "main.py").unlink()
    os.symlink(evil, snap / "main.py")
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# J. Directory replacement rejected.
# ---------------------------------------------------------------------------

def test_j_directory_replacement_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap = env["snapshot"]
    evil_dir = pathlib.Path(tmp_path) / "evil_dir"
    evil_dir.mkdir()
    (evil_dir / "main.py").write_bytes(b"print('B')\n")
    with pytest.raises(PermissionError):
        os.replace(evil_dir, snap)
    force_replace_dir(snap, evil_dir)
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# K. `:ro` is not the invariant; host-side immutability is.
# ---------------------------------------------------------------------------

def test_k_read_only_mount_is_not_the_security_invariant(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    report = mount(env, env["identity"])
    assert report["verified_artifact_dir"] == str(env["snapshot"].resolve())
    force_tamper_file(env["snapshot"] / "main.py", b"print('B')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# L. Digest binding: E(D_A) != E(D_B), Run Intent A cannot resolve E(D_B).
# ---------------------------------------------------------------------------

def test_l_snapshot_digest_binding(tmp_path) -> None:
    tmp = pathlib.Path(tmp_path)
    env_b = canonical_env(tmp, cand_id="cand-B", name="bar",
                          main=b"print('B')\n", family="F+2")
    env_a = canonical_env(tmp, cand_id="cand-A", name="foo",
                          main=b"print('A')\n")
    assert env_a["snapshot"].resolve() != env_b["snapshot"].resolve()
    assert env_a["identity"]["artifact_digest"] != env_b["identity"]["artifact_digest"]
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env_a, env_a["identity"], mount_source=env_b["snapshot"])
    assert "RUNTIME_BINDING_MISMATCH" in blocked_codes(ei.value)
    report = mount(env_a, env_a["identity"])
    assert report["artifact_digest"] == env_a["identity"]["artifact_digest"]


# ---------------------------------------------------------------------------
# M. Missing snapshot: REJECT, never fall back to a mutable locator.
# ---------------------------------------------------------------------------

def test_m_missing_snapshot_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    snap_dir = env["snapshot"].parent
    record = env["frozen_root"] / "frozen" / f"{env['identity']['candidate_id']}.json"
    force_writable(snap_dir.parent)
    force_writable_tree(snap_dir)
    shutil.rmtree(snap_dir)
    record.unlink()
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "MISSING_FROZEN_CANDIDATE" in blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# N. Corrupt snapshot (digest != D): REJECT via full digest recompute.
# ---------------------------------------------------------------------------

def test_n_corrupt_snapshot_rejected(tmp_path) -> None:
    env = canonical_env(pathlib.Path(tmp_path), cand_id="cand-A", name="foo")
    force_tamper_file(env["snapshot"] / "main.py", b"print('B')\n")
    with pytest.raises(AdoptionBlocked) as ei:
        mount(env, env["identity"])
    assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


# ---------------------------------------------------------------------------
# O. Rebuild -> immediate tamper blocked -> ALLOW A only when intact.
# ---------------------------------------------------------------------------

def test_o_rebuild_then_tamper(tmp_path) -> None:
    tmp = pathlib.Path(tmp_path)
    frozen_root = tmp / "frozen"
    cand = build_candidate(tmp, "cand-A", "foo", main=b"print('A')\n")
    frozen = freeze_candidate_dir(cand, frozen_root)
    assert frozen["ok"], frozen
    snap = frozen_root / "frozen" / "cand-A" / "artifact"
    with pytest.raises(PermissionError):
        (snap / "main.py").write_bytes(b"print('B')\n")
    check = verify_frozen(frozen_root, "cand-A")
    assert check["ok"], check
    force_tamper_file(snap / "main.py", b"print('B')\n")
    check = verify_frozen(frozen_root, "cand-A")
    assert not check["ok"]
    assert any(v["code"] == "ARTIFACT_DIGEST_MISMATCH"
               for v in check["violations"])
