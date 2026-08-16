# 20 — Codex → Unified Semantic Runtime Mapping（Phase 5-A）

> 目标：把已考古的 Codex（openai/codex @ `279b93242cfef379e65da97e87e44b83c5934fd7`，2026-08-11）映射到冻结的 DSH / Unified Semantic Runtime 契约。
> Unified 基线：`13-event-sourcing-contract.md`、`14-turn-step-contract.md`、`15-tool-waterfall-contract.md`、`16-causal-chain-contract.md`、`17-semantic-runtime-model.md`、`21-context-compaction-contract.md`；Capability：`python-cordis/12/13`；Phase 4 实现：`deepseek-harness/runtime/`。
> 方法：复用 `docs/archaeology/codex/00-10/99/verification-01` + `research/codex*`；关键争议点直接复核 Codex 源码。源码事实与 Adapter interpretation 分开标注。
> 状态词（本文件）：EXACT / ADAPTER / LOSSY / MISSING / UNKNOWN / BACKEND-SPECIFIC。

---

## 0. 结论摘要

1. **Codex 不能以 EXACT 语义接入**：Session/Turn 边界有可对应对象，但 Step 没有原生持久化对象，Tool Call/Result 缺少 step 级归属与结构化 lineage，exec 失败 `success` 固定 true，crash recovery 缺少 unknown-outcome 标记。
2. **通过 Adapter 可以在不改 Semantic Core contract 的前提下承载**：Unified 的 Session/Turn/Step、EventLog/Surface、Tool Waterfall、Authorization 都有可翻译的 Codex 对应物，翻译规则全部属于 Adapter 职责。
3. **最终判定：PARTIAL**。存在多个 LOSSY / MISSING 语义（Step 边界、exec 失败、crash unknown outcome、Capability/Initiator），不得宣称 PASS。

---

## 1. Coverage Matrix

`Unified` 列 = 冻结契约中的语义；`Codex` 列 = 本次复核的源码事实；`Status` 只允许本文件词表。

