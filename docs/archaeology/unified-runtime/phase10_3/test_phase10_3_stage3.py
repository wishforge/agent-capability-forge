"""Phase 10.3 Stage 3 RED/GREEN tests: Canonical Multi-Version Implementation.

Production-reachable proof (NOT seed_version):
    create_version -> promote(version entry) -> authority -> run intent
    -> snapshot E(D) -> deployment -> reconcile -> Runtime vN

Contract under test (docs/architecture/managed-agent-multi-version-v1.md):
  L1: same Agent may hold v1 + v2 registry version entries (write-once each)
  L2: adoption_store.run_requests[capability_id|candidate_version] coexist
  L3: consumers resolve the version-specific Run Intent, never a global one
  L4: v1/v2 share one stable capability_id (Agent identity)
  Upgrade / Rollback / Revoke(v2) are production-reachable.
  Adversarial A-H all fail closed.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from forge.capabilityizer import bind_evaluation, freeze_candidate_dir  # noqa: E402
from pilot.adoption_authority import load_store  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
import pilot.registry as registry  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
from pilot.managed_runtime import (  # noqa: E402
    DockerRuntime,
    ManagedRuntimeError,
    create_deployment,
    create_version,
    get_deployment,
    get_runtime_instances,
    reconcile,
    revoke_version,
    rollback,
    upgrade,
)
from test_phase10_3_stage1 import (  # noqa: E402
    CONFIRM,
    NAME,
    FakeRuntime,
    base_evaluation,
    build_candidate,
    canonical_env,
    seed_version,
)
from test_phase10_3_stage2 import _rm_readonly  # noqa: E402

import pilot.harness as harness_mod  # noqa: E402
import pilot.run_record as rr  # noqa: E402


def _snapshot(env, candidate_id) -> pathlib.Path:
    return pathlib.Path(env["frozen_root"]) / "frozen" / candidate_id / "artifact"


def publish(env, tmp: pathlib.Path, cand_id: str, *, version: int,
            main: bytes = b"print('B')\n", name: str = NAME) -> dict:
    """Real production publish chain for one AgentVersion."""
    cand = build_candidate(tmp, cand_id, name, main=main, version=version)
    frozen = freeze_candidate_dir(cand, env["frozen_root"], namespace="F+",
                                  registry_root=env["registry_root"])
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation(f"eval-{cand_id}"),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(env["registry_root"], cand, evaluation,
                             confirm=CONFIRM, frozen_root=env["frozen_root"])
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote("F+", name, cand, evaluation, env["registry_root"],
                    adoption_authority=issued["authority"],
                    frozen_root=env["frozen_root"])
    guard.mark_promoted(env["registry_root"], entry)
    version_rec = create_version(env["state_root"], env["registry_root"],
                                 env["frozen_root"],
                                 frozen["record"]["candidate_id"])
    return {"entry": entry, "authority": issued["authority"],
            "version": version_rec, "frozen": frozen["record"]}


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class DockerProc:
    """subprocess.run stand-in: records mount sources, never talks to Docker."""

    def __init__(self):
        self.mounts: list[str] = []
        self.kills: list[str] = []

    def __call__(self, args, **kwargs):
        if args[:2] == ["docker", "run"]:
            for i, arg in enumerate(args):
                if arg == "-v" and i + 1 < len(args) and "/artifact:ro" in args[i + 1]:
                    self.mounts.append(args[i + 1].split(":")[0])
            return FakeProc(0)
        if args[:2] == ["docker", "inspect"]:
            return FakeProc(0, "true\n")
        if args[:2] == ["docker", "kill"]:
            self.kills.append(args[2])
            return FakeProc(0)
        if args[:2] == ["docker", "rm"]:
            return FakeProc(0)
        return FakeProc(1, stderr="unexpected docker command")


def docker_runtime(env, monkeypatch) -> tuple[DockerRuntime, DockerProc]:
    proc = DockerProc()
    monkeypatch.setattr("pilot.managed_runtime.subprocess.run", proc)
    return DockerRuntime(state_root=env["state_root"], runtime_uid=65534), proc


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def make_harness(env, monkeypatch) -> tuple[harness_mod.Harness, list]:
    h = harness_mod.Harness(force=True)
    h.state = env["state_root"].parent
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
    calls = []
    monkeypatch.setattr(harness_mod, "docker_launch", lambda *a, **k: calls.append(a) or {
        "sandbox_id": "cbx-st3", "exit_code": 0, "stdout": "ok", "stderr": "",
        "elapsed_s": 0.1, "timed_out": False})
    monkeypatch.setattr(harness_mod.os, "getuid", lambda: 65534)
    return h, calls


def test_v1_and_v2_publish_allow_and_coexist(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    p2 = publish(env, tmp_path, "cand-st3-v2", version=2,
                 main=b"print('B')\n")
    v2 = p2["version"]

    assert v1["agent_id"] == v2["agent_id"]  # L4 stable capability_id
    assert v1["candidate_version"] == "v1"
    assert v2["candidate_version"] == "v2"
    assert v1["authority_id"] != v2["authority_id"]
    assert v1["artifact_digest"] != v2["artifact_digest"]
    assert v1["execution_snapshot_identity"] != v2["execution_snapshot_identity"]

    e1 = registry.discover_version(env["registry_root"], "F+", NAME, "v1")
    e2 = registry.discover_version(env["registry_root"], "F+", NAME, "v2")
    assert e1 is not None and e2 is not None
    assert e1["capability_id"] == v1["agent_id"] == e2["capability_id"] == v2["agent_id"]
    assert e1["adoption"]["candidate_id"] == v1["candidate_id"]
    assert e2["adoption"]["candidate_id"] == v2["candidate_id"]

    store = load_store(env["registry_root"])
    assert set(store["run_requests"]) == {
        f"{v1['agent_id']}|v1", f"{v2['agent_id']}|v2"}
    # v2 publish never replaced the v1 entry / v1 run intent.
    assert store["run_requests"][f"{v1['agent_id']}|v1"]["candidate_id"] == \
        v1["candidate_id"]


def test_promote_same_version_different_binding_conflicts(tmp_path):
    env = canonical_env(tmp_path)
    cand = build_candidate(tmp_path, "cand-st3-v1b", NAME,
                           main=b"print('A2')\n", version=1)
    frozen = freeze_candidate_dir(cand, env["frozen_root"], namespace="F+",
                                  registry_root=env["registry_root"])
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation("eval-cand-st3-v1b"),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(env["registry_root"], cand, evaluation,
                             confirm=CONFIRM, frozen_root=env["frozen_root"])
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    with pytest.raises(AdoptionBlocked) as exc:
        promote("F+", NAME, cand, evaluation, env["registry_root"],
                adoption_authority=issued["authority"],
                frozen_root=env["frozen_root"])
    assert "ENTRY_BINDING_CONFLICT" in blocked_codes(exc.value)


def test_version_scoped_run_intents_load_independently(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    p2 = publish(env, tmp_path, "cand-st3-v2b", version=2)
    v2 = p2["version"]

    r1 = guard.load_trusted_run_request(
        env["registry_root"], f"{v1['agent_id']}|v1")
    r2 = guard.load_trusted_run_request(
        env["registry_root"], f"{v2['agent_id']}|v2")
    assert r1["candidate_id"] == v1["candidate_id"]
    assert r2["candidate_id"] == v2["candidate_id"]
    assert r1 != r2
    # Legacy alias is a Phase 9 reader mirror (latest intent); version-scoped
    # canonical consumers never read it.
    store = load_store(env["registry_root"])
    assert store["run_request"]["candidate_id"] == v2["candidate_id"]
    with pytest.raises(AdoptionBlocked) as exc:
        guard.load_trusted_run_request(
            env["registry_root"], f"{v1['agent_id']}|v9")
    assert "MISSING_RUN_REQUEST" in blocked_codes(exc.value)


def test_production_upgrade_v2_and_rollback_v1_resolve_own_intent(
        tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt, proc = docker_runtime(env, monkeypatch)

    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY", report
    assert len(proc.mounts) == 1
    assert proc.mounts[0] == str(_snapshot(env, v1["candidate_id"]).resolve())

    v2 = publish(env, tmp_path, "cand-st3-v2c", version=2,
                 main=b"print('C')\n")["version"]
    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["diff"] == "UPGRADE", report
    assert report["verdict"] == "HEALTHY", report
    assert proc.mounts[-1] == str(_snapshot(env, v2["candidate_id"]).resolve())

    report = rollback(env["state_root"], dep["deployment_id"],
                      v1["version_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY", report
    assert proc.mounts[-1] == str(_snapshot(env, v1["candidate_id"]).resolve())
    versions = [i["version_id"] for i in
                get_runtime_instances(env["state_root"], dep["deployment_id"])]
    assert versions == ["v1", "v2", "v1"]
    assert len(proc.kills) == 2


def test_two_deployments_can_coexist_domain(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep1 = create_deployment(env["state_root"], v1["agent_id"],
                             v1["version_id"], "STOPPED")
    v2 = publish(env, tmp_path, "cand-st3-v2d", version=2)["version"]
    dep2 = create_deployment(env["state_root"], v2["agent_id"],
                             v2["version_id"], "STOPPED")
    assert dep1["deployment_id"] != dep2["deployment_id"]
    assert get_deployment(env["state_root"], dep1["deployment_id"])["version_id"] == "v1"
    assert get_deployment(env["state_root"], dep2["deployment_id"])["version_id"] == "v2"


def test_revoke_v2_is_version_scoped_and_v1_stays_valid(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep1 = create_deployment(env["state_root"], v1["agent_id"],
                             v1["version_id"], "RUNNING")
    v2 = publish(env, tmp_path, "cand-st3-v2e", version=2)["version"]
    dep2 = create_deployment(env["state_root"], v2["agent_id"],
                             v2["version_id"], "RUNNING")
    rt = FakeRuntime()
    assert reconcile(env["state_root"], dep1["deployment_id"], runtime=rt)["verdict"] == "HEALTHY"
    assert reconcile(env["state_root"], dep2["deployment_id"], runtime=rt)["verdict"] == "HEALTHY"

    revoke_version(env["state_root"], env["registry_root"], v2["version_id"],
                   agent_id=v2["agent_id"], issuer_id="test", reason="stage3")
    v2_latest = [json.loads(l) for l in
                 (env["state_root"] / "versions.jsonl").read_text().splitlines()
                 if json.loads(l)["version_id"] == "v2"][-1]
    v1_latest = [json.loads(l) for l in
                 (env["state_root"] / "versions.jsonl").read_text().splitlines()
                 if json.loads(l)["version_id"] == "v1"][-1]
    assert v2_latest["state"] == "REVOKED"
    assert v1_latest["state"] == "ACTIVE"

    # H: Deployment -> v2 is REJECT after revoke(v2).
    with pytest.raises(ManagedRuntimeError) as exc:
        upgrade(env["state_root"], dep1["deployment_id"],
                v2["version_id"], runtime=rt)
    assert exc.value.code == "VERSION_REVOKED"
    dep_bad = create_deployment(env["state_root"], v2["agent_id"],
                                v2["version_id"], "RUNNING")
    assert reconcile(env["state_root"], dep_bad["deployment_id"],
                     runtime=rt)["verdict"] == "REJECT"

    # G: Deployment -> v1 is still ALLOW.
    dep1b = create_deployment(env["state_root"], v1["agent_id"],
                              v1["version_id"], "RUNNING")
    report = reconcile(env["state_root"], dep1b["deployment_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY", report


def test_adversarial_deployment_v2_run_intent_v1_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = publish(env, tmp_path, "cand-st3-v2f", version=2)["version"]
    bad = dict(v2, candidate_version="v1")
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-a"}, bad)
    assert res["observed_state"] == "FAILED"
    assert "CANDIDATE_VERSION_MISMATCH" in res["failure_reason"]


def test_adversarial_deployment_v1_run_intent_v2_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    publish(env, tmp_path, "cand-st3-v2g", version=2)
    bad = dict(v1, candidate_version="v2")
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-b"}, bad)
    assert res["observed_state"] == "FAILED"
    assert "CANDIDATE_VERSION_MISMATCH" in res["failure_reason"]


def test_adversarial_v2_run_intent_missing_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = seed_version(env)  # version record without a published run intent
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-c"}, v2)
    assert res["observed_state"] == "FAILED"
    assert "MISSING_RUN_REQUEST" in res["failure_reason"]


def test_adversarial_v2_authority_missing_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = publish(env, tmp_path, "cand-st3-v2h", version=2)["version"]
    (env["registry_root"] / "authorities" / f"{v2['authority_id']}.json").unlink()
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-d"}, v2)
    assert res["observed_state"] == "FAILED"
    assert "UNISSUED_AUTHORITY" in res["failure_reason"]


def test_adversarial_v2_snapshot_missing_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = publish(env, tmp_path, "cand-st3-v2i", version=2)["version"]
    _rm_readonly(env["frozen_root"] / "frozen" / v2["candidate_id"])
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-e"}, v2)
    assert res["observed_state"] == "FAILED"
    assert "FROZEN_CANDIDATE_INCOMPLETE" in res["failure_reason"]


def test_adversarial_v2_snapshot_digest_mismatch_rejected(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = publish(env, tmp_path, "cand-st3-v2j", version=2)["version"]
    main_py = _snapshot(env, v2["candidate_id"]) / "main.py"
    os.chmod(main_py, 0o644)
    main_py.write_bytes(b"print('tampered')\n")
    rt, _proc = docker_runtime(env, monkeypatch)
    res = rt.start({"instance_id": "inst-f"}, v2)
    assert res["observed_state"] == "FAILED"
    assert "ARTIFACT_DIGEST_MISMATCH" in res["failure_reason"]


def test_harness_multiversion_resolves_v2_intent(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    v2 = publish(env, tmp_path, "cand-st3-v2k", version=2)["version"]
    h, calls = make_harness(env, monkeypatch)
    (h.state / "b3_entry.json").write_text(json.dumps({
        "name": NAME,
        "capability_id": v2["agent_id"],
        "candidate_id": v2["candidate_id"],
        "candidate_version": "v2",
        "artifact_digest": v2["artifact_digest"],
        "seal_digest": v2["seal_digest"],
    }, indent=2) + "\n")
    ids = h.phase_future("b3")
    assert len(ids) == 1
    assert len(calls) == 1
    mounts = [m[0] for m in calls[0][1]]
    assert _snapshot(env, v2["candidate_id"]).resolve() in mounts
    records = rr.load_records(h.records_path)
    assert records[0]["capability_used"] == v2["agent_id"]


def test_harness_multiversion_missing_cache_fails_closed(tmp_path, monkeypatch):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    publish(env, tmp_path, "cand-st3-v2l", version=2)
    h, calls = make_harness(env, monkeypatch)
    with pytest.raises(AdoptionBlocked) as exc:
        h.phase_future("b3")
    assert "MISSING_RUN_REQUEST" in blocked_codes(exc.value)
    assert calls == []


NAME_B = "cap-b"


def _versions(env, version_id: str) -> list[dict]:
    return [json.loads(line) for line in
            (env["state_root"] / "versions.jsonl").read_text().splitlines()
            if line.strip() and json.loads(line)["version_id"] == version_id]


def _canonical_env_with_legacy_anchor(tmp_path, *, legacy_id: str) -> dict:
    """Legacy anchor with a minted-style id, then canonical v1 for same agent."""
    registry_root = tmp_path / "state" / "registry"
    legacy = registry_root / "F+" / f"{NAME}.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({
        "schema_version": "experimental_registry_v1",
        "capability_id": legacy_id,
        "name": NAME,
        "version": 1,
        "state": "promoted",
    }, indent=2) + "\n")
    return canonical_env(tmp_path)


def test_agent_a_and_agent_b_v1_both_allow(tmp_path):
    env = canonical_env(tmp_path)
    v1_a = create_version(env["state_root"], env["registry_root"],
                          env["frozen_root"], env["candidate_id"])
    v1_b = publish(env, tmp_path, "cand-st3-agent-b", version=1,
                   main=b"print('B1')\n", name=NAME_B)["version"]

    assert v1_a["version_id"] == v1_b["version_id"] == "v1"
    assert v1_a["agent_id"] != v1_b["agent_id"]
    assert len(_versions(env, "v1")) == 2


def test_same_agent_same_version_same_content_idempotent(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    again = create_version(env["state_root"], env["registry_root"],
                           env["frozen_root"], env["candidate_id"])

    assert again == v1
    assert len(_versions(env, "v1")) == 1  # no duplicate semantic version


def test_same_agent_same_version_different_content_conflicts(tmp_path):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    seed_version(env, cand_id="cand-st3-v1-conflict", version=1,
                 main=b"print('CONFLICT')\n")

    with pytest.raises(ManagedRuntimeError) as exc:
        create_version(env["state_root"], env["registry_root"],
                       env["frozen_root"], env["candidate_id"])
    assert exc.value.code == "VERSION_CONFLICT"


def test_cross_agent_v1_registry_entries_coexist(tmp_path):
    env = canonical_env(tmp_path)
    create_version(env["state_root"], env["registry_root"],
                   env["frozen_root"], env["candidate_id"])
    publish(env, tmp_path, "cand-st3-agent-b2", version=1,
            main=b"print('B1b')\n", name=NAME_B)

    assert (env["registry_root"] / "F+" / NAME / "versions" / "v1.json").exists()
    assert (env["registry_root"] / "F+" / NAME_B / "versions" / "v1.json").exists()


def test_revoke_agent_a_v1_does_not_revoke_agent_b_deployment(tmp_path):
    env = canonical_env(tmp_path)
    v1_a = create_version(env["state_root"], env["registry_root"],
                          env["frozen_root"], env["candidate_id"])
    dep_a = create_deployment(env["state_root"], v1_a["agent_id"],
                              v1_a["version_id"], "RUNNING")
    v1_b = publish(env, tmp_path, "cand-st3-agent-b3", version=1,
                   main=b"print('B1c')\n", name=NAME_B)["version"]
    dep_b = create_deployment(env["state_root"], v1_b["agent_id"],
                              v1_b["version_id"], "RUNNING")

    revoke_version(env["state_root"], env["registry_root"], "v1",
                   agent_id=v1_a["agent_id"], issuer_id="test",
                   reason="stage3 review")

    assert get_deployment(env["state_root"], dep_a["deployment_id"])["desired_state"] == "REVOKED"
    assert get_deployment(env["state_root"], dep_b["deployment_id"])["desired_state"] == "RUNNING"


def test_revoke_agent_a_v1_leaves_agent_b_deployment_runnable(tmp_path):
    env = canonical_env(tmp_path)
    v1_a = create_version(env["state_root"], env["registry_root"],
                          env["frozen_root"], env["candidate_id"])
    dep_a = create_deployment(env["state_root"], v1_a["agent_id"],
                              v1_a["version_id"], "RUNNING")
    v1_b = publish(env, tmp_path, "cand-st3-agent-b4", version=1,
                   main=b"print('B1d')\n", name=NAME_B)["version"]
    dep_b = create_deployment(env["state_root"], v1_b["agent_id"],
                              v1_b["version_id"], "RUNNING")
    rt = FakeRuntime()
    assert reconcile(env["state_root"], dep_a["deployment_id"],
                     runtime=rt)["verdict"] == "HEALTHY"
    assert reconcile(env["state_root"], dep_b["deployment_id"],
                     runtime=rt)["verdict"] == "HEALTHY"

    revoke_version(env["state_root"], env["registry_root"], "v1",
                   agent_id=v1_a["agent_id"], issuer_id="test",
                   reason="stage3 review")

    assert reconcile(env["state_root"], dep_b["deployment_id"],
                     runtime=rt)["verdict"] == "HEALTHY"


def test_legacy_anchor_removal_keeps_capability_id_stable(tmp_path):
    env = _canonical_env_with_legacy_anchor(tmp_path, legacy_id="cap-legacy-anchor")
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    (env["registry_root"] / "F+" / f"{NAME}.json").unlink()
    v2 = publish(env, tmp_path, "cand-st3-v2-legacy", version=2)["version"]

    assert v1["agent_id"] == v2["agent_id"] == "cap-legacy-anchor"
    assert registry.discover_version(env["registry_root"], "F+", NAME,
                                     "v1")["capability_id"] == "cap-legacy-anchor"
    assert registry.discover_version(env["registry_root"], "F+", NAME,
                                     "v2")["capability_id"] == "cap-legacy-anchor"


def test_legacy_anchor_removal_upgrade_no_version_mismatch(tmp_path):
    env = _canonical_env_with_legacy_anchor(tmp_path, legacy_id="cap-legacy-anchor")
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt = FakeRuntime()
    assert reconcile(env["state_root"], dep["deployment_id"],
                     runtime=rt)["verdict"] == "HEALTHY"
    (env["registry_root"] / "F+" / f"{NAME}.json").unlink()
    v2 = publish(env, tmp_path, "cand-st3-v2-legacy-b", version=2)["version"]

    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY", report


def test_a_v1_a_v2_b_v1_identities_isolated(tmp_path):
    env = _canonical_env_with_legacy_anchor(tmp_path, legacy_id="cap-legacy-anchor")
    v1_a = create_version(env["state_root"], env["registry_root"],
                          env["frozen_root"], env["candidate_id"])
    v2_a = publish(env, tmp_path, "cand-st3-v2-legacy-c", version=2)["version"]
    v1_b = publish(env, tmp_path, "cand-st3-agent-b5", version=1,
                   main=b"print('B1e')\n", name=NAME_B)["version"]

    assert v1_a["agent_id"] == v2_a["agent_id"] == "cap-legacy-anchor"
    assert v1_b["agent_id"] != "cap-legacy-anchor"
    assert v1_b["agent_id"] != v1_a["agent_id"]
