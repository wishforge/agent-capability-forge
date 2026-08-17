# 65 — Phase 7.3 Enforcement Contract Fix（7.3.1）

> 阶段：Phase 7.3.1（Enforcement Contract Bug Fix；offline only）。
> 基线：64（Phase 7.3）、63（Phase 7.2）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 已冻结
> artifacts；未进入真实 Runtime；未接 Registry；未接 Langfuse API；未做
> production enforcement；未做 E.8；未 commit / push。

## 1. P2 Bug #1：Decision 没有绑定 Candidate

`validate_adoption_contract()` 通过 `decision_id` 找到 PromotionDecision
后，只检查了 `candidate_version`，没有验证：

```text
adoption.candidate_id == decision.candidate_id
adoption.candidate_id == run.candidate_id
```

因此 Decision(cand-2, v1) 可以授权 Adoption(cand-1, v1)，只要 version
相同即被放行。

## 2. P2 Bug #2：Adoption 没有经过 PROMOTABLE -> PROMOTED

旧 lifecycle 检查只拦截：

```text
HOLD / REJECTED
```

DRAFT / EVALUATING / EVALUATED / REGRESSION_CHECKED /
PROMOTION_REVIEW 仍可被 adoption；lifecycle 缺失时也默认放行。
旧实现还允许 status == PROMOTED 且存在 PROMOTABLE->PROMOTED transition
的 snapshot 直接视为已采用，混淆了“PROMOTE 决策”与“PROMOTED 采用”。

## 3. P3：Bypass #2 的 FACT / INFERENCE / UNKNOWN 标注

64 号报告 Bypass #2 原先把“Langfuse API 可直接建 active prompt”标为
FACT，且标注区写“本表无需 INFERENCE；全部可代码验证”，不成立。已拆分：

```text
FACT      repo 代码只发送 isActive=False 的调用；
          discover / docker 路径存在。
INFERENCE 基于 API payload shape 推断可能存在直接 active 的路径。
UNKNOWN   Langfuse 服务端是否允许外部直接创建 active prompt。
```

## 4. 修复前的错误放行路径

```text
Adoption(cand-1, v1, dec-1)
  -> decision dec-1 的 candidate_id = cand-2（未检查）
  -> candidate_version v1 一致（通过）
  -> decision.value == PROMOTE（通过）
  -> lifecycle 无记录 / DRAFT / EVALUATING / PROMOTION_REVIEW（未拦截）
  -> ADOPTION_ALLOWED（错误）
```

## 5. 修复后的 invariant

Adoption 放行前必须同时满足：

```text
1. decision.status == PROMOTE（snapshot 字段 value）
2. lifecycle.status == PROMOTABLE
3. lifecycle 中明确存在 PROMOTABLE -> PROMOTED transition
4. adoption 是该 transition 的触发（离线形态：记录存在且状态为
   PROMOTABLE，禁止 status == PROMOTED 直接放行）
5. adoption.candidate_id == decision.candidate_id == run.candidate_id
6. adoption.candidate_version == decision.candidate_version
   == run.candidate_version == candidate.version
7. decision 引用的 run 存在（RUN_MISSING）
8. policy_version / provenance / G5 未篡改 / stale 检查保持原有要求
```

任一不满足 -> `ADOPTION_BLOCKED` + 具体原因码；lifecycle 缺失 ->
`MISSING_LIFECYCLE`，禁止“没有 lifecycle 就默认允许”。

新增 / 调整的原因码（全部为 ADOPTION_BLOCKED）：

```text
CANDIDATE_ID_MISMATCH
RUN_MISSING
MISSING_LIFECYCLE
INVALID_ADOPTION_LIFECYCLE
```

删除旧码：`ADOPTION_FROM_HOLD`、`ADOPTION_FROM_REJECTED`、
`PROMOTED_WITHOUT_PROMOTABLE`（统一由 INVALID_ADOPTION_LIFECYCLE 表达，
message 中带具体 status / 缺失 transition）。

## 6. 新增测试

`phase7.3/test_enforcement_contract.py` 在原有 16 项之上新增：

```text
A test_a_decision_candidate_id_mismatch_blocks_adoption
B test_b_decision_run_candidate_id_mismatch_blocks_adoption
C test_c_lifecycle_draft_blocks_adoption
D test_d_lifecycle_evaluating_blocks_adoption
E test_e_lifecycle_promotion_review_blocks_adoption
F test_f_missing_lifecycle_blocks_adoption
G test_g_promotable_valid_transition_allows_adoption
H test_h_promote_invalid_transition_blocks_adoption
I test_i_all_bindings_consistent_allows_adoption
（额外）test_missing_run_blocks_adoption
```

每个 blocked 测试同时断言 `adoptions_allowed == false` 与具体
invariant code；允许测试断言 `adoptions_allowed == true` 与
`violations == []`。合法路径要求 lifecycle.status == PROMOTABLE 且
存在 PROMOTABLE->PROMOTED transition。

## 7. 验证结果

```text
pytest docs/archaeology/unified-runtime/phase7.3 -q
  -> 26 passed（含 doc consistency）
py_compile phase7.3/*.py
  -> COMPILE_OK
compileall -q phase7.3
  -> COMPILE_OK
documentation consistency
  -> PASS（64 号报告列出全部 ADOPTION_BLOCKED codes）
```

adversarial mutation 覆盖（A-I + RUN_MISSING）全部保持非法状态
`ADOPTION_BLOCKED`，合法路径（PROMOTABLE + valid transition + 全绑定
一致）`adoptions_allowed == true`。

## 8. 为什么总体 Gate 仍为 ENFORCEMENT_BOUNDARY_PARTIAL

本次修复只提升 offline enforcement contract 的正确性：

```text
FACT  offline enforcement contract 可机械检查且本次测试通过。
FACT  Evaluation 侧 policy enforcement 存在（E.7 runner）。
FACT  Runtime / Registry 层 adoption guard 仍不存在。
FACT  仍然存在 production bypass（bypass 1-11）。
UNKNOWN  真实 production enforcement（未接入，无法观察）。
```

因此不自动升级为 ENFORCEMENT_BOUNDARY_VALID，总体 Gate 维持：

```text
ENFORCEMENT_BOUNDARY_PARTIAL
```

## 9. FACT / INFERENCE / UNKNOWN 说明

```text
FACT     仓库代码 / 已归档审计直接可见（repo 只发 isActive=False；
         discover / docker 路径存在；无 adoption guard）。
INFERENCE 由 FACT 推导（基于 API payload shape 推断可能存在直接
          active 的路径）。
UNKNOWN   Langfuse 服务端是否允许外部直接创建 active prompt；
          真实 Runtime 是否另有外部保护。
```

STOP：不 commit、不 push、不进入真实 Runtime、不写 production
AdoptionGuard、不做 E.8。