| Unified | Codex 源码事实 | Status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Session | 线程级运行上下文，同时最多 1 个 task；持久化为每线程 rollout + SessionMeta（含 forked_from_id / parent_thread_id） | ADAPTER | `session/session.rs:32-58`；`protocol/protocol.rs:2855-2895`；`rollout/src/recorder.rs:15-17` | 语义边界（一个执行历史边界）一致，但 Codex Session 是 runtime struct + 独立 rollout，不是 Unified SessionEvent log；Unified Session 需由 Adapter 从 rollout 构建 |
| Turn | 公开事件层：`TurnStarted`（一次/ Task）→ `TurnComplete`/`TurnAborted`/`Error`；`TurnContext` 是单 turn 配置（sub_id/trace_id/mode/session_source/parent_thread_id）；`run_turn` 是内部循环 | ADAPTER | `tasks/regular.rs:44-61`；`tasks/mod.rs:566,815-830`；`session/turn_context.rs:129`；`session/turn.rs:154` | Unified Turn = 0..N Step；Codex 公开 Turn = Task 生命周期事件；内部 `run_turn` 是 BACKEND-SPECIFIC 控制边界（见 §2） |
| Step | 无持久化 Step 对象；`StepContext` 是“单次采样请求快照”（env/MCP/tool_router），每次 sampling request 捕获一次；retry 在同一 sampling request 内 | ADAPTER | `session/step_context.rs:12`；`session/mod.rs:3112-3200`；`session/turn.rs:314-364,1334-1415` | Unified Step = 一次模型请求 + 关联工具活动；Adapter 必须从 sampling request 构造 Step 边界；无 step_id 持久化、无 step/start-end 事件（LOSSY 细节） |
| Execution | `StepContext` + `ToolCallRuntime` + `ModelClientSession::stream` + `ToolRouter.dispatch_tool_call_with_terminal_outcome` | ADAPTER | `session/turn.rs:1334-1345`；`tools/parallel.rs:41,69`；`tools/router.rs:233` | 运行时实例语义可对应；Execution 本身不持久化 |
| Model Request | `run_sampling_request` 构造 prompt + `client_session.stream`；`TurnContextItem` 持久化 turn 级配置（approval/sandbox/model/cwd）；`WorldStateItem` 持久化上下文基线 | ADAPTER（LOSSY） | `session/turn.rs:341-364,1334-1360`；`protocol/protocol.rs:2984-2998,3011-3050` | 无默认 per-request header 事件；只有 opt-in `RolloutTrace.InferenceCall` 含 request/response 快照（`rollout-trace/src/model/conversation.rs:161-182`） |
| Assistant Stream | `ResponseItem::Message/Reasoning` 持久化；`AgentMessageContentDelta`/`RawResponseItem` 事件发给客户端并持久化 | LOSSY | `protocol/models.rs:816-864`；`session/mod.rs:3043-3068,3412`；`protocol/protocol.rs:1461,1827` | Unified 要求 chunk→message 的 `sourceEventSeqs`；Codex 默认不持久化 chunk 级 lineage，Adapter 只能从最终 item 重建 |
| Tool Call | `ToolCall { tool_name, call_id, payload }`；`ResponseItem::FunctionCall/CustomToolCall/ToolSearchCall` 带 call_id；`ExecCommandBegin/End` 事件带 call_id + turn_id | ADAPTER（LOSSY） | `tools/router.rs:34-44`；`protocol/models.rs:865+`；`protocol/protocol.rs:3248-3312` | call_id 身份存在；无 step_id、无 call→result 的持久化 sourceEventSeqs；归属只能由顺序/分段推导 |
| Tool Result | `ResponseItem::FunctionCallOutput/CustomToolCallOutput/ToolSearchOutput` 带 call_id + success；exec `success` 固定 `Some(true)`；MCP 用真实 `result.success()`；取消 `success: None` | ADAPTER（LOSSY） | `tools/context.rs:339-347,163,283-307`；`tools/parallel.rs:230-282` | Unified `tool/result` 是模型可见 surface 事件；Codex 的 rollout ResponseItem 等价物存在，但 exec 失败不结构化为失败 |
| Tool Error | 非 fatal 错误 → `FunctionCallError` → `FunctionCallOutput(success=false)` 回模型；exec 非零退出码只进文本；fatal 工具错误 → `CodexErr::Fatal`；approval 拒绝 → 拒绝消息作为工具输出 | LOSSY | `tools/parallel.rs:230-282`；`tools/context.rs:339-347`；`tools/events.rs:66-72`；`tools/orchestrator.rs:202-225` | Unified：tool failure ≠ step/turn failure；Codex 大体符合，但 exec 失败无法从结构区分，且 fatal 错误会终止 turn |
| Event Log | 默认 append-only rollout JSONL：`RolloutItem { SessionMeta / ResponseItem / InterAgentCommunication / Compacted / TurnContext / WorldState / EventMsg }` | ADAPTER | `history/src/lib.rs:30-44`；`rollout/src/recorder.rs:15-17`；`session/mod.rs:2126-2132` | 原生日志是 EventLog 的 source，但 schema 不同；`EventMsg::RawResponseItem` 是 ResponseItem 的客户端投影副本，Adapter 应去重（见 §3） |
| Surface | `ContextManager`：内存历史（`items: Arc<Vec<ResponseItem>>`）+ 过滤（`is_api_message`）+ 截断 + `for_prompt()` 投影 | ADAPTER | `context_manager/history.rs:42,145,485-512`；`session/turn.rs:341` | 投影语义存在，但没有独立 Surface 对象；compaction 以 `replace_compacted_history` 替换内存窗口（见 §7） |
| Model Context | `clone_history().for_prompt(input_modalities)` → `build_prompt`（base instructions + tools + messages） | ADAPTER | `session/turn.rs:341-364`；`context_manager/history.rs:145`；`tools/spec_plan.rs:316-449` | 每次采样前重建；不持久化为独立对象；与 Unified “Context = System + Runtime + Surface-derived History + User Input” 可对应 |
| Compaction | `CompactedItem { message, replacement_history, window_number, window_ids }` + `WorldState` + `TurnContextItem` 追加进 rollout；内存历史替换；旧 item 保留；resume 以最新 `replacement_history` 为重建基 | ADAPTER（LOSSY） | `history/src/lib.rs:42-56`；`session/mod.rs:3312-3358`；`session/rollout_reconstruction.rs:9-24,120-160` | 原则同 Unified（append-only + 投影替换），但无 `compaction/start…end` 事务事件、无显式 shadowed-range/sourceEventSeqs；`CompactedItem` 是“新事实”而非“replacement 事件 + lineage” |
| Retry | 模型流错误：同一 sampling request 内指数退避 + WS→HTTP fallback；工具失败：不自动重试（sandbox denial 除外）；compaction 后：新 sampling request 继续 | ADAPTER（LOSSY） | `session/turn.rs:1398-1415`；`responses_retry.rs:65-125`；`session/turn.rs:447-478`；`unified_exec/mod.rs:6-16` | Unified LLM retry 在同一 Step 内；Codex 模型流 retry 也在同一 sampling request（可视为同 Step），但 compaction 后重试会开启新 sampling request（新 Step）——不同 |
| Replay | resume/fork/rollback 都由 rollout 重建：`InitialHistory::Resumed/Forked`；`RolloutReconstruction` 反向扫描 + 正向前放；rollback = 追加 `ThreadRolledBack` 标记 + 重建时跳过最后 N 个用户 turn | ADAPTER | `session/mod.rs:1360-1450`；`session/rollout_reconstruction.rs:9-24`；`session/handlers.rs:452-554` | 都是“重建历史”，不是“重新执行模型/工具”；trace `replay_bundle` 是原始事件确定性重放（`rollout-trace/src/reducer/mod.rs`）。不得与 Unified replay 等同（BP-07） |
| Recovery | 中断：记录 interrupted-turn marker（ResponseItem）+ `TurnAborted` 后 flush；resume 若最后状态是 Interrupted 则恢复该状态；rollout 尾部有终止修复 | MISSING（部分 ADAPTER） | `tasks/mod.rs:927-967`；`thread_manager.rs:2121-2142`；`session/mod.rs:1371-1376`；`rollout/src/recorder_tests.rs:138` | Unified 要求崩溃尾部合成 `tool/result + step/end + turn/end{interrupted}` 且区分 `TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN`；Codex 无这两个标记（MISSING） |
| Initiator | 无 ambient initiator / current agent 上下文；只有 `TurnContext.originator`（产品/客户端来源串，用于 Responses metadata）与 session 级 agent_path / parent_thread_id | MISSING | `session/turn_context.rs:129-165`；`session/session.rs:123-126`；`protocol/protocol.rs:2855-2879` | 不发明 `initiator_id`；Codex 没有“当前执行身份”对象。Unified initiator 只能由 Adapter 从 session/thread 边界推导或标记为 UNKNOWN |
| Parent/Child | `SessionMeta.forked_from_id` / `parent_thread_id`；`SubAgentSource::ThreadSpawn { parent_thread_id, depth, agent_path }`；`InterAgentCommunication`（author/recipient AgentPath）持久化；state DB 有 parent/child 边 | ADAPTER | `protocol/protocol.rs:2647-2662,2855-2895`；`session/mod.rs:3188-3235`；`state/src/runtime/threads.rs:105-170` | durable lineage 存在且可恢复；但事件层没有 `parentCallId/rootCallId` 之外的统一因果字段；tool call 级 initiator 不持久化 |
| Ownership | 资源由 SessionServices 持有：MCP runtime（“single owner of live MCP connections”）、UnifiedExecProcessManager、ApprovalStore、skills/plugins/extensions；ToolRouter 每 step 重建 | BACKEND-SPECIFIC | `state/service.rs:46-70`；`tools/spec_plan.rs:119-170`；`session/mod.rs:3125-3200` | 谁调用 ≠ 谁拥有；Codex 的 owner 是 session-scoped 服务，不是 Capability/Scope；见 §5 |
| Capability | 无 Capability 对象；skills / plugins / MCP / dynamic tools 只是工具贡献者；`SelectedCapabilityRoot` 是 executor 能力根，不是 lifecycle 所有权 | MISSING | `tools/spec_plan.rs:119-170`；`protocol/protocol.rs:2891-2893` | Unified Capability = 独立 lifecycle truth（install/dispose/scope/effect）；Codex 没有对应物，不可强制映射 |
| Scope | 无 PluginScope / EffectRegistry 等价物 | MISSING | 同 Capability | — |
| Effect | 无统一 effect 注册/回收；MCP 连接、进程、审批缓存等按 session 服务生命周期管理 | MISSING | `state/service.rs:46-70` | — |
| Authorization | 工具执行前 `ToolOrchestrator`：approval（Skip/Forbidden/NeedsApproval）→ sandbox → run；Guardian 是自动审批审查（allow/deny + risk）；事件：`ExecApprovalRequest` / `ApplyPatchApprovalRequest` / `GuardianAssessment` | ADAPTER（LOSSY） | `tools/orchestrator.rs:137-240`；`session/mod.rs:2524-2537`；`protocol/approvals.rs:179-261` | Unified：approval/guard/permission 是三个可区分机制；Codex approval 是执行流水线 stage + Guardian 外部策略；无统一 authorized_principal 字段 |
| Sandbox | sandbox 选择/变换在工具执行路径；denial 自动以 `SandboxType::None` 重试（策略允许时）；`TurnContextItem` 持久化 sandbox_policy/permission_profile | ADAPTER（BACKEND-SPECIFIC） | `unified_exec/mod.rs:6-16`；`tools/orchestrator.rs:330-440`；`protocol/protocol.rs:3023-3028` | 自动无沙箱重试改变 effect/safety 语义，是 Codex 特有行为；Unified Sandbox 无对应自动降级语义 |
| Approval | `ExecApprovalRequirement { Skip / NeedsApproval / Forbidden }`；用户通过 `Op::ExecApproval` 决定；拒绝 → 工具输出回模型（不结束 turn） | ADAPTER | `tools/sandboxing.rs:152-225`；`tools/orchestrator.rs:172-225`；`tools/events.rs:66-72`；`protocol/protocol.rs:581-590` | approval 是 Codex 工具执行流水线的显式 stage；Guardian 是额外 external policy；对应 Unified approval stage（ADAPTER） |

