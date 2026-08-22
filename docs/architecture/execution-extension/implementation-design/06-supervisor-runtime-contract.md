# 06 — Supervisor Runtime Contract

`ARCHAEOLOGY EVIDENCE`：既有项目提供局部 restart/resume/repair；通用 reconciliation authority 是 `DESIGN DECISION`。

Supervisor 是 Runtime 内的 reconciliation authority，不是第二个 Attempt owner，也不是 provider executor。

## Inputs and outputs

输入：durable Run/Attempt/BindingEpoch/Artifact/Recovery state、Extension observations、wakeup/failure signals、lease/heartbeat/timeout evidence。

输出：reconcile decision，例如继续观察、restart live primitive、标记 UNKNOWN/RESOLVING、创建新 epoch/new Attempt、verify、compensate、terminate 或 human gate。每个输出先写 durable decision，再调用 Extension primitive。

## Loop

```text
read durable state + observations
  → detect drift / stale handle / missing fact
  → classify recoverable | UNKNOWN | terminal
  → persist decision
  → execute primitive or verification/compensation
  → record observation and reconcile again
```

## Boundaries

Supervisor 可以安排新 Attempt，但不能 mutate old Attempt identity、旧 epoch 或 artifact content；不拥有 process/session/provider internals。进程重启只代表 live primitive 被重启，不代表 Run/Attempt 已恢复。遇到 crash、disconnect、event loss、stale binding、artifact mismatch、stuck Attempt 时，先保留证据不足语义，再按 recovery policy 处理。

Supervisor 的 observation 可按部署需要 durable；影响语义的 observation、decision、receipt、verification、compensation history 必须交 Runtime durable owner 记录。retry/cleanup/termination/人工审批预算属于 `OPEN PARAMETER`。
