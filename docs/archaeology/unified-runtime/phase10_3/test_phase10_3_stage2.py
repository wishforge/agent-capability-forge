"""Phase 10.3 Stage 2 tests: Managed Agent Version Lifecycle State Machine
(Upgrade / Rollback / Revoke).

These tests validate state-machine semantics only. Versions are seeded
directly (seed_version) because the production multi-version publish path
(create_version -> registry.promote -> authority -> anchored run_request)
is MIGRATION_REQUIRED; passing here is not a production-live upgrade proof.

Contract under test (managed-agent-runtime-v1.md §11-13, §18-19):
  U1: v1 RUNNING -> upgrade v2 -> v2 RUNNING, old STOPPED, new bound to E(D2)
  U2: upgrade v2 -> v2 -> NO-OP; repeated upgrade -> one active instance
  U3: upgrade unknown / revoked / snapshot mismatch -> REJECT (stable codes)
  R1: v2 RUNNING -> rollback v1 -> v1 RUNNING
  R2: rollback idempotent -> one active instance
  R3: rollback missing snapshot / revoked target -> REJECT
  V1: revoke STOPPED -> REVOKED terminal
  V2: revoke RUNNING -> STOPPING -> STOPPED -> REVOKED
  V3: revoke idempotent (x3) -> one revocation event
  V4: new start after revoke -> REJECT
  F1: upgrade start failure -> desired=v2 / observed=FAILED (no auto rollback)
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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from pilot.managed_runtime import (  # noqa: E402
    ManagedRuntimeError,
    create_deployment,
    create_version,
    get_deployment,
    get_runtime_instances,
    get_runtime_status,
    reconcile,
    revoke_version,
    rollback,
    set_desired_state,
    upgrade,
    _stop,
)
from test_phase10_3_stage1 import (  # noqa: E402
    FakeRuntime,
    canonical_env,
    seed_version,
)


def _running_v1(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt = FakeRuntime()
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY"
    old = get_runtime_instances(env["state_root"], dep["deployment_id"])[0]
    return env, v1, dep, rt, old


def _v2_running(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY", report
    return env, v1, v2, dep, rt


def _active_count(env, dep):
    return len([i for i in get_runtime_instances(env["state_root"], dep["deployment_id"])
                if i["observed_state"] in ("READY", "STARTING", "RUNNING", "STOPPING")])


def _rm_readonly(path: pathlib.Path) -> None:
    # Frozen candidates are chmod read-only (owner isolation); make the tree
    # writable before removing it in the tamper test.
    for root, _dirs, _files in os.walk(path):
        os.chmod(root, 0o700)
    os.chmod(path.parent, 0o700)
    shutil.rmtree(path)


def test_upgrade_v1_running_to_v2(tmp_path):
    env, v1, dep, rt, old = _running_v1(tmp_path)
    v2 = seed_version(env)
    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["diff"] == "UPGRADE"
    assert report["verdict"] == "HEALTHY"
    dep2 = get_deployment(env["state_root"], dep["deployment_id"])
    assert dep2["version_id"] == v2["version_id"]
    assert dep2["desired_state"] == "RUNNING"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 2
    assert instances[0]["instance_id"] == old["instance_id"]
    assert instances[0]["observed_state"] == "STOPPED"
    assert instances[1]["version_id"] == v2["version_id"]
    assert instances[1]["observed_state"] == "RUNNING"
    assert instances[1]["execution_snapshot_identity"] == \
        v2["execution_snapshot_identity"]
    assert _active_count(env, dep) == 1
    status = get_runtime_status(env["state_root"], instances[1]["instance_id"])
    assert status["version_drift"] is False
    assert status["snapshot_binding"] == "OK"
    assert rt.starts == [old["instance_id"], instances[1]["instance_id"]]


def test_upgrade_idempotent_and_same_version_noop(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    first = upgrade(env["state_root"], dep["deployment_id"],
                    v2["version_id"], runtime=rt)
    assert first["diff"] == "UPGRADE"
    second = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert second["diff"] == "NO-OP"
    assert second["verdict"] == "HEALTHY"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 2
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 1
    assert rt.starts == [instances[0]["instance_id"], instances[1]["instance_id"]]


def test_upgrade_unknown_version_rejects(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    with pytest.raises(ManagedRuntimeError) as exc:
        upgrade(env["state_root"], dep["deployment_id"], "v999", runtime=rt)
    assert exc.value.code == "VERSION_NOT_FOUND"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v1["version_id"]
    assert len(get_runtime_instances(env["state_root"], dep["deployment_id"])) == 1


def test_upgrade_revoked_version_rejects(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    revoke_version(env["state_root"], env["registry_root"], v2["version_id"],
                   issuer_id="test", reason="stage2")
    with pytest.raises(ManagedRuntimeError) as exc:
        upgrade(env["state_root"], dep["deployment_id"],
                v2["version_id"], runtime=rt)
    assert exc.value.code == "VERSION_REVOKED"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v1["version_id"]
    assert len(get_runtime_instances(env["state_root"], dep["deployment_id"])) == 1


def test_upgrade_snapshot_binding_mismatch_rejects(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    path = env["state_root"] / "versions.jsonl"
    bad = dict(v2)
    bad["event"] = "version_tampered"
    bad["execution_snapshot_identity"] = "snap-deadbeef"
    with path.open("a") as fh:
        fh.write(json.dumps(bad, sort_keys=True) + "\n")
    with pytest.raises(ManagedRuntimeError) as exc:
        upgrade(env["state_root"], dep["deployment_id"],
                v2["version_id"], runtime=rt)
    assert exc.value.code == "SNAPSHOT_BINDING_MISMATCH"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v1["version_id"]


def test_upgrade_snapshot_corrupted_rejects(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    _rm_readonly(env["frozen_root"] / "frozen" / v2["candidate_id"])
    with pytest.raises(ManagedRuntimeError) as exc:
        upgrade(env["state_root"], dep["deployment_id"],
                v2["version_id"], runtime=rt)
    assert exc.value.code == "SNAPSHOT_INVALID"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v1["version_id"]


def test_rollback_v2_to_v1(tmp_path):
    env, v1, v2, dep, rt = _v2_running(tmp_path)
    report = rollback(env["state_root"], dep["deployment_id"],
                      v1["version_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY"
    dep1 = get_deployment(env["state_root"], dep["deployment_id"])
    assert dep1["version_id"] == v1["version_id"]
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 3
    assert instances[-1]["version_id"] == v1["version_id"]
    assert instances[-1]["observed_state"] == "RUNNING"
    assert instances[-1]["execution_snapshot_identity"] == \
        v1["execution_snapshot_identity"]
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 1
    status = get_runtime_status(env["state_root"], instances[-1]["instance_id"])
    assert status["version_drift"] is False


def test_rollback_idempotent(tmp_path):
    env, v1, v2, dep, rt = _v2_running(tmp_path)
    first = rollback(env["state_root"], dep["deployment_id"],
                     v1["version_id"], runtime=rt)
    assert first["diff"] == "UPGRADE"
    second = rollback(env["state_root"], dep["deployment_id"],
                      v1["version_id"], runtime=rt)
    assert second["diff"] == "NO-OP"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 3
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 1


def test_rollback_missing_snapshot_rejects(tmp_path):
    env, v1, v2, dep, rt = _v2_running(tmp_path)
    _rm_readonly(env["frozen_root"] / "frozen" / v1["candidate_id"])
    with pytest.raises(ManagedRuntimeError) as exc:
        rollback(env["state_root"], dep["deployment_id"],
                 v1["version_id"], runtime=rt)
    assert exc.value.code == "SNAPSHOT_INVALID"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v2["version_id"]


def test_rollback_revoked_target_rejects(tmp_path):
    env, v1, v2, dep, rt = _v2_running(tmp_path)
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    with pytest.raises(ManagedRuntimeError) as exc:
        rollback(env["state_root"], dep["deployment_id"],
                 v1["version_id"], runtime=rt)
    assert exc.value.code == "VERSION_REVOKED"
    assert get_deployment(env["state_root"], dep["deployment_id"])["version_id"] == \
        v2["version_id"]


def test_revoke_stopped_instance_reaches_revoked(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt = FakeRuntime()
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instance = get_runtime_instances(env["state_root"], dep["deployment_id"])[0]
    set_desired_state(env["state_root"], dep["deployment_id"], "STOPPED")
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert get_runtime_status(env["state_root"], instance["instance_id"])[
        "observed_state"] == "STOPPED"
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "REVOKE"
    assert report["verdict"] == "REVOKED"
    assert get_runtime_status(env["state_root"], instance["instance_id"])[
        "observed_state"] == "REVOKED"


def test_revoke_running_instance_transitions(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt = FakeRuntime()
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instance = get_runtime_instances(env["state_root"], dep["deployment_id"])[0]
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "REVOKED"
    events = []
    for line in (env["state_root"] / "instances.jsonl").read_text().splitlines():
        rec = json.loads(line)
        if rec["instance_id"] == instance["instance_id"]:
            events.append((rec["event"], rec["observed_state"]))
    states = [state for _event, state in events]
    assert states.index("STOPPING") < states.index("STOPPED") < states.index("REVOKED")
    assert events[-1] == ("instance_revoked", "REVOKED")
    assert rt.stops == [instance["instance_id"]]


def test_revoke_idempotent(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    create_deployment(env["state_root"], v1["agent_id"],
                      v1["version_id"], "STOPPED")
    a = revoke_version(env["state_root"], env["registry_root"],
                       v1["version_id"], issuer_id="test", reason="stage2")
    b = revoke_version(env["state_root"], env["registry_root"],
                       v1["version_id"], issuer_id="test", reason="again")
    c = revoke_version(env["state_root"], env["registry_root"],
                       v1["version_id"], issuer_id="test", reason="again2")
    assert a == b == c
    revoked = 0
    for line in (env["state_root"] / "versions.jsonl").read_text().splitlines():
        rec = json.loads(line)
        if rec.get("version_id") == v1["version_id"] \
                and rec.get("event") == "version_revoked":
            revoked += 1
    assert revoked == 1


def test_revoked_version_blocks_new_start(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    assert get_deployment(env["state_root"], dep["deployment_id"])[
        "desired_state"] == "REVOKED"
    with pytest.raises(ManagedRuntimeError) as exc:
        set_desired_state(env["state_root"], dep["deployment_id"], "RUNNING")
    assert exc.value.code == "REVOKED_TERMINAL"
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=FakeRuntime())
    assert report["verdict"] == "REVOKED"
    assert get_runtime_instances(env["state_root"], dep["deployment_id"]) == []


def test_start_after_revoke_is_rejected(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    dep = create_deployment(env["state_root"], v1["agent_id"],
                            v1["version_id"], "RUNNING")
    rt = FakeRuntime()
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "REJECT"
    assert rt.starts == []
    assert get_runtime_instances(env["state_root"], dep["deployment_id"]) == []


def test_upgrade_failure_keeps_desired_target_and_observed_failed(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    rt.start_result = "FAILED"
    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["verdict"] == "FAILED"
    dep2 = get_deployment(env["state_root"], dep["deployment_id"])
    assert dep2["version_id"] == v2["version_id"]  # no implicit auto-rollback
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert instances[0]["observed_state"] == "STOPPED"
    assert instances[1]["observed_state"] == "FAILED"
    assert instances[1]["version_id"] == v2["version_id"]
    rt.start_result = "RUNNING"
    retry = reconcile(env["state_root"], dep2["deployment_id"], runtime=rt)
    assert retry["verdict"] == "HEALTHY"
    status = get_runtime_status(env["state_root"], instances[1]["instance_id"])
    assert status["observed_state"] == "RUNNING"


def test_failed_stop_blocks_upgrade(tmp_path):
    env, v1, dep, rt, old = _running_v1(tmp_path)
    v2 = seed_version(env)
    rt.stop_result = "FAILED"
    report = upgrade(env["state_root"], dep["deployment_id"],
                     v2["version_id"], runtime=rt)
    assert report["verdict"] == "RECONCILE_REQUIRED"
    assert get_deployment(env["state_root"], dep["deployment_id"])[
        "version_id"] == v2["version_id"]
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 1
    assert instances[0]["instance_id"] == old["instance_id"]
    assert instances[0]["version_id"] == v1["version_id"]
    assert instances[0]["observed_state"] == "FAILED"
    assert rt.starts == [old["instance_id"]]  # v2 not started
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 0


def test_next_reconcile_after_failed_stop_blocks_again(tmp_path):
    env, v1, dep, rt, old = _running_v1(tmp_path)
    v2 = seed_version(env)
    rt.stop_result = "FAILED"
    first = upgrade(env["state_root"], dep["deployment_id"],
                    v2["version_id"], runtime=rt)
    assert first["verdict"] == "RECONCILE_REQUIRED"
    rt.stop_result = "STOPPED"
    second = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert second["verdict"] == "RECONCILE_REQUIRED"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 1
    assert instances[0]["observed_state"] == "FAILED"
    assert instances[0]["version_id"] == v1["version_id"]
    assert rt.starts == [old["instance_id"]]  # v2 not started
    assert rt.stops == [old["instance_id"]]  # stop not retried by reconcile


def test_confirmed_stopped_allows_target_start(tmp_path):
    env, v1, dep, rt, _old = _running_v1(tmp_path)
    v2 = seed_version(env)
    rt.stop_result = "FAILED"
    upgrade(env["state_root"], dep["deployment_id"],
            v2["version_id"], runtime=rt)
    failed = get_runtime_instances(env["state_root"], dep["deployment_id"])[-1]
    assert failed["observed_state"] == "FAILED"
    rt.stop_result = "STOPPED"
    stopped, ok = _stop(env["state_root"], failed, rt)
    assert ok
    assert stopped["observed_state"] == "STOPPED"
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert instances[0]["observed_state"] == "STOPPED"
    assert instances[0]["version_id"] == v1["version_id"]
    assert instances[-1]["version_id"] == v2["version_id"]
    assert instances[-1]["observed_state"] == "RUNNING"
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 1


def test_at_most_one_running_instance_through_failed_stop(tmp_path):
    env, v1, dep, rt, old = _running_v1(tmp_path)
    v2 = seed_version(env)
    rt.stop_result = "FAILED"
    for _ in range(2):
        upgrade(env["state_root"], dep["deployment_id"],
                v2["version_id"], runtime=rt)
        reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
        instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
        assert len([i for i in instances if i["observed_state"] == "RUNNING"]) <= 1
    failed = get_runtime_instances(env["state_root"], dep["deployment_id"])[-1]
    assert failed["observed_state"] == "FAILED"
    rt.stop_result = "STOPPED"
    _stop(env["state_root"], failed, rt)
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "HEALTHY"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len([i for i in instances if i["observed_state"] == "RUNNING"]) == 1
    assert rt.starts == [old["instance_id"], instances[-1]["instance_id"]]


def test_upgrade_rollback_preserve_version_immutability(tmp_path):
    env, v1, v2, dep, rt = _v2_running(tmp_path)
    path = env["state_root"] / "versions.jsonl"
    before = [json.loads(line) for line in path.read_text().splitlines()
              if line.strip()]
    rollback(env["state_root"], dep["deployment_id"], v1["version_id"], runtime=rt)
    upgrade(env["state_root"], dep["deployment_id"], v2["version_id"], runtime=rt)
    after = [json.loads(line) for line in path.read_text().splitlines()
             if line.strip()]
    assert before == after


def test_version_state_stays_active_revoked(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    revoke_version(env["state_root"], env["registry_root"], v1["version_id"],
                   issuer_id="test", reason="stage2")
    states = {json.loads(line)["state"]
              for line in (env["state_root"] / "versions.jsonl").read_text().splitlines()
              if line.strip()}
    assert states <= {"ACTIVE", "REVOKED"}
