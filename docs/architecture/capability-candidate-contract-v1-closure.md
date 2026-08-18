# CapabilityCandidate v1 Contract Closure（Phase 9-A.1.1）

- 阶段：Phase 9-A.1.1（CapabilityCandidate Canonicalization Closure）
- 日期：2026-08-18
- 基线：`capability-candidate-contract-v1.md`（Phase 9-A.1）、`capability-candidate-contract-v1-review.md`、`docs/archaeology/unified-runtime/phase9a1/`
- 范围：只允许新增 closure 文档 + 离线 design validator/tests；未修改 `src/`、`pilot/`、Phase 7–8.5 历史 artifacts；未实现 Source Adapter；未 commit / push
- 最终判定：**CANDIDATE_CONTRACT_CLOSED**

判定理由：Phase 9-A.1 Review 的四个硬门全部闭合，且每个硬门都有可运行的离线验证：

```text
A. Identity ownership 明确    -> intake 首次生成、Registry 只消费；碰撞/迁移规则明确
B. Digest semantics 唯一      -> CANONICAL_ARTIFACT_IDENTITY_V1（allowlist digest + 精确布局）
C. Candidate seal 语义闭合    -> CANDIDATE_FREEZE_RULES_V1（Draft -> Intake -> Seal -> Frozen）
D. Governance source independence -> semantic projection 不含 source；5 种 source 突变投影全等
```

---

## 1. Executive Summary

本阶段把 Review 的四个硬断点从 DESIGN 声明变成可机器验证的 closure 语义：

1. **capability_id 所有权**：首次生成点从 Registry 移到 Intake；Registry 从“自造 id”变成“消费并校验 Candidate 提供的 id”；拒绝路径不再 mint id。现有 legacy `cap-<uuid>` entry 保留为对应 name 的权威 id。
2. **digest 归一化**：仓库里三种编码（capabilityizer A、authority B、harness C）归一为一种：**allowlist-only 内容 digest（Phase 8 `dir_digest` bare-map 形状）+ 精确布局校验**。`__pycache__` / `*.pyc` / logs / tmp / generated 不影响 digest，但在 seal 与激活时 fail-closed。
3. **Candidate seal**：定义 write-once Frozen Candidate；`manifest` / `tests` / artifact 全部进入 seal 身份；`evaluation.json` / `validation.json` 外置为 append-only evidence 并引用 seal digest，不再污染 Candidate 身份。
4. **Governance 与 Source 隔离**：`governance_projection` 改为 source-free 的 semantic projection；deep scan 断言任意层级不存在 `source_type` / `source_reference`；git / oci / agent / marketplace / `future_source_xyz` 突变产生完全相同的投影。

验证：新增 27 个 closure 测试 + 1 个 design validator，与原有 26 个测试合计 **53 passed**；validator main 输出 `CANDIDATE_CONTRACT_CLOSED INTAKE_ACCEPTED`。

---

## 2. Evidence Gate（Step 0 复现）

以下事实全部在本仓库当前状态复现（2026-08-18，`pilot/state` 是 gitignored 的实验目录）。

### 2.1 Identity 事实

| # | 事实 | 代码/数据位置 | 实测 |
|---|---|---|---|
| 1 | `capability_id` 唯一真实生产者是 Registry | `pilot/registry.py:132`（promote）、`:184`（reject） | `cap-d24c50c27fa8`（当前 F+ promoted entry） |
| 2 | prototype `candidate.json` 不含 `capability_id` | `src/forge/capabilityizer.py:116-117` | `{candidate_id, name, state, source_bundle_ids}` |
| 3 | 当前 F+ registry entry 无 `adoption` 块 | `pilot/state/registry/F+/csv-clean-statistical-report.json` | 无 `adoption`、无 `adopted_at`、无 `adoption_store.json` |
| 4 | bundle 内 producer 有两个值 | bundle.json `identity.producer` vs `provenance.producer` | `codex-cli-0.144.4` vs `codex-artifact-builder-v0` |
| 5 | authority issuer 来自 confirm | `pilot/adoption_authority_producer.py:119-126`；`pilot/confirm.json` | `rehearsal-runner` |

### 2.2 Digest 事实