---

## 2. Session / Turn / Step 映射（源码事实 vs Adapter interpretation）

### 2.1 源码事实

- `Session`：线程级运行上下文，注释明确 “A session has at most 1 running task at a time, and can be interrupted by user input.”（`session/session.rs:32-58`）。持久化按线程 rollout。
- `SessionTask`：可运行工作单元抽象（Regular/Review/Compact/UserShell），`SessionTask::run` 是 task 生命周期（`tasks/mod.rs:188-230`）。
- `RegularTask::run`：发出一次 `TurnStarted`，然后循环调用 `run_turn`，直到 input queue 无 pending input（`tasks/regular.rs:30-87`）。task 结束由 `on_task_finished` 发出 `TurnComplete`/`TurnAborted`（`tasks/mod.rs:566,815-830`）。
- `run_turn`：内部循环，每次迭代 = 一次 sampling request（`run_sampling_request` → `try_run_sampling_request` → tool call/result → `drain_in_flight`），直到 `needs_follow_up == false` 且无 pending input + stop hooks 放行（`turn.rs:154,282-500,2547-2562`）。
- `StepContext`：每次 sampling request 捕获一次，注释 “Capture once so context, advertised tools, and tool calls share one request view”（`turn.rs:314-318`；`step_context.rs:12`）。它不是持久化对象。
- 源码注释明确 Codex 内部“turn”与用户视角“turn”不同：`TurnDiffTracker has the lifecycle of a Task which contains many turns, but from the perspective of the user, it is a single turn`（`turn.rs:266-270`）。
- `RolloutTrace` 的 `CodexTurn` 注释：`One activation of the Codex runtime for one thread … It is not a user/assistant message pair`（`rollout-trace/src/model/session.rs:98-110`）。

### 2.2 六个问题的回答

**Q1. Codex Session 是否可以直接映射 Unified Session？**

源码事实：Codex Session 是“一个线程 + 一个运行中 task”的运行时边界，且每线程有独立 rollout 与 SessionMeta lineage。Unified Session 是“一个 append-only SessionEvent log + header lineage”。

Adapter interpretation：**ADAPTER**。可以按 1:1 建立 `Codex Session/Thread ↔ Unified Session`，但 Unified SessionEvent log 必须由 Adapter 从 rollout 翻译，不能把 Codex `Session` struct 当成 Unified Session。

**Q2. Codex Task 是否对应 Unified Turn、Step，还是其他控制边界？**

源码事实：`TurnStarted`/`TurnComplete` 的 `turn_id` 是 `TurnContext.sub_id`，由 Task 生命周期发出；一次 RegularTask 可包含多次内部 `run_turn`。

Adapter interpretation：**Codex Task（公开事件层）↔ Unified Turn**（一次用户可感知交互边界，含 0..N Step）。**内部 `run_turn` 是 BACKEND-SPECIFIC 控制边界**（可含 1..N sampling requests；一个 Task 内可多次执行），不映射到 Unified 的任何固定对象，除非 Adapter 需要保留为 backend metadata。不能把“Codex Turn”（内部 run_turn）与 Unified Turn 直接等同。

**Q3. Codex Turn 是否等价于 Unified Step？**

不是。源码事实：一次 `run_turn` 可以包含多个 sampling request（每个都有自己的 StepContext 和 tool activity），等价于 Unified 的“一个 Turn 含多个 Step”。内部 `run_turn` 更接近 Unified Turn 的实现循环，而不是 Step。

**Q4. Codex 是否有独立 Step object？**

源码事实：**没有持久化 Step object**；只有 `StepContext`（请求级快照，不持久化）与 opt-in `RolloutTrace.InferenceCall`（一次上游推理请求的结构化记录）。

**Q5. 如果没有，Adapter 如何构造 Step 边界？**

