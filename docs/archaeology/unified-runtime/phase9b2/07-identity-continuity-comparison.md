# 07 跨项目对照矩阵

固定版本见 `00-code-archaeology-plan.md`。所有单元写“机制 + 源码证据”，不写空泛的
“支持”。

## 1. 机制要点速览

| 项目 | 一句话机制 |
|---|---|
| Agent Capability Forge | frozen seal digest 全链透传；authority write-once + trust anchor；mount 前重算 digest |
| in-toto | root 签 layout，functionary 签 link；MATCH 规则对路径+hash 双重相等；队列+DISALLOW |
| SLSA | 受信 builder 签 provenance；subject.digest 绑 artifact；消费者按期望值验证 |
| Cosign | 先 tag->digest；签名+证书链+SAN/issuer 策略+payload digest 比对 |
| Policy Controller | mutating 把 tag 改 digest；validating 拒绝非 digest；cosign 验证 + fail-closed |
| DSSE | payloadType 进 PAE 一起签名；验签后原字节进应用层 |

## 2. 矩阵

### Artifact identity

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| canonical digest = sha256(排序路径+文件 hash)，allowlist-only，exact layout（capabilityizer.py:49,54） | materials/products = `{path: {alg: digest}}`，由 functionary 记录（models/link.py:52-64；runlib.py:69） | subject.digest = 制品内容身份（spec/build-provenance.md; verifying-artifacts.md Step 1.2） | payload `docker-manifest-digest` 与 ResolveDigest 结果比对（verifiers.go:33） | 强制 image 必须是 digest，否则拒绝（validator.go:1309） | payload 是被签字节；digest 语义由 payloadType 决定 |

### Candidate identity

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| candidate_id = 随机标签；candidate+version+digest+seal 四元组才构成安全身份（capabilityizer.py:656,392） | step name + functionary keyid + layout 签名（verifylib.py:402） | signer-builder 对 + builder.id（verifying-artifacts.md Step 1） | 证书 SAN + OIDC issuer 策略（verify.go:441） | Authority 是 policy 对象，identity 由 ClusterImagePolicy 配置表达（clusterimagepolicy_types.go:66） | keyid 不参与安全决策（protocol.md：KEYID Unauthenticated） |

### Provenance

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| authority.provenance = policy/evidence_manifest/run_ids/immutable_artifact_refs（runtime_adoption_guard.py:83） | link 记录 command/environment/byproducts，step 证据链（models/link.py） | buildDefinition+builder+resolvedDependencies（spec/build-provenance.md） | 签名 bundle + tlog/TSA 时间证据（verify.go VerifyBundle） | 验证结果可被 CIP policy 消费（validator.go:679） | envelope 本身是通用载体，不含业务 provenance |

### Step continuity

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| decision/run/authority/entry/live 六方 digest 全等（runtime_adoption_guard.py:92） | MATCH：上一步 products 与下一步 materials 路径+hash 相等（verifylib.py:645-762） | 无“链式步骤”语义；依赖递归验证（verifying-artifacts.md Step 3） | 单步验证：签名对象 digest == 被验证 digest | 单次 admission：验证 digest-pinned 对象 | 不表达步骤；保证 envelope 内部一致性 |

### Signer identity

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| issuer_id + env allowlist；无密码学签名（adoption_authority.py:281） | layout/root 签名 + functionary keyid 阈值（verifylib.py:360,402） | roots of trust: (public key, builder.id) -> level（verifying-artifacts.md Step 1） | 证书链到 trusted root + SAN/issuer（verify.go:369,441） | key/keyless authority 配置（clusterimagepolicy_types.go:66） | signature 由外部算法提供；keyid 不认证 |

### Trust root

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| 外部 integrity anchor JSON：store/authority/revocation manifest digest（adoption_authority.py:123） | root key 签 layout（verify_metadata_signatures） | verifier 预配置 roots of trust | TUF/自定义 trusted material（verify.go:76,203） | TrustRoot/ClusterImagePolicy CRD（config/300-trustroot.yaml） | 无信任根概念；验证方自行决定 |

### Runtime/admission verification

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| adopt + verify_at_mount 在 bind mount 前重算 live digest（runtime_adoption_guard.py:297,415） | 不部署；验证 link 元数据后把 digest 交给消费者 | 推荐 upload/consumer/monitor 至少一处验证（verifying-artifacts.md Architecture options） | 验证发生在用户调用侧；输出是验证过的签名对象 | mutating 改 digest + validating 验签（validator.go:1103,1309） | 要求“验证字节原样进应用层”（envelope.md Security considerations） |

### Fail closed

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| 任何 missing/mismatch -> AdoptionBlocked；无 legacy fallback（runtime_adoption_guard.py:1-25） | DISALLOW/REQUIRE 抛 RuleVerificationError；阈值不足抛错（verifylib.py:1014,1180） | 期望值不匹配即 REJECT；未识别 externalParameters 应拒绝（verifying-artifacts.md Step 2） | 任一步失败返回 error（verify.go:829） | 无匹配策略默认拒绝；static fail（validator.go:404,567） | 解码/验签/类型不支持任一失败即拒绝（protocol.md） |

### Tamper detection

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| recorded/current hash + verify_frozen 重算 + trust anchor manifest（capabilityizer.py:315; adoption_authority.py:123） | 签名元数据；验证时重算目标 digest 由消费者做 | 签名 envelope + subject digest | 签名 + SCT + tlog 条目 | 复用 cosign | 签名覆盖 payloadType+payload |

### Identity drift detection

| Agent Capability Forge | in-toto | SLSA | Cosign | Policy Controller | DSSE |
|---|---|---|---|---|---|
| digest 全链相等拦截字节漂移；名字/指针漂移需 authority 交叉校验；b3_entry/registry entry 指针本身无锚定（见 08） | 链内 drift 由 MATCH 拦截；链外“最终交付物被换”需消费者绑定 digest | verifier 把 subject.digest 与真实 artifact 比对；名字与 provenance 分开（verifying-artifacts.md Expectations） | digest 解析先于验证，验证后只信 digest | digest 强制 + ClaimVerifier 双重绑定，tag 无法漂移 | payloadType 被认证，防止类型漂移 |

## 3. 关键差异总结

```text
行业共同点（五个项目全部具备）：
  1. 内容身份 = digest，名字 = locator
  2. 验证对象与运行对象必须共享同一个 digest 引用
  3. 失败默认拒绝，不降级
  4. 类型/版本/过程标签必须与内容一起被认证（DSSE/PAE；SLSA predicateType）

本地与行业的主要差距：
  A. 无密码学 signer 身份；issuer 是 env 字符串（确定性 hash 可被同写者伪造）
  B. registry entry 与 b3_entry.json 不在 trust anchor 覆盖内（指针可被同写者改）
  C. seal 的 schema/seal_version 未进 seal_digest payload（DSSE 缺口）
  D. 运行时按 name 解析 entry，再靠 digest 验证；行业则“先 pin digest，再只信 digest”
```