| # | 编码 | 表达式 | 当前实测值 |
|---|---|---|---|
| A | `capabilityizer.forged_artifact_digest`（`src/forge/capabilityizer.py:87-89`） | `sha256(canonical({"files":[{"path":"main.py","digest":...}]}))`，只含声明文件 | `sha256:87a6f062...`（manifest 现值） |
| B | `adoption_authority.dir_digest`（`pilot/adoption_authority.py:52-59`） | `sha256(canonical({rel_path: file_digest}))`，含目录全部文件 | candidate artifact `1238c032...`；registry artifact `b94ec2a6...` |
| C | `harness._dir_digest`（`pilot/harness.py:59-62`） | `sha256(canonical({"files":{rel_path: file_digest}}))` | `657057ac...`（排除 `__pycache__` 后与历史 B3 记录一致） |

关键新证据：

```text
FACT  candidate artifact 排除 __pycache__ 后 digest = 5ac13b1a...；
      registry artifact 排除 __pycache__ 后 digest = 5ac13b1a...（同一源码一致）。
FACT  candidate 与 registry 的 main.cpython-313.pyc 字节不同
      （5902 vs 5885 bytes），因为 pyc 内嵌编译时绝对源码路径；
      同一 main.py 在不同目录产生不同 pyc -> 不同 dir_digest。
FACT  source_artifact_digest = 2b0b6305... = sha256(canonical(
      {"bundle_digests": [4 个 bundle digest 排序]}))，与 manifest 现值一致；
      它不等于任何一个 bundle digest（0c44fb2f / aee20185 / ccbcb2cb / e2c0c21a）。
```

结论：编码 B 是 Runtime Guard 实际强制的语义（`runtime_adoption_guard.py:199-210` 六处 digest 全等），但 B 的“全部文件”行为会把路径相关 pyc 变成 digest 噪音；A 与 C 必须淘汰。

### 2.3 Immutability 事实

| # | 事实 | 位置 |
|---|---|---|
| 1 | `candidate.json` / `manifest.json` / `tests/` 是普通可写文件 | `src/forge/capabilityizer.py:87-118` |
| 2 | `validation.json` / `evaluation.json` 在 intake 后写入 Candidate 目录 | `src/forge/validator.py:96`、`src/forge/evaluator.py:68` |
| 3 | `evaluation.json` 不记录 `artifact_digest` | 实测 keys：`candidate_id, evaluated_at, evaluation_id, independent_reuse, novel_input_test, pass_rate, promotion_rule, regression, test_cases, verdict` |
| 4 | `issue_authority` 在签发时刻重新读 candidate/manifest 并重算 digest | `pilot/adoption_authority_producer.py:129-145` |
| 5 | `registry.promote` 在 promote 时刻重新读 manifest 并复制 artifact | `pilot/registry.py:118-126` |

结论：evaluation → issuance 窗口内替换 artifact / manifest / tests 不会被检测；“approved A, execute B”风险真实存在。

### 2.4 Governance 事实

`governance_projection()` 不按 `source_type` 分支（`validate_capability_candidate_contract.py:211-223`），但把整个 `source` 对象透传；gap probe 实测投影包含 `source.source_type`。生产消费者目前不读取 Candidate v1，Source Independence 在生产层仍是 DESIGN_ONLY。

---

## 3. Identity Closure（硬门 A）

### 3.1 标识符职责（闭合版）

| 标识符 | 含义 | 首次生成 | authority | 稳定性 |
|---|---|---|---|---|
| `capability_id` | 逻辑 Capability 的跨版本稳定身份 | **Intake（adapter/normalizer）** | **Intake**；Registry 只消费/冲突拒绝，永不 mint | 跨版本、跨 candidate、跨来源稳定 |
| `candidate_id` | 一次 Intake 被接受后生成的 Candidate 实例身份 | Intake（`capabilityize`） | Intake | 每对象唯一；同 capability 可多 candidate |
| `version` | 业务版本（int >= 1） | Intake（manifest 同步） | Intake；顶层与 manifest 必须一致 | 版本内稳定 |
| `source.resolved_revision` | 输入来源的不可变锚点 | Intake 时 adapter 解析 | Adapter（必须可验证） | 不可变（provenance） |
| `artifact_digest` | 被运行 artifact 的内容身份 | Intake 时按 `CANONICAL_ARTIFACT_IDENTITY_V1` 计算 | 字节事实，任何人可重算 | 不可变（content binding） |

