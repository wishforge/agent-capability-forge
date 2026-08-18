# CapabilityCandidate v1 Contract — Phase 9-A.1 反方审查报告

- 审查对象：`docs/architecture/capability-candidate-contract-v1.md`
- 审查范围：Phase 9-A.1 文档 + `phase9a1/` 离线验证器/测试 + `src/forge/`、`pilot/` 真实代码
- 审查日期：2026-08-18
- 审查立场：反方审查（不重复总结，只找不闭合点）
- 审查约束：未修改任何生产代码；未实现 Phase 9-B；未 commit / push
- 审查判定：**PASS_WITH_FINDINGS**
- 合同判定：**CANDIDATE_CONTRACT_PARTIAL**

---

## 1. Executive Summary

CapabilityCandidate v1 的方向是正确的：10 个 Core 键 + `extensions` 的边界、Intake Check fail-closed、Evidence/Policy/Decision 对象分离、Requester/Producer 字段分离，这些设计在离线 validator 中可机器验证，且与 Phase 7.2/61 的对象分层一致。

但它**还不是** "Capability Intake → Governance → Registry → Runtime 的稳定 Canonical Object"。反方审查发现四个核心语义在真实代码中没有闭合：

1. **Identity ownership 不闭合**：`capability_id` 今天唯一的生产者是 Registry（`pilot/registry.py:132`，promote 时 `cap-<uuid>`）；prototype candidate 完全不含 `capability_id`，没有任何代码消费 v1 的 `capability_id`。"intake 提供 capability_id" 只是 DESIGN。
2. **Digest semantics 不闭合**：仓库存在三种 digest 编码（capabilityizer 的 `forged_artifact_digest`、`adoption_authority.dir_digest`、`harness._dir_digest`）；合同声称实测 `dir=b94ec2a6`，当前状态不可复现（现为 `5ac13b1a`/`1238c032`）；artifact 目录含 `__pycache__/*.pyc`，`dir_digest` 会在无源代码变更时漂移。
3. **Immutability 无法保证**：`candidate.json` / `manifest.json` / `tests/` 都是普通可写文件；`validation.json` / `evaluation.json` 在 intake 之后写入同一目录；没有任何 write-once / 哈希链机制。`evaluation.json` 不记录 `artifact_digest`，Evaluation 与 artifact 字节无绑定，"approved A, execute B" 在 evaluation→authority issuance 窗口真实存在。
4. **Phase 8 semantic binding 为 PARTIAL**：`candidate_id`/`candidate_version` DIRECT，但 `artifact_digest` 编码不一致、`capability_id` 由 Registry 自造、`producer` 语义在 bundle 内部已有两个不同值（`identity.producer="codex-cli-0.144.4"` vs `provenance.producer="codex-artifact-builder-v0"`）、`request_id` 无对象。

18 个 phase9a1 测试全部通过，但只证明离线 validator 的行为；生产消费者（AdoptionAuthority / Registry / Runtime Guard）目前**不读取任何 Candidate v1 记录**。因此原文档的最终判定 `CANDIDATE_CONTRACT_VALID_WITH_UNKNOWN` 过强，应降级为 `CANDIDATE_CONTRACT_PARTIAL`。

---

## 2. Contract Strengths

| # | 优点 | 证据 |
|---|---|---|
| S1 | Core/Extension 分离且未知顶层键 fail-closed | `phase9a1/validate_capability_candidate_contract.py:55-58` |
| S2 | Evidence/Policy/Decision/AdoptionAuthority 禁止嵌入 Candidate | `FORBIDDEN_CORE_KEYS`，测试 `test_evidence_is_separate_object` 等 |
| S3 | Intake 规则 fail-closed：任何缺失/非法字段 → `INTAKE_REJECTED` | `intake()` 全部检查无 violation 才 ACCEPTED |
| S4 | Requester/Producer 是独立字段，不合并 | `check_party` 分别校验；测试 `test_requester_and_producer_are_separate` |
| S5 | Source 类型开放（`future_source_xyz` 可过） | `SOURCE_TYPES` 非封闭 enum；测试 `test_git_oci_agent_source_compatibility` |
| S6 | `version` int → `"v{N}"` 的 Phase 8 adapter 与 `adoption_authority_producer.py:124` 行为一致 | `phase8_compatibility()` |
| S7 | Provenance 最小化，不做"万能 provenance"；Governance provenance 独立 | `PROVENANCE_KEYS` 在 `pilot/adoption_authority.py:30` |
| S8 | Runtime 侧的六处 digest 全等检查是真实保护 | `pilot/runtime_adoption_guard.py:199-210` |

---

## 3. Identity Audit

### 3.1 真实代码事实

