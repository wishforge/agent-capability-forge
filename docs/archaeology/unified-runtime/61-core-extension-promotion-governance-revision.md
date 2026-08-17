# 61 — Core / Extension / Promotion Governance Revision（Phase 7.1）

> 阶段：Phase 7.1（协议语义修订，非实现阶段）。
> 基线：57（Phase 7 synthesis）、58（第二消费者验证计划）、
> 59（Generic vs Consumer-specific matrix）、60（第二消费者验证报告，
> PARTIAL_REUSE）。
> 约束遵守：未修改 E.5–E.7.1 结论、代码或 artifacts；未修改 48/51/52/53；
> 未新增第三个 consumer；未做 universal schema / API / DB / Kubernetes /
> production runtime integration / E.8 / production promotion；未运行 live
> provider；未 commit / push。

## 标注约定

```text
FACT      —— 两个消费者中的至少一个提供机器可读证据（引用 54-56a / s7 /
            phase7 artifacts）
INFERENCE —— 从 FACT 推导的设计判断
UNKNOWN   —— 当前证据无法确定，禁止猜测

Core 升级规则：
  CORE + FACT       = 两个消费者都已验证（如 59 的 REUSE_CONFIRMED）
  CORE + INFERENCE  = 协议要求的推导结论（仅第一消费者支持 ≠ FACT）
  UNKNOWN           = 未验证，不升级、不降级、不写死
```

---

## 1. Phase 7 Findings

Phase 7 第二消费者（swe-planner plan-writer / control-plane-loop S7.3）
离线 replay 的最终判定是 **GATE = PARTIAL_REUSE**（FACT，60 §6）。

已验证（FACT，60 §3/§6）：

```text
- Candidate / EvaluationRun / Evidence / RegressionFinding / Attribution /
  PromotionGate / Decision 的核心语义可跨消费者复用。
- repeat replay 成功；regression / attribution 可运行。
- BASELINE_INSTABILITY / PROVIDER_NONDETERMINISM / INSUFFICIENT_EVIDENCE
  可以作为通用归因类型。
- 第二消费者不需要复制 CAL-26 / B-prime / Model_Studio 专属逻辑。
- Outcome.confidence 在第二消费者没有对应事实，不能继续作为 Core 必填字段。
- 原 S7.3 没有预注册 PromotionPolicy，因此只能形成 Evaluation evidence，
  不能形成完整 Promotion evidence；protocol-level PROMOTE 不可达。
- S7.3 中 PROMOTE 不可达是治理正确行为，不是实现缺陷。
```

由此得出本阶段结论（INFERENCE）：

```text
协议正式形态 = Core Protocol + Consumer Extensions + Mandatory Governance
Invariants，而不是“一个适用于所有 Agent 的巨大统一 Schema”。
```

## 2. Core Protocol Revision

### 2.1 Core

Core 只保留第二消费者已经证明可以复用的语义（FACT，60 §6；
逐字段复核见 §5）：

```text
Candidate
EvaluationRun
Attempt
Evidence
Outcome
RegressionFinding
Attribution
PromotionPolicy
PromotionGate
Decision
PolicyVersion
ArtifactManifest
Provenance
```

每个对象在 §5 重新检查“是否真的跨两个 consumer 成立”。检查结果：
对象集合本身全部保留为 Core（FACT，两消费者验证）；但对象内若干字段
降级为 OPTIONAL_EXTENSION 或标记为 CONSUMER_SPECIFIC / UNKNOWN。

### 2.2 Extension

consumer-specific semantics 必须进入 extension，不得自动升级为 Core：

```text
- Outcome.confidence（Judge consumer 可提供；swe-planner 无此事实）
- Outcome.score（swe-planner 有连续 score；第一消费者无连续 score）
- CANDIDATE_REGRESSION 的具体判定标准（verdict flip / score delta /
  rate delta / confidence interval / other metric）
- INVALID_OUTPUT 等 outcome 标签（contract-reject 语义是 Core，标签是
  consumer 实例）
- 固定条件值（Model_Studio / qwen3.7-plus vs DeepSeek / deepseek-v4-flash）
- 阈值与实验结构（Wilson / 8-of-10 / -0.1 / CI 0.5 / 44-case matrix）
- CAL-26 / B-prime 等第一消费者实例命名
```

