# 57 — Evaluation / Promotion Control Plane Synthesis（Phase 7）

> 阶段：Phase 7（架构抽象，非实验阶段）。
> 冻结基线：`ca06a9a`（E.7 pre-register promotion evidence policy）、
> `22890c1`（E.7 experiment, GATE = HOLD）、`f0ae41f`（E.7.1 policy
> provenance finalization）。
> 约束遵守：未修改 E.5 / E.6 / E.7 / E.7.1 的任何结论、代码或 artifacts；
> 未修改 candidate prompt / parser / contract / retry / production runtime；
> 未运行 live provider；未做 E.8；未做 production promotion；未 commit /
> push。
>
> 证据来源：
> - Phase 6-E 报告：`46-phase6e-cross-backend-robustness-design.md`、
>   `47-phase6e-cross-backend-robustness-report.md`、`48`~`53`（E.1–E.4）、
>   `54-phase6e5-prompt-candidate-evaluation.md`（E.5）、
>   `55-phase6e6-regression-attribution.md`（E.6）、
>   `56-phase6e7-promotion-evidence-gate.md`（E.7）、
>   `56-phase6e7a-audit-fix.md`（E.7.1）；
> - Phase 6-E artifacts：`candidate-eval/`、`regression-attribution/`、
>   `promotion-gate/`（policy registered/final、manifest、runs、matrix、
>   stats、gate）；
> - Phase 5 契约：`04`/`05`/`06`（ExecutionRecord / EvaluationInput /
>   Evaluation boundary）、`23`–`28`（Regression / Promotion contract）、
>   `29`–`31`（Control Plane Proof）；
> - 生态 synthesis：`codex/99-synthesis.md`、`deepseek-harness/99-synthesis.md`、
>   `control-plane/99-synthesis.md`、`control-plane/s7/99-synthesis.md`。

## 标注约定

本文件给每条结论打三类标签，禁止把设计推测写成实验事实：

```text
FACT      —— Phase 6-E 实验 / 审计 / 契约测试已证明（可在 46-56a 或
            artifacts 中找到机器可读证据）
INFERENCE —— 本文件从 FACT 推导出的通用架构结论（设计判断）
UNKNOWN   —— 未被 Phase 6-E 覆盖、未验证、或明确留给未来的问题
```

另用“实验专属”/“通用机制”区分：CAL-26、TASK-JUDGE-01、B-prime、8/10 这类
阈值是实验专属值；它们背后的对象、协议与不可变规则才是可复用机制。

---

## 1. Executive Summary

**回答：Phase 6-E 沉淀的不是“某个候选修复了某个 case”，而是一条可复用的
Agent Evaluation / Promotion Control Plane 协议。**

Phase 6-E 真正证明可通用的机制（FACT，来自 E.5–E.7.1 报告与 artifacts）：

```text
1. 预注册策略：决策规则必须在 live 实验前写入并冻结，runner 在 policy
   缺失或与 frozen policy 不一致时拒绝运行（E.7）。
2. 固定条件配对重放：baseline / candidate 在相同 dataset / provider /
   model / 参数 / parser / contract 下按轮配对；arm 顺序交替控制时间漂移
   （E.5 / E.6 / E.7）。
3. 失败也是证据：transport（TIMEOUT / UNAVAILABLE）与 contract
   （INVALID_OUTPUT）失败全部保留为独立 attempt 记录，不静默丢弃
   （E.5–E.7；142 条 attempt rows）。
4. 三层 outcome 编码：ACCEPT（PASS/FAIL/INCONCLUSIVE）≠ INVALID_OUTPUT
   ≠ transport；aggregate 不得掩盖 per-case 差异（E.5–E.7）。
5. 两层回归语义：strict-stability attribution（E.6，100% 稳定才算
   CANDIDATE_REGRESSION）与 rate-level stability（E.7，率差与 CI 阈值）
   是两层不同问题，不能混用。
6. 三态 Gate：PROMOTE / HOLD / REJECT；默认保守，HOLD 不是失败而是
   “证据不足以上线”的终态输出（E.5 / E.6 / E.7）。
7. 证据不可变 + 策略分版本：registered policy、final/audited policy、
   experiment evidence 三者分离；审计只允许修正声明/来源，禁止改阈值、
   禁止重写历史证据（E.7.1）。
8. 字节级 provenance：registered policy bytes == `git show <commit>`，
   离线 recompute 产出与 committed gate 逐字节一致（E.7 / E.7.1）。
```

**实验专属值**（不可直接当通用模型）：

```text
CAL-26 作为 target、TASK-JUDGE-01/CAL-08/CAL-18 作为 suspicious cases、
B / B-prime 两个 prompt、qwen3.7-plus / temp=0 / seed=42、
core N=10 / control N=5、8/10、9/10、-0.1 delta、0.5 CI lower 等阈值。
```

这些值只证明了“该实验在该 provider 上的证据强度”，不构成通用阈值库
（INFERENCE；具体阈值的外推能力是 UNKNOWN）。

Phase 6-E 没有证明的（UNKNOWN / 明确不做）：

```text
- 没有证明 B-prime 可以上线（GATE = HOLD，FACT）。
- 没有实现通用版本注册表、canary、生产部署、自动授权、rollback 执行。
- 没有验证阈值在不同 provider / 任务域上可复用。
```

---

## 2. Business Problem

Agent 能力的“改进”不能靠单次分数比较决定（INFERENCE，且被 E.5 证明）：

```text
同一条件（temp=0 / seed=42 / 同 prompt）下，E.5 Run 1 出现 3 个
PASS→INCONCLUSIVE，Run 2 为 0；单轮“0 regression”矩阵不能认证安全
（FACT）。
```

业务上需要回答四个问题，任何一个缺失都会让上线决策不可审计：