Adapter interpretation：以**一次 sampling request**（`run_sampling_request` / `try_run_sampling_request` 完整周期：模型流 → tool call/result → drain）作为 Unified Step；模型流 retry 仍在同一 Step；compaction 后的继续是新 sampling request，因此是新 Step。Step 归属从 rollout 的 `TurnStarted/TurnComplete` 分段 + ResponseItem/EventMsg 顺序推导，并显式标记 `step_id = adapter-derived`。

**Q6. Rollout 是 EventLog、ExecutionTrace、Projection 还是另一个对象？**

都不是单一个：

| 对象 | 角色 | 证据 |
| --- | --- | --- |
| Rollout JSONL（`RolloutItem`） | **EventLog**（append-only 原生历史，可重建） | `history/src/lib.rs:30-44`；`rollout/src/recorder.rs:15-17` |
| `ContextManager` / `for_prompt` | **Projection**（模型可见历史） | `context_manager/history.rs:42,145` |
| `RolloutTrace`（opt-in） | **ExecutionTrace**（结构化诊断图，非默认、非 source of truth） | `rollout-trace/src/model/mod.rs:30-70` |
| `CompactedItem` | **新事实 / checkpoint**（replacement_history 快照 + window ids），不是 replacement 事件 | `history/src/lib.rs:42-56`；`session/mod.rs:3312-3358` |

---

## 3. Event Source of Truth

### 3.1 五个问题的回答

**Q1. Codex rollout 是否是真正 source of truth？**

源码事实：运行时权威是 `SessionState.history`（内存 `ContextManager`），持久化权威是 rollout JSONL；resume/fork 用 `RolloutRecorder::get_rollout_history` / thread-store 读取并 `reconstruct_history_from_rollout` 重建（`session/mod.rs:1479`；`session/rollout_reconstruction.rs:9-24`）。rollout 是 append-only，注释明确 “Persist Codex session rollouts (.jsonl) so sessions can be replayed or inspected later”（`rollout/src/recorder.rs:15-17`）。

结论：**是持久化 source of truth（执行层）**；内存 `ContextManager` 是运行时投影。与 Unified ES-01 概念一致，但 schema 不同，Adapter 必须翻译。

**Q2. history 是否可以重新构建？**

是（源码事实）：`RolloutReconstruction` 从 rollout 反向扫描 + 正向前放重建 history / reference_context_item / world_state_baseline / auto-compact window（`session/rollout_reconstruction.rs:9-24,120-260`）。重建以最新 `CompactedItem.replacement_history` 为基，旧 item 仍可回溯。

**Q3. RawResponseItem 是否相当于 source event？**

不是。源码事实：`record_conversation_items` 持久化 `RolloutItem::ResponseItem`（`session/mod.rs:3043-3068`）；随后 `send_raw_response_items` 发送 `EventMsg::RawResponseItem`（`session/mod.rs:3412`），`send_event` 默认也把它持久化为 `RolloutItem::EventMsg`（`session/mod.rs:2126-2132`）。因此 rollout 中存在两份：`ResponseItem`（canonical）与 `RawResponseItem`（客户端投影副本）。

Adapter interpretation：把 `RolloutItem::ResponseItem` 作为 raw source event；`EventMsg::RawResponseItem` 视为重复投影，Adapter 必须去重，避免同一内容产生两个 Unified event。

**Q4. EventMsg / Compacted / WorldState / TurnContext 如何处理？**

| RolloutItem | Adapter interpretation |
| --- | --- |
| `EventMsg` | 边界/生命周期/客户端事件（TurnStarted/TurnComplete/TurnAborted/Error/TurnDiff/ExecCommandBegin-End/Approval/Guardian…）。翻译为 Unified trace/log-only 事件或 backend metadata；`TurnStarted/TurnComplete` 决定 Unified turn 边界 |
| `Compacted` | 翻译为 Unified compaction/replacement 语义（保留 raw ref），同时保留 `replacement_history`/window ids 为 backend metadata |
| `WorldState` | 模型上下文基线快照，不是 execution event；映射为 backend metadata（可辅助重建 request context），不进入 Unified SessionEvent 主链 |
| `TurnContext` | turn 级配置快照（approval/sandbox/model/cwd）；映射为 backend metadata，近似 Unified `request/header` 的一部分（ADAPTER） |

**Q5. RolloutTrace 与 Rollout JSONL 的关系是什么？**

源码事实：`RolloutTrace` 是 opt-in（`CODEX_ROLLOUT_TRACE_ROOT`）的 reducer 产物；`RolloutTrace.raw_payloads` 引用原始 payload，`trace_id` 与 `rollout_id` 分离（`rollout-trace/src/model/mod.rs:30-70`；`rollout-trace/src/thread.rs:44,104-115`）。关系：**Rollout JSONL（EventLog）→ TraceWriter 原始事件/负载 → replay_bundle 归约 → RolloutTrace（ExecutionTrace）**。

---

## 4. Tool Mapping

### 4.1 调用链（源码事实）

```text
model ResponseItem (FunctionCall / CustomToolCall / ToolSearchCall)
  → handle_output_item_done (stream_events_utils.rs:288)
  → ToolRouter::build_tool_call (stream_events_utils.rs:296)
  → ToolCallRuntime::handle_tool_call (tools/parallel.rs:69)
      → router.dispatch_tool_call_with_terminal_outcome (tools/router.rs:233)
          → ToolOrchestrator: approval → sandbox → run (tools/orchestrator.rs:137-240)
          → unified_exec / MCP / apply_patch / extension / dynamic tool
  → failure_response / success output → ResponseInputItem (tools/parallel.rs:230-282)
  → drain_in_flight → record_conversation_items (turn.rs:2114; session/mod.rs:3043)
```

### 4.2 七个问题的回答

**Q1. Codex command/exec 是否等价于 ToolCall？**

是（源码事实）：exec/unified_exec 是 ToolRouter 下的 tool runtime 之一；`ExecCommandToolOutput` 是工具输出对象（`tools/context.rs:314-347`）。但 Unified `tool/call + tool/result` 的持久化 schema 在 Codex 中分散为 ResponseItem + EventMsg（ExecCommandBegin/End + ItemStarted/ItemCompleted），Adapter 需要聚合。

**Q2. ToolCall identity 从哪里来？**