extension 的合法条件：必须声明 applicability（哪个 consumer、什么事实
结构）和 provenance（规则/值来自哪个 policy 版本或 artifacts）。

## 3. Extension Model

Core 是跨 consumer 的强制最小集；Extension 是 consumer 在 Core 之上声明
的补充语义。二者关系：

```text
Core：对象身份、不可变证据、三层 outcome 语义、配对回归、四类归因
     分类集、三态 Gate、governance invariants（§6）。
Extension：Core 不要求、但 consumer 事实结构需要的字段与规则。
```

约束（INFERENCE）：

```text
1. Core 不允许要求 consumer 提供其不存在的事实。
2. Extension 必须明确 applicability 与 provenance。
3. 第一消费者使用过 ≠ Core；只有第二消费者验证通过才可标 CORE + FACT。
4. 无法判断的语义保持 UNKNOWN，不猜。
```

## 4. Outcome.confidence Revision

`Outcome.confidence` 从 Core requirement 降级为
**optional / consumer-specific extension**。

```text
FACT        Judge consumer 可以提供 confidence（E.5 用低置信 PASS 判契约，
            54）。
FACT        swe-planner 的 judge 只输出 score + reasoning，没有 confidence
            （60 §4；s7/03）。
INFERENCE   Core protocol 不允许要求 consumer 提供不存在的事实；因此
            confidence 不能是 Core 必填字段。
INFERENCE   若 consumer 提供 confidence，必须以 extension 形式声明
            applicability（什么对象、什么语义）与 provenance（来自哪个
            judge / policy 版本）。
```

对称发现：`Outcome.score` 同样不是跨 consumer 事实（第二消费者有连续
score，第一消费者只有 verdict），因此标记为 OPTIONAL_EXTENSION，而不是
Core 必填字段。

## 5. Field-level Classification（57 §4 的 13 个对象）

分类取值：

```text
CORE               —— 两个消费者都验证成立，或协议治理推导要求
OPTIONAL_EXTENSION —— consumer 可选提供；Core 不要求
CONSUMER_SPECIFIC  —— 仅属于某个 consumer 的实例/值/标签，不进入协议
UNKNOWN            —— 当前证据无法确定
```

### 5.1 Candidate

```text
CORE               candidate_id
CORE               baseline_ref（语义；第二消费者为隐式 baseline 对象，
                    显式字段未实现属落地缺口）
CORE               change_ref / change_type
CORE               artifact hashes（prompt/skill/config）
CORE               dataset_id + dataset_version
CORE               fixed conditions
CORE               git_commit（G4 provenance 前提；第二消费者未显式记录）
CORE               status
```

### 5.2 EvaluationRun

```text
CORE               run_id（run-<id>/ 唯一，FACT）
CORE               candidate_id
CORE               dataset/task-set ref + version
CORE               arms
CORE               rounds + arm order（字段本身）
UNKNOWN            arm-order 交替是否必须（59；第二消费者未记录）
CORE               replacement policy
CORE               fixed conditions
CORE               policy_ref（G3 要求；第二消费者未实现属落地缺口）
CORE               evidence refs / matrix / stats refs
```

### 5.3 Attempt

```text
CORE               attempt_id / run_id / case_id / arm / round / attempt_seq
CORE               prompt_id + prompt_hash
CORE               provider/model/params（值是 consumer 实例：
                    Model_Studio/qwen3.7-plus vs deepseek-v4-flash）
CORE               raw_response / raw_content / parsed / contract
CORE               failure_kind（分类语义；具体标签 consumer-specific）
CORE               timestamp / artifact path
```

### 5.4 Evidence