```text
Q1. 新版本是否解决了目标问题？        -> Effectiveness Evidence
Q2. 新版本是否把旧能力搞坏了？        -> Safety Evidence
Q3. 当时依据什么规则做出决定？        -> Governance Evidence
Q4. 这些证据是否可复现、可回查？      -> Provenance
```

现有生态考古的结论是：Evaluation 库、trace 平台、优化器都已商品化，但
“eval-gated promotion”在整个开源生态中不存在（`control-plane/99-synthesis.md`
，FACT）。Phase 6-E 第一次在本地把这条断链以可审计方式接起来：不是靠新
平台，而是靠“预注册策略 + 不可变证据 + 三态 Gate + 字节级 provenance”四件
套件（INFERENCE，基于 E.5–E.7.1 的事实）。

---

## 3. Phase 6-E Lessons

### 3.1 逐阶段事实与通用教训

| Phase | 结论（FACT，详见对应报告） | 通用机制 | 实验专属部分 |
| --- | --- | --- | --- |
| E.1 (46–48) | 两层 deterministic 结构：deterministic 层 + LLM 层共用 guard；deterministic 否定结论是终局、肯定结论不是（48） | 契约 guard 是权威边界，不得被模型输出绕过 | TASK-JUDGE-01 的 PASS 语义、semantic fallback 矩阵 |
| E.1.A/1.B (49/49a/50) | fixture 修正（dataset v1→v2）不改变 deterministic layer（49a） | dataset 必须显式版本化，fixture 变更 = 新版本，不覆盖历史 | qty=10/qty=5 的 36/44 case 文本 |
| E.2 (51) | retry 不能修复 CAL-16/CAL-26 这类语义性失败；v2 的 machine-readable provenance 不完整（51） | 失败必须分类（transport vs contract vs semantic），且 provenance 必须机器可读 | CAL-16/CAL-26 的稳定失败 signature |
| E.3 (52) | raw payload capture 落地前，失败样本从 `_create`/`_parse` 开始丢失原始结构（52） | 每个 attempt 必须保留 raw_response + raw_content + parsed + contract，缺一不可 | model_studio 的 raw 结构 |
| E.4 (53) | CAL-26 = SUPPORTED_PROMPT_SENSITIVITY；reasoning 推演 PASS 而 final 输出低置信 PASS 的 divergence 可复现（53） | prompt 差异必须 hash 化，reasoning 与 final 必须分开归档 | B vs B-prime 的一句话措辞差 |
| E.5 (54) | GATE = INSUFFICIENT_EVIDENCE：target 两轮 6/6 修复，但 3 个稳定 PASS 翻转只在 Run 1 出现、Run 2 为 0；矩阵因 TIMEOUT 不完整 | 单轮 0-regression 不能认证“no deterministic regression”；aggregate 不得掩盖 per-case 差异 | CAL-26、7 个 stable PASS、24-case matrix |
| E.6 (55) | TASK-JUDGE-01 = BASELINE_INSTABILITY；CAL-08 / CAL-18 = PROVIDER_NONDETERMINISM；GATE = REGRESSION_SAFETY_CONFIRMED | 归因必须预注册判定顺序 + 全证据集；100% 稳定标准是策略选择，不是结果解释 | 3 个 suspicious cases 的 SYSTEM_PROMPT_SNAPSHOT 弃权机制 |
| E.7 (56) | GATE = HOLD：effectiveness 有（CAL-26 10/10），rate-level stability 不达标（candidate PASS 率 0.1/0.3/0.6 vs baseline 0.9/1.0/1.0） | effectiveness / safety / repeatability / sample / confidence 六个维度分离；预注册 rate rules | 8 case × 10/5 rounds、Wilson 阈值、transport bound |
| E.7.1 (56a) | 恢复审计：registered policy 字节等于 `ca06a9a`；final policy 单独版本化；E.7 evidence 从 `22890c1` 逐字节恢复 | 历史 policy / evidence 不可覆盖；审计修订只允许声明/来源修正 | promotion-policy-e7-v1 的声明性字段 |

### 3.2 最重要的三条教训

```text
FACT-1   REGRESSION_SAFETY_CONFIRMED ≠ PROMOTION_APPROVED。
         E.6 只证明“三个异常 case 没有 candidate-induced regression”，
         E.7 在 E.6 之上补 rate-level 证据后仍 HOLD。

FACT-2   effectiveness 证据存在 + 无 confirmed regression ≠ 可以上线。
         E.7 的 target 修复 10/10，稳定 controls 全过，但 suspicious cases
         的率差使 GATE = HOLD。

FACT-3   证据完整性是 gate 的输入，不是 gate 的装饰。
         E.7.1 记录的前一次 attempt 中，matrix/stats/gate 被重写、manifest
         把编辑后的字节归属到 `ca06a9a`；这类 governance 损坏本身就是
         REJECT 条件（56 §2.5）。
```

---

## 4. Generic Object Model

以下对象是 Phase 6-E 抽象出的通用模型。已有 Phase 5 契约对象
（`ImprovementCandidate` / `RegressionRun` / `PromotionDecision` /
`GateResult`）被复用并映射到新模型，不重新发明（INFERENCE；映射见 4.14）。

