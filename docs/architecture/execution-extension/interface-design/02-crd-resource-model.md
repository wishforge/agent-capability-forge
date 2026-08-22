# 02 — Kubernetes CRD Resource Model

## CRD decision

只定义三个 logical CRD：`AgentRun`、`AgentBinding`、`ArtifactReference`。`Attempt`、`BindingEpoch`、`Recovery`、Supervisor observation 不自动各建 CRD；它们是 `AgentRun.status` 的 observed history/reference，必要时由 API subresource 查询。内部对象不自动等于 Kubernetes reconciliation unit。

| CRD | Reconciliation purpose | Spec | Status |
|---|---|---|---|
| AgentRun | desired execution and lifecycle commands | target, intent, constraints, retry/resume/cancel policy, artifact references | Run phase, current Attempt refs, durable recovery/verification facts, conditions, observed generation |
| AgentBinding | desired binding admission/configuration | agent/provider intent, capability and isolation requirements | compatibility decision, active/stale epoch refs, observed facts |
| ArtifactReference | desired/declared artifact input or output reference | kind, locator/claim, integrity/trust requirements | identity, provenance refs, integrity observations, trust verdict |

`AgentRun` controller 是主要 Supervisor reconciliation surface；`AgentBinding` controller 只负责 binding admission/epoch observation；`ArtifactReference` controller 负责 reference/integrity/trust observation，不拥有 world-state compensation。

## Run vs Attempt

一个 `AgentRun` 表达一个 Run。每次 managed retry/resume 都在 status history 中追加一个 Attempt reference；不把 Attempt identity 复用为 CR object identity，也不通过 spec 数字字段伪造状态机。Attempt 的完整 durable record 由 Runtime persistence owner 保存。

`BindingEpoch` 通过 status reference 与 immutable snapshot digest/identity exposed；不允许用户更新 active epoch。跨 epoch 必须建立新 Attempt。

## Desired vs observed

`spec` 只表达 desired intent/policy：目标、绑定选择约束、isolation、artifact requirements 与 command policy。`status` 表达 observed/durable runtime state：`PENDING/STARTING/RUNNING/WAITING/UNKNOWN/RESOLVING/terminal`、receipt、verification、compensation、epoch、handle freshness 与 conditions。

`UNKNOWN` 永远只出现在 status/recovery history；不能写入 spec，也不能因 controller 重启清除。status 更新需带 Kubernetes `observedGeneration` 与 Runtime semantic version，防止 stale controller 覆盖新事实。

## Actions and controller boundary

start/retry/resume/cancel/verify/reconcile 是 API commands，controller 只消费已持久化 command/intent 并写 status；controller 不直接成为 Attempt owner。删除策略必须先走 cancel/termination policy；删除对象不等于成功取消 side effect。
