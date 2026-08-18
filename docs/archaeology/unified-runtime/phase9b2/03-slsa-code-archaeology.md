# 03 SLSA 代码考古

仓库：

- `https://github.com/slsa-framework/slsa`，固定 commit `1686afeba11a456e470235ecf50cfc0d2f9ecbc3`
- `https://github.com/slsa-framework/slsa-github-generator`，固定 commit `bb91a05077afa6601a3d7538c4cbbdbf0abe7ed9`

证据来源：SLSA v1.0 规范（`spec/build-provenance.md`、`spec/verifying-artifacts.md`）+ generator 真实 Go 源码。

## 1. Provenance 结构（v1.0）

`spec/build-provenance.md`，predicateType `https://slsa.dev/provenance/v1`：

```text
Statement（in-toto attestation 框架）
  subject[]: [{name, digest}]            # 产出物身份：名字 + 内容 digest
  predicateType
  predicate:
    buildDefinition:
      buildType                            # 构建模板的 TypeURI
      externalParameters                   # 外部可控输入（untrusted，必须下游验证）
      internalParameters                   # 平台内部输入（trusted，可不验证）
      resolvedDependencies[]               # 构建时拉取/依赖的 artifact（uri + digest）
    runDetails:
      builder:
        id                                 # 受信构建平台的传递闭包
        version
      metadata:
        invocationId
      byproducts[]
```

规范原文关键点：

```text
"The builder.id identifies this platform, representing the transitive closure
 of all entities that are trusted to faithfully run the build and record the
 provenance."

"Consumers MUST accept only specific signer-builder pairs."
```

## 2. 三个概念的分离

SLSA 规范明确区分（`spec/verifying-artifacts.md`）：

| 概念 | 承担的责任 |
|---|---|
| identity | 谁/什么：builder.id（平台身份）、signer（签发者身份）、subject.name（制品名） |
| artifact digest | 制品内容：subject.digest，把 provenance 绑定到具体字节 |
| provenance | 过程：buildDefinition（如何构建）+ runDetails（何时、由谁） |

“一个 artifact 是由这个过程产生的”= 三个绑定同时成立：

```text
签名（signer）验证 provenance 完整字节
subject.digest == 实际 artifact digest
builder.id + signer 在 verifier 的 roots of trust 中（且是允许的 signer-builder 对）
buildType / externalParameters 符合消费者期望（Step 2）
```

## 3. 验证流程（`spec/verifying-artifacts.md`）

```text
Step 1 Check SLSA Build level:
  1. 验证 envelope 签名（用 roots of trust）
  2. 验证 statement.subject.digest == 待验证 artifact 的 digest
  3. 验证 predicateType
  4. 用 (recognized public keys, builder.id) 查表得 SLSA level
Step 2 Check expectations:
  builder identity / canonical source repository / buildType / externalParameters
  （不认识的 externalParameters 字段应当 REJECT）
Step 3 (可选) 递归验证 resolvedDependencies
```

架构选项：包生态在 upload 时验证（推荐）、消费者在 download/install 时验证、
monitor 持续验证。规范建议至少一处，且消费者侧验证防 “Threat G/I”（registry/传输
被攻破）。

## 4. 真实 builder 实现（slsa-github-generator）

### subject 解析：`internal/builders/generic/generic.go:77 parseSubjects`

```go
// 输入是 sha256sum 格式（base64），每行 "<digest> <name>"
shaDigest := strings.ToLower(strings.TrimSpace(parts[0]))
...
parsed = append(parsed, intoto.Subject{
    Name: name,
    Digest: slsacommon.DigestSet{"sha256": shaDigest},
})
```

subject digest 由 workflow 调用方提供，generator 做格式校验但不重新计算文件——这符合
SLSA 模型：**subject 是 builder 的受信输出**（`builder.id` 文档化声明 subject 字段由
谁生成）。

### provenance 生成：`slsa/provenance.go:44 HostedActionsGenerator.Generate`

```go
builderID := GithubHostedActionsBuilderID
if t.JobWorkflowRef != "" {
    builderID = fmt.Sprintf("https://github.com/%s", t.JobWorkflowRef)
}
...
return &intoto.ProvenanceStatement{
    StatementHeader: intoto.StatementHeader{
        Type:          intoto.StatementInTotoV01,
        PredicateType: slsa02.PredicateSLSAProvenance,
        Subject:       subject,
    },
    Predicate: slsa02.ProvenancePredicate{
        BuildType: g.buildType.URI(),
        Builder: slsacommon.ProvenanceBuilder{ID: builderID},
        Invocation:  invocation,
        BuildConfig: buildConfig,
        Materials:   materials,
        Metadata:    metadata,
    },
}, nil
```

builder.id 来自 OIDC token 的 `JobWorkflowRef`（`slsa/provenance.go:70-74`），签名由
signer（Sigstore）完成（`internal/builders/generic/attest.go:97-102`）。

## 5. 我的理解

SLSA 把“这个 artifact 是这个过程产生的”拆成：**受信平台声明 + 密码学签名 + 消费者
把 subject.digest 绑定到真实字节**。它不解决“验证后字节又被换掉”——它把验证位置
的责任明确交给消费者（upload / download / monitor 三选一，推荐 upload+consumer）。

与本地对比：

| SLSA 概念 | 本地对应 |
|---|---|
| subject.name + digest | registry entry name + `artifact_digest` |
| builder.id | authority.issuer_id + policy_ref（字符串，非 keyid） |
| externalParameters | decision.policy_ref / evaluation 记录 |
| resolvedDependencies / materials | `immutable_artifact_refs`（目前只有 `artifact:<digest>`） |
| signer identity | issuer allowlist（env） |
| roots of trust | trust anchor（digest 根，非签名） |
| consumer 侧验证 | adopt + verify_at_mount |

## 6. 值得借鉴 / 不值得借鉴

### 值得借鉴

1. **subject digest 作为唯一绑定点**：本地已等价实现（authority/decision/run/
   candidate/entry/artifact 六方 digest 全等）。
2. **外部参数显式区分 trusted/untrusted**：SLSA 把 `externalParameters` 视为
   untrusted 且必须下游验证；本地 `evaluation` 和 `policy` 是 untrusted 输入，但
   policy 是否被运行时“重验字段”而非“重验来源”值得对照。
3. **signer-builder 配对**：`builder.id` 与 signer 必须成对信任。本地 authority
   的 issuer 与 artifact_identity 可以类比；目前没有“issuer 只能签发 canonical
   identity”的显式约束（实际由 issue 路径强制，但契约未表达）。
4. **期望值验证（Step 2）**：本地有 policy_ref/policy_version 检查，等价于最小
   期望验证；SLSA 的“拒绝未识别 externalParameters”与本地 exact layout 精神一致。

### 不直接借

1. **完整 SLSA level 体系（L1-L3 与平台安全模型）**：本地是单机 pilot，没有多租户
   build platform，L3 的“平台内部受信边界”文档化价值大于实现价值。
2. **OIDC / Sigstore 签名基础设施**：本地没有公钥基础设施；直接引入是过度建设。
   如果未来要对外发布 Candidate，再考虑。
