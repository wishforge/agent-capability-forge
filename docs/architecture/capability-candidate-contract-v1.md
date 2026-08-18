# CapabilityCandidate v1 Contract（Phase 9-A.1）

- 阶段：Phase 9-A.1（CapabilityCandidate Contract Design）
- 日期：2026-08-18
- 基线：Phase 8.6（repository-structure-v1）、Phase 7.1（61）、Phase 8.5（78）、外部考古 01–05
- 范围：只允许新文档 + 离线 validator/tests（`docs/archaeology/unified-runtime/phase9a1/`）；未修改 `src/`、`pilot/`、Phase 7–8.5 历史 artifacts；未实现 Source Adapter；未 commit / push
- 最终判定：**CANDIDATE_CONTRACT_DESIGN_CLOSED_WITH_PRODUCTION_GAPS**

判定理由：本文是 CapabilityCandidate v1 **Design Contract**。Phase 9-A.1 Review（`CANDIDATE_CONTRACT_PARTIAL`）的四个硬门已在 Phase 9-A.1.1 Closure（`CANDIDATE_CONTRACT_CLOSED`，53 个离线测试通过）中以设计语义闭合；但 production implementation 尚未完成，全部已知 gap 属于 Phase 9-B production realization，不改变本 Design Contract 的闭合状态。

> 本文定义的是 CapabilityCandidate v1 Design Contract。
> Design Contract 已闭合，但 production implementation 尚未完成。
> Phase 9-B 才负责 production realization。
>
> 相关文档：`capability-candidate-contract-v1-review.md`（反方审查）、
> `capability-candidate-contract-v1-closure.md`（设计闭合）、
> `capability-candidate-contract-v1-production-reconciliation.md`（Design/Production reconciliation）。

---

## 1. Executive Summary

CapabilityCandidate 是 **Canonical Governance Intake Object**，不是整条链的“稳定 Canonical Object”：在一次 Intake 被接受（`INTAKE_ACCEPTED`）时创建（Design），把 `capability_id`、`candidate_id`、`version`、`source`、`artifact`、`producer`、`requester`、`manifest`、`provenance`、`extensions` 绑定为一个 Design 上不可变的记录（production 未实现，见 §25.4）。

核心结论：

1. **Candidate ≠ Source**：source 是 Candidate 内部的一个独立子对象，只回答“从哪里来”，不参与 Candidate 身份。
2. **Candidate ≠ Artifact**：artifact 是内容引用（digest + ref），Candidate 是治理对象；同一 artifact 可被多个 Candidate 引用。
3. **Requester ≠ Producer**：两个独立字段；当前仓库没有 formal request 对象（UNKNOWN），但字段边界在 v1 中固定。
4. **Evidence / Policy / Decision 分层**：Candidate 禁止嵌入 `evidence` / `policy` / `decision`；`PromotionDecision` 属于 Decision 层。
5. **Core / Extension 分离**：Core 是 10 个稳定字段；source-specific 数据只允许进 `extensions`，治理层不读 extension。
6. **Intake 规则机器可验证**：不满足任一 REQUIRED 字段或 binding invariant → `INTAKE_REJECTED`，非法 raw input 永不成为 Candidate。
7. **Phase 8 可消费**：`candidate_id`、`candidate_version`、`artifact_digest` 直接映射 AdoptionAuthority / Registry / Runtime Guard 的绑定键；`version` 与 `capability_id` 需要 adapter（Registry 当前在 promote 时自造 `capability_id`）。
8. **Candidate ≠ Registry Entry / CapabilityVersion ≠ CapabilityInstance**：CapabilityCandidate 只覆盖 Intake → Governance 的 canonical intake object；发布层 logical object（Registry Entry / CapabilityVersion）与运行层 CapabilityInstance 是另外两个对象，本 contract 不定义、不消除它们。

本阶段不实现 Source Adapter、不修改生产代码、不修改 Phase 7–8.5 历史语义。

---

## 2. Business Problem

> “任何来源的能力进入 Capability Intake 之后，什么条件下，它才正式成为一个 CapabilityCandidate？”

答案（本 contract 的机器可验证规则）：

```text
Raw Input
  -> Adapter 验证（mutable ref -> immutable revision；内容 digest）
  -> Normalizer 产出标准化候选记录（Capabilityization）
  -> Intake Check：所有 REQUIRED Core 字段 + binding invariants 通过
       -> INTAKE_ACCEPTED -> 创建 CapabilityCandidate v1（Design：不可变）
  -> 任一检查失败
       -> INTAKE_REJECTED（非法 raw input 永不成为 Candidate）
```

来源可以变化（Git / OCI / Artifact Registry / Agent Output / Marketplace / Internal System / External Vendor / Local Package），但 **CapabilityCandidate Contract 不变化**。Evaluation、Regression、Promotion、AdoptionAuthority、Registry、Runtime 统一消费同一个 Candidate 对象；它们不得感知来源类型。

---

## 3. External Evidence

只消费冻结的 `05-cross-project-synthesis.md`（其事实来源 01–04）。以下是 external FACT，不是自动变成 Candidate 字段：

| # | External FACT | 对 Candidate v1 的约束 |
|---|---|---|
| 1 | 4/4 项目存在 Source/Object Separation | source 必须与 Candidate 身份分离 |
| 2 | 4/4 项目区分逻辑身份与内容身份 | `capability_id`/`candidate_id` ≠ `artifact_digest` |
| 3 | 4/4 项目在输入成为 canonical 对象前有显式校验边界 | Intake Check 必须 fail-closed |
| 4 | 3/4 项目存在 mutable reference → immutable anchor 问题 | `source_reference`（可变）与 `resolved_revision`（不可变）必须分离 |
| 5 | 只有 in-toto 有完整 Evidence/Policy/Decision 分层 | Candidate 不得携带 governance decision |
| 6 | 4/4 项目没有独立 provenance object | 不做“万能 provenance”；只做最小 intake provenance 块 |
| 7 | 4/4 项目无 runtime enforcement / end-to-end promotion / revocation / cross-system identity binding | 这些是平台新机制，不是可复用外部模式 |
| 8 | 消费者消费 canonical/已处理对象而非裸输入 | Governance 只消费 Candidate，不消费 adapter 输出 |

设计约束（05 §14）中与本阶段最相关的四条：

```text
DESIGN_CONSTRAINT：Content identity 不应等于 source reference。
DESIGN_CONSTRAINT：稳定逻辑身份应独立于可变引用。
DESIGN_CONSTRAINT：若接受外部 resolver 报告的 revision，必须有验证手段。
DESIGN_CONSTRAINT：统一 canonical object 不是唯一解（但本业务目标要求统一消费）。
```

---

## 4. Current Repository Facts

只列机器可读证据（FACT），带代码位置。

### 4.1 已有对象

