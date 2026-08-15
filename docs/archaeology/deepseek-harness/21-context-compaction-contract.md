# 21 — Context Projection + Compaction Semantic Contract（Phase 4-C）

> 基线：deepseek-ai/deepseek-harness @ `47f943859bef60e4160492346772ded9b24f765a`（2026-08-13）
> 上游源码：`/Users/david/k8s/auto_swe_sys/deepseek-harness`（已核对 HEAD == 基线；下文相对路径均以该目录为根）
> 方法：直接读 compaction / token-meter / session / agent-loop 源码；复用 02/13/17 已冻结结论；不重复研究 EventStore / Replay / Turn / Step。
> 状态词：VERIFIED / PARTIAL / INFERENCE / UNKNOWN / DESIGN PROPOSAL / NOT FOUND
> 最终状态：**PARTIAL** —— 契约冻结；UNKNOWN / INFERENCE 保持原样，未伪装成 VERIFIED。

---

## 0. 冻结的 Context 公式

```text
Context
    = System Prompt
    + Runtime Context
    + Surface-derived History
    + Current User Input

Context Pressure → Compaction → Surface Replacement → deriveMessages → Model Request
```

证据：`packages/core/agent-loop/src/agent.ts:225-237`（preStep：systemPrompt.assemble + runtimeContext.project + agent/pre-step）、`:339-343`（step：`buildRequest(..., this.session.deriveMessages(), ...)`）、`:407-467`（buildRequest：request/header 重建 system/tools/config）；`packages/core/agent-loop/src/runtime-context.ts:1-76`（runtime-context 是 user message，source = dsh-system-prompt）。

---

## 1. 三层分离（禁止合并）

| 层 | 定义 | 权威 | 状态 |
| --- | --- | --- | --- |
| Source History | append-only `SessionEvent[]`（内存 log + 持久化订阅） | 唯一 source of truth；从不物理截断 | VERIFIED（13 ES-01；`core/session/src/index.ts`） |
| Surface | log 的有序投影，只含 message-producing 节点（user/assistant/tool result）；由 `surfaceOp` 维护 | 派生视图，可重建，不是第二权威 | VERIFIED（13 ES-02；`core/session/src/surface.ts:74-85,330-371`） |
| Model Context | 单次 model request 实际看到的 messages（system/tools + deriveMessages + runtime-context + claimed input） | 每次请求重新组装，不持久化为独立对象；retry 时重建 | VERIFIED（02 §1；`agent.ts:339-343,407-467`） |

契约：Event Log、Surface、Model Context 不得混成一个对象。

---

## 2. BasicCompactionEngine 语义逐项验证

实现入口：`packages/compaction/compaction-basic/src/index.ts:129`（`auto` 时注册自动监听）、`:258`（`compactIfNeeded`）；事务在 `packages/compaction/compaction-basic/src/region.ts:152`（`compactSurfaceRegion`）。

