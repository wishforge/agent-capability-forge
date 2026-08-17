# 63 — Protocol Contract Validation Report（Phase 7.2）

> 阶段：Phase 7.2（Contract Validation；离线）。
> 基线：61（Phase 7.1 Core + Extension + Governance Invariants）、
> 57、60。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 second-consumer
> artifacts；未新增第三个 consumer；未做 universal JSON Schema / API / DB /
> Kubernetes / production runtime integration / E.8 / production promotion；
> 未运行 live provider；未 commit / push。

## 1. 执行摘要

新增最小 offline validator + offline tests，把 61 定义的 G1–G7、最小状态机、
Core / Extension 隔离全部变成可机械检查的协议契约。

```text
新增文件：
  docs/archaeology/unified-runtime/62-protocol-contract-validation-plan.md
  docs/archaeology/unified-runtime/63-protocol-contract-validation-report.md
  docs/archaeology/unified-runtime/phase7.2/validate_protocol_contract.py
  docs/archaeology/unified-runtime/phase7.2/test_protocol_contract.py

验证命令（本次实际运行）：
  python3 -m pytest docs/archaeology/unified-runtime/phase7.2 -q
    -> 29 passed in 0.03s
  python3 -m py_compile docs/archaeology/unified-runtime/phase7.2/validate_protocol_contract.py
    -> COMPILE_OK
```

最终判定：

```text
CONTRACT_VALID_WITH_EXTENSIONS
```

回答核心问题：

> Core + Extension + Governance Invariants 已经从架构理念变成了机器可以
> 检查的协议契约 —— 在离线快照层面是（FACT，29 个测试证据）；production
> runtime 强制执行未实现（UNKNOWN，本阶段不接 runtime）。

## 2. 每个 Invariant 的验证结果

| Invariant | 机械检查？ | 证据（FACT，测试函数） | 违例消息 |
| --- | --- | --- | --- |
| G1 No registered policy → PROMOTE impossible | MACHINE_CHECKABLE | test_g1_missing_policy_blocks_promote / test_g1_unregistered_policy_blocks_promote | POLICY_NOT_REGISTERED |
| G2 Unfrozen policy → PROMOTE impossible | MACHINE_CHECKABLE | test_g2_unfrozen_policy_blocks_promote | POLICY_NOT_FROZEN |
| G3 Run-policy mismatch → PROMOTE impossible | MACHINE_CHECKABLE | test_g3_run_policy_mismatch_blocks_promote | RUN_POLICY_MISMATCH |
| G4 Incomplete provenance → PROMOTE impossible | MACHINE_CHECKABLE | test_g4_missing_provenance_flag_blocks_promote / test_g4_missing_provenance_list_blocks_promote | PROVENANCE_INCOMPLETE（missing 列出缺失项） |
| G5 Historical evidence immutable | MACHINE_CHECKABLE | test_g5_evidence_content_change_detected / test_g5_artifact_hash_change_detected / test_g5_manifest_change_detected | EVIDENCE_TAMPERED / ARTIFACT_HASH_CHANGED / MANIFEST_TAMPERED |
| G6 HOLD retry → new EvaluationRun | MACHINE_CHECKABLE | test_g6_hold_reentry_without_new_run_rejected / test_g6_hold_reentry_with_new_run_passes / test_g6_hold_reentry_reusing_run_rejected | HOLD_REENTRY_WITHOUT_NEW_RUN / RUN_REUSE_AFTER_HOLD |
| G7 Historical evidence never overwritten | MACHINE_CHECKABLE | test_g7_new_run_does_not_modify_old / test_g7_duplicate_run_overwrite_detected / test_g7_duplicate_decision_overwrite_detected | EVALUATIONRUN_OVERWRITTEN / DECISION_OVERWRITTEN |

G5 的边界（明确区分，不是把 Git 机制当协议语义）：