| 对象 | 形态 | 证据 |
|---|---|---|
| VerifiedTaskArtifactBundle v0 | 密封、immutable 的 Capabilityization 输入；严格 schema、13 条校验、内容寻址存储 | `src/forge/bundle_producer.py`（FROZEN P0） |
| CapabilityCandidate（prototype） | 目录：`candidate.json` + `manifest.json` + `implementation/artifact/` + `tests/` + 后续 `validation.json` / `evaluation.json` | `src/forge/capabilityizer.py`、`validator.py`、`evaluator.py` |
| Capability Manifest v0.1 | Candidate 内嵌 value object；含 capability/entrypoint/contract/env/secrets/tests/sandbox/provenance | `capabilityizer.py` manifest；MVP spec §8 |
| CapabilityEvaluation | `evaluation_id` / `candidate_id` / test_cases / pass_rate / verdict / promotion_rule | `evaluator.py` |
| AdoptionAuthority | `AUTHORITY_FIELDS` = candidate_id / candidate_version / promotion_decision_id / evaluation_run_id / policy_version / artifact_digest / provenance；确定性 authority_id；write-once ledger；revocation events | `pilot/adoption_authority.py` |
| PromotionDecision | `decision_id` / candidate_id / candidate_version / run_id / policy_ref / value=PROMOTE / gate_result / recorded_hash | `pilot/adoption_authority_producer.py` |
| Registry Entry | `experimental_registry_v1`：capability_id（promote 时生成）/ name / version / family / artifact_dir / manifest / evaluation / state / adoption | `pilot/registry.py`；`pilot/state/registry/F+/*.json` |
| Runtime Guard | 激活前二次校验 state/binding/digest/lifecycle/policy/provenance/revocation/staleness | `pilot/runtime_adoption_guard.py`；唯一真实路径 `harness.py phase_future("b3")` |
| Phase 7.2 Protocol Objects | Candidate / EvaluationRun / Attempt / Evidence / Outcome / RegressionFinding / Attribution / PromotionPolicy / PromotionGate / Decision / PolicyVersion / ArtifactManifest / Provenance | `docs/archaeology/unified-runtime/phase7.2/validate_protocol_contract.py` |
| ImprovementCandidate | 与 failure evidence 绑定的变更提案（prompt/skill/policy/config），禁止任意代码变更 | `docs/archaeology/deepseek-harness/evaluation/improvement_candidate.py` |
| CapabilityInstance | `instance_id` / version_id / sandbox / status（activating/running/stopped/failed） | MVP spec §7.5（DESIGN，未实现） |

### 4.2 回答考古问题

1. **已有对象**：§4.1 全表。
2. **candidate-like**：`CapabilityCandidate`（capabilityizer 输出）。
3. **artifact-like**：`VerifiedTaskArtifactBundle`（输入 artifact）与 forged artifact 目录（`implementation/artifact/`，Candidate 的产物内容）。
4. **request-like**：`llm_proposal.json` / `confirm.json`（原型数据）、`ImprovementCandidate`（考古提案对象）。都不是 formal `CapabilityRequest`。
5. **冻结语义**：Bundle v0、Capability Manifest v0.1、Phase 7.2 协议对象与 G1–G7、`AUTHORITY_FIELDS`、`BINDING_KEYS`、`PROVENANCE_KEYS`、registry `experimental_registry_v1`、lifecycle 状态机（61 §7）。
6. **只是 prototype**：`candidate.json`（只有 4 个字段）、Registry Entry（flat two-state、promote 时自造 capability_id）、CapabilityInstance（spec only）。
7. **可复用**：manifest 结构、`forged_artifact_digest` 位置（但语义需归一化，见 §12）、evaluation 结构、authority binding keys、provenance keys、lifecycle 状态机。
8. **不能复用**：`ImprovementCandidate`（不同对象：它是“改动提案”，不是能力候选）；当前 `candidate.json` 的 `state` 字段（v1 不携带，见 §23）；capabilityizer 的 `forged_artifact_digest` 编码（与 Phase 8 `dir_digest` 不一致，见 §12）；registry 自造 `capability_id`（v1 由 intake 提供）。

### 4.3 关键 FACTS

```text
FACT  capabilityizer 计算 forged_artifact_digest = sha256(canonical({files:[{path,digest}]}))。
FACT  Phase 8 producer 计算 artifact_digest = dir_digest(artifact_dir) = sha256(canonical({rel_path:digest}))。
FACT  对 pilot/state 同一 artifact：forged=87a6f062...（编码 A），dir=1238c032...（编码 B，含
      __pycache__）/ 5ac13b1a...（编码 B，仅 main.py），harness=657057ac...（编码 C）；三套编码不等
      （closure §2.2 实测）。
FACT  Phase 8 runtime guard 要求 authority/decision/run/candidate/entry/artifact 六处 digest 全等
      （runtime_adoption_guard.py ARTIFACT_DIGEST_MISMATCH），因此运行时强制的是 dir_digest 语义。
FACT  registry 在 promote() 时生成 capability_id（cap-<uuid>），Candidate 当前不携带 capability_id。
FACT  pilot/state 的 F+ registry entry 没有 adoption 块（Phase 8 hardening 之前的 historical artifact）。
FACT  当前 Candidate 在 capabilityize 后仍可编辑 manifest/tests（MVP §7.2 设计为可编辑）。
```

---

## 5. Object Boundary

根据真实代码调整后的对象链（`->` 表示数据/控制流；方括号为存在状态）：

```text
CapabilityRequest [DESIGN/UNKNOWN：当前只有 llm_proposal + confirm 原型]
   |
   v
Source / Producer [FACT 部分：Bundle identity.producer；无 source_type]
   |
   v
Raw Input [FACT 部分：rollout JSONL + workspace snapshot + run_meta]
   |
   v
Artifact [FACT：VerifiedTaskArtifactBundle + forged artifact 目录]
   |
   v
CapabilityCandidate [FACT prototype -> DESIGN v1]
   |
   v
Evidence [FACT：evaluation.json / store evidence；validation.json]
   |
   v
Policy Evaluation [FACT：PROMOTION_RULE + store policies registered/frozen]
   |
   v
Decision [FACT：PromotionDecision；value=PROMOTE / gate_result=PASS]
   |
   v
AdoptionAuthority [FACT：write-once ledger + revocation events]
   |
   v
Registry [FACT：promoted entry] -> Runtime Guard [FACT] -> Runtime Instance [DESIGN]
```

十个对象必须分离：

> 对象链语义：CapabilityCandidate 是 Canonical Governance Intake Object；Registry Entry /
> CapabilityVersion（发布层）与 CapabilityInstance（运行层）是另外两个对象，三者不是同一个对象
> （review §9.2）。

