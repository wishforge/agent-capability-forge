# 25 — Regression Report（Phase 5-M）

> 阶段：Phase 5-M。产物：
> `23-regression-audit.md`、`24-regression-assumptions.md`、
> `evaluation/regression.py`（RegressionRun contract）、
> `evaluation/tests/test_regression_contract.py`（15 tests）。
> 未实现 Regression Engine / Promotion / Canary / Rollback / LLM Judge /
> 自动生成 candidate；未修改 Runtime / EventStore / Evaluator rules / models。

## 1. 十二问

### 1. Regression 是否完全独立于 Runtime？

**是。** `compare()` 只消费 `ExecutionRecord` + `EvaluationResult` +
`TaskSet` + `ImprovementCandidate`；不 import runtime / EventStore /
ContextVar，无写回，不重执行。

### 2. Baseline 是否有稳定 identity？

**是（契约层）。** baseline_ref 必填且阻断 `UNKNOWN` / `latest` /
`last-run` / `last-successful-run` / `previous`；candidate.baseline_ref
必须与 run 一致。版本注册表解析在契约外（A1，PARTIAL）。

### 3. Candidate 是否有稳定 identity？

**是。** `candidate_ref = ImprovementCandidate.candidate_id`；
`REQUIRES_DISAMBIGUATION` / `INVALID_FOR_REGRESSION` 被 BLOCK，Regression
不重新解释 candidate。

### 4. TaskSet 是否可版本化？

**是（契约层）。** `TaskSet(task_set_id, version, task_ids)`；同一次
Regression 的 baseline / candidate 共享同一 TaskSet，结果/记录超出 task
set 或缺失均 BLOCK。

### 5. Replay 与 Re-execution 是否严格分离？

**是。** Replay = 历史 EventLog → ExecutionRecord 的只读重建（04 §12，
不调用 model/tool）；Re-execution = 新 execution identity（
`baseline_run_id` / `candidate_run_id` / `task_id`），不覆盖历史 execution。
测试 `test_replay_vs_reexecution` / `test_reexecution_identity` 覆盖。

### 6. Per-task comparison 是否成立？

**是。** 每个任务输出 `task_id` + `baseline_status` + `candidate_status` +
`delta` + `outcome`（IMPROVED / REGRESSED / UNCHANGED / INCONCLUSIVE）+
baseline/candidate evidence refs（execution + evaluation + 可选 attribution）。

### 7. Aggregate comparison 是否成立？

**是。** success_rate / failure_rate / timeout_rate / unsafe_retry_rate /
unresolved_tool_rate 确定性派生；cost/usage 无可靠来源时 `NOT_AVAILABLE`，
不创造虚假数值。

### 8. Critical regression 是否能阻断整体改善？

**是。** decision 规则 A 优先：任一 critical task PASS → FAIL 即 REGRESSED，
即使 aggregate success_rate 上升（`test_aggregate_does_not_hide_critical_regression`）。
category 白名单：security / authorization / unsafe_tool_use /
policy_violation / data_integrity。

### 9. Lossiness 是否透明？

**是。** `comparison_quality` = EXACT / PARTIAL / LOSSY / INCONCLUSIVE；
LOSSY 或 INCONCLUSIVE 时 decision 不默认为 IMPROVED（
`test_lossy_evidence`）。

### 10. Replay 后 Evaluation 是否稳定？

**是。** same record + same rules ⇒ same EvaluationResult；RegressionRun
由 immutable 输入确定性派生，重放输入产出相等 run（
`test_replay_stability`）。

### 11. AgentScope/Codex 是否共享 Regression semantics？

**是。** `compare()` 无 backend 分支；backend 差异只出现在 evidence refs /
backend refs / lossiness，不进入 decision（`test_cross_backend_shape`）。

### 12. 最大 Regression Data Gap 是什么？

1. **baseline / version 注册表未实现**：契约能阻断不稳定 token，但任意
   引用的版本解析依赖外部 registry（A1）。
2. **cost / usage 统一层 UNKNOWN**：契约允许 `NOT_AVAILABLE`，不伪造。
3. **critical category 由调用方声明**：无自动分类（刻意禁止 LLM Judge）。
4. **re-execution runner 未实现**：契约可表达 identity，执行在 Phase 6。

## 2. 最终判定

**PASS**

- baseline / candidate 可稳定识别（契约层 + BLOCK 规则）；
- TaskSet 可识别且可版本化；
- Replay 与 Re-execution 严格分离；
- per-task comparison 成立（4 分类 + 双方 evidence refs）；
- aggregate comparison 成立（5 类率值，usage 允许 NOT_AVAILABLE）；
- critical regression 可阻断整体改善；
- lossiness 可见（comparison_quality + decision 规则 D）；
- evidence 可追溯（execution / evaluation / replay / backend refs）；
- cross-backend semantics 独立（无 backend 分支）；
- Runtime / EventStore / Evaluator rules / models 零修改。

## 3. 回归

| Suite | 结果 |
| --- | --- |
| Phase 5-I / 5-J / 5-K / 5-L evaluation suite + Phase 5-M（77 tests） | PASS |

```bash
PYTHONPYCACHEPREFIX=/private/tmp/phase5m-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/evaluation/tests \
  -p 'test_*.py' -q
```

按阶段指令，完成后停止：不进入 Phase 5-N / Regression Engine /
Promotion / Canary / Rollback。
