"""Phase 10.3 Stage 1 RED tests: Deployment -> Reconcile -> RuntimeInstance
minimal closed loop.

Contract under test (docs/architecture/managed-agent-runtime-v1.md + Phase 10.3):
  A: desired RUNNING + observed STOPPED  -> START -> RUNNING
  B: desired STOPPED + observed RUNNING  -> STOP -> STOPPED (idempotent)
  C: reconcile(RUNNING) x3               -> one active instance
  D: desired v17 + observed v16          -> VERSION_DRIFT (no auto upgrade)
  E: version snapshot mismatch           -> REJECT
  F: revoke                              -> new start REJECT, existing -> REVOKED
  G: start failure                       -> FAILED; bounded retry; exhausted -> ESCALATE
"""

from __future__ import annotations

import json
import pathlib
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
from pilot.adoption_authority import load_store  # noqa: E402
from pilot.adoption_authority import revoke_authority  # noqa: E402
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402
from pilot.managed_runtime import (  # noqa: E402
    START_MAX_ATTEMPTS,
    ManagedRuntimeError,
    create_deployment,
    create_version,
    get_deployment,
    get_runtime_instances,
    get_runtime_status,
    reconcile,
    revoke_version,
    set_desired_state,
)

CONFIRM = {"operator": "test", "confirm": True}
NAME = "cap-x"


class FakeRuntime:
    """Deterministic runtime adapter for state-machine tests (no Docker)."""

    def __init__(self, start="RUNNING", stop="STOPPED"):
        self.start_result = start
        self.stop_result = stop
        self.starts = []
        self.stops = []

    def start(self, instance, version):
        self.starts.append(instance["instance_id"])
        if isinstance(self.start_result, str):
            return {
                "observed_state": self.start_result,
                "failure_reason": None if self.start_result == "RUNNING"
                else "fake start failed",
            }
        return self.start_result(instance, version)

    def stop(self, instance):
        self.stops.append(instance["instance_id"])
        if isinstance(self.stop_result, str):
            return {
                "observed_state": self.stop_result,
                "failure_reason": None if self.stop_result == "STOPPED"
                else "fake stop failed",
            }
        return self.stop_result(instance)


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


def canonical_env(tmp: pathlib.Path, *, cand_id: str = "cand-10.3",
                  name: str = NAME, main: bytes = b"print('A')\n",
                  version: int = 1) -> dict:
    state = tmp / "state"
    registry_root = state / "registry"
    frozen_root = state / "frozen_candidates"
    registry_root.mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, cand_id, name, main=main, version=version)
    frozen = freeze_candidate_dir(cand, frozen_root, namespace="F+",
                                  registry_root=registry_root)
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation(f"eval-{cand_id}"),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM,
                             frozen_root=frozen_root)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote("F+", name, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"],
                    frozen_root=frozen_root)
    guard.mark_promoted(registry_root, entry)
    store = load_store(registry_root)
    candidate_id = entry["adoption"]["candidate_id"]
    return {
        "state_root": state / "managed_runtime",
        "registry_root": registry_root,
        "frozen_root": frozen_root,
        "entry": entry,
        "candidate_id": candidate_id,
        "identity": {
            "candidate_id": candidate_id,
            "candidate_version": entry["adoption"]["candidate_version"],
            "artifact_digest": entry["adoption"]["artifact_digest"],
            "seal_digest": issued["authority"]["seal_digest"],
        },
        "run_request": store["run_request"],
    }


def _simulate_upgrade(state_root: pathlib.Path, deployment: dict,
                      version_id: str) -> None:
    """Directly append a deployment_update event with a new desired version.

    Stage 1 has no upgrade API; this simulates the deferred Phase 10.4
    upgrade mechanism so VERSION_DRIFT detection can be tested.
    """
    event = dict(deployment)
    event["event"] = "deployment_updated"
    event["version_id"] = version_id
    path = state_root / "deployments.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def test_a_desired_running_starts_instance(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime()
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "START"
    assert report["verdict"] == "HEALTHY"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 1
    assert instances[0]["observed_state"] == "RUNNING"
    status = get_runtime_status(env["state_root"], instances[0]["instance_id"])
    assert status["observed_state"] == "RUNNING"
    assert status["version_drift"] is False
    assert status["snapshot_binding"] == "OK"
    assert rt.starts == [instances[0]["instance_id"]]


