# 15 — Execution Record Projection Report（Phase 5-J）

> 阶段：Phase 5-J。产物：
> `13-execution-record-gap-audit.md`、
> `14-execution-record-projection-assumptions.md`、
> `runtime/recovery.py`（ExecutionRecord 投影扩展，5h.1 → 5j.1）、
> `evaluation/tests/test_execution_record_projection.py`（15 tests）。
> 未修改 EventStore / Session / Turn / Step / ExecutionAttempt / Evaluator
> rules；未调用网络模型；未做 LLM Judge / RCA / Regression / Promotion /
> UI。

## 1. ExecutionRecord 是否足够支撑基本 deterministic Evaluation？

**是。** 5j.1 record 提供 RULE-01..13 所需的最小事实集：

- turn outcome：`turn_end_reason`（真实 `turn/end.reason`）+ `turns[]`；
- step outcome：`steps[].outcome`（DERIVED）；
- tool call：`tools[]`（call_id / name / arguments / attempt/step/turn/
  execution 归属 / backend ref / owner / initiator）；
- tool result：`tool_results[]`（call_id / content / is_error / error_code /
  source_event_seqs / 归属）；
- unresolved tool：`unresolved_tools[]`（TOOL_OUTCOME_UNKNOWN）；
- attempt：`attempts[]`（status / reason / error / refs）；
- replay：`replay_ref` + record/projection 版本 + identity；
- 附加证据：initiator / owner / context provenance / backend refs /
  lossiness。

Evaluator 与 rules 一行未改；原先依赖缺失数据而降级的规则现在读到真实
证据。

## 2. Tool result 是否完整？

**基本完整；一个字段 PARTIAL。** content / is_error / error_code / call 配对 /
source_event_seqs / attempt/step/turn/execution 归属均来自 `tool/result`
事件。`backend_ref` 为 PARTIAL：当前 result 事件本身不携带
`backend_event_ref`（ToolRuntime 写 result 时未附），投影不借用 call 的 ref
冒充 result 的 ref。缺失 result 的 call 不产生假 result，只进入
`unresolved_tools[]`（RULE-02 可判 FAIL）。

## 3. Step outcome 是否可靠？

**可靠，但标 DERIVED。** 无独立 step 失败事件，投影组合最终 attempt 状态 +
`step/end` 存在性 + `turn/end.reason`，只区分 COMPLETED / FAILED / ABORTED /
UNKNOWN；证据不足时返回 UNKNOWN，不猜。`steps[].derived=true` 明确它不是
persisted fact。

## 4. Turn outcome 是否可靠？

**可靠。** 只从 `turn/end.reason` 取原始六值（completed / max-tokens /
error / aborted / blocked / interrupted），`turn_outcome` 是显式映射的派生
状态；绝不从“最后一个 Step 成功”推断 turn 成功。

## 5. Execution outcome 是否明确区分 derived/persisted？

**是。** 当前 runtime 没有 execution 级 start/end 事件，因此
`execution_outcome` 恒为 `{"status": ..., "derived": true, "basis":
[attempt 证据, turn reason]}`，不伪装 PERSISTED FACT。`SUCCESS` 只表示该
execution 的最终 attempt 完成，不等于任务成功（05 §2）。

## 6. Replay ref 是否成立？

**成立。** `replay_ref` 指向 `event_log` + session_id + execution_id +
event_range（该 execution 引用事件的 seq 闭区间）+ record_version +
projection_rule_version；不复制 Event Log。RULE-10 读取它并要求 record 身份
字段齐全后返回 PASS。

## 7. Replay 后 projection 是否稳定？

**稳定。** `test_replay_projection_stable`：run → record A，close →
reopen → replay → record B；execution_id / attempt_id / tool call identity /
tool results / steps / turns / execution outcome / replay_ref 全部相等；
仅对象身份不同。record 由 EventStore 纯重建，不重执行工具/模型。

## 8. AgentScope / Codex 是否都能提供最小 Evaluation Record？

**能。** 两 backend 走同一 `build_execution_record`：AgentScope fixture 与
Codex golden fixture 均产生 tools / tool_results / steps / turns /
execution_outcome / replay_ref / lossiness。Codex 的 backend ref 与
missing_semantics 保留在 call payload 与 `lossiness[]`；result 内容是统一
ToolRuntime 的实际执行结果，不是伪造的 backend 字段。

## 9. 哪些规则仍然 INCONCLUSIVE？

在完整真实 record + 本阶段 TaskSpecification 上，RULE-01..13 全部 PASS，
不再 INCONCLUSIVE。仍可能 INCONCLUSIVE 的合法场景（规则未改，证据条件触发）：

- RULE-02/06/07：record 无 `tool_results`（旧 5h.1 record 或缺失 log）；
- RULE-06/07：result `mapping_quality=LOSSY`（规则按契约降级）；
- RULE-10：record 无 `replay_ref`（旧 record）；
- RULE-09：`terminal_condition` 谓词抛错或证据不足；
- RULE-11/12/13：initiator / owner / context provenance 缺失。

## 10. 最大剩余 Evaluation Data Gap 是什么？

**ToolResultRecord 的 backend_ref**：`tool/result` 事件未持久化
`backend_event_ref`，Evaluation 无法从 result 直接回源 backend raw event
（只能经配对 call 的 ref 回源）。次大缺口仍是完整 request-time context
snapshot（context provenance quality=PARTIAL）与统一层 usage/cost。这些属于
5-G/5-H 已冻结的 extension 边界，本阶段不补。

## 变更记录

1. `runtime/recovery.py`：`ExecutionRecord` 新增 turns / steps /
   tool_results / unresolved_tools / execution_outcome / turn_end_reason /
   turn_outcome / replay_ref / lossiness；`build_execution_record` 扩展为
   完整投影；`record_version` 5h.1 → 5j.1，`projection_rule_version`
   v1 → v2（04 §2：投影规则变更 = 新版本 record）。
2. `runtime/tests/test_phase5h_durable_evidence.py`：record_version 断言
   更新为 5j.1（语义断言不变）。
3. `evaluation/tests/test_evaluator.py`：AgentScope/Codex fixture 的总体
   状态断言从 INCONCLUSIVE 更新为 PASS——不是放宽规则，而是 5-J 投影后
   真实证据已经可用（Phase 5-I 报告 §4 中这些 INCONCLUSIVE 正是本阶段
   要消除的）。
4. 新增 `evaluation/tests/test_execution_record_projection.py`（15 tests）。

## 最终判定

**PASS**

- ToolResult projection 完整（backend_ref 显式 PARTIAL，不伪造）；
- Step outcome 可评估（DERIVED，证据不足 UNKNOWN）；
- Turn outcome 可评估（真实 turn/end reason）；
- Execution outcome 可表达且明确 DERIVED；
- replay_ref 成立；replay 后 record 稳定；
- RULE-01/02/06/07/10 在真实 AgentScope/Codex record 上从 INCONCLUSIVE
  转为 PASS；
- AgentScope / Codex 最小 Evaluation Record 均可用；
- Evaluation Engine（rules/evaluator）未修改；
- Runtime semantic contract（EventStore / Session / Turn / Step /
  ExecutionAttempt）未修改。

按阶段指令，完成后停止：不进入 Phase 5-K。
