# 15 — DSH Tool Waterfall Semantic Contract

> 对象：deepseek-ai/deepseek-harness @ `47f943859bef60e4160492346772ded9b24f765a`（2026-08-13，`git rev-parse HEAD` 一致）
> 阶段：Phase 3-C；只做 contract，不实现
> 来源：本阶段直接读源码（`packages/core/tools`、`packages/core/agent-loop`、`packages/core/session`、`packages/interaction/user-approval`、`packages/interaction/permission-presets`、`packages/sandbox/*`、`packages/guard/timeout-policy`）；复用 03 / 05 / 13 / 14 / 99 已证明事实
> 状态词：VERIFIED（本次源码直接确认）/ PARTIAL（部分路径确认）/ NOT FOUND（当前基线不存在）/ INFERENCE（推导）/ UNKNOWN（无证据）

---

## 1. Tool Call Model

### Durable `tool/call`（VERIFIED）

`packages/core/session/src/types.ts:279-282`：

```ts
'tool/call': { turn: number; step: number; callId: CallId; name: string; arguments: string }
```

- `name`、`callId`、`turn`、`step`：VERIFIED。
- `arguments` 是模型产出的**原始 JSON 字符串**，未解析（注释原文 "unparsed"）；解析后的参数只在运行时 `ToolExecutionInput.arguments` 中，不落事件（`tool-calls.ts:262-288`；`tools/src/index.ts:314-404`）。
- 事件顺序 `seq` / `time` 在 `SessionEvent` 信封上，`tool/call` data 内没有独立 sequence 字段（PARTIAL：信封级有序）。

### 运行时 call identity（VERIFIED）

`ToolExecutionInput` = `{ callId, rootCallId?, name, arguments, agent?, parent?, signal }`；`ToolExecution` 追加 registry 分配的不可见 `token`（`tools/src/index.ts:314-404`）。`agent`（initiator）只存在于运行时执行对象，**不写入 `tool/call` 事件**（PARTIAL / NOT FOUND at event level）。`token`、`rootCallId`、`parent` 均为进程内元数据，不持久化（PARTIAL）。

### `tool/result`（VERIFIED）

`packages/core/session/src/types.ts:291-300`：

```ts
'tool/result': {
  turn: number
  step: number
  message: ToolResultMessage   // callId + content + isError（llm/src/message.ts:152-160, 220-237）
  error?: { name: string; code: string }
  meta?: JsonValue
}
```

| 字段 | 状态 |
| --- | --- |
| success/failure（`message.isError`） | VERIFIED |
| error `{name, code}` | VERIFIED（仅当 `ToolErrorInfo` 存在；普通 deny 无此字段） |
| content（`message.content[0].content`） | VERIFIED |
| additionalContexts | NOT FOUND（运行时字段，事件不持久化） |
| concludesTurn | NOT FOUND（运行时标记，事件不持久化） |
| sourceEventSeqs | VERIFIED（事件信封字段，`tool/result` 指向其 `tool/call` 的 seq，`tool-calls.ts:268-288`） |

配对关系：`tool/result.sourceEventSeqs = [tool/call.seq]`（`tool-calls.ts:262-288`）；`session/invariant.ts:122-141` 要求 `tool/result` 必须落在 open step 且同 step 内已有对应 `tool/call`。

---

## 2. Pre-execute

Waterfall：`tools/pre-execute(exec, next)`（`tools/src/index.ts:145-156`；`prepareExecution` 在 `index.ts:1463-1504`）。默认 `next()` → `{ kind: 'allow' }`。

决策词汇（`index.ts:590-595`）：`allow | deny(reason) | ask(reason?)`。

问答（全部 VERIFIED，除非注明）：