### 3.2 逐问回答

1. **capability_id 在哪里首次生成？** Intake 边界的 Normalizer。当前 prototype 没有这一层，所以今天的事实是 Registry 在 promote/reject 时 mint —— 这是 Review F1 的缺口。closure 要求 Phase 9-B 的 intake 层在 `INTAKE_ACCEPTED` 之前生成并写入 Candidate。
2. **谁有 authority 创建 capability_id？** 只有 Intake。Registry、AdoptionAuthority、Runtime Guard 均只有“消费 + 校验”权限。Registry 发现 candidate 提供的 id 与既有 entry 不一致时只能 BLOCK。
3. **Registry 是否允许再生成？** 不允许。`registry.promote()` / `reject()` 的 mint 行为（`pilot/registry.py:132,184`）在 Phase 9-B 删除；新 entry 直接使用 candidate 的 id。
4. **candidate_id 是否一次 intake 唯一？** 是。每个 `INTAKE_ACCEPTED` 生成一个新的 `cand-<uuid>`（当前行为保留）。同 version 的两次不同 intake 是两个 candidate。
5. **capability_id 是否跨版本稳定？** 是。v1 与 v2 必须是同一个 `capability_id`；不同 version 只改变 `version` 与 `candidate_id`。
6. **一个 capability_id 是否可以多个 candidate_id？** 可以（多来源、多 intake、多 version）。同一个 `(capability_id, version)` 同时只有一个 active candidate（见 §3.4 冲突规则）。
7. **Registry / Runtime 是否只消费 Candidate 提供的 capability_id？** 是。Registry entry `capability_id`、B3 invoke evidence `capability_id`（`pilot/harness.py:740-754`）与 treatment attribution 全部改为 Candidate 的字段；Runtime 不 mint。

### 3.3 完整生命周期示例

```text
capability X（capability_id = cap-...）
│
├─ v1 ─ candidate A（candidate_id = cand-A，artifact_digest = dA）
│     ├─ Intake 接受 -> Seal -> Frozen Candidate A
│     ├─ Evaluation PASS（evidence 绑定 cand-A / dA / seal digest）
│     ├─ AdoptionAuthority（candidate_id=cand-A, candidate_version=v1, artifact_digest=dA）
│     ├─ Registry promote（capability_id 复用 Candidate，不再自造）
│     └─ Runtime Guard 激活（六处 digest + layout 校验）
│
└─ v2 ─ candidate B（candidate_id = cand-B，artifact_digest = dB）
      ├─ Intake 接受 -> Seal -> Frozen Candidate B（同一 capability_id）
      └─ 走同一 governance 链
```

**如果 capability v1 被拒绝**：

```text
capability_id 继续存在。
拒绝是 governance lifecycle 状态（REJECTED / HOLD），不是 identity 删除。
candidate A 仍是一个已 seal 的 Frozen Candidate（记录保留、evidence 保留）；
capability X 没有 promoted v1。
v2 的 candidate B 可以继续用同一 capability_id 进入 intake。
```

拒绝路径中 `registry.reject()` 也不得 mint 新的 `capability_id`（当前 `pilot/registry.py:184` 行为必须删除）；rejected entry 记录 candidate 提供的 id 与拒绝证据。

### 3.4 派生、碰撞与迁移

**新 capability 的派生规则（确定性，保证 replay 幂等）：**

```text
capability_id = "cap-" + sha256(canonical_json({
    "namespace": <intake namespace, 例如 "F+">,
    "name": <candidate name>,
}))[:16]
```

同一 `(namespace, name)` 无论来源（git / oci / agent / marketplace / future）与重试次数，都得到同一 id；改名 = 新 capability。

**碰撞规则（Registry 层 fail-closed）：**