| 标识符 | 今天谁生成 | 谁消费 | 位置 |
|---|---|---|---|
| `candidate_id` | `capabilityize()`：`cand-<uuid4 hex[:12]>` | validator / evaluator / `issue_authority` / Registry `adoption.candidate_id` / Runtime Guard | `src/forge/capabilityizer.py:116-117` |
| `capability_id` | `registry.promote()/reject()`：`cap-<uuid4 hex[:12]>` | B3 invoke evidence / treatment.ref | `pilot/registry.py:132,184`；`pilot/harness.py:740-754` |
| `version` | manifest `capability.version`（int，恒 1） | `issue_authority` 转 `"v1"`；Registry entry 存 int | `adoption_authority_producer.py:124` |
| `source_revision` | v1 schema 才有；prototype 只有 `provenance.source_artifact_digest` + `candidate.json.source_bundle_ids` | 无 | `capabilityizer.py:90,108` |
| `artifact_digest` | manifest `forged_artifact_digest`（编码 A）；authority 另算 `dir_digest`（编码 B） | authority/decision/run/candidate-store/entry/guard | `capabilityizer.py:87`；`adoption_authority.py:52` |

### 3.2 逐问回答

1. **capability_id 到底谁拥有？** 今天 Registry 在 promote/reject 时拥有并生成（FACT）。v1 说 intake 拥有、Registry 复用（DESIGN，`contract §10/§22`）。两者之间没有任何代码路径：Registry 不知道 Candidate 的 `capability_id`，Candidate 也没有这个字段。**所有权未闭合。**
2. **Candidate 是不是 logical capability version？** 不是。v1 明确 Candidate 是一次 intake 的治理对象，`version` 只是属性；MVP §7.4 的 CapabilityVersion 才是不可变逻辑版本（DESIGN）。prototype 恰好一 candidate 一 version，但合同允许多 candidate 同 version。
3. **candidate_id 是否真正是 intake instance identity？** 是（prototype FACT，v1 DESIGN 一致）。每个 `capabilityize` 调用生成新 `cand-<uuid>`；`capabilityize` 拒绝已存在同名 candidate 目录（`FileExistsError`）。
4. **Registry 是否会再次生成/覆盖 capability_id？** 会。`registry.promote()`/`reject()` 每次都生成新 `cap-<uuid>`（FACT）。v1 要求 Registry 改为复用（DESIGN），但没有实现、没有迁移方案（UNKNOWN，合同 Open Q8 自己承认）。
5. **两个 Candidate 指向同一 capability_id 是否合理？** 合理（多来源/多次 intake），validator 也不阻止。但下游未定义"谁成为 Registry entry / 谁参与 promotion"的规则：同一 name 第二次 promote 会 `ENTRY_BINDING_CONFLICT`（`registry.py:78-86`），不同 name 同 capability_id 则无任何冲突检查。**ALLOW at intake / BLOCK at registry / winner 规则 UNKNOWN。**
6. **两个 Candidate 不同 capability_id 引用同一 artifact？** 允许（validator 不要求 digest 唯一；内容寻址本应多引用）。每个 Candidate 可独立走 authority，运行时各自校验 digest，语义一致。ALLOW。
7. **identity collision 如何处理？** `candidate_id` 靠 uuid4 概率防碰撞，无 store 级唯一性检查（validator 无状态）；`capability_id` 无格式/命名空间/派生规则，碰撞处理未定义（UNKNOWN）。Registry 唯一的碰撞机制是 name 文件级重复，不是 capability_id 级。

**Identity 审查结论**：`candidate_id` 语义闭合；`capability_id` 所有权、派生、碰撞、迁移全部未闭合。

---

## 4. Digest Audit

### 4.1 仓库中实际存在的三种编码

| 编码 | 实现 | 表达式 | 实测值（当前 main.py） |
|---|---|---|---|
| A：capabilityizer `forged_artifact_digest` | `src/forge/capabilityizer.py:87-89` | `sha256(canonical({"files":[{"path":"main.py","digest":sha256:...}]}))`，只含声明文件 | `sha256:87a6f062...` |
| B：`adoption_authority.dir_digest` | `pilot/adoption_authority.py:52-59` | `sha256(canonical({rel_path:"sha256:..."}))`，含目录全部文件 | 仅 main.py：`5ac13b1a...`；含 `__pycache__`：`1238c032...` |
| C：`harness._dir_digest` | `pilot/harness.py:59-62` | `sha256(canonical({"files":{rel_path:"sha256:..."}}))` | `sha256:657057ac...` |

历史 B3 实验记录中的 artifact digest `657057ac...`（`research/experiments/formal-pilot-gate-review.md:86`）正是编码 C，不是编码 B。合同文档声称的 `dir=b94ec2a6...` 在当前仓库状态**不可复现**（pilot/state 被 `.gitignore:3` 排除，是可变实验目录）。

