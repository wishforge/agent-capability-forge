# 06 — Evaluation Boundary Report（Phase 5-G）

> 阶段：Phase 5-G。Execution Record → Evaluation 边界冻结完成。
> 产物：`04-execution-record-contract.md`、`05-evaluation-input-contract.md`。
> 本阶段未实现 Evaluation Engine / Judge / Scoring / Regression / Promotion，
> 未修改 Runtime semantics。

---

## 1. 核心结论

```text
Execution Runtime
    ↓
Immutable Execution Record（Event Log 的 evaluation-facing 投影）
    ↓
Evaluation Input（ExecutionRecord + Task Spec + Oracle ref）
    ↓
Evaluation（本阶段不实现）
```

Event Log 是唯一 source of truth；ExecutionRecord 是派生投影，不是第二
source of truth，不反向修改 Runtime。

---

## 2. 数据可用性总表

| 事实 | 来源 | 状态 |
| --- | --- | --- |
| Session/Turn/Step 边界 | Event Log | VERIFIED |
| Attempt 树（execution/attempt/parent/status） | Event Log + replay | VERIFIED |
| Tool call / result / error | Event Log | VERIFIED（部分字段 PARTIAL） |
| Event 级血缘（source_event_seqs） | Event Log | VERIFIED |
| Backend raw 引用 | BackendEventRef | VERIFIED |
| Lossiness | BackendMetadata | VERIFIED |
| 模型可见 surface 重建 | Surface 投影 | PARTIAL（determinism INFERENCE） |
| 完整 context provenance | request/header + surface | PARTIAL / REQUIRED EXTENSION |
| Initiator 归因 | durable surrogate 不足；ambient 不持久化 | PARTIAL / REQUIRED EXTENSION |
| Ownership refs | 运行时 registry，不落事件 | PARTIAL / REQUIRED EXTENSION |
| Authorized principal | 事件层无字段 | OPEN |
| Cost / usage | 统一事件无；Codex raw 有 | UNKNOWN（只允许引用） |

---

## 3. 十二问回答

### 1. ExecutionRecord 是什么？

Event Log 的 immutable evaluation-facing 投影：逻辑层次
Execution → Attempts → Steps → Events → Tools → Backend References →
Outcome，附 Ownership / Causality / Context provenance / Replay reference /
Lossiness。只引用 raw event，不复制。

### 2. 为什么不是第二 source of truth？

它是派生视图：same log + same projection rules ⇒ same record；record 与
log 冲突时以 log 为准；record 不可变、无写回路径，Runtime 不消费它做决策。

### 3. Evaluation 最少需要哪些执行事实？

边界身份（session/turn/step/execution/attempt）、事件引用、tool
call/result + error、attempt 状态、backend refs、lossiness、可重建的
context provenance、outcome 证据、replay ref。Expected Outcome 由 Task
Definition 提供，不属于 Runtime 事实。

### 4. Runtime 与 Evaluation 的边界在哪里？

Runtime 负责“怎么执行”，Evaluation 负责“执行得怎么样”；中间隔着不可变的
ExecutionRecord。Evaluation 对 Runtime 全部 READ ONLY，只能经 record +
raw ref 读证据，不能修改任何 runtime 状态，不依赖 ambient ContextVar。

### 5. Context provenance 是否足够？

**PARTIAL**。模型可见消息可由 surface 重建；但完整 request-time context
（system / runtime_context / current_input）未持久化，derive_messages
确定性只是 INFERENCE。contract 标 PARTIAL / REQUIRED EXTENSION，不假设。

### 6. Tool evidence 是否足够？

**PARTIAL（核心足够，扩展不足）**。identity / arguments / result / is_error /
event refs / backend refs 全部 VERIFIED；owner ref、authorization、
concludes_turn / additional_contexts 未持久化；Codex exec success 固定
true（LOSSY）。

### 7. Causality 是否足够？

**PARTIAL**。durable 层（source_event_seqs、attempt parent 链接、call tree）
VERIFIED 且 replay 可重建；但 initiator durable ref 不存在（Codex LOSSY），
session header lineage 未持久化（Phase 4-B A11）。契约强制 Evaluation 只用
durable refs。

### 8. Ownership 是否足够？

**PARTIAL**。owner ≠ initiator ≠ principal 已冻结；但 owner 只在 runtime
registry（ToolRegistration.owner / Capability→Scope→Effect），不落事件；
Codex 为 BACKEND_SPECIFIC。需要 owner_ref 扩展点才能让 Evaluation 回答
“消耗了谁的能力”。

### 9. Lossiness 是否足够？

**VERIFIED**。BackendMetadata（mapping_quality + missing_semantics +
backend_event_ref）持久化且 replay-aware；Codex 六项 / AgentScope 三项清单
可枚举。LOSSY 不得当 EXACT 用。

### 10. Replay 是否可以重建 Evaluation input？

**可以（语义级）**。same execution + replay ⇒ same semantic record；attempt
identity 稳定，不重执行。raw backend representation 允许不同，但必须可回源；
ambient 状态不恢复。Task Spec / Oracle 在 replay 外，由 Evaluation 持有。

### 11. AgentScope/Codex 是否都可以提供 Evaluation input？

**可以**。两个 backend 都产生统一事件（含 attempt / tool / backend ref /
metadata，Phase 5-D/5-F 已验证），可投影为同一 EvaluationInput 形状；差异
显式标记为 ADAPTER / LOSSY / BACKEND_SPECIFIC，语义层可复用。

### 12. 最大的 Evaluation data gap 是什么？

**Causality / Ownership 的 durable refs（initiator_ref / owner_ref）尚未写入
Event Log**：Evaluation 无法从 replay 可靠回答“谁导致执行、消耗了谁的能力”。
次大缺口是完整 context provenance（request-time 快照未持久化）与
usage/cost（统一层 UNKNOWN）。

---

## 4. 最终判定

**PASS** — Phase 5-G 契约冻结完成。

- ExecutionRecord 定义为 Event Log 的 immutable evaluation-facing
  projection，不成为第二 source of truth；
- Evaluation 与 Runtime 之间只读边界冻结；EvaluationInput 与 Expected
  Outcome / Verification 解耦；
- ExecutionAttempt、Tool evidence、durable causality、lossiness、replay
  均进入 Evaluation 可见范围；
- AgentScope / Codex 均可产生 Evaluation input；无需修改 Core execution
  semantics；
- 未实现 evaluator / judge / scoring / regression / promotion / UI。

契约内显式保留的 PARTIAL / REQUIRED EXTENSION：

```text
initiator_ref
ownership_refs
context provenance（完整 request-time 快照）
authorized principal
cost / usage（统一层）
```

这些字段由后续阶段决定是否扩展；本阶段不实现。
