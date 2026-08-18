# 06 — Phase 10.3 Stage 1 实现报告

- 阶段：Phase 10.3 Stage 1（Reconcile + RuntimeInstance Minimal Closed Loop）
- 日期：2026-08-19
- 基线：`main == origin/main == 661d866`（managed-agent-runtime-v1.md 已 commit/push）
- 方法：RED → GREEN → Phase 9 regression → 全量 suite → scope audit

## 交付物

| 文件 | 角色 |
|---|---|
| `pilot/managed_runtime.py` | 生产实现：AgentVersion / Deployment / RuntimeInstance / Reconcile / Revoke / DockerRuntime |
| `docs/archaeology/unified-runtime/phase10_3/01-state-source-analysis.md` | Q1/Q3/Q4 收口：真实状态源、legacy migration、run_record 关联 |
| `docs/archaeology/unified-runtime/phase10_3/02-runtime-instance-lifecycle.md` | Q2 收口：retry contract + 生命周期事件 |
| `docs/archaeology/unified-runtime/phase10_3/03-reconcile-contract.md` | Diff → Action、幂等、revoke |
| `docs/archaeology/unified-runtime/phase10_3/04-version-drift.md` | Drift 检测与 snapshot binding |
| `docs/archaeology/unified-runtime/phase10_3/05-failure-semantics.md` | Failure 行为表 |
| `docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage1.py` | Tests A–G + retry/幂等/legacy 边界（10 tests） |

## Open Questions 收口

1. **真实状态源**：Deployment desired = `managed_runtime/deployments.jsonl`
   最新事件；RuntimeInstance observed = `managed_runtime/instances.jsonl`
   最新事件；`run_record / b3_entry / adoption_store` 不参与状态判定。
2. **Retry**：`START_MAX_ATTEMPTS = 3`、`START_RETRY_BACKOFF_S = 0`
   （无 scheduler，manual/synchronous reconcile）；超限保持 FAILED + ESCALATE。
   同一 instance 追加 STARTING（attempt_count+1），不新建 instance。
3. **Legacy migration**：`MIGRATION_REQUIRED`；legacy entry 无 canonical
   adoption 时 `create_version` 显式拒绝（`LEGACY_MIGRATION_REQUIRED`），不实施迁移。
4. **run_record ↔ instance_id**：`run_record = historical evidence`；
   不修改 `pilot/run_record.py:FIELDS`；RuntimeInstance 事件可选记录 `run_id`
   反向关联，不拥有 run_record 生命周期。

## 测试结果

```text
Phase 10.3 targeted（A–G + 边界）: 10 passed
  A desired RUNNING  -> START -> RUNNING        PASS
  B desired STOPPED  -> STOP  -> STOPPED        PASS（重复 reconcile 只 stop 1 次）
  C RUNNING x3       -> 1 active instance       PASS
  D v17 desired + v16 observed -> VERSION_DRIFT PASS（不自动升级）
  E snapshot mismatch -> REJECT                  PASS（不创建 instance）
  F revoke            -> new start REJECT       PASS
    revoke            -> existing STOP -> REVOKED PASS
  G start failure     -> FAILED -> retry -> RUNNING PASS
  G2 retry 超限        -> RECONCILE_REQUIRED     PASS
  create_version 幂等 / legacy 拒绝              PASS

Phase 9 regression（phase9a1/b1/b3/b5/d3 + tests/）: 160 → 170 passed
Full suite（tests/ + docs/archaeology/unified-runtime）: 437 passed, 6 subtests
```

## Live Runtime

```text
LIVE_RUNTIME = UNAVAILABLE
原因 1: docker daemon 不可用（permission denied on docker.sock）
原因 2: 真实 pilot registry entry 是 legacy 形态
        （cap-d24c50c27fa8, artifact_identity=None, 无 adoption/frozen_root）
        -> create_version 按契约拒绝（MIGRATION_REQUIRED）
```

