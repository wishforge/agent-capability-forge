# 24 — Regression Assumptions（Phase 5-M）

> 阶段：Phase 5-M。冻结 RegressionRun 契约时的假设。
> 状态词：VERIFIED / PARTIAL / UNKNOWN / DESIGN PROPOSAL。
> 实现位置：`evaluation/regression.py` + `tests/test_regression_contract.py`。

## 逐项假设

### A1 baseline identity — PARTIAL

`ImprovementCandidate.baseline_ref` 必填（5-L）；Regression 契约阻断
`UNKNOWN` / `latest` / `last-run` / `last-successful-run` / `previous` 等
不稳定引用，并要求 candidate 与 run 的 baseline_ref 一致。但任意引用的
**稳定版本解析**依赖外部版本注册表，本阶段不实现；解析责任在调用方。

### A2 candidate identity — VERIFIED

`ImprovementCandidate.candidate_id` 由 failure_id + target + change +
baseline 确定性派生（5-L）；`REQUIRES_DISAMBIGUATION` /
`INVALID_FOR_REGRESSION` 的 candidate 被 Regression 阻断。Regression
只消费 Candidate Contract，不重新解释 candidate。

### A3 task set version — DESIGN PROPOSAL

`TaskSet`（task_set_id + version + task_ids）在本阶段冻结为 dataclass；
同一 Regression 的 baseline / candidate 必须共享同一 TaskSet。存储格式、
版本注册表、TaskSpecification 的 version 字段均未实现。

### A4 replay semantics — VERIFIED

Replay = 历史 EventLog → ExecutionRecord 的只读重建（04 §12；RULE-10）；
不重新调用 model / tool / external system；same execution + replay ⇒
same semantic record。Replay 前后只允许 runtime object identity /
timestamp / backend raw formatting 不同。

### A5 re-execution semantics — DESIGN PROPOSAL

Re-execution = TaskSpecification + Baseline/Candidate 真正再次执行，验证
Candidate。契约能表达 `baseline_run_id` / `candidate_run_id` / `task_id`，
且新 execution 必须使用新 identity、不覆盖历史 execution；执行 runner 未
实现（Phase 6 边界）。

### A6 evaluation comparability — VERIFIED

baseline / candidate 使用同一 evaluator + 同一 RULE 集合 + 同一
`EvaluationResult` shape，按 `task_id` 绑定；LOSSY 字段带质量标记消费，
不报假精度（04 §13；05 §5）。

### A7 per-task comparison — VERIFIED

`TaskComparison`（task_id + baseline_status + candidate_status + delta +
outcome + 双方 evidence refs）已实现并经 15 项契约测试覆盖；
IMPROVED / REGRESSED / UNCHANGED / INCONCLUSIVE 由 status 确定性派生。

### A8 aggregate metrics — PARTIAL

success_rate / failure_rate 从 status 确定性派生；timeout_rate /
unsafe_retry_rate / unresolved_tool_rate 从 RULE-07 / RULE-03 / RULE-02
findings 派生（findings 缺失时 NOT_AVAILABLE）；cost/usage 仅在调用方提供
可靠值时启用，否则 NOT_AVAILABLE，不创造虚假数值。

### A9 critical regression — DESIGN PROPOSAL

critical category（security / authorization / unsafe_tool_use /
policy_violation / data_integrity）由调用方按 task 声明，契约校验白名单并
在 PASS → FAIL 时生成 `CriticalRegression`。不做自动分类（无 LLM Judge）。

### A10 lossiness — VERIFIED

`comparison_quality` = EXACT / PARTIAL / LOSSY / INCONCLUSIVE；任一 record
为 LOSSY 即整体 LOSSY；LOSSY 或 INCONCLUSIVE 时 decision 不默认为
IMPROVED（critical regression 仍优先 REGRESSED）。

### A11 cross-backend equivalence — VERIFIED

`compare()` 无 `if codex` / `if agentscope` 分支；AgentScope / Codex 走同一
`RegressionRun` shape，backend 差异只出现在 evidence refs / backend refs /
lossiness。Backend difference ≠ Regression difference；以 Unified
Evaluation semantics 为比较依据。

## 汇总

| 假设 | 状态 |
| --- | --- |
| A1 baseline identity | PARTIAL |
| A2 candidate identity | VERIFIED |
| A3 task set version | DESIGN PROPOSAL |
| A4 replay semantics | VERIFIED |
| A5 re-execution semantics | DESIGN PROPOSAL |
| A6 evaluation comparability | VERIFIED |
| A7 per-task comparison | VERIFIED |
| A8 aggregate metrics | PARTIAL |
| A9 critical regression | DESIGN PROPOSAL |
| A10 lossiness | VERIFIED |
| A11 cross-backend equivalence | VERIFIED |