### 4.1 Candidate

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 用一个稳定身份表达“改了什么”，使 baseline / candidate 可被重复比较；防止把不可复现的改动当候选 |
| 最小字段 | `candidate_id`、`baseline_ref`（稳定版本）、`change_ref` / `change_type`、artifact hashes（prompt/skill/config）、`dataset_id` + `dataset_version`、fixed conditions、`git_commit`、status |
| 生命周期 | DRAFT → EVALUATING → EVALUATED → REGRESSION_CHECKED → PROMOTION_REVIEW → PROMOTABLE / HOLD / REJECTED → PROMOTED（见 §13） |
| 谁产生 | 改进子系统 / 优化器 / 人工（E.5：B-prime 被定义为 `prompt-b-v2-candidate-1`，带 hash 与 metadata，FACT） |
| 谁消费 | EvaluationRun、Regression、PromotionGate、审计 |
| immutable | 是：身份 + artifact 内容 + fixed conditions 冻结；只有状态转移可变 |
| version | 是：candidate 本身版本化（`prompt-b-v2-candidate-1`），内容用 hash 锚定 |
| 关系 | 1 Candidate → N EvaluationRun；Candidate.baseline_ref 必须等于 Regression 的 baseline_ref（Phase 5-N A2，FACT） |

### 4.2 EvaluationRun

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 把一次受控实验（targeted / regression / promotion evidence）变成一个可归档、可重算的单元 |
| 最小字段 | `run_id`、`candidate_id`、dataset/task-set ref + version、arms（baseline/candidate）、rounds + arm order、replacement policy、fixed conditions、`policy_ref`、evidence refs、matrix/stats refs |
| 生命周期 | 预注册 → 调度 → 执行 → summarize → 归档（E.7：policy 先冻结，runner 后跑，FACT） |
| 谁产生 | evaluation runner（E.5 `--candidate-eval`、E.6 `attribution` replay、E.7 `promotion-gate`） |
| 谁消费 | Regression / Attribution / PromotionGate / 审计 |
| immutable | 是：run 的 evidence 与最终 matrix/stats/gate 在提交后逐字节冻结（E.7.1，FACT） |
| version | 是：`run_id` + artifact 目录（E.5 `run1/` 与 committed matrix 并存，FACT） |
| 关系 | 1 EvaluationRun → N Attempt；E.7 run 引用一个 registered policy |

### 4.3 Attempt

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 保存一次真实 provider 调用的完整原始事实；失败不得静默丢弃 |
| 最小字段 | `attempt_id`、`run_id`、`case_id`、`arm`、`round`、`attempt_seq`、`prompt_id` + `prompt_hash`、provider/model/params、`raw_response`、`raw_content`、`parsed`、`contract`、`failure_kind`、timestamp、artifact path |
| 生命周期 | 调用 → raw 捕获 → parse → contract 检查 → 记录（成功或失败）→ 归档（E.3 capture 落地，FACT） |
| 谁产生 | runner（`_run_probe` / 替换调用） |
| 谁消费 | Evidence row、matrix、attribution、审计 |
| immutable | 是：raw + parsed + contract 一旦写入不修改 |
| version | 否：attempt 是原子事实；引用 prompt / parser / dataset / policy 的版本 |
| 关系 | 属于 EvaluationRun；E.7 的 142 条 attempt 中 22 条是失败后替换调用，全部保留（FACT） |

### 4.4 Evidence

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 提供机器可读的“发生了什么”，使结论可由 bytes 重推，而非依赖报告文本 |
| 最小字段 | `evidence_id`（row id）、`run_id`、`case_id`、`arm`、prompt hash、fixed conditions、raw/parsed/contract/outcome、`failure_kind`、timestamp、artifact path、`policy_ref` |
| 生命周期 | 捕获 → 校验（raw==parsed 字段级比较，E.5 F 节）→ 冻结 → 被 matrix/stats/gate 引用 |
| 谁产生 | runner 的 evidence capture（E.3 基础设施，FACT） |
| 谁消费 | matrix、attribution、promotion gate、审计、离线 recompute |
| immutable | 是（E.7.1：`promotion-runs.jsonl` 从 `22890c1` 逐字节恢复，FACT） |
| version | 否：Evidence 引用版本（prompt/parser/dataset/policy），自身不版本化 |
| 关系 | 1 Evidence 来自 1 Attempt；N Evidence → 1 case-arm 统计 |

### 4.5 Outcome

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 把 attempt 归一化成可聚合的 verdict，并显式区分“有效判定 / 契约无效 / 传输失败”三类结果 |
| 最小字段 | `outcome_id`、attempt/round ref、`status`（ACCEPT / REJECT）、`verdict`（PASS / FAIL / INCONCLUSIVE）、`confidence`、`score`、`error_kind`（INVALID_OUTPUT / TIMEOUT / TRANSIENT / UNAVAILABLE / PERMANENT）、`coding_scheme_version` |
| 生命周期 | 由 parser + contract guard 派生 → 进入 matrix → 被 rate rules 消费（E.7 `outcome_coding`，FACT） |
| 谁产生 | parser / contract 层（deterministic），不是模型自己（E.1 guard 是契约，FACT） |
| 谁消费 | matrix、stats、rate rules、attribution、gate |
| immutable | 是：从 immutable evidence 确定性派生 |
| version | 是：outcome coding 方案版本化（E.7 policy 显式声明，FACT） |
| 关系 | Outcome 附着于 Attempt；`INCONCLUSIVE` 是合法 verdict，`INVALID_OUTPUT` 是契约拒绝，二者不得混淆（E.7 用 n_contract 区分，FACT） |

### 4.6 RegressionFinding

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 记录“某个 case 在 baseline vs candidate 下发生了什么变化”，作为回归检测的原子单元 |
| 最小字段 | `finding_id`、`case_id`、baseline outcomes、candidate outcomes、`delta`（如 PASS→INCONCLUSIVE）、change class（UNCHANGED / IMPROVEMENT / REGRESSION / UNCLASSIFIED）、双方 evidence refs、`classification_scheme_version` |
| 生命周期 | 配对结果比较 → 分类 → 输入 attribution / rate rules |
| 谁产生 | 比较层（E.5 matrix、E.6 paired replay、Phase 5-M `TaskComparison`，FACT） |
| 谁消费 | Attribution、PromotionGate、审计 |
| immutable | 是：由固定 pair 派生 |
| version | 是：分类方案版本化（E.6 strict-stability vs E.7 rate-level 是两套方案，FACT） |
| 关系 | 属于 EvaluationRun；transport 造成的不可比行标 UNCLASSIFIED，不得当 UNCHANGED（E.5，FACT） |