源码事实：`ToolCall.call_id` 来自模型 ResponseItem 的 `call_id`（Responses API）或本地 shell call id（`tools/router.rs:34-44`）；`ExecCommandBegin/End.call_id` 配对（`protocol/protocol.rs:3248-3312`）。**没有 step_id**；turn_id 在 exec/approval 事件上存在（`protocol/protocol.rs:3263,3297`），ResponseItem 上只有可选的 passthrough turn_id。

**Q3. tool result 如何进入 next step？**

源码事实：`drain_in_flight` 把 `ResponseInputItem` 转成 `ResponseItem` 并经 `record_conversation_items` 写入内存历史 + rollout；下一轮 prompt 从同一 `ContextManager.for_prompt` 构建（`turn.rs:2114-2130`；`session/mod.rs:3043`；`turn.rs:341`）。

**Q4. tool failure 是否继续 turn？**

源码事实：一般工具失败转为 `FunctionCallOutput(success=false)` 回模型，turn 继续（`tools/parallel.rs:230-282`）；fatal 工具错误（`FunctionCallError::Fatal`）转为 `CodexErr::Fatal` 终止（`tools/parallel.rs:75-88`）；sandbox denial 自动无沙箱重试（`unified_exec/mod.rs:6-16`）。Unified 原则“tool failure ≠ step/turn failure”大体成立，但 fatal 边界存在。

**Q5. timeout 如何映射？**

源码事实：默认 exec 超时 10s（`exec.rs:58`），可被 `timeout_ms` 覆盖；超时进程被杀，输出（含取消/截断标记）作为 tool result 回模型，不自动重试（`exec.rs:142-195`；`tools/parallel.rs:225-247`）。映射为 Unified `tool/result is_error`（TOOL_TIMEOUT 等价），Adapter 需从输出文本/事件推断，因为 rollout 没有结构化 timeout code。

**Q6. sandbox denial 如何映射？**

源码事实：denial 后 orchestrator 在策略允许时以 `SandboxType::None` 重试（`unified_exec/mod.rs:6-16`；`tools/orchestrator.rs:330-440`）；`Never`/`OnRequest` 下可能要求新 approval 或直接拒绝。映射：**BACKEND-SPECIFIC**——Unified 没有“denial 后自动降级无沙箱”语义；Adapter 必须把它暴露为 backend-specific effect，不能当作普通 tool failure。

**Q7. approval 是否是 Waterfall stage 还是 external policy？**

两者都有（源码事实）：`ToolOrchestrator.run` 把 approval 作为工具执行前的显式 stage（`tools/orchestrator.rs:137-240`）；Guardian 是独立的自动审批审查服务（`guardian/mod.rs:116-119`；`session/mod.rs:2524-2537`）。映射：approval = Unified Waterfall 的 approval stage（ADAPTER）；Guardian = external policy / guard（ADAPTER/BACKEND-SPECIFIC）。

**Q8. Tool ownership 在 Codex 中由谁管理？**

源码事实：session-scoped `SessionServices` 持有 MCP runtime（“The single owner of live MCP connections for this thread”）、`UnifiedExecProcessManager`、`ApprovalStore`、skills/plugins/extensions（`state/service.rs:46-70`）；`ToolRouter`/`ToolRegistry` 每 step 由这些服务重建（`tools/spec_plan.rs:119-170`）。**owner = session 服务，不是 Task/Turn/Step，也不是调用方模型**。见 §5。

### 4.3 Tool 映射状态（逐项）

| 项 | Status |
| --- | --- |
| `ToolCallRuntime.handle_tool_call` → Unified Tool Call | ADAPTER |
| `router.dispatch_tool_call_with_terminal_outcome` → Unified Tool Waterfall execute | ADAPTER |
| `exec` / `unified_exec` → Unified Tool Call/Result | ADAPTER（LOSSY：exec 失败结构缺失） |
| `apply_patch` → Unified Tool Call/Result | ADAPTER（有 PatchApplyBegin/End + ApplyPatchApprovalRequest 事件） |
| MCP → Unified Tool Call/Result | ADAPTER（有 McpToolCallBegin/End；result 用真实 success） |
| sandbox → Unified Sandbox | BACKEND-SPECIFIC（denial 自动降级） |
| approval → Unified Approval stage | ADAPTER |
| Tool identity / lineage | LOSSY（无 step_id、无持久化 call→result lineage） |

---

## 5. Ownership Mapping

### 5.1 Codex 资源生命周期（源码事实）

| 资源 | Codex 中的 owner | 生命周期边界 | Evidence |
| --- | --- | --- | --- |
| Session / Thread | ThreadManager / CodexDelegate 创建；`Session::spawn` | 线程创建 → 关闭 | `session/mod.rs:492`；`thread_manager.rs:1783` |
| Task | Session 持有，最多 1 个运行中 task；abort_all_tasks 可替换 | task spawn → on_task_finished / abort | `session/session.rs:32-58`；`session/mod.rs:279-330` |
| Turn（公开） | Session 的 `active_turn` + `TurnContext` | task 生命周期 | `tasks/regular.rs:44-61`；`session/session.rs:48-50` |
| Tool registry / router | SessionServices 提供工具源；`ToolRouter` 每 step 重建 | step 级快照 | `tools/spec_plan.rs:119-170`；`session/mod.rs:3125-3200` |
| MCP connection | `SessionServices.mcp_runtime`（单 owner） | session 生命周期 | `state/service.rs:50-53` |
| subprocess / terminal | `UnifiedExecProcessManager`（session 级，上限 64 进程） | session 生命周期；进程退出/移除 | `state/service.rs:54-55`；`unified_exec/mod.rs:60-64` |
| Sandbox / approval 缓存 | `tool_approvals: Mutex<ApprovalStore>`（session 级） | session 生命周期 | `state/service.rs:61-62` |
| Skills / plugins / extensions | `skills_service` / `plugins_manager` / `ExtensionRegistry`（session 服务） | session 生命周期 | `state/service.rs:63-65` |
| Command execution | 无独立 owner 对象；调用方是 model，执行归属 session 服务 | 每次 exec 调用 | `tools/orchestrator.rs:137-240` |

### 5.2 Unified Capability / Scope / Effect 映射

