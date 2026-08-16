# 23 — Regression Audit（Phase 5-M）

> 阶段：Phase 5-M。本文件在 Regression 契约冻结前完成，只审计
> `ExecutionRecord`（5-J）、`EvaluationResult`（5-I）、`FailureAttribution`（5-K）、
> `ImprovementCandidate`（5-L）以及 Codex / DSH archaeology（10/11）已经能为
> RegressionRun 提供什么。
> 状态词：AVAILABLE / PARTIAL / MISSING。
> 判定原则：只依据 durable evidence 与已冻结契约；evidence 不足时不猜。

## 1. 审计对象

```text
ImprovementCandidate
    ↓
RegressionRun（本阶段契约）
    ↓
Baseline vs Candidate
    ↓
Evaluation Comparison
    ↓
RegressionDecision
```

## 2. 逐项审计

| # | 需要的事实 | 现状证据 | 判定 |
| --- | --- | --- | --- |
| 1 | baseline identity | `ImprovementCandidate.baseline_ref` 必填（5-L §2/§9）；Codex 10 §1.3 的 baseline 是 context/memory/git baseline，不是 capability/eval baseline；DSH 10 §3 无产品层 baseline | PARTIAL（ref 存在；无版本注册表/解析） |
| 2 | candidate identity | `ImprovementCandidate.candidate_id` + `propose()`（5-L）；`REQUIRES_DISAMBIGUATION` / `INVALID_FOR_REGRESSION` 状态可识别 | AVAILABLE |
| 3 | task set identity | `TaskSpecification.task_id` + `EvaluationResult.task_id` 已绑定（5-I）；无 TaskSet 对象 | PARTIAL（task 可识别；task set 无 id/version） |
| 4 | task version | `TaskSpecification` 无 version 字段；golden/historical/synthetic 无版本对象 | MISSING |
| 5 | baseline execution record | `ExecutionRecord` 不可变投影（5-J）+ `replay_ref` + RULE-10（5-I） | AVAILABLE |
| 6 | candidate execution record | 同上；新 execution 可用新 `execution_id` / `attempt_id`（5-J） | AVAILABLE |
| 7 | baseline evaluation result | `evaluate()` → `EvaluationResult`（5-I），绑定 task_id | AVAILABLE |
| 8 | candidate evaluation result | 同上 | AVAILABLE |
| 9 | per-task comparison | 无 comparison 层；task_id + status 数据可支撑 | MISSING（输入 AVAILABLE） |
| 10 | aggregate comparison | 无 aggregate 层；success/failure 可从 status 派生；timeout / unsafe retry / unresolved tool 可从 RULE-07 / RULE-03 / RULE-02 findings 派生；cost/usage 统一层 UNKNOWN（5-G §2） | MISSING（输入 PARTIAL） |
| 11 | replay reference | `replay_ref` + RULE-10 + 04 §12（same execution + replay ⇒ same semantic record） | AVAILABLE |
| 12 | re-execution reference | `execution_id` / `attempt_id` 可表达新 identity（5-J）；无 run-level re-execution 对象 | PARTIAL |
| 13 | critical regression | 无 critical 分类；`TaskSpecification.policy_constraints` 存在但未定义 critical 集合 | MISSING |
| 14 | lossiness | `BackendMetadata`（mapping_quality + missing_semantics + backend_event_ref）持久化且 replay-aware（04 §11；5-H） | AVAILABLE |
| 15 | comparison quality | 无 comparison 层；lossiness 输入 AVAILABLE | MISSING（输入 AVAILABLE） |
| 16 | regression decision | 无 decision 规则；Codex / DSH 均无 eval 驱动决策 | MISSING |

## 3. 结论

- **AVAILABLE**：candidate identity、baseline/candidate execution record、
  baseline/candidate evaluation result、replay reference、lossiness。
- **PARTIAL**：baseline identity（无版本注册表）、task set identity（无
  id/version）、re-execution reference（无 run-level 对象）、aggregate
  metric 的 cost/usage。
- **MISSING**：task version、per-task comparison、aggregate comparison、
  critical regression、comparison quality、regression decision。

Phase 5-M 只补 **contract / comparison layer**：`TaskSet` 身份、
`RegressionRun` 语义、per-task / aggregate comparison、critical regression
阻断、lossiness 可见的 decision。不实现 re-execution runner、Promotion、
Canary、Rollback，不修改 Runtime / Evaluator。
