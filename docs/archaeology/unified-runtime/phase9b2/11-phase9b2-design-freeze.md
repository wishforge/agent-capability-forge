# Phase 9-B.2 Design Freeze

- 日期：2026-08-18
- 基线：`034a3b2`（`d19ec91` 仅增加 archaeology 文档，未改代码）
- 模式：Design Freeze；未修改 production code、未加测试、未 commit
- 输入：`phase9b2/01,07,08,09,10,99` + `pilot/*.py` + `src/forge/capabilityizer.py`
- 证据优先级：当前源码事实 > archaeology 报告；本文所有行号以基线代码为准

---

## 1. Scope

本文件把 Phase 9-B.2 archaeology 的结论冻结为工程契约，回答唯一核心问题：

> Evaluation / Promotion / Authority / Adoption / Runtime 之间，如何保证接受、
> 批准、执行的是同一个不可漂移的 Candidate？

冻结范围：

```text
统一 Identity Model
Candidate Identity Contract
Evaluation / Promotion / Authority / Registry / Adoption / Runtime 六段契约
R1 / R2 / R3 / R4 / R8 的 invariant + 最小改造边界
8 个 Adversarial Scenario 的 fail-closed 判定
最终 Trust Chain 与验收标准
```

本阶段不实现任何代码，不新增数据库 / 服务 / 外部依赖，不引入 Sigstore、
OCI、Kubernetes、in-toto layout。

## 2. Current Architecture

### 2.1 真实链路（基线代码）

```text
capabilityize(capabilityizer.py:596)
  candidate_id = "cand-" + uuid4().hex[:12]            (:656)
  forged_artifact_digest = canonical digest(["main.py"]) (:95)
  -> candidate_dir/{candidate.json, manifest.json, implementation/artifact, tests}
        ↓
freeze_candidate_dir / freeze_candidate (capabilityizer.py:534,205)
  frozen record {schema, seal_version, candidate_id, capability_id, name,
                 version, artifact_digest, manifest_digest, tests_digest,
                 seal_digest, sealed_at}
  snapshot {candidate.json, tests/, artifact/}  (write-once record, os.link CAS)
        ↓
evaluate (evaluator.py:24) -> evaluation_id + candidate_id（无 digest）
  bind_evaluation (capabilityizer.py:465)  -> + artifact_digest + seal_digest
        ↓
issue_authority (adoption_authority_producer.py:98)
  frozen_checks + evaluation_binding_violations + live_candidate_violations
  -> decision/run/evidence/provenance/lifecycle/authority（write-once ledger + anchor）
        ↓
registry.promote (registry.py:69)
  重验 frozen/eval/live layout；copytree artifact -> registry/<family>/<name>/artifact
  entry.adoption = {candidate_id, candidate_version, promotion_decision_id,
                    evaluation_run_id, policy_version, artifact_digest, provenance}
        ↓
harness.phase_future("b3") (harness.py:673)
  b3_entry.json{name, capability_id} -> registry.discover(name)
  -> adopt()  -> verify_at_mount()  -> docker_launch(mount artifact_dir)
```

### 2.2 信任源与锚定（现状事实）

| 对象 | 锚定方式 | 位置 |
|---|---|---|
| Frozen Candidate record | write-once `os.link` + `verify_frozen` 全量重算 | capabilityizer.py:205,315 |
| Evaluation / Decision / Run | store 内 `recorded_hash/current_hash` + trust anchor | adoption_authority.py:123 |
| Authority | immutable ledger（write-once）+ anchor manifest digest | adoption_authority.py:307,123 |
| Registry entry | 无独立锚定（不进 anchor digest） | registry.py:69 |
| Frozen snapshot | `verify_frozen` 重算（record+snapshot 非单一原子提交，fail-closed 检测） | capabilityizer.py:315 |
| Live artifact | adopt / verify_at_mount 每次重算 canonical digest | runtime_adoption_guard.py:297,415 |
| `b3_entry.json` | 无锚定；只有 `name` + 随机 `capability_id` | harness.py:633 |

### 2.3 关键代码事实

1. `candidate_id` 是随机标签；安全身份是
   `candidate_id + candidate_version + artifact_digest + seal_digest` 四元组
   （capabilityizer.py:656,392；adoption_authority.py:45）。
2. `seal_digest` 覆盖 FROZEN_CORE_KEYS + artifact/manifest/tests 三个 digest，
   **不覆盖 record 级 `schema` / `seal_version`**（capabilityizer.py:114；GAP-4）。
3. Authority 记录 `seal_digest` 与 `artifact_identity = CANONICAL_ARTIFACT_IDENTITY_V1`
   （adoption_authority_producer.py:98，canonical 路径）。
4. Registry entry 的 `capability_id` 是 promote 时新生成的随机
   `"cap-" + uuid4().hex[:12]`，**不是** seal 内确定性的
   `capability_id_derivation(namespace, name)`（registry.py:69 vs capabilityizer.py:182）。
5. `b3_entry.json` 只记录 `name` + `capability_id`，没有 digest
   （harness.py:633）；runtime 按 name 解析（harness.py:689）。
6. adopt 校验六方 digest 全等：
   authority / decision / run / candidate / entry / actual artifact
   （runtime_adoption_guard.py:92）。
7. `verify_at_mount` 紧邻 `docker_launch`，使用同一 `artifact_dir` 变量
   （harness.py:741-750）；verify 返回与内核 bind mount 之间的 OS 级窗口
   = UNKNOWN（phase9b1 声明，本文继续声明）。

## 3. Identity Model

### 3.1 术语定义