| Unified | Codex | Status | 结论 |
| --- | --- | --- | --- |
| Capability | 无对应对象；skills/plugins/MCP 是工具贡献者 | MISSING | 不能把工具贡献者误当 Capability |
| Scope | 无 PluginScope | MISSING | — |
| Effect | 无 EffectRegistry；资源回收按 session 服务生命周期 | MISSING | — |
| Capability → Scope → Effect → Tool/Worker/Service | 无 | BACKEND-SPECIFIC | Unified ownership 必须留在 Runtime，不从 Codex rollout 推导 |

**必须保持：`owner != initiator`。** Codex 的 owner 是 session 服务；调用方（模型/工具）不是 owner；Codex 也没有 Unified 意义上的 initiator（见 §6）。

---

## 6. Causality Mapping

### 6.1 六个问题的回答

**Q1. Codex 是否有当前 initiator？**

源码事实：没有 `currentInitiator`/ambient execution identity。最接近的是 `TurnContext.originator`（Responses requests / analytics 的客户端来源串，`session/turn_context.rs:144`；`session/session.rs:123-126`）与 `AgentPath`（multi-agent 路由身份，如 `/root`、`/root/search_docs`，`rollout-trace/src/model/mod.rs:34-37`）。**originator 不是 agent 身份，也不是 initiator_id。**

**Q2. 是否有 ambient execution context？**

源码事实：无 AsyncLocalStorage/ContextVar 级别的执行身份上下文。MCP 请求 metadata 带 `turn_id / thread_id / parent_thread_id / parent_turn_id / subagent_kind`（`turn_metadata.rs:209-250`），但这是请求 metadata，不是运行时 initiator。

**Q3. parent/child lineage 是否持久化？**

是（源码事实）：`SessionMeta.forked_from_id` / `parent_thread_id`（`protocol/protocol.rs:2855-2862`）；`SubAgentSource::ThreadSpawn { parent_thread_id, depth, agent_path }`（`protocol/protocol.rs:2647-2662`）；state DB 保存 parent/child 边（`state/src/runtime/threads.rs:105-170`）。

**Q4. subagent lineage 是否可恢复？**

是（线程级）：SessionMeta + 子线程自己的 rollout；`RolloutTrace.AgentOrigin::Spawned { parent_thread_id, spawn_edge_id, task_name, agent_role }` 可恢复（`rollout-trace/src/model/session.rs:52-66`）。事件级 `InterAgentCommunication` 的 author/recipient 持久化（`session/mod.rs:3188-3235`；`protocol/protocol.rs:739-760`）。

**Q5. Tool Call 能否归因到具体 Agent/Turn/Step？**

源码事实：
- Agent：只能到线程/session（tool call 在哪个线程的 rollout 中执行）；`ExecCommandBegin/End` 的 turn_id 存在，但没有 agent_path 字段。
- Turn：可归因（turn_id 在 exec/approval/guardian 事件；ResponseItem 可选 passthrough turn_id）。
- Step：**不能直接归因**（无 step_id 持久化；只能由 Adapter 从顺序/分段推导）。

**Q6. replay 后 causal lineage 是否可恢复？**

源码事实：线程级 lineage（SessionMeta/state DB）可恢复；事件级 call_id 配对可恢复；**ambient initiator 不存在，因此没有“恢复 ambient”问题**。Unified 的 initiator 语义在 Codex 侧是 MISSING，Adapter 只能建立“session/thread → turn → tool call”的因果链，不能发明 `initiator_id`。

### 6.2 三层区分（17 §5 对齐）

| 维度 | Codex 事实 | Status |
| --- | --- | --- |
| Ownership | session-scoped services | BACKEND-SPECIFIC |
| Causality / Initiator | 无 ambient initiator；有 durable thread lineage + InterAgentCommunication | MISSING（initiator）/ ADAPTER（lineage） |
| Authorization | approval + Guardian + sandbox policy | ADAPTER |

---

## 7. Context / Compaction Mapping

### 7.1 九个问题的回答

**Q1. Codex source history 是什么？**

源码事实：rollout JSONL（append-only `RolloutItem`）是持久化 source history；`ContextManager` 是内存历史投影（`context_manager/history.rs:42`）。

**Q2. ContextManager 是否是 projection？**

是（源码事实）：`ContextManager` 注释 “Transcript of thread history”；`for_prompt` 返回 “prepared for sending to the model”（`history.rs:16,145`）。它等价于 Unified Surface + deriveMessages 的合并实现，但**不是独立 Surface 对象**。

**Q3. Codex history 是否可以恢复 model context？**

是（日志级）：`RolloutReconstruction` 重建 history + reference_context_item + world_state_baseline + window ids（`session/rollout_reconstruction.rs:9-24`）；`for_prompt` 再从 history 生成模型输入。Unified ES-03 的“可重建”对应成立（PARTIAL：依赖 `for_prompt` 投影规则确定性，未单独证明）。

**Q4. compaction 是否删除 source history？**

否（源码事实）：`replace_compacted_history` 只替换内存历史，追加 `CompactedItem + WorldState + TurnContext` 到 rollout（`session/mod.rs:3312-3358`）；rollout append-only。与 Unified COMP-01 一致。

**Q5. CompactedItem 是 replacement/projection 还是新事实？**

源码事实：两者兼有——内存侧是 replacement/projection；持久化侧是**新事实**：`replacement_history` 保存完整新窗口 + window ids（`history/src/lib.rs:42-56`）。Unified 的 `compaction/summary + surfaceOp.replace + sourceEventSeqs` 在 Codex 没有直接等价物；Adapter 需从 `CompactedItem` 合成 replacement 语义并保留 raw ref。

**Q6. world_state_baseline 如何映射？**

源码事实：`WorldStateItem { full: bool, state }` 持久化；`replace_compacted_history` 在 replacement 后写 full baseline（`session/mod.rs:3331-3349`；`protocol/protocol.rs:2984-2998`）。映射为 Unified backend metadata（request context 基线），不进入 SessionEvent 主链。

**Q7. Codex context budget 如何工作？**