| 场景 | 判定 | 原因 |
|---|---|---|
| 同 name 新 promote，id 与既有 entry 相同 | ALLOW（幂等） | 同逻辑能力重复 adoption |
| 同 name 新 promote，id 不同 | BLOCK `CAPABILITY_ID_CONFLICT` | name 与 capability_id 的绑定不可被静默改写 |
| 不同 name 使用同一 capability_id | BLOCK `CAPABILITY_ID_CONFLICT` | capability_id 在 store 内唯一 |
| candidate 缺 capability_id 或格式非法 | BLOCK `CAPABILITY_ID_FORMAT` | intake fail-closed |

**legacy 迁移：**

```text
现有 cap-<uuid> entry 的 id 保留为对应 name 的权威 id。
Phase 9-B adapter 对“已有 entry 的 name”使用 entry 既有 id；
确定性派生只用于全新 capability。
操作者显式 re-bind 需要 governance event（capability_id_rebind），本阶段不实现。
```

---

## 4. Digest Canonicalization Closure（硬门 B，最高优先级）

### 4.1 逐问回答

1. **每个 digest 表示什么？**
   - `artifact.artifact_digest`：被 seal、被评估、被授权、被挂载执行的 forged artifact 的内容身份。
   - `source.resolved_revision`：输入来源的不可变锚点（agent 路径 = 4 个 bundle digest 的复合 digest；git = commit SHA；OCI = manifest digest）。
   - `manifest.provenance.forged_artifact_digest`：legacy 镜像字段，必须等于 `artifact.artifact_digest`。
   - `manifest.provenance.source_artifact_digest`：输入集合 digest，必须等于 `source.resolved_revision`。
   - `bundle_digest`：VerifiedTaskArtifactBundle 的密封 digest（另一对象，不参与 Candidate artifact 身份）。
2. **输入文件集合是什么？** 显式 allowlist `artifact.files`（相对路径列表）。非 allowlist 文件不属于 artifact 身份。
3. **排序规则是什么？** 相对路径按 posix 字典序排序。
4. **canonical serialization 是什么？** `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8")`，对象形状为 **bare map** `{rel_path: "sha256:<64 hex>"}`（Phase 8 `adoption_authority.dir_digest` 形状）。旧的 harness `{"files": {...}}` 包装（编码 C）仅作历史运行记录，不再用于 artifact binding。
5. **是否包含 `__pycache__` / `*.pyc` / logs / tmp / generated？** 不包含（allowlist-only digest，digest 稳定）；但这些文件在 seal 与激活时被精确布局校验拒绝（fail-closed，无 ignore list）。
6. **是否有明确 artifact allowlist？** 有：`artifact.files` 成为 REQUIRED 字段；缺省、重复、绝对路径、`..`、指向不存在文件、或实际目录存在未声明文件 → `INTAKE_REJECTED` / seal BLOCK。
7. **artifact_ref 与 artifact_digest 是否重复？** `artifact_ref` 是派生 locator，不是独立身份。保留但硬绑定：`artifact_ref == "artifact:" + artifact_digest`，否则 `ARTIFACT_REF_BINDING_MISMATCH`。Phase 9-B 可整体删除（无消费者依赖）。
8. **source artifact digest 与 runtime artifact digest 是否不同？** 不同且必须不同字段：`source.resolved_revision`（输入）vs `artifact.artifact_digest`（输出）。交叉绑定：`manifest.provenance.source_artifact_digest == source.resolved_revision`。

### 4.2 CANONICAL_ARTIFACT_IDENTITY_V1

```text
输入：
  artifact_dir   （冻结的 artifact 目录）
  allowlist      （candidate.artifact.files，REQUIRED，非空）

布局校验（seal 与激活时都执行）：
  actual_files = {相对 posix 路径 | 目录内所有 is_file()}
  wanted_files = set(allowlist)
  任一 actual - wanted            -> UNDECLARED_ARTIFACT_FILE:<path>（BLOCK）
  任一 wanted - actual            -> ARTIFACT_ALLOWLIST_FILE_MISSING:<path>（BLOCK）
  路径绝对 / 含 ".." / 重复       -> ARTIFACT_ALLOWLIST_PATH_INVALID（BLOCK）

digest：
  file_digest(p)   = "sha256:" + sha256(file_bytes).hexdigest()
  files            = {rel_path: file_digest(p) for rel_path in sorted(allowlist)}
  artifact_digest  = "sha256:" + sha256(canonical_json(files)).hexdigest()

性质：
  artifact/main.py
  与
  artifact/main.py + __pycache__/main.cpython-313.pyc
  -> SAME_ARTIFACT_DIGEST（digest 只由 allowlist 决定）
  main.py 内容变化 -> MUST_CHANGE_DIGEST
```