| 术语 | 定义 | 生成位置 | 生命周期 | Immutable | Security-sensitive | Caller 可提供 | Authority 锚定 | 可作安全 routing 条件 | 仅 Locator |
|---|---|---|---|---|---|---|---|---|---|
| Candidate Identity | `(candidate_id, candidate_version, seal_digest, artifact_digest)` 四元组；稳定回答“这到底是哪一个 Candidate” | candidate_id 于 capabilityize；version 于 manifest；digests 于 freeze | seal 后冻结 | 是（write-once record） | 是（唯一合法身份） | 否（id 内部生成；digest 由字节计算） | 是（authority 全字段透传） | 是（作为整体） | 否 |
| Artifact Identity | `(artifact_identity_type, artifact_digest)`；类型常量 + 内容 hash | 类型为常量；digest 于 capabilityize/freeze | 冻结 | 是 | 是（类型+digest 必须同时匹配） | 否（digest 由字节计算；类型是协议常量） | 是（authority 持有两者） | 仅 digest 可以 | 类型字段本身不是身份 |
| Artifact Digest | `sha256(canonical({rel_path: sha256(bytes)}))`，allowlist + exact layout | capabilityize / freeze / promote / adopt 重算 | 内容不变则值不变 | 是 | 是（内容身份） | 否（永远从字节计算） | 是 | 是 | 否 |
| Seal Digest | `sha256(canonical(FROZEN_CORE_KEYS + artifact/manifest/tests digest))` | freeze_candidate | 写后不可变 | 是 | 是（最强 Candidate 身份） | 否（从 record 计算） | 是 | 是 | 否 |
| Provenance | authority.provenance = {policy, evidence_manifest, run_ids, immutable_artifact_refs} | issue_authority | 写后不可变 | 是 | 是（缺失即 BLOCK，PROVENANCE_INCOMPLETE） | 否 | 是（锚定于 authority record） | 否（是证据，不是身份） | 否 |
| Registry Locator | `family/name.json` + `artifact_dir` + entry `capability_id` | promote | 可变 | 否 | 否 | 是 | 否（不在 anchor 内） | 否 | 是 |
| Runtime Reference | 当前 = `artifact_dir`（可变目录）；目标 = digest 命名快照（R4） | promote / harness | 当前可变；R4 后不可变 | R4 后是 | 由 digest 验证赋予 | 否 | 否（需 digest 验证兜底） | 否（路径本身永远不是身份） | 是 |

### 3.2 Security Identity vs Locator（冻结结论）

```text
Security Identity（内容 + 生命周期绑定）：
  artifact_digest          —— 可执行字节的身份
  seal_digest              —— 整个 Candidate（元数据 + manifest + tests + artifact）的身份
  candidate_id + candidate_version + artifact_digest + seal_digest
                           —— 跨 Evaluation/Authority/Registry 的 Candidate Identity
  artifact_identity        —— 协议类型判别符（CANONICAL_ARTIFACT_IDENTITY_V1），
                              是 security-sensitive 的 routing 条件，但不是具体对象身份

Locator（永远不能单独作安全身份）：
  name                     —— registry 文件名 / b3_entry 指针
  candidate_id（单独）      —— 生命周期标签
  registry key (family/name)—— 文件系统索引
  path (artifact_dir)      —— 可变路径
  entry.capability_id      —— promote 时随机生成的运行记录标签
  b3_entry.json["name"]    —— 运行意图的名字指针
```

禁止把 `name` / `path` / registry key / 单独 `candidate_id` 当作安全身份。
任何只按这些字段索引的界面都不能单独作出信任决策。

### 3.3 明确的两个事实差异（代码优先）

1. **entry `capability_id` ≠ seal `capability_id`**：seal 内是确定性
   `capability_id_derivation(namespace, name)`；registry entry 是 promote 时
   随机生成。两者当前都只被当作运行记录标签（`capability_used` / `treatment.ref`），
   未参与信任决策。冻结：该字段永远是 Locator；不得用于 routing。
2. **`candidate_version` 是身份分量**：`authority_id_for` 与
   `CANDIDATE_VERSION_MISMATCH` 都依赖它（adoption_authority.py:45；
   runtime_adoption_guard.py:92）。没有它，`candidate_id + digests` 无法区分
   同一候选的多版本决策。

## 4. Candidate Identity Contract

### 4.1 最小契约（复用现有字段，不新建对象）

```text
CandidateIdentity =
  candidate_id          # 生命周期标签（intake 时生成，seal 后不可变）
  + candidate_version   # manifest.capability.version 派生（"vN"）
  + artifact_digest     # 可执行字节内容身份
  + seal_digest         # 整个 Candidate 内容身份（元数据 + manifest + tests + artifact）
```

关系：

```text
Candidate Identity
        |
        +---- Artifact Identity  = CANONICAL_ARTIFACT_IDENTITY_V1 + artifact_digest
        |        （类型判别符 + 字节内容身份）
        +---- Artifact Digest   = canonical(allowlist files)，seal 时写入 record
        +---- Seal              = frozen record + snapshot；seal_digest 覆盖核心字段
        +---- Authority         = authority record 锚定 candidate_id/version/
                                   seal_digest/artifact_digest + decision/run 链接
```

### 4.2 判定规则

```text
两个 Candidate 相同
  <=> candidate_id 相同
      AND candidate_version 相同
      AND seal_digest 相同
      AND artifact_digest 相同

artifact_digest 相同 ≠ identity 相同（Case D）
name / path / registry key 相同 ≠ identity 相同
```

### 4.3 不允许的行为