### 4.7 Attribution

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 回答“这个差异为什么发生”，避免用单次抖动给 candidate 定罪或洗白 |
| 最小字段 | `attribution_id`、`case_id`、anomaly 描述、evidence set refs（fresh + historical）、decision（CANDIDATE_REGRESSION / PROVIDER_NONDETERMINISM / BASELINE_INSTABILITY / INSUFFICIENT_EVIDENCE）、`policy_ref` |
| 生命周期 | 预注册判定顺序 → 收集全证据集 → 分类 → 进入 gate（E.6 B 节，FACT） |
| 谁产生 | attribution 子系统（按预注册 policy 机械判定） |
| 谁消费 | Regression gate、PromotionGate、审计 |
| immutable | 是：判定与证据集一起冻结 |
| version | 是：attribution policy 版本化（E.6 的 strict-stable 标准是策略选择，FACT） |
| 关系 | 一个 suspicious RegressionFinding 对应一个 Attribution；E.6 结果作为 E.7 的 precondition（FACT） |

### 4.8 PromotionPolicy

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 让“什么证据、多少样本、什么阈值、什么结论”在实验前成为不可变规则，杜绝事后改阈值 |
| 最小字段 | `policy_id`、`policy_version`、`pre_registration_ref`（commit）、scope（case strata）、fixed conditions、sample sizes、replacement policy、outcome coding、success definitions、statistical method、rate rules、transport bounds、decision semantics、precondition（如 E.6 gate） |
| 生命周期 | draft → registered（冻结）→ 用于 live run → audited final（单独版本）→ 归档（E.7 / E.7.1，FACT） |
| 谁产生 | 控制面 / operator；runner 只消费 |
| 谁消费 | runner（强制执行）、gate（计算）、审计（字节比对） |
| immutable | 是：registered bytes 不可覆盖（E.7.1，FACT） |
| version | 是：`promotion-policy-e7-v1`（registered）与 `promotion-policy-e7-v1-final` 是两个版本对象（FACT） |
| 关系 | 1 PromotionPolicy → N EvaluationRun；被 ArtifactManifest / Provenance 引用 |

### 4.9 PromotionGate

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 把“证据 + 规则”变成唯一的三个输出之一（PROMOTE / HOLD / REJECT），不让分数差直接当结论 |
| 最小字段 | `gate_id`、`policy_ref`、evidence refs（runs/matrix/stats）、precondition status、rule results、sample sufficiency、transport bound status、blockers、decision |
| 生命周期 | 预注册 → 实验后离线计算 → 归档（E.7：`promotion-gate.json` 在 `22890c1` 冻结，FACT） |
| 谁产生 | gate 引擎（`--summarize-promotion-gate`，FACT） |
| 谁消费 | operator、审计、未来实验 |
| immutable | 是：gate.json 是 evidence 的一部分 |
| version | 是：跟随 policy version + artifact version |
| 关系 | 消费 PromotionPolicy + EvaluationRun + Attribution；产出 Decision |

### 4.10 Decision

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 记录一次权威结论（PROMOTE / HOLD / REJECT，或 precondition 如 REGRESSION_SAFETY_CONFIRMED），供下游执行或人工审查 |
| 最小字段 | `decision_id`、type（GATE / PRECONDITION）、value、`policy_ref`、`evidence_refs`、reason、`created_at`、artifact ref |
| 生命周期 | 计算 → 记录 → 冻结 → 被引用 |
| 谁产生 | PromotionGate / attribution gate |
| 谁消费 | 部署层（仅 PROMOTE）、人工、审计 |
| immutable | 是（Phase 5-N `PromotionDecision` 是 frozen dataclass，FACT） |
| version | 否：Decision 不版本化，引用 policy version |
| 关系 | 每轮 gate 一个 Decision；E.5 = INSUFFICIENT_EVIDENCE、E.6 = REGRESSION_SAFETY_CONFIRMED、E.7 = HOLD（FACT） |

### 4.11 PolicyVersion

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 表达“registered policy”与“final/audited policy”是两个不可混用的版本，审计修订不能改已注册规则 |
| 最小字段 | `version_id`、`policy_id`、revision kind（registered / final）、`content_hash`、`commit_ref`、diff vs 前一 revision、`created_at` |
| 生命周期 | registered（实验用）→ final（审计修订）→ 归档 |
| 谁产生 | 控制面 |
| 谁消费 | runner（registered）、审计 / provenance 检查（final） |
| immutable | 是：两个 revision 都不可变；final 必须证明与 registered 阈值等价（E.7.1，FACT） |
| version | 是：它就是版本对象本身 |
| 关系 | registered + final 成对出现；被 manifest / provenance 引用 |

### 4.12 ArtifactManifest

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 证明“证据集完整、每个文件属于哪个 policy / run / commit”，使完整性可机械校验 |
| 最小字段 | `manifest_id`、policy refs（registered/final）、experiment refs、artifact 列表 + hashes、git commits、`audit_revision`、`created_at` |
| 生命周期 | 实验归档时生成 → 审计时只追加 revision → 冻结 |
| 谁产生 | runner / 控制面 |
| 谁消费 | verification tests、离线 recompute、审计 |
| immutable | 是：evidence 部分冻结；audit revision 单独追加（E.7.1 重建为 manifest-2，FACT） |
| version | 是（`promotion-gate-e7-manifest-2`，FACT） |
| 关系 | 绑定 PolicyVersion + Evidence + matrix/stats/gate 文件 |