源码事实：`context_window_token_status` 计算 auto_compact_scope_tokens / full_context_window_limit / token_limit_reached（`context_window.rs:23-90`）；`run_turn` 采样后检查并触发 `run_auto_compact`（`turn.rs:447-464`）；预采样压缩（`turn.rs:177`）；token-budget 模式跳过模型总结（`compact_token_budget.rs:25-63`）。

**Q8. Unified TokenMeter 是否能表达 Codex budget？**

Adapter interpretation：概念可对应（context window + threshold + retain），但 Codex 使用 provider usage anchor + 本地估算 + auto_compact_window + token-budget/fallback buffer，字段比 Unified TokenMeter 多。Unified TokenMeter 是 estimate（21 CTX-06），可表达基本压力，**不能表达全部 Codex budget 语义**（LOSSY）。

**Q9. Codex compaction retry 是否与 Unified retry semantics 相同？**

不同（源码事实）：Unified compaction overflow retry 在同一 Step 内重建请求（21 §2-10）；Codex 在 `run_auto_compact` 后 `continue` 主循环并捕获**新 StepContext / 新 sampling request**（`turn.rs:447-478`）。因此 **LOSSY**：Adapter 会看到 post-compaction 请求成为新的 Step 边界。

### 7.2 状态汇总

| Unified | Codex | Status |
| --- | --- | --- |
| Event Log → Surface → Model Context 三层 | rollout → ContextManager → for_prompt | ADAPTER |
| Compaction replacement/projection | CompactedItem + replace_compacted_history | ADAPTER |
| Compaction 事务事件 + lineage | 无 start/end 事务、无 sourceEventSeqs | LOSSY |
| Compaction retry 同 Step | compaction 后新 sampling request | LOSSY |
| TokenMeter | context_window + provider usage + estimates | ADAPTER（LOSSY） |

---

## 8. Persistence / Replay / Recovery Mapping

### 8.1 六个问题的回答

**Q1. Codex 的 resume 是否等价 Unified resume？**

ADAPTER：两者都从持久化历史重建（Codex `InitialHistory::Resumed` + `RolloutReconstruction`；Unified resume 从 EventLog 重放）。但 Codex 没有 seed 边界事件、没有 `session/end-seed`；rollback 用 marker；因此不等价（不能 EXACT）。

**Q2. Codex fork 是 event-copy、reference、还是另一个 semantics？**

源码事实：**两者都有**：
- `ForkPersistence::Copied`：把父 rollout 前缀复制进新线程（`thread_manager.rs:1156`；`session/mod.rs:1446-1451`）。
- `ForkPersistence::Referenced { history_base, inherited_item_count }`：子线程只保存 effective 边界，父记录留在 history_base 之后（`thread_manager.rs:1179`；`session/mod.rs:413-420,1431-1438`）。

**Q3. rollback 属于 execution recovery 还是 history mutation？**

源码事实：`thread_rollback` **不重写/截断 rollout**：flush → 读取 stored history → 追加 `ThreadRolledBack` 标记 → `apply_rollout_reconstruction` 重建内存历史（跳过最后 N 个用户 turn）→ 持久化 marker（`handlers.rs:452-554`；`rollout_reconstruction.rs:120-160`）。因此 rollback = **append marker + 投影重建（execution recovery）**，不是 history mutation。

**Q4. tool call 没有 result 时如何恢复？**

源码事实：无 Unified 式 `TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN` 标记（rg NOT FOUND）。中断时只记录 interrupted marker + `TurnAborted`（`tasks/mod.rs:927-967`）。恢复边界 **MISSING**。

**Q5. crash recovery 是否区分 unknown outcome？**

否（源码事实）：无 unknown-outcome 区分；rollout 尾部有终止修复（`recorder_tests.rs:138` 所示 open 时补换行），state DB 有 read-repair（`state_db.rs:594-640`），但没有工具副作用边界判定。

**Q6. RolloutTrace 是否能用于 replay？**

是（源码事实）：`replay_bundle`（`rollout-trace/src/reducer/mod.rs`）确定性重放原始事件并归约出 `RolloutTrace`。但它是 opt-in 诊断通道，不是默认产品路径；且它是“重放原始事件生成 trace”，不是“恢复可继续的 session”。

### 8.2 统一原则

- Replay 恢复 durable execution semantics，不恢复 ambient process state（与 17 UN-11 一致）。
- Codex 的 resume/fork/rollback 都属于**历史重建**，不重新执行模型/工具（源码事实：`apply_rollout_reconstruction` 只重建 history）。
- 不得把 Codex resume/fork/rollback 与 Unified replay 等同（BP-07）。

---

## 9. Verification / Completion Mapping

### 9.1 源码事实

- Completion = `ResponseEvent::Completed { end_turn }` + 无 in-flight tool + 无 pending input + stop hooks 放行 → `TurnComplete`（`turn.rs:2547-2562,465-500`；`tasks/mod.rs:566,815-830`）。
- **没有外部验证器**参与 completion（04；本次复核无 grader/oracle/test gate）。
- 模型主动跑测试/检查是工具行为，失败作为工具输出回模型（04）。

### 9.2 三个问题的回答

**Q1. Codex completion 能否映射 Turn End？**

是（ADAPTER）：`TurnComplete` ↔ Unified `turn/end{completed}`；`TurnAborted`/`Error` ↔ `turn/end{aborted|error}`。reason 词汇不完全对齐：Codex `TurnAbortReason { Interrupted, Replaced, ReviewEnded, BudgetLimited }`（`protocol/protocol.rs:3957-3962`），没有 Unified 的 `max-tokens` / `blocked` 显式枚举；stop hooks 可 block 但会继续，不产生 blocked turn/end。

**Q2. Codex verification 缺失是否构成 Unified semantic gap？**

是：Unified 明确 `Completion != Verification`（04/13）。Codex 只有 completion，无 verification 事件；Adapter 不得把 completion 提升为 verification，也不得在 Unified 侧伪造验证结果。

**Q3. Unified Runtime 是否不应该把 completion 与 verification 合并？**

是（契约结论）：不能合并。Codex 侧 absence of verification 必须作为 backend lossiness 暴露（BP-06）。

---

## 10. Capability Mapping

