"""Phase 10.3 Stage 1 — minimal Deployment -> Reconcile -> RuntimeInstance
closed loop on top of the Phase 9 trust chain.

Single source of truth per object (JSONL, latest event wins):
  versions.jsonl     AgentVersion, write-once; revoke appends terminal event
  deployments.jsonl  Deployment desired-state events
  instances.jsonl    RuntimeInstance observed-state events

run_record stays historical evidence; RuntimeInstance may reference run_id.
Stage 1 implements READY/STARTING/RUNNING/STOPPING/STOPPED/FAILED/REVOKED;
DEPLOYING/PENDING/UNKNOWN stay contract only. Upgrade/rollback auto-reconcile
is deferred; VERSION_DRIFT is detected and reported, never auto-fixed.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from forge.bundle_producer import canonical_json, sha256_bytes
from forge.capabilityizer import CANONICAL_ARTIFACT_IDENTITY_V1, frozen_checks
from pilot.adoption_authority import (
    REVOCABLE_STATUSES,
    authority_id_for,
    load_authority_events,
    load_authority_record,
    revoke_authority,
)
from pilot import runtime_adoption_guard as guard
from pilot.registry import AdoptionBlocked, discover

ROOT = Path(__file__).resolve().parent

DESIRED_STATES = ("RUNNING", "STOPPED", "REVOKED")
OBSERVED_STATES = (
    "READY", "DEPLOYING", "PENDING", "STARTING", "RUNNING",
    "STOPPING", "STOPPED", "FAILED", "REVOKED", "UNKNOWN",
)
ACTIVE_STATES = ("READY", "STARTING", "RUNNING", "STOPPING", "FAILED")

# 10.3 Q2: minimal retry contract; no scheduler in Stage 1.
START_MAX_ATTEMPTS = 3
START_RETRY_BACKOFF_S = 0


class ManagedRuntimeError(Exception):
    """Fail-closed domain error with machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uuid(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def _latest(path: Path, key: str, value: str) -> dict | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text().splitlines()):
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get(key) == value:
            return rec
    return None


def _current(state_root: Path, filename: str, id_key: str) -> list[dict]:
    path = state_root / filename
    if not path.exists():
        return []
    current = {}
    for line in path.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            current[rec[id_key]] = rec
    return list(current.values())


def execution_snapshot_identity(candidate_id: str, artifact_digest: str,
                                seal_digest: str) -> str:
    """E(D) identity from 10.1 §4: snap-<sha256(canonical{candidate,D,seal})[:16]>."""
    payload = canonical_json({
        "candidate_id": candidate_id,
        "artifact_digest": artifact_digest,
        "seal_digest": seal_digest,
    })
    return "snap-" + sha256_bytes(payload)[len("sha256:"):][:16]


def _version(state_root: Path, version_id: str) -> dict | None:
    return _latest(state_root / "versions.jsonl", "version_id", version_id)


def _version_revoked(version: dict) -> bool:
    if version.get("state") == "REVOKED":
        return True
    try:
        events = load_authority_events(
            Path(version["registry_root"]), version["authority_id"])
    except (OSError, json.JSONDecodeError):
        return True  # unreadable revocation ledger -> fail closed
    return any(e.get("status") in REVOCABLE_STATUSES for e in events)


def _snapshot_binding_violation(version: dict) -> bool:
    expected = execution_snapshot_identity(
        version["candidate_id"], version["artifact_digest"], version["seal_digest"])
    return version.get("execution_snapshot_identity") != expected


def _authority(registry_root: Path, adoption: dict) -> dict | None:
    aid = authority_id_for(
        adoption.get("candidate_id"),
        adoption.get("candidate_version"),
        adoption.get("promotion_decision_id"),
    )
    try:
        return load_authority_record(registry_root, aid)
    except (OSError, json.JSONDecodeError):
        return None


