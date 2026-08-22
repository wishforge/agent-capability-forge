# 02 — Attempt Runtime Contract

`DESIGN DECISION`：Attempt 是 Runtime 归因的一次 execution boundary；创建、转移和 terminal 归因只由 Runtime semantic authority 执行。Supervisor 提交 reconciliation decision，不能直接改写状态。

## Creation contract

Runtime 创建 `PENDING` Attempt，必须同时指定 Run、immutable Binding Epoch、execution intent reference、capability/isolation decision reference 和 lineage。创建不表示 Extension 已启动。

## Transition contract

| Transition | Actor | Preconditions | Durable fact | Forbidden shortcut |
|---|---|---|---|---|
| `PENDING → STARTING` | Runtime admission | epoch active、capability/isolation compatible、无冲突 active admission | dispatch admitted | 未 admission 先调用 Extension |
| `STARTING → RUNNING` | Runtime | Extension 返回可归因 live execution observation | handle/session observation | 仅凭 start request |
| `RUNNING ↔ WAITING` | Runtime | 外部事件/工具/人工 gate 使执行暂停或恢复 | wait reason/fact | 把等待当成功 |
| active → `SUCCEEDED` | Runtime | result、所需 artifact/side-effect facts 足够可信 | terminal success | 仅凭 exit code/字符串 |
| active → `FAILED` | Runtime | 明确不能完成且不是证据不足 | failure reason; side-effect uncertainty retained | crash 自动等同失败 |
| active → `CANCELLED` | Runtime | cancellation accepted and termination attributed | cancellation/termination fact | 请求取消即宣称完成 |
| active → `UNKNOWN` | Runtime | crash、disconnect、event loss、timeout、stale handle 或事实冲突使边界不可判定 | UNKNOWN cause/boundary | 自动重放或清零副作用 |
| `UNKNOWN → RESOLVING` | Runtime | recovery policy starts | recovery record opened | 直接覆盖为 FAILED |
| `RESOLVING → terminal/new Attempt` | Runtime | verification/receipt/compensation/human decision recorded | decision and evidence | 未记录证据先 retry |

## Identity and crash

`attempt_id` 在任何 transition、retry、resume、reconnect、process restart 中不变；`execution_handle`、process id、session id 只表达一次 live observation。transport retry/reconnect 在同一 boundary 且语义不变时可留在同一 Attempt；managed retry、resume、fork、binding migration 默认创建新 Attempt。

process crash、session disconnect、transport loss 先产生 observation。能证明原 boundary 和副作用连续时可恢复 observation；否则旧 Attempt durable 为 `UNKNOWN`，Supervisor 先 resolve。旧 identity 不复用。

## Invariants

Attempt 恰好属于一个 Run、恰好引用一个 immutable BindingEpoch；terminal Attempt 不回到 active；新 Attempt 不覆盖旧 Attempt 的结果、receipt、UNKNOWN 或 identity。

