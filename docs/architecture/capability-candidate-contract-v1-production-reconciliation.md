# CapabilityCandidate v1 Contract — Production Reconciliation（Phase 9-A.1.2）

- 阶段：Phase 9-A.1.2（CapabilityCandidate Contract / Production Reconciliation）
- 日期：2026-08-18
- 基线：
  - `docs/architecture/capability-candidate-contract-v1.md`（Design Contract，Phase 9-A.1）
  - `docs/architecture/capability-candidate-contract-v1-review.md`（反方审查，Phase 9-A.1）
  - `docs/architecture/capability-candidate-contract-v1-closure.md`（设计闭合，Phase 9-A.1.1）
  - `docs/archaeology/unified-runtime/phase9a1/`（离线 validator/tests）
- 范围：只允许新增本文档；未修改 `src/`、`pilot/`、`tests/`、Phase 7–8.5 历史 artifacts；未实现 Phase 9-B / Source Adapter；未 commit / push
- 最终判定：**CANDIDATE_CONTRACT_DESIGN_CLOSED_WITH_PRODUCTION_GAPS**

判定理由：CapabilityCandidate v1 的 **Design Contract 已闭合**（Review 四硬门 -> Closure 53 个离线测试通过），但 **production implementation 尚未完成**。本文档把“设计闭合”与“production 实现”彻底分开；下列 gap 全部属于 production（NOT_IMPLEMENTED），不改变 Design 闭合状态。

---

## 1. Purpose

“CapabilityCandidate v1 已闭合”只成立在设计层：

- `capability-candidate-contract-v1.md` 定义 CapabilityCandidate v1 Design Contract；
- `capability-candidate-contract-v1-closure.md` 以离线 validator/tests 证明四个核心 invariant 的设计语义闭合；
- production（`src/forge` + `pilot`）仍运行 prototype 实现，尚未产出或消费 Candidate v1。

本 reconciliation 文档的目标：

1. 记录 Design Closure 与 Current Production Reality 的边界；
2. 逐项列出 production gap 及其证据；
3. 明确 Phase 9-B Required Work；
4. 防止把 DESIGN / OFFLINE PROOF 当作 production 事实。

## 2. Design Closure

| 阶段 | 文档 | 判定 | 含义 |
|---|---|---|---|
| Phase 9-A.1 | contract-v1.md | `CANDIDATE_CONTRACT_VALID_WITH_UNKNOWN`（初始） | 初始设计判定过强 |
| Phase 9-A.1 Review | review.md | `PASS_WITH_FINDINGS` / `CANDIDATE_CONTRACT_PARTIAL` | 四硬门未闭合 |
| Phase 9-A.1.1 | closure.md | `CANDIDATE_CONTRACT_CLOSED` | 设计语义闭合 |
| Phase 9-A.1.2 | 本文档 | `CANDIDATE_CONTRACT_DESIGN_CLOSED_WITH_PRODUCTION_GAPS` | 设计闭合 + production 未实现 |

Closure 闭合的四硬门 + evaluation binding：

```text
A. Identity ownership：Intake 首次生成（确定性派生），Registry 只消费/校验，拒绝路径不再 mint（closure §3）。
B. Digest semantics：CANONICAL_ARTIFACT_IDENTITY_V1（allowlist-only digest + 精确布局，closure §4）。
C. Candidate seal：Draft -> Intake -> Seal -> Frozen Candidate；evidence 外置
   （CANDIDATE_FREEZE_RULES_V1，closure §5）。
D. Governance source independence：source-free semantic projection；deep scan 无 source 泄漏（closure §6）。
E. Evaluation binding：evidence 记录 artifact_digest + seal_digest；签发链校验（closure §5.3 R3/R6）。
```

离线证明：53 tests PASS（18 contract + 8 gap probes + 27 closure）；closure validator main 输出
`CANDIDATE_CONTRACT_CLOSED INTAKE_ACCEPTED`。这是 **Design Contract 的离线证明，不是 production 证明**。

## 3. Current Production Reality

以下均为 2026-08-18 实测 FACT：