### 10.1 候选对象逐一判定

| Codex 对象 | 是否可对应 Capability | 判定 |
| --- | --- | --- |
| Tool registry / ToolRouter | 否（每 step 重建的执行视图） | BACKEND-SPECIFIC |
| Sandbox | 否（执行策略/环境约束） | BACKEND-SPECIFIC |
| Skill | 部分（SKILL.md 是贡献的上下文/工具，不是 lifecycle 对象） | ADAPTER（仅内容映射） |
| MCP server | 部分（session 级连接是资源，但无 install/dispose 契约） | BACKEND-SPECIFIC |
| Command / unified_exec | 否（工具执行） | BACKEND-SPECIFIC |
| Worker / subagent | 否（AgentControl 子线程；无 effect registry） | BACKEND-SPECIFIC |

### 10.2 结论

不要把 Codex 的任何对象强制映射成 Unified Capability。Unified Capability/Scope/Effect 是 runtime-owned lifecycle truth（python-cordis 12/13）；Codex 没有等价物（MISSING），Adapter 只能把 Codex 工具可见性翻译为“backend 工具集快照”，ownership 仍由 Unified Runtime 自己管理。

---

## 11. Authorization Mapping

| Unified | Codex | Status |
| --- | --- | --- |
| authorized_principal | 无统一主体字段；`TurnContextItem` 有 approval/sandbox/permission 快照 | MISSING |
| approval | `ExecApprovalRequirement` + `Op::ExecApproval` + `ExecApprovalRequest/ApplyPatchApprovalRequest` 事件 | ADAPTER |
| guard | Guardian 自动审批审查（allow/deny + risk）；`GuardianAssessment` 事件持久化 | ADAPTER |
| permission | permission profile / sandbox policy（`TurnContextItem` 快照；granted_permissions_by_environment_id 在 SessionState） | ADAPTER（BACKEND-SPECIFIC 形态） |
| runtime authorization vs external policy | approval 是工具执行流水线 stage；Guardian 是外部策略；sandbox 是环境策略 | ADAPTER |

不要把 Ownership / Causality / Authorization 混合：Codex 侧三者分别对应 session 服务 / thread lineage（无 initiator）/ approval+guardian+sandbox。

---

## 12. 最重要的 5 个 Semantic Gap（仅基于已有 archaeology + 本次复核）

1. **Step 边界不存在于持久层**：无 Step 对象、无 step/start-end 事件、无 chunk→message lineage；compaction retry 还会跨 Step。Adapter 必须构造 Step，且该构造是有损的（LOSSY）。
2. **Tool failure 语义不一致**：exec 非零退出码 `success` 固定 true（`tools/context.rs:339-347`）；无统一工具错误 taxonomy；fatal 错误可终止 turn。Unified “tool failure ≠ step/turn failure” 在 Codex 只能部分成立（LOSSY）。
3. **Crash recovery 缺少 unknown outcome**：无 `TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN`；中断只写 marker + TurnAborted（MISSING）。副作用重试安全性无法由 Runtime 判定。
4. **Ownership / Capability / Initiator 缺失**：Codex 没有 Capability/Scope/Effect，没有 ambient initiator；owner 是 session 服务（BACKEND-SPECIFIC / MISSING）。Unified 必须保留 runtime-owned ownership，Adapter 不能从 rollout 推导。
5. **EventLog schema 不对齐**：`CompactedItem` 是“新事实 + replacement_history”而非 replacement 事件；`EventMsg::RawResponseItem` 与 `ResponseItem` 重复；rollback 是 marker + 重建；无 sourceEventSeqs。Adapter 需要去重、合成 lineage，并暴露 lossiness（ADAPTER/LOSSY）。

---

## 13. 证据纪律与冲突记录

### 13.1 本次复核的源码路径

- `codex-rs/core/src/session/{session.rs,step_context.rs,turn_context.rs,turn.rs,handlers.rs,rollout_reconstruction.rs,multi_agents.rs,mod.rs}`
- `codex-rs/core/src/tasks/{mod.rs,regular.rs}`
- `codex-rs/core/src/state/{session.rs,service.rs}`
- `codex-rs/core/src/context_manager/history.rs`、`codex-rs/core/src/compact.rs`、`codex-rs/core/src/session/context_window.rs`
- `codex-rs/core/src/tools/{router.rs,registry.rs,parallel.rs,context.rs,events.rs,orchestrator.rs,sandboxing.rs,spec_plan.rs}`
- `codex-rs/core/src/unified_exec/mod.rs`、`codex-rs/core/src/guardian/mod.rs`
- `codex-rs/history/src/lib.rs`、`codex-rs/rollout/src/recorder.rs`、`codex-rs/rollout-trace/src/model/*`
- `codex-rs/protocol/src/{protocol.rs,models.rs,approvals.rs,error.rs}`、`codex-rs/core/src/turn_metadata.rs`

### 13.2 CONFLICT FOUND

- 本仓库 `src/forge/codex_adapter/rollout_parser.py` 仍按 fork PoC 的 phase packet 前缀（`task-contract/explorer/worker-plan/.../result-review`）解析 rollout；pinned main 中这些结构 **NOT FOUND**（与 `01 §1.3` 一致）。该文件不能作为 pinned-main 的证据，也不能直接复用于 Phase 5-B。
- `docs/capability-forge-mvp-spec.md` 同样引用 fork PoC 符号（`PhasePacket`、`orchestrated_execution_facts`）。本次未修改（用户禁止修改 business source），仅记录冲突。

### 13.3 未修改范围

本文件未修改任何 Codex / AgentScope / Semantic Core / Phase 2 / Phase 3 / Phase 4 代码；只新增映射文档。

---

## 14. Final Verdict

**PARTIAL**

Unified Semantic Runtime 在语义层面**可以承载 Codex**：Session/Turn/Tool/Authorization/Compaction/Replay 都有可翻译的源码事实，且不需要修改核心 contract。但 Step、Tool Error、Crash Recovery、Capability/Initiator、EventLog schema 存在 LOSSY / MISSING / BACKEND-SPECIFIC 语义，Adapter 必须显式构造与暴露，不能宣称 EXACT 或 PASS。
