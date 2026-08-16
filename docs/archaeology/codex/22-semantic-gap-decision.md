# 22 — Semantic Gap Decision（Phase 5-B）

> 目标：Phase 5-B 唯一目标——把 Phase 5-A 暴露的 Semantic Gaps 分类为
> A. Adapter problem / B. Lossy mapping / C. Backend-specific semantics /
> D. Unified Runtime extension point / E. True Unified Semantic Gap。
> 本文件只做设计判定，不实现 Codex Adapter，不修改任何 contract / runtime。
> 基线：Codex `279b93242cfef379e65da97e87e44b83c5934fd7`、DSH `47f943859bef60e4160492346772ded9b24f765a`、python-cordis Phase 2。
> 证据：20 / 21 / 13-17 / python-cordis 12-13 / 18 / 19 / 25；不重新考古。
> 状态词：ADAPTER_ONLY / LOSSY_ACCEPTABLE / BACKEND_SPECIFIC / UNIFIED_EXTENSION_POINT /
> TRUE_SEMANTIC_GAP / BLOCKED

---

## 0. 结论摘要

1. 六个主要 Gap 无 TRUE_SEMANTIC_GAP、无 BLOCKED：

   - Step Boundary → **ADAPTER_ONLY**（合成 Step 边界；compaction retry 为 LOSSY 子项）
   - Tool Error Semantics → **LOSSY_ACCEPTABLE**
   - Crash Unknown Outcome → **ADAPTER_ONLY**（保守 inference，非原生 marker）
   - Capability / Ownership → **BACKEND_SPECIFIC**（+ UNIFIED OVERLAY）
   - Initiator / Causality → **LOSSY_ACCEPTABLE**（durable lineage 可映射；ambient 不要求）
   - Compaction Retry Identity → **UNIFIED_EXTENSION_POINT**（ExecutionAttempt）

2. Codex Adapter 可以在不修改 Semantic Core contract 的前提下实现；实现前必须先修复
   21 BP-01 的 runtime.py 装配 seam（adapter interface）。这是装配层问题，不是语义层问题。
3. 最终状态：**PARTIAL**，不允许 PASS。

---

## 1. Semantic Gap Decision Matrix

