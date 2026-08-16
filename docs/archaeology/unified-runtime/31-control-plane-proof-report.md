# 31 — Control Plane Proof Report（Phase 5-O）

> 阶段：Phase 5-O。产物：
> `29-control-plane-proof-audit.md`、`30-control-plane-proof-assumptions.md`、
> `evaluation/tests/test_control_plane_e2e.py`（11 tests）。
> 只做 composition / integration proof，未修改任何 Core contract。

## 1. 是否真正跑通 Execution → Evaluation？

**是。** AgentScope 通过真实 adapter 路径 + 确定性 model script 执行；
Codex 通过 pinned schema 的确定性 rollout fixture 执行。每个版本
（V1/V2/V3）生成 `ExecutionRecord` 后调用 `evaluate()`。

- V1：`procurement-001/002` = FAIL（RULE-04 缺 `procurement.suggest`），
  `lookup-001` / `safety-001` = PASS。
- V2：全部 PASS。
- V3：`safety-001` = FAIL（RULE-05 调用 `erp.force_write`），其余 PASS。

## 2. Evaluation → Failure Attribution 是否闭环？

**是。** V1 的 `EvaluationResult`（RULE-04 FAIL）输入 `attribute()`，
得到 `FailureAttribution`：failure_kind=`COMPLETION_FAILURE`，
failure_id / turn / step / attempt / owner / initiator / mapping_quality
全部有值（`test_failure_to_candidate`、`test_replay_stability`）。

## 3. Failure → ImprovementCandidate 是否闭环？

**是。** `propose()` 从 V1 attribution 生成 `PROPOSED` candidate，
携带 `source_failure_ids` / `source_evaluation_ids` /
`source_execution_ids` / `baseline_ref` / `change_type` / hypothesis /
expected_effect；不修改 V1（`test_failure_to_candidate`）。

## 4. Candidate → Regression 是否闭环？

**是。** 同一 TaskSet 下 V1 vs V2 进入 `compare()`，得到
`RegressionRun`：task comparison、aggregate、critical_regressions、
decision、evidence_refs（`test_candidate_to_regression`）。

## 5. Regression → Promotion 是否闭环？

**是。** V2 的 `RegressionRun`（IMPROVED，critical=0）输入 `decide()`：
Evaluation / Regression / Safety / Policy 四个 gate 全部 PASS，
`decision=PROMOTED`（`test_end_to_end_good_candidate`）。

> 这是 contract-level promotion eligibility；没有真实部署。

## 6. Critical Regression → Rejection 是否闭环？

**是。** V3 的 aggregate success 从 0.5 提升到 0.75，但
`safety-001` 出现 critical regression（PASS→FAIL，category=authorization），
`RegressionRun.decision=REGRESSED`，`PromotionDecision.decision=REJECTED`
（`test_critical_regression`、`test_promotion_rejected`）。
aggregate improvement 不能覆盖 critical regression。

## 7. Promotion → Rollback Decision 是否闭环？

**是。** 以 V2 已采用为前置，输入 production-style incident evidence，
`request_rollback(from_version=v2, to_version=v1)` 返回
`RollbackDecision(status=REQUESTED, trigger=critical_safety_incident)`；
只验证语义，不执行回滚（`test_rollback_decision`）。

## 8. Replay 后结果是否稳定？

**是（语义等价）。** V1 记录持久化后 reopen + `replay()`：
重建的 ExecutionRecord、EvaluationResult、FailureAttribution 在
status / findings / failure_id / kind / ids / evidence refs 上完全一致；
EventStore 事件数不变（`test_replay_stability`）。

注意：AgentScope adapter 每次运行会生成随机 backend event/reply ID，
因此跨 run 的 backend event refs 不做字节级相等；这是既有 adapter 行为，
不影响任何 control-plane decision，也不是本阶段引入的损失。

## 9. Evidence Chain 是否完整？

**是（契约层）。** `test_evidence_chain` 从 PromotionDecision 反查：

```text
PromotionDecision -> regression_ref -> RegressionRun
  -> candidate_ref -> ImprovementCandidate
  -> source_failure_ids -> FailureAttribution
  -> execution_id -> ExecutionRecord
  -> replay_ref / backend refs / evaluation refs
```

PARTIAL 项（如实记录，不伪造）：

- 没有独立 `evaluation_id`，测试使用 `{execution_id}:{task_id}` 组合引用。
- 版本注册表不存在；V1/V2/V3 是确定性 fixture identity。
- `authorized_principal` 只记录，Promotion gate 不强制 authorization。
- RollbackDecision 只到 REQUESTED，不包含执行。

## 10. AgentScope / Codex 是否共享 Control Plane semantics？

**是。** `test_cross_backend_shape` 对两个 backend 各跑完整
Execution → Evaluation → Attribution → Candidate → Regression →
Promotion：decision、gate 状态、aggregate、critical regressions 全部相等；
candidate / regression / decision id 因 backend 内部 representation 不同
而不同。

证明口径：

- AgentScope：真实 adapter 执行路径 + 确定性 scripted model（无网络）。
- Codex：pinned RolloutItem schema 的确定性 fixture（本测试内联生成
  V1/V3 与单步双 tool 的 V2 等效 fixture），不调用网络模型；
  已有 real Codex golden record 由 Phase 5-C/5-D 测试继续覆盖。

## 11. 是否存在新的 Unified Core Gap？

**否。** 29 号审计逐模块确认输入 / 输出 / identity / evidence refs /
replay refs / lossiness / cross-backend / coupling 均可用；
本阶段未修改 Session / Turn / Step / Execution / Attempt / EventStore /
Surface / Model Context / Capability Ownership / Causality / Evaluator /
Regression / Promotion 语义。

## 12. 当前最大的商业化/工程化 gap 是什么？

1. 版本注册表：`baseline_ref` / `target_version` 目前是稳定字符串，
   没有外部 registry 解析与不可变版本对象。
2. validated candidate 的 durable 证据：`VALIDATED` 是状态常量，
   没有状态转换引擎或 validation 记录。
3. 部署 / canary / rollback 执行层：契约只给 eligibility / REQUESTED，
   没有 traffic、观察窗口持久化或回滚执行。
4. authorization：decision 记录 principal，但不作为 gate 强制执行。

## 最终判定

**PASS。**

- V1 failure 被 Evaluation 发现：FAIL（RULE-04）。
- Failure Attribution 定位：COMPLETION_FAILURE + step/attempt/evidence。
- ImprovementCandidate 生成：PROPOSED，refs 完整。
- V2 Regression = IMPROVED（success 0.5 → 1.0，critical=0）。
- V2 Promotion = PROMOTED（契约层资格）。
- V3 Regression = REGRESSED（success 0.5 → 0.75 但 critical>0）。
- V3 Promotion = REJECTED。
- RollbackDecision 形成：v2 → v1，REQUESTED。
- Replay 保持 semantic equivalence。
- Evidence Chain 完整（PARTIAL 项已如实标注）。
- AgentScope 真实执行 + Codex 可信 fixture 均可通过完整闭环。
- 无需修改 Core semantics。

## 回归

执行结果（2026-08-16）：

```text
python3 -m pytest docs/archaeology/deepseek-harness/evaluation/tests -q
108 passed

python3 -m pytest docs/archaeology/deepseek-harness/runtime/tests -q
116 passed, 5 subtests passed

python3 -m pytest research/control-plane-loop -q
30 passed
```

Phase 1 / 2 / 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H /
5-I / 5-J / 5-K / 5-L / 5-M / 5-N 继续 PASS；新增 Phase 5-O。

Phase 5-O 完成后停止，未进入 Phase 6。
