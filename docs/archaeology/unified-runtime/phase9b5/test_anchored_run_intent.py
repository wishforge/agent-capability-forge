"""Phase 9-B.5 RED tests: anchored Run Intent (O2 Option A).

Contract under test:
  RUN_INTENT_OWNER   = anchored adoption_store["run_request"]
  B3_ENTRY_ROLE      = derived cache / locator (never security authority)

  Run Intent = A, Registry = B, b3_entry = B  -> REJECT (RUN_REQUEST_CACHE_MISMATCH)
  Run Intent = A, b3_entry missing            -> rebuild from A -> ALLOW A
  Run Intent = A, b3_entry partial mismatch   -> REJECT (RUN_REQUEST_CACHE_MISMATCH)
  Run Intent A tampered to B after sealing     -> INTEGRITY_STORE_CORRUPTED
  Rebuild result tampered before use           -> REJECT
  Canonical candidate with missing run_request -> MISSING_RUN_REQUEST (no inference)
  Legacy candidate                            -> legacy path unchanged (ALLOW)
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
    artifact_digest,
    bind_evaluation,
    freeze_candidate_dir,
)
from pilot.adoption_authority import load_store, seal_trust_anchor  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402

CONFIRM = {"operator": "test", "confirm": True}
CACHE_FIELDS = ("name", "candidate_id", "candidate_version",
                "artifact_digest", "seal_digest")


def build_candidate(tmp: pathlib.Path, cand_id: str, name: str, *,
                    main: bytes = b"print('A')\n", version: int = 1,
                    new: bool = True) -> pathlib.Path:
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
    meta = {"candidate_id": cand_id, "name": name, "state": "candidate"}
    if new:
        meta["source_bundle_ids"] = ["bundle-1"]
    (cand / "candidate.json").write_text(json.dumps(meta, indent=2) + "\n")
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
    assert isinstance(store.get("run_request"), dict), store.get("run_request")
    return {
        "state": state,
        "registry_root": registry_root,
        "frozen_root": frozen_root,
        "entry": entry,
        "artifact_dir": pathlib.Path(entry["artifact_dir"]),
        "snapshot": frozen_root / "frozen" / entry["adoption"]["candidate_id"]
        / "artifact",
        "identity": {
            "candidate_id": entry["adoption"]["candidate_id"],
            "candidate_version": entry["adoption"]["candidate_version"],
            "artifact_digest": entry["adoption"]["artifact_digest"],
            "seal_digest": issued["authority"]["seal_digest"],
        },
        "run_request": store["run_request"],
    }


def legacy_env(tmp: pathlib.Path, *, name: str = "legacy-cap") -> dict:
    state = tmp / "state"
    registry_root = state / "registry"
    registry_root.mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, "cand-legacy", name, main=b"print('legacy')\n",
                           new=False)
    evaluation = {"evaluation_id": "eval-legacy", "candidate_id": "cand-legacy",
                  "verdict": "PASS", "regression": "PASS",
                  "novel_input_test": "PASS", "independent_reuse": "PASS",
                  "evaluated_at": "2026-08-18T01:00:00Z"}
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote("F+", name, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"])
    guard.mark_promoted(registry_root, entry)
    return {
        "state": state,
        "registry_root": registry_root,
        "entry": entry,
        "artifact_dir": pathlib.Path(entry["artifact_dir"]),
    }


def cache_for(env: dict, name: str | None = None) -> dict:
    return {
        "name": name or env["entry"]["name"],
        "capability_id": env["entry"]["capability_id"],
        "candidate_id": env["identity"]["candidate_id"],
        "candidate_version": env["identity"]["candidate_version"],
        "artifact_digest": env["identity"]["artifact_digest"],
        "seal_digest": env["identity"]["seal_digest"],
    }


def stage_entry(env: dict, other: dict) -> None:
    """Copy other's registry entry under env's family/name path."""
    path = env["registry_root"] / "F+" / f"{other['entry']['name']}.json"
    path.write_text(json.dumps(other["entry"], indent=2) + "\n")


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
        "sandbox_id": "cbx-9b5", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    monkeypatch.setattr(harness_mod.os, "getuid", lambda: 65534)
    return h


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def write_cache(env: dict, cache: dict) -> None:
    (env["state"] / "b3_entry.json").write_text(json.dumps(cache, indent=2) + "\n")


def delete_cache(env: dict) -> None:
    (env["state"] / "b3_entry.json").unlink(missing_ok=True)


def launch_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append(a) or {
        "sandbox_id": "cbx-9b5", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    return calls


# --------------------------------------------------------------------------
# A/F: whole b3_entry swap (with registry also swapped) must REJECT.
# --------------------------------------------------------------------------

def test_a_whole_b3_entry_swap_rejected(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env_b = canonical_env(tmp, cand_id="cand-B", name="bar",
                          main=b"print('B')\n", family="F+2")
    env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
    stage_entry(env_a, env_b)
    write_cache(env_a, cache_for(env_b))
    h = make_harness(tmp, env_a, monkeypatch)
    calls = launch_calls(monkeypatch)
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    assert "RUN_REQUEST_CACHE_MISMATCH" in blocked_codes(ei.value)
    assert calls == []


def test_f_registry_and_b3_swap_rejected_while_intent_a(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env_b = canonical_env(tmp, cand_id="cand-B", name="bar",
                          main=b"print('B')\n", family="F+2")
    env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
    stage_entry(env_a, env_b)
    write_cache(env_a, cache_for(env_b))
    h = make_harness(tmp, env_a, monkeypatch)
    calls = launch_calls(monkeypatch)
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    codes = blocked_codes(ei.value)
    assert "RUN_REQUEST_CACHE_MISMATCH" in codes
    assert "CANDIDATE_ID_MISMATCH" not in codes
    assert calls == []


# --------------------------------------------------------------------------
# B/G: b3_entry deletion -> rebuild from anchored Run Intent, ALLOW A.
# --------------------------------------------------------------------------

def test_b_b3_entry_deletion_rebuilds_from_run_intent(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    write_cache(env, cache_for(env))
    delete_cache(env)
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    assert any(str(m[0]) == str(env["snapshot"]) for m in calls[0][1])
    rebuilt = json.loads((env["state"] / "b3_entry.json").read_text())
    assert rebuilt["candidate_id"] == "cand-A"
    assert rebuilt["artifact_digest"] == env["identity"]["artifact_digest"]
    assert rebuilt["seal_digest"] == env["identity"]["seal_digest"]
    records = rr.load_records(h.records_path)
    assert records[0]["capability_used"] == env["entry"]["capability_id"]


def test_g_b3_entry_deleted_after_sealing_rebuilds(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    assert seal_trust_anchor(env["registry_root"]) is None
    write_cache(env, cache_for(env))
    delete_cache(env)
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    h.phase_future("b3")
    assert len(calls) == 1
    rebuilt = json.loads((env["state"] / "b3_entry.json").read_text())
    assert rebuilt["candidate_id"] == "cand-A"


# --------------------------------------------------------------------------
# C: partial cache mismatch -> RUN_REQUEST_CACHE_MISMATCH.
# --------------------------------------------------------------------------

def test_c_partial_cache_mismatch_rejected(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
    env_b = canonical_env(tmp, cand_id="cand-B", name="bar",
                          main=b"print('B')\n", family="F+2")
    stage_entry(env_a, env_b)
    for field in CACHE_FIELDS:
        cache = cache_for(env_a)
        cache[field] = cache_for(env_b)[field]
        write_cache(env_a, cache)
        h = make_harness(tmp, env_a, monkeypatch)
        calls = launch_calls(monkeypatch)
        with pytest.raises(AdoptionBlocked) as ei:
            h.phase_future("b3")
        assert "RUN_REQUEST_CACHE_MISMATCH" in blocked_codes(ei.value), field
        assert calls == [], field


# --------------------------------------------------------------------------
# D: sealed run_request tamper -> INTEGRITY_STORE_CORRUPTED first.
# --------------------------------------------------------------------------

def test_d_sealed_run_request_tamper_rejected(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    assert seal_trust_anchor(env["registry_root"]) is None
    store_path = env["registry_root"] / "adoption_store.json"
    store = json.loads(store_path.read_text())
    store["run_request"]["candidate_id"] = "cand-B"
    store_path.write_text(json.dumps(store, indent=2) + "\n")
    write_cache(env, cache_for(env))
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    codes = blocked_codes(ei.value)
    assert "INTEGRITY_STORE_CORRUPTED" in codes
    assert "RUN_REQUEST_CACHE_MISMATCH" not in codes
    assert calls == []


# --------------------------------------------------------------------------
# E: positive canonical run ALLOW A.
# --------------------------------------------------------------------------

def test_e_positive_canonical_run_allows_a(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    write_cache(env, cache_for(env))
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    assert any(str(m[0]) == str(env["snapshot"]) for m in calls[0][1])
    records = rr.load_records(h.records_path)
    assert records[0]["capability_used"] == env["entry"]["capability_id"]


# --------------------------------------------------------------------------
# H: rebuild result tampered before use -> REJECT, never ALLOW B.
# --------------------------------------------------------------------------

def test_h_rebuilt_cache_tampered_before_use_rejected(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    write_cache(env, cache_for(env))
    delete_cache(env)
    bogus = cache_for(env)
    bogus["candidate_id"] = "cand-B"
    bogus["seal_digest"] = "sha256:" + "b" * 64
    orig_write = pathlib.Path.write_text

    def tampered_write(self, data, *args, **kwargs):
        if str(self).endswith("b3_entry.json"):
            data = json.dumps(bogus, indent=2)
        return orig_write(self, data, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", tampered_write)
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    assert "RUN_REQUEST_CACHE_MISMATCH" in blocked_codes(ei.value)
    assert calls == []


# --------------------------------------------------------------------------
# I: legacy path stays legacy (no run_request required).
# --------------------------------------------------------------------------

def test_i_legacy_compatibility_unchanged(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = legacy_env(tmp)
    write_cache(env, {"name": env["entry"]["name"],
                      "capability_id": env["entry"]["capability_id"]})
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    assert any(str(m[0]) == str(env["artifact_dir"]) for m in calls[0][1])


# --------------------------------------------------------------------------
# J: canonical candidate must not infer intent from b3_entry/registry.
# --------------------------------------------------------------------------

def test_j_missing_run_request_rejected(tmp_path, monkeypatch) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    store_path = env["registry_root"] / "adoption_store.json"
    store = json.loads(store_path.read_text())
    del store["run_request"]
    store_path.write_text(json.dumps(store, indent=2) + "\n")
    write_cache(env, cache_for(env))
    h = make_harness(tmp, env, monkeypatch)
    calls = launch_calls(monkeypatch)
    with pytest.raises(AdoptionBlocked) as ei:
        h.phase_future("b3")
    assert "MISSING_RUN_REQUEST" in blocked_codes(ei.value)
    assert calls == []


# --------------------------------------------------------------------------
# Rebuild equality + cache helper contracts (guard-level).
# --------------------------------------------------------------------------

def test_rebuild_writes_derived_cache_equal_to_run_request(tmp_path) -> None:
    tmp = pathlib.Path(tmp_path)
    env = canonical_env(tmp, cand_id="cand-A", name="foo")
    cache_path = env["state"] / "b3_entry.json"
    cache = guard.resolve_b3_cache(cache_path, env["run_request"])
    assert cache["name"] == env["run_request"]["name"]
    assert cache["candidate_id"] == env["run_request"]["candidate_id"]
    assert cache["candidate_version"] == env["run_request"]["candidate_version"]
    assert cache["artifact_digest"] == env["run_request"]["artifact_digest"]
    assert cache["seal_digest"] == env["run_request"]["seal_digest"]


def test_cache_mismatch_code_semantics() -> None:
    req = {"name": "foo", "candidate_id": "cand-A", "candidate_version": "v1",
           "artifact_digest": "sha256:" + "a" * 64,
           "seal_digest": "sha256:" + "s" * 64}
    cache = dict(req, candidate_id="cand-B")
    violations = guard.run_request_cache_violations(req, cache)
    assert [v["code"] for v in violations] == ["RUN_REQUEST_CACHE_MISMATCH"]
