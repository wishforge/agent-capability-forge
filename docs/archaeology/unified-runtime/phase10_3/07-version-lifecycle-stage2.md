# 07 — Phase 10.3 Stage 2 实现报告（Upgrade / Rollback / Revoke）

- 阶段：Phase 10.3 Stage 2（Managed Agent Version Lifecycle）
- 日期：2026-08-19
- 基线：`main == origin/main == daafa4d`（Phase 10.3 Stage 1 已 commit/push）
- 方法：RED（22 个测试：18 个新测试 + 4 个 review-fix 回归测试）→ minimal
  implementation → GREEN → Phase 9 regression → 全量 suite → scope audit

## 交付物

| 文件 | 角色 |
|---|---|
| `pilot/managed_runtime.py` | `upgrade()` / `rollback()`；reconcile 版本切换（UPGRADE）；REVOKED 终态覆盖 STOPPED/FAILED/READY；目标 Version 校验（unknown / revoked / snapshot binding / frozen_checks） |
| `docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage2.py` | Managed Agent Version Lifecycle State Machine 测试：Upgrade ×6 / Rollback ×4 / Revoke ×6 / Failure ×1 / Immutability ×1 / stop-failure 回归 ×4（22 tests） |
| `docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage1.py` | 必要配套：Stage 1 Test D 从“不自动升级”更新为“upgrade 自动切换”；新增 `seed_version` 测试夹具 |
| `docs/archaeology/unified-runtime/phase10_3/07-version-lifecycle-stage2.md` | 本报告 |

## Upgrade

```text
upgrade(state_root, deployment_id, target_version_id, runtime=None)
```

操作顺序：校验 target Version（存在 / 同 agent / 未 REVOKED / snapshot
binding 一致 / frozen_checks 通过）→ Deployment desired
version_id=target、desired_state=RUNNING → reconcile → 旧 instance STOP →
新 instance START target Version。

- `upgrade(v16→v17)`：旧 v16 instance → STOPPED；新 v17 instance →
  RUNNING，且 `execution_snapshot_identity == E(D17)`。
- 版本切换期间旧 instance STOPPING 尚未完成时：`VERSION_DRIFT /
  RECONCILE_REQUIRED`，不会并行启动第二个 running instance。
- `upgrade` 不改写任何 Version 记录（immutability 测试锁定 versions.jsonl
  字节不变）。

## Rollback

`rollback(...)` 与 upgrade 共用同一机制：Deployment desired version 指向旧
Version，reconcile 停止当前 instance 并启动旧的 immutable snapshot。禁止
“把 v17 原地改成 v16”；Version 记录在任何路径下都不被修改。

Rollback 前置校验与 Upgrade 相同，且明确要求旧 snapshot 仍然存在并
`frozen_checks` 通过：删除 frozen candidate 后 rollback 返回
`SNAPSHOT_INVALID`，Desired 保持不变。

## Revoke

`revoke_version()`（Stage 1 已有）保持原语义，本阶段补齐终态覆盖：

- version state → `REVOKED`（authority event + versions.jsonl 事件）；
- 引用该 Version 的 Deployment desired_state → `REVOKED`；
- reconcile：
  - RUNNING/STARTING → STOPPING → STOPPED → REVOKED；
  - STOPPED/FAILED/READY → 直接追加 REVOKED 终态事件（修复 Stage 1
    对 STOPPED instance 不写 REVOKED 终态的缺口）；
  - 无 instance → NO-OP REVOKED；
- 之后 new start = REJECT；`set_desired_state(RUNNING)` 或
  `upgrade()` 对 REVOKED Deployment 均返回 `REVOKED_TERMINAL`。

## Idempotency

| 操作 | 重复调用 |
|---|---|
| `upgrade(v16→v17)` ×2 | 第二次 NO-OP，只保留 1 个 v17 active instance |
| `upgrade(v17→v17)` | NO-OP，不产生新 instance |
| `rollback(v17→v16)` ×2 | 第二次 NO-OP，只保留 1 个 v16 active instance |
| `revoke(v17)` ×3 | 返回同一 REVOKED 记录，仅 1 条 `version_revoked` 事件 |
| `reconcile` 空 diff | NO-OP，不产生新事件 |

## Version State

AgentVersion 只使用 `ACTIVE` / `REVOKED` 两个状态；DEPLOYED / RUNNING /
STOPPED 不属于 Version，仍属于 Deployment / RuntimeInstance。测试锁定
Version 事件 state 集合 ⊆ {ACTIVE, REVOKED}。

## Snapshot Binding

`upgrade` / `rollback` 在写 Desired 前执行双重校验：

1. Version 记录级：`execution_snapshot_identity ==
   E(candidate_id, artifact_digest, seal_digest)`，不一致 →
   `SNAPSHOT_BINDING_MISMATCH`；
2. 磁盘级：`frozen_checks(frozen_root, candidate_id)`，缺失 / digest
   变化 / owner isolation 违反 → `SNAPSHOT_INVALID`（fail-closed）。