`DockerRuntime`（`pilot/managed_runtime.py`）已实现但未 live 验证：启动前
`guard.verify_at_mount` 复验 Phase 9 信任链，只挂载已验证的
`frozen/<candidate_id>/artifact`；Stage 1 用 `docker run -d` + sleep-hold 让
RUNNING/STOPPED 可观察（`ponytail:` 注明：非 process supervisor，长驻 Agent
下一阶段替换）。由于 daemon 不可用，该路径保持 fail-closed（start → FAILED），
不会在未验证时报告 RUNNING。

## Scope Audit

```text
git status --short:
  新增（仅 Phase 10.3）:
    pilot/managed_runtime.py
    docs/archaeology/unified-runtime/phase10_3/
  既有未跟踪文件（未触碰）:
    docs/archaeology/codex/
    docs/archaeology/control-plane/
    docs/archaeology/deepseek-harness/
    docs/archaeology/openhands/
    docs/archaeology/unified-runtime/48..53-*.md
    docs/architecture/candidate-seal-v1.md
    docs/architecture/canonical-artifact-identity-v1.md
git diff --name-only: 空（未修改任何已跟踪文件）
```

未执行 `git add -A`，未 commit（用户未要求提交）。

## Final Verdict

```text
PHASE_10_3_STAGE1 = PASS_WITH_FINDINGS

STATE_SOURCE = managed_runtime/deployments.jsonl (desired) +
               managed_runtime/instances.jsonl (observed); run_record 仅历史证据
DEPLOYMENT = deployments.jsonl latest-event-wins; one deployment per agent;
             desired_state = RUNNING | STOPPED | REVOKED
RUNTIME_INSTANCE = instances.jsonl latest-event-wins; instance_id /
             deployment_id / agent_id / version_id /
             execution_snapshot_identity / observed_state / started_at /
             stopped_at / failure_reason
DESIRED_STATE = RUNNING / STOPPED / REVOKED
OBSERVED_STATE = READY / STARTING / RUNNING / STOPPING / STOPPED / FAILED /
             REVOKED 已实现; DEPLOYING / PENDING / UNKNOWN 为 contract
RECONCILIATION = Desired vs Observed diff -> START / STOP / NO-OP /
             VERSION_DRIFT / REJECT / RECONCILE_REQUIRED
START = version not revoked + snapshot binding OK -> verify_at_mount ->
             runtime start -> RUNNING / FAILED
STOP = STOPPING -> runtime stop -> STOPPED / FAILED(failure_reason)
IDEMPOTENCY = RUNNING+RUNNING -> NO-OP (1 active instance); STOPPED+STOPPED ->
             NO-OP (no duplicate stop); set_desired_state same value -> NO-OP
VERSION_DRIFT = desired v17 + observed v16 RUNNING -> VERSION_DRIFT
             (not HEALTHY); no auto-upgrade in Stage 1
SNAPSHOT_BINDING = CLOSED (instance identity == version identity ==
             E(candidate_id, artifact_digest, seal_digest); mismatch -> REJECT)
PHASE_9_REGRESSION = PASS (160 baseline; 170 with Phase 10.3; 437 full)
LIVE_RUNTIME = UNAVAILABLE (docker daemon down; real pilot entry legacy)
NEXT_PHASE = Stage 2: Upgrade / Rollback / Revoke lifecycle completion +
             legacy migration + real process supervisor
```

## Findings

1. `DockerRuntime` 代码已实现但未 live 验证；daemon 可用 + canonical store
   部署（含 runtime user != store owner，Phase 9 OWNER_ISOLATION 仍 OPEN）
   后才能验收。
2. 真实 pilot state 是 legacy entry：`create_version` 直接拒绝；
   live 闭环需要先完成 legacy migration（MIGRATION_REQUIRED，独立阶段）。
3. 真实状态源是 JSONL latest-event-wins，单进程假设；多进程并发写需要
   文件锁/CAS（未来阶段，不阻塞 Stage 1）。