| # | 对象 | 存在状态 | v1 中的角色 |
|---|---|---|---|
| 1 | CapabilityRequest | DESIGN / UNKNOWN | `requester.request_id` 引用；不嵌入 |
| 2 | Source | DESIGN | Candidate 子对象（source_type / source_reference / resolved_revision） |
| 3 | Raw Input | FACT 部分 / DESIGN | adapter 输出；Intake Check 输入 |
| 4 | Artifact | FACT | Candidate 内容引用（artifact_digest / artifact_ref） |
| 5 | CapabilityCandidate | prototype -> v1 | 本 contract 定义的对象 |
| 6 | Evidence | FACT | 独立对象；Candidate 禁止嵌入 |
| 7 | Policy | FACT | 独立对象（PromotionPolicy）；Candidate 禁止嵌入 |
| 8 | Decision | FACT | 独立对象（PromotionDecision）；Candidate 禁止嵌入 |
| 9 | AdoptionAuthority | FACT | Decision 的下游授权对象 |
| 10 | Runtime Instance | DESIGN | 运行时生命周期；与 Candidate 状态分离 |

---

## 6. Candidate Model A — Identity-centric

**核心**：Candidate 表示一个逻辑 Capability version；artifact / source / producer 是附带的引用属性。

维度评估：

| 维度 | Model A |
|---|---|
| identity | 强（capability + version） |
| source | 引用属性 |
| artifact | 引用属性（内容身份独立） |
| version | 身份核心 |
| producer | 属性 |
| requester | 属性（可无） |
| provenance | 属性 |
| evidence | 独立对象 |
| lifecycle | 身份对象可带对象状态 |
| governance compatibility | 中：Evaluation 需要同时传 Candidate + artifact |
| runtime compatibility | 中：运行时仍要 artifact 解析 |
| extensibility | 好 |
| migration cost | 中（需拆 artifact 出目录） |
| replayability | 中 |
| auditability | 中（source/producer 绑定弱） |

**问题**：本阶段业务目标要求“Evaluation(Candidate)、Adoption(Candidate)”单对象消费；Model A 下这些消费者仍要第二个参数（artifact），统一消费不成立。

---

## 7. Candidate Model B — Artifact-centric

**核心**：Candidate 紧绑定实际可执行 artifact；Candidate ≈ artifact 的治理包装。

| 维度 | Model B |
|---|---|
| identity | 弱（内容身份主导，逻辑身份退化） |
| source | 属性 |
| artifact | 身份核心 |
| version | 属性 |
| producer | 属性 |
| requester | 属性（可无） |
| provenance | 属性 |
| evidence | 独立对象 |
| lifecycle | 内容不可变，状态可带 |
| governance compatibility | 低：Phase 8 明确区分 candidate_id 与 artifact_digest |
| runtime compatibility | 好（运行直接消费） |
| extensibility | 中 |
| migration cost | 高（当前 candidate_id 语义重排） |
| replayability | 中 |
| auditability | 中（逻辑能力演进难追溯） |

**问题**：同一 artifact 被不同来源/不同 intake 带入时，Model B 无法区分两个候选；逻辑能力版本升级没有稳定锚点。外部证据也明确“逻辑身份 ≠ 内容身份”（05 §5）。

---

## 8. Candidate Model C — Intake-centric

**核心**：Candidate 表示一次进入 Governance 的标准化候选对象（intake record）。

| 维度 | Model C |
|---|---|
| identity | 中（intake 实例身份；能力身份弱） |
| source | 身份核心之一 |
| artifact | 引用 |
| version | 属性 |
| producer | 属性 |
| requester | 核心（intake 语境） |
| provenance | 核心 |
| evidence | 独立对象 |
| lifecycle | intake → governance 状态 |
| governance compatibility | 中：下游仍需把 intake 记录映射成能力对象 |
| runtime compatibility | 低（intake 记录不是可运行对象） |
| extensibility | 好 |
| migration cost | 低（与当前 pipeline 接近） |
| replayability | 好（intake 可重放） |
| auditability | 好 |

**问题**：Model C 本身不是能力治理对象；若它只表达“一次进入”，下游还要再造一个 capability object，等于引入并行生命周期（YAGNI 违反）。C 的合理部分（intake 语义、source 归一化）应并入 E。

---

## 9. Recommended Model

**选择 E：一个把 logical capability、version、source、artifact、provenance、producer、request 绑定起来的标准化治理对象。**

理由（按权重）：

1. **统一消费是本阶段业务目标的硬约束**（“Evaluation、Regression、Promotion、AdoptionAuthority、Registry、Runtime 统一消费 CapabilityCandidate”）：只有 E 让每个下游消费者拿到一个自足对象。
2. **Phase 8 事实支持 E**：`AUTHORITY_FIELDS` 与 `BINDING_KEYS` 已经把 candidate_id + candidate_version + artifact_digest + provenance 放在同一绑定记录上；E 是这些事实的 intake 侧统一形态。
3. **E 不违反 Source/Artifact 分离**：source 与 artifact 是 Candidate 内部的独立子对象（引用/来源），不是 Candidate 本身。
4. **E 是 Model C 的超集**：Intake 被接受的那一刻就是 E 对象创建的时刻；不需要额外的 intake record 对象。
5. **避免 universal schema**：E 是语义契约（Core + Extensions），不是“一个适用于所有来源的巨大 schema”；扩展被隔离在 `extensions` 中。

不是 Model A/B/C 单独成立的原因：

- A 缺统一消费（artifact 仍要单独传）。
- B 缺稳定逻辑身份（capability evolution 无法追溯）。
- C 缺能力语义（下游仍要再造能力对象）。

---

## 9.1 Design vs Production Status（四项核心 invariant）

以下四项已在 Phase 9-A.1.1 Closure 中以设计语义闭合（offline 验证通过）；production 均未实现。
标记：DESIGN = 本 Design Contract 语义；OFFLINE PROOF = `phase9a1` 离线 validator/tests 已验证；
PRODUCTION = 当前 `src/` / `pilot/` 真实行为。

### 9.1.1 capability_id ownership

| 维度 | 内容 |
|---|---|
| DESIGN | Intake 首次生成 `capability_id`（确定性派生，closure §3.4）；Registry 只消费/校验，永不 mint |
| OFFLINE PROOF | `IdentityOwnershipTests`（4）+ `test_capability_id_format` PASS |
| PRODUCTION | `registry.promote()` / `reject()` 仍 mint `cap-<uuid>`（`pilot/registry.py:132,184`） |
| STATUS | **DESIGN_ONLY** |

### 9.1.2 artifact digest（CANONICAL_ARTIFACT_IDENTITY_V1）

| 维度 | 内容 |
|---|---|
| DESIGN | `CANONICAL_ARTIFACT_IDENTITY_V1`：allowlist-only digest + 精确布局校验（closure §4.2） |
| OFFLINE PROOF | `CanonicalArtifactIdentityV1Tests`（5）PASS |
| PRODUCTION | A（capabilityizer forged digest）/ B（adoption_authority `dir_digest`）/ C（harness digest）三种编码仍并存（closure §2.2） |
| STATUS | **DESIGN_ONLY** |

### 9.1.3 Candidate seal / immutability