### 4.2 逐问回答

1. **两个 digest 的语义**：A 表达"capabilityizer 声明/锻造的文件集合"；B/C 表达"运行时将挂载的目录字节"（B 是当前 guard 强制语义）。两者都是 forged artifact 的内容身份，**语义相同、编码不同** —— 这正是必须归一化的原因。A 与 B 的差别不只是编码：A 只哈希 `main.py`，B 哈希目录里所有文件（包括 Python 生成的 `__pycache__/*.pyc`）。
2. **是否应该统一？** 应该。运行时强制的是 B，v1 选 B 作唯一语义正确；但当前真实数据不满足（`87a6f062...` vs `5ac13b1a...`），v1 validator 只能校验字符串相等，无法校验语义（它看不到 artifact 字节）。
3. **canonical artifact identity 由谁定义？** 事实上由运行时强制点定义：`adoption_authority.dir_digest` + Registry `promote()` 重算 + Guard `verify_at_mount()`（FACT）。v1 应直接采纳该编码并冻结 artifact 字节，而不是让 intake 自己发明一种。
4. **Candidate 是否只存一个 digest？** 每个 artifact 对象只存一个 digest（正确）；但 Candidate 需要两个不同对象：source 的 `resolved_revision`（输入）与 artifact 的 `artifact_digest`（输出）。合同已区分，方向正确。
5. **artifact_ref 是否必需？** 不必需。`artifact_ref` 只是 `"artifact:" + digest` 的可派生冗余，且 validator 只要求非空字符串（`validate_capability_candidate_contract.py:100-104`），不要求等于 digest —— 可以指向另一个 digest 却照样 INTAKE_ACCEPTED（probe 已验证）。建议删除，或绑定 `== "artifact:" + artifact_digest`。
6. **source artifact digest 与 forged artifact digest 是否都需要？** 都需要（输入身份 vs 输出身份），但原型把 source digest 同时放在 `manifest.provenance.source_artifact_digest` 与 `source.resolved_revision`，v1 没有 invariant 绑定二者，存在双份来源真相。
7. **Bundle digest 与 runtime artifact digest 是否混淆？** v1 schema 不混淆（source vs artifact 两个子对象）；混淆点在实现：capabilityizer 的 `source_artifact_digest` 是 `sha256({"bundle_digests":[...]})`，不是任何 bundle 的 digest，也不等于 `source.resolved_revision` 示例值。真实 bundle digest 是 `ccbcb2cb...` 等四个值，示例里的 `2b0b6305...` 是另一个 hash，无法从当前状态验证。

### 4.3 附加事实：digest 会无源漂移

`pilot/state/candidates/F+/csv-clean-statistical-report/implementation/artifact/` 与 registry artifact 副本均含 `__pycache__/main.cpython-313.pyc`。编码 B 对当前目录实测为 `1238c032...`，排除 `__pycache__` 后为 `5ac13b1a...`。也就是说：任何在本地执行/编译 `main.py` 的动作都会改变 `dir_digest`，而源代码一行未改。Phase 8 guard 对"已绑定 authority"的 artifact 会正确 BLOCK（digest mismatch），但这也意味着一个合法 artifact 可能因为 Python 字节码缓存而无法激活。v1 必须定义 artifact 的显式文件集合（或 digest 前排除生成物/冻结目录），否则 canonical digest 不稳定。

**Digest 审查结论：`DIGEST_MODEL_PARTIAL`。** 方向正确（B 为唯一语义），但三种编码并存、pycache 污染、validator 无法验证语义、artifact_ref 未绑定、合同实测值已漂移。

---

## 5. Immutability Audit

### 5.1 Candidate 何时真正被冻结？

**没有冻结点。** 真实写入路径：

| 阶段 | 写入内容 | 位置 |
|---|---|---|
| Capabilityize | `candidate.json` + `manifest.json` + `implementation/artifact/` + `tests/` | `capabilityizer.py:87-118` |
| 重建 | `harness` 直接 `shutil.rmtree(stale_cand)` 删除旧 candidate 再重建 | `harness.py:573-575` |
| Validation | 向 candidate 目录写 `validation.json` | `src/forge/validator.py:96` |
| Evaluation | 向 candidate 目录写 `evaluation.json` | `src/forge/evaluator.py:68` |
| Authority | 读 candidate/manifest，写 `adoption_store.json` 的 candidates 记录 | `adoption_authority_producer.py:129-145,223-226` |
| Promote | 读 manifest，复制 artifact 到 registry | `registry.py:118,124-126` |
| Force promote | 删除旧 registry entry + artifact 目录 | `harness.py:596-600` |

`candidate.json`、`manifest.json`、`tests/` 全部是普通文件，MVP §7.2 明说用户可编辑 manifest/tests（FACT）。没有任何 write-once、哈希链或内容寻址记录来检测 intake 后的修改。