```text
FACT      validator 检测“快照内篡改”：recorded_hash != current_hash。
INFERENCE Git 是记录 hash 的锚点之一，但 validator 不证明 Git immutable。
UNKNOWN   recorded hash 的信任锚点形态（写一次存储 / 签名 / git commit）
          未实现；本阶段只定义协议要求：完成时必须记录 hash。
```

## 3. 最小 Conceptual Contract

11 个 contract 已定义（62 §3 表格，validator 中 `CONTRACTS` 表）：

```text
Candidate / EvaluationRun / Attempt / Evidence / Outcome /
RegressionFinding / Attribution / PromotionPolicy / PromotionGate /
Decision / Provenance
```

每个 contract 只声明 required invariants、optional extension points、
forbidden states；没有大规模字段 schema（INFERENCE：字段 schema 属于
落地层，不属于协议验证层）。

## 4. Core / Extension 隔离验证

两个消费者场景均通过（FACT）：

```text
Consumer A = LLM Judge（llm_judge）
  - confidence / judge findings 放在 extensions.llm_judge.fields
  - Core 验证不读这些字段，不因缺少它们失败
  - test_judge_consumer_extension_stays_local

Consumer B = swe-planner（swe_planner）
  - score / plan_metrics 放在 extensions.swe_planner.fields
  - 没有 confidence、没有 judge findings，Core 验证通过
  - test_planner_consumer_without_judge_fields_passes
```

机械检查项：

```text
FACT  Outcome Contract 的 required_invariants 不包含 confidence / score /
      judge_findings（test_core_does_not_require_confidence_score_or_judge_findings）。
FACT  若有人把 confidence 写进 Core required，validator 报
      CORE_REQUIRES_EXTENSION_FIELD（test_core_requiring_extension_field_is_rejected）。
FACT  extension 块必须声明 applicability + provenance_ref，否则报
      EXTENSION_MISSING_APPLICABILITY / EXTENSION_MISSING_PROVENANCE
      （test_extension_requires_applicability_and_provenance）。
```

分类：

```text
extension schema 是否存在/局部化          -> MACHINE_CHECKABLE（FACT）
extension 字段的业务语义是否正确          -> HUMAN_REVIEW_REQUIRED（INFERENCE）
```

## 5. Forbidden State Matrix

| 状态 | 是否允许 | 检查方式 | 分类 |
| --- | --- | --- | --- |
| PROMOTE without policy | NO | validate_promotion → G1 | MACHINE_CHECKABLE |
| PROMOTE with unfrozen policy | NO | validate_promotion → G2 | MACHINE_CHECKABLE |
| PROMOTE with policy mismatch | NO | validate_promotion → G3 | MACHINE_CHECKABLE |
| PROMOTE without provenance | NO | validate_promotion → G4 | MACHINE_CHECKABLE |
| overwrite historical evidence | NO | validate_immutability → G5/G7 | MACHINE_CHECKABLE |
| reuse same EvaluationRun after HOLD | NO | validate_hold_reentry → G6 | MACHINE_CHECKABLE |
| Core requiring confidence | NO | validate_extension_isolation → CORE_REQUIRES_EXTENSION_FIELD | MACHINE_CHECKABLE |
| Consumer-specific field required globally | NO | extension 必须声明 applicability + provenance | PARTIALLY_CHECKABLE（schema 可检查；字段语义人工） |

## 6. 最小状态机验证

验证边（validator 内 `TRANSITIONS`）：

```text
DRAFT -> EVALUATING -> EVALUATED -> REGRESSION_CHECKED
  -> PROMOTION_REVIEW -> PROMOTABLE / HOLD / REJECTED -> PROMOTED
HOLD -> EVALUATING（必须开新 run）
REJECTED / PROMOTED 为终态
```

测试证据（FACT）：

```text
非法转移被拒绝                     test_illegal_transition_rejected（DRAFT->PROMOTED）
HOLD 重入必须新 run                test_g6_hold_reentry_*
REJECTED 终态                      test_rejected_is_terminal（REJECTED->PROMOTED）
没 PROMOTABLE 不能 PROMOTED       test_promoted_requires_promotable
没 policy/provenance 不能 PROMOTABLE
                                   test_promotable_requires_policy_and_provenance
完整合法链通过                     test_valid_core_state_passes
```