- 不允许用 `candidate_id` 单独索引并作信任决策。
- 不允许在 seal 后修改 frozen record / snapshot（write-once + verify_frozen）。
- 不允许以“digest 没变”为由合并两个不同 candidate_id 的身份。
- 不允许用 registry name / path 替代 authority 绑定判断。

## 5. Evaluation Contract

### 5.1 Evaluation 当前保存什么

`evaluate()` 原生输出（evaluator.py:24）：

```text
evaluation_id, candidate_id, test_cases, pass_rate, regression,
novel_input_test, independent_reuse, verdict, promotion_rule, evaluated_at
```

`bind_evaluation()` 后（capabilityizer.py:465）追加并校验：

```text
candidate_id     == frozen record.candidate_id
artifact_digest  == frozen record.artifact_digest
seal_digest      == frozen record.seal_digest
```

### 5.2 四个问题的冻结答案

| 问题 | 答案 |
|---|---|
| 是否保存 Candidate Identity？ | 保存 `candidate_id`；绑定后与 `candidate_version` 通过 frozen record 关联 |
| 是否保存 Artifact Digest？ | 绑定后保存 `artifact_digest` |
| 是否保存 Authority / Seal reference？ | 保存 `seal_digest`；不保存 authority（authority 反向引用 evaluation：`authority.evaluation_run_id == evaluation_id`） |
| Promotion 如何证明 Evaluation 针对当前 Candidate？ | `issue_authority` 先跑 `evaluation_binding_violations(evaluation, frozen)` + `live_candidate_violations(frozen, cand)`；`registry.promote` 再跑一遍；adopt 再跑 `evaluation_binding_violations(entry.evaluation, frozen)`；外加六方 digest 全等 |

### 5.3 核心 invariant

```text
Evaluation(A, digest=D, seal=S)
  不能被 Promotion(B, digest=D, seal=S') 消费
  不能被 Promotion(B, digest=D, seal=S) 消费    # 同 digest 不等于同 identity

验证点：
  issue_authority  : EVALUATION_BINDING_MISMATCH（三字段逐项比对）
  registry.promote : EVALUATION_BINDING_MISMATCH + FROZEN_CANDIDATE_MISMATCH
  adopt            : EVALUATION_BINDING_MISMATCH（entry.evaluation vs frozen）
```

### 5.4 最小要求

进入 Promotion 的 evaluation 必须已经绑定三字段；未绑定的历史 evaluation
只能作为 legacy 兼容读取，不能作为 canonical 路径的 Promotion 依据。

## 6. Promotion Contract

### 6.1 定义

```text
Promotion =
  Candidate Identity（candidate_id + candidate_version + digests）
  + Evaluation Reference（evaluation_id == decision.run_id == authority.evaluation_run_id）
  + Authority（write-once ledger record，promotion_decision_id 链接）
  + Artifact Digest（entry.adoption.artifact_digest == authority.artifact_digest）
```

Promotion **不能**只依赖 `candidate_name` / registry key / path。

### 6.2 当前实现证据

`registry.promote()`（registry.py:69）：

```text
前置：authority 必传（MISSING_AUTHORITY）
canonical 路径：
  frozen_checks(frozen_root, candidate_id)
  authority.seal_digest == frozen.record.seal_digest
  evaluation_binding_violations(evaluation, frozen)
  live_candidate_violations(frozen, candidate_dir)   # candidate.json/manifest/tests/artifact 全比对
  validate(authority, store, actual_digest)          # authority/store/decision/run/policy/lifecycle
  hardened mode 下 authority ledger record 必须存在
写 entry：adoption 段 = BINDING_KEYS（与 authority 逐字段一致）
写 artifact：copytree(candidate artifact -> registry/<family>/<name>/artifact)
entry 文件 create-if-absent（os.link CAS）；冲突 -> ENTRY_BINDING_CONFLICT
```

### 6.3 验证

```text
Evaluation Candidate == Promotion Candidate
  <=> evaluation_binding_violations 三字段全等
      AND candidate_id/version 在 decision/run/authority/entry 全等
      AND artifact_digest 六方全等
否则 REJECT（ADOPTION_BLOCKED）
```

### 6.4 已冻结差异

- `name` 参数只决定 registry 文件写到哪里；不做安全绑定。
- entry 的 `capability_id` 是随机标签，不是 seal 的 capability_id；不得作信任字段。

## 7. Authority Contract

### 7.1 Authority 是当前 canonical trust root 的核心

权威记录（adoption_authority_producer.py:98 生成的 authority 对象）：

```text
authority_id                 = "auth-" + sha256(candidate_id|candidate_version|decision_id)[:16]
candidate_id                 # 生命周期身份
candidate_version            # 版本身份
promotion_decision_id        # = decision_id（确定性派生）
evaluation_run_id            # = evaluation_id = decision.run_id
policy_version
artifact_digest              # 内容身份
provenance                   # {policy, evidence_manifest, run_ids, immutable_artifact_refs}
issued_at / status / issuer_id / issuer_type / decision_id
canonical 附加：
  artifact_identity          # CANONICAL_ARTIFACT_IDENTITY_V1
  seal_digest                # 最强内容身份
```

### 7.2 锚定

```text
write_authority_record（adoption_authority.py:307）
  os.link 原子 create-if-absent；已有不同记录 -> AUTHORITY_BINDING_MISMATCH
  + store 内 authorities[] 双写
  + trust anchor 覆盖 authority_manifest_digest + revocation_manifest_digest
  + append-only events（REVOKED / SUPERSEDED）
```