### 4.13 Provenance

| 维度 | 说明 |
| --- | --- |
| 业务问题 | 回答“当时依据什么规则、什么输入、什么代码、什么证据做出了决定”，且可以从仓库 bytes 重推 |
| 最小字段 | `provenance_id`、registered policy bytes + hash + commit、experiment evidence refs + hashes、fixed conditions、final policy diff、audit trail、recompute 命令与结果 |
| 生命周期 | Registered Policy → Experiment → Immutable Evidence → Audit Revision → Final Policy（见 §10） |
| 谁产生 | 控制面 |
| 谁消费 | 审计、未来实验、取证 |
| immutable | 是：禁止 retroactively rewrite（E.7.1，FACT） |
| version | 是：绑定 policy / run / manifest 版本 |
| 关系 | Provenance = ArtifactManifest + hashes + audit trail；校验规则为 `registered bytes == git show ca06a9a`（FACT） |

### 4.14 与 Phase 5 既有契约的映射（复用而非重造）

| 新对象 | Phase 5 既有实现 |
| --- | --- |
| Candidate | `ImprovementCandidate` + E.5 `candidate-b-v2-metadata.json` |
| EvaluationRun | `EvaluationResult` + `RegressionRun` + E.5/E.7 的 matrix runner |
| RegressionFinding | `TaskComparison`（regression.py，FACT） |
| Attribution | `FailureAttribution` + E.6 归因 policy |
| PromotionGate / Decision | `decide()` 的 `GateResult` / `PromotionDecision`（promotion.py，FACT） |
| PromotionPolicy / PolicyVersion / Manifest / Provenance | Phase 6-E 新增（Phase 5-N 只有 `policy_ref` 占位，FACT） |

---

## 5. Generic Lifecycle（通用闭环）

```text
Candidate
   ↓
Evaluation（受控配对重放）
   ↓
Evidence（attempt 级原始事实）
   ↓
Outcome（归一化 verdict）
   ↓
Regression Detection（per-case delta）
   ↓
Attribution（为什么）
   ↓
Promotion Evidence（effectiveness + safety + governance）
   ↓
Gate
   ↓
PROMOTE / HOLD / REJECT
   ↓
Provenance（bytes 级可重推）
```

| 步骤 | 输入 | 输出 | Gate | 失败怎么办 | 允许重试 | 必须 immutable |
| --- | --- | --- | --- | --- | --- | --- |
| 1. Candidate | baseline + failure evidence + 变更描述 | Candidate（hash + 稳定 ref） | baseline_ref 稳定、artifact hashes 完整 | 不满足 → 不进入实验 | 可以重新 formulate，但新内容 = 新 candidate 版本 | candidate 身份与内容 |
| 2. Evaluation | Candidate + TaskSet + fixed conditions + registered policy | EvaluationRun + Attempts | runner 在 policy 缺失 / 不一致时拒绝运行（E.7，FACT） | 无 policy → 不执行 | 是：同一 run 内同条件替换（上限见 policy） | 固定条件、policy bytes |
| 3. Evidence | Attempts | Evidence rows | 每行必须含 raw + parsed + contract + artifact | 字段缺失 → 该行不可用，matrix 不完整 | 重跑必须用新 run id | 所有 evidence rows |
| 4. Outcome | Evidence | Outcome（ACCEPT / INVALID_OUTPUT / transport） | 编码方案必须预注册 | 未知编码 → INCONCLUSIVE，不得猜 | 否 | 派生 outcome |
| 5. Regression Detection | 配对 Outcomes | RegressionFindings + matrix | 不可比行（transport）必须显式 UNCLASSIFIED | matrix 不完整 → 不足以认证安全 | 是：新 EvaluationRun | matrix 与 stats |
| 6. Attribution | Findings + 全证据集 + attribution policy | Attribution | 判定顺序预注册（E.6，FACT） | INSUFFICIENT_EVIDENCE → 不归因 | 是：补证据 = 新 run | attribution 结果 |
| 7. Promotion Evidence | effectiveness + safety + governance 三路证据 | 证据包 | 三类证据缺一不可（§6） | governance 损坏 → REJECT（E.7.1） | 否 | 证据包 |
| 8. Gate | Policy + 证据包 | Decision（PROMOTE / HOLD / REJECT） | 按预注册 rules + precondition 机械求值 | rules 不满足 → HOLD / REJECT 按语义 | 否：decision 不可重算覆盖；HOLD 只能开新 run | gate.json、Decision |
| 9. Provenance | Manifest + hashes + commits | Provenance | `registered bytes == git show`；离线 recompute 一致（E.7，FACT） | 不一致 → evidence integrity failure → REJECT | 否 | 全部历史 artifacts |

---

## 6. Evaluation Model

Evaluation = 在固定条件下对 baseline / candidate 做受控测量，产出可归档的
Evidence 与 Outcome。通用语义（全部有 Phase 6-E 事实支撑）：

```text
FACT   EvaluationInput = ExecutionRecord + TaskSpecification + Expected
        Outcome；Expected Outcome 不属于 Runtime（05）。
FACT   完成 ≠ 成功：turn/end completed 只是执行终止证据（04/05）。
FACT   判定链 = deterministic rules + LLM judge + contract guard；
        guard 是契约，不是模型可选的“建议”（48）。
FACT   INCONCLUSIVE 是合法 verdict，不是错误；低置信 PASS 才是契约违规
        （E.5：B 的 9 次 INVALID_OUTPUT 全部是 low-confidence PASS）。
FACT   INVALID_OUTPUT 与 transport 必须分开计数（E.7：n_contract vs
        n_transport）。
```

通用 EvaluationRun 设计规则（INFERENCE）：

