# 13 — Execution Record Projection Gap Audit（Phase 5-J）

> 阶段：Phase 5-J。本文件在投影实现前审计 `ExecutionRecord` 5h.1（Phase
> 5-H）缺什么，并逐项给出 5j.1 投影后的 Source Event → Projection field。
> 状态词：AVAILABLE / PARTIAL / MISSING。
> 判定原则：只依据 Event Log 已有事实；source event 没有的字段不伪造。

## 1. 审计对象

```text
Event Log（source of truth）
    ↓ build_execution_record（5h.1 → 5j.1）
ExecutionRecord（immutable evaluation-facing projection）
    ↓ evaluate()
EvaluationResult
```

5h.1 已有：attempts / tools（payload）/ events（seq,type）/ backend_refs /
initiator_ref / owner_refs / context_provenance。
5j.1 新增：turns / steps / tool_results / unresolved_tools /
execution_outcome / turn_end_reason / turn_outcome / replay_ref / lossiness，
并把 tools 与 tool_results 补上 step/turn/execution/attempt 归属。

## 2. 逐项审计

| # | 事实 | 5h.1 现状 | 5j.1 投影 | Source Event → Projection field |
| --- | --- | --- | --- | --- |
| 1 | execution outcome | PARTIAL（attempt 证据有，无 execution 级字段） | AVAILABLE（DERIVED） | `execution/attempt/*.status` + `turn/end.reason` → `execution_outcome{status,derived,basis}` |
| 2 | turn outcome | MISSING | AVAILABLE（DERIVED） | `turn/end.reason` → `turn_end_reason` / `turn_outcome` / `turns[].end_reason|outcome` |
| 3 | step outcome | MISSING | AVAILABLE（DERIVED） | `step/start` + `step/end` + attempt status + `turn/end.reason` → `steps[].outcome` |
| 4 | attempt outcome | AVAILABLE | AVAILABLE（不变） | `execution/attempt/start|end.status` → `attempts[].status` |
| 5 | tool call | AVAILABLE（payload 仅原始字段） | AVAILABLE（补归属上下文） | `tool/call` payload + 所在 turn/step/execution/attempt 事件 → `tools[]`（ToolCallRecord） |
| 6 | tool result | MISSING | AVAILABLE（backend_ref PARTIAL） | `tool/result` payload + 配对 `tool/call` → `tool_results[]`（ToolResultRecord） |
| 7 | timeout | MISSING | AVAILABLE | `tool/result.error_code=TOOL_TIMEOUT` → `tool_results[].error_code`（RULE-07） |
| 8 | unresolved tool | MISSING | AVAILABLE（DERIVED 配对） | `tool/call` 无匹配 `tool/result`（按 call_id）→ `unresolved_tools[]`，status=TOOL_OUTCOME_UNKNOWN |
| 9 | unsafe retry | PARTIAL（attempt reason 有，无专门字段） | AVAILABLE（不新增字段，reason 即证据） | `execution/attempt/end.reason=UNSAFE_RETRY_BLOCKED` → `attempts[].reason`（RULE-03） |
| 10 | initiator_ref | AVAILABLE | AVAILABLE（不变） | attempt/tool 事件 `initiator_ref` → `initiator_ref` / `tools[].initiator_ref` |
| 11 | owner_ref | AVAILABLE（tool/call） | AVAILABLE（tool/result 也纳入聚合） | `tool/call|result.owner_ref` → `owner_refs` / `tools[].owner_ref` |
| 12 | context provenance | AVAILABLE（内容 PARTIAL） | AVAILABLE（不变） | `execution/attempt/start.context_provenance` → `context_provenance[]` |
| 13 | backend refs | AVAILABLE | AVAILABLE（不变） | 事件 payload `backend_event_ref` → `backend_refs` / `tools[].backend_event_ref` |
| 14 | lossiness | PARTIAL（metadata 内嵌各事件，未顶层聚合） | AVAILABLE | `turn/start` + attempt + tool 事件 `backend_metadata` → `lossiness[]` |
| 15 | replay_ref | PARTIAL（有 record 身份，无源 log 范围） | AVAILABLE | session + included event seq 范围 + record/projection 版本 → `replay_ref` |

## 3. 保留的 PARTIAL / MISSING（不伪造）

- `tool_results[].backend_ref`：当前 `tool/result` 事件本身不携带
  `backend_event_ref`（ToolRuntime 写入 result 时未附 backend ref）；
  投影不借用 call 的 ref 充当 result 的 ref。ToolResultRecord 表达该字段，
  但值为缺失（不写 key 或 None），审计标 PARTIAL。
- 完整 request-time context snapshot（system prompt / runtime context）：
  事件层没有 → `context_provenance.quality=PARTIAL` 保持，不改。
- usage/cost：统一事件层无 → 不投影，保持 UNKNOWN。

## 4. 结论

5h.1 有 5 项 MISSING（turn/step outcome、tool results、unresolved tools、
timeout 证据）与 3 项 PARTIAL（execution outcome、lossiness 聚合、
replay_ref）；5j.1 投影后全部变为 AVAILABLE 或显式 PARTIAL。所有 outcome
字段均标 `derived: true`，不冒充 PERSISTED FACT；缺失 result 只产生
UNRESOLVED 状态，不创建假 ToolResultRecord。