### 5.2 逐问回答

1. **Candidate 什么时候真正被冻结？** 从不。v1 的 `INTAKE_ACCEPTED` 只存在于离线 validator 的返回值里；没有任何持久化机制把它变成不可变记录。
2. **manifest 是否还能修改？** 能。文件可写；`issue_authority` 和 `registry.promote` 在各自时刻重新读取，`evaluation.json` 不记录 manifest digest，所以 evaluation 后的 manifest 修改会静默进入 authority/registry。
3. **tests 是否还能修改？** 能。`validator.py`/`evaluator.py` 在运行时刻读取 tests，结果不绑定 tests 内容 digest；修改 tests 后重跑或直接改历史结果都无法被检测。
4. **artifact 是否能重新生成？** 能。重建路径删除旧 candidate；force promote 删除旧 registry entry。artifact 字节在 authority 签发后被 guard 保护，但在签发前可任意更换。
5. **evaluation 是否可能引用旧 artifact？** 是。`evaluation.json` 只有 `candidate_id`，**没有 `artifact_digest`**（实测 keys：`candidate_id, evaluated_at, evaluation_id, independent_reuse, novel_input_test, pass_rate, promotion_rule, regression, test_cases, verdict`）。artifact 在 evaluation 后被替换，`issue_authority` 会用新 digest 签发 authority，而 evaluation 证据仍指向旧字节 —— 守卫无从发现。
6. **Candidate immutable 是否重新引入 "approved A, execute B"？** 当前的保护只覆盖 authority 签发之后（`runtime_adoption_guard.py:199-210` 六处 digest 全等 + `verify_at_mount`）。签发之前的窗口（evaluation → issuance）没有绑定，**"approved A, execute B" 风险真实存在且未被 v1 关闭**。

### 5.3 DESIGN 建议（不修改生产代码）

Draft Candidate → Frozen Candidate 是合理方向，但还不够：必须定义 Frozen 的持久化机制（write-once 记录 + 内容哈希），并把 `validation.json` / `evaluation.json` 明确排除在冻结记录之外（它们应作为外部 evidence 引用 candidate 的 digest）。仅增加一个状态字段不会带来不可变性。

**Immutability 审查结论：无法保证。** 这是 DESIGN 承诺，不是机器行为。

---

## 6. Requester / Producer / Request Audit

### 6.1 真实代码事实

| 角色 | 真实值 | 位置 |
|---|---|---|
| Bundle `identity.producer` | `codex-cli-0.144.4` | `pilot/state/bundle_store/bundles/01a0002b-6723-70b5-836d-6bd7af2af4dc/bundle.json:11`（gitignored 实测） |
| Bundle `provenance.producer` | `codex-artifact-builder-v0` | 同文件 `:106`；`BUILDER_PRODUCER` 常量 |
| Authority issuer | `confirm.operator` = `rehearsal-runner`，或 `DEFAULT_ISSUER_ID` = `pilot-rehearsal` | `adoption_authority_producer.py:119-126` |
| Requester | 无；原型只有 `llm_proposal.json` + `confirm.json`，都不是 formal request | `pilot/state/llm_proposal.json` |

### 6.2 逐问回答

1. **requester OPTIONAL 是否合理？** 对无主/外部来源（OCI、marketplace）合理；但对 agent-produced capability 意味着完全丢失 request lineage。合同没有按 source_type 区分 REQUIRED/OPTIONAL，属于统一放宽。
2. **什么情况下 request_id 必须存在？** 合同没有定义。`requester.request_id` 与 `provenance.request_id` 都是 optional 且互不绑定（probe 已验证可指向不同值仍 ACCEPTED）。
3. **agent-produced capability 是否必须有 request lineage？** 按本仓库的真实来源（rollout + bundle + proposal + operator confirm），当前没有任何 formal request 对象；`request_id` 是 DESIGN/UNKNOWN。反方意见：agent-produced 至少应要求 `requester`（operator/workflow）或 `provenance.request_id` 之一，否则审计责任链断在生成侧。
4. **external artifact 是否可以没有 request？** 可以；这支持 OPTIONAL。但应显式声明"无 requester 的 candidate 默认 governance 要求更严（例如必须人工确认）"。
5. **requester 和 producer 是否始终可以不同？** 字段分离是 FACT；值相同时合同允许（"即使值相同也必须分别记录"），合理。但 validator 只保证字段存在，不保证语义角色。
6. **AdoptionAuthority issuer 是否必须与 producer 分离？** 必须（审计责任不同），代码里二者来源也确实不同（FACT）。但**没有任何 invariant 阻止 issuer_id == producer.id**：`issuer_allowed()` 只查信任名单，不比较 producer。v1 Candidate 不携带 issuer，所以该分离只能在 authority 签发层强制 —— 现在是 DESIGN，不是 BLOCK。

