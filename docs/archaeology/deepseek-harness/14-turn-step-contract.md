# 14 — DSH Turn / Step Semantic Contract

> 对象：deepseek-ai/deepseek-harness @ `47f943859bef60e4160492346772ded9b24f765a`（2026-08-13）
> 阶段：Phase 3-B（Turn / Step 语义）；只做 contract，不实现
> 来源：01 / 02 / 05 / 06 / 10 / 13 / 99（本阶段不重新考古；无证据 → UNKNOWN）
> 状态词：VERIFIED / PARTIAL / NOT FOUND / INFERENCE / DESIGN_PROPOSAL / UNKNOWN

---

## 1. Turn Definition

冻结：`Turn = 0..N Step`；边界事件 `turn/start`、`turn/end{reason}`（13 TURN-01；99 §2）。

**Turn end reason（VERIFIED）** — `TurnEndReason = completed | max-tokens | error | aborted | blocked | interrupted`（01 §1.3，`core/session/src/types.ts:155`）。

| reason | 触发路径（源码事实） |
| --- | --- |
| completed | assistant/message 无 tool-call（agent.ts:376）；或某 tool/result 带 `concludesTurn`（tool-calls.ts:99）— 01 §1.8 |
| max-tokens | 输出 token 达上限（agent.ts:374）— 01 §1.8 |
| error | 结构化 `LlmFailure` 且不再 retry（agent.ts:285-315）— 01 §1.8；05 §1 |
| aborted | `AgentCancelCause {user,parent,hook,disposed}`（types.ts:144-150）— 05 §1 |
| blocked | `agent/pre-step` reject — 01 §1.8 |
| interrupted | 崩溃修复合成（repair.ts:31-134）— 05 §1 |

**问答：**

1. 是否所有 reason 都是源码事实？**是（VERIFIED）**：六个 reason 全部在枚举与触发路径中确认。
2. 是否允许 empty turn？**是（仅 blocked，VERIFIED）**：call graph 中 `preStep` 在 `step/start` 之前（01 §3），pre-step reject → `turn/end{blocked}` 不产生 step。其它 reason 的 empty turn：**UNKNOWN**。
3. 一个 Turn 是否一定有 Step？**否（VERIFIED）**：blocked 是 zero-step 反例。
4. 一个 Turn 是否可以有多个 Step？**是（VERIFIED）**：13 TURN-03；99 §2。
5. turn/end 与 session event 顺序？**VERIFIED**：`turn/start → preStep → step/start → … → step/end → turn/end`（01 §3），事件按调用顺序 append，带 seq/time（01 §4）。崩溃修复顺序：合成 `tool/result → step/end → turn/end{interrupted}`（05 §1）。

## 2. Step Definition

冻结：`Step = one model request + all tool activity caused by that request`；边界事件 `step/start`、`step/end`（01 §1.3；13 TURN-02）。

相关事件：`request/header`（请求配置快照）、`assistant/chunk*`、`assistant/message`、`tool/call*`、`tool/result*`（01 §3；13 §3.1）。`agent/request` 是 waterfall（插件钩子），不持久化；持久化的是 `request/header`（01 §1.2/§1.3）。

**问答：**

1. 没有 tool call 的 Step 是否合法？**是（VERIFIED）**：assistant 无 tool-call → completed（01 §1.8）。
2. 多个 tool call 如何归属同一 Step？**VERIFIED**：`executeToolCalls` 在一次 step 内按 exclusive/parallel 调度 N 个 call，每个写 `tool/call` + `tool/result`（01 §1.5，tool-calls.ts:203-236）。
3. tool failure 是否终止 Step？**否（VERIFIED）**：失败落为 `isError` tool/result，错误文本进模型可见 surface，additionalContexts 注入下一 step，由模型决定重试或结束（05 §1）。
4. tool result 是否一定属于同一 Step？**VERIFIED（顺序层）**：result 在 executeToolCalls 内、step/end 之前 append（01 §3）；崩溃修复也先合成 result 再合成 step/end（05 §1）。**INFERENCE（归属层）**：无显式 stepId 字段，lineage 只有 call→result 的 sourceEventSeqs（02 §2）；"同一步"由嵌套顺序推导。
5. step/end 是否一定存在？**PARTIAL**：正常路径与 interrupted 修复路径有 step/end（VERIFIED）；aborted 路径无证据（UNKNOWN）。
6. aborted/interrupted 时 Step 如何结束？interrupted：合成 `tool/result + step/end + turn/end{interrupted}`（VERIFIED，05 §1）。aborted：未启动的工具调用写合成错误 result + `turn/end{aborted}`（VERIFIED，tool-calls.ts:249-263；05 §1）；aborted 是否写 step/end：**UNKNOWN**。