### 7.3 证明什么

Authority 证明的是 **Candidate 身份连续性**，而不仅是 artifact bytes 未变化：

```text
authority.candidate_id       == decision.candidate_id == run.candidate_id
authority.candidate_version  == decision.candidate_version == candidate.version == run.candidate_version
authority.evaluation_run_id  == decision.run_id
authority.artifact_digest    == decision/run/candidate/entry/actual digest
authority.seal_digest        == frozen.record.seal_digest（canonical）
```

任何一处不相等 -> `CANDIDATE_ID_MISMATCH` / `CANDIDATE_VERSION_MISMATCH` /
`RUN_MISMATCH` / `ENTRY_BINDING_MISMATCH` / `ARTIFACT_DIGEST_MISMATCH` ->
REJECT。

### 7.4 边界声明

`authority_id` 是确定性 hash，不是密码学签名；issuer 是 env 字符串
（GAP-3）。单机 pilot 内“能写 store + ledger + anchor 的人”即信任写者；
这是本阶段声明的应用层信任边界，不是对外发布身份。不引入签名体系。

## 8. Registry Contract

### 8.1 冻结结论

```text
Registry = Locator / Index
Authority = Security Identity
```

Registry entry 是可变指针：

```text
family/name.json   -> entry 对象（adoption 段绑定 authority）
entry.artifact_dir -> 实际执行目录（当前为可变目录）
entry.capability_id -> 运行记录标签（随机，非 seal 值）
```

### 8.2 规则

```text
Registry entry 发生 A -> B 但 Authority = A：
  B 与 A 内容不同   -> ARTIFACT_DIGEST_MISMATCH / ENTRY_BINDING_MISMATCH -> REJECT
  B 是另一合法候选   -> entry.adoption 与 authority 绑定字段不等 -> REJECT
  B 与 A 字节相同     -> 内容等价（byte-equivalent），但 identity 仍以 authority 为准；
                        不会合并身份；R1 预期 digest 使意图漂移可审计
```

Registry name 永远不是安全身份；`discover(name)` 只做索引，不做信任决策。

### 8.3 已冻结差距

entry 与 `b3_entry.json` 不在 trust anchor 覆盖内（GAP-2）：

```text
R2 冻结：anchor 覆盖范围扩展为 store + authorities + revocations
         + registry entries + frozen records/snapshots；
         或显式声明“同写者边界”的条目（见 §11 R2）
```

## 9. Adoption Contract

### 9.1 adopt() 的最终信任条件

`runtime_adoption_guard.adopt()`（:297）：

```text
1. load_store + integrity_anchor_violations
2. store authority 与 immutable file authority 双读且必须一致
3. canonical 路由：
   a. frozen_checks(frozen_root, adoption.candidate_id)
   b. authority.seal_digest == frozen.record.seal_digest
      （CANONICAL_IDENTITY_MISMATCH）
   c. evaluation_binding_violations(entry.evaluation, frozen)
   d. frozen_artifact_violations(frozen, live artifact_dir)   # 重算 live digest
4. violations_for_runtime_activation：
   state=promoted、BINDING_KEYS 全等、authority_id 确定性校验、
   issuer allowlist、revocation、decision/run/policy/lifecycle、
   六方 digest 全等（authority/decision/run/candidate/entry/artifact）、
   provenance 完整、recorded/current hash、staleness
5. 全部通过 -> ALLOW + actual_digest
```

### 9.2 核心要求

```text
Promotion Candidate == Authority Candidate == Adoption Candidate
  <=> entry.adoption 与 authority 的 BINDING_KEYS 全等
      AND frozen/eval/decision/run 全链 candidate_id/version/digest 全等

expected artifact digest == actual artifact digest
  <=> 六方 digest 全等中的 entry/artifact 两项相等

registry locator 解析出的对象不能绕过以上验证
  <=> adopt 不接受“路径存在 + digest 正确”作为唯一条件；
     必须先通过 authority/store/frozen/eval 全链验证
```

`adopt()` 不能仅仅因为“当前路径存在且 digest 正确”就认为 Candidate 合法——
当前实现已满足（authority/store/ledger/frozen/eval 全部在 digest 比对之前执行）。

## 10. Runtime Contract

### 10.1 最终执行对象

```text
verified identity（authority + candidate 绑定）
        +
verified digest（adopt + verify_at_mount 两次重算）
        ↓
同一 artifact_dir（不可变引用，R4 后为 digest 命名快照）
        ↓
execute（docker_launch 只读 bind mount）
```

禁止：

```text
verify A
    ↓
resolve mutable path
    ↓
execute B
```

### 10.2 当前实现与残余窗口

```text
adopt()             完整验证（含 live digest 重算）      harness.py:742
verify_at_mount()   再次 adopt + expected digest 比对   harness.py:748
docker_launch()     同一 artifact_dir 变量，只读挂载     harness.py:750
```

已关闭：adopt 与 verify_at_mount 之间的替换窗口。
残余窗口：verify_at_mount 返回与内核 bind mount 之间的 OS 级替换 = **UNKNOWN**。

### 10.3 最小约束（目录方案下）

证明 `runtime input == verified artifact`：

```text
1. runtime input 只能是 adopt/verify_at_mount 验证过的 artifact_dir 本身
   （单一调用点，禁止二次解析）
2. 挂载必须为只读（docker -v host:container:ro）
3. R4 后 artifact_dir 指向 digest 命名的不可变快照，路径本身不再可变
4. 残余 OS 竞态窗口必须显式声明为 UNKNOWN，不得宣称已防御
```

