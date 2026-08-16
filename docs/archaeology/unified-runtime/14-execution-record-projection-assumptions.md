# 14 — Execution Record Projection Assumptions（Phase 5-J）

> 依据：13-execution-record-gap-audit.md + Phase 5-G/5-H 契约
> （04/07/08/09）+ Phase 5-I（10/11/12）+ 本次 `recovery.py` 投影实现。
> 状态词：VERIFIED（有实现/测试证据）/ PARTIAL（source fact 不足）。
> 本文件只冻结投影语义，不修改 Runtime / EventStore / Evaluation semantics。

| # | Assumption | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| A1 | tool result source | VERIFIED | `tool/result` payload（tool_call_id / content / is_error / error_code / source_event_seqs）是唯一结果事实；`test_tool_result_projected`。result 事件本身无 `backend_event_ref` → ToolResultRecord.backend_ref PARTIAL，不借用 call 的 ref。 |
| A2 | tool result pairing | VERIFIED | 按 `tool/result.tool_call_id == tool/call.call_id` 配对；`source_event_seqs` 保留 call seq 供回源；无配对 result 的 call 投影为 `unresolved_tools[]`（status=TOOL_OUTCOME_UNKNOWN），不伪造 result；`test_tool_call_result_pairing` / `test_missing_tool_result`。 |
| A3 | step outcome derivation | VERIFIED（规则）/ PARTIAL（无独立 step 失败事件） | 无独立 step failure 事件（5-E §4；17 §9）。投影只组合已有事实：最终 attempt 状态 + step/end 存在性 + turn/end reason；结果标 `derived: true`；`test_step_outcome`。 |
| A4 | turn outcome derivation | VERIFIED | 只取 `turn/end.reason` 六值并映射为 TurnRecord.outcome；绝不从最后一个 Step 成功推断 turn 成功；`test_turn_outcome`；RULE-01 读 `turn_end_reason` 原始值。 |
| A5 | execution outcome derivation | VERIFIED | 无 execution 级 start/end 事件 → `execution_outcome` 恒为 DERIVED：取最终 attempt 状态映射 SUCCESS/FAILED/ABORTED/UNKNOWN，basis 列出 attempt 证据与 turn reason；`SUCCESS` 只表示该 execution 的最终 attempt 完成，≠ 任务成功；`test_execution_outcome`。 |
| A6 | replay ref semantics | VERIFIED | `replay_ref` = source=event_log + session_id + execution_id + event_range（该 execution 引用事件的 seq 闭区间）+ record_version + projection_rule_version；不复制 Event Log；`test_replay_ref`。 |
| A7 | timestamp handling | VERIFIED | timestamp 是持久化的不透明字符串；语义比较不依赖格式/对象身份；replay 后 semantic fields 相等，只允许 backend raw representation / object identity 不同；`test_replay_projection_stable`。 |
| A8 | cross-backend completeness | VERIFIED | AgentScope 与 Codex 经同一 `build_execution_record` 得到同一形状（tools/tool_results/steps/turns/execution_outcome/replay_ref）；backend-specific / LOSSY metadata 保留在 tool payload 与 `lossiness[]`，不因字段一致而伪造 backend facts；`test_agent_scope_execution_record` / `test_codex_execution_record`。 |

## 显式保留的已知缺口

1. `tool_results[].backend_ref`：result 事件无 backend ref → PARTIAL。
2. 完整 request-time context snapshot：仍 PARTIAL（A7 之外，内容来自 5-H）。
3. usage/cost：统一事件层无 → 不投影。

## 禁止事项

- 不为缺失 result 创建 ToolResultRecord；
- 不把 DERIVED outcome 标记为 PERSISTED FACT；
- 不用 Step 成功推断 Turn 成功；
- 不把 execution SUCCESS 解释为任务成功；
- 不复制 Event Log 到 ExecutionRecord；
- 不修改 EventStore / Session / Turn / Step / ExecutionAttempt / Evaluator
  semantics。