## 3. Event Boundaries

| 事件 | 角色 | 模型历史 | 状态 |
| --- | --- | --- | --- |
| turn/start, turn/end | Turn 边界 | 否 | VERIFIED |
| step/start, step/end | Step 边界 | 否 | VERIFIED |
| user/message | 用户输入 | 是 | VERIFIED |
| assistant/chunk | 原始流块 | 否 | VERIFIED |
| assistant/message | 组装后的模型消息 | 是 | VERIFIED |
| tool/call | 工具调用记录 | 否（模型消息由 tool/result 派生） | VERIFIED |
| tool/result | 工具结果 | 是 | VERIFIED |
| request/header, request/context | 请求快照 | 否 | VERIFIED |
| usage, error | 计量 / 错误 | 否 | VERIFIED |
| compaction/summary, compaction/prune | 投影替换 | 间接（改变后续 surface） | VERIFIED |
| session/end-seed | seed 边界 | 否 | VERIFIED |
| llm/retry, llm/retry-started | 重试轨迹 | 否 | VERIFIED |

证据：02 §2/§3（事件清单、deriveMessages）；`surface.ts:85` "turn/step boundaries, chunks, usage, errors are trace/replay data, not history"；13 §3.1。

## 4. Model-visible Boundaries

- 模型可见 = log → surface → deriveMessages 的派生子集：**user/message、assistant/message、tool/result**（02 §3，`index.ts:726-749`）。
- 显式排除：turn/step 边界、assistant/chunk、usage、error（02 §3，surface.ts:85）。
- 分类（"both" 指既持久化于 trace、又派生为模型历史）：
  - **A. trace/replay only**：turn/start、turn/end、step/start、step/end、assistant/chunk、usage、error、tool/call、request/header、request/context、compaction/*、llm/retry*、session/end-seed
  - **C. both**：user/message、assistant/message、tool/result
  - **B. model-visible only**：无。事件溯源下所有模型可见内容都同时是 log 的一部分（13 ES-03）。
- 推论（VERIFIED，TS-07）：trace 事件 ≠ 模型历史；Python 实现不得把边界/chunk/usage/error 直接塞进 model messages。

## 5. Failure Boundaries

| 失败 | 分类（源码事实） | 边界 |
| --- | --- | --- |
| Model failure | `LlmFailure {message, code, status?, retryAfter?, requestId?}`；`agent/request-error`；llm-retry（05 §1） | step 内重试（同一 step 重新 buildRequest，05 §1）；不再 retry → `turn/end{error}`（01 §1.8）。error 路径是否先写 step/end：**UNKNOWN** |
| Tool failure | `ToolExecutionFailure {isError:true, error:{message,info}}`（tools/src/index.ts:569-576） | **tool-result 层失败**：持久化 isError result，不终止 step/turn（05 §1） |
| Timeout | `TOOL_TIMEOUT`（guard/timeout-policy）；子进程 kill（05 §1） | **tool-result 层失败**：isError result 替换原结果，交回模型（05 §1） |
| Abort | `AgentCancelCause`；未启动调用合成错误结果（tool-calls.ts:249-263） | **turn 层失败**：`turn/end{aborted}`；step 结束方式 UNKNOWN（05 §1） |
| Blocked | `agent/pre-step` reject（01 §1.8） | **turn 层失败**：`turn/end{blocked}`，zero steps（01 §3） |
| Interrupted | 崩溃修复 `interruptedTurnClosers()`（repair.ts:31-134） | **turn 层失败 + step 闭合**：合成 tool/result + step/end + turn/end{interrupted}（05 §1） |

区分：tool failure / timeout 是 tool-result 层，不混为 step/turn failure；model failure 可 step 内恢复或 turn 终止；abort / blocked / interrupted 是 turn 层终止。

## 6. Multi-step Semantics

VERIFIED 链（01 §1.6/§3；02 §1/§3；05 §1；99 §4）：

```text
Step N:
  model request → assistant/message（含 tool-call）
  → executeToolCalls → tool/call* → tool/result*
  → additionalContexts → acceptContext → next-step inbox
  → step/end

Step N+1:
  preStep 认领 inbox → deriveMessages（surface 含上一步 tool/result）
  → buildRequest → 下一个 model request
```

- 一个 Turn 可含多个 Step（13 TURN-03）。
- 工具结果成为下一步模型输入的两个载体：surface 中 tool/result 派生消息 + additionalContexts 注入 next-step inbox（01 §1.6）。

## 7. State Machine

- **DSH 原生没有 Step 状态对象（NOT FOUND）**；唯一进程内状态机是 `ReactLoopAgent.Phase = idle/maintenance/running`（01 §4，agent 层，不是 step 层）。
- 以下状态仅作为 "事件可观测阶段" 或 Python 设计状态，**不得伪装成 DSH 原生状态机**：

| 提议状态 | 依据 | 状态 |
| --- | --- | --- |
| CREATED | 无 step 对象/事件 | DESIGN_PROPOSAL |
| STARTED | step/start 事件 | VERIFIED（边界事件） |
| REQUESTED | request/header 事件（buildRequest 内） | PARTIAL（事件可观测；无状态对象） |
| STREAMING | assistant/chunk* 事件 | VERIFIED（事件可观测） |
| TOOL_EXECUTING | tool/call → tool/result；scheduler prepare/dispatch/finalize（tool-calls.ts:203-236） | VERIFIED（事件可观测） |
| ENDING | 无源码 | DESIGN_PROPOSAL |
| ENDED | step/end 事件（正常 + 修复合成） | VERIFIED（边界事件） |
| FAILED | 无 step 级失败事件；失败落在 turn/end{error} 或 isError tool/result | DESIGN_PROPOSAL |
| ABORTED | turn/end{aborted}；无 step 级 abort 事件 | DESIGN_PROPOSAL |

## 8. Verified Facts

### VERIFIED

1. TurnEndReason 六值枚举 + 每个 reason 的触发路径（01 §1.3/§1.8；05 §1）。
2. 事件顺序：turn/start → preStep → step/start → … → step/end → turn/end（01 §3）。
3. Step = 一次模型请求 + 该请求的工具活动（01 §1.3；13 TURN-02）。
4. Step 无 tool call 合法（completed 路径）（01 §1.8）。
5. 同一 Step 可含多个 tool call/result（01 §1.5）。
6. Tool failure 不终止 step（05 §1）。
7. Turn 可含多个 Step（13 TURN-03；99 §2）。
8. tool/result → additionalContexts → next-step inbox → deriveMessages → 下一请求（01 §1.6；99 §4）。
9. 模型失败重试在同一 step 内重新 buildRequest（05 §1；13 TURN-02）。
10. 模型可见历史仅 user/message、assistant/message、tool/result；边界/chunk/usage/error 排除（02 §3；surface.ts:85）。
11. 崩溃修复合成 tool/result + step/end + turn/end{interrupted}（05 §1）。
12. blocked 由 agent/pre-step reject 产生，位于 step/start 之前（01 §1.8/§3）→ empty turn 存在。
13. Capability lifecycle 与 execution truth 概念分离（13 §13.2）。

### PARTIAL

1. step/end 一定存在：正常 + interrupted VERIFIED；aborted 无证据。
2. TS-05：log 级边界可重建 VERIFIED；"恰好一个 turn" 归属为 INFERENCE；aborted step 结束未知。
3. TS-09：failure 语义区分 model/tool/turn 部分 VERIFIED；step 级失败细节未知。
4. TS-10：概念正交 VERIFIED；是否同一 event domain 未决（13 §13.3）。

### UNKNOWN

详见 §9：aborted 的 step/end、非 blocked 的 empty turn、error 路径 step/end、显式 step→turn 引用、capability/execution event domain 合并。

### INFERENCE

1. Step 归属唯一 Turn（TS-01）：调用图嵌套推导；无显式 turnId/stepId 字段证据。
2. tool/result 严格归属同一步（无 stepId；lineage 仅 call→result）。
3. deriveMessages 确定性（13 §12-7，实现级 INFERENCE）。

### Core Invariants（TS-01..10）

| # | Invariant | 状态 |
| --- | --- | --- |
| TS-01 | Every Step belongs to exactly one Turn | INFERENCE（调用图嵌套；无显式引用字段） |
| TS-02 | A Step contains exactly one model request | VERIFIED（逻辑一次；重试同一 step 重新 buildRequest，05 §1） |
| TS-03 | Tool activity caused by that request belongs to that Step | VERIFIED（01 §1.3/§1.5；13 TURN-02） |
| TS-04 | A Turn may contain multiple Steps | VERIFIED（13 TURN-03） |
| TS-05 | Step boundaries are reconstructable from events | PARTIAL（正常/interrupted VERIFIED；aborted 未知） |
| TS-06 | Tool result can become next-step model input | VERIFIED（01 §1.6；99 §4） |
| TS-07 | Execution trace events are not automatically model-visible | VERIFIED（02 §3；surface.ts:85） |
| TS-08 | Turn end reason is explicit | VERIFIED（types.ts:155；修复合成 reason） |
| TS-09 | Failure semantics distinguish model/tool/turn where supported | PARTIAL（05 §1；aborted step 细节未知） |
| TS-10 | Capability lifecycle is orthogonal to Turn/Step lifecycle | PARTIAL（13 §13.2 概念冻结；event domain 未决） |

## 9. Unknowns

| # | Unknown | 当前证据 | 状态 |
| --- | --- | --- | --- |
| 1 | aborted 时 step/end 是否存在 / 如何结束 | 只有合成 tool result + turn/end{aborted}（05 §1） | UNKNOWN |
| 2 | 非 blocked 的 empty turn（aborted/error/max-tokens 是否可在 step/start 前结束） | 无证据 | UNKNOWN |
| 3 | model failure 不再重试的 error 路径是否先写 step/end | 只有 turn/end{error}（01 §1.8；05 §1） | UNKNOWN |
| 4 | Step↔Turn 显式归属字段（stepId/turnId） | 无；只有调用嵌套与事件顺序 | UNKNOWN（NOT FOUND） |
| 5 | Capability lifecycle 事件与 Step execution 事件是否同一 event domain | 13 §13.2 概念分离；§13.3 open questions 未决 | UNKNOWN（OPEN） |
| 6 | deriveMessages 形式化确定性 | 纯投影 INFERENCE，无测试保证（13 §12-7） | UNKNOWN（PARTIAL） |
| 7 | 工具副作用边界（TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN 判定） | 状态存在，判定边界未展开（13 §12-10） | UNKNOWN（PARTIAL） |

## 10. Python Runtime Requirements

契约级要求（不实现，仅约束下一阶段设计；引用 13 §13.1）：

1. **Turn/Step runner**：turn 边界 + reason 枚举；step = 一次逻辑模型请求 + 该请求工具活动；重试不新开 step；blocked 允许 zero-step turn；interrupted 需合成闭合事件。
2. **EventStore / SessionEvent schema**：turn/step 边界事件 + turn/end.reason；sourceEventSeqs 保留（call→result、chunk→message）；无 delete/update。
3. **Surface / deriveMessages**：模型可见 = user/message、assistant/message、tool/result；边界/chunk/usage/error 不得进入模型消息。
4. **Failure classification**：model failure → step 内重试或 turn/end{error}；tool failure/timeout → isError tool/result；abort/blocked/interrupted → turn 层 reason；step/end 的 aborted/error 语义在补证据前按 UNKNOWN 处理（不假定）。
5. **Repair**：崩溃尾部合成 tool/result + step/end + turn/end{interrupted}；TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN 标记保留。
6. **Capability Runtime 边界**：lifecycle（install/activate/dispose）是独立 domain，不进入 SessionEvent；tool execution 属于 execution truth（capability effect → tool/call → tool/result）。合并与否保持 open（13 §13.3）。
7. 未解决项（§9）必须在 Python 设计中显式声明为 assumption，不能写成 VERIFIED。

---

## Final Verdict

**PARTIAL** — 契约已冻结：Turn/Step 定义、边界事件、模型可见边界、多步链、turn reason、failure 分层均来自已有考古（VERIFIED 为主）；aborted step 结束、error 路径 step/end、显式归属字段、capability event domain 仍是 UNKNOWN，未伪装成源码事实。
