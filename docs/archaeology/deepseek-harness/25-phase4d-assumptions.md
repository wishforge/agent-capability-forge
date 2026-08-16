# 25 — Phase 4-D Implementation Assumptions

> 阶段：Phase 4-D（Real Agent Loop + AgentScope 2.0 Python）
> 基线：24-phase4c-report.md（PASS）+ AgentScope 2.0.2（base conda env）
> 引用：13 Event Sourcing / 14 Turn-Step / 15 Tool Waterfall / 16 Causal Chain /
> 17 Semantic Runtime Model / 18–23 Phase 4-A/B/C Assumptions
> 状态词：DSH VERIFIED / DSH PARTIAL / DSH UNKNOWN / PHASE-4D DESIGN

以下每一项都是 Phase 4-D implementation contract，不是 DSH facts。
PASS 只代表 Phase 4-D 最小 scope 完成；真实网络模型、生产部署、
AgentScope 内部事件总线、多进程并发等仍保持 UNKNOWN / NOT IMPLEMENTED。

## AgentScope Event Mapping

| AgentScope event | DSH event | 映射方式 | 状态 |
| --- | --- | --- | --- |
| `ReplyStartEvent` | 无（turn/start 已由 runtime 记录） | 忽略 | ADAPTER |
| `ModelCallStartEvent` | `step/start` + `request/header`（runtime 先记录） | ADAPTER | PHASE-4D DESIGN |
| `TextBlockDeltaEvent` | `assistant/chunk`（每个 delta 一条） | EXACT | PHASE-4D DESIGN |
| `ModelCallEndEvent` | `assistant/message`（adapter 组装 content + tool_calls） | ADAPTER | PHASE-4D DESIGN |
| `ToolCallStart/Delta/EndEvent` | `tool/call`（adapter 缓冲，ToolResultStart 前交给 ToolRuntime） | ADAPTER | PHASE-4D DESIGN |
| `ToolResultStart/TextDelta/EndEvent` | `tool/result`（wrapper 内 `ToolRuntime.execute` 记录；End state 校验） | ADAPTER | PHASE-4D DESIGN |
| `ExceedMaxItersEvent` / `ReplyEndEvent` | Step 流终止信号 | ADAPTER | PHASE-4D DESIGN |
| `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` | 无 | NOT_SUPPORTED（Phase 4-D 全部 ALLOW） | PHASE-4D DESIGN |
| `ThinkingBlock*` / `DataBlock*` | 无 | LOSSY（trace-only，不落 DSH event） | PHASE-4D DESIGN |
| 模型异常（无 `ModelErrorEvent`） | `ModelRequestError(code)` | ADAPTER | PHASE-4D DESIGN |

## 必需 Assumptions（A1–A12）