### 10.4 最终 Trust Chain

```text
Candidate
  ↓ Evaluation
  Identity  : candidate_id（+ 绑定后 digest/seal）
  Digest    : artifact_digest + seal_digest（bind_evaluation 写入）
  Provenance: evaluate() 产物（test_cases/verdict/promotion_rule）
  Trust     : frozen record/snapshot（write-once）
  Verify    : evaluation_binding_violations vs frozen
  Failure   : EVALUATION_BINDING_MISMATCH -> REJECT

Candidate
  ↓ Promotion
  Identity  : candidate_id + candidate_version + decision/run 链接
  Digest    : 与 frozen/authority 全等（六方之一）
  Provenance: authority.provenance（policy/evidence/run_ids/immutable_artifact_refs）
  Trust     : AdoptionAuthority（write-once ledger）
  Verify    : frozen_checks + eval binding + live_candidate_violations + validate()
  Failure   : FROZEN_CANDIDATE_MISMATCH / ENTRY_BINDING_CONFLICT -> REJECT

Promotion
  ↓ Authority / Seal
  Identity  : authority_id（确定性绑定 candidate|version|decision）
  Digest    : artifact_digest + seal_digest（canonical）
  Provenance: authority.provenance（必须完整）
  Trust     : immutable ledger + trust anchor manifest
  Verify    : authority_id_for 重算 + ledger 双读 + revocations
  Failure   : AUTHORITY_BINDING_MISMATCH / REVOKED_DECISION -> REJECT

Authority / Seal
  ↓ Registry
  Identity  : entry.adoption（BINDING_KEYS 透传 authority）
  Digest    : entry.adoption.artifact_digest
  Provenance: entry.adoption.provenance
  Trust     : 无独立锚定（GAP-2；R2 扩展）
  Verify    : 运行时 BINDING_KEYS 全等 + 六方 digest
  Failure   : ENTRY_BINDING_MISMATCH / ARTIFACT_DIGEST_MISMATCH -> REJECT

Registry
  ↓ Adoption
  Identity  : authority + frozen + entry 三向绑定
  Digest    : 六方全等（authority/decision/run/candidate/entry/actual）
  Provenance: PROVENANCE_INCOMPLETE -> BLOCK
  Trust     : store + ledger + anchor
  Verify    : adopt() 全链 fail-closed
  Failure   : ADOPTION_BLOCKED（任何缺失/不匹配）

Adoption
  ↓ Runtime
  Identity  : 同一 authority（verify_at_mount 再次 adopt）
  Digest    : expected_digest（= adopt 结果）vs verify_at_mount 重算值
  Provenance: run record（capability_id + artifact_digest）
  Trust     : 同一 artifact_dir 只读挂载（R4 后为不可变快照）
  Verify    : verify_at_mount -> docker_launch 单调用点
  Failure   : ARTIFACT_DIGEST_MISMATCH -> REJECT；
              verify 与内核 bind mount 之间的 OS 窗口 = UNKNOWN（R4 缩小）
```

### 10.5 回答“Evaluation 说 A，Runtime 为什么一定只能运行 A”

字段/机制级答案：

```text
1. evaluation 绑定字段 candidate_id/artifact_digest/seal_digest 必须等于 frozen A
2. authority 通过 evaluation_id -> decision.run_id -> authority.evaluation_run_id
   链到 evaluation A，且 candidate_id/version/digest 全等
3. registry entry.adoption 与 authority 的 BINDING_KEYS 全等
4. adopt 重算 live digest 并强制六方 digest 全等
5. verify_at_mount 在 mount 前再次 adopt + expected digest 比对
6. docker_launch 挂载的只能是同一个 artifact_dir
=> 任何一步把对象换成 B（不同 identity 或不同字节）都会命中
   EVALUATION_BINDING_MISMATCH / ENTRY_BINDING_MISMATCH / CANDIDATE_ID_MISMATCH /
   ARTIFACT_DIGEST_MISMATCH 之一并 REJECT。
```

## 11. R1 / R2 / R3 / R4 / R8 Design Freeze

以下 R 编号与 `10-recommendations.md` 保持一致，不重新命名。

### R1 — 运行时“预期对象”用 digest 记录

```text
Requirement     : 运行请求记录预期 artifact_digest（可选 seal_digest）；
                  runtime 解析后必须比对 预期 digest == 解析对象 digest。
Current Evidence: b3_entry.json 只写 {"name", "capability_id"}（harness.py:633）；
                  phase_future 按 name discover（harness.py:689）；
                  verify_at_mount 只比对“第一次 adopt 的结果”，不是独立预期值。
Gap             : GAP-1 —— name 指向另一合法候选时系统完整运行 B，无对账点。
Invariant       : expected_artifact_digest == entry.adoption.artifact_digest
                  == verify_at_mount 重算 digest；不匹配 -> BLOCK。
                  name 只用于定位，不用于确认意图。
Minimal Change  : phase_b3_build 写 b3_entry.json 时追加 candidate_id /
                  artifact_digest / seal_digest（值来自 authority/entry）；
                  phase_future("b3") discover 后先比对
                  entry_meta["artifact_digest"] == entry.adoption.artifact_digest，
                  再把该值作为 expected_digest 传给 verify_at_mount。
                  旧格式 b3_entry.json（无 digest）-> BLOCK。
New State       : b3_entry.json = {name, capability_id, candidate_id,
                  artifact_digest, seal_digest}（schema v2）。
Negative Case   : name 被改为已 promote 的 B -> expected digest 不匹配 -> REJECT。
Positive Case   : name -> A，expected digest == A digest -> ALLOW。
```