```text
1. 每个 run 声明 arms、rounds、arm order、replacement policy；
2. 每个 case 的每个 arm 必须有预注册最小样本数；
3. 失败 attempt 保留，替换调用同条件；
4. matrix 必须逐 case 可审计，禁止只用 aggregate；
5. run 的统计方法（如 Wilson）在 policy 中预注册。
```

---

## 7. Regression Model

Regression = 在同一 TaskSet / 同一控制条件下比较 baseline 与 candidate 的
repeated replay。Phase 6-E 证明了两个层次必须分开：

```text
Level 1 — strict-stability（E.6）：
  只回答“是否存在 100% 稳定的 candidate-induced regression”。
  判定顺序预注册：INSUFFICIENT_EVIDENCE → BASELINE_INSTABILITY →
  CANDIDATE_REGRESSION → PROVIDER_NONDETERMINISM。
  全证据集 = E.5 Run1 + Run2 + E.6 fresh（FACT）。

Level 2 — rate-level（E.7）：
  只回答“candidate 在 rate 意义上是否稳定到可以上线”。
  使用 success rate、Wilson 95% CI、delta 与预注册阈值（FACT）。
```

两者不可互相推导（FACT）：

```text
E.6 = REGRESSION_SAFETY_CONFIRMED 时，E.7 仍因 rate-level 不达标而 HOLD。
```

通用回归机制（INFERENCE）：

```text
1. Replay（只读重建历史 record）与 Re-execution（新 run id）严格分离
   （25，FACT 契约层）。
2. baseline / candidate 共享同一 TaskSet 版本；任务缺失或越界 BLOCK
   （regression.py，FACT）。
3. transport 导致的不可比行 = UNCLASSIFIED，不是 UNCHANGED（E.5，FACT）。
4. critical regression（stable-PASS → FAIL / critical → PASS）优先于任何
   aggregate 改善（Phase 5-M，FACT）。
5. 稳定 controls（已知 PASS / FAIL case）作为环境漂移 sanity check
   （E.7，FACT）。
```

---

## 8. Attribution Model

把 E.6 的判定抽象为通用归因模型：

| Attribution | 什么证据支持 | 什么证据不能支持 | 对 Gate 的含义 |
| --- | --- | --- | --- |
| CANDIDATE_REGRESSION | 全证据集 baseline 100% PASS、candidate 100% 变 INC/FAIL；同条件、无 transport 解释 | 单次翻转、率差（如 6/7 vs 0/7）、candidate 自身摇摆 | 可 REJECT（明确 blocker） |
| PROVIDER_NONDETERMINISM | 同一 arm 在相同条件下出现 PASS/INC 两种结果；异常未复现；baseline/candidate 都出现过该行为 | 全部同 arm 结果都一致的稳定差异 | 不能单独 REJECT；通常 HOLD 或进入 rate-level 层 |
| BASELINE_INSTABILITY | 全证据集中 baseline 自身出现非预期 verdict | candidate 独有的稳定差异 | 不能归因 candidate；HOLD 由其他证据决定 |
| INSUFFICIENT_EVIDENCE | matrix 不完整：有效 attempt 不足、transport 替换后仍失败 | 任何“稳定”结论 | 必须 HOLD；禁止归因 |

关键规则（FACT，来自 E.6 B.2）：

```text
稳定 = 全证据集 100% 无例外。
同一 arm 出现过 PASS 和 INC => PROVIDER_NONDETERMINISM，
不允许把不稳定的 INC 解释成 candidate-induced regression。
```

Gate 语义（FACT / INFERENCE 混合）：

```text
任一 case = CANDIDATE_REGRESSION            -> REGRESSION_CONFIRMED -> REJECT
全部 case ∈ {PROVIDER_NONDETERMINISM,
            BASELINE_INSTABILITY}           -> REGRESSION_SAFETY_CONFIRMED
任一 case = INSUFFICIENT_EVIDENCE           -> INSUFFICIENT_EVIDENCE -> HOLD
```

率差本身（如 6/7 vs 0/7）在 strict-stability policy 下不构成
CANDIDATE_REGRESSION（FACT），但它必须被带到 rate-level 层继续检查
（E.7 正是这样做的，FACT）。

---

## 9. Promotion Gate

通用 Promotion Gate 只有三个输出，语义与“score > baseline”无关：

```text
PROMOTE = 证据足够支持上线。
  有效性证据（target 修复达标）+ 安全性证据（无 confirmed regression、
  rate-level 达标、controls 干净）+ 治理证据（policy 预注册、证据完整、
  provenance 一致）+ 样本充分性 + transport bound + 无 unresolved
  blocker，全部满足（E.7 §2.5，FACT）。

HOLD = 没有明确证明失败，但证据不足以上线。
  默认态。典型触发：矩阵不完整、样本不足、provider variance、
  rate-level 未达阈值、strict-stability 无法下结论（E.5 / E.7，FACT）。

REJECT = 存在明确 blocker。
  典型触发：confirmed candidate regression（stable-PASS FAIL 或 critical
  PASS）、target fix 不成立、candidate INVALID_OUTPUT、evidence
  integrity 失败、policy 事后被修改（E.7 §2.5，FACT）。
```

Gate 组合规则（INFERENCE，基于 E.5–E.7）：

```text
1. 三个证据类型缺一不可（§6 / §11）：effectiveness 满分 + REJECT。
2. HOLD 与 REJECT 都允许由“证据完整性”触发；HOLD 是证据不足，
   REJECT 是证据/规则本身被破坏。
3. precondition（如 E.6 = REGRESSION_SAFETY_CONFIRMED）缺失或不同
   => REJECT，不重新诉讼（E.7 policy，FACT）。
4. Gate 结果一旦归档不可重算覆盖；HOLD 后只能以同一 policy 开新
   EvaluationRun（56 §11，FACT）。
```