## 7. Contract Failure Semantics

validator 区分六类错误（不是所有错误都叫 INVALID_OUTPUT）：

| Code | 触发 | 示例消息 |
| --- | --- | --- |
| CONTRACT_VIOLATION | 结构引用错误、gate 未过、G6 重入违例 | RUN_REUSE_AFTER_HOLD / PROMOTE_WITHOUT_GATE_PASS |
| GOVERNANCE_BLOCK | G1–G3，或 PROMOTABLE 前置缺失 | POLICY_NOT_REGISTERED / RUN_POLICY_MISMATCH / PROMOTABLE_WITHOUT_GOVERNANCE |
| PROVENANCE_INCOMPLETE | G4 任一 provenance 元素缺失 | PROVENANCE_INCOMPLETE decision=... missing=policy_provenance |
| INVALID_TRANSITION | 非法 lifecycle 边 / 终态违例 | ILLEGAL_TRANSITION / REJECTED_IS_TERMINAL |
| IMMUTABILITY_VIOLATION | G5 / G7 内容或历史记录被改 | EVIDENCE_TAMPERED / EVALUATIONRUN_OVERWRITTEN |
| EXTENSION_SCHEMA_ERROR | extension 缺声明，或 Core 要求 extension 字段 | EXTENSION_MISSING_APPLICABILITY / CORE_REQUIRES_EXTENSION_FIELD |

允许 consumer-specific errors，但 Core violation 始终带 Core invariant
标识（G1–G7 / LIFECYCLE / GATE / EXT），可识别（FACT，测试断言 invariant）。

## 8. 事实等级

```text
FACT      G1–G7、状态机、Core/Extension 隔离均可被离线 validator 机械检查
          （29 个测试本次全部通过）。
FACT      Core 不要求 confidence / score / judge findings。
INFERENCE 协议形态 = Core + Extension + Governance Invariants 成立；
          extension 的业务语义属于 consumer，validator 只检查声明。
UNKNOWN   production runtime 是否强制执行这些检查（本阶段未接 runtime）；
          recorded hash 的信任锚点；REJECT hard-blocker 判定清单；
          extension 字段的业务语义正确性。
```

“某 invariant 可以被实现检查”标注 FACT 的唯一依据是本阶段实际运行
的测试证据；没有 production 实现，因此不标 FACT。

## 9. 最终判定

```text
CONTRACT_VALID_WITH_EXTENSIONS
```

理由：

```text
1. Core invariants（G1–G7）与 lifecycle 都能被离线 validator 机械验证
   （FACT，29 passed）。
2. Core / Extension 隔离被机械验证：缺少 confidence 或 judge findings
   不使 Core 失败；extension 必须显式声明 applicability + provenance
   （FACT）。
3. 协议按 Phase 7.1 设计本身就包含 consumer-specific extension 点，
   因此不能宣称“不需要 extension contract”——符合
   CONTRACT_VALID_WITH_EXTENSIONS 的定义。
```

不是 CONTRACT_VALID：extension 是协议正式组成部分，需要显式 extension
contract。
不是 CONTRACT_PARTIAL：Core invariant 没有停留在人工审计层面。
不是 CONTRACT_INVALID：未发现无法绕过的语义冲突。

## 10. Git 边界

未 commit、未 push、未 `git add .`。交付时输出 `git status --short` /
`git diff --stat` / `git diff --name-only`（见最终交付消息），确保没有混入
`codex/`、`control-plane/`、`openhands/`、`48*`、`51*`、`52*`、`53*`。

STOP：不建 schema / API / DB / Kubernetes / service；不做 E.8；
不做 production promotion；不修改 Phase 6-E 或 Phase 7 second-consumer
artifacts。