def create_version(state_root, registry_root, frozen_root, candidate_id: str,
                   *, family: str = "F+") -> dict:
    """Publish an immutable AgentVersion from a canonical Frozen Candidate.

    Requires: frozen candidate verified, promoted canonical registry entry,
    issued authority (not revoked), anchored run_request. Legacy entries
    (no canonical adoption) are refused with LEGACY_MIGRATION_REQUIRED.
    """
    state_root, registry_root, frozen_root = Path(state_root), Path(registry_root), Path(frozen_root)
    frozen = frozen_checks(frozen_root, candidate_id)
    if not frozen["ok"]:
        raise ManagedRuntimeError(
            "CANDIDATE_NOT_FROZEN",
            json.dumps(frozen["violations"], ensure_ascii=False))
    record = frozen["record"]
    name = record["name"]
    entry = discover(registry_root, family, name)
    if entry is None:
        raise ManagedRuntimeError("REGISTRY_ENTRY_MISSING",
                                  f"family={family} name={name}")
    adoption = entry.get("adoption") or {}
    if entry.get("artifact_identity") != CANONICAL_ARTIFACT_IDENTITY_V1 or not adoption:
        raise ManagedRuntimeError(
            "LEGACY_MIGRATION_REQUIRED",
            f"entry {name} has no canonical adoption binding; legacy id "
            "migration is deferred (MIGRATION_REQUIRED)")
    if adoption.get("candidate_id") != candidate_id:
        raise ManagedRuntimeError("CANDIDATE_ID_MISMATCH",
                                  f"entry candidate={adoption.get('candidate_id')} "
                                  f"frozen candidate={candidate_id}")
    authority = _authority(registry_root, adoption)
    if authority is None:
        raise ManagedRuntimeError("AUTHORITY_MISSING",
                                  f"candidate={candidate_id}")
    if any(e.get("status") in REVOCABLE_STATUSES
           for e in load_authority_events(registry_root, authority["authority_id"])):
        raise ManagedRuntimeError("VERSION_REVOKED",
                                  f"authority={authority['authority_id']}")
    run_request = guard.load_trusted_run_request(registry_root)
    if run_request is None:
        raise ManagedRuntimeError("MISSING_RUN_REQUEST",
                                  "canonical candidate requires anchored run_request")
    # Registry entry adoption block predates seal_digest (registry.py:186);
    # seal_digest is carried by the authority record and anchored run_request.
    identity = dict(adoption)
    identity["seal_digest"] = authority.get("seal_digest")
    for key in ("candidate_id", "candidate_version", "artifact_digest", "seal_digest"):
        if run_request.get(key) != identity.get(key):
            raise ManagedRuntimeError("RUN_REQUEST_MISMATCH", f"field={key}")
        if authority.get(key) != identity.get(key):
            raise ManagedRuntimeError("AUTHORITY_MISMATCH", f"field={key}")
    version_id = f"v{record['version']}"
    if version_id != adoption.get("candidate_version"):
        raise ManagedRuntimeError("VERSION_CONFLICT",
                                  f"frozen version={version_id} "
                                  f"adoption version={adoption.get('candidate_version')}")
    event = {
        "schema": "managed_runtime_v1",
        "event": "version_created",
        "state": "ACTIVE",
        "version_id": version_id,
        "agent_id": entry["capability_id"],
        "name": name,
        "family": family,
        "candidate_id": candidate_id,
        "candidate_version": adoption["candidate_version"],
        "artifact_digest": identity["artifact_digest"],
        "seal_digest": identity["seal_digest"],
        "execution_snapshot_identity": execution_snapshot_identity(
            candidate_id, identity["artifact_digest"], identity["seal_digest"]),
        "authority_id": authority["authority_id"],
        "promotion_decision_id": adoption["promotion_decision_id"],
        "evaluation_run_id": adoption["evaluation_run_id"],
        "registry_root": str(registry_root),
        "frozen_root": str(frozen_root),
        "created_at": _now(),
    }
    existing = _latest(state_root / "versions.jsonl", "version_id", version_id)
    if existing is not None:
        binding = ("candidate_id", "artifact_digest", "seal_digest",
                   "execution_snapshot_identity")
        if all(existing.get(k) == event[k] for k in binding):
            return existing
        raise ManagedRuntimeError(
            "VERSION_CONFLICT", f"version_id={version_id} bound to different content")
    _append(state_root / "versions.jsonl", event)
    return event