```text
CORE               evidence_id / run_id / case_id / arm
CORE               prompt hash / fixed conditions
CORE               raw / parsed / contract / outcome
CORE               failure_kind
CORE               timestamp / artifact path
CORE               policy_ref（追溯要求；第二消费者未实现属落地缺口）
```

### 5.5 Outcome

```text
CORE               outcome_id / attempt / round ref
CORE               status（ACCEPT / REJECT）
CORE               verdict（PASS / FAIL / INCONCLUSIVE 语义）
OPTIONAL_EXTENSION confidence（本阶段降级，见 §4）
OPTIONAL_EXTENSION score（第二消费者事实；第一消费者无）
CORE               error_kind 的 contract vs transport 分离语义
CONSUMER_SPECIFIC  error_kind 具体标签（INVALID_OUTPUT / JUDGE_* / TIMEOUT…）
CORE               coding_scheme_version
```

### 5.6 RegressionFinding

```text
CORE               finding_id / case_id
CORE               baseline outcomes / candidate outcomes
CORE               delta（字段）；delta 形态（verdict flip vs score delta）
                    由 consumer policy 定义
CORE               change class 语义（UNCHANGED / IMPROVEMENT / REGRESSION /
                    UNCLASSIFIED）；具体分类规则 consumer-specific
CORE               evidence refs
CORE               classification_scheme_version
```

### 5.7 Attribution

```text
CORE               attribution_id / case_id / anomaly 描述
CORE               evidence set refs（fresh + historical）
CORE               decision 四类分类集（CANDIDATE_REGRESSION /
                    PROVIDER_NONDETERMINISM / BASELINE_INSTABILITY /
                    INSUFFICIENT_EVIDENCE）
OPTIONAL_EXTENSION CANDIDATE_REGRESSION 判定标准（见 §9）
CORE               policy_ref（判定规则必须预注册）
```

### 5.8 PromotionPolicy

```text
CORE               policy_id / policy_version
CORE               pre_registration_ref（G1 / G2）
CORE               scope（字段）；44-case / 24-case 分层值是 consumer 实例
CORE               fixed conditions / sample sizes / replacement policy
                    （值 consumer-specific）
CORE               outcome coding
CORE               success definitions（target/success 值 consumer-specific）
CORE               statistical method（Wilson / median + repeat std 都是值）
CORE               rate rules（阈值值 consumer-specific）
CORE               transport bounds（值 consumer-specific）
CORE               decision semantics
CORE               precondition（E.6 REGRESSION_SAFETY_CONFIRMED 是
                    第一消费者实例）
```

### 5.9 PromotionGate

```text
CORE               gate_id / policy_ref
CORE               evidence refs（runs / matrix / stats）
CORE               precondition status
CORE               rule results / sample sufficiency / transport bound status
CORE               blockers
CORE               decision
```

### 5.10 Decision

```text
CORE               decision_id / type / value
CORE               policy_ref / evidence_refs / reason / created_at / artifact ref
```

### 5.11 PolicyVersion

```text
CORE               version_id / policy_id / revision kind（registered / final）
CORE               content_hash / commit_ref / diff / created_at
UNKNOWN            该对象在第二消费者上的实现形态（59；原实验无 policy 文件）
```

### 5.12 ArtifactManifest

```text
CORE               manifest_id / policy refs / experiment refs
CORE               artifact 列表 + hashes / git commits / audit_revision / created_at
UNKNOWN            第二消费者侧的 manifest 实现形态（原实验无 manifest）
```

### 5.13 Provenance

```text
CORE               provenance_id
CORE               registered policy bytes + hash + commit
CORE               evidence refs + hashes / fixed conditions
CORE               final policy diff / audit trail
CORE               recompute 命令与结果
```

### 5.14 重点检查项结论

