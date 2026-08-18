# 04 Cosign 代码考古

仓库：`https://github.com/sigstore/cosign`
固定 commit：`8b8c87b68a75f70c12e1adf25f9bb87f24abea7e`（2026-08-14）
证据来源：真实 verifier 源码（`pkg/cosign/verify.go`、`pkg/cosign/verifiers.go`）。

## 1. 核心问题

> Cosign 如何同时验证“是谁签的”和“签的是什么”？

答案在 `VerifyImageSignatures -> verifySignatures -> verifyInternal` 链路：

```text
tag -> ResolveDigest -> digest H            （先解析定位，签名按 digest 查找）
signature bytes + payload
  -> 密码学验证签名（verifyOCISignature）
  -> 证书链到 trusted root（ValidateAndUnpackCertWithIntermediates）
  -> 证书策略：SAN subject + OIDC issuer（CheckCertificatePolicy）
  -> SCT / transparency log
  -> ClaimVerifier：payload 内 digest == H
```

## 2. Tag -> Digest 解析（TOCTOU 第一道闸）

`VerifyImageSignatures`（`pkg/cosign/verify.go:650`）：

```go
// Enforce this up front.
if co.RootCerts == nil && co.SigVerifier == nil && co.TrustedMaterial == nil {
    return nil, false, errors.New("one of verifier, root certs, or trusted root is required")
}

digest, err := ociremote.ResolveDigest(signedImgRef, co.RegistryClientOpts...)
...
h, err := v1.NewHash(digest.Identifier())
...
st, err := ociremote.SignatureTag(digest, co.RegistryClientOpts...)
```

行为：**先把 tag 解析成 digest，再用 digest 去找签名**。这样签名的 payload 引用的是
digest 而非 tag；tag 之后怎么动都不影响这次验证的对象。

## 3. “谁签的”：证书链 + 身份策略

### 证书链（`ValidateAndUnpackCertWithIntermediates`，`verify.go:369`）

```go
verifier, err := signature.LoadVerifier(cert.PublicKey, crypto.SHA256)
...
if co.TrustedMaterial != nil {
    chains, err = verify.VerifyLeafCertificate(cert.NotBefore, cert, co.TrustedMaterial)
} else {
    chains, err = TrustedCert(cert, co.RootCerts, intermediateCerts)
}
...
err = CheckCertificatePolicy(cert, co)
```

行为：证书必须链到 verifier 配置的 trusted root（TUF/自定义池），否则失败。

### 身份策略（`CheckCertificatePolicy`，`verify.go:441`）

```go
oidcIssuer := ce.GetIssuer()
sans := cryptoutils.GetSubjectAlternateNames(cert)
// Identity 匹配 = issuer 匹配 AND subject(SAN) 匹配
if subjectMatches && issuerMatches {
    return nil
}
...
return &VerificationFailure{fmt.Errorf(
    "none of the expected identities matched ... got subjects [%s] with issuer %s", ...)}
```

`Identity`（`verify.go:66`）支持严格相等或正则：

```go
type Identity struct {
    Issuer        string
    Subject       string
    IssuerRegExp  string
    SubjectRegExp string
}
```

行为：证书里的 OIDC issuer + SAN 必须命中策略中至少一个 identity。**身份 = 证书
（Fulcio 签发的短期证书）里经 CA 认证的 OIDC 身份**，而不是一个自报字段。

## 4. “签的是什么”：payload digest 绑定

`verifyInternal`（`verify.go:829`）在密码学验签后调用 `ClaimVerifier`：

```go
if co.ClaimVerifier != nil {
    if err := co.ClaimVerifier(sig, h, co.Annotations); err != nil {
        return false, err
    }
}
```

### 镜像签名：`SimpleClaimVerifier`（`pkg/cosign/verifiers.go:33`）

```go
ss := &payload.SimpleContainerImage{}
if err := json.Unmarshal(p, ss); err != nil { return err }
foundDgst := ss.Critical.Image.DockerManifestDigest
if foundDgst != imageDigest.String() {
    return fmt.Errorf("invalid or missing digest in claim: %s", foundDgst)
}
```

行为：签名 payload 中 `critical.image.docker-manifest-digest` 必须等于解析出的 digest。

### 内嵌 attestation：`IntotoSubjectClaimVerifier`（`verifiers.go:59`）

```go
for _, subj := range st.Subject {
    dgst, ok := subj.Digest["sha256"]
    ...
    subjDigest := "sha256:" + dgst
    if subjDigest != imageDigest.String() { continue }
    ...
    return nil
}
return errors.New("no matching subject digest found")
```

行为：in-toto statement 的 subject digest 必须命中当前 digest。

## 5. 我的理解

Cosign 用一个**闭合验证序列**同时回答 who 和 what：

```text
who   = trusted root -> 证书链 -> SAN + OIDC issuer 策略
what  = ResolveDigest 得到当前字节身份 H
绑定  = 签名覆盖 payload，payload 内 digest 必须 == H
时间  = SCT/tlog/RFC3161 提供“签名时刻”并约束证书有效期
```

关键点：**签名绑定的是 digest 而不是名字**；名字（tag）只用于初始解析，解析后
立即被 digest 取代。这与本地“name 是 locator、digest 是 security identity”的判断一致。

## 6. 值得借鉴 / 不值得借鉴

### 值得借鉴

1. **先解析成 digest，再验证，再让下游只信 digest**：本地 `verify_at_mount` 已等价
   （重算 digest + expected 比对），但 runtime 记录仍以 capability/name 为主键；
   可借鉴“验证后只接受 digest 引用”的纪律。
2. **证书身份 + 签名 + payload 绑定三者合一**：本地没有密码学签名，issuer 是
   env 字符串；如果未来要签名 authority，cosign 的“身份策略独立于签名算法”设计
   可直接参考。
3. **失败模式是 error 而非降级**：`verifyInternal` 任何一步失败都返回错误，
   没有“部分验证继续”的路径。

### 不直接借

1. **OCI/Sigstore 基础设施（Fulcio/Rekor/TUF）**：本地是 flat JSON + 文件 ledger，
   没有公钥体系；整套引入会重写当前 trust 模型。
2. **SimpleSigning payload 格式**：与本地 candidate contract 无关。