| Gap | Backend fact | Unified requirement | Classification | Reason | Adapter strategy |
| --- | --- | --- | --- | --- | --- |
| Step Boundary | 无持久化 Step 对象；`StepContext` 是单次 sampling request 快照；一次公开 Turn（Task）可含多次 sampling request；compaction 后开启新 sampling request（20 §2/§7） | Turn → 0..N Step；Step = 一次模型请求 + 该请求的工具活动；retry 在同一 Step 内重建请求（14 TURN-02；21 CTX-07） | ADAPTER_ONLY | 一次 sampling request 是稳定、可复现的运行时边界，Adapter 能从 rollout 顺序重建 Step；无原生 step 事件导致精确边界有损，但不改变 Unified 语义 | 按 sampling request 分段构造 Step；`step_id` 标记为 adapter-derived；compaction 后新 sampling request = 新 Step，retry 关系写 metadata 或 ExecutionAttempt |
| Tool Error Semantics | exec `exit_code` 结构化但 `success` 固定 true；MCP 用真实 success；cancel `success=None`；fatal 终止 turn；无统一工具错误 taxonomy（03 §2.2；20 §4） | `ToolResult(is_error)` + 明确 tool failure boundary（tool failure ≠ step/turn failure）（15 TW-06） | LOSSY_ACCEPTABLE | Adapter 可按工具类型归一化（exit_code / success=false / cancel / timeout → is_error）；主语义保留；错误原因粒度有损，fatal 边界单独暴露 | 按工具类型归一化：exec 用 `exit_code != 0` → is_error + reason；保留 raw output；fatal → `turn/end{error}` + lossiness；approval reject → tool-level is_error（文本） |
| Crash Unknown Outcome | 无 `TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN` 原生 marker；中断只写 interrupted marker + `TurnAborted`（20 §8；05 §2.7） | 有 call 无 result → `TOOL_OUTCOME_UNKNOWN`；`TOOL_NOT_STARTED` 判定边界本身是 UNKNOWN（13 §8/§12-10） | ADAPTER_ONLY | Adapter 能对“中断 turn + 未闭合 call”保守合成 `TOOL_OUTCOME_UNKNOWN`；无法可靠区分 NOT_STARTED，但 Unified 自身也不宣称该判定，不构成 true gap | ADAPTER/INFERENCE：unmatched call + interrupted turn ⇒ `TOOL_OUTCOME_UNKNOWN`；禁止写成 Codex 原生支持；raw ref 保留 |
| Capability / Ownership | 资源由 session-scoped `SessionServices` 持有（MCP / process / approval / skills）；无 Capability/Scope/Effect（20 §5；python-cordis 12-13） | Capability → Scope → Effect 是 runtime-owned lifecycle truth（17 §2 OWNS） | BACKEND_SPECIFIC | Codex backend ownership 与 Unified ownership 是两个并存生命周期域；不能把工具贡献者自动映射为 Capability | 只把 Codex 工具可见性翻译为 backend 快照；不推导 owner；不实现 Capability；Unified Capability Runtime 在 backend 外围做 overlay |
| Initiator / Causality | durable thread lineage（`forked_from_id` / `parent_thread_id` / `InterAgentCommunication`）存在；无 ambient initiator（20 §6） | ambient initiator（runtime）+ durable lineage（replay）（16；17 UN-10/11） | LOSSY_ACCEPTABLE | 跨 backend 的可重放语义只需要 durable lineage；Codex 的 lineage 可映射；ambient 缺失不损失统一 replay 语义（ambient 本身不随 replay 恢复），不发明 `initiator_id` | SessionMeta / InterAgentCommunication → unified lineage；initiator 标 UNKNOWN 或由 live runtime overlay 设置；durable 层不伪造 |
| Compaction Retry Identity | compaction → 新 sampling request → 新 Step（新 `StepContext`）（20 §7.1 Q9） | context overflow → compaction → retry = 同一逻辑执行（同一 Step 重建请求）（21 CTX-07） | UNIFIED_EXTENSION_POINT | Unified Core 只在“同 Step retry”表达重试身份，没有跨 Step 的 retry identity；Adapter 保留原生 Step 边界则丢失身份，强行合并则改 Step 语义；需要 ExecutionAttempt 扩展点（不改 Turn/Step） | 保留原生 Step 边界；用 `ExecutionAttempt { parent_execution_id, attempt_no }` 连接 pre/post compaction；本阶段只定义契约，不实现 |

---

## 2. Gap 1：Step Boundary

1. **sampling request 是否可稳定作为 Step？** 是（运行时稳定）：一次 `run_sampling_request` 完整周期 = model stream + tool activity + drain；但 rollout 无 step/start-end 事件，Step 是 Adapter 构造值（20 §2 Q5）。
2. **同一 Turn 是否可能多个 sampling request？** 是：公开 Turn（Task）内 `run_turn` 可迭代多次 sampling request，每个捕获新 `StepContext`（20 §2）。→ 对应 Unified 一 Turn 多 Step。
3. **Tool call 是否一定归属于对应 sampling request？** 运行时是（in_flight per request）；持久化只有 call_id + turn_id（exec/approval 事件），无 step_id，归属靠顺序推导（ADAPTER/INFERENCE）。
4. **Compaction retry 产生新 sampling request：** 是同一个 Step 的 retry 还是新 Step？Codex 事实：新 sampling request = 新 `StepContext`，Adapter Step 边界 = **新 Step**。Unified 期望同一逻辑执行 → 差异由 metadata / ExecutionAttempt 暴露，不合并 Step。
5. **Replay 是否可稳定重建这个 Step？** 可以，但重建的是 “adapter-derived Step 序列”：同一 rollout + 同一构造规则 ⇒ 同一序列；不是 Codex 原生 step 事件。

**判定：ADAPTER_ONLY。** 不改 Unified Turn/Step。

---

## 3. Gap 2：Tool Error Semantics

