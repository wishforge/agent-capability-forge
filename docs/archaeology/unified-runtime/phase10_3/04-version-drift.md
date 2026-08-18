# 04 — Version Drift 与 Snapshot Binding

- 阶段：Phase 10.3 Stage 1
- 基线：`main == origin/main == 661d866`

## Execution Snapshot Identity

```text
execution_snapshot_identity =
  "snap-" + sha256(canonical({
    candidate_id, artifact_digest, seal_digest
  }))[:16]
```

与 10.1 §4 冻结定义一致；`create_version` 只能由
`candidate_id + artifact_digest + seal_digest` 计算，不允许外部传入 identity，
因此正常创建路径不可能出现 `version=v17, snapshot=E(v16)`。

## Drift 检测

`get_runtime_status(instance_id)` 输出：

```text
version_drift = deployment.version_id != instance.version_id
snapshot_binding = "OK" | "MISMATCH"
```

- `Desired v17 + Observed v16 RUNNING` → `version_drift: true`，
  `observed_state` 保持 RUNNING 但 **verdict 不是 HEALTHY**，而是
  `VERSION_DRIFT / RECONCILE_REQUIRED`（Test D）。
- Stage 1 不自动 UPGRADE：不执行 STOP v16 → START v17；仅暴露 drift 与
  `desired_version / observed_version`。

## Snapshot Binding 强制（Test E）

reconcile start 前校验：

```text
version.execution_snapshot_identity
  == execution_snapshot_identity(version.candidate_id,
                                  version.artifact_digest,
                                  version.seal_digest)
```

不一致 → `REJECT`，不创建 instance（fail-closed）。已运行 instance 的
`execution_snapshot_identity != version.execution_snapshot_identity` →
`SNAPSHOT_BINDING_MISMATCH`，执行 STOP。

## 与 Registry live path 的关系

RuntimeInstance 只消费 `frozen/<candidate_id>/artifact`（Phase 9 已验证的
immutable snapshot）；`registry/<family>/<name>/artifact` 只用于身份/发布绑定，
不作为运行挂载源（`pilot/runtime_adoption_guard.py:623-650` verify_at_mount
强制 mount_source == verified_artifact_dir）。

