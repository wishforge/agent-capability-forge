# 18 — Phase 4-A Implementation Assumptions

> 阶段：Phase 4-A（Minimal Python DSH Runtime Skeleton）
> 引用：13 Event Sourcing / 14 Turn-Step / 15 Tool Waterfall / 16 Causal Chain / 17 Semantic Runtime Model
>
> 以下每一项都是 **PHASE-4A IMPLEMENTATION ASSUMPTION**，不是 DSH facts，
> 不是 Phase 3 契约的 VERIFIED 语义。把它们写成 assumption 是 Phase 4-A 的
> 显式要求（17 §12 PASS 条件），不得在后续阶段伪装成已证明语义。

## 必需 Assumptions（A1–A8）

| # | Assumption | Phase 3 状态 | 说明 |
| --- | --- | --- | --- |
| A1 | EventStore durability：只实现内存版，无 JSONL / SQLite / Redis / fsync / crash recovery。`event_store.py` 中明确标注 `DURABILITY: PHASE-4A ASSUMPTION`。 | 13 §12-2 UNKNOWN（flush 精确 durability 无证据） | Phase 4-A 不声明任何 durability 边界。 |
| A2 | cross-backend event ordering：只有一个内存 backend，不声明跨 backend 顺序一致性。 | 13 §12-6 UNKNOWN | 无持久化 backend 可比较。 |
| A3 | derive_messages determinism：same event history + same projection rules ⇒ same messages，作为本实现假设；不写 “DSH guarantees deterministic deriveMessages”。 | 13 ES-04 INFERENCE（实现级纯投影，无显式保证） | `surface.py` 中已按此措辞标注。 |
| A4 | fork copy/reference：不实现 fork；`snapshot()` 返回不可变事件元组（frozen dataclass，读取时复制）。 | 13 §12-3 UNKNOWN（只有 fork 入口，无机制证据） | 不声明 fork 复制或引用语义。 |
| A5 | compaction omitted：不实现 compaction / prune / replace；日志只追加。 | 13 COMP-01..04 VERIFIED（DSH 侧） | Phase 4-A 不实现投影替换，不是 DSH 没有。 |
| A6 | capability event domain omitted：capability install/dispose 不写入 SessionEvent；ownership 只在 runtime 侧经 EffectRegistry 演示。 | 13 §13.3 / 17 §4 OPEN QUESTION | 不替 Phase 3 未决问题定 schema。 |
| A7 | dispose-mid-call behavior：不实现 `Capability.dispose()` 与 in-flight Tool Call 并发；语义视为未定义。 | 17 §8-3 OPEN QUESTION | 无契约/测试前不得自行设计。 |
| A8 | authorization persistence omitted：approval / guard 是 runtime-only seam；不落 `approval/asked`、`approval/decided`、`permission/preset`、`sandbox/mode` 等事件。 | 15 §3/§4（DSH 有 policy 事件） | Phase 4-A 只证明 owner ≠ initiator ≠ authorization 概念分离，不持久化授权。 |

## 附加实现记录（同样不是 DSH facts）

| # | Assumption | Phase 3 状态 |
| --- | --- | --- |
| A9 | `user/message` 事件在 `turn/start` 之前追加。契约固定了 `turn/start → step/start → … → turn/end`，但未固定 user/message 相对 turn/start 的位置。 | 14 §1/§3 无直接冲突 |
| A10 | `agent/request` 作为内存 trace 事件追加。17 §4 明确 agent/request 是 runtime-only、不得作为 durable SessionEvent；Phase 4-A EventStore 只有内存，不构成 durable 写入。若未来加持久化 backend，`agent/request` 必须改走 `request/header` 语义。 | 17 §4 REQUIRED（保持 runtime-only） |
| A11 | 显式 `turn_id` / `step_id` 字段是 Python 扩展；DSH 用数字 turn/step + 事件嵌套顺序。 | 14 §9 Unknown #4；16 §13.2 DESIGN PROPOSAL |
| A12 | `NEW / ACTIVE / ENDED` 是 Phase 4-A runtime 状态，不是 DSH 原生 Step 状态机。 | 14 §7 DESIGN_PROPOSAL |
| A13 | initiator 是 `InitiatorContext(agent_id)` 对象 + `contextvars.ContextVar`；DSH 是 live Agent 对象 + AsyncLocalStorage。ambient initiator 不持久化。 | 16 §1/§2 VERIFIED（机制） / NOT FOUND（持久化） |
| A14 | `parent_session / delegation_depth / seed_length`（Session metadata）与 `root_call_id / parent_call_id`（ToolCall）是 **PHASE-4A COMPATIBILITY MODEL**：只作元数据/显式字段，无 fork/resume/嵌套执行。 | 16 §3/§5 VERIFIED（DSH 字段存在）；Phase 4-A 不实现其完整语义 |
| A15 | 同一 Step 的多个 tool call 顺序执行；DSH 支持 `isConcurrencySafe` 并行（默认 max 10）。 | 15 §5 VERIFIED；Phase 4-A 不做并发 |
| A16 | 内部 scheduler/runtime 异常 → `step/end`（finally）+ `turn/end{error}`；tool failure 永不升级为 step/turn failure。 | 15 §11 VERIFIED；aborted/error step/end 已由 15 §6 确认 |
| A17 | `concludes_turn` / `additional_contexts` 是运行时 ToolResult 字段，不写进 `tool/result` 事件；additional contexts 的持久化载体是下一步 `user/message` 事件。 | 15 §1/§10 PARTIAL；15 §12 VERIFIED（载体） |
| A18 | timeout / cancellation 错误码使用 `TOOL_TIMEOUT` / `ABORTED` / `ABORTED_BEFORE_DISPATCH`，与 DSH 命名一致。 | 15 §6/§11 VERIFIED |

## 结论

Phase 4-A runtime 只对“本实现可证明”的语义给出 PASS；A1–A18 覆盖的边界
（durability、跨 backend 顺序、deriveMessages 确定性、fork、compaction、
capability 事件域、dispose-mid-call、授权持久化等）全部保留为
PHASE-4A IMPLEMENTATION ASSUMPTION，不进入下一阶段作为已证明事实。
