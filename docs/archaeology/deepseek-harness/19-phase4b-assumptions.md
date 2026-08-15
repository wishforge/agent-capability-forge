# 19 — Phase 4-B Implementation Assumptions

> 阶段：Phase 4-B（最小 append-only persistent event store：JSONL + replay + resume）
> 引用：13 Event Sourcing / 14 Turn-Step / 15 Tool Waterfall / 16 Causal Chain / 17 Semantic Runtime Model / 18 Phase 4-A Assumptions
> 状态词：DSH VERIFIED / DSH PARTIAL / DSH UNKNOWN / PHASE-4B DESIGN
>
> 以下每一项都是 Phase 4-B implementation contract，不是 DSH facts。
> PASS 只代表 Phase 4-B 最小 scope 完成，不代表完整 DSH durability / replay / resume semantics。

## 必需 Assumptions（A1–A10）

| # | Assumption | 状态 | 说明 |
| --- | --- | --- | --- |
| A1 | physical fsync semantics：`flush()` 只 flush 到 OS，`flush != fsync`；JSONL write success ≠ durable fsync；不声明崩溃后的物理落盘保证。 | DSH UNKNOWN（13 §12-2）；PHASE-4B DESIGN | `event_store.py` 已按此措辞标注。 |
| A2 | JSONL serialization compatibility：每行一个 UTF-8 JSON SessionEvent，`sort_keys` 稳定字段序；payload 经 JSON 归一化（tuple 值 → list）；无版本字段/迁移（见 A10）。 | PHASE-4B DESIGN | DSH 有 JSONL persistence 插件（VERIFIED），但字段级格式兼容性未在本阶段比对。 |
| A3 | tail repair policy：`open()` 加载最长完整前缀；`repair_tail()` 从首个无效行（JSON 解析失败 / seq 不连续 / session 不匹配 / 未终止行 / 空行）起截断；保留最后一个完整 event 并恢复正常 append。 | PHASE-4B DESIGN | DSH crash repair 是合成闭合事件（VERIFIED，05 §1），不是截断；截断是 Phase 4-B crash-tail repair implementation behavior。 |
| A4 | tool outcome unknown reconstruction：`tool/call` 无 `tool/result` → 标记 `TOOL_OUTCOME_UNKNOWN`；`TOOL_NOT_STARTED` 定义但从不判定，因为 Phase 4-A 没有持久化 execution-started marker。 | DSH 两状态存在性 VERIFIED（05 §1；13 §8）；精确判定边界 DSH UNKNOWN（13 §12-10）；PHASE-4B DESIGN | 修复合成 `tool/result`（`is_error`，`error_code=TOOL_OUTCOME_UNKNOWN`）。 |
| A5 | resume point semantics：安全恢复点 = 最后一个 completed turn 之后；中断 turn 先合成 `tool/result → step/end → turn/end{interrupted}`，再以新 turn 继续确定性 mock 执行；未决工具永不重跑。 | DSH 合成闭合 VERIFIED（15 §11）；完整 resume 重建路径 DSH PARTIAL/UNKNOWN（13 §12-8）；PHASE-4B DESIGN | 不伪装成 exact DSH resume behavior。 |
| A6 | fork omitted：本阶段不实现 fork、不定义 API seam 之外的机制；保留 open question：fork 是复制 event data 还是 reference/prefix lineage。 | DSH UNKNOWN（13 §12-3；10 §2）；PHASE-4B DESIGN | 不自行决定成 DSH fact。 |
| A7 | cross-backend ordering omitted：只有单一 JSONL backend，不声明跨 backend 顺序一致性。 | DSH UNKNOWN（13 §12-6）；PHASE-4B DESIGN | 无第二个 backend 可比较。 |
| A8 | persistence transaction atomicity：无事务；每次 append 是单行写入；撕裂写由 A3 tail repair 处理。 | DSH compaction 事务标记存在但原子性 UNKNOWN（13 §12-5 / COMP-03）；PHASE-4B DESIGN | 不声明多行/多事件原子性。 |
| A9 | replay deterministic boundary：`replay()` 是纯事件投影（不重跑模型/工具）；same log + same code ⇒ same ReplayHistory。 | DSH 事件级 replay VERIFIED（13 REPLAY-01）；跨版本/重跑确定性 DSH UNKNOWN（13 §12-4）；deriveMessages determinism 为 INFERENCE（13 ES-04）；PHASE-4B DESIGN | 只保证本实现投影确定性。 |
| A10 | event schema evolution omitted：无版本号、无迁移；`_decode` 按当前字段读取，缺字段用默认值。 | PHASE-4B DESIGN | 未来 schema 变化不属于本阶段。 |

## 附加实现记录（同样不是 DSH facts）

| # | Assumption | 状态 |
| --- | --- | --- |
| A11 | session header lineage persistence omitted：`parent_session / delegation_depth / seed_length` 只存在于 Phase 4-A `Session` 对象，从不写入事件；`rebuild_session()` 只恢复 `session_id`。 | DSH header lineage 持久化 VERIFIED（16 §3）；Phase 4-A Python compatibility model 不持久化（18 A14）；PHASE-4B DESIGN |
| A12 | `agent/request → request/header` durable surrogate：落盘时把 runtime-only 的 `AGENT_REQUEST` 写成 `REQUEST_HEADER`（18 A10 / 17 §4 REQUIRED）；reload 后事件类型为 `request/header`，live 内存中仍为 `agent/request`。 | PHASE-4B DESIGN；不是完整 DSH `request/header` 语义 |

## 结论

Phase 4-B PASS 只覆盖最小 scope：JSONL append-only、序列连续、tail repair、
session/surface 重建、replay、`TOOL_OUTCOME_UNKNOWN` 修复、restart/resume。
A1–A12 覆盖的边界（fsync、跨 backend 顺序、fork、事务原子性、schema 迁移、
TOOL_NOT_STARTED 判定、header lineage 持久化）全部保留为
PHASE-4B IMPLEMENTATION ASSUMPTION，不进入下一阶段作为已证明事实。