为什么“精确布局”与“allowlist-only digest”必须同时存在：

```text
只做 allowlist digest：pycache/log/tmp 不干扰 digest，但多出的文件可被运行时 import/执行。
只做全部文件 digest：pycache 内嵌绝对路径，同一源码在不同目录 digest 不同（已实测 5902 vs 5885）。
两者合起来：digest 稳定且运行字节集合可验证。
```

### 4.3 生产修正方案（Phase 9-B 实施，本阶段不改）

```text
1. capabilityizer 不再用编码 A；改为 CANONICAL_ARTIFACT_IDENTITY_V1。
2. adoption_authority.dir_digest / runtime guard 的 digest 重算改为
   allowlist-aware canonical digest（allowlist 随 authority/entry binding 持久化）。
3. harness._dir_digest 只保留给 skill/run-record，不参与 artifact binding。
4. intake 校验器必须看到 artifact 字节（closure validator 已实现），
   不再只做字符串相等检查。
```

---

## 5. Immutability / Seal Closure（硬门 C）

### 5.1 状态与冻结点

```text
Draft
  （raw input / adapter 输出 / normalizer 结果；可编辑）
  -> Intake Check（含字节级 digest + 布局校验）
  -> INTAKE_ACCEPTED
  -> Seal（write-once，原子创建 Frozen Candidate 记录）
  -> Frozen Candidate
```

**Seal 点 = `freeze_candidate()`**：只有 Intake Check 全过才允许写 Frozen Candidate 记录；seal 后任何 immutable 字段变化都会被 `verify_frozen()` 检测。

### 5.2 Frozen Candidate 的文件归属

| 内容 | 阶段 | 归属 | 可写性 |
|---|---|---|---|
| `candidate.json`（v1 identity 记录：schema/candidate_id/capability_id/name/version/source/producer/requester/artifact/manifest/provenance/extensions） | seal 后 | **Frozen Candidate** | write-once |
| `manifest.json`（frozen 副本） | seal 后 | **Frozen Candidate** | immutable |
| `tests/`（frozen 副本 + `tests_digest`） | seal 后 | **Frozen Candidate** | immutable |
| `implementation/artifact/`（allowlist 精确字节） | seal 后 | **Candidate Artifact** | immutable + layout 精确 |
| `validation.json` | post-seal | **Evaluation Evidence** | append-only，引用 `candidate_id + artifact_digest + seal_digest` |
| `evaluation.json` | post-seal | **Evaluation Evidence** | append-only，必须记录 `artifact_digest` + `seal_digest`（新增） |
| decisions / authorities / revocations / lifecycle | post-seal | **Governance State** | append-only（Phase 8 已实现 write-once ledger / events） |
| run records / CapabilityInstance | post-seal | **Runtime State** | runtime lifecycle |

`evaluation.json` **不是** Candidate artifact identity 的输入：`seal_digest` 计算只覆盖 Frozen Core + `manifest_digest` + `tests_digest` + `artifact_digest`，证据文件加进目录不会改变 seal digest（测试覆盖）。

### 5.3 CANDIDATE_FREEZE_RULES_V1

```text
R1. Seal 后以下字段绝对不可修改：
    schema_version / candidate_id / capability_id / name / version /
    source / producer / requester / artifact（含 allowlist）/ manifest /
    provenance / extensions。
R2. Seal 后 artifact 字节必须与 allowlist 精确一致；新出现或消失任何文件都是 BLOCK。
R3. Seal 后允许 append-only evidence：validation / evaluation / decisions /
    authorities / revocations / runtime activation records；
    每条必须引用 candidate_id + artifact_digest（evaluation 还引用 seal_digest）。
R4. 证据永远不写进 Candidate artifact identity；Candidate 身份永远不写进 evidence。
R5. 任何 R1 字段需要修改：
    - 修正内容（代码/manifest/tests）-> 新建 candidate_id（重新 intake），
      原 Frozen Candidate 原样保留；
    - 语义升级 -> 新建 candidate_id + 新 version（同一 capability_id）；
    - 禁止原地改写任何 Frozen Candidate 文件。
R6. “PASS A -> mutate -> execute B”防护链：
    evaluation 记录 artifact_digest+seal_digest
    -> issue_authority 重算 digest 并与 evidence 绑定一致
    -> registry.promote 重算 digest
    -> runtime guard adopt() + verify_at_mount() 重算 digest + layout
    任一环不一致 -> BLOCK。
```