def _deployment_for_agent(state_root: Path, agent_id: str) -> dict | None:
    for dep in _current(state_root, "deployments.jsonl", "deployment_id"):
        if dep["agent_id"] == agent_id:
            return dep
    return None


def create_deployment(state_root, agent_id: str, version_id: str,
                      desired_state: str = "STOPPED") -> dict:
    """One Deployment per Agent (MVP): idempotent on identical content."""
    state_root = Path(state_root)
    if desired_state not in DESIRED_STATES:
        raise ManagedRuntimeError("INVALID_DESIRED_STATE",
                                  f"desired_state={desired_state!r}")
    version = _version(state_root, version_id)
    if version is None:
        raise ManagedRuntimeError("VERSION_NOT_FOUND", f"version_id={version_id}")
    if version["agent_id"] != agent_id:
        raise ManagedRuntimeError("AGENT_VERSION_MISMATCH",
                                  f"agent_id={agent_id} version={version_id}")
    existing = _deployment_for_agent(state_root, agent_id)
    if existing is not None:
        if existing["version_id"] == version_id \
                and existing["desired_state"] == desired_state:
            return existing
        raise ManagedRuntimeError("DEPLOYMENT_CONFLICT",
                                  f"agent_id={agent_id} already has a deployment")
    dep = {
        "schema": "managed_runtime_v1",
        "event": "deployment_created",
        "deployment_id": _uuid("dep"),
        "agent_id": agent_id,
        "version_id": version_id,
        "desired_state": desired_state,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _append(state_root / "deployments.jsonl", dep)
    return dep


def get_deployment(state_root, deployment_id: str) -> dict:
    dep = _latest(Path(state_root) / "deployments.jsonl",
                  "deployment_id", deployment_id)
    if dep is None:
        raise ManagedRuntimeError("DEPLOYMENT_NOT_FOUND",
                                  f"deployment_id={deployment_id}")
    return dep


def set_desired_state(state_root, deployment_id: str, desired_state: str) -> dict:
    if desired_state not in DESIRED_STATES:
        raise ManagedRuntimeError("INVALID_DESIRED_STATE",
                                  f"desired_state={desired_state!r}")
    dep = get_deployment(state_root, deployment_id)
    if dep["desired_state"] == desired_state:
        return dep  # idempotent NO-OP
    if dep["desired_state"] == "REVOKED":
        raise ManagedRuntimeError("REVOKED_TERMINAL",
                                  "cannot leave REVOKED deployment")
    event = dict(dep)
    event.update({"event": "deployment_updated",
                  "desired_state": desired_state,
                  "updated_at": _now()})
    _append(Path(state_root) / "deployments.jsonl", event)
    return event


def get_runtime_instances(state_root, deployment_id: str | None = None) -> list[dict]:
    instances = _current(Path(state_root), "instances.jsonl", "instance_id")
    if deployment_id is not None:
        instances = [i for i in instances if i["deployment_id"] == deployment_id]
    return instances


# 10.1 API name compatibility.
list_runtime_instances = get_runtime_instances


def _active_instance(state_root: Path, deployment_id: str,
                     version_id: str | None = None) -> dict | None:
    for inst in reversed(get_runtime_instances(state_root, deployment_id)):
        if inst["observed_state"] in ACTIVE_STATES:
            # A failed instance of an old version is not retryable for the
            # desired version; a new instance must start instead.
            if version_id is not None and inst["observed_state"] == "FAILED" \
                    and inst["version_id"] != version_id:
                continue
            return inst
    return None


def _append_instance(state_root: Path, prev: dict, observed_state: str,
                     event: str, **extra) -> dict:
    rec = dict(prev)
    rec.update({"event": event, "observed_state": observed_state})
    rec.update(extra)
    _append(state_root / "instances.jsonl", rec)
    return rec


def _start(state_root: Path, dep: dict, version: dict, runtime,
           *, instance: dict | None = None, attempt: int = 1) -> tuple[dict, bool]:
    if instance is None:
        instance = {
            "schema": "managed_runtime_v1",
            "event": "instance_created",
            "instance_id": _uuid("inst"),
            "deployment_id": dep["deployment_id"],
            "agent_id": dep["agent_id"],
            "version_id": dep["version_id"],
            "execution_snapshot_identity": version["execution_snapshot_identity"],
            "observed_state": "READY",
            "started_at": _now(),
            "stopped_at": None,
            "failure_reason": None,
            "attempt_count": 0,
            "run_id": None,
        }
        _append(state_root / "instances.jsonl", instance)
    starting = _append_instance(state_root, instance, "STARTING",
                                "instance_starting", attempt_count=attempt)
    result = runtime.start(starting, version)
    if result.get("observed_state") == "RUNNING":
        running = _append_instance(state_root, starting, "RUNNING",
                                   "instance_running", failure_reason=None)
        return running, True
    failed = _append_instance(state_root, starting, "FAILED", "instance_failed",
                              failure_reason=result.get("failure_reason")
                              or "RUNTIME_START_FAILED")
    return failed, False


def _stop(state_root: Path, instance: dict, runtime) -> tuple[dict, bool]:
    stopping = _append_instance(state_root, instance, "STOPPING", "instance_stopping")
    result = runtime.stop(stopping)
    if result.get("observed_state") == "STOPPED":
        stopped = _append_instance(state_root, stopping, "STOPPED",
                                   "instance_stopped", stopped_at=_now(),
                                   failure_reason=None)
        return stopped, True
    failed = _append_instance(state_root, stopping, "FAILED", "instance_failed",
                              failure_reason=result.get("failure_reason")
                              or "RUNTIME_STOP_FAILED")
    return failed, False


def _report(state_root: Path, dep: dict, diff: str, verdict: str, *,
            version_drift: bool = False, reason: str | None = None,
            instance: dict | None = None) -> dict:
    actions = []
    if instance is not None and diff in ("START", "STOP", "REVOKE"):
        actions.append({"action": diff.lower(),
                        "instance_id": instance["instance_id"]})
    return {
        "deployment_id": dep["deployment_id"],
        "desired_state": dep["desired_state"],
        "desired_version": dep["version_id"],
        "diff": diff,
        "actions": actions,
        "verdict": verdict,
        "version_drift": version_drift,
        "reason": reason,
        "instances": get_runtime_instances(state_root, dep["deployment_id"]),
    }


def reconcile(state_root, deployment_id: str, runtime=None) -> dict:
    """Diff Deployment desired state against RuntimeInstance observed state
    and apply the minimal action (START / STOP / UPGRADE / NO-OP / REJECT)."""
    state_root = Path(state_root)
    dep = get_deployment(state_root, deployment_id)
    version = _version(state_root, dep["version_id"])
    if version is None:
        return _report(state_root, dep, "RECONCILE_REQUIRED", "VERSION_NOT_FOUND",
                       reason=f"version_id={dep['version_id']}")

    runtime = runtime or DockerRuntime(state_root=state_root)
    desired = dep["desired_state"]
    active = _active_instance(state_root, deployment_id)

    if desired == "RUNNING":
        if _version_revoked(version):
            return _report(state_root, dep, "REJECT", "REJECT",
                           reason=f"version {version['version_id']} is REVOKED")
        if _snapshot_binding_violation(version):
            return _report(state_root, dep, "REJECT", "REJECT",
                           reason="execution_snapshot_identity does not match "
                                  "candidate_id/artifact_digest/seal_digest")
        if active is not None and active["version_id"] != dep["version_id"]:
            old = active
            if old["observed_state"] in ("RUNNING", "READY", "STARTING"):
                stopped, ok = _stop(state_root, old, runtime)
                if not ok:
                    return _report(state_root, dep, "STOP", "FAILED",
                                   instance=stopped,
                                   reason=f"stop {old['version_id']} before switch failed")
            elif old["observed_state"] == "STOPPING":
                return _report(state_root, dep, "VERSION_DRIFT",
                               "RECONCILE_REQUIRED", version_drift=True,
                               instance=old,
                               reason=f"old version {old['version_id']} stopping")
            elif old["observed_state"] != "FAILED":
                return _report(state_root, dep, "NO-OP", "RECONCILE_REQUIRED",
                               instance=old)
            instance, ok = _start(state_root, dep, version, runtime)
            return _report(state_root, dep, "UPGRADE",
                           "HEALTHY" if ok else "FAILED", instance=instance,
                           reason=f"version switch {old['version_id']} -> "
                                  f"{dep['version_id']}")
        if active is None or active["observed_state"] == "STOPPED":
            instance, ok = _start(state_root, dep, version, runtime, attempt=1)
            return _report(state_root, dep, "START",
                           "HEALTHY" if ok else "FAILED", instance=instance)
        if active["observed_state"] == "RUNNING":
            return _report(state_root, dep, "NO-OP", "HEALTHY", instance=active)
        if active["observed_state"] == "FAILED":
            attempt = active.get("attempt_count") or 1
            if attempt >= START_MAX_ATTEMPTS:
                return _report(state_root, dep, "RECONCILE_REQUIRED",
                               "RECONCILE_REQUIRED", instance=active,
                               reason="start retries exhausted")
            instance, ok = _start(state_root, dep, version, runtime,
                                  instance=active, attempt=attempt + 1)
            return _report(state_root, dep, "START",
                           "HEALTHY" if ok else "FAILED", instance=instance)
        return _report(state_root, dep, "NO-OP", "RECONCILE_REQUIRED",
                       instance=active)  # READY / STARTING / STOPPING in transition

    if desired == "STOPPED":
        if active is None or active["observed_state"] in ("STOPPED", "FAILED"):
            return _report(state_root, dep, "NO-OP", "HEALTHY", instance=active)
        if active["observed_state"] in ("RUNNING", "STARTING", "READY"):
            instance, ok = _stop(state_root, active, runtime)
            return _report(state_root, dep, "STOP",
                           "HEALTHY" if ok else "FAILED", instance=instance)
        return _report(state_root, dep, "NO-OP", "RECONCILE_REQUIRED",
                       instance=active)  # STOPPING in transition

    # desired == REVOKED
    instances = get_runtime_instances(state_root, dep["deployment_id"])
    current = instances[-1] if instances else None
    if current is None:
        return _report(state_root, dep, "NO-OP", "REVOKED")
    if current["observed_state"] in ("STOPPED", "FAILED", "READY"):
        instance = _append_instance(state_root, current, "REVOKED",
                                    "instance_revoked", stopped_at=_now())
        return _report(state_root, dep, "REVOKE", "REVOKED", instance=instance)
    if current["observed_state"] == "REVOKED":
        return _report(state_root, dep, "NO-OP", "REVOKED", instance=current)
    if current["observed_state"] in ("RUNNING", "STARTING"):
        stopped, ok = _stop(state_root, current, runtime)
        if ok:
            instance = _append_instance(state_root, stopped, "REVOKED",
                                        "instance_revoked", stopped_at=_now())
            return _report(state_root, dep, "STOP", "REVOKED", instance=instance)
        return _report(state_root, dep, "STOP", "FAILED", instance=stopped)
    return _report(state_root, dep, "NO-OP", "RECONCILE_REQUIRED", instance=current)


def _validate_target_version(state_root: Path, dep: dict,
                             target_version_id: str) -> dict:
    version = _version(state_root, target_version_id)
    if version is None:
        raise ManagedRuntimeError("VERSION_NOT_FOUND",
                                  f"version_id={target_version_id}")
    if version["agent_id"] != dep["agent_id"]:
        raise ManagedRuntimeError("AGENT_VERSION_MISMATCH",
                                  f"agent_id={dep['agent_id']} "
                                  f"version={target_version_id}")
    if _version_revoked(version):
        raise ManagedRuntimeError("VERSION_REVOKED",
                                  f"version_id={target_version_id}")
    if _snapshot_binding_violation(version):
        raise ManagedRuntimeError(
            "SNAPSHOT_BINDING_MISMATCH",
            f"version_id={target_version_id} snapshot identity mismatch")
    frozen = frozen_checks(Path(version["frozen_root"]), version["candidate_id"])
    if not frozen["ok"]:
        raise ManagedRuntimeError(
            "SNAPSHOT_INVALID",
            json.dumps(frozen["violations"], ensure_ascii=False))
    return version


def upgrade(state_root, deployment_id: str, target_version_id: str,
            runtime=None) -> dict:
    """Set Deployment desired version to target (RUNNING) and reconcile.

    Validates target before any state change; same target/state is a NO-OP.
    A failed start leaves desired=target and observed=FAILED; Stage 2 does
    not implement implicit auto-rollback.
    """
    state_root = Path(state_root)
    dep = get_deployment(state_root, deployment_id)
    if dep["desired_state"] == "REVOKED":
        raise ManagedRuntimeError("REVOKED_TERMINAL",
                                  "cannot upgrade a REVOKED deployment")
    _validate_target_version(state_root, dep, target_version_id)
    if dep["version_id"] != target_version_id or dep["desired_state"] != "RUNNING":
        event = dict(dep)
        event.update({"event": "deployment_updated",
                      "version_id": target_version_id,
                      "desired_state": "RUNNING",
                      "updated_at": _now()})
        _append(state_root / "deployments.jsonl", event)
    return reconcile(state_root, deployment_id, runtime=runtime)


def rollback(state_root, deployment_id: str, target_version_id: str,
             runtime=None) -> dict:
    """Rollback is the same mechanism as upgrade: point Deployment at an
    older immutable Version and reconcile; Version records are never mutated."""
    return upgrade(state_root, deployment_id, target_version_id, runtime=runtime)


def get_runtime_status(state_root, instance_id: str) -> dict:
    state_root = Path(state_root)
    inst = _latest(state_root / "instances.jsonl", "instance_id", instance_id)
    if inst is None:
        raise ManagedRuntimeError("INSTANCE_NOT_FOUND", f"instance_id={instance_id}")
    dep = get_deployment(state_root, inst["deployment_id"])
    version = _version(state_root, inst["version_id"])
    drift = dep["version_id"] != inst["version_id"]
    binding = version is not None and \
        inst["execution_snapshot_identity"] == version["execution_snapshot_identity"]
    return {
        "instance_id": inst["instance_id"],
        "deployment_id": inst["deployment_id"],
        "agent_id": inst["agent_id"],
        "version_id": inst["version_id"],
        "execution_snapshot_identity": inst["execution_snapshot_identity"],
        "observed_state": inst["observed_state"],
        "started_at": inst["started_at"],
        "stopped_at": inst["stopped_at"],
        "failure_reason": inst.get("failure_reason"),
        "desired_state": dep["desired_state"],
        "desired_version": dep["version_id"],
        "observed_version": inst["version_id"],
        "version_drift": drift,
        "snapshot_binding": "OK" if binding else "MISMATCH",
    }


def revoke_version(state_root, registry_root, version_id: str, *,
                   issuer_id: str, reason: str = "") -> dict:
    """Terminal revoke: authority event -> version REVOKED -> deployments
    desired REVOKED. Idempotent on already-revoked version."""
    state_root, registry_root = Path(state_root), Path(registry_root)
    version = _version(state_root, version_id)
    if version is None:
        raise ManagedRuntimeError("VERSION_NOT_FOUND", f"version_id={version_id}")
    if version.get("state") == "REVOKED":
        return version
    res = revoke_authority(registry_root, version["authority_id"],
                           status="REVOKED", issuer_id=issuer_id, reason=reason)
    if not res["allowed"]:
        raise ManagedRuntimeError(res.get("code") or "REVOKE_BLOCKED",
                                  res.get("message") or "authority revoke failed")
    event = dict(version)
    event.update({"event": "version_revoked", "state": "REVOKED",
                  "revocation_id": res["revocation_id"], "revoked_at": _now()})
    _append(state_root / "versions.jsonl", event)
    for dep in _current(state_root, "deployments.jsonl", "deployment_id"):
        if dep["version_id"] == version_id and dep["desired_state"] != "REVOKED":
            set_desired_state(state_root, dep["deployment_id"], "REVOKED")
    return event


class DockerRuntime:
    """Phase 9 verified Docker runtime (existing pilot sandbox; no new
    sandbox integration). verify_at_mount -> bind mount E(D) -> docker run -d.

    ponytail: stage-1 holder runs the verified entrypoint then keeps the
    container alive so RUNNING/STOPPED are observable; stop = docker kill.
    Replace with a real process supervisor when long-running agents arrive.
    """

    def __init__(self, image: str | None = None, state_root=None,
                 runtime_uid: int | None = None):
        if image is None:
            cfg = json.loads((ROOT / "config.json").read_text())
            image = cfg["sandbox"]["image"]
        self.image = image
        self.state_root = Path(state_root or (ROOT / "state"))
        self.runtime_uid = runtime_uid

    def start(self, instance: dict, version: dict) -> dict:
        registry_root = Path(version["registry_root"])
        entry = discover(registry_root, version["family"], version["name"])
        run_request = guard.load_trusted_run_request(registry_root)
        if entry is None or run_request is None:
            return {"observed_state": "FAILED",
                    "failure_reason": "MISSING_RUN_REQUEST_OR_ENTRY"}
        snapshot = Path(version["frozen_root"]) / "frozen" \
            / version["candidate_id"] / "artifact"
        try:
            mount = guard.verify_at_mount(
                registry_root, entry, snapshot,
                expected_digest=run_request["artifact_digest"],
                expected_identity=run_request,
                mount_source=snapshot, runtime_uid=self.runtime_uid)
        except AdoptionBlocked as exc:
            return {"observed_state": "FAILED",
                    "failure_reason": exc.report["verdict"] + ": "
                    + json.dumps(exc.report["violations"], ensure_ascii=False)}
        work = self.state_root / "runtime_work" / instance["instance_id"]
        work.mkdir(parents=True, exist_ok=True)
        candidate = json.loads((Path(snapshot).parent / "candidate.json").read_text())
        entrypoint = (candidate.get("manifest") or {}).get("entrypoint") or {}
        cmd = entrypoint.get("command") or ["python", "main.py"]
        args = [
            "docker", "run", "-d", "--name", instance["instance_id"],
            "--network", "none",
            "-v", f"{mount['verified_artifact_dir']}:/artifact:ro",
            "-v", f"{work}:/work:rw",
            self.image,
            "sh", "-c", 'cd /artifact && "$@" && sleep infinity', "sh", *cmd,
        ]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"observed_state": "FAILED",
                    "failure_reason": "docker run: "
                    + (proc.stderr or proc.stdout).strip()[:500]}
        inspect = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}",
             instance["instance_id"]],
            capture_output=True, text=True)
        if inspect.stdout.strip() == "true":
            return {"observed_state": "RUNNING", "failure_reason": None}
        code = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.ExitCode}}",
             instance["instance_id"]],
            capture_output=True, text=True)
        subprocess.run(["docker", "rm", "-f", instance["instance_id"]],
                       capture_output=True)
        return {"observed_state": "FAILED",
                "failure_reason": "container exited code="
                + code.stdout.strip()}

    def stop(self, instance: dict) -> dict:
        kill = subprocess.run(["docker", "kill", instance["instance_id"]],
                              capture_output=True, text=True)
        if kill.returncode != 0:
            return {"observed_state": "FAILED",
                    "failure_reason": "docker kill: "
                    + (kill.stderr or kill.stdout).strip()[:500]}
        subprocess.run(["docker", "rm", instance["instance_id"]],
                       capture_output=True)
        return {"observed_state": "STOPPED", "failure_reason": None}
