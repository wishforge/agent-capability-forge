# 26 — Promotion Audit（Phase 5-N）

> 阶段：Phase 5-N。本文件在 Promotion 契约冻结前完成，只审计
> `ImprovementCandidate`（5-L）、`RegressionRun`（5-M）、`EvaluationResult`（5-I）、
> `FailureAttribution`（5-K）以及 Codex / DSH / python-cordis archaeology
> （codex 10、DSH 11/12、capability 12/13）已经能为 Promotion / Rollback 提供什么。
> 状态词：AVAILABLE / PARTIAL / MISSING。
> 判定原则：只依据 durable evidence 与已冻结契约；evidence 不足时不猜。

审计对象：

```text
ImprovementCandidate
    ↓
RegressionRun
    ↓
Safety / Policy Gates（本阶段契约）
    ↓
PromotionDecision
    ↓
RollbackDecision
```

## 1. 逐项审计

| # | 需要的事实 | 现状证据 | 判定 |
| --- | --- | --- | --- |
| 1 | candidate identity | `ImprovementCandidate.candidate_id` + `propose()`（5-L）；`REQUIRES_DISAMBIGUATION` / `INVALID_FOR_REGRESSION` 可识别 | AVAILABLE |
| 2 | baseline identity | `candidate.baseline_ref` 必填 + Regression 阻断不稳定 token（5-M）；版本注册表解析在契约外 | PARTIAL（ref 存在；无 registry） |
| 3 | validated improvement identity | `ImprovementCandidate.VALIDATED` 状态常量存在（5-L）；无状态转换引擎、无 validated 证据记录 | PARTIAL |
| 4 | regression result | `RegressionRun`：decision / comparison_quality / critical_regressions / evidence_refs（5-M） | AVAILABLE |
| 5 | safety gate | `CriticalRegression` + `CRITICAL_CATEGORIES`（5-M）可表达 critical 阻断；无 gate 对象/语义 | PARTIAL |
| 6 | policy gate | `TaskSpecification.policy_constraints`（5-I）是任务级约束；无 promotion policy 引用/结果 | MISSING |
| 7 | approval | 无 `authorized_principal` / approval 记录；5-K 只有 initiator / owner，不代表授权 | MISSING |
| 8 | promotion version | `candidate.target_ref` / `change_ref` 是 proposal 引用（5-L）；无稳定 `target_version` / 版本注册表 | PARTIAL（ref 存在；无版本对象） |
| 9 | canary version | Codex 10 §1.6 / DSH 11 §1：canary 全 NOT FOUND | MISSING |
| 10 | rollback target | Codex 只有线程级 `/rollback`（codex 10 §1.7）；DSH 只有事务回滚（11 §1.5）；无版本回滚目标 | MISSING |
| 11 | rollback reason | 无 rollback 契约、无 reason 字段 | MISSING |
| 12 | promotion evidence | `candidate.evidence_refs`（5-L）+ `RegressionRun.evidence_refs`（5-M）可追溯；无 promotion 聚合层 | PARTIAL（输入 AVAILABLE） |
| 13 | decision provenance | 无 decision 对象；initiator / owner 存在但无 authorization 分离 | MISSING |

## 2. 结论

- **AVAILABLE**：candidate identity、regression result。
- **PARTIAL**：baseline identity、validated improvement identity、safety
  gate、promotion version、promotion evidence。
- **MISSING**：policy gate、approval、canary version、rollback target、
  rollback reason、decision provenance。

Phase 5-N 只补 **Promotion / Rollback contract + gate semantics**：让
`PromotionDecision` 能消费 Candidate + Regression，表达版本 / 回滚目标 /
evidence / gate results / 审计字段；不实现版本注册表、部署层、canary
traffic、真实 authorization、真实 rollback，不修改 Runtime / Evaluator /
Capability ownership。