**明确禁止的简单规则：**

```text
score > baseline => PROMOTE
aggregate improvement => PROMOTE
单轮 0 regression => PROMOTE
REGRESSION_SAFETY_CONFIRMED => PROMOTION_APPROVED
```

四条都被 Phase 6-E 直接证伪（FACT）。

---

## 10. Provenance Model

把 E.7.1 抽象成通用 provenance 链：

```text
Registered Policy
   ↓ （live 实验前冻结，commit + bytes）
Experiment
   ↓ （固定条件 + 调度 + 全部 attempts）
Immutable Evidence
   ↓ （matrix / stats / gate / runs 逐字节冻结）
Audit Revision
   ↓ （只修正声明与来源，不改阈值）
Final Policy
```

通用规则：

```text
FACT   registered policy 不可覆盖：E.7.1 将 `promotion-policy.json`
       恢复为 `ca06a9a` 字节，并归档
       `promotion-policy-e7-v1-registered.json`。
FACT   final policy 单独版本化：`promotion-policy-e7-v1-final.json`；
       与 registered 的完整差异只有 policy_id、rate 文档、新增
       `target_fix_absent` 声明。
FACT   E.7 evidence 不可再生成：matrix / stats / gate / runs 从
       `22890c1` 逐字节恢复，不重跑实验。
FACT   provenance 校验 = registered bytes == `git show ca06a9a`；
       manifest 显式承载 registered / final 两节。
```

**禁止事项（E.7.1 以 violations 列表证明其必要性，FACT）：**

```text
禁止 1  overwrite historical policy
禁止 2  regenerate historical experiment artifacts
禁止 3  change threshold after experiment
禁止 4  retroactively rewrite provenance
禁止 5  用“磁盘 vs manifest”代替“registered bytes vs git show”做校验
禁止 6  给审计修订 invent commit hash（E.7.1：`NOT_AVAILABLE_YET` 显式保留）
```

---

## 11. Evidence Immutability

什么必须 immutable：

```text
1. Attempt 级原始事实：raw_response / raw_content / parsed / contract /
   failure_kind / timestamp / artifact path。
2. 派生统计：matrix、stats、gate、runs.jsonl（E.7.1 逐字节恢复，FACT）。
3. Registered policy 与 final policy（分开版本，FACT）。
4. 每个 Decision / GateResult / Attribution。
```

允许变更的只有“新版本”：

```text
新 EvaluationRun（新 run_id）、新 PolicyVersion（未来的新实验）、
新 Candidate 版本（REJECTED 后的重新提案）、新 dataset version。
```

HOLD 重入规则（FACT + INFERENCE）：

```text
HOLD 可以重新进入 evaluation，但历史 evidence 不允许被覆盖（FACT，
56 §11：以同一 policy 重新收集证据）。
新证据以新 run 追加；gate 是否只消费 fresh evidence 由 policy 声明
（E.7 选择 fresh-only，FACT）；通用规则是“policy 决定证据集，而不是
gate 事后挑选”（INFERENCE）。
```

---

## 12. Runtime vs Control Plane Boundary

目标结构：

```text
Agent Runtime
   ↑   （执行任务、产生 Event Log / ExecutionRecord）
Promotion Control Plane
   ↑   （策略、Gate、Decision、版本注册表、回滚目标）
Evaluation / Evidence System
```

三层职责与禁止项：

| 层 | 拥有 | 禁止 |
| --- | --- | --- |
| Agent Runtime | 执行、Event Log（append-only）、ExecutionRecord 只读投影、replay 重建 | 自己判定成功/质量；把 turn/end 当成功；写回 derived 结论；做归因/RCA；决定版本采用；修改或消费自己产生的 evidence 做 promotion |
| Evaluation / Evidence System | TaskSet / Oracle、evaluation rules、LLM judge + contract、evidence capture、matrix / stats、attribution | 修改 Runtime 状态；把 LOSSY 当 EXACT；在 policy 未冻结时跑受控实验；覆盖历史 evidence |
| Promotion Control Plane | Policy 注册与冻结、PromotionGate、Decision、Provenance / Manifest、版本注册表、canary / rollback 目标（未来） | 重算覆盖历史 decision；事后改阈值；代替 Runtime 执行；在无有效证据时放行 |

依据（FACT）：

```text
- 04/05：Evaluation 对 Runtime 全部 READ ONLY，Expected Outcome 属于
  Task Definition。
- 06：Runtime 负责“怎么执行”，Evaluation 负责“执行得怎么样”。
- Phase 5-N：`decide()` 不部署、不路由、不执行 rollback（28）。
- E.7：runner 自己拒绝无 policy 的运行，这是 Control Plane 规则在
  Evaluation Plane 的强制执行点。
```

结论（INFERENCE）：未来 Runtime 不应该承担 promotion 决策、阈值解释、
证据完整性判定；它只提供不可变执行事实。Control Plane 不感知具体
provider / prompt 内容，只消费 Evidence + Policy。

---

## 13. Minimal State Machine

```text
DRAFT
  ↓   candidate 有稳定 baseline_ref + artifact hashes + policy 已注册
EVALUATING
  ↓   证据集满足 policy（样本量 / 替换上限）
EVALUATED
  ↓   regression attribution 完成
REGRESSION_CHECKED
  ↓   effectiveness 证据存在且无 confirmed regression
PROMOTION_REVIEW
  ↓   gate 求值
PROMOTABLE / HOLD / REJECTED
  ↓   （仅 PROMOTABLE）控制面执行版本采用
PROMOTED
```

转移规则：

