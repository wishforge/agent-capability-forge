# 05 — Recovery Runtime Contract

`ARCHAEOLOGY EVIDENCE`：既有材料支持 receipt/probe/undo 等局部能力以及 UNKNOWN 的边界；以下 authority、状态映射与 append-only recovery record 是 `DESIGN DECISION`。

Runtime semantic state 与 Extension execution state 分离：Extension 只能报告执行事实；Runtime 产生 durable outcome/recovery state；Supervisor 负责 orchestration。

## Facts and states

`SUCCESS` 表示结果及要求的事实可信；`FAILURE` 表示明确不能完成但不表示无副作用；`UNKNOWN` 表示证据不足；`VERIFIED` 表示 probe/receipt/audit 得到的 world-state fact；`COMPENSATED` 表示 compensation 已执行并达到 policy 目标。

## Contract

| Question | Authority | Required record |
|---|---|---|
| 产生 UNKNOWN | Runtime，根据 Extension observation、丢失/冲突事实 | cause、boundary、last known fact、Attempt/epoch |
| 触发 verification | Supervisor 按 Runtime recovery policy | probe/receipt/audit request 与 freshness |
| 记录 receipt | Runtime durable journal；Extension/tool 提供原始 receipt | operation identity、source、trust/verification status |
| 提供 idempotency/dedup identity | tool/Extension contract；Runtime 记录并施策 | operation identity/key、scope、expiry（如适用） |
| 请求 compensation | Runtime 作 durable decision，Supervisor 编排，Extension 执行 primitive | authorization、undo operation、result、verification |

默认流程：`UNKNOWN → RESOLVING → observe/verify → VERIFIED → derive outcome | safe retry | compensation | human gate | terminate`。未解决 UNKNOWN 禁止 blind retry；无 receipt/probe 时不得伪造 SUCCESS；无安全 compensation 时不得自动补偿。`COMPENSATED` 不表示原副作用从未发生。

## Recovery record boundary

每次 decision 都追加 RecoveryRecord，不覆盖原 observation。Recovery decision 必须关联 Run、Attempt、epoch、operation identity（若有）、证据与 policy version。Tool-specific receipt/probe/undo 能力是 optional adapter facts，不是 Runtime 自动保证。

`OPEN PARAMETER`：tool-class receipt/operation journal contract、probe freshness、verification timeout、compensation budget、人工 gate policy、receipt retention。
