# 27 — Promotion Assumptions（Phase 5-N）

> 阶段：Phase 5-N。冻结 Promotion / Rollback 契约时的假设。
> 状态词：VERIFIED（有实现/测试证据）/ PARTIAL（source fact 不足）/
> UNKNOWN / DESIGN PROPOSAL。
> 实现位置：`evaluation/promotion.py` + `tests/test_promotion_contract.py`。
> 本文件只冻结决策语义，不实现部署 / canary / rollback execution。

## 逐项假设

### A1 version identity — PARTIAL

`target_version` / `rollback_to_version` / `from_version` / `to_version`
必须是 Stable Version Reference；契约阻断 `candidate` / `latest` /
`current` / `previous` / `last good` / `上一次部署` 等不稳定 token
（`UNSTABLE_VERSION_REFS`，`test_unstable_version_blocks_promotion` /
`test_rollback_target_required`）。任意引用的版本解析依赖外部版本注册表，
本阶段不实现；解析责任在调用方。

### A2 promotion gate semantics — VERIFIED

`decide()` 消费 `ImprovementCandidate`（status=VALIDATED）+ `RegressionRun`，
输出不可变 `PromotionDecision`；Evaluation / Regression / Safety 三个 required
gate 任一 FAIL / INCONCLUSIVE ⇒ REJECTED；Policy gate 允许 NOT_APPLICABLE。
INCONCLUSIVE ≠ PASS，REGRESSED ≠ PROMOTE（`test_promotion_decision` /
`test_inconclusive_evaluation_blocks_promotion` / `test_regressed_blocks_promotion`）。

### A3 safety gate semantics — VERIFIED

调用方声明 critical safety categories（默认 security / authorization /
unsafe_tool_use / data_integrity）；`CriticalRegression.category` 命中 ⇒
Safety gate FAIL 并阻断 Promotion；未命中时 Safety gate PASS，但 Regression
gate 仍因任何 critical regression 阻断（`test_safety_gate`）。

### A4 policy gate semantics — PARTIAL

契约允许引用外部 `policy_ref`（如 promotion policy v3）并把它记为 gate
evidence；无 policy_ref 时 gate = NOT_APPLICABLE 且不阻断。外部 policy
engine / IAM / RBAC 未实现（刻意不在本阶段）。

### A5 authorization evidence — PARTIAL

`authorized_principal` 必须由调用方提供 durable evidence；缺失时
`authorization=PARTIAL`，不伪造。`owner_ref` / `initiator_ref` 只记录不授权
（`test_owner_not_authorization` / `test_initiator_not_authorization`）。

### A6 canary observation semantics — PARTIAL

CANARY 必须同时有 `canary_observations` + `observation_window`；缺任一 ⇒
PENDING，不伪造 CANARY PASS（`test_canary_state`）。真实 observation /
流量路由未实现，属外部职责。

### A7 rollback target identity — VERIFIED

每个 `PromotionDecision` 必须携带稳定的 `rollback_to_version`；缺失或不稳定
token ⇒ BLOCKED。`request_rollback()` 同样要求 from / to 稳定且不同
（`test_rollback_target_required` / `test_rollback_decision`）。

### A8 rollback trigger — VERIFIED

`ROLLBACK_TRIGGERS` 白名单：regression_after_promotion /
critical_safety_incident / policy_violation / operator_decision；白名单外
拒绝。本阶段不自动监控生产（`test_rollback_decision`）。

### A9 lossiness — VERIFIED

`promotion_evidence_quality` 继承 `RegressionRun.comparison_quality`；
LOSSY 默认阻断，即使 policy 例外放行也保持 LOSSY / PARTIAL，绝不升级成
EXACT（`test_lossy_evidence_not_exact`）。

### A10 cross-backend portability — VERIFIED

`decide()` / `request_rollback()` 无 `if codex` / `if agentscope` 分支；
backend 差异只出现在 evidence refs / backend refs，不进入 decision
（`test_cross_backend_shape`）。

### A11 capability-version relationship — DESIGN PROPOSAL

Promotion 只决定“哪个版本被采用”（validated version → decision →
deploy/adopt）；Capability 的 install / dispose / ownership 仍由 Capability
Runtime 管理（python-cordis 12/13）。Deployment Layer 未实现，Phase 6 边界。

## 汇总

| 假设 | 状态 |
| --- | --- |
| A1 version identity | PARTIAL |
| A2 promotion gate semantics | VERIFIED |
| A3 safety gate semantics | VERIFIED |
| A4 policy gate semantics | PARTIAL |
| A5 authorization evidence | PARTIAL |
| A6 canary observation semantics | PARTIAL |
| A7 rollback target identity | VERIFIED |
| A8 rollback trigger | VERIFIED |
| A9 lossiness | VERIFIED |
| A10 cross-backend portability | VERIFIED |
| A11 capability-version relationship | DESIGN PROPOSAL |
