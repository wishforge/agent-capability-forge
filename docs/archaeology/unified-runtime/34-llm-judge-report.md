# 34 — LLM Judge Report（Phase 6-A）

> 阶段：Phase 6-A。产物：
> `32-llm-judge-audit.md`、`33-llm-judge-assumptions.md`、
> `evaluation/llm_judge.py`（Judge contract + fake judge + aggregator +
> golden tasks）、`evaluation/tests/test_llm_judge.py`（20 + 2 tests）。
> 未实现真实生产 LLM Judge / Auto Improvement / Auto Promotion / Auto
> Rollback / Canary / Third Backend / Runtime semantic change /
> Evaluator rule change / Prompt mutation / Capability mutation。

---

## 1. 十二问

### 1. Judge 是否完全 Runtime-independent？

**是。** `llm_judge.py` 只 import `models` 与标准库；Judge 只消费
`LLMJudgeInput`（task spec / execution record 投影 / deterministic
evaluation / rubric / oracle / evidence refs），不读 Runtime、EventStore、
Capability Manager、ContextVar。`test_judge_input_is_runtime_independent`
检查模块源码 import 面。

### 2. Deterministic Evaluation 与 Judge 如何分工？

**事实 vs 语义。** RULE-01..13 继续负责 objective / runtime-verifiable facts
（tool 是否调用、是否 timeout、是否 unsafe retry、是否成功）；Judge 负责
semantic / qualitative judgment（最终答案质量、业务完成度、推理合理性、
隐藏语义错误、答案级安全/策略）。规则一行未改。

### 3. Objective failure 是否能覆盖 Judge PASS？

**是。** `aggregate()` 先看 deterministic status：FAIL → 最终 FAIL，即使
Judge 给出 PASS；`test_deterministic_failure_overrides_judge_pass` 与
TASK-JUDGE-03（答案正确但调用 erp.force_write）覆盖。

### 4. Judge semantic failure 如何进入最终 Evaluation？

**能降低，不能覆盖 objective fact。** Deterministic PASS + Judge FAIL →
最终 FAIL；Deterministic PASS + Judge INCONCLUSIVE → 最终 INCONCLUSIVE；
Deterministic FAIL 时无论 Judge 结果如何最终 FAIL。
`test_judge_failure_reduces_final_result` 覆盖。

### 5. Confidence 是否明确？

**是。** HIGH / MEDIUM / LOW；明确不确定 → INCONCLUSIVE；LOW + PASS 构造时
拒绝；INCONCLUSIVE + HIGH 拒绝；多个 Judge 取最低 confidence。

### 6. Rubric 是否版本化？

**是。** `JudgeRubric(rubric_id, version, criteria, pass_threshold,
fail_threshold)`；criteria 带 criterion_id / description / weight /
required；阈值校验 0 <= fail < pass <= 1；不写死在 evaluator。

### 7. Prompt / model 是否可追溯？

**是。** 每个 `LLMJudgeResult` 记录 judge_id、model_ref、model_version、
prompt_ref、prompt_version、rubric_ref；provider 无版本时允许 UNKNOWN，
不伪造。

### 8. Lossiness 是否透明？

**是。** Judge 读取 record 的 `lossiness[]` / `mapping_quality`；fake judge
对 LOSSY 证据返回 INCONCLUSIVE + LOW confidence；聚合器不把 LOSSY 升级为
EXACT（`test_lossy_evidence`）。

### 9. Context 不足能否 INCONCLUSIVE？

**是。** `context_provenance` 缺失时 fake judge 强制 INCONCLUSIVE + LOW，
aggregator 保持 INCONCLUSIVE（`test_missing_context_inconclusive`、
TASK-JUDGE-04）。

### 10. Replay 与 Judge rerun 是否分离？

**是。** `replay()` / `build_execution_record()` 只重建 ExecutionRecord，
不产生 judge 结果；重新运行 Judge 生成新 judge_id，旧结果 immutable、
不被覆盖（`test_replay_does_not_rerun_judge`、
`test_judge_rerun_new_run_id`）。

### 11. AgentScope / Codex 是否共享 Judge semantics？

**是。** 同一 TaskSpecification + Rubric + fake judge 跑两个 backend：
final status / score / confidence / model / prompt / rubric 完全一致；
judge_id 与 evidence refs 因 backend 不同而不同（
`test_cross_backend_judge_shape`）。

### 12. 最大 LLM Judge data gap 是什么？

**完整 request-time context snapshot 未持久化（quality=PARTIAL）**：Judge
无法从 record 精确重建 “Agent actually saw” 的全部输入（system /
runtime_context / current_input）。次大缺口：`tool_results[].backend_ref`
PARTIAL、统一层 usage/cost UNKNOWN（04 §8 / 06 §2 / 15 §10），以及真实
LLM Judge 的 model variance / prompt sensitivity 未验证。

---

## 2. 最终判定

**PARTIAL**。

已成立：

- Judge 不依赖 Runtime internals（模块边界 + 测试）；
- Deterministic facts 最高优先级（objective FAIL 覆盖 Judge PASS）；
- Judge 可评价 semantic quality（rubric + fake judge + golden tasks）；
- Confidence / Rubric / Prompt / Model 可追溯；
- Lossiness 可见，LOSSY 不升级 EXACT；
- Context 不足可 INCONCLUSIVE；
- Judge result immutable，rerun identity 独立；
- AgentScope / Codex 共享 Judge semantics（shape 一致）；
- 既有 Deterministic Evaluation 零修改。

未验证（按阶段禁令，本轮不做）：

- 真实 provider / model variance；
- 真实 context snapshot 完整性；
- 真实 prompt 敏感度 / calibration；
- 多 Judge ensemble 算法（第一版只做 conflict → INCONCLUSIVE）。

---

## 3. 回归

执行（2026-08-16）：

```text
python3 -m pytest docs/archaeology/deepseek-harness/evaluation/tests -q
128 passed（108 + 20）

python3 -m pytest docs/archaeology/deepseek-harness/runtime/tests -q
116 passed, 5 subtests passed

python3 -m pytest research/control-plane-loop -q
30 passed
```

Phase 1 / 2 / 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H /
5-I / 5-J / 5-K / 5-L / 5-M / 5-N / 5-O 继续 PASS；新增 Phase 6-A。

按阶段指令停止：不进入 Phase 6-B。
