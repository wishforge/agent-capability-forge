# 16 — Failure Attribution Audit（Phase 5-K）

> 阶段：Phase 5-K。本文件在实现 Attribution Layer 前完成，只审计当前
> `ExecutionRecord`（`record_version=5j.1`，Phase 5-J）与 Evaluation
> `EvaluationResult`（Phase 5-I）已经能为 `FailureAttribution` 提供什么。
> 状态词：AVAILABLE / PARTIAL / MISSING。
> 判定原则：只依据 ExecutionRecord / EvaluationResult 中的 durable
> evidence；不读取 ContextVar / runtime mutable state；evidence 不足时不猜。

审计对象：

```text
ExecutionRecord（5j.1，immutable 投影）
    ↓
EvaluationResult（RULE-01..13 findings，deterministic）
    ↓
FailureAttribution（本阶段新增）
```

## 1. 逐项审计

| # | 需要归因的事实 | ExecutionRecord / Evaluation 证据 | 判定 |
| --- | --- | --- | --- |
| 1 | execution failure | `execution_outcome{status,derived,basis}` 已投影（DERIVED：attempt 状态 + turn/end reason）；`RULE-08` 可 FAIL | AVAILABLE（DERIVED） |
| 2 | turn failure | `turn_end_reason` 原始六值 + `turns[].outcome` 已投影；`RULE-01` 可 FAIL | AVAILABLE |
| 3 | step failure | `steps[].outcome` 已投影（DERIVED：attempt + step/end + turn/end）；`RULE-08` 可 FAIL | AVAILABLE（DERIVED） |
| 4 | attempt failure | `attempts[]`（status / reason / error / attempt_id / step_id）完整；`RULE-03` / `RULE-08` 可 FAIL | AVAILABLE |
| 5 | tool failure | `tools[]` + `tool_results[]`（is_error / error_code / 配对 / 归属）；`RULE-06` 可 FAIL；Codex exec success 固定 true 属 LOSSY | AVAILABLE（LOSSY 显式） |
| 6 | timeout | `tool_results[].error_code=TOOL_TIMEOUT`；`RULE-07` 可 FAIL；attempt 层无 timeout 字段 | AVAILABLE（tool 层）/ PARTIAL（attempt 层） |
| 7 | unsafe retry | `attempts[].reason=UNSAFE_RETRY_BLOCKED`；`RULE-03` 可 FAIL | AVAILABLE |
| 8 | unresolved tool | `unresolved_tools[]`（TOOL_OUTCOME_UNKNOWN）；`RULE-02` 可 FAIL；`TOOL_NOT_STARTED` 无法区分 | AVAILABLE（outcome-unknown）/ PARTIAL（not-started 细分） |
| 9 | backend error | attempt 可带 `error`（如 MODEL_ERROR / CONTEXT_WINDOW_EXCEEDED）+ `backend_event_ref`；`tool/result` 事件本身无 backend ref | PARTIAL |
| 10 | context-related failure | `context_provenance[]` 已投影（quality=PARTIAL，不判断好坏）；attempt.error 可携带 `CONTEXT_WINDOW_EXCEEDED` | PARTIAL（仅“failure 发生在某 provenance 下”，不做质量判断） |
| 11 | completion failure | `turn_end_reason=max-tokens`、`RULE-04`（required 未调用）、`RULE-09`（terminal condition 不满足）可 FAIL | AVAILABLE（DERIVED） |
| 12 | verification failure | Event Log / ExecutionRecord 无 execution-time verification gate 事件；Evaluator 无对应 RULE | MISSING |
| 13 | model failure | attempt.error=MODEL_ERROR / CONTEXT_WINDOW_EXCEEDED（runtime 统一错误码）；无模型层细分事件 | AVAILABLE（错误码层）/ PARTIAL（细分） |
| 14 | initiator | `initiator_ref` 已持久化（ADAPTER_DERIVED），attempt/tool 事件可读 | AVAILABLE |
| 15 | owner | `owner_ref` 已持久化（tool_registration），tool/call + tool/result 可读；owner 语义稳定性 PARTIAL | AVAILABLE（ref）/ PARTIAL（语义） |
| 16 | context provenance ref | `context_provenance[]` 已投影（request_ref / source_event_refs / surface_refs / current_input_ref；system/runtime snapshot 缺失） | AVAILABLE（内容 PARTIAL） |
| 17 | backend event refs | `backend_refs[]` + tool/call backend ref AVAILABLE；tool/result 自身无 backend ref | PARTIAL |
| 18 | lossiness | `lossiness[]` 已投影；LOSSY / BACKEND_SPECIFIC 显式 | AVAILABLE |

## 2. Failure Kind 可用性

| Failure Kind | 证据 | 判定 |
| --- | --- | --- |
| TOOL_FAILURE | tool/result.is_error / error_code + RULE-06 | AVAILABLE |
| MODEL_FAILURE | attempt.error=MODEL_ERROR（exact code） | AVAILABLE |
| TIMEOUT | tool/result.error_code=TOOL_TIMEOUT + RULE-07 | AVAILABLE |
| UNRESOLVED_TOOL | unresolved_tools[] + RULE-02 | AVAILABLE |
| UNSAFE_RETRY | attempt.reason=UNSAFE_RETRY_BLOCKED + RULE-03 | AVAILABLE |
| TURN_FAILURE | turn_end_reason ≠ completed + RULE-01 | AVAILABLE |
| STEP_FAILURE | steps[].outcome FAILED/ABORTED + RULE-08 | AVAILABLE（DERIVED） |
| EXECUTION_ABORTED | attempt.status=ABORTED + RULE-08 | AVAILABLE |
| CONTEXT_FAILURE | attempt.error=CONTEXT_WINDOW_EXCEEDED | PARTIAL（只有错误码，无上下文质量判断） |
| COMPLETION_FAILURE | turn_end_reason=max-tokens / RULE-04 / RULE-09 | AVAILABLE（DERIVED） |
| VERIFICATION_FAILURE | 无 verification 事件 / 无 RULE | MISSING |
| UNKNOWN | 以上证据均不足时的保留值 | AVAILABLE（兜底，不猜） |

## 3. 结论

5j.1 record + 5-I Evaluator 已能确定性支撑：

- execution / turn / step / attempt / tool / timeout / unsafe retry /
  unresolved tool / completion 失败归因；
- initiator / owner / context provenance / backend refs / lossiness 引用；
- LOSSY 显式保留，不冒充 EXACT。

无法确定性支撑（本阶段不补数据，不猜）：

- VERIFICATION_FAILURE（无证据）；
- attempt 层 timeout 细分；
- TOOL_NOT_STARTED 与 TOOL_OUTCOME_UNKNOWN 的区分；
- tool/result 自身 backend ref（Phase 5-J 已显式 PARTIAL）；
- 完整 request-time context snapshot（system / runtime_context）；
- 模型层细分（HTTP / stream / retry 等）。
