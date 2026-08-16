# 29 — Control Plane Proof Audit（Phase 5-O）

> 阶段：Phase 5-O。本文件在新增任何 composition / integration 之前完成，
> 只审计既有契约是否足以支撑端到端闭环，不修改 Core。
> 状态词：VERIFIED / PARTIAL / MISSING。
>
> 审计对象：
>
> ```text
> Runtime / ExecutionRecord
> -> Evaluator (EvaluationResult)
> -> Failure Attribution (FailureAttribution)
> -> Improvement Candidate (ImprovementCandidate)
> -> Regression (RegressionRun)
> -> Promotion / Rollback (PromotionDecision / RollbackDecision)
> ```

## 1. Runtime / ExecutionRecord

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | EventStore 事件日志 + `build_execution_record(store, execution_id)`（`runtime/recovery.py`） | VERIFIED |
| 输出类型 | `ExecutionRecord`：record/projection version、execution_id、session_id、attempts、steps、turns、tools、tool_results、unresolved_tools、execution_outcome、replay_ref、lossiness | VERIFIED |
| identity | `execution_id` + `session_id` + `replay_ref.event_range` | VERIFIED |
| evidence refs | `backend_refs`、tool/attempt 的 `backend_event_ref`、`initiator_ref`、`owner_refs` | VERIFIED |
| replay refs | `replay_ref`（session_id / execution_id / event_range / 版本） | VERIFIED |
| version refs | `record_version` / `projection_rule_version` 存在；Agent 版本是外部 fixture 身份，不在 record 内 | PARTIAL |
| lossiness | `lossiness` 元组 + `mapping_quality`（ADAPTER / EXACT / LOSSY）显式保留 | VERIFIED |
| cross-backend assumptions | Core 不 import backend；差异只出现在 adapter 产生的 refs / metadata | VERIFIED |
| 隐式 mutable coupling | projection 只读；不写回 EventStore、不重跑 model/tool | VERIFIED |

## 2. Evaluator

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | duck-typed ExecutionRecord + `TaskSpecification`（`evaluation/evaluator.py`） | VERIFIED |
| 输出类型 | `EvaluationResult`：execution_id / task_id / status / findings | VERIFIED |
| identity | `execution_id` + `task_id`；无独立 `evaluation_id`（测试用 `{execution_id}:{task_id}` 组合引用） | PARTIAL |
| evidence refs | 每条 Finding 携带 `evidence_refs` | VERIFIED |
| replay refs | RULE-10 消费 `record.replay_ref`；`evaluate()` 纯读 | VERIFIED |
| version refs | record/projection 版本可读；TaskSet 版本由调用方传入 | PARTIAL |
| lossiness | LOSSY mapping ⇒ 相关规则 INCONCLUSIVE，不升级 | VERIFIED |
| cross-backend assumptions | 同一规则表，无 backend 分支 | VERIFIED |
| 隐式 mutable coupling | 无 Runtime / EventStore 写入 | VERIFIED |

## 3. Failure Attribution

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | ExecutionRecord + EvaluationResult（`evaluation/failure_attribution.py`） | VERIFIED |
| 输出类型 | `FailureAttribution`：failure_id / kind / turn / step / attempt / refs / owner / initiator / mapping_quality | VERIFIED |
| identity | `failure_id` 由 execution_id + failure kinds 确定性派生 | VERIFIED |
| evidence refs | `evidence_refs` + `backend_event_refs` | VERIFIED |
| replay refs | 通过 `execution_id` / `backend_event_refs` 可回溯；replay 后重建得到等价 attribution | VERIFIED |
| version refs | attribution 本身不携带 Agent 版本（版本属于 candidate） | MISSING（契约外，不阻断） |
| lossiness | `mapping_quality` 显式输出 | VERIFIED |
| cross-backend assumptions | 无 backend 分支 | VERIFIED |
| 隐式 mutable coupling | 纯读，无写回 | VERIFIED |

## 4. ImprovementCandidate

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | `FailureAttribution`（`evaluation/improvement_candidate.py`） | VERIFIED |
| 输出类型 | `ImprovementCandidate`：proposal metadata，无 apply | VERIFIED |
| identity | `candidate_id` 由 failure_id + target + change + baseline 确定性派生 | VERIFIED |
| evidence refs | `evidence_refs` 继承 attribution | VERIFIED |
| replay refs | `source_execution_ids` 存在；无独立 `replay_ref` 字段 | PARTIAL |
| version refs | `baseline_ref` / `change_ref` / `change_type` 存在；无版本注册表解析 | PARTIAL |
| lossiness | `source_mapping_quality`、`context_evidence_status` 保留 | VERIFIED |
| cross-backend assumptions | 无 backend 分支 | VERIFIED |
| 隐式 mutable coupling | 只生成 proposal；不修改 Prompt / Skill / Code | VERIFIED |

## 5. Regression

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | baseline/candidate 的 results + records + attributions + `ImprovementCandidate` + `TaskSet`（`evaluation/regression.py`） | VERIFIED |
| 输出类型 | `RegressionRun`：task_comparisons / aggregate / critical / decision / evidence_refs / comparison_quality | VERIFIED |
| identity | `regression_id` 由 baseline + candidate + task set + run ids 确定性派生 | VERIFIED |
| evidence refs | 每 task 的 execution / evaluation / attribution refs + critical refs | VERIFIED |
| replay refs | execution refs 含 `replay_ref`；compare 不重执行 | VERIFIED |
| version refs | `baseline_ref` / `candidate_ref` 稳定 token；无 registry | PARTIAL |
| lossiness | `comparison_quality` = EXACT / PARTIAL / LOSSY；LOSSY/INCONCLUSIVE 不自动 IMPROVED | VERIFIED |
| cross-backend assumptions | 无 backend 分支 | VERIFIED |
| 隐式 mutable coupling | 纯读，无 promotion / 无执行 | VERIFIED |

## 6. Promotion / Rollback

| 维度 | 现状 | 判定 |
| --- | --- | --- |
| 输入类型 | `ImprovementCandidate`（VALIDATED）+ `RegressionRun`（`evaluation/promotion.py`） | VERIFIED |
| 输出类型 | `PromotionDecision` / `RollbackDecision`（不可变 decision 对象） | VERIFIED |
| identity | `decision_id` / `rollback_id` 确定性派生 | VERIFIED |
| evidence refs | `evidence_refs` 聚合 candidate / regression / gates | VERIFIED |
| replay refs | 经 regression evidence refs 间接回溯 | VERIFIED |
| version refs | `target_version` / `rollback_to_version` 稳定 token；无 registry | PARTIAL |
| lossiness | `promotion_evidence_quality` 继承 regression quality，不升级 | VERIFIED |
| cross-backend assumptions | 无 backend 分支 | VERIFIED |
| 隐式 mutable coupling | 不部署、不路由、不执行 rollback；`authorized_principal` 只记录不强制 | VERIFIED（契约层） |

## 7. 结论

- 六个模块的输入 / 输出 / identity / evidence refs / replay refs / lossiness /
  cross-backend / coupling 均足以支撑本阶段闭环，无需修改 Core semantics。
- PARTIAL 项全部是「外部版本注册表、独立 evaluation_id、rollback 执行」等
  契约外职责；本阶段用确定性 fixture identity + 组合引用表达，不伪造。
- 未发现新的 UNIFIED CORE GAP。