新 RuntimeInstance 只从 target Version 派生 snapshot identity；测试断言
upgrade 后新 instance 的 identity == v17 identity，rollback 后 == v16
identity。

## Failure Semantics

Upgrade 到 v17 启动失败：

```text
Deployment desired = v17 (RUNNING)
Observed           = FAILED（新 instance）
旧 instance        = STOPPED
```

不隐式自动回滚到 v16（自动 rollback 是另一种控制策略，本阶段不实现）。
下次 reconcile 在 `START_MAX_ATTEMPTS` 内对同一 v17 instance 重试；
超限 → `RECONCILE_REQUIRED`。

## Phase 9 Regression

```text
phase9b1 / phase9b3 / phase9b5 / phase9d3: 96 passed, 6 subtests passed
```

Upgrade/Rollback/Revoke 不引入 bypass：目标版本先过 `frozen_checks`；
真实启动路径仍经过 `DockerRuntime.start -> guard.verify_at_mount`
（Run Intent / Execution Snapshot / verify_at_mount 未改动）。

## Full Suite

```text
pytest -q: 902 passed, 11 skipped, 19 subtests passed
```

## Live Runtime

```text
LIVE_RUNTIME = UNAVAILABLE
```

`docker info` 实测：`permission denied while trying to connect to the
docker API at unix:///Users/david/.docker/run/docker.sock`。未伪造 Docker
live PASS；生命周期 domain semantics 通过 FakeRuntime 验证。

## Findings

1. **多版本发布被 registry 单 adoption 模型阻塞**：
   `pilot/registry.py:promote()` 是 write-once（`ENTRY_BINDING_CONFLICT`），
   同一 agent 无法通过 canonical `create_version` 发布 v2。本阶段
   `seed_version` 测试夹具直接写入第二个 Version 记录来验证生命周期语义；
   生产多版本发布路径记为 `MIGRATION_REQUIRED`，不实施。
2. **Live rollback 的 per-version 信任解析未实现**：
   `DockerRuntime.start` 使用当前 registry entry + 单一 `run_request`，
   `verify_at_mount` 按 entry 当前 adoption 找 authority。v2 发布后，
   真实回滚 v1 会在 mount 时 fail-closed（不会绕过信任链），但需要
   per-version run intent / authority 解析才能 live 跑通。属于后续
   live runtime 阶段，不影响本阶段 domain 语义。
3. Stage 1 Test D 随 Stage 2 契约更新：Desired v17 + Observed v16 从
   “只报告 VERSION_DRIFT”改为“UPGRADE 自动切换”（10.1 §9 冻结的
   UPGRADE action）。

## Review Findings

1. **stop failure blocks target start**：旧 instance stop 返回 FAILED 后，
   reconcile 返回 `RECONCILE_REQUIRED`，且不启动 target；下一次 reconcile
   在旧 instance 被确认 `STOPPED` 之前持续阻塞（修复前 FAILED 会直接落入
   START target 分支）。新增 4 个回归测试覆盖：
   failed-stop upgrade / next reconcile / confirmed STOPPED -> upgrade /
   at-most-one-running。
2. **tests validate state-machine semantics only**：Stage 2 测试使用
   `seed_version` 直接写 Version 记录，未走 production publish path
   （`create_version -> registry.promote -> authority -> anchored
   run_request`）；UPGRADE/ROLLBACK 通过只代表状态机语义，不代表
   production-live 通过。
3. **documentation updated**：`pilot/managed_runtime.py` module docstring
   和 Stage 1 Test D header 已同步为“VERSION_DRIFT / auto-upgrade，且
   仅当旧 instance 确认 STOPPED 后 target 才允许启动”。

## Scope Audit

```text
git diff --name-only:
  pilot/managed_runtime.py
  docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage1.py
  docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage2.py
  docs/archaeology/unified-runtime/phase10_3/07-version-lifecycle-stage2.md
git diff --check: 空
未执行 git add -A；既有 untracked archaeology 未触碰。
```

## Final Verdict

```text
PHASE_10_3_STAGE2_REVIEW_FIX = PASS

UPGRADE
    = state-machine PASS
    != production-live PASS
ROLLBACK
    = state-machine PASS
    != production-live PASS
REVOKE
    = state-machine PASS

STOP_FAILURE_SAFETY = CLOSED（FAILED old instance -> RECONCILE_REQUIRED；
                      target 仅在 old confirmed STOPPED 后启动）
AT_MOST_ONE_RUNNING = CLOSED（stop failure / reconcile retry /
                      duplicate reconcile 均不产生第二个 RUNNING）
STATE_MACHINE_TESTS = PASS（22 tests）
PRODUCTION_MULTI_VERSION = MIGRATION_REQUIRED（registry single-adoption /
                      per-version run intent 解析未实施）
LIVE_RUNTIME = UNAVAILABLE（docker.sock permission denied；FakeRuntime
               domain semantics only）

NEXT_PHASE = Legacy Migration → Process Supervisor → Live Runtime
```