def test_b_desired_stopped_stops_instance_idempotent(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime()
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instance_id = rt.starts[0]

    dep = set_desired_state(env["state_root"], dep["deployment_id"], "STOPPED")
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "STOP"
    status = get_runtime_status(env["state_root"], instance_id)
    assert status["observed_state"] == "STOPPED"
    assert rt.stops == [instance_id]

    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "NO-OP"
    assert rt.stops == [instance_id]  # no duplicate stop


def test_c_reconcile_running_is_idempotent(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime()
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "NO-OP"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert len(instances) == 1
    assert len(rt.starts) == 1


def test_d_version_drift_is_reported_not_upgraded(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime()
    reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instance = get_runtime_instances(env["state_root"], dep["deployment_id"])[0]

    _simulate_upgrade(env["state_root"], dep, "v2")
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "VERSION_DRIFT"
    assert report["version_drift"] is True
    assert len(rt.starts) == 1  # no auto upgrade / new start
    status = get_runtime_status(env["state_root"], instance["instance_id"])
    assert status["version_drift"] is True
    assert status["desired_version"] == "v2"
    assert status["observed_version"] == version["version_id"]


def test_e_snapshot_mismatch_rejects_start(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    # Tamper the write-once version record (append event with same id,
    # different snapshot identity) to simulate corruption.
    path = env["state_root"] / "versions.jsonl"
    lines = path.read_text().splitlines()
    bad = dict(json.loads(lines[-1]))
    bad["execution_snapshot_identity"] = "snap-deadbeef"
    with path.open("a") as fh:
        fh.write(json.dumps(bad, sort_keys=True) + "\n")

    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime()
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "REJECT"
    assert get_runtime_instances(env["state_root"], dep["deployment_id"]) == []
    assert rt.starts == []


def test_f_revoke_rejects_new_start_and_terminates_running(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    # Authority revoked while deployment still desires RUNNING -> start REJECT.
    res = revoke_authority(env["registry_root"], version["authority_id"],
                           status="REVOKED", issuer_id="test",
                           reason="stage1 test")
    assert res["allowed"] is True
    rt = FakeRuntime()
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "REJECT"
    assert rt.starts == []
    assert get_runtime_instances(env["state_root"], dep["deployment_id"]) == []

    # Existing running instance: revoke must stop immediately and reach REVOKED.
    env2 = canonical_env(tmp_path / "second", cand_id="cand-10.3b")
    v2 = create_version(env2["state_root"], env2["registry_root"],
                        env2["frozen_root"], env2["candidate_id"])
    dep2 = create_deployment(env2["state_root"], v2["agent_id"],
                             v2["version_id"], "RUNNING")
    rt2 = FakeRuntime()
    reconcile(env2["state_root"], dep2["deployment_id"], runtime=rt2)
    instance = get_runtime_instances(env2["state_root"], dep2["deployment_id"])[0]
    revoke_version(env2["state_root"], env2["registry_root"],
                   v2["version_id"], issuer_id="test", reason="stage1 test")
    assert get_deployment(env2["state_root"], dep2["deployment_id"])["desired_state"] == "REVOKED"
    report = reconcile(env2["state_root"], dep2["deployment_id"], runtime=rt2)
    status = get_runtime_status(env2["state_root"], instance["instance_id"])
    assert status["observed_state"] == "REVOKED"
    assert rt2.stops == [instance["instance_id"]]


def test_g_start_failure_is_failed_then_retries(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime(start="FAILED")
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert report["diff"] == "START"
    assert instances[0]["observed_state"] == "FAILED"
    assert instances[0]["failure_reason"]
    assert instances[0]["attempt_count"] == 1

    rt.start_result = "RUNNING"
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["diff"] == "START"
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert instances[0]["observed_state"] == "RUNNING"
    assert instances[0]["attempt_count"] == 2
    assert len(rt.starts) == 2


def test_g2_start_failure_exhausts_retry_then_escalates(tmp_path):
    env = canonical_env(tmp_path)
    version = create_version(env["state_root"], env["registry_root"],
                             env["frozen_root"], env["candidate_id"])
    dep = create_deployment(env["state_root"], version["agent_id"],
                            version["version_id"], "RUNNING")
    rt = FakeRuntime(start="FAILED")
    for _ in range(START_MAX_ATTEMPTS):
        reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    instances = get_runtime_instances(env["state_root"], dep["deployment_id"])
    assert instances[0]["attempt_count"] == START_MAX_ATTEMPTS
    assert instances[0]["observed_state"] == "FAILED"
    report = reconcile(env["state_root"], dep["deployment_id"], runtime=rt)
    assert report["verdict"] == "RECONCILE_REQUIRED"
    assert len(rt.starts) == START_MAX_ATTEMPTS


def test_create_version_is_idempotent_and_conflict_safe(tmp_path):
    env = canonical_env(tmp_path)
    v1 = create_version(env["state_root"], env["registry_root"],
                        env["frozen_root"], env["candidate_id"])
    again = create_version(env["state_root"], env["registry_root"],
                           env["frozen_root"], env["candidate_id"])
    assert again == v1
    assert v1["execution_snapshot_identity"].startswith("snap-")


def test_legacy_registry_entry_requires_migration(tmp_path):
    env = canonical_env(tmp_path)
    entry_path = env["registry_root"] / "F+" / f"{NAME}.json"
    legacy = json.loads(entry_path.read_text())
    legacy.pop("adoption", None)
    legacy["artifact_identity"] = None
    entry_path.write_text(json.dumps(legacy, indent=2) + "\n")
    with pytest.raises(ManagedRuntimeError) as exc:
        create_version(env["state_root"], env["registry_root"],
                       env["frozen_root"], env["candidate_id"])
    assert exc.value.code == "LEGACY_MIGRATION_REQUIRED"