```text
Judge-specific confidence        -> OPTIONAL_EXTENSION（§4）
CAL-26 / B-prime                 -> CONSUMER_SPECIFIC（实例，不进入 Core）
INVALID_OUTPUT                   -> CONSUMER_SPECIFIC 标签；contract-reject
                                    语义为 CORE
Model_Studio / qwen3.7-plus      -> CONSUMER_SPECIFIC 固定条件值
Wilson threshold / 8-of-10 /
  -0.1 / CI 0.5                  -> CONSUMER_SPECIFIC policy 值
44-case / 24-case matrix         -> CONSUMER_SPECIFIC 实验结构
judge-only status semantics      -> CONSUMER_SPECIFIC 标签与契约规则；
                                    三层 outcome 语义为 CORE
arm-order 交替                   -> UNKNOWN
Registered/Final PolicyVersion +
  Manifest 在第二消费者的形态    -> UNKNOWN
```

## 6. Promotion Governance Invariants

以下为不可绕过的 Core governance semantics：

```text
G1  No registered policy                 -> PROMOTE impossible
G2  Unfrozen policy                      -> PROMOTE impossible
G3  Run-policy mismatch                  -> PROMOTE impossible
G4  Incomplete provenance                -> PROMOTE impossible
G5  Historical evidence immutable
G6  HOLD retry 必须建立新的 EvaluationRun
G7  Historical evidence 不允许覆盖
```

依据：

```text
FACT        G5 / G7：E.7.1 恢复审计证明历史 evidence 逐字节恢复、
            禁止覆盖（57 §11）。
FACT        G6：HOLD 以同一 policy 开新 EvaluationRun 是 56 §11 的做法
            （57 §11）。
INFERENCE   G1–G4：由 60 §3.D / §5 的 governance 缺失事实推导；
            第二消费者原实验因缺 policy 而 PROMOTE 不可达。
```

PROMOTE 的必要条件（全部满足才可达）：

```text
1. PromotionPolicy 已注册
2. Policy 已 frozen
3. EvaluationRun 明确绑定该 policy version
4. Evidence 可追溯到该 run + policy
5. Gate rules 全部通过
6. Provenance 完整
7. 没有 unresolved evidence blocker
```

缺少任一条件时 PROMOTE 不可达；允许的终态是 HOLD 或 REJECT。没有 policy
本身不能自动等价为 candidate 质量 REJECT（见 §8）。

## 7. Updated Lifecycle / State Machine

保留主体状态机（57 §13）：

```text
DRAFT
→ EVALUATING
→ EVALUATED
→ REGRESSION_CHECKED
→ PROMOTION_REVIEW
→ PROMOTABLE / HOLD / REJECTED
→ PROMOTED
```

在 PROMOTION_REVIEW 明确增加 governance prerequisites：

```text
policy_registered
policy_frozen
run_policy_match
provenance_complete
```

转移规则修订：

```text
PROMOTION_REVIEW -> PROMOTABLE：
  governance prerequisites 全部满足 + 全部 promotion rules 通过。

PROMOTION_REVIEW -> HOLD：
  没有 confirmed candidate blocker，但至少一个 evidence / stability /
  governance prerequisite 不满足（默认分支；包括缺 policy）。

PROMOTION_REVIEW -> REJECTED：
  存在明确 hard blocker（confirmed candidate regression、evidence
  integrity 失败、policy 被事后修改、明确 governance policy 要求 REJECT）。

HOLD -> EVALUATING：
  candidate 可用同一 policy 重新开新 EvaluationRun；历史 evidence
  不覆盖、不删除（G5 / G6 / G7）。
```

## 8. Updated Gate Semantics

```text
PROMOTE：
  effectiveness evidence
  + regression safety
  + governance prerequisites（policy_registered / policy_frozen /
    run_policy_match / provenance_complete）
  + provenance completeness
  + all promotion rules pass

HOLD：
  没有 confirmed candidate blocker，
  但至少一个 evidence / stability / governance prerequisite 不满足。

REJECT：
  存在明确 blocker（confirmed regression、evidence integrity 失败、
  policy 被事后修改等）。
```

特别明确：

```text
No policy -> HOLD / PROMOTE impossible
No policy -> 不自动 REJECT candidate
```