| 维度 | 内容 |
|---|---|
| DESIGN | `Draft -> Intake -> Seal -> Frozen Candidate`（CANDIDATE_FREEZE_RULES_V1，closure §5） |
| OFFLINE PROOF | `CandidateFreezeRulesTests`（8）PASS |
| PRODUCTION | `candidate.json` / `manifest.json` / `tests/` 仍可写；`validation.json` / `evaluation.json` 在 intake 后写入同一目录（FACT） |
| STATUS | **DESIGN_ONLY** |

### 9.1.4 Governance source independence

| 维度 | 内容 |
|---|---|
| DESIGN | source-free semantic projection（closure §6.2：投影不含 source 子对象） |
| OFFLINE PROOF | `GovernanceSourceIndependenceTests`（3）PASS |
| PRODUCTION | Governance consumers（AdoptionAuthority / Registry / Runtime Guard）尚未消费 Candidate v1（FACT） |
| STATUS | **DESIGN_ONLY** |

## 9.2 Production Gap Matrix

| Invariant | Design | Offline | Production |
|---|---|---|---|
| capability_id ownership | CLOSED | PASS | NOT_IMPLEMENTED |
| artifact digest | CLOSED | PASS | NOT_IMPLEMENTED |
| Candidate seal | CLOSED | PASS | NOT_IMPLEMENTED |
| evaluation binding | CLOSED | PASS | NOT_IMPLEMENTED |
| source-free governance | CLOSED | PASS | NOT_IMPLEMENTED |

其他已知 production gap（不改变 Design 闭合，Phase 9-B 处理）：

- Candidate v1 尚未由 production 产出：capabilityizer 仍写 prototype `candidate.json`（4 字段）。
- Governance consumers 尚未接入 Candidate v1：Authority / Registry / Guard 消费 prototype 目录。
- 无 production Intake 层 / Source Adapter；`resolved_revision` 验证机制未实现。
- `evaluation.json` 不记录 `artifact_digest` / `seal_digest`（evaluation binding 的生产缺口）。
- formal `CapabilityRequest` 对象不存在（`request_id` lineage UNKNOWN）。

---

## 10. Identity

五个标识符的职责：

| 标识符 | 职责 | 稳定性 |
|---|---|---|
| `capability_id` | 逻辑 Capability 的跨版本稳定身份 | 跨版本稳定 |
| `candidate_id` | 一次 Intake 生成的 Candidate 实例身份 | 每对象唯一 |
| `version` | 业务版本（Capability 的语义版本） | 版本内稳定 |
| `source_revision` | 来源在 intake 时解析到的不可变锚点 | 不可变（provenance） |
| `artifact_digest` | 被运行内容的不可变内容身份 | 不可变（content binding） |

逐问回答：

1. **capability_id 是否跨版本稳定？** 是（MVP §7.3；Design：v1 将其纳入 Candidate，由 intake 首次生成，Registry 只消费/校验；Production：当前 registry 在 promote/reject 时仍自造 `cap-<uuid>`，Phase 9-B 删除 mint）。
2. **candidate_id 是否每个版本唯一？** `candidate_id` 每个 Candidate 对象唯一；一个 version 可以有多个 Candidate（不同来源/不同 intake）。不是“version 唯一”。
3. **version 是否业务版本？** 是。整数（当前 manifest `capability.version: 1`）；Phase 8 authority 使用 `"v1"` 字符串，由 adapter 转换。
4. **artifact_digest 是否属于 Candidate identity？** 否。内容身份 ≠ 逻辑身份（05 §5 external FACT）；它是不可变 content binding。
5. **source_revision 是否属于 Candidate identity？** 否。它是 provenance（外部 resolver 报告的 revision 必须经 adapter 验证，05 §14）。
6. **一个 Capability 能否产生多个 Candidate？** 是。
7. **一个 Artifact 能否被多个 Candidate 引用？** 是（内容寻址允许多引用；ORAS pattern）。
8. **Candidate 是否必须 immutable？** Design rule：是——`INTAKE_ACCEPTED` → `SEAL` → `FROZEN`（CANDIDATE_FREEZE_RULES_V1，closure §5）。Production status：**NOT IMPLEMENTED**——当前 prototype 在 forge 期间可编辑（FACT），该可写行为属于 legacy/prototype implementation，Phase 9-B 负责实现 seal。

---

## 11. Source

统一表达但不绑定实现：

```json
{
  "source_type": "git",
  "source_reference": "https://github.com/acme/cap.git",
  "resolved_revision": "a1b2c3..."
}
```

- `source_type`：非空字符串。建议初始词汇：`git / oci / artifact_registry / agent / marketplace / internal / external / local`。**这不是封闭 enum**；未来来源类型必须不加 Core 改动即可通过（离线测试用 `future_source_xyz` 验证）。
- `source_reference`：可变引用（URL / registry ref / rollout 路径）。
- `resolved_revision`：adapter 验证后的不可变锚点（commit SHA / OCI digest / bundle digest）。没有验证手段的 resolver 报告值不构成可信 revision（05 §14）。

Source 只回答“这个 Candidate 从哪里来”；不回答“是否合格”。来源可信度、是否可 promote，属于 Policy / Decision 层。

---

## 12. Artifact

Artifact 只回答“真正被消费/运行的内容是什么”。

```json
{
  "artifact_digest": "sha256:...",
  "artifact_ref": "artifact:sha256:..."
}
```

**单 digest semantics（关键裁决）**：

- Design：v1 唯一 canonical digest = **CANONICAL_ARTIFACT_IDENTITY_V1**（allowlist-only digest + 精确布局校验；closure §4.2）。它以 Phase 8 `dir_digest` 的 bare-map 形状为基线，但排除 `__pycache__` 等生成物；这是 Design Contract，不是当前 production 实现。
- manifest 内 legacy 字段 `provenance.forged_artifact_digest` 在 v1 中必须等于 `artifact.artifact_digest`，否则 `ARTIFACT_DIGEST_SEMANTICS_CONFLICT`（validator 强制，Design）。
- Production FACT：capabilityizer 的 `forged_artifact_digest` 编码（A）与 `adoption_authority.dir_digest`（B）、`harness._dir_digest`（C）仍然并存（同一 artifact 实测 `87a6f062...` vs `1238c032...` / `5ac13b1a...` / `657057ac...`，closure §2.2）。Phase 9-B 统一 A/B/C 为 CANONICAL_ARTIFACT_IDENTITY_V1。**禁止在本文档中声称当前 production 已统一**。

Candidate ≠ Artifact：

- Candidate 是治理对象（identity + source + provenance + manifest）。
- Artifact 是内容引用（digest + ref），字节存于内容寻址存储。
- Bundle（输入 artifact）与 forged artifact（Candidate 产物）是不同 artifact；v1 记录的是 forged artifact。

---

## 13. Requester

谁提出需要：

```json
{
  "kind": "human | agent | workflow | event",
  "id": "operator-david",
  "request_id": "req-fplus-1"
}
```