---

## 7. Source Independence Audit

### 7.1 离线层（FACT）

- `governance_projection()` 的代码路径从不读取 `source.source_type` 做分支（`validate_capability_candidate_contract.py:211-223`）。
- `test_governance_independent_of_source` 覆盖 `git/oci/agent/future_source_xyz`，投影键集一致（FACT，18 tests 实测通过）。

### 7.2 弱点（FACT）

- 投影**把整个 `source` 对象透传给下游**，包括 `source_type`。测试只断言顶层没有 `source_type` 键，不断言投影值中不存在 `source_type`。probe `test_probe_governance_projection_carries_source_type` 实测：`governance_projection(cand)["source"]["source_type"] == "agent"`。
- 因此"Governance 与 Source 无关"在离线层也只是"投影函数自身不分支"，而不是"下游拿不到 source_type"。

### 7.3 生产层（DESIGN_ONLY）

`adoption_authority.py` / `registry.py` / `runtime_adoption_guard.py` **目前不消费 Candidate v1**，它们消费的是 prototype 目录（`candidate.json` + `manifest.json` + artifact dir）。所以"Evaluation/Promotion/Adoption/Registry/Runtime 不读 source_type"没有任何生产代码证据。如果 v1 声称 Evaluation(Candidate)、Adoption(Candidate) 统一消费，必须先有消费路径，否则 Source Independence 是文档声明。

**Source Independence 审查结论：离线 validator 行为 FACT；生产层 DESIGN_ONLY；投影携带 source_type 使声明弱于文档表述。**

---

## 8. Phase 8 Compatibility Audit

| Candidate v1 字段 | Phase 8 消费点 | 真实语义 | 兼容级别 |
|---|---|---|---|
| `candidate_id` | `AUTHORITY_FIELDS`、Registry `adoption.candidate_id`、Guard | 同一字符串贯穿 | **DIRECT**（FACT） |
| `version` (int) | Authority `candidate_version="v1"`；Registry entry `version=1` | `issue_authority` 已有 int→`vN` 转换 | **DIRECT/ADAPTER**（FACT） |
| `artifact.artifact_digest` | Authority/decision/run/candidate-store/entry/guard 六处 | 原型 manifest 是编码 A，Phase 8 是编码 B，二者不等 | **PARTIAL**（FACT） |
| `capability_id` | Registry entry `capability_id`（promote 自造） | v1 要求 intake 提供、Registry 复用；无实现、无迁移 | **ADAPTER / 未闭合**（DESIGN） |
| `producer` | Authority `issuer_id`（operator） | bundle 内 `identity.producer` 与 `provenance.producer` 已不同，v1 单 producer 对象无映射规则；issuer≠producer 无强制 | **PARTIAL**（FACT） |
| `source` | Manifest `provenance.source_bundle_id/source_artifact_digest/source_task_id` | 扁平字段 → 子对象；`source_type` 是新语义 | **ADAPTER**（DESIGN） |
| `request_id` | Provenance | 仓库无 formal request 对象 | **UNKNOWN** |
| `manifest` | Registry entry `manifest`（promote 时嵌入） | 直接嵌入，但无 digest 绑定 | **DIRECT 形状 / PARTIAL 完整性** |

重点风险：

- **version int vs "v1"**：映射本身没问题（producer 已实现）。真正的缺口是 validator 不检查顶层 `version == manifest.capability.version`（probe 实测 version=2 + manifest version=1 仍 ACCEPTED），可能签发 `v2` authority 但 registry 嵌入 version 1 的 manifest。
- **capability_id 自造问题**：合同已正确诊断（§4.2/§22），但没有给出闭合方案；现有 `cap-d24c50c27fa8` 等已 promote entry 的迁移未定义。
- **evaluation 不参与绑定链**：Phase 8 的 `AUTHORITY_FIELDS` 不含 manifest/tests digest，Guard 也不校验 evaluation 引用的字节；这不是 v1 引入的，但 v1 没有修复。

---

## 9. Candidate Model A/B/C/E Reassessment

### 9.1 文档论证中的弱点

文档对 E 的核心论据是"统一消费：Evaluation(Candidate)、Adoption(Candidate) 单对象自足"。但 E 的 `artifact` 只是 digest 引用，**Evaluation 和 Runtime 仍然需要 artifact 字节**（`validator.py`/`evaluator.py` 直接读 `implementation/artifact` 目录）。Model A 也可以携带同一个 digest 引用。因此"A 缺统一消费、E 有统一消费"的对比不成立：E 并不比 A 更自足，只是把 source/producer/request 元数据一起打包。

### 9.2 E 的真实定位