### R2 — trust anchor 覆盖范围显式化

```text
Requirement     : 把 registry entries + frozen records 纳入锚定清单，或明确写
                  “不锚定、同写者边界内”的声明；二选一，不许含糊。
Current Evidence: integrity_anchor_violations 只计算 store_digest /
                  authority_manifest_digest / revocation_manifest_digest
                  （adoption_authority.py:123）；registry entry 写入不刷新
                  anchor（registry.py:69）；frozen 在 harness state 内。
Gap             : GAP-2 —— 指针类文件不在 anchor 内；同写者同时改 entry +
                  store + ledger 时 digest 一致性可被重写。
Invariant       : anchor 必须覆盖 store + authorities + revocation events +
                  registry entries + frozen records/snapshots；任一 mismatch
                  -> INTEGRITY_STORE_CORRUPTED（fail-closed，无 legacy 降级）。
                  同时显式声明：anchor 文件本身可由同一写者改写，这是本阶段
                  trust boundary；不宣称已防御密码学级篡改。
Minimal Change  : 1) anchor 增加 registry_manifest_digest
                     = sha256({family/name.json: sha256(entry bytes)})；
                  2) anchor 增加 frozen_manifest_digest
                     = sha256({candidate_id: sha256(record bytes)
                               + sha256(snapshot dir digest)})；
                  3) integrity_anchor_violations 增加两项比对；
                  4) promote/reject/mark_promoted/revoke 后刷新 anchor；
                  5) anchor schema 升 v2，旧 anchor 需 operator 重新 seal。
New State       : anchor v2 字段 =
                  store_digest / authority_manifest_digest /
                  revocation_manifest_digest / registry_manifest_digest /
                  frozen_manifest_digest。
Negative Case   : entry 被改写（含 pointer swap）-> registry manifest digest
                  mismatch -> BLOCK。
Positive Case   : 所有锚定文件未变 -> ALLOW。
```

### R3 — seal 的 schema/version 进入 seal_digest

```text
Requirement     : SEAL_SCHEMA / SEAL_VERSION 纳入 seal_digest payload；
                  verify 继续全量重算（DSSE PAE 等价物）。
Current Evidence: seal_digest() payload 不含 schema/seal_version
                  （capabilityizer.py:114）；verify_frozen 单独比对字段常量
                  （capabilityizer.py:315）。
Gap             : GAP-4 —— 类型标签不在内容 hash 内。
Invariant       : 被 seal 的内容必须包含其 schema 标识与版本；
                  读取方必须以验证过的同一份字节进入消费逻辑。
                  v1 record 不变；v2+ record 的 seal_digest 必须覆盖 schema/version。
Minimal Change  : SEAL_SCHEMA = "frozen-candidate-v2"、SEAL_VERSION = "v2"；
                  seal_digest() 对 v2 增加
                  payload["seal_schema"] / payload["seal_version"]；
                  verify_frozen 按 record.seal_version 分派：v1 走现有字段
                  校验 + 旧 payload 重算；v2 走新 payload 重算。
                  新候选必须用 v2；已有 v1 record 不允许迁移。
New State       : frozen record 存在 v1 / v2 两种 seal_version；
                  只有 v2 满足“schema 在 digest 内”；
                  canonical 新候选从 v2 起。
Negative Case   : v1 record 被改成 v2 字段但 digest 未重算 ->
                  SEAL_SCHEMA_MISMATCH / SEAL_DIGEST_MISMATCH -> BLOCK。
Positive Case   : v2 record 重算 == 存储 seal_digest -> ALLOW。
```

### R4 — runtime 执行对象改为内容寻址引用

```text
Requirement     : promote 后保存 digest 命名的不可变快照（或归档）；
                  runtime 从快照派生挂载，而不是每次复用可变目录路径。
Current Evidence: promote copytree -> registry/<family>/<name>/artifact
                  （registry.py:69）；entry.artifact_dir 是可变目录；
                  verify_at_mount 与内核 bind mount 之间窗口 = UNKNOWN
                  （runtime_adoption_guard.py:415；harness.py:748-750）。
Gap             : GAP-5 —— 运行对象不是内容寻址快照。
Invariant       : runtime input == verified artifact；
                  挂载路径必须是 digest 命名的快照目录；
                  快照创建后不再写入；任何路径解析不能绕过 digest 验证。
Minimal Change  : promote 中 artifact_dst 改为
                  registry_root / family / "artifacts" / artifact_digest
                  （digest 命名；create-if-absent，已存在同 digest 则复用）；
                  entry.artifact_dir 指向该快照；保留 adopt +
                  verify_at_mount + expected digest 比对；只读挂载不变。
                  存量 entry（旧路径布局）保持不变或重新 promote。
New State       : artifact 快照按 digest 命名；路径不再是“名字/目录”可变指针。
Negative Case   : 快照字节被改 -> verify_at_mount digest mismatch -> BLOCK；
                  artifact_dir 指向不同 digest 目录 -> mismatch -> BLOCK。
Positive Case   : 快照 digest == expected -> ALLOW。
Note            : 目录快照缩小但不能数学关闭 verify 与内核 mount 之间的
                  OS 竞态；该窗口继续声明为 UNKNOWN。完整关闭需要
                  镜像/归档（本期 Non-Goal）。
```

### R8 — DSSE 验证字节契约