1. **是否允许 reject？** 是。`deny` 直接物化 `isError` 结果。
2. **是否允许 ask/approval？** 是。`ask` 经 `serviceAsk` → `ctx.get('approval')` → `ApprovalService.request`；`allowed-once` → allow，`rejected/cancelled/unavailable` → deny（`index.ts:1689-1727`）。
3. **是否可以短路 execution？** 可以跳过 tool body（deny / ask 未批准），但不能注入成功结果（`PreToolDecision` 无 success 分支）。deny 结果仍走 `post-result` → post-execute（`index.ts:1463-1504` 返回 `post-result`）。
4. **guards 与 approval 的先后顺序？** pre-execute 监听器 → （若 `ask`）approval → guards → dispatch。源码：`denialReason = decision.kind === 'allow' ? this.guardReason(exec) : decision.reason`（`index.ts:1475-1503`）。
5. **谁决定 permission？** 分层：pre-execute 监听器决定 gate；ApprovalService 决定 ask；`tools.guard()` 决定最终 deny；session 级 sandbox/approval policy 由工具体内 `ctx.sandboxPolicy.resolve()` 决定实际执行授权（见 §3）。
6. **reject 是否生成 tool/result？** 是。deny/guard 物化 `isError` 结果并随调度器 append `tool/result`（`tool-calls.ts:268-288`）。
7. **reject 是否结束 step？** 否。结果正常提交，step 继续；`executeToolCalls` 返回 `concluded=false`，agent 继续下一轮模型请求（`agent.ts:390-397`）。
8. **reject 是否结束 turn？** 否。failure 永远不能携带 `concludesTurn`（`tools/src/index.ts:576`）。

---

## 3. Guards / Permission

DSH 中三者不是同一概念，且没有把 "Permission" 实现成 registry pipeline 的一个 stage：

### Guard（VERIFIED）

- `ToolGuard = (execution) => string | undefined`，同步、单调：返回 reason 即 deny，`undefined` 不改变决定；**没有任何 guard 可以 force-allow**（`tools/src/index.ts:704-711`）。
- `tools.guard()` 注册到 global 或 agent scope（`index.ts:1101-1127`）。
- 执行顺序在 pre-execute / approval 之后、tool body 之前；第一个 denial 生效（`index.ts:1475-1503`）。

### Permission（VERIFIED，但不是独立执行 stage）

DSH 的 "permission" 是 **session 级授权状态**：

- 事件：`permission/preset`、`sandbox/mode`、`approval/policy`（`packages/interaction/permission-presets/src/index.ts:44-52`；`packages/sandbox/sandbox-policy/src/session-mode.ts:20-38`；`packages/interaction/user-approval/src/index.ts:70-92`）。
- 执行时由 `ctx.sandboxPolicy.resolve()` 折叠：approved explicit mode > session override > deployment default；产出 `SandboxExecutionPolicy { mode, workspaceRoot, sessionId }`（`sandbox-policy/src/index.ts:127-154`）。
- 该 policy 由**工具体**消费（bash / fs / terminal），不是 `ToolRuntime` 管道的一部分：`approveEscalation` 在工具体内、任何副作用前执行（`packages/sandbox/sandbox/src/escalation.ts:131-180`；`packages/shell/tool-bash/src/index.ts:206-224`；`packages/fs/tool-fs/src/sandbox.ts:87-102`）。

### Approval（VERIFIED）

- 独立服务 seam：`ctx.approval`（`ApprovalService`），`approval/request` waterfall，outcome 闭合为 `allowed-once | rejected | cancelled | unavailable`，失败关闭（`user-approval/src/types.ts:16-23`；`index.ts:257-347`）。
- 每个 ask 落一对 log-only audit 事件：`approval/asked` + `approval/decided`（`index.ts:257-296`）。
- 策略 `'ask'`（默认，无人应答 → unavailable）或 `'never'`（确定性 rejected）（`index.ts:84-108, 215-231`）。
- 两种消费点：registry `pre-execute` 的 `ask`，以及 sandbox 工具体的 escalation（`escalation.ts`）。