E 是合理的 **Governance Intake Object**：把 capability_id、candidate_id、version、source、artifact、producer、requester 绑定在一次 intake 上。但全管线的 canonical object 不止一个：

- Intake 层：CapabilityCandidate v1（E）—— intake canonical object；
- 发布层：Registry Entry（或 MVP §7.3/7.4 的 Capability + CapabilityVersion）—— logical canonical object；
- 运行层：CapabilityInstance —— runtime object。

合同标题把 Candidate 说成整条链的 "稳定 Canonical Object" 过强；准确说法应是 **canonical governance intake object**。Registry entry 仍是另一个对象（含 `state=promoted/rejected`，Candidate 明确不带 state）。这是 Model E 与 Model C 的边界：E 吸收了 intake 记录，但没有消除下游 Capability 对象。

### 9.3 E 的 counterexamples / 边界问题

1. 同一 capability_id + version + 两个来源 → 两个 Candidate；谁有资格 promote、冲突时谁是 winner，未定义。
2. Candidate 不可变声明与 `validation.json`/`evaluation.json` 同目录写入冲突；E 没有定义存储边界（哪些文件属于不可变记录）。
3. E 把 `source` 放进 governance projection，削弱了 Source Independence（见 §7）。
4. `artifact_ref` 冗余且未绑定 digest。
5. Replay 问题：`capability_id` 派生规则未定；若沿用 Registry 的 uuid 风格，同一 intake 重放会得到不同 capability_id，不可重放。

### 9.4 是否需要新 Model D？

不需要新字母：把 E 限定为 intake object，并显式命名 Registry Entry（Capability + CapabilityVersion）为 logical object，即可覆盖 D 的全部内容。文档应补一句对象层声明，而不是引入第四套模型。

**结论：E 仍是最佳 intake 模型（比 A/B/C 好），但"E 因统一消费而胜出"的证据不成立；E 的优势是绑定完整性 + 单次 intake 记录。**

---

## 10. Adversarial Matrix

| # | 场景 | 判定 | 原因 |
|---|---|---|---|
| 1 | 同一 artifact + 两 Candidate | ALLOW（intake）/ BLOCK（registry 同名 promote）/ UNKNOWN（winner 规则） | validator 不要求 digest 唯一；`registry.promote` 对同 name 不同 binding 抛 `ENTRY_BINDING_CONFLICT`；不同 name 同 capability_id 无检查 |
| 2 | 同一 Candidate + 两 artifact | BLOCK（单记录内）/ UNKNOWN（evaluation→issuance 窗口） | schema 单 `artifact_digest`；但 evaluation 无 digest，签发前换字节会被静默吸收 |
| 3 | 同一 capability + 两 version | ALLOW（contract）/ BLOCK（当前 registry） | v1 允许 version≥1；`experimental_registry_v1` 恒 version=1、同名重复 promote 被拒 |
| 4 | same source ref + 不同 resolved revision | ALLOW | 两个不同 intake 实例，validator 不比较 source_reference；旧 revision 候选的 stale 处理 UNKNOWN |
| 5 | mutable source ref 在 intake 后改变 | ALLOW | Candidate 记录保留原 resolved_revision（设计）；无 re-resolve / supersede 机制 |
| 6 | artifact bytes 在 intake 后改变 | 签发前：ALLOW（未检测）；签发后：BLOCK | `evaluation.json` 无 digest；`runtime_adoption_guard.py:199-210` + `verify_at_mount` 在激活时 BLOCK |
| 7 | manifest 在 evaluation 后改变 | ALLOW（未检测） | 无 manifest digest 绑定；`registry.promote` 在 promote 时重新读取 manifest 并嵌入 |
| 8 | tests 在 evaluation 后改变 | ALLOW（未检测） | validation/evaluation 不记录 tests digest |
| 9 | requester = producer | ALLOW | 字段分离是要求，值相同被设计允许（"即使值相同也必须分别记录"） |
| 10 | producer = issuer | ALLOW（无 invariant） | `issuer_allowed` 只查信任名单；Candidate 不携带 issuer，无法在 intake 层强制 |
| 11 | agent-produced capability 缺 request | ALLOW | `requester` 全局 OPTIONAL；无 request lineage 规则 |
| 12 | Registry 生成不同 capability_id | ALLOW（现状）/ BLOCK（v1 目标） | 今天 Registry 必然自造 `cap-<uuid>`；v1 只声明不实现，迁移 UNKNOWN |
| 13 | forged_artifact_digest ≠ dir_digest | 现状：ALLOW（guard 不看 manifest 值）；v1：BLOCK（字符串相等检查） | 实测 `87a6f062...` ≠ `5ac13b1a...`/`1238c032...`；v1 validator 只能查字符串相等，不能验证编码语义 |
| 14 | source-specific 字段注入 Core | BLOCK | `UNKNOWN_CORE_FIELD` fail-closed；`extensions` 允许对象型扩展（FACT） |