### 5.4 修改判定

`modification_verdict()` 把 `verify_frozen()` 的结果映射为：

```text
FROZEN_CANDIDATE_UNCHANGED   验证通过
NEW_CANDIDATE_REQUIRED       任一 frozen 字段/字节变化
```

---

## 6. Governance Isolation Closure（硬门 D）

### 6.1 判断结论

Review 的问题：“`governance_projection()` 传递 source object 是 semantic dependency、metadata passthrough，还是 test artifact？”

答案：**当前是 metadata passthrough**（投影函数不按 `source_type` 分支），但**透传本身就是泄漏面**：任何下游消费者一旦读取 `projection["source"]["source_type"]` 做分支，metadata 就变成 semantic dependency。closure 把“不分支”升级为“结构上不可见”。

### 6.2 Semantic Projection（闭合版）

```text
governance_projection = {
  candidate_id, candidate_version, capability_id, name,
  artifact_digest, manifest_digest, tests_digest, governance_digest,
  producer, requester,
  provenance: {created_at, source_revision, build_ref, request_id, intake_ref}
}
```

规则：

```text
1. 投影不含 source 子对象；任意层级 deep scan 不得出现
   "source_type" / "source_reference" -> GOVERNANCE_SOURCE_LEAK。
2. governance_digest 只覆盖 source-independent 语义字段；
   完整 seal_digest 仍覆盖 source，用于审计级不可变性。
3. 若 Candidate 的 identity / artifact / producer / version / provenance 相同，
   仅 source_type / source_reference 改变：
   projection 必须 deep-equal。
4. Phase 9-B 的 Evaluation / Promotion / AdoptionAuthority / Registry /
   Runtime 只消费本 projection（+ 需要时 Candidate 完整记录做审计），
   不消费裸 Candidate 的 source。
```

### 6.3 Mutation Tests（全部通过）

```text
source_type ∈ {git, oci, agent, marketplace, future_source_xyz}
source_reference 任意改变（resolved_revision 相同）
-> governance projection 完全相等；source_leak_violations 为空。
```

测试位置：`docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_closure.py`（`GovernanceSourceIndependenceTests`，3 tests）。

---

## 7. Adversarial Matrix

| # | 场景 | 判定 | 原因 |
|---|---|---|---|
| 1 | Registry creates a new capability_id | **BLOCK** | 所有权在 Intake；Registry 自造（`registry.py:132,184`）是 Phase 9-B 必须删除的缺口 |
| 2 | Candidate has capability_id A, Registry attempts B | **BLOCK** `CAPABILITY_ID_CONFLICT` | Registry 必须消费 Candidate 的 id；不一致即 fail-closed |
| 3 | `__pycache__` added | digest **SAME**；seal/激活 **BLOCK** `UNDECLARED_ARTIFACT_FILE` | allowlist-only digest 稳定；精确布局拒绝未声明文件 |
| 4 | temp file added | digest **SAME**；seal/激活 **BLOCK** | 同 #3 |
| 5 | log file added | digest **SAME**；seal/激活 **BLOCK** | 同 #3 |
| 6 | artifact bytes changed | digest **MUST CHANGE**；seal 后 **BLOCK** `ARTIFACT_DIGEST_MISMATCH` | 内容身份绑定字节 |
| 7 | manifest changed after seal | **BLOCK** `MANIFEST_CHANGED_AFTER_SEAL` | `manifest_digest` 进 seal 身份 |
| 8 | tests changed after seal | **BLOCK** `TESTS_CHANGED_AFTER_SEAL` | `tests_digest` 进 seal 身份 |
| 9 | evidence appended after seal | **ALLOW**（append-only） | evidence 外置、引用 digest；不改变 Candidate 身份 |
| 10 | source_type changed | seal 后 **BLOCK** `SEAL_DIGEST_MISMATCH`；投影不变（无 leak） | source 属 frozen core；governance 结构上不可见 source |
| 11 | source_reference changed, resolved_revision same | seal 后 **BLOCK** `SEAL_DIGEST_MISMATCH`；投影不变 | 引用不可变；投影不受影响 |
| 12 | requester changed after seal | **BLOCK** `SEAL_DIGEST_MISMATCH` | requester 属 frozen core |
| 13 | producer changed after seal | **BLOCK** `SEAL_DIGEST_MISMATCH` | producer 属 frozen core |