| # | 问题 | 答案 | 状态 |
| --- | --- | --- | --- |
| 1 | 哪些节点被选择？ | 始终是 **head-anchored 连续 surface 区间**：`selectCompactableRange` 从尾部累积保留预算，得到 `keepFromIdx`，再向前回退到 `toolPairingBalancedBefore` 为真的平衡 cut；`start = surface[0]`，`end = surface[keepFromIdx-1]`。区间按 surface 位置而非数字 seq 顺序；`validateSurfaceRegion` 强制 start/end 都是平衡边界，不拆开 assistant tool-call/tool-result 对。 | VERIFIED（`region.ts:98-148`；`compaction/src/tool-pairing.ts:1-92`） |
| 2 | retainRatio / retainTokens 的真实作用？ | 两者互斥（`config.ts:177-181`）。默认 `retainRatio=0.16`；pressure 路径 `retainTokens = floor(contextWindow * retainRatio)` 或显式绝对 token 数（`config.ts:86-115`）。它只决定**保留尾部预算**：从 surface 尾向头累加节点 token，直到 ≥ retainTokens，然后回退到最近的平衡 cut；该尾部原样保留，头部区间被替换。`keepFromIdx == 0` 时不压缩。overflow 路径用 `retainTokens=0`，即保留最短平衡尾部（至少一个节点），不是“什么都不留”。 | VERIFIED（`region.ts:98-135`；`index.ts:285-319`） |
| 3 | summary 如何生成？ | `summarizeWithLlm`：复用最新 `request/header` 的 system/tools，shadowed 区间按 surface 顺序 derive 成 messages，末尾追加固定 compaction instruction 作为最后一条 user message；一次 `ctx.llm.stream()` 生成，输出只允许 text blocks（含 image 报 `UNSUPPORTED_CONTENT`），用 `<compacted-summary>…</compacted-summary>` + preamble 包装。**必须比 shadowed 内容小**：framed summary 的 heuristic token 数 >= shadowedTokenCount 即失败。 | VERIFIED（`compaction-basic/src/summarizer.ts:121-224`；`region.ts:339-357`） |
| 4 | summary 自己是否成为新的 user/message？ | 是。`commitCompactionBody` 追加一个 `user/message`（checkpointMessage），`surfaceOp: {op:'replace', start, end}`，`source: compactCheckpointSource(compactionId)`（plugin marker `'compact'`）。 | VERIFIED（`region.ts:427-451`；`compaction/src/checkpoint.ts:17-49`） |
| 5 | replacement event 如何记录？ | 一个事务追加四个事件：`compaction/start`（log-only，持锁）→ `compaction/summary`（log-only，记录 summary/shadowedRange/shadowedSeqs/shadowedTokenCount/provider/model/rawOutput/usage）→ 替换 `user/message`（surface replace）→ `compaction/end`（成功或带 `error` 释放锁）。 | VERIFIED（`region.ts:152-235,427-451`；`compaction/src/types.ts:26-109`） |
| 6 | sourceEventSeqs 如何保留？ | 替换 user/message 的 `sourceEventSeqs = [compaction/start.seq, compaction/summary.seq, ...shadowedSeqs]`；`assertProvenance` 强制必须包含全部被替换 surface 节点、无重复、必须早于当前 seq。 | VERIFIED（`region.ts:439-445`；`core/session/src/surface.ts:210-233`） |
| 7 | 原 Event 是否永远保留？ | 是。log append-only，无物理删除；surface replace 只把旧节点移出投影。 | VERIFIED（13 COMP-01；`surface.ts:331-371`） |
| 8 | compaction start/end 如何持久化？ | 与所有事件一样 append 进 Session log（persistence 插件订阅落盘）。自动路径不额外 flush；manual `compactNow` 成功后调用 `ctx.sessions.flush()`（`index.ts:385-390`）。崩溃留下 unmatched `compaction/start` 时，`assertCompactionInactive` 阻止后续压缩，除非其后有 `session/end-seed` 证明属于已结束生命周期。 | VERIFIED（`region.ts:152-170,366-399`；`compaction/src/index.ts:70-84`） |
| 9 | compaction failure 如何处理？ | 显式分类：`busy / cancelled / changed / summary / commit / persistence`（`compaction/src/index.ts:28-49`）。事务中 `compaction/end` 带 `error`；失败尝试留在 log。自动 pressure 路径 catch 后仅告警并继续 turn；overflow 路径：无 durable surface 进展则保留原 request error，有进展（`replaceGeneration` 前进）则即使 summary 抛错也 retry（prune 已落地）。取消始终优先，不 retry。 | VERIFIED（`region.ts:152-235`；`index.ts:145-235`） |
| 10 | compaction 成功后如何 retry 当前 request？ | `agent/request-error` 监听器返回 `{kind:'retry'}`；agent loop 的 `while(true)` `continue`，用**新的** `session.deriveMessages()` 重新 `buildRequest`（同 turn/step，不新开 step）。受 `maxOverflowRetries`（默认 1）限制；`overflowRetries` 在 agent idle 或新 `assistant/message` 时清零。 | VERIFIED（`index.ts:179-228`；`agent.ts:339-367`） |

---

## 3. Tool Result Pruning

实现：`packages/compaction/compaction-tool-result-pruner/src/index.ts:136-166`（`pruneSession`）。

| # | 问题 | 答案 | 状态 |
| --- | --- | --- | --- |
| 1 | 原 tool/result 是否保留？ | 是。log append-only；新增 `tool/result` replace 事件覆盖同一个 surface 位置，原事件仍在 log。 | VERIFIED（`index.ts:136-166`；13 COMP-01） |
| 2 | pruning 是否独立于 full compaction？ | 是。`ToolResultPruner` 是独立可选服务；`compaction-basic` 用 `ctx.get('toolResultPruner')` 按需组合：pressure 达标后先 prune 再决定是否 summary；overflow 无条件先 prune。 | VERIFIED（`index.ts:97-103,279-319`） |
| 3 | prune 是否也生成 surface replacement？ | 是。每条超长 tool/result：先 append `compaction/prune`（shadow price），再 append 替换 `tool/result`，`surfaceOp:{op:'replace', start:seq, end:seq}`，`sourceEventSeqs:[seq]`；`assertToolResultRewrite` 强制只允许改 content，其余字段深比较不变。 | VERIFIED（`index.ts:141-166`；`core/session/src/surface.ts:259-290`） |
| 4 | replay 后是否能恢复原始 tool/result？ | 默认投影不能：replay/surface fold 按事件顺序应用 replace，得到的是 pruned surface（测试 `tool-result-pruner.spec.ts:254` 证明 replay.deriveMessages == session.deriveMessages）。原始内容仍可通过替换事件的 `sourceEventSeqs` 找到并重新投影——这是 lineage 恢复，不是默认投影行为。 | VERIFIED（DSH 侧）；Python 4-B 未实现（见 §8） |