- v1 中 `requester` 是 OPTIONAL（有些来源/自动化流水线没有显式 requester）。
- `request_id` 是 optional 引用；当前仓库没有 formal `CapabilityRequest` 对象（UNKNOWN）。
- Requester 与 Producer 是独立字段，绝不合并；即使值相同也必须分别记录。

---

## 14. Producer

谁生产能力：

```json
{
  "kind": "human | agent | build_system | vendor",
  "id": "codex-artifact-builder-v0"
}
```

- v1 中 `producer` 是 REQUIRED。
- 当前事实：Bundle `identity.producer` / `provenance.producer` 记录构建者（`codex-artifact-builder-v0`）。
- 重要区分：**Candidate 的 producer ≠ AdoptionAuthority 的 issuer**。authority issuer 是 operator（`pilot-rehearsal` / `confirm.operator`，FACT），producer 是能力生产者。两者混淆会导致审计责任错位。

---

## 15. Evidence

Evidence = 发生过什么，有什么证据。

- 现有形态：`evaluation.json` / `validation.json`（Candidate 目录内 co-located）、store `evidence[]`（`evidence_id` / `run_id` / `recorded_hash` / `current_hash`）、Phase 7.2 `Evidence` 协议对象。
- v1 规则：Candidate 禁止嵌入 `evidence` 字段（`OBJECT_BOUNDARY_VIOLATION`）。Evidence 是独立对象，通过 `candidate_id` / `run_id` 引用 Candidate。
- 不把“运行期事件/状态”当 evidence（05 §8：Backstage status / OpenHands observation 都不是 evidence）。

---

## 16. Policy

Policy = 什么条件算合格。

- 现有形态：`PROMOTION_RULE`（`src/forge/evaluator.py`）+ store `policies`（registered / frozen）+ Phase 7.2 `PromotionPolicy`（G1–G3）。
- v1 规则：Candidate 禁止嵌入 `policy` 字段。Policy 预注册、预冻结，Evaluation/Decision 绑定 policy_ref + policy_version。

---

## 17. Decision

Decision = 根据 Evidence + Policy 得出的治理结论。

- 现有形态：`PromotionDecision`（value=PROMOTE / gate_result=PASS / recorded_hash）+ `AdoptionAuthority`。
- v1 规则：Candidate 禁止嵌入 `decision` / `promotion_decision` / `adoption_authority` / `promotion_gate`。
- **Candidate 不等于 PROMOTE / REJECT / PROMOTED**：这些值属于 Governance。HOLD ≠ REJECT（61 §8：缺 policy 是 HOLD，不是 candidate 质量 REJECT）。

---

## 18. Provenance

不做“万能 provenance”。v1 只定义最小 intake provenance 块：

```json
{
  "created_at": "2026-08-14T12:11:46.275Z",
  "source_revision": "sha256:...",
  "build_ref": "bundle:01a0002b-...",
  "request_id": "req-fplus-1",
  "intake_ref": "intake:..."
}
```

字段语义与数据现状：

| 字段 | 状态 | 当前数据来源 |
|---|---|---|
| `created_at` | REQUIRED | manifest `provenance.forge_timestamp` |
| `source_revision` | REQUIRED（必须等于 `source.resolved_revision`） | bundle digest / resolved revision |
| `build_ref` | OPTIONAL | 当前可用 `bundle_id` |
| `request_id` | OPTIONAL | **UNKNOWN**：当前仓库无 request 对象 |
| `intake_ref` | OPTIONAL | **UNKNOWN**：Phase 9-B 定义 |

顶层 `source` / `producer` / `artifact_digest` 已经覆盖了其余 provenance 维度；不重复塞进 provenance。Governance provenance（Phase 8 `PROVENANCE_KEYS` = policy / evidence_manifest / run_ids / immutable_artifact_refs）是另一个层，属于 Evaluation/Decision 之后，不并入 Candidate。

---

## 19. Intake Eligibility

Raw Input 什么时候变成 CapabilityCandidate：Intake Check 全过。

字段分类：

| 字段 | 分类 | 规则 |
|---|---|---|
| `schema_version` | REQUIRED | literal `capability-candidate-v1` |
| `candidate_id` | REQUIRED | 非空；intake 时生成 |
| `capability_id` | REQUIRED | 非空；跨版本稳定 |
| `name` | REQUIRED | kebab-case |
| `version` | REQUIRED | int >= 1 |
| `source` | REQUIRED | 对象；`source_type` / `source_reference` / `resolved_revision` 非空 |
| `artifact` | REQUIRED | 对象；`artifact_digest` = `sha256:<64 hex>` |
| `producer` | REQUIRED | 对象；`kind` / `id` 非空 |
| `requester` | OPTIONAL | 若存在：对象；`kind` / `id` 非空 |
| `manifest` | REQUIRED | 对象；`manifest_version` / `capability.name` / `entrypoint` / `contract` / `tests` 非空 |
| `provenance` | REQUIRED | 对象；`created_at` 非空；`source_revision` 非空且 = `source.resolved_revision` |
| `extensions` | OPTIONAL | 若存在：对象；每个 extension 必须是对象 |
| `evidence` / `policy` / `decision` / `adoption_authority` / `promotion_gate` | FORBIDDEN | 独立 governance 对象，嵌入即 `OBJECT_BOUNDARY_VIOLATION` |
| 其他顶层字段 | FORBIDDEN | `UNKNOWN_CORE_FIELD`；source-specific 数据进 `extensions` |

结果：

```text
INTAKE_ACCEPTED  所有检查通过 -> 创建不可变 CapabilityCandidate v1（Design rule；production 未实现）
INTAKE_REJECTED  任一检查失败 -> 不创建 Candidate；fail-closed
```

禁止：invalid raw input 直接变成 Candidate。

---

## 20. Core vs Extension

**CORE**（所有 CapabilityCandidate 都必须拥有的稳定语义，10 个顶层键）：

```text
schema_version  candidate_id  capability_id  name  version
source          artifact      producer       manifest  provenance
extensions      requester (OPTIONAL)
```

**EXTENSION**（source-specific / capability-specific / runtime-specific，只允许在 `extensions` 内）：

| 来源 | 示例 extension 字段 |
|---|---|
| GitHub | `extensions.git.pr_number`、`extensions.git.review_thread_ref` |
| Claude | `extensions.claude.session_id`、`extensions.claude.thread_id` |
| OCI | `extensions.oci.media_type`、`extensions.oci.annotations` |
| MCP | `extensions.mcp.server_metadata` |
| Skill | `extensions.skill.skill_specific_metadata` |
| Codex（当前唯一实现） | `extensions.codex.session_id / thread_id / turn_id` |

Extension 规则：