**结论：Guard = 执行前单调否决；Permission = session/sandbox 授权状态 + 每调用 policy 折叠；Approval = 人工/策略门，是可审计的服务 seam。** 用户提议的划分与源码基本一致，但 "Permission 是 runtime authorization" 在 DSH 中表现为 tool-body 消费的 policy，而非 waterfall 节点。

---

## 4. Approval

已在上节覆盖。补充：

- `allowed-once` 是唯一 grant，只作用于被请求的这一次调用（`user-approval/src/types.ts:16-23`）。
- 无 ApprovalService、无 agent、无可用 answerer 均 fail-closed 为 deny，reason 各不相同（`tools/src/index.ts:1689-1727`）。
- abort 会撤回请求：`signal.aborted` → `cancelled`；迟到 answer 被丢弃（`user-approval/src/index.ts:237-272`）。
- 审批事件不是 model-visible surface event（`user-approval/src/index.ts:57-68` 注释）。

---

## 5. Execute

调度链（VERIFIED）：

```text
executeToolCalls (tool-calls.ts:59-118)
  → append tool/call
  → scheduler.prepare  = pre-execute / approval / guards（tools/src/index.ts:1459-1504）
  → scheduler.dispatch = tools/execute waterfall + tool body（index.ts:1532-1607）
  → scheduler.finalize = tools/post-execute + finalizeContent + materialize + tools/result（index.ts:1609-1658）
  → append tool/result（tool-calls.ts:268-288）
```

- **sync/async**：`ToolDefinition.execute(args, exec): Promise<unknown>`（`index.ts:222-246`）；body 必须观察/转发 `exec.signal` 并到达 quiescence；同进程 promise 无法硬杀（`index.ts:235-245`）。
- **concurrency**：`isConcurrencySafe` 精确返回 `true` 才 parallel，否则 exclusive；每 step 默认 `maxParallelToolCalls = 10`（`tools/src/index.ts:1276-1300`；`agent-loop/src/constants.ts:6`）。Code Mode 子调度默认 `maxParallelSubCalls = 10`（`index.ts:836-844`）。有序阶段（pre/post/commit）单 lane，只有 body 重叠（`code-mode.ts:346-373`）。
- **subprocess / sandbox**：`subprocess-local` detached process tree（SIGTERM → grace → SIGKILL）；`SandboxProvider.confine()`，无可用后端 → `SANDBOX_UNAVAILABLE`（03 §1.3/§1.8；`sandbox/src/index.ts:124-145`）。
- **failure**：工具抛错、无效输出、未知工具全部归一为 `isError` 结果（`toolErrorResult`，`index.ts:1928-1937`）；`HarnessError` 保留结构化 `{name, code}`（`UNKNOWN_TOOL` / `INVALID_TOOL_OUTPUT` / `SANDBOX_UNAVAILABLE` 等）。只有**内部调度失败**（`schedulerFailure`）才向 agent loop 抛错 → turn error（`tool-calls.ts:202-234`）。

---

## 6. Timeout / Cancellation

### Timeout（VERIFIED）

- 工具声明 `timeoutMs`（`tools/src/index.ts:249-255`）；`dsh-tool-call-timeout-policy` 在 `tools/execute` 层用 `deadline()` 替换 `exec.signal`，到期把结果替换为 `TOOL_TIMEOUT` 的 `isError` result（`packages/guard/timeout-policy/src/index.ts:20-81`）。
- shell 工具还接受模型传入的 `timeoutMs`（03 §1.3）。
- timeout 是 **tool-result 层失败**：不抛错、不终止 step/turn；模型看到 `Error: tool call timed out after Xms` + code `TOOL_TIMEOUT`（03 §1.3）。

### Cancellation（VERIFIED）

