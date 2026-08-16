# 11 — Evaluation Engine Assumptions（Phase 5-I）

> 依据：`10-evaluation-engine-audit.md`（实现前审计）+ Phase 5-E Contract v1
> + Phase 5-G 04/05/06 + Phase 5-H 07/08/09 + 本次实现的
> `deepseek-harness/evaluation/`（models / rules / evaluator / golden）。
> 状态词：VERIFIED / PARTIAL / DESIGN PROPOSAL。实现后状态只表示本阶段
> Evaluation Engine 的语义，不修改 Runtime 契约。

| # | Assumption | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| A1 | deterministic rule semantics：同一 ExecutionRecord + 同一 TaskSpecification ⇒ 同一 findings 序列；规则只做布尔/集合/缺失判断，无模型、无随机 | VERIFIED | `rules.py` 纯函数；golden + replay 测试断言 findings 相等 |
| A2 | task specification semantics：TaskSpecification 只表达 task_id / goal / required / forbidden / terminal_condition / policy_constraints；required/forbidden 按工具名精确匹配，policy_constraints 本阶段只携带不判定 | VERIFIED（字段）/ PARTIAL（policy 语义） | `models.py`；无 DSL |
| A3 | terminal condition semantics：terminal_condition 是任务定义提供的可调用谓词（record → bool），不是 Runtime 事实；谓词抛错或证据不足 ⇒ INCONCLUSIVE | DESIGN PROPOSAL | `rule_09`；golden TASK-04 |
| A4 | unresolved tool definition：tool call 无匹配 tool result 即 unresolved；记录缺 tool_results 时无法判定 ⇒ INCONCLUSIVE | VERIFIED（判定）/ MISSING（当前 record 数据） | `rule_02`；审计 §1 #6/#7 |
| A5 | replayability rule：record 必须携带 replay_ref + record_version + projection_rule_version + identity 才可判定 replayable；缺 replay_ref ⇒ INCONCLUSIVE | VERIFIED（规则）；当前 5h.1 record 无 replay_ref ⇒ INCONCLUSIVE | `rule_10`；审计 §1 #13 |
| A6 | lossiness handling：任何 LOSSY 证据不得当 EXACT；规则依赖有损字段时降为 INCONCLUSIVE 并在 message 显式标注 | VERIFIED | `rule_06` / `rule_07`；`test_lossy_mapping_visible` |
| A7 | inconclusive semantics：证据缺失 = INCONCLUSIVE（warning），不是 PASS 也不是 FAIL；汇总时任一 FAIL ⇒ FAIL，否则任一 INCONCLUSIVE ⇒ INCONCLUSIVE，否则 PASS | VERIFIED | `evaluator.py` 汇总；测试覆盖 3 种状态 |
| A8 | cross-backend equivalence：同一 TaskSpecification 对 AgentScope / Codex 的 ExecutionRecord 产生相同 rule_id + status 序列；evidence refs 可定位且 backend 不同 | VERIFIED | `test_same_task_cross_backend`；两 backend 均 INCONCLUSIVE 且序列一致 |

## 显式补充（§11/§12 要求的证据规则）

在 RULE-01..10 之外实现三条纯证据规则，不做任何质量判断：

- RULE-11 Attribution evidence：initiator_ref 缺失 ⇒ INCONCLUSIVE；
- RULE-12 Ownership evidence：owner_refs 缺失 ⇒ INCONCLUSIVE；
- RULE-13 Context evidence：context_provenance 缺失 ⇒ INCONCLUSIVE。

这三条不判断“Context 好不好 / 归因对不对”，只判断证据是否 available，
符合 Phase 5-I §11/§12 与测试清单（missing initiator / missing owner）。

## 显式保留

- `score`：本阶段恒为 None，不设计无可靠数值语义的分数。
- `policy_constraints`：字段存在但不消费（无对应 deterministic rule）。
- ExecutionRecord 数据缺口（tool results / turn / step / replay_ref）：
  本阶段不修改 Runtime 来补数据；相应规则在真实 5h.1 record 上为
  INCONCLUSIVE。