```text
Requirement     : 验证字节必须原样进入消费层；防“验 A 用 B”。
Current Evidence: harness.py:741-750 已满足 —— adopt/verify_at_mount 与
                  docker_launch 使用同一 artifact_dir 变量，无二次解析。
Gap             : 契约未写成 runtime guard 的 contract；未来重构可能引入
                  “verify A, run B”而不被察觉。
Invariant       : mount_source == verified artifact_dir == adopt 报告捕获的路径；
                  验证后禁止任何调用方再次解析/替换路径。
Minimal Change  : 在 verify_at_mount 的 docstring 固化 contract；
                  新增一个调用点断言（下一阶段测试）：
                  adopt/verify_at_mount(dirA) 后 docker_launch 传入 dirB
                  必须被 guard 拒绝或由 harness 结构上不可能发生；
                  B3 路径保持单一 artifact_dir 来源。
New State       : runtime guard contract 文本 + 一个可运行反例测试。
Negative Case   : verify 后路径被替换 -> 断言/重验失败 -> REJECT。
Positive Case   : 同一路径原样执行 -> ALLOW。
```

## 12. Adversarial Scenarios

统一判定：

```text
字节漂移 / 身份漂移 / 意图漂移 => REJECT（fail-closed）
字节等价但身份不同             => 不合并身份；identity 以 authority 为准
同写者同时改写 anchor          => 声明为 trust boundary 之外，本期不防御
```

### Case A — Evaluation(A) → Promotion(B)

```text
判定：REJECT
机制：issue_authority 与 registry.promote 都执行
      evaluation_binding_violations(evaluation_A, frozen_B)；
      A 的 candidate_id/artifact_digest/seal_digest 与 B 的 frozen record
      不等 -> EVALUATION_BINDING_MISMATCH -> ADOPTION_BLOCKED。
残余：无（字节与身份都不一致时必然命中）。
```

### Case B — Evaluation(A) → Registry→B → Adopt

```text
判定：REJECT（B 与 A 身份/字节不同时）
机制：adopt 校验 entry.adoption（B）与 authority（A）的 BINDING_KEYS 全等
      -> ENTRY_BINDING_MISMATCH；frozen/eval/digest 六方不等 ->
      CANDIDATE_ID_MISMATCH / ARTIFACT_DIGEST_MISMATCH -> BLOCK。
边界：若仅 artifact_dir 被指到与 A 字节相同的另一目录，adopt 通过
      （字节等价）；这是 R1 预期 digest + R2 entry 锚定要消除的
      意图漂移面，身份记录仍保持 A。
```

### Case C — Promotion(A) → Runtime resolves B

```text
判定：REJECT（字节不同）；R1 后 REJECT（任何其他合法候选 B）
机制：adopt + verify_at_mount 重算 live digest；B 字节 != A digest
      -> ARTIFACT_DIGEST_MISMATCH -> BLOCK。
现状缺口：b3_entry name 被改为另一合法候选时，系统完整验证并运行 B
      （GAP-1）；R1 的 expected digest 比对使该情况 REJECT。
```

### Case D — Same digest, different identity

```text
判定：A != B；不得因 digest 相同合并身份
机制：identity = candidate_id + candidate_version + seal_digest +
      artifact_digest；digest 相同只是必要条件。authority/decision/run/
      entry 的 candidate_id/version 比对独立于 digest；
      R4 digest 命名快照可以共享字节，但记录身份保持分离。
```

### Case E — Same path, changed content

```text
判定：REJECT（或由不可变引用保证 X 不再可变）
机制：adopt（frozen_artifact_violations）与 verify_at_mount 对同一路径
      重算 canonical digest；内容变 -> ARTIFACT_DIGEST_MISMATCH -> BLOCK。
残余：verify_at_mount 返回与内核 bind mount 之间的窗口 = UNKNOWN；
      R4 快照 + 只读挂载缩小该窗口。
```

### Case F — Registry pointer swap（registry/foo: A -> B）

```text
判定：REJECT
机制：B 字节不同 -> adopt digest 比对 BLOCK；
      B 是另一候选 -> entry.adoption 与 authority BINDING_KEYS 不等 ->
      ENTRY_BINDING_MISMATCH BLOCK；
      R2 后 entry 进入 anchor -> registry_manifest_digest mismatch BLOCK。
边界：同写者同时改写 anchor = 边界外。
```

### Case G — Authority = A, runtime artifact = B

```text
判定：REJECT
机制：六方 digest 全等中 actual != authority.artifact_digest ->
      ARTIFACT_DIGEST_MISMATCH -> BLOCK（当前已实现）。
```

### Case H — Schema/version mutation（v1 -> v2, digest byte 关系不变）

```text
判定：现有 v1 record = REJECT；新候选按 v2 重新走完整生命周期
机制：v1 record 是 write-once；字段常量变化 -> SEAL_SCHEMA_MISMATCH
      -> verify_frozen BLOCK。当前 v1 的 schema/version 不在 seal_digest
      内（GAP-4），所以字段级校验是唯一防线；R3 之后 v2 的 schema/version
      进入 digest，该防线变成 digest 级。
冻结答案：允许 v2 作为新候选的 seal 版本（R3），不允许对已有 v1 record
      做“字节关系不变”的版本迁移；身份变更必须走新的
      freeze -> evaluate -> issue -> promote 生命周期。
```

## 13. Minimal Implementation Boundary

下一阶段（Phase 9-B.3，最小集）只允许改动：

```text
R1 : pilot/harness.py（b3_entry.json 写入/读取 + expected digest 比对）
R3 : src/forge/capabilityizer.py（seal_digest payload + SEAL_VERSION v2 +
     verify_frozen 版本分派）
R8 : pilot/runtime_adoption_guard.py（contract docstring）+ 一个契约测试
```