- `AgentCancelCause { user | parent | hook | disposed }`（`session/src/types.ts:144-150`）。
- 未启动 body：`ABORTED_BEFORE_DISPATCH` 合成错误结果；已启动 body：协作式 abort，成功后若已取消则替换为 `ABORTED`（`tools/src/index.ts:1532-1567, 1919-1946`；`tool-calls.ts:249-260`）。
- wrapper 可替换 signal，但 registry 把 caller signal 重新融合，避免 detach（`fuseToolSignals`，`index.ts:1559-1603`）。
- step 级：`step/end` 在 `agent.ts` 的 `finally` 中 append（`agent.ts:292`）→ **aborted/error 路径也有 step/end**（本阶段直接确认；14 §9 Unknown #1 可更新）。turn 级：`turn/end{aborted}`（`agent.ts:349-362`）。

---

## 7. Retry

**Tool-level automatic retry：NOT FOUND。**

- 全仓库没有工具级重试策略/插件实现。`tools/execute` 的 JSDoc 提过 "timeout, retry, or metrics"，`timeout-policy` README 提过 "future retry wrapper"，但当前基线只有 timeout wrapper（`tools/src/index.ts:157-169`；`guard/timeout-policy/README.md:36`）。
- 工具失败 → `isError` tool/result → 是否重试由模型决定（05 §1）。
- 不要混淆：
  - **LLM retry** = `llm-retry` + `agent/request-error`（05 §1；`llm/llm-retry/src/index.ts`）。
  - **Compaction retry** = context-overflow 后同一模型请求重试（05 §1）。
  - **repeat-tool-reminder** = 只注入建议、不 veto、不自动重试（`guard/repeat-tool-reminder/README.md:5`）。
  - **MCP reconnect** = 基础设施连接恢复，不是 tool retry（03 §1.7）。

---

## 8. Post-execute

Waterfall：`tools/post-execute(exec, result, next)`（`tools/src/index.ts:175-188`；`postExecute` 1742-1792）。

能力（VERIFIED）：

- `accept`：可替换 `content`，**或**替换 `value`（后者重新走 output schema 校验 + render，`createSuccessResult`）；可附加 `additionalContexts`。
- `block`：把结果变成 `isError`，content = corrective feedback；只暴露 block 决策自己给的 `additionalContexts`（body defer 的 context 被丢弃）。
- 两个都有会抛错 → 最终 isError。
- 监听器抛错被包含 → `toolErrorResult`（`finalizeScheduledExecution` catch，`index.ts:1609-1629`）。

**post-execute 是否可以替换原始 tool output？可以。**

- 最终结果（post-execute 后 + 工具自有 `finalizeContent` 后）是唯一被 append 的 `tool/result`；原始 body `value` 从不写入事件（`index.ts:556-558` "deliberately omitted from durable events"）。
- 工具定义 `finalizeContent` 在 post-execute **之后**、materialize 之前执行，只能替换 content（`index.ts:247-253, 1631-1658`）。
- `tools/result` emit 观察者看到的是 deep-frozen 最终快照（`index.ts:1638-1660`）。
- Code Mode 的 `tools/code-dispatch-log` 可替换子调度的**持久化日志副本**，但程序已收到完整 value，模型看到的不是该日志（`index.ts:170-189`）。

---

## 9. Result

`ToolExecutionSuccess | ToolExecutionFailure`（`tools/src/index.ts:556-580`）：

- Success：`content`、可选 `value`（执行局部、不落盘）、`meta`、`additionalContexts`、`concludesTurn?: true`。
- Failure：`content`、`error { message, info? }`、可选 `meta` / `additionalContexts`；`concludesTurn?: never`。

`tool/result` 事件持久化 `message` + 可选 `error {name, code}` + 可选 `meta`；**value、additionalContexts、concludesTurn 均不持久化**（§1）。

模型可见：`tool/result` 是 surface event，`deriveMessages()` 直接投影 `event.data.message`（`session/src/surface.ts:18, 106-112`）。

---

## 10. concludesTurn

问答（VERIFIED，除注明外）：