1. 禁止污染 Core：`pr_number` 出现在顶层 → `UNKNOWN_CORE_FIELD`。
2. Core validator 不解释 extension 内容，只要求它是对象。
3. Governance / Registry / Runtime 不读 extension。
4. Extension 应声明 `applicability`（对哪个 source/capability）与 provenance（值来自哪里），遵循 61 §2.2。

---

## 21. Governance Boundary

正式 invariant：

```text
任何进入 Governance 的对象必须是 CapabilityCandidate。

Evaluation(Candidate)
Regression(Candidate)
Promotion(Candidate)
Adoption(Candidate)

禁止 EvaluationGitHub / EvaluationOCI / EvaluationAgent 等 source-bound 治理入口。
```

Governance 不得知道 Source Adapter 的内部实现。机器验证方式（offline）：

- `governance_projection()` 永不读取 `source.source_type`，且投影任意层级不含 `source_type` / `source_reference`（closure §6.2 deep scan；离线测试断言）。
- git / oci / agent / 未知来源类型的 Candidate 产生完全相同的 governance projection（deep-equal，closure §6.3）。

Design vs Production：

```text
DESIGN          source-free semantic projection（投影不含 source 子对象）
OFFLINE PROOF   GovernanceSourceIndependenceTests（3）PASS
PRODUCTION      Candidate v1 未接入 AdoptionAuthority / Registry / Runtime；
                生产消费者不消费 Candidate v1，生产层无 source-free projection
PRODUCTION_STATUS = NOT_IMPLEMENTED
```

---

## 22. Phase 8 Compatibility

Compatibility Matrix：

| Candidate Field | Existing Phase 8 Consumer | Semantics | Compatible |
|---|---|---|---|
| `candidate_id` | AdoptionAuthority `AUTHORITY_FIELDS`；Registry `adoption.candidate_id`；Runtime Guard | 稳定 candidate 身份 | **DIRECT**（同字符串） |
| `version` | Registry entry `version`（int）；Authority `candidate_version`（"v1"） | 业务版本 | **ADAPTER**（int → `"v{N}"`；registry 直接） |
| `artifact.artifact_digest` | Runtime Guard digest 绑定；Authority `artifact_digest`；Registry `adoption.artifact_digest` | forged artifact 内容身份（dir-digest 语义） | **DIRECT**（Phase 9-B 需归一化 capabilityizer 编码，见 §12） |
| `source` | Manifest `provenance.source_bundle_id` / `source_artifact_digest` / `source_task_id` | intake 来源 | **ADAPTER**（扁平字段 → source 对象；`source_type` 是新语义） |
| `producer` | Bundle `identity.producer`（构建者）；Authority `issuer_id`（operator） | 能力生产者 vs 授权签发者 | **PARTIAL / ADAPTER**（两个角色不同，禁止合并） |
| `request_id` | Provenance | requester 追溯 | **UNKNOWN**（当前仓库无 request 对象） |
| `manifest` | Registry entry `manifest`（直接嵌入） | 能力负载 | **DIRECT** |
| `capability_id` | Registry entry `capability_id`（promote 时自造） | 逻辑能力稳定身份 | **ADAPTER**（registry 必须复用 Candidate 的 `capability_id`，不再自造） |

约束：

- 不能修改 Phase 8 historical semantics：`adoption_store.json` schema、`AUTHORITY_FIELDS`、`BINDING_KEYS`、`PROVENANCE_KEYS`、write-once ledger、revocation events、registry entry 形状全部保持冻结。
- pilot/state 中无 `adoption` 块的 historical entry 不追溯改造。
- 需要 adapter 的字段由 Phase 9-B 的 intake 层提供；Candidate v1 不反写 Phase 8 对象。
- 上表 DIRECT 行是当前生产事实；ADAPTER / PARTIAL / UNKNOWN 行是 Design Contract 或待 Phase 9-B 实现的缺口（逐项状态见 §9.1 与 production reconciliation 文档）。

---

## 23. Lifecycle

三类生命周期必须分离：

| 生命周期 | 状态示例 | 存放位置 |
|---|---|---|
| **Object State（Candidate）** | Design：`INTAKE_ACCEPTED` → `SEAL` → `FROZEN`，记录不可变；不携带状态字段（production NOT IMPLEMENTED） | Frozen Candidate 记录（closure §5；production 尚无） |
| **Governance Lifecycle** | DRAFT → EVALUATING → EVALUATED → REGRESSION_CHECKED → PROMOTION_REVIEW → PROMOTABLE / HOLD / REJECTED → PROMOTED（61 §7 冻结）；REVOKED / SUPERSEDED（Phase 8 events） | governance store `lifecycle` + authority events |
| **Runtime State** | CapabilityInstance：activating / running / stopped / failed（MVP §7.5） | Runtime Instance |

研究过的 RAW / INTAKED / CANDIDATE / EVALUATING / EVALUATED / PROMOTION_REVIEW / PROMOTABLE / PROMOTED / REVOKED 中：

- RAW = adapter 输出（不是 Candidate）。
- INTAKED / CANDIDATE = Intake Check 通过的时刻（v1 记录创建）。
- EVALUATING / EVALUATED / PROMOTION_REVIEW / PROMOTABLE / PROMOTED / REVOKED = governance lifecycle，进 store，不进 Candidate schema。
- ACTIVE / RUNNING = runtime lifecycle。

v1 因此**不携带 state 字段**。当前 prototype `candidate.json` 的 `state: "candidate"` 是冗余原型字段（Phase 8 消费者不读它），adapter 可丢弃。

---

## 24. Source Adapter Contract

只设计，不实现：

```text
Source
  -> Adapter       （fetch + verify：mutable ref -> immutable revision；内容 digest）
  -> Raw Intake    （source + artifact bytes/refs + raw metadata）
  -> Normalizer    （Capabilityization：识别可复用行为、提取 entrypoint、参数化、
                     剥离任务私有状态、提取契约、生成测试、构建 manifest、
                     计算 artifact_digest）
  -> Intake Check  （§19）
  -> CapabilityCandidate v1
```

Adapter **只负责**“把外部东西带到统一 Intake 边界”。

Adapter 禁止：

```text
- PROMOTE / APPROVE / REJECT quality
- Activate Runtime
- mutate PromotionDecision / AdoptionAuthority / lifecycle
- 绕过 Intake Check 直接创建 Candidate
```

失败语义：每个边界必须显式 fail-closed（05 §14：OpenHands 混合失败语义是反例）。无法验证 `resolved_revision` → `INTAKE_REJECTED`，不降级为“未验证候选”。

---

## 25. Candidate v1

### 25.1 JSON Example（agent source，映射当前 pilot F+ 数据）