---

## 11. Findings

| # | 严重度 | 性质 | 发现 |
|---|---|---|---|
| F1 | HIGH | FACT | `capability_id` 唯一真实生成者是 Registry（`registry.py:132,184`）；prototype candidate 无此字段；v1 的 intake 所有权无消费路径、无派生规则、无碰撞处理、无迁移方案 |
| F2 | HIGH | FACT | 三种 digest 编码并存（A/B/C）；合同实测 `b94ec2a6` 不可复现；`evaluation.json` 无 digest；doc 的 FACT 基线是 gitignored 可变状态 |
| F3 | HIGH | FACT | artifact 目录含 `__pycache__/*.pyc`，编码 B 因此无源漂移（`1238c032` vs `5ac13b1a`）；capabilityizer 编码 A 只哈希 main.py，二者对"同一 artifact"语义不同 |
| F4 | HIGH | FACT | Evaluation 与 artifact 字节无绑定 → evaluation→issuance 窗口可换 artifact，authority 静默绑定新字节，"approved A, execute B" |
| F5 | HIGH | FACT | Candidate immutability 无机制：candidate.json/manifest/tests 可写；validation/evaluation 在 intake 后写入同一目录；无 write-once/哈希链 |
| F6 | MEDIUM | FACT | `governance_projection` 透传整个 `source`（含 `source_type`）；生产消费者不读 Candidate v1，Source Independence 生产层为 DESIGN_ONLY |
| F7 | MEDIUM | FACT | bundle 内已有两个 producer 值（`identity.producer=codex-cli-0.144.4` vs `provenance.producer=codex-artifact-builder-v0`）；v1 单 producer 对象无映射规则；issuer≠producer 无强制 |
| F8 | MEDIUM | FACT | validator 缺交叉字段 invariant：顶层 name/version ≠ manifest、requester.request_id ≠ provenance.request_id、artifact_ref ≠ digest、forged digest 缺失被接受、candidate/capability id 无唯一性（无状态） |
| F9 | LOW | FACT | 当前 F+ promoted entry 无 adoption 块、无 `adoption_store.json`；phase9a1 的"当前仓库事实"无法从仓库本身复现 |
| F10 | LOW | DESIGN | Registry 不支持多版本/多 candidate 每 capability；v1 允许但 promote 冲突规则未定义 |
| F11 | DESIGN | — | Draft → Frozen Candidate（或内容寻址 write-once 记录）是闭合 immutability 的自然方案，但需同时定义冻结边界与 evidence 外置 |

---

## 12. FACT / INFERENCE / DESIGN / UNKNOWN

### FACT（本次审查实测）

- `candidate_id` 由 capabilityizer 生成并贯穿 authority/registry/guard；`capability_id` 由 registry 生成（`registry.py:132,184`）。
- 三种 digest 编码存在；manifest forged digest `87a6f062...`；当前 dir_digest `1238c032...`（含 pycache）/ `5ac13b1a...`（仅 main.py）；harness 编码 `657057ac...` = 历史 B3 记录值。
- `evaluation.json` 无 `artifact_digest`；`validation.json`/`evaluation.json` 写入 candidate 目录。
- bundle `identity.producer=codex-cli-0.144.4`，`provenance.producer=codex-artifact-builder-v0`；authority issuer=`rehearsal-runner`。
- 18 个 phase9a1 测试 + 8 个新 gap probe 全部通过；probe 证明 validator 接受 name/version 不一致、artifact_ref 不绑定、request_id 不一致、缺 forged digest、无 requester 的 agent candidate，且投影携带 source_type。

### INFERENCE

- v1 选 dir_digest 语义为唯一 canonical digest 方向正确（与运行时强制点一致）。
- Registry Entry 仍将是 logical canonical object，Candidate 是 intake canonical object。
- 若 capability_id 沿用 uuid 生成，intake replay 不可幂等。

### DESIGN

- intake 拥有 capability_id、Registry 复用；Candidate 不可变；requester/producer 分离；source/artifact 子对象；Draft → Frozen。

### UNKNOWN

- capability_id 派生与碰撞规则；digest 归一化方向（改 capabilityizer vs intake adapter 转换）；Frozen 持久化机制；formal request 对象；agent-produced 的 request lineage 要求；多 candidate 同 capability/version 的 promote winner 规则；现有 `cap-<uuid>` entry 迁移；artifact 显式文件集合（pycache 排除）的定义。

---

## 13. Required Fixes（Phase 9-B 前置，本阶段不实现）