1. **`concludesTurn=true` 如何让 Turn 完成？** Tool body 调 `exec.concludeTurn()` → 成功结果带 `concludesTurn: true` → scheduler 聚合 `concluded` → `executeToolCalls` 返回 `{concluded: true}` → `step()` 返回 `{kind:'completed'}` → turn loop 在 `agent/turn-stopping` 后以 `completed` 关闭（`tools/src/index.ts:404-445, 1793-1859`；`tool-calls.ts:94-118, 157`；`agent.ts:395-399, 352-368`）。
2. **是否要求 assistant message？** 不要求新 assistant message。assistant/message（含 tool-call）已在本 step 存在；`concludesTurn` 后直接以 `completed` 结束，不再生成收尾 assistant 消息（`agent.ts:376-397`）。
3. **tool result 是否进入下一 Step？** 是（两载体）：`tool/result` 进 surface/deriveMessages；`additionalContexts` 进 next-step inbox → 下一 step 的 `user/message`（`agent.ts:395-399, 321-326`）。但 `concludesTurn` 只在 next-step inbox 排空后才关闭 turn；同一批 `additionalContexts` 或 racing steering 仍先跑（`agent/src/runtime-types.ts:268-278`）。
4. **concludesTurn 与 tool failure 的关系？** failure 类型禁止 `concludesTurn`（`index.ts:576`）；timeout/cancel/deny 都是 failure，不能结束 turn。
5. **持久化**：`concludesTurn` 不是 `tool/result` 事件字段；durable 可观测事实只有随后的 `turn/end{completed}`（PARTIAL / UNKNOWN as direct evidence）。

---

## 11. Failure Matrix

| Failure | Event | Step | Turn | Retry |
| --- | --- | --- | --- | --- |
| timeout | `tool/result` isError，code `TOOL_TIMEOUT` | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND；模型决定 |
| permission denied | `tool/result` isError；fs 保留 `FS_SANDBOX_DENIED` 结构化 code，escalation 拒绝为纯 message（VERIFIED） | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND 自动；模型可带 `sandbox_permissions + justification` 单次重试并经 approval（VERIFIED） |
| approval rejected | `approval/asked` + `approval/decided` + `tool/result` isError（VERIFIED） | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND 自动；模型可重新请求（05 §1） |
| guard rejected | `tool/result` isError，仅 `error.message`（无 code）（VERIFIED） | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND |
| execution error | `tool/result` isError；HarnessError 带 `{name, code}`（`UNKNOWN_TOOL` / `INVALID_TOOL_OUTPUT` 等）（VERIFIED） | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND |
| post-execute error | 监听器 throw 被包含为 `tool/result` isError（VERIFIED） | 继续（VERIFIED） | 继续（VERIFIED） | NOT FOUND |
| process crash | repair 合成 `tool/result`（`TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN`）+ `step/end` + `turn/end{interrupted}`（VERIFIED，`repair.ts:31-134`） | 合成关闭 | interrupted | PARTIAL：修复文本提示模型只对只读/幂等操作重试；无自动重试（05 §1） |
| cancellation | 未启动 → 合成 `ABORTED_BEFORE_DISPATCH`；已启动 → `ABORTED`（VERIFIED） | `step/end` 经 finally append（VERIFIED，agent.ts:292） | `turn/end{aborted}`（VERIFIED） | NOT FOUND；`keepInbox` 可保留排队工作（runtime-types.ts:20-28） |
| internal scheduler failure | 不伪造未启动调用的结果；保留已记录 `tool/call`；向 loop 抛错（VERIFIED，tool-calls.ts:202-234） | 抛错 → step 异常 | `turn/end{error}`（VERIFIED，agent.ts:349-362） | NOT FOUND |

---

## 12. Event Semantics