---

## 8. Phase 8 Compatibility

### 8.1 逐项确认

| Phase 8 冻结语义 | closure 是否保持 | 说明 |
|---|---|---|
| `AUTHORITY_FIELDS`（candidate_id/candidate_version/promotion_decision_id/evaluation_run_id/policy_version/artifact_digest/provenance） | 保持 | 字段形状不变；`artifact_digest` 在 Phase 9-B 换用 canonical 函数重算 |
| `BINDING_KEYS` | 保持 | Registry `_same_binding` 逻辑不变 |
| `PROVENANCE_KEYS`（policy/evidence_manifest/run_ids/immutable_artifact_refs） | 保持 | 不变 |
| artifact digest binding（六处全等） | 保持 | `runtime_adoption_guard.py:199-210` 语义不变；digest 函数归一 |
| registry state machine（promote/reject/discover） | 保持 | promote/reject 不再 mint id；entry 形状不变 |
| runtime guard（adopt / verify_at_mount / mark_promoted） | 保持 | fail-closed 语义不变；Phase 9-B 增加 layout + evidence 绑定检查 |
| write-once authority ledger / revocation events | 保持 | 不变 |

### 8.2 同一标识符链

```text
Candidate（v1 frozen record）
  candidate_id       -> PromotionDecision.candidate_id
                      -> AdoptionAuthority.candidate_id
                      -> Registry.adoption.candidate_id
                      -> Runtime Guard.candidate_id
  candidate_version  -> v{N} 字符串，全链一致（int -> vN 转换已有）
  artifact_digest    -> decision / run / authority / store candidate /
                        entry / runtime guard 六处全等
  capability_id      -> Registry entry（复用，不再自造）
                      -> B3 invoke evidence / treatment attribution
```

### 8.3 已闭合的 Review 缺口

| Review 发现 | closure 措施 | 状态 |
|---|---|---|
| F1 capability_id 所有权 | §3 Intake 所有权 + Registry 消费 + 碰撞/迁移规则 | 闭合 |
| F2/F3 三种 digest + pycache 漂移 | §4 CANONICAL_ARTIFACT_IDENTITY_V1 + 字节级校验 | 闭合 |
| F4 evaluation 无 digest 绑定 | §5.3 R3/R6 evidence 引用 digest + 签发链校验 | 闭合 |
| F5 Candidate 不可变无机制 | §5 seal + write-once + verify_frozen | 闭合 |
| F6 governance 透传 source | §6 source-free projection + deep scan | 闭合 |
| F7 producer 双值 | v1 `producer = {kind, id}` 取 build producer（`codex-artifact-builder-v0`）；CLI 版本进 `extensions`；Phase 9-B 强制 `issuer_id != producer.id`（trusted-issuer allowlist 生效时） | 闭合（设计层） |
| F8 交叉字段 invariant | closure intake：version/name 绑定 manifest、artifact_ref 绑定 digest、forged digest 必填、request_id 绑定、source_artifact_digest 绑定 resolved_revision | 闭合 |
| F9/F10/F11 | 状态不可复现性问题由字节级校验解决；多 candidate promote 规则见 §3.4；Frozen 持久化见 §5 | 闭合 |

---

## 9. Offline Verification

新增文件：

```text
docs/architecture/capability-candidate-contract-v1-closure.md
docs/archaeology/unified-runtime/phase9a1/validate_capability_candidate_closure.py
docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_closure.py
```

运行方式与结果：