除非另有明确 governance policy 明确要求 REJECT。这一区分保留
“候选没有做坏事”与“候选被证明不合格”的不同语义（INFERENCE，来自
60 §3.D：bad_v1 机械 PASS 因 governance 缺失落 HOLD，而不是 REJECT）。

## 9. Attribution Extension Model

Attribution 设计为：

```text
AttributionType（Core）
+ AttributionPolicy / Consumer Extension（判定标准）
```

Core 只规定：

```text
必须有明确的归因规则和证据。
```

`CANDIDATE_REGRESSION` 的具体 criteria 由 consumer policy 定义，例如：

```text
- verdict flip（第一消费者：per-case verdict 100% 翻转）
- score delta（第二消费者：稳定负 delta）
- rate delta
- confidence interval
- other metric
```

不得强迫连续 score consumer 使用 verdict-level 100% flip（FACT，60 §3.C：
第二消费者无 per-case 二值 verdict，该规则 not applicable）。consumer 没有
足够证据时，Attribution = `UNKNOWN` / `INSUFFICIENT_EVIDENCE`，禁止为套
模型强行归因（FACT，60 §3.C）。

## 10. S7.3 Lessons

```text
FACT  S7.3：
  - repeat replay 成功
  - regression / attribution 可运行
  - 没有 pre-registered PromotionPolicy
  - 因此只能形成 Evaluation evidence
  - 不能形成完整 Promotion evidence
  - protocol-level PROMOTE 不可达
```

不要把 S7.3 重新改成 PROMOTE：原实验缺 governance 前提（G1 / G4）是
消费者侧落地缺口，不是协议缺陷；缺 policy 是 HOLD 的 governance 原因，
不是 candidate 质量 REJECT 的证据（60 §5.1；本文件 §8）。

## 11. Compatibility Impact

对已有文档与 artifacts 的影响（全部离线）：

```text
1. 57 §4.5 的 Outcome.confidence 不再作为 Core 必填字段；本文件 §4/§5.5
   取代该要求。
2. 57 §9 / §13 增加 governance prerequisites（本文件 §6–§8）；PROMOTE
   语义变严，HOLD 默认分支不变。
3. 59 / 60 的分类结论保留；本文件把它们正式化为 Core + Extension +
   Governance Invariants。
4. Phase 6-E artifacts（E.5–E.7.1、48/51/52/53）不改动。
5. 第二消费者原 S7.3 实验保持 Evaluation evidence 状态，不追溯 PROMOTE。
6. 未来 consumer 必须满足 Core 对象与 G1–G7；extension 必须声明
   applicability + provenance，才能被审计。
7. 不引入 universal schema：对象模型仍是语义契约，不是统一序列化格式。
```

## 12. Non-goals

本阶段明确不做：

```text
1. 第三个 consumer
2. universal schema implementation
3. API
4. DB
5. Kubernetes
6. production runtime integration
7. live provider experiment
8. E.8
9. production promotion
10. 修改 E.5–E.7.1
11. 修改历史 promotion artifacts
12. 把 S7.3 改成 PROMOTE
```

## 13. Open Questions

以下均为 UNKNOWN / 未验证：

```text
1. Registered / Final PolicyVersion 与 ArtifactManifest 在第二消费者上的
   实现形态（原实验无 policy 文件、无 manifest）。
2. arm-order 交替对配对重放是否必要。
3. 连续 score consumer 的统计归因阈值（score delta / CI）如何预注册与
   校准。
4. Outcome.confidence 是否会在第三个 consumer 出现并重新获得通用性。
5. governance 证据的最低形态（git bytes 是否足够，是否需要签名 / 时间戳）。
6. “明确 hard blocker”的判定清单（REJECT 触发集）是否可跨 consumer 通用。
7. HOLD 重入后 gate 应消费 fresh evidence 还是全证据集（57 §16.3 保留）。
```

STOP：本阶段不 commit、不 push、不运行 live provider、不做 E.8、
不做 production promotion。
