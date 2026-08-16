# 21 — Improvement Candidate Assumptions（Phase 5-L）

> 依据：`20-improvement-audit.md`（实现前审计）+ Phase 5-G/5-H/5-I/5-J/5-K
> 契约（04/05/17/19）+ Codex / DSH 09/10/11 + 本次
> `evaluation/improvement_candidate.py` 与
> `evaluation/tests/test_improvement_candidate.py`。
> 状态词：VERIFIED（有实现/测试证据）/ PARTIAL（source fact 不足）/
> UNKNOWN / DESIGN PROPOSAL。
> 本文件只冻结 Candidate 语义，不实现 Regression / Promotion / 存储。

| # | Assumption | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| A1 | candidate identity：确定性派生，与输入 attribution + target/change/baseline 一一对应 | VERIFIED | `candidate_id = failure_id|target_type|target_ref|change_type|change_ref|baseline_ref`；`test_candidate_replay_stable` |
| A2 | baseline identity：candidate 必须指向改动前的具体版本/配置；缺失不能生成；UNKNOWN 不能进 Regression | VERIFIED | `baseline_ref` 必填，空值 ValueError；`baseline_ref="UNKNOWN"` ⇒ `INVALID_FOR_REGRESSION`；`test_candidate_requires_baseline` |
| A3 | target reference：candidate 必须明确改哪个 capability / prompt / skill / policy | VERIFIED | `target_type` + `target_ref` 必填；`test_candidate_target_explicit` |
| A4 | hypothesis semantics：hypothesis 是待验证提案，不是事实或状态 | VERIFIED | 字段名为 `hypothesis`；`"VERIFIED"` 被拒绝；初始 status=PROPOSED；`test_candidate_hypothesis_marked` |
| A5 | expected effect semantics：定性描述必填；定量目标可选；无历史基线禁止伪造数值 | VERIFIED | 无 metric/delta ⇒ `QUALITATIVE_ONLY`；提供 metric/delta ⇒ `METRIC_DRIVEN`；`baseline_ref="UNKNOWN"` 时拒绝数值；`test_candidate_expected_effect` |
| A6 | evidence completeness：必须引用 FailureAttribution + EvaluationResult + ExecutionRecord | VERIFIED | `failure_id` + `evidence_refs` + `source_execution_ids` + `source_evaluation_ids` 全必填；`test_candidate_requires_failure_evidence` / `test_candidate_evidence_refs` |
| A7 | lossiness handling：LOSSY 不得因 Candidate 层变 EXACT | VERIFIED | `source_mapping_quality` 继承 `attribution.mapping_quality`；`test_lossy_candidate_visible` |
| A8 | multiple failure handling：多个不可排序失败不猜 root cause | VERIFIED | `MULTIPLE_CANDIDATES` ⇒ `REQUIRES_DISAMBIGUATION`，保留 composite failure_id；`test_multiple_failure_requires_disambiguation` |
| A9 | cross-backend portability：AgentScope / Codex 同一 Candidate shape | VERIFIED | 同一 `propose()`；backend 差异只允许在 refs / `source_mapping_quality`；`test_cross_backend_candidate_shape` |
| A10 | candidate lifecycle：状态集合冻结；不自动应用、不实现 promotion/rollback | VERIFIED（状态集合）/ DESIGN PROPOSAL（状态转换） | `STATUSES` 含 PROPOSED / UNDER_VALIDATION / REJECTED / VALIDATED / PROMOTED / ROLLED_BACK + REQUIRES_DISAMBIGUATION / INVALID_FOR_REGRESSION；无 apply/promote/rollback 方法；`test_candidate_not_auto_applied` |

## 显式保留的 gap（不伪造）

- EvaluationResult 没有 `evaluation_id`：`propose` 要求调用者显式传
  `evaluation_ids`，本阶段不发明 id。
- `change_ref` 是 proposal 引用，无具体 change artifact / version registry。
- 完整 request-time context snapshot 仍 PARTIAL：
  `context_evidence_status=CONTEXT_EVIDENCE_PARTIAL` 显式保留。
- 状态转换（UNDER_VALIDATION → VALIDATED → PROMOTED / ROLLED_BACK）只定义
  状态，不实现转换引擎。
- 无存储格式、无 Regression engine、无 promotion / canary / rollback。

## 禁止事项

- 不自动改 prompt / skill / code / capability；
- 不自动发布 / 不实现 promotion / rollback / canary；
- 不把 LOSSY 当 EXACT；
- 不猜 root cause（MULTIPLE_CANDIDATES ⇒ REQUIRES_DISAMBIGUATION）；
- 不伪造 expected metric / delta（无 baseline 时）；
- 不修改 Runtime / EventStore / Evaluator rules / models。