---

## 4. Token Meter

实现：`packages/llm/token-meter/src/estimate.ts:26-69`、`surface-fold.ts:1-66`、`index.ts:99-193`、`breakdown-projection.ts:42-70`。

| 字段 | 含义 | 计算 | 状态 |
| --- | --- | --- | --- |
| systemTokens | 最新 request envelope 的 system prompt heuristic tokens | `ceil(system.length/4) + 4`（ROLE_OVERHEAD），无 header 为 0 | VERIFIED（`estimate.ts:44-53`） |
| toolsTokens | 最新 request envelope 的 tool schema heuristic tokens | `ceil(JSON.stringify(tools).length/4) + 4`，空为 0 | VERIFIED（`estimate.ts:55-64`） |
| messageTokens | 当前 surface 的 heuristic tokens | 逐 surface 节点 `estimateMessage`（text/reasoning/tool-call/tool-result 递归，`chars/4` + block overhead + role overhead）；replacement 走 `compaction/summary|prune` shadow-price 协议，O(1) fold | VERIFIED（`estimate.ts:26-42`；`surface-projection.ts:66-94`；`breakdown-projection.ts:42-70`） |
| contextWindow | adapter 声明的模型容量 | 由 `request/context` 记录；pressure 决策用 `ctx.llm.resolveModelInfo(...).context.contextWindow` | VERIFIED（`core/session/src/types.ts:180-187`；`index.ts:275-283`） |
| thresholdRatio | 压力阈值比例 | 默认 0.8；`thresholdTokens = floor(contextWindow * thresholdRatio)` | VERIFIED（`config.ts:9-10,86-115`） |
| retainRatio | 保留尾部比例 | 默认 0.16；与 retainTokens 互斥；`retainTokens = floor(contextWindow * retainRatio)` | VERIFIED（`config.ts:13-14,98-101`） |
| retainTokens | 保留尾部绝对 token 数 | 互斥覆盖；必须 < thresholdTokens | VERIFIED（`config.ts:177-181`） |

### token estimation vs provider actual usage

- 固定启发式：4 字符/token + 结构 overhead；README 明示 CJK 与 JSON schema 系统性低估，**不是 billing 或 gating input**。
- 有 provider usage 时 `measure()` 用 `assistant/message.usage` 做 anchor（仅当 canonical envelope 匹配且 provider total >= 对应 heuristic anchor），surface 增量仍用 heuristic；否则全量估计（`index.ts:99-193`）。
- `contextPressure.projectedTokens = provider pressureTokens + heuristic surface delta`，显式“not one atomic observation”。
- 结论：**token budget 是 estimate，不是精确 provider accounting**（CTX-06）。精确对齐 provider tokenizer 仍 UNKNOWN。

---

## 5. Compaction Trigger

| 触发 | 语义 | 状态 |
| --- | --- | --- |
| A. pre-step pressure | `agent/pre-step` hook：`measure().totalTokens >= thresholdTokens` 才进入；先 prune 再 remeasure；仍超阈值则循环 `compactionRetries+1` 次（默认 2 次尝试），每次保留尾部 `retainTokens`；最终仍超阈值抛错，hook catch 后告警并继续 turn。无 routed request header 时不触发。 | VERIFIED（`index.ts:137-177,258-333`） |
| B. request-error / CONTEXT_WINDOW_EXCEEDED | `agent/request-error` 且 `failure.code === 'CONTEXT_WINDOW_EXCEEDED'`（`llm/src/error.ts:25`）、未取消、`overflowRetries < maxOverflowRetries`（默认 1）时：先 prune，再 `selectCompactableRange(..., retainTokens=0)` 压缩；surface `replaceGeneration` 前进且未取消 → `{kind:'retry'}`；否则 `next()` 保留原错误。 | VERIFIED（`index.ts:179-228,285-297`） |
| Manual | `compactNow`：idle agent + `runMaintenance` + standalone `compaction/start…end` + 可选 flush；不触发当前 request retry。 | VERIFIED（`index.ts:363-407`；`compaction/src/index.ts:60-84`） |