| 事件 | 模型历史 | 状态 |
| --- | --- | --- |
| `tool/call` | 否（trace/replay only） | VERIFIED（14 §4；surface.ts:85） |
| `tool/result` | 是（`message` 直接投影） | VERIFIED |
| `tool/code-dispatch-start` / `tool/code-dispatch` | 否 | VERIFIED（known-event-types.ts；code-mode） |
| `approval/asked` / `approval/decided` / `approval/policy` | 否（log-only audit / policy） | VERIFIED |
| `permission/preset` / `sandbox/mode` | 否（log-only policy state） | VERIFIED |
| `llm/retry` / `llm/retry-started` | 否 | VERIFIED（14 §3） |

顺序约束（VERIFIED）：

- `tool/call` 在 pre-execute 之前 append（`tool-calls.ts:164-178`）。
- `tool/result` 在 `step/end` 之前、且用 `sourceEventSeqs` 引用同 step 的 `tool/call`（`tool-calls.ts:268-288`；`session/invariant.ts:122-141`）。
- `additionalContexts` 的持久化轨迹是下一 step 的 `user/message` 事件，而不是 `tool/result` 事件内的字段（`agent.ts:321-326, 395-399`）。
- `concludesTurn` 没有事件字段；可观测结果是 `turn/end{reason: completed}`（§10）。

---

## 13. Capability Boundary

- DSH 侧：Tool **ownership** = 注册/可见性/scope 遮蔽/restriction（`tools.register()` / `restrict()` / `guard()`，`tools/src/index.ts:1040-1126`）；Tool **execution semantics** = pre/guard/around/post/result pipeline（`index.ts:1329-1648`）。两者在源码里是不同机制，但属于同一 `ToolRuntime` 服务。
- Phase 2 Python：Capability Runtime = lifecycle truth（install/dispose / EffectRegistry / 注册所有权），DSH Event Store = execution truth；13 §13.2 已冻结概念分离，event domain 是否合并仍是 open（13 §13.3）。
- 建议：**所有权与执行语义分开**，这已被两侧源码支持；是否同一 event domain 保持 open question，不在此阶段定案。

---

## 14. AgentScope Boundary

- DSH 仓库内没有外部 AgentScope Toolkit 依赖（`rg agentscope package.json packages` 无命中）；仓库里的 "AgentScope" 仅指内部 Cordis agent scope（`createScope` / `agent.ctx`）。
- Python 侧（Phase 2-B/2-D，本工作区文档证据）：AgentScope 2.0.2 提供 scheduling / dispatch substrate（`Agent.reply_stream`、`Toolkit`、`FunctionTool`、`AgentEvent`、`PermissionContext`），Semantic Layer 通过 `adapters.agentscope` 只使用 public API 管理注册/事件/worker/service；`PluginManager` / `Capability` 不 import AgentScope（`docs/archaeology/python-cordis/11-agentscope-bridge.md` §2/§7；`13-capability-manager.md` §8）。
- 因此 "AgentScope = scheduling/dispatch，DSH semantic layer = policy/waterfall/lifecycle/event semantics" 目前是 **Python Phase 2 本地证据 + 设计方向（INFERENCE）**，不是 DSH 源码中已存在的桥（NOT FOUND）。未来桥必须由 API/source evidence 决定。

---

## 15. Verified / Partial / Unknown / Inference

### VERIFIED

1. Tool waterfall 作为显式 pipeline 存在：pre-execute → approval → guards → execute → post-execute → finalizeContent → materialize → tools/result → `tool/result` 事件（§2/§5/§8）。
2. `tool/call` / `tool/result` 事件 schema、callId 配对、`sourceEventSeqs`、turn/step 归属（§1）。
3. pre-execute 支持 allow/deny/ask；deny 物化 isError；reject 不结束 step/turn（§2）。
4. Guard / Permission / Approval 三个概念可区分，且 Permission 不在 registry pipeline 中（§3）。
5. Timeout、cancellation、ABORTED / ABORTED_BEFORE_DISPATCH、TOOL_TIMEOUT 语义（§6）。
6. 工具失败不隐式失败 step/turn；只有内部 scheduler failure 抛错（§5/§11）。
7. post-execute 可替换 content/value、block、附加 additionalContexts；只有最终结果落 `tool/result`（§8）。
8. `concludesTurn` 只存在于成功结果，令 turn 以 completed 关闭，不要求新的 assistant message；失败不能 conclude（§10）。
9. aborted/error 路径也有 `step/end`（agent.ts:292 finally；更新 14 §9 的 UNKNOWN #1）（§6/§11）。
10. 崩溃修复合成 `tool/result` + `step/end` + `turn/end{interrupted}`，含 TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN（§11）。