Phase 9-B.4（后续）：

```text
R2 : pilot/adoption_authority.py（anchor v2 + 两个 manifest digest）
     + pilot/registry.py / harness.py（刷新 anchor 的调用点）
R4 : pilot/registry.py（digest 命名快照布局）+ harness.py 消费
```

约束：

```text
不新建数据库 / 服务 / 外部依赖
不引入 Sigstore / OCI / Kubernetes / in-toto layout
不修改 legacy Phase 8 非 canonical 路径
不迁移已有 v1 frozen record
不改多 artifact allowlist 语义（GAP-6 留待 intake 阶段）
```

## 14. Non-Goals

```text
密码学签名 / PKI / Sigstore（GAP-3 保持应用层边界声明）
内容寻址存储系统 / OCI 镜像 / 归档格式（R4 以 digest 目录为最小形态）
in-toto layout / 阈值模型 / SLSA L1-L3 / Kubernetes webhook
多 artifact / 多目录 intake 清单（GAP-6）
registry entry capability_id 与 seal capability_id 的统一
  （冻结为 Locator，若未来需要再立项）
v1 frozen record 的版本迁移
```

## 15. Acceptance Criteria

设计必须满足，并映射到可验证的失败码：

```text
A evaluated == A promoted == A authorized == A adopted == A executed
  -> EVALUATION_BINDING_MISMATCH / ENTRY_BINDING_MISMATCH /
     CANDIDATE_ID_MISMATCH / CANDIDATE_VERSION_MISMATCH /
     CANONICAL_IDENTITY_MISMATCH / 六方 digest 全等 / verify_at_mount

A -> B 在任何阶段发生 => REJECT
  -> 字节漂移：ARTIFACT_DIGEST_MISMATCH
  -> 身份漂移：ENTRY_BINDING_MISMATCH / CANDIDATE_ID_MISMATCH /
     CANDIDATE_VERSION_MISMATCH / EVALUATION_BINDING_MISMATCH
  -> 意图漂移（R1 后）：expected digest mismatch -> BLOCK

Same digest != Same identity
  -> identity 四元组独立于 digest；digest 相等永不合并记录

Same path != Same artifact
  -> path 只是 locator；adopt/verify_at_mount 每次重算 digest

Registry name != Security identity
  -> name/registry key 只用于 discover/索引；信任决策只用
     authority + 四元组 + digest
```

验收级测试（下一阶段实现后）：

```text
Case A-H 各一个 fail-closed 断言（BLOCK 且不产生副作用）
R1：b3_entry name 指向 B -> BLOCK
R2：entry 被改写 -> INTEGRITY_STORE_CORRUPTED
R3：v2 record schema 字段被改 -> SEAL_DIGEST_MISMATCH
R4：快照内容被改 -> ARTIFACT_DIGEST_MISMATCH；同 digest 快照复用
R8：verify(dirA) 后 run(dirB) 的路径被 guard 拒绝
```

## 16. Open Questions

```text
O1  verify_at_mount 与内核 bind mount 之间的 OS 竞态：
      R4 缩小但未数学关闭；是否需要镜像/归档级不可变引用，何时需要。
O2  b3_entry.json 位于 harness state 目录，不在 R2 anchor 范围内：
      R1 的 expected digest 由同一 harness 写入，同写者可同时改写；
      是否把预期引用移入 anchored store/registry entry，或显式声明
      state 目录属于同写者边界（本期默认后者）。
O3  entry.capability_id（随机）vs seal capability_id（确定性派生）：
      冻结为 Locator，是否需要统一，统一时是否会影响 run record 兼容。
O4  legacy Phase 8 非 canonical 路径的最终处置：保留 / 弃用 / 迁移。
O5  R2 的 anchor v1 -> v2：存量 sealed store 的重新 seal 流程与操作顺序。
O6  GAP-6 多 artifact allowlist：何时进入 intake 契约（与 Phase 9-B.1
      candidate-seal-v1 的多文件扩展一起）。
```

## 17. Final Verdict

```text
PHASE 9-B.2 DESIGN VERDICT

DESIGN = READY

R1 = FROZEN
R2 = FROZEN
R3 = FROZEN
R4 = FROZEN
R8 = FROZEN

IDENTITY_MODEL = frozen-candidate 四元组
  (candidate_id, candidate_version, artifact_digest, seal_digest)
  + artifact_identity 类型判别符（CANONICAL_ARTIFACT_IDENTITY_V1）；
  digest = security identity；name/path/registry key/capability_id = locator；
  seal schema/version 自 v2 起进入 digest。

IMPLEMENTATION_BOUNDARY = pilot canonical 路径
  （CANONICAL_ARTIFACT_IDENTITY_V1）+ authority/store/anchor；
  Phase 9-B.3 = R1 + R3 + R8（无布局变更）；
  Phase 9-B.4 = R2 + R4（anchor manifests + digest 命名快照）；
  不新增存储/服务/依赖；legacy Phase 8 路径与 v1 frozen record 不动。

OPEN_QUESTIONS = O1 OS bind-mount 竞态；O2 b3_entry 锚定；
  O3 capability_id 双义；O4 legacy 路径处置；O5 anchor v1->v2 重 seal；
  O6 多 artifact intake（GAP-6）。

NEXT_PHASE = Phase 9-B.3：实现 R1 + R3 + R8 的最小 fail-closed 契约
  + 对应断言测试；随后 Phase 9-B.4：R2 + R4。
```

本阶段结束条件确认：只新增本文件，未修改 production code、未增加 production
tests、未 commit。