| # | 对象/行为 | 当前 production 状态 | 证据 |
|---|---|---|---|
| 1 | CapabilityCandidate v1 | 不存在生产记录；capabilityizer 产出 prototype `candidate.json`（candidate_id / name / state / source_bundle_ids） | `src/forge/capabilityizer.py:116-117` |
| 2 | capability_id | `registry.promote()` / `reject()` 仍 mint `cap-<uuid>` | `pilot/registry.py:132,184` |
| 3 | artifact digest | A / B / C 三种编码并存且对同一 artifact 不等 | closure §2.2 |
| 4 | Candidate immutability | `candidate.json` / `manifest.json` / `tests/` 可写；`validation.json` / `evaluation.json` 在 intake 后写入同一目录 | `src/forge/capabilityizer.py:87-118`、`validator.py:96`、`evaluator.py:68` |
| 5 | evaluation binding | `evaluation.json` 不记录 `artifact_digest` / `seal_digest` | closure §2.3 |
| 6 | Governance consumption | AdoptionAuthority / Registry / Runtime Guard 不消费 Candidate v1 | review §7.3 |
| 7 | Source Adapter | 未实现 | contract §24（只设计） |
| 8 | CapabilityRequest | 无 formal 对象；只有 `llm_proposal.json` + `confirm.json` 原型 | contract §4.2 |

## 4. Identity Gap

| 维度 | 内容 |
|---|---|
| Design | Intake 首次生成 capability_id（确定性派生），Registry 只消费/校验；拒绝路径不 mint（closure §3） |
| Offline proof | `IdentityOwnershipTests`（4）+ capability_id format test PASS |
| Production | `registry.promote()` / `reject()` 仍 mint `cap-<uuid>`；prototype candidate 不含 capability_id |
| Status | **DESIGN_ONLY** |

Gap 本质：生产代码中 capability_id 的所有权与 Design Contract 相反；Candidate 没有 capability_id 字段，
Registry 没有“消费 Candidate 的 id”的路径。

## 5. Digest Gap

| 维度 | 内容 |
|---|---|
| Design | CANONICAL_ARTIFACT_IDENTITY_V1：allowlist-only digest + 精确布局（closure §4.2） |
| Offline proof | `CanonicalArtifactIdentityV1Tests`（5）PASS（SAME / MUST_CHANGE / 布局） |
| Production | A = capabilityizer forged digest；B = adoption_authority `dir_digest`；C = harness digest；三者并存且对同一 artifact 不等（closure §2.2） |
| Status | **DESIGN_ONLY** |

Gap 本质：production 没有唯一 canonical digest；`__pycache__/*.pyc` 使 `dir_digest` 无源漂移；
Runtime Guard 强制的仍是旧 `dir_digest` 语义，未切换到 allowlist-aware canonical digest。

## 6. Seal Gap

| 维度 | 内容 |
|---|---|
| Design | Draft -> Intake -> Seal -> Frozen Candidate；CANDIDATE_FREEZE_RULES_V1；evidence 外置 append-only（closure §5） |
| Offline proof | `CandidateFreezeRulesTests`（8）PASS |
| Production | `candidate.json` / `manifest.json` / `tests/` 普通可写；`validation.json` / `evaluation.json` 在 intake 后写入同一目录；无 write-once / 哈希链 |
| Status | **DESIGN_ONLY** |

Gap 本质：production 没有冻结点；“approved A, execute B” 的 evaluation→issuance 窗口仍然开放
（evaluation 无 digest 绑定，见 §7）。

## 7. Evaluation Binding Gap

| 维度 | 内容 |
|---|---|
| Design | evaluation/evidence 记录 artifact_digest + seal_digest；issue_authority / registry / guard 校验绑定一致（closure §5.3 R3/R6） |
| Offline proof | `CandidateFreezeRulesTests.test_seal_requires_byte_level_digest_match` 等 PASS |
| Production | `evaluation.json` 实测无 artifact_digest（keys：candidate_id, evaluated_at, evaluation_id, independent_reuse, novel_input_test, pass_rate, promotion_rule, regression, test_cases, verdict） |
| Status | **DESIGN_ONLY** |

Gap 本质：evaluation 只引用 candidate_id，不引用 artifact 字节；evaluation 后替换 artifact，
`issue_authority` 会用新 digest 签发，守卫无法发现。

## 8. Governance Consumption Gap

| 维度 | 内容 |
|---|---|
| Design | Governance(Candidate)：Evaluation / Regression / Promotion / Adoption 统一消费 Candidate v1；source-free semantic projection（closure §6.2） |
| Offline proof | `GovernanceSourceIndependenceTests`（3）PASS；5 种 source 突变投影 deep-equal |
| Production | AdoptionAuthority / Registry / Runtime Guard 消费 prototype 目录（`candidate.json` + `manifest.json` + artifact dir），不消费 Candidate v1；生产层无 source-free projection |
| Status | **DESIGN_ONLY** |