```text
EVALUATING -> EVALUATED：
  矩阵完整或按 policy 声明为 INSUFFICIENT_EVIDENCE（此时跳 HOLD）。

EVALUATED -> REGRESSION_CHECKED：
  归因完成；任一 CANDIDATE_REGRESSION => REJECTED。

REGRESSION_CHECKED -> PROMOTION_REVIEW：
  REGRESSION_SAFETY_CONFIRMED 且 target effectiveness 有证据；
  缺任一 => HOLD。

PROMOTION_REVIEW -> PROMOTABLE：
  全部 rate rules + sample sufficiency + transport bound + 证据完整
  + governance 一致。

PROMOTION_REVIEW -> HOLD：
  无明确 blocker，但证据/稳定性/样本不足（默认分支）。

PROMOTION_REVIEW -> REJECTED：
  存在明确 blocker（confirmed regression、target fix 缺失、
  INVALID_OUTPUT、evidence integrity 失败、policy 被改）。

HOLD -> EVALUATING：
  允许同一 candidate 版本以同一 policy（或显式新 PolicyVersion）重入，
  但必须开新 EvaluationRun；历史 evidence 不覆盖、不删除。

REJECTED：
  对该 candidate 版本终态；新候选 = 新 Candidate 版本，从 DRAFT 开始。
```

---

## 14. MVP Scope

把 Phase 6-E 的参考实现（`provider_probe.py` + artifacts）提炼成最小可复用
机制，不需要新建平台（INFERENCE；对应代码已存在，FACT）：

```text
MVP-1  Policy 文件 schema + 注册/冻结检查
       （已实现：promotion-policy*.json + `_load_promotion_policy_version`，
       FACT）
MVP-2  固定条件 runner + 失败替换 + evidence rows
       （已实现：`--candidate-eval` / `--summarize` / promotion gate 子命令，
       FACT）
MVP-3  离线 matrix / stats / gate 重算
       （已实现：`--summarize-promotion-gate` 与 committed gate 字节一致，
       FACT）
MVP-4  Manifest + provenance 校验
       （已实现：manifest-2 + provenance tests，FACT）
MVP-5  对象模型的序列化契约（本文件 §4）
       （INFERENCE：仅当出现第二个消费方时才落 schema，YAGNI）
```

验收标准（全部离线，不跑 live provider）：

```text
1. 任意 run 可从 committed artifacts 离线重算 matrix/stats/gate；
2. registered policy bytes == git show <commit>；
3. final policy 与 registered 的 diff 只含声明/来源，不含阈值；
4. 任何 HOLD/REJECT 都能给出 blocker 清单，而不只是分数；
5. 任何 Decision 都能反查到 Attempt 级 evidence。
```

---

## 15. Non-goals

本阶段及 MVP 明确不做：

```text
1. E.8 / 继续优化 B-prime / 重跑 E.5–E.7（Phase 7 是架构抽象）。
2. Production promotion、canary 流量、真实部署。
3. 修改 candidate prompt、parser / contract / retry、production runtime。
4. 把阈值（8/10、-0.1、CI 0.5）固化成通用默认值。
5. 实现通用版本注册表、authorization 强制执行、rollback 执行层
   （Phase 5-N 已标 PARTIAL/外部职责，FACT）。
6. 自动生成 improvement candidate（E.5 的 candidate 由人工/流程定义）。
7. 用“aggregate score”替代 per-case + rate 两层证据。
8. 把 LLM judge 当作唯一事实来源（guard / deterministic 层优先）。
```

---

## 16. Open Questions

以下均为 UNKNOWN / 未验证：

```text
1. 版本注册表：baseline_ref / target_version 目前是稳定字符串，无 registry
   解析与不可变版本对象（Phase 5-N A1，PARTIAL）。通用 Candidate 需要它吗？
2. 阈值可迁移性：E.7 的 N=10、8/10、-0.1 在另一个 provider / 任务域是否
   仍然合理？如何校准？没有第二个数据集，UNKNOWN。
3. HOLD 重入的证据集：新 run 通过后，gate 应只消费 fresh evidence（E.7
   做法）还是全证据集（E.6 做法）？没有跨重入实验，UNKNOWN。
4. 归因阈值：strict-stability 的 100% 标准在小样本下过于保守；多大 N 下
   应引入统计归因（而非策略阈值）？UNKNOWN。
5. evaluation_id：Phase 5-O 只有 `{execution_id}:{task_id}` 组合引用，
   无独立 evaluation_id（29/31，PARTIAL）。通用对象模型是否需要？
6. authorization / canary / rollback 执行：Phase 5-N 只到契约层，
   E.7 未触及；Control Plane 的“执行”边界未定义，UNKNOWN。
7. governance 证据的最低形态：policy 文件 + manifest + git 引用是否足够，
   还是需要签名 / 时间戳服务？E.7.1 证明 git 字节足够本地审计，生产场景
   未验证。
8. provider nondeterminism 占主导（如 PASS/INC 各 50%）时，Gate 是否
   永远 HOLD？是否存在“该 case 不可判”的显式退出路径？UNKNOWN。
```

---

## 17. Validation（本阶段执行）

只做只读检查，未运行 live provider：

```text
1. 引用 artifacts 存在性确认：candidate-eval/（metadata、matrix、
   targeted/regression runs、raw evidence）、regression-attribution/
   （matrix、runs）、promotion-gate/（registered/final policy、manifest、
   runs.jsonl、matrix、stats、gate.json）——全部存在（FACT）。
2. 报告一致性：54/55/56/56a 与 artifacts 中的 policy bytes、GATE 值、
   统计表一致（FACT）。
3. 本文件内部一致性：对象关系、状态机、Gate 语义与 Phase 6-E 结论
   交叉核对，无新增实验结论（本文件）。
```

STOP：本阶段不 commit、不 push、不运行 live experiment、不做 E.8、
不做 production promotion。