失败分类（自动与 manual 共用词汇）：`busy`（压缩锁/agent busy）、`cancelled`（agent 取消）、`changed`（surface 在 summarization 期间变化）、`summary`（LLM/空文本/不够小）、`commit`（end 事件追加失败）、`persistence`（manual flush 失败）。

---

## 6. 冻结契约 CTX-01..08

| # | 契约 | 状态 |
| --- | --- | --- |
| CTX-01 | Model input is derived from current projection, not raw event history | VERIFIED（`deriveMessages` 只走 surface；`surface.ts:74-85`；`index.ts:726-749`） |
| CTX-02 | Source event history is not physically deleted by compaction | VERIFIED（append-only + replace 事件；13 COMP-01） |
| CTX-03 | Compaction changes future model-visible context | VERIFIED（replace 从 surface 移除 shadowed 节点；13 COMP-02） |
| CTX-04 | Compaction is reconstructable from persisted events | VERIFIED（DSH：start/summary/replace/end 全部落 log；测试 `compaction-basic.spec.ts:879`）。Python 4-B：**NOT IMPLEMENTED**（无 surfaceOp/compaction 事件） |
| CTX-05 | Tool-result pruning follows the same replacement/projection principle | VERIFIED（`pruneSession` + shadow price；`surface.ts:259-290`） |
| CTX-06 | Token meter is an estimate, not guaranteed exact provider accounting | VERIFIED（README 明示；usage anchor 只是 PARTIAL 精确性） |
| CTX-07 | Compaction may retry a failed request where source semantics support it | VERIFIED（overflow 发生在 model stream 完成前，未 append assistant/message、未执行 tool call；retry 同 turn/step 重建请求） |
| CTX-08 | Compaction failure is explicitly represented | VERIFIED（`compaction/end.error` + ManualCompactionError 六类） |

---

## 7. Capability Runtime 边界

如果 Capability 生成大量 tool output：

- **它是 Session history（execution truth）**：执行结果落 `tool/result` 事件，可能进入 surface → model context。
- **它不是 Capability state**：capability 的 install/dispose/scope/effect/注册 是 lifecycle truth（runtime registry，不落 SessionEvent；17 §2 OWNS）。
- **不得把 capability state 直接写入 model context**：模型只能看到工具 schema（request/header）与 tool/result（surface 投影）；capability 内部状态永远不进入 deriveMessages。

三分：Runtime State（capability registry/scope，内存，不持久化）≠ Execution History（SessionEvent log，持久化）≠ Model Context（单次请求投影，瞬态）。DSH 本身无 Capability 对象（NOT FOUND）；该边界来自 Phase 2 Python + 17 契约（VERIFIED 概念层；capability 事件是否进 SessionEvent 仍 OPEN QUESTION）。

---

## 8. Replay 边界

| 问题 | DSH | Phase 4-B Python |
| --- | --- | --- |
| Replay 后重建什么？ | original event history（log 全量保留）+ compacted surface（surface fold 按事件顺序应用 replace）+ model-visible messages（deriveMessages 从 compacted surface 派生） | 只重建 original event history + 未压缩 surface；无 compaction 事件可应用 |
| Compaction 是 event replay behavior 还是 projection rebuild behavior？ | 两者都是：事件在 log 中可重放，surface/messages 是 projection rebuild；compaction 不改变 log 的原始内容 | 证据不足——Python 尚未实现任一，标 **UNKNOWN** |
| 能否恢复原始 tool/result？ | 能（通过替换事件 sourceEventSeqs 定位原事件）；默认投影不恢复 | 未实现 |

---

## 9. UNKNOWN / OPEN 清单

1. 跨 backend / 崩溃时 `compaction/start…end` 的原子性（有显式事件对，无多事件原子保证）——UNKNOWN（13 §12-5）。
2. `flush == fsync`——UNKNOWN（13 §12；20 §4-11）。
3. 与 provider tokenizer 精确对齐的 token accounting——UNKNOWN（CTX-06 只保证 estimate）。
4. Python replay 重建 compacted surface——UNKNOWN（需先补 surfaceOp/compaction schema）。
5. capability lifecycle 事件是否进入 SessionEvent——OPEN QUESTION（13 §13.3；17 §4）。
6. deriveMessages 跨版本/schema 迁移的确定性——INFERENCE（13 ES-04）。
7. 压缩后 model-visible messages 的信息质量评估（summary 信息损失）——NOT FOUND（02 §8）。

---

## 10. 结论

**PARTIAL** —— Context Projection / Compaction 语义契约已冻结：三层分离、BasicCompactionEngine 十项行为、tool-result pruning、token meter estimate、双触发与 retry、CTX-01..08 均有源码证据。UNKNOWN / INFERENCE 项原样保留；Python 最小实现要求见 `22-context-compaction-requirements.md`。