Gap 本质：Source Independence 只被离线 validator 证明；生产消费者还没有 Candidate v1 消费路径，
“不读 source_type” 没有生产代码证据。

## 9. Phase 8 Compatibility

- Phase 8 冻结语义保持：`AUTHORITY_FIELDS` / `BINDING_KEYS` / `PROVENANCE_KEYS` / write-once authority ledger / revocation events / runtime guard fail-closed 均不改变（closure §8.1）。
- DIRECT 字段是当前生产事实：`candidate_id`、`version` int → `"v{N}"` 转换。
- ADAPTER / PARTIAL 字段是 Design：`capability_id` 复用、`artifact_digest` 归一、producer 映射、request_id。
- Candidate v1 尚未接入任何 Phase 8 消费者；Phase 9-B 的适配不得改写 Phase 8 historical semantics（contract §22 约束）。

## 10. Phase 9-B Required Work

Phase 9-B 负责 production realization（本阶段不实现）：

1. 实现 Intake 层：Candidate v1 产出（含 capability_id）、Intake Check、确定性 capability_id 派生。
2. Registry：删除 promote / reject 的 capability_id mint，改为消费 Candidate 的 id；处理 legacy `cap-<uuid>` 迁移。
3. Digest：统一 CANONICAL_ARTIFACT_IDENTITY_V1（capabilityizer 编码、authority / guard 重算、allowlist 持久化）。
4. Seal：实现 write-once Frozen Candidate 持久化；manifest / tests / artifact 编辑窗口移到 draft。
5. Evaluation binding：`evaluation.json` / evidence 记录 artifact_digest + seal_digest；issue_authority 校验。
6. Governance：Evaluation / Promotion / Adoption / Registry / Runtime 接入 Candidate v1；落地 source-free governance projection。
7. Source Adapter：先实现 codex / agent adapter（contract §24）。
8. 保持 Phase 7–8.5 冻结语义与历史 artifacts 不变。

## 11. FACT / DESIGN / UNKNOWN

### FACT（本阶段实测）

```text
- 53 个离线测试通过（18 contract + 8 gap probes + 27 closure）。
- capability_id 生产者为 registry.promote()/reject()；prototype candidate.json 无 capability_id。
- 三种 digest 编码并存；pycache 使 dir_digest 无源漂移。
- candidate.json / manifest.json / tests 可写；evaluation.json 无 artifact_digest。
- Governance consumers 不消费 Candidate v1。
```

### DESIGN（已闭合）

```text
- capability_id ownership：Intake 首次生成，Registry 只消费。
- CANONICAL_ARTIFACT_IDENTITY_V1。
- CANDIDATE_FREEZE_RULES_V1（INTAKE_ACCEPTED -> SEAL -> FROZEN；evidence 外置）。
- Evaluation binding（artifact_digest + seal_digest）。
- source-free governance projection。
```

### UNKNOWN（Phase 9-B 实施细节，不阻塞 Design closure）

```text
- formal CapabilityRequest 对象与 request_id 的真实数据来源。
- legacy cap-<uuid> entry 的自动迁移执行细节。
- digest 归一化的生产改动顺序。
- seal 的 production 持久化落地方式。
- Source Adapter（Git / OCI / Marketplace / Local）的 resolved_revision 验证机制。
- Governance consumers 切换到 Candidate v1 的落地顺序。
```

## 12. Final Verdict

```text
CANDIDATE_CONTRACT_DESIGN_CLOSED_WITH_PRODUCTION_GAPS
```

判定依据：

1. Design Closure：Review 四硬门 + evaluation binding 已在设计层闭合（closure，53 个离线测试通过）。
2. Production Gaps：identity / digest / seal / evaluation binding / governance consumption 全部 NOT_IMPLEMENTED（§4–§8）。
3. 语义边界：contract-v1.md 只定义 Design Contract；Phase 9-B 才负责 production realization。
4. 禁止混淆：DESIGN / OFFLINE PROOF 不得被表述为 production 事实；53 tests 是离线设计证明，不是生产验证。

STOP：Phase 9-A.1.2 到此为止。