| # | Assumption | 状态 | 说明 |
| --- | --- | --- | --- |
| A1 | AgentScope 版本与 public API 边界：本阶段只使用 AgentScope 2.0.2 公开类/方法（`Agent` / `AgentState` / `Toolkit` / `FunctionTool` / `ChatModelBase` / `reply_stream` / event 类）。未修改第三方源码。 | PHASE-4D DESIGN | 与 11-agentscope-bridge.md 一致。 |
| A2 | Agent 每 Step 重建：`AgentScopeModelAdapter` 每 Step 从 DSH surface 构造新 `AgentState.context`（公开字段）并新建 `Agent`；AgentScope 内部状态是 DSH 事件日志的一次性投影，不是第二 source of truth。 | PHASE-4D DESIGN | DSH Session 权威（13 ES-01）。 |
| A3 | one reply = one Step：`ReActConfig(max_iters=1)` 使一次 `reply_stream(None)` 恰好包含一次 model request + 该请求的 tool activity；`ExceedMaxItersEvent` + `ReplyEndEvent` 只作流终止，不映射为 DSH 事件；AgentScope 合成的 “Executed maximum iterations…” Msg 被 `reply_stream` 过滤，不进入日志。 | PHASE-4D DESIGN | 14 TURN-02（Step = one model request）。 |
| A4 | model error mapping：AgentScope 2.0.2 没有 model error 事件；错误以异常从 `reply_stream` 抛出。adapter 按异常文本标记识别 `CONTEXT_WINDOW_EXCEEDED`（`CONTEXT_WINDOW_EXCEEDED` / `context_length_exceeded` / `maximum context length` / `context window` / `token limit`），其余为 `MODEL_ERROR`。 | DSH PARTIAL（DSH 有 `llm/retry` 事件；异常映射无 DSH 证据）；PHASE-4D DESIGN | 真实 provider 错误文本未验证。 |
| A5 | overflow retry：`AgentRuntime` 捕获 `ModelRequestError(CONTEXT_WINDOW_EXCEEDED)` → `CompactionEngine.handle_request_error()` → RETRY 时重建 mctx 并重试同一 Step（不新建 STEP_START/AGENT_REQUEST）。如果第一次请求已流式产生 `assistant/chunk`，这些 chunk 是 append-only trace 事件，保留在日志中；重试的 final message 只引用重试流的 chunk seq。 | PHASE-4C A7 升级为真实 loop 接线；PHASE-4D DESIGN | 部分流失败无回滚（append-only）。 |
| A6 | tool side-effect boundary：Step 在 tool 完成后先写 `step/end` 再开始下一步的 model request，因此 overflow retry 只可能发生在“无本步 tool 事件”的 Step；`retry_safe()` 额外阻止同一 Step 内 request 之后出现 `assistant/message` / `tool/call` / `tool/result` 时的重试。副作用 Step 永不重放。 | DSH VERIFIED（15 §11 修复顺序）；PHASE-4D DESIGN（loop 结构） | `test_tool_side_effect_retry_boundary` 覆盖。 |
| A7 | real model determinism：只验证了 AgentScope-compatible 的确定性 `ChatModelBase` 子类；未调用 OpenAI/Anthropic/DeepSeek 等真实网络模型，真实 provider 的 error code、token 计费、流式 chunk 边界未验证。 | DSH UNKNOWN；PHASE-4D DESIGN | 统一 `ModelAdapter` 接口允许替换真实模型，但本阶段不声明其行为。 |
| A8 | AgentScope public API gaps：无 core 事件总线（只有 `reply_stream`）；`Toolkit` 无 per-tool unregister；无公开 deterministic mock model；无 model error 事件；`FunctionTool` wrapper 的 `**kwargs` 只生成空 schema（`{}`，jsonschema 接受任意对象）。 | DSH NOT FOUND（AgentScope 非 DSH）；PHASE-4D DESIGN | Phase 2 bridge 已记录前两项；本阶段新增后两项。 |
| A9 | unknown tool：模型调用未注册工具时，AgentScope 自行产出 `ToolResultEndEvent(error)`；adapter 合成 DSH `tool/call` + `tool/result(is_error, error_code=UNKNOWN_TOOL)`，不进入 ToolRuntime。 | PHASE-4D DESIGN | 保持 tool failure ≠ step/turn failure。 |
| A10 | `concludes_turn` / `additional_contexts` 经 adapter 的 `step_tool_results`（runtime-only）从 ToolRuntime 回传 AgentRuntime；不写入 `tool/result` 事件 payload。 | 18 A17 延续；PHASE-4D DESIGN | |
| A11 | 事件日志始终先 append，再 projection：AgentRuntime 在模型请求前写 `request/header`（内存 `agent/request`，落盘映射 `request/header`），所有 chunk/message/tool 事件先入 EventStore，模型上下文只从 surface 派生。 | DSH VERIFIED（13 ES-01/02）；PHASE-4D DESIGN | |
| A12 | streaming 语义：AgentScope 只把非 last chunk 转成 `TextBlockDeltaEvent`，last chunk 只作为 completed response 保存；测试模型约定 last chunk 为空 content。adapter 累积 delta 组装 `assistant/message`。 | PHASE-4D DESIGN | `test_stream_reconstruction` 覆盖。 |

## 结论

Phase 4-D PASS 只覆盖最小 scope：真实 AgentScope Agent + 确定性
AgentScope-compatible model + Tool Waterfall + persistence + replay +
compaction→retry 闭环。A1–A12 覆盖的边界（真实网络模型、provider 精确
error/token、AgentScope 内部事件总线、外部确认/外部执行工具、多进程并发、
部分流失败回滚）全部保留为 PHASE-4D IMPLEMENTATION ASSUMPTION，
不进入下一阶段作为已证明事实。