```json
{
  "schema_version": "capability-candidate-v1",
  "candidate_id": "cand-deb537a46e21",
  "capability_id": "cap-fplus-csv-clean-statistical-report",
  "name": "csv-clean-statistical-report",
  "version": 1,
  "requester": {
    "kind": "human",
    "id": "operator-david",
    "request_id": "req-fplus-1"
  },
  "producer": {
    "kind": "agent",
    "id": "codex-artifact-builder-v0"
  },
  "source": {
    "source_type": "agent",
    "source_reference": "rollout:bd8491b7-f5ab-4ec4-bec2-bb07e0c45e6b",
    "resolved_revision": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2"
  },
  "artifact": {
    "artifact_digest": "sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592",
    "artifact_ref": "artifact:sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592"
  },
  "manifest": {
    "manifest_version": "0.1",
    "capability": {
      "name": "csv-clean-statistical-report",
      "description": "Cleans an order/sales CSV and writes a Markdown statistical report.",
      "version": 1
    },
    "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
    "contract": {
      "input": {"files": ["data/*.csv"], "args": {"freeform": ""}},
      "output": {"files": ["report.md"], "stdout": "string", "exit_code": 0}
    },
    "env": {},
    "secrets": [],
    "tests": [
      {"id": "t1",
       "input": {"files": ["data/data.csv"], "args": {}},
       "expected": {"files": ["report.md"]}}
    ],
    "sandbox": {
      "permissions": {"network": false, "fs_write": ["/output"]},
      "limits": {"timeout_seconds": 120, "output_bytes": 1048576}
    },
    "provenance": {
      "source_bundle_id": "01a0002b-6723-70b5-836d-6bd7af2af4dc",
      "source_artifact_digest": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2",
      "source_task_id": "fplus-cal-1",
      "source_execution_id": "bd8491b7-f5ab-4ec4-bec2-bb07e0c45e6b",
      "forged_artifact_digest": "sha256:87a6f062080231ca31b0a5cd7b6a7b13a0c8b23a9c7fb60695554ed562596592",
      "forge_timestamp": "2026-08-14T12:11:46.275Z"
    }
  },
  "provenance": {
    "created_at": "2026-08-14T12:11:46.275Z",
    "source_revision": "sha256:2b0b630587faa0b9664ff7248ef797941709a7b822b61342bfe53716aa43eae2",
    "build_ref": "bundle:01a0002b-6723-70b5-836d-6bd7af2af4dc",
    "request_id": "req-fplus-1"
  },
  "extensions": {
    "codex": {
      "applicability": "agent source produced from a Codex rollout",
      "session_id": "sess-01a0002b",
      "thread_id": "thread-01a0002b",
      "turn_id": "turn-01a0002b"
    }
  }
}
```

注意：示例中 `manifest.provenance.forged_artifact_digest` 等于 `artifact.artifact_digest`（v1 单 digest 规则）。当前 pilot/state 的 legacy 数据不满足此规则（FACT），Phase 9-B 归一化。

### 25.2 YAML Example（git source，展示 extension）

```yaml
schema_version: capability-candidate-v1
candidate_id: cand-abc123
capability_id: cap-my-capability
name: my-capability
version: 2
requester:
  kind: workflow
  id: nightly-promote-flow
  request_id: req-42
producer:
  kind: build_system
  id: ci-runner
source:
  source_type: git
  source_reference: https://github.com/acme/capability-repo.git
  resolved_revision: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0
artifact:
  artifact_digest: sha256:1111111111111111111111111111111111111111111111111111111111111111
  artifact_ref: artifact:sha256:1111111111111111111111111111111111111111111111111111111111111111
manifest:
  manifest_version: "0.1"
  capability:
    name: my-capability
    description: packaged from a git repository
    version: 2
  entrypoint:
    command: [python, main.py]
    workdir: artifact
  contract:
    input:
      files: ["data/*.csv"]
    output:
      files: ["report.md"]
      exit_code: 0
  env: {}
  secrets: []
  tests:
    - id: t1
      input: {files: ["data/data.csv"]}
      expected: {files: ["report.md"]}
  sandbox:
    permissions: {network: false, fs_write: ["/output"]}
    limits: {timeout_seconds: 120, output_bytes: 1048576}
provenance:
  created_at: "2026-08-18T00:00:00.000Z"
  source_revision: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0
  build_ref: "ci:job-42"
extensions:
  git:
    applicability: git source
    pr_number: 42
    commit_message: "Add my-capability"
```

### 25.3 Field Spec 汇总

见 §19 表；`source` / `artifact` / `requester` / `producer` / `provenance` 内部结构见 §11–§14、§18。

### 25.4 Immutability Semantics

**Design rule**：

```text
INTAKE_ACCEPTED
  -> SEAL
  -> FROZEN
```

- `schema_version` / `candidate_id` / `capability_id` / `version` / `artifact_digest` / `source.resolved_revision`：seal 后不可变。
- `manifest` / `source_reference` / `provenance`：seal 后不可变（可编辑窗口在 raw input / draft 阶段）。
- `extensions`：seal 后不可变；新语义用新 Candidate，不原地改写（审计要求）。
- 具体规则：CANDIDATE_FREEZE_RULES_V1（closure §5.3）；修改判定 = NEW_CANDIDATE_REQUIRED。

**Production status：NOT IMPLEMENTED**。当前 prototype 的 `candidate.json` / `manifest.json` / `tests/`
在 capabilityize 后仍可写（FACT，MVP §7.2）；该可写行为属于 legacy/prototype implementation，不是
v1 frozen semantics。Phase 9-B 实现 seal 后替换。

---

## 26. Validation

离线验证位于 `docs/archaeology/unified-runtime/phase9a1/`：

```text
validate_capability_candidate_contract.py   契约 validator + example main
test_capability_candidate_contract.py       18 个 unittest
```

运行方式：

```bash
python3 -m unittest docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_contract.py -v
python3 docs/archaeology/unified-runtime/phase9a1/validate_capability_candidate_contract.py
```

验证项与契约章节映射：

| # | 验证项 | 测试 |
|---|---|---|
| 1 | valid Candidate | `test_valid_candidate_accepted` |
| 2 | missing candidate identity | `test_missing_candidate_identity_rejected` |
| 3 | missing capability identity | `test_missing_capability_identity_rejected` |
| 4 | missing source | `test_missing_source_rejected` |
| 5 | missing artifact | `test_missing_artifact_rejected` |
| 6 | missing artifact digest | `test_missing_artifact_digest_rejected` |
| 7 | missing producer | `test_missing_producer_rejected` |
| 8 | requester ≠ producer | `test_requester_and_producer_are_separate` |
| 9 | evidence ≠ policy | `test_evidence_is_separate_object` + `test_policy_is_separate_object` |
| 10 | evidence ≠ decision | `test_evidence_is_separate_object` + `test_decision_is_separate_object` |
| 11 | extension 不污染 Core | `test_extension_does_not_pollute_core` |
| 12 | Git / OCI / Agent source compatibility | `test_git_oci_agent_source_compatibility` |
| 13 | Governance 与 Source 无关 | `test_governance_independent_of_source` |
| 14 | Phase 8 compatibility | `test_phase8_compatibility` |
| 15 | invalid raw input → INTAKE_REJECTED | `test_invalid_raw_input_rejected` |
| 附加 | provenance 绑定一致性 | `test_provenance_source_revision_mismatch_rejected` |
| 附加 | 单 digest semantics | `test_manifest_forged_digest_semantics_conflict_rejected` |