### PARTIAL

1. `tool/call` 事件缺少 initiator/agent、运行时 token/rootCallId/parent（运行时存在，事件未持久化）。
2. `concludesTurn` 无可持久化字段；只能从 `turn/end{completed}` 推断。
3. `additionalContexts` 不随 `tool/result` 持久化；durable 载体是下一 step 的 `user/message`。
4. aborted 时 `step/end` 已确认（见上），但 turn error 路径的 step 归属等仍依赖调用图推断。
5. Tool ownership 与 execution semantics 分离：源码与 Python Phase 2 都支持，event domain 合并未决（13 §13.3）。

### NOT FOUND

1. Tool-level automatic retry。
2. `tool/result` 事件内的 `additionalContexts` / `concludesTurn` / `value`。
3. DSH 与外部 AgentScope Toolkit 的任何现成桥 / 依赖。
4. 独立的 "Permission" registry pipeline stage（源码中不存在）。

### UNKNOWN

1. 未来 AgentScope ↔ DSH semantic layer 的桥接契约（设计方向 INFERENCE，无 DSH 源码证据）。
2. Capability lifecycle 事件是否与 execution 事件同一 domain（13 §13.3 open）。
3. 普通 deny（无 error.info）的持久化失败身份是否足够支撑 replay 路由（DSH 未定义）。

---

## Core Invariants

| # | Invariant | 状态 |
| --- | --- | --- |
| TW-01 | Every tool invocation has a stable call identity | VERIFIED（callId + turn/step + 事件 seq + sourceEventSeqs；registry token 仅进程内） |
| TW-02 | tool/call is recorded before or at execution boundary | VERIFIED（append 先于 prepare/dispatch，tool-calls.ts:164-178） |
| TW-03 | Tool execution passes through explicit pre-execute semantics | VERIFIED（tools/pre-execute waterfall） |
| TW-04 | Approval/permission/guard semantics are distinguishable | VERIFIED（§3 三机制；Permission 为 session policy + tool-body 消费） |
| TW-05 | Tool execution result is represented explicitly | VERIFIED（success/failure union + tool/result） |
| TW-06 | Tool failure does not implicitly mean Step failure | VERIFIED（isError result；scheduler failure 除外） |
| TW-07 | Tool result can feed the next Step | VERIFIED（surface 派生 + additionalContexts → inbox → user/message） |
| TW-08 | Post-execute may affect model-visible result only per explicit semantics | VERIFIED（accept/block + finalizeContent；原始 value 不落盘） |
| TW-09 | concludesTurn is an explicit execution control signal | VERIFIED（运行时标记 + completed；失败禁止） |
| TW-10 | Tool lifecycle ownership is orthogonal to tool execution semantics | PARTIAL（DSH 与 Python 均分层；event domain 未决） |

---

## Final Verdict

**PARTIAL**

DSH Tool Waterfall 本身存在且大部分语义为 VERIFIED（pre-execute / guards / approval / execute / timeout / cancel / post-execute / result / concludesTurn / failure 分层）。PARTIAL 的原因是：`concludesTurn` 与 `additionalContexts` 无可持久化事件字段、AgentScope 桥只有本地 Python Phase 2 证据、Capability/execution event domain 仍未决。