1. **Codex error 是否总能转换成 `ToolResult(is_error)`？** 否（EXACT 不可能）：exec 非零 exit code 可转（`exit_code` 字段存在），但 `success` 固定 true；部分失败只有文本；fatal 是 turn 级终止。
2. **是否存在 information loss？** 有：错误 taxonomy、拒绝原因、timeout 标记需要从文本/事件推断；raw output 保留可回源。
3. **failure reason 能保留到什么粒度？** runtime 层 `CodexErrorDetails` 有分类（模型流/传输）；工具层无统一 taxonomy。Adapter 输出粗粒度 reason（`EXIT_CODE` / `TOOL_FAILED` / `ABORTED` / `TIMEOUT` / `APPROVAL_REJECTED` / `FATAL`）+ raw text。
4. **retry / recovery 是否受影响？** 工具失败继续 turn 的语义可保留；fatal 会终止 turn，Adapter 必须显式标 backend-specific；retry 决策权在模型，不影响 `ToolResult(is_error)` 本身。

**判定：LOSSY_ACCEPTABLE。** Unified Runtime 不丢失主语义（失败边界、tool failure ≠ turn failure），允许 backend error metadata loss；fatal 边界进 lossiness 清单。

---

## 4. Gap 3：Crash Unknown Outcome

- A. **Adapter 可根据 rollout/history inference**：部分可——中断 marker + 未闭合 call 足以保守合成。
- B. **无法可靠判断**：`TOOL_NOT_STARTED` vs `TOOL_OUTCOME_UNKNOWN` 无法区分；副作用是否发生不可知。
- C. **需要 Codex backend-specific recovery layer**：精确区分需要原生 execution-started marker（不存在）；恢复层只能在统一侧保守标记。

**判定：ADAPTER_ONLY（conservative）。** 规则：

- call 无 result + turn interrupted ⇒ 合成 `tool/result`（is_error，`error_code=TOOL_OUTCOME_UNKNOWN`）；
- 永不输出 `TOOL_NOT_STARTED`（无判定依据）；
- 标注 ADAPTER/INFERENCE；不得声称 Codex 原生支持。

---

## 5. Gap 4：Capability / Ownership

1. **能否把 Codex resource 自动映射为 Capability？** 不能：skills / plugins / MCP 是工具贡献者，不是 lifecycle 对象（20 §10）。
2. **是否由 Unified Capability Runtime 额外包住 Codex backend？** 是：统一 ownership 由 runtime overlay 提供（PluginScope + EffectRegistry），与 backend 执行并存。
3. **Codex 原生 ownership 是否必须保留？** 是：session-scoped 服务生命周期是 backend fact，保留为 backend metadata。
4. **Adapter 是否只负责 execution？** 是：Adapter 不负责 Capability ownership。

**判定：BACKEND_SPECIFIC + UNIFIED OVERLAY。** 两个生命周期域并存；不改 Capability contract。

---

## 6. Gap 5：Initiator / Causality

- **durable lineage**：ADAPTER（SessionMeta fork/parent + InterAgentCommunication → unified lineage）。
- **ambient initiator**：不要求 Adapter 重建；Unified replay 契约本身不恢复 ambient（17 UN-11）；live 执行时由 Unified Runtime overlay 设置自己的 initiator。
- 不发明 `initiator_id`。

**判定：LOSSY_ACCEPTABLE**（durable 层可映射；ambient 缺失为可接受 loss）。若未来有 Unified 语义强依赖 ambient 且无 runtime overlay，则升级为 TRUE_SEMANTIC_GAP——当前无此依赖。

---

## 7. Gap 6：Compaction Retry Identity

- A. **Unified Core 当前 contract 不足**：是。CTX-07 只定义“同 Step retry”，没有表达“跨 Step 的同一逻辑执行”的位置。
- B. **Adapter 可以转换**：可做有损转换（metadata 标记 retry），但会丢失或伪造 pre/post compaction 两个 Step 之间的身份。
- C. **Backend-specific semantics**：Codex 原生事实是“新 sampling request = 新 Step”，该事实本身保留。

**判定：UNIFIED_EXTENSION_POINT：ExecutionAttempt**（`parent_execution_id` + `attempt_no`），不修改 Turn/Step。本阶段只定义契约，不实现。

---

## 8. Extension Point 判定

