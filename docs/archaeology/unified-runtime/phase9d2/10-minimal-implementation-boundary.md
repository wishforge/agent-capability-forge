# Phase 9-D.2.10 — Minimal Implementation Boundary

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：design freeze；**本阶段不实现**

## 1. 目标行为

```text
canonical runtime 接收 immutable execution reference：
  run_request(candidate_id, artifact_digest, seal_digest)
    -> E(D) = frozen_root/frozen/<candidate_id>/artifact
    -> verify E(D)（digest == run_request.artifact_digest）
    -> mount E(D) :ro
```

## 2. 文件级最小改造

### src/forge/capabilityizer.py（必须改）

| existing behavior | required behavior | minimal change |
|---|---|---|
| `freeze_candidate` copy 后直接发布（capabilityizer.py:213 附近） | snapshot 发布后不可写 | `os.replace` 前递归 chmod（目录 0555、文件 0444）；发布后无写路径 |
| `verify_frozen` 只检测 | 维持 | 不改变 record/identity schema；写域隔离作为部署契约 |

### pilot/runtime_adoption_guard.py（必须改）

| existing behavior | required behavior | minimal change |
|---|---|---|
| `verify_at_mount` 验证并返回任意 artifact_dir（:534,538） | canonical 只接受 frozen snapshot 作为 mount source | canonical 分支要求 `mount_source == frozen_root/frozen/<candidate_id>/artifact`；新增 fail code（如 `EXECUTION_SNAPSHOT_REQUIRED`）；`verified_artifact_dir` 返回 snapshot 路径 |
| `RUNTIME_BINDING_MISMATCH`（:559） | 保持 | 保持 |

### pilot/harness.py（必须改）

| existing behavior | required behavior | minimal change |
|---|---|---|
| b3 canonical 分支 mount `entry["artifact_dir"]`（:767,778-791） | mount frozen snapshot | 由 `entry["frozen_root"] + run_request["candidate_id"]` 派生 snapshot 路径；`verify_at_mount` 与 `docker_launch` 都用它；registry live dir 不进 mount 参数 |

### pilot/registry.py（可选）

| existing behavior | required behavior | minimal change |
|---|---|---|
| promote 复制 artifact 到 registry（:183） | canonical 执行不再需要 registry 副本 | 可选：canonical 不再 copytree（省一份磁盘）；entry.artifact_dir 保留为 locator/legacy 兼容 |

### src/forge/sandbox.py（不改）

已经按传入 path 构造 `-v <path>:/artifact:ro`；无需修改。

## 3. 明确不修改

```text
pilot/adoption_authority.py        （anchor / ledger 机制不动）
Run Intent / b3_entry 语义         （9-B.5 已冻结；本次只是消费 digest）
pilot/registry.py（若走最小组）    （只改 harness+guard+freeze）
Legacy Phase 8 路径                （保持历史语义；O1 记录为 LEGACY SECURITY DEBT）
migration / tests / 外部服务        （无）
```

## 4. 部署契约（随实现一起落地）

```text
EXECUTION_SNAPSHOT_STORE：
  owner != runtime user
  目录 0555 / 文件 0444
  parent 层级只读
  创建路径：特权/独立账号 freeze 步骤（或等效）
```

若该契约无法落地，实现阶段必须明确降级声明（NO SAFE MINIMAL OPTION /
same-writer boundary），不能声称 O1 已闭合。

## 5. 验收断言（下一阶段）

```text
1. replace original registry A -> B：canonical run 仍 mount E(D)，观察到 A
2. replace verified snapshot A -> B（有写权限时）：verify 重算 REJECT，不执行
3. replace verified snapshot A -> B（无写权限时）：文件系统操作失败（不可能）
4. post-mount host 文件 mutation：写域隔离下失败；运行中容器 bytes 不变
5. legacy 路径行为不变（回归）
```

