# 10 — Evaluation Engine Audit（Phase 5-I）

> 阶段：Phase 5-I。本文件在实现 Evaluator 前完成，只审计当前
> `ExecutionRecord`（`record_version=5h.1`，`build_execution_record` 纯投影，
> 5-H）是否已经提供 Evaluation 需要的证据。
> 状态词：AVAILABLE / PARTIAL / MISSING。结论只描述 ExecutionRecord 本身，
> 不描述 Event Log / ReplayHistory / runtime 内部对象（Evaluator 禁止读取）。

审计对象（一次性实跑确认，非文档推断）：

```text
ExecutionRecord
  record_version / projection_rule_version
  execution_id / session_id
  initiator_ref / owner_refs
  attempts[]  (ReplayAttempt: status/reason/backend refs/metadata/provenance)
  tools[]     (仅 tool/call payload)
  events[]    (seq, event_type)
  backend_refs[]
  context_provenance[]
```

## 1. 逐项审计

| # | Evaluation 需要 | ExecutionRecord 现状 | 判定 |
| --- | --- | --- | --- |
| 1 | execution outcome | attempts[] 有 status（SUCCEEDED/FAILED/ABORTED），但没有 execution 级 outcome 字段；04 §5 的 SUCCESS/PARTIAL/FAILED/ABORTED/UNKNOWN 未投影 | PARTIAL（attempt 证据有；execution 结论需派生且依赖 turn/step） |
| 2 | turn outcome | record 无 turn_id / turn/end reason；ReplayHistory 有，但 record 未携带 | MISSING |
| 3 | step outcome | record 无 step_id / step 状态；events[] 只有 (seq, event_type) | MISSING |
| 4 | attempt outcomes | ReplayAttempt.status / reason / error / started_at / ended_at 完整 | AVAILABLE |
| 5 | tool calls | tools[] = tool/call payload（call_id / name / arguments / root/parent / refs） | AVAILABLE |
| 6 | tool results | record 无 tool_results；tool/result 只在 events[] 类型表中可见，payload 未投影 | MISSING |
| 7 | unresolved tools | 无 results 可配对；`find_unresolved_tools` 是 runtime/recovery 函数，Evaluator 不可用 | MISSING |
| 8 | unsafe retry | ReplayAttempt.reason 可携带 `UNSAFE_RETRY_BLOCKED`（runtime 5-F 路径写入），但无专门字段 | PARTIAL |
| 9 | timeout | tool/result 才有 TOOL_TIMEOUT；attempt 无 timeout 字段 | MISSING |
| 10 | initiator_ref | ReplayAttempt.initiator_ref / record.initiator_ref（ADAPTER_DERIVED） | AVAILABLE |
| 11 | owner_ref | record.owner_refs（来自 tool/call owner_ref） | AVAILABLE |
| 12 | context provenance | record.context_provenance[]（quality=PARTIAL + missing_semantics 显式） | AVAILABLE（内容 PARTIAL） |
| 13 | replay_ref | 有 record_version / projection_rule_version / session_id / execution_id，但无显式 replay_ref（源 log 范围） | PARTIAL |
| 14 | backend mapping / lossiness | backend_refs[] 有 quality；tool/attempt payload 内嵌 backend_metadata（missing_semantics），但 record 顶层未聚合 lossiness | PARTIAL |

## 2. 结论

- 可直接支持：attempt outcomes、tool calls、initiator、owner、context
  provenance（PARTIAL 内容）、backend refs。
- 只能部分支持：execution outcome、unsafe retry、replay 身份、lossiness
  聚合（需要从 attempts/tools 的 payload 内嵌 metadata 提取）。
- 完全缺失：turn outcome、step outcome、tool results、unresolved tools、
  timeout。

Evaluator 不得为实现 Evaluation 自己补数据：对 MISSING 项一律
INCONCLUSIVE；对 PARTIAL 项按已有证据降级。Runtime semantics 保持 5-H
冻结不变。