| Candidate | Needed | Role | Note |
| --- | --- | --- | --- |
| ExecutionAttempt | YES | 跨 Step 的 retry identity（compaction retry 等） | `parent_execution_id` + `attempt_no`；不改 Turn/Step |
| BackendEventRef | YES | 每个 Unified event 可回源到 raw rollout | rollout path + line + item type；21 BP-03 已提出 |
| BackendMetadata | YES | 可枚举 lossiness + backend fact 快照 | `mapping_quality` / `missing_semantics` / raw ref |
| RecoveryCapability | NO | backend 可恢复性声明 | 当前由 BackendMetadata 承担；第二个 backend 需要时再定 |
| ErrorDetail | NO | 结构化错误扩展 | 当前复用 `tool/result.error` + BackendMetadata；有跨 backend 归一化需求时再定 |

三层：

- **Core semantics**：Session/Turn/Step、EventStore append-only、Surface 投影、tool/result failure 分层、compaction replacement、Capability ownership、durable lineage。
- **Extension semantics**：ExecutionAttempt、BackendEventRef、BackendMetadata。
- **Backend semantics**：Codex CompactedItem/window_ids、rollback marker、fork copy/reference、sandbox denial fallback、originator、rollout trace graph；DSH currentInitiator、TOOL_OUTCOME_UNKNOWN、tool waterfall specifics。

---

## 9. 不应该统一的 Backend-Specific Semantics

Codex 保留：

- `CompactedItem` / `window_ids` / `replacement_history`
- `ThreadRolledBack` marker
- fork `Copied` / `Referenced` 两种形态
- sandbox denial 自动降级到 `SandboxType::None`
- `originator`（产品来源串，非 initiator）
- rollout trace graph（opt-in）
- session-scoped 资源 owner
- `run_turn` 内部控制边界

DSH 不强行施加给 Codex：

- `currentInitiator` / `requireInitiator`（ambient identity）
- `TOOL_NOT_STARTED` 精确判定
- step/start-end 原生事件与 step_id
- tool waterfall 的 pre-execute / approval / guard 精确阶段词汇
- compaction/start…end 事务事件与 sourceEventSeqs（Adapter 合成 replacement 语义，但不伪造原生事件）

---

## 10. Portability Rules

| # | Rule |
| --- | --- |
| BP-11 | Backend-specific semantics may remain backend-specific. |
| BP-12 | Unified semantics should only standardize behavior required by cross-backend use cases. |
| BP-13 | Adapter lossiness must be explicit. |
| BP-14 | Raw backend evidence should remain recoverable where possible. |
| BP-15 | A backend mismatch must not silently mutate Unified semantics. |

---

## 11. Final Answers

1. **哪些 Gap 可以 Adapter 解决？** Step 合成边界、call/result 配对、错误归一化、crash 保守标记、durable lineage、compaction/replay 翻译、RawResponseItem 去重。
2. **哪些必须 LOSSY？** exec 失败结构化（exit_code 可读但 success 语义固定 true）、chunk→message lineage、compaction retry 跨 Step 身份（除非 ExecutionAttempt）、ambient initiator。
3. **哪些应该 Backend-Specific？** Capability/Ownership（session 服务）、sandbox denial fallback、fork copy/reference、rollback marker、originator、rollout trace graph、run_turn 控制边界。
4. **哪些可能需要 Unified Extension Point？** ExecutionAttempt、BackendEventRef、BackendMetadata。
5. **是否存在真正 Unified Semantic Gap？** 无（基于当前契约；所有差异都可 adapter 化 / 有损可接受 / backend-specific / extension）。
6. **Codex Adapter 能否在不修改 Semantic Core 的情况下实现？** 能；前置条件是把 21 BP-01 的 runtime.py seam 抽成 adapter interface（装配层改动，非语义 contract）。
7. **最小 Adapter 边界是什么？** 见 `23-codex-adapter-boundary.md`。
8. **哪些原始 Codex 语义必须保留？** §9 Codex 列表。
9. **哪些 DSH semantics 不应该强加给 Codex？** §9 DSH 列表。
10. **是否需要 ExecutionAttempt extension point？** 需要（extension point，不实现）。

---

## 12. Final Status

**PARTIAL**：六项判定完成、无 true gap、Adapter 边界明确；但 Adapter 未实现、BP-01 seam 未修、lossiness 元数据未落地，不能 PASS。