```bash
python3 docs/archaeology/unified-runtime/phase9a1/validate_capability_candidate_closure.py
# CANDIDATE_CONTRACT_CLOSED INTAKE_ACCEPTED

python3 -m unittest docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_contract.py \
  docs/archaeology/unified-runtime/phase9a1/test_candidate_contract_gap_probes.py \
  docs/archaeology/unified-runtime/phase9a1/test_capability_candidate_closure.py
# Ran 53 tests ... OK
```

验证覆盖：

| 硬门 | 测试 |
|---|---|
| A | `IdentityOwnershipTests`（4）+ `ClosureIntakeInvariantTests.test_capability_id_format` |
| B | `CanonicalArtifactIdentityV1Tests`（5）+ `CandidateFreezeRulesTests.test_seal_requires_byte_level_digest_match` |
| C | `CandidateFreezeRulesTests`（8） |
| D | `GovernanceSourceIndependenceTests`（3） |

---

## 10. FACT / INFERENCE / DESIGN / UNKNOWN

### FACT（本阶段实测）

```text
- capability_id 唯一生产者为 registry.promote()/reject()；candidate.json 无此字段。
- 三种 digest 编码并存；candidate artifact full=1238c032、registry full=b94ec2a6、
  exclude-pyc=5ac13b1a、harness legacy=657057ac。
- pyc 内嵌绝对源码路径：同一 main.py 的两个副本 pyc 不同（5902 vs 5885 bytes）。
- evaluation.json 无 artifact_digest；validation/evaluation 写入 candidate 目录。
- bundle identity.producer=codex-cli-0.144.4；provenance.producer=codex-artifact-builder-v0。
- source_artifact_digest=2b0b6305...=4 个 bundle digest 的复合 digest。
- 53 个离线测试通过；validator main 输出 CANDIDATE_CONTRACT_CLOSED。
```

### INFERENCE

```text
- Runtime Guard 强制的 digest 语义（Phase 8 dir_digest）是唯一正确基线。
- pycache 类生成物必须由 allowlist 排除，否则 digest 不可稳定。
- governance 投影携带 source 会使“不分支”退化成为依赖风险，必须结构上消除。
```

### DESIGN（本阶段新语义）

```text
- capability_id 由 intake 确定性派生；Registry 消费/冲突拒绝；legacy id 保留。
- CANONICAL_ARTIFACT_IDENTITY_V1：allowlist-only digest + 精确布局。
- CANDIDATE_FREEZE_RULES_V1：Draft -> Intake -> Seal -> Frozen；evidence 外置。
- source-free governance projection + governance_digest。
- 交叉字段 invariant 全部机器验证。
```

### UNKNOWN（不阻塞四硬门，Phase 9-B 处理）

```text
- formal CapabilityRequest 对象（requester 保持 OPTIONAL，request_id 绑定已闭合）。
- legacy cap-<uuid> entry 的自动迁移执行细节（本设计给出规则，Phase 9-B 实现）。
- Phase 9-B 生产消费者（authority/registry/guard）切换到 Candidate v1 的落地顺序。
- OS 级 bind-mount 原子性（verify_at_mount 之后的竞态，Review 已标注 UNKNOWN）。
```

---

## 11. Final Verdict

```text
CANDIDATE_CONTRACT_CLOSED
```

判定依据：

```text
A. Identity ownership 明确：intake 首次生成（确定性派生）、Registry 只消费、
   碰撞与迁移规则明确、拒绝不删除 identity。            [闭合]
B. Digest semantics 唯一：CANONICAL_ARTIFACT_IDENTITY_V1 定义唯一语义，
   字节级 validator 验证 SAME/MUST_CHANGE/布局。        [闭合]
C. Candidate seal 语义闭合：Frozen Candidate 组成、证据外置、
   修改必须新建 candidate_id、approve→execute 防护链完整。 [闭合]
D. Governance source independence 成立：source-free projection、
   5 种 source 突变 deep-equal、无 GOVERNANCE_SOURCE_LEAK。 [闭合]
```

四硬门均无 UNKNOWN；剩余 UNKNOWN 全部属于 Phase 9-B 实施细节，不影响本阶段判定。

---

## 12. Git

```text
未 commit / 未 push。
未修改 src/、pilot/ 生产代码；未实现 Source Adapter；未进入 Phase 9-B。
```

STOP：Phase 9-A.1.1 到此为止。