1. **闭合 capability_id 所有权**：定义派生规则（建议确定性 name+namespace hash，保证 replay）、collision 规则、Registry 复用路径、现有 entry 迁移；validator 增加 capability_id 格式/关系校验。
2. **归一化 digest**：唯一编码 = 编码 B（dir_digest），但先定义 artifact 的显式文件集合（排除 `__pycache__` 等生成物）或 intake 时冻结目录；capabilityizer 改用同一编码；validator 在 intake 时对字节做语义校验，而不只是字符串相等；删除或绑定 `artifact_ref`。
3. **冻结 Candidate**：write-once 记录（内容哈希 + append-only 存储）；manifest/tests 编辑窗口移到 draft；明确 `validation.json`/`evaluation.json` 不是冻结记录的一部分。
4. **绑定 Evaluation → artifact/manifest**：`evaluation.json`/evidence 记录 `artifact_digest`（和 manifest digest）；`issue_authority` 校验 evaluation 绑定 == 当前 candidate digest；Guard 增加 evidence↔artifact 绑定检查。
5. **收紧 Governance 投影**：从 projection 剥离 `source_type`（或整个 source 对象），并加断言"投影任何层级不含 source_type"；在 Phase 9-B 落地 authority/registry/guard 对 Candidate v1 的真实消费路径后，Source Independence 才能从 DESIGN_ONLY 转 FACT。
6. **producer 映射规则**：定义单 producer 取 `identity.producer` 还是 `provenance.producer`；issuance 时强制 `issuer_id != producer.id`（在 trusted-issuer allowlist 生效时）。
7. **validator 交叉字段 invariant**：顶层 name/version == manifest；`requester.request_id` == `provenance.request_id`（存在时）；`artifact_ref` == `artifact:digest`；`forged_artifact_digest` 缺失拒绝；source.resolved_revision 与 manifest.source_artifact_digest 一致性。
8. **定义多 candidate promote 规则**：每 capability+version 只有一个 active candidate（或显式 supersede），否则 Registry 冲突语义不明。

---

## 14. Non-blocking Questions

1. `requester` 是否应对 agent-produced source 变 REQUIRED？
2. `source_type` 是否应在 v1.1 收紧为封闭 enum（配 schema 注册），还是保持开放并接受 Governance 无法区分来源的代价？
3. `artifact_ref` 是否应整体删除（可派生），还是保留为未来内容寻址存储的 locator？
4. `extensions` 是否需要 applicability/provenance 校验（Phase 7.1 已要求）？
5. `validation.json`/`evaluation.json` 的存储边界：继续 co-locate 但排除在冻结记录外，还是移出 candidate 目录？
6. `candidate_id` 是否应改为确定性内容哈希（`cand-<sha256(...)[:12]>`）以实现 replay 幂等？
7. 已 promote 的 `cap-<uuid>` entry：保持 uuid 还是迁移到确定性 id？迁移谁有权执行？

---

## 15. Final Verdict

### 审查判定：**PASS_WITH_FINDINGS**

合同 schema 和离线 validator 是合格的设计产物，可以进入 Phase 9-B 的前置设计基线；但按用户设定的门槛（identity ownership 不闭合 / digest semantics 不闭合 / immutability 无法保证 / Phase 8 semantic binding 不兼容 → 不得给 VALID），四项中：identity ownership 未闭合（F1）、digest semantics 未闭合（F2/F3）、immutability 无法保证（F4/F5）、Phase 8 binding PARTIAL（§8）。因此：

### 合同判定：**CANDIDATE_CONTRACT_PARTIAL**

不得标记 `CANDIDATE_CONTRACT_VALID` 或 `VALID_WITH_UNKNOWN`。原文档的 `VALID_WITH_UNKNOWN` 判定不成立 —— 所列 UNKNOWN 不是全部属于"数据来源/后续实现"，其中 capability_id 所有权、digest 归一化、immutability 机制、evaluation↔artifact 绑定是 Core 语义缺口，必须在 Phase 9-B 实现前用设计/代码闭合。

### 验证记录

- `python3 -m unittest docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_contract.py -v`：18 passed（原套件）
- `python3 docs/archaeology/unified-runtime/phase9a1/validate_capability_candidate_contract.py`：`CANDIDATE_CONTRACT_VALID INTAKE_ACCEPTED`（原 example main）
- `python3 -m unittest docs/archaeology/unified-runtime/phase9a1/test_candidate_contract_gap_probes.py -v`：8 passed（本次新增 gap probes，只读验证器行为，不修改生产代码）

### 范围确认

- 未修改 `src/`、`pilot/` 生产代码；未实现 Source Adapter；未进入 Phase 9-B。
- 新增：`docs/architecture/capability-candidate-contract-v1-review.md`、`docs/archaeology/unified-runtime/phase9a1/test_candidate_contract_gap_probes.py`。

STOP。