本阶段实测（Design Contract 的离线证明，不是 production 证明）：18 passed，`compileall` OK，
example main 输出 `CANDIDATE_CONTRACT_VALID INTAKE_ACCEPTED`；
Phase 9-A.1.1 closure 将离线套件扩展至 53 passed（closure §9）。

---

## 27. FACT / INFERENCE / DESIGN / UNKNOWN

### FACT（仓库代码/数据实测）

```text
- Bundle v0 是 frozen P0 immutable 输入；strict schema。
- capabilityizer 产出 candidate.json + manifest.json + implementation/artifact + tests；
  candidate.json 只有 candidate_id/name/state/source_bundle_ids。
- validator/evaluator 向 Candidate 目录写入 validation.json / evaluation.json。
- Phase 8 AUTHORITY_FIELDS = candidate_id/candidate_version/promotion_decision_id/
  evaluation_run_id/policy_version/artifact_digest/provenance。
- registry.promote() 生成 capability_id（cap-<uuid>）并要求 authority + store + anchor + ledger。
- runtime guard 对六处 digest 全等 fail-closed。
- capabilityizer forged_artifact_digest ≠ Phase 8 dir_digest（同一 artifact 实测不等）。
- pilot/state F+ registry entry 无 adoption 块（Phase 8 前历史数据）。
- Phase 7.2 协议有 13 个对象与 G1–G7；lifecycle 状态机已冻结。
- ImprovementCandidate 是考古层变更提案对象，与 CapabilityCandidate 不同。
- 外部证据 05：4/4 source/object separation；4/4 逻辑身份≠内容身份；4/4 输入校验边界；
  3/4 mutable→immutable；仅 in-toto 有完整 E/P/D 分层；4/4 无独立 provenance object；
  4/4 无 runtime enforcement / promotion / revocation / cross-system identity binding。
```

### INFERENCE（从 FACT 推导）

```text
- 运行时强制的是 dir_digest 语义，因此 v1 唯一 digest 应采用该语义。
- registry 自造 capability_id 是原型缺口；intake 层提供 capability_id 后 registry 应复用。
- 当前 candidate.json 的 state 字段无消费者，v1 可安全丢弃。
- 统一消费目标要求 E 模型（单对象自足）。
```

### DESIGN（本 contract 的新语义）

以下全部是 Design Contract 语义；production 未实现（状态见 §9.1 / production reconciliation 文档）：

```text
- CapabilityCandidate v1 schema（10 个核心键 + extensions）。
- capability_id 跨版本稳定且由 intake 首次生成（确定性派生，closure §3.4）。
- Candidate 不可变（Design rule：INTAKE_ACCEPTED -> SEAL -> FROZEN；production NOT IMPLEMENTED）。
- requester/producer 分离字段。
- source/artifact 子对象结构。
- provenance 最小块（created_at/source_revision/build_ref/request_id/intake_ref）。
- Intake Check / INTAKE_ACCEPTED / INTAKE_REJECTED。
- Governance Boundary invariant。
- Source Adapter 职责边界。
- evaluation binding：evidence 记录 artifact_digest + seal_digest（closure §5.3 R3/R6）。
```

### UNKNOWN（Phase 9-B 实施细节，不阻塞 Design closure）

```text
- formal CapabilityRequest 对象与 request_id 的真实数据来源。
- capability_id 确定性派生的生产落地与 legacy cap-<uuid> entry 迁移执行细节
  （设计规则已闭合：closure §3.4）。
- digest 归一化的生产改动顺序（capabilityizer / authority / guard 如何分批切换；
  编码方向已闭合：CANONICAL_ARTIFACT_IDENTITY_V1）。
- seal 的 production 持久化机制（设计规则已闭合：CANDIDATE_FREEZE_RULES_V1）。
- Git / OCI / Marketplace / Local adapters 的 resolved_revision 验证机制。
- manifest v0.2 是否需要移除 legacy forged_artifact_digest。
- Governance consumers（Authority / Registry / Guard）切换到 Candidate v1 的落地顺序。
```

---

## 28. Open Questions

1. CapabilityRequest 是否应该成为 v1.1 的正式对象？当前只有 `llm_proposal` + `confirm` 原型。
2. `capability_id` 的派生规则：确定性（name + namespace hash）还是 UUID？——Design 已闭合：确定性派生（closure §3.4）；production 落地待 Phase 9-B。
3. `forged_artifact_digest` 与 `dir_digest` 归一化：改 capabilityizer 还是加 intake adapter？——Design 已闭合：CANONICAL_ARTIFACT_IDENTITY_V1（closure §4.2）；生产改动顺序待 Phase 9-B。
4. Candidate v1 不可变 vs 当前 forge 可编辑窗口：编辑发生在 raw input / draft 阶段，还是引入 draft Candidate？——Design 已闭合：CANDIDATE_FREEZE_RULES_V1（closure §5）；seal 持久化待 Phase 9-B。
5. `source_type` 是否在 v1.1 收紧为封闭 enum？当前有意开放。
6. `extensions` 是否需要 schema 注册机制（类似 Phase 7.1 extension 的 applicability + provenance）？
7. Governance store 是否直接消费 Candidate v1 记录，还是继续用目录布局 + adapter？
8. Registry 复用 `capability_id` 后，现有已 promote 的 `cap-<uuid>` entry 如何迁移？

---

## 29. Phase 9-B Boundary

Phase 9-B 负责本 Design Contract 的 production realization。Phase 9-B 允许（本阶段之后）：

```text
- 新建 src/forge/candidate/（Candidate v1 类型 + Intake Check 实现）
- 新建 src/forge/sources/（adapter 接口；先实现 codex/agent adapter 迁移）
- 新建 src/forge/governance/ / registry / runtime 的 Candidate v1 消费适配
- 把 Capabilityizer 输出改为 Candidate v1 记录（含 capability_id）
- digest 归一化（统一为 CANONICAL_ARTIFACT_IDENTITY_V1，见 closure §4）
- Registry 复用 Candidate 的 capability_id
```

Phase 9-B 禁止（除非单独授权）：

```text
- 修改 Phase 7–8.5 冻结语义与历史 artifacts
- 修改 pilot/state 冻结评估证据
- 重写 AdoptionAuthority / Runtime Guard 的 fail-closed 语义
- 引入第二套 artifact digest
- 把 governance decision 塞进 Candidate
```

本阶段完成条件：

```text
1. 新文档（本文件）                 DONE
2. 新离线 validator + tests         DONE（18 passed）
3. 未修改 src/ pilot/ 历史 artifacts DONE
4. 未实现 Source Adapter            DONE（只设计）
5. 未 commit / push                 DONE
```

STOP：Phase 9-A.1 到此为止。
