# 05 Sigstore Policy Controller 代码考古

仓库：`https://github.com/sigstore/policy-controller`
固定 commit：`e9dfc010306dacf9e563744e92e1f015c7418f1a`（2026-08-17）
证据来源：真实 admission 源码（`pkg/webhook/validator.go`、`pkg/webhook/validation.go`、
`pkg/webhook/clusterimagepolicy/clusterimagepolicy_types.go`）。

## 1. 职责定位

与本地 `runtime_adoption_guard.py` 同类：**在对象进入运行环境之前，根据可信 metadata
决定放行/拒绝**。Controller 用两个 Kubernetes admission webhook 实现：

```text
Mutating webhook   （ResolvePod/ResolvePodSpecable/...）：
  把 image tag 解析成 digest 并改写成 tag@digest
Validating webhook （ValidatePod/ValidatePodSpecable/...）：
  强制 image 必须是 digest，并对 digest-pinned image 做签名/attestation 策略验证
```

## 2. Admission 验证路径

### 2.1 强制 digest（`validatePodSpec`，`validator.go:259`）

```go
// Require digests, otherwise the validation is meaningless
// since the tag can move.
fe := refOrFieldError(c.Image, field, i)
```

`refOrFieldError`（`validator.go:1309`）：

```go
ref, err := name.ParseReference(image)
...
if _, ok := ref.(name.Digest); !ok {
    return apis.ErrInvalidValue(
        fmt.Sprintf("%s must be an image digest", image), "image")
}
```

行为：**非 digest 引用直接拒绝**。这是“名字不能作为安全身份”最直接的生产代码证据。

### 2.2 tag -> digest 改写（`resolvePodSpec`，`validator.go:1103`）

```go
// If we are in the context of a mutating webhook, then resolve the tag to a digest.
case apis.IsInCreate(ctx), apis.IsInUpdate(ctx):
    digest, err := remoteResolveDigest(ref, ociremote.WithRemoteOptions(...))
    ...
    cs[i].Image = fmt.Sprintf("%s@%s", tagRef.Name(), digest.DigestStr())
```

行为：用户在 create/update 时写 tag，webhook 先解析到 digest，把对象改写为
`name:tag@sha256:...`。Kubelet 之后按 digest 拉取。

### 2.3 策略匹配与验证（`validateContainerImage`，`validator.go:1233`）

```go
policies, err := config.ImagePolicyConfig.GetMatchingPolicies(ref.Name(), kind, apiVersion, labels)
...
if len(policies) > 0 {
    signatures, fieldErrors := validatePolicies(ctx, namespace, ref, policies, kc, ociRemoteOpts...)
    ...
}
```

### 2.4 per-policy 验证（`ValidatePolicy`，`validator.go:525`）

每个 `Authority`（key / keyless / static）走一条路径：

```go
case authority.Static != nil:
    if authority.Static.Action == "fail" { ... }   // 静态拒绝
case len(authority.Attestations) > 0:
    result.attestations, result.err = ValidatePolicyAttestationsForAuthority(...)
default:
    result.signatures, result.err = ValidatePolicySignaturesForAuthority(...)
```

至少一个 authority 通过即该 policy 通过；多个 policy 匹配时**全部必须满足**：

```go
// validator.go:453 注释原文
// "If multiple policies match a particular image, then ALL of those
//  policies must be satisfied for the image to be admitted."
```

### 2.5 签名/attestation 验证（`pkg/webhook/validation.go:39`）

```go
func validSignatures(ctx context.Context, ref name.Reference, checkOpts *cosign.CheckOpts) ([]oci.Signature, error) {
    checkOpts.ClaimVerifier = cosign.SimpleClaimVerifier
    sigs, _, err := cosignVerifySignatures(ctx, ref, checkOpts)
    return sigs, err
}

func validAttestations(ctx context.Context, ref name.Reference, checkOpts *cosign.CheckOpts) ([]oci.Signature, error) {
    ...
    checkOpts.ClaimVerifier = cosign.IntotoSubjectClaimVerifier
    attestations, _, err := cosignVerifyAttestations(ctx, ref, checkOpts)
    return attestations, err
}
```

即：直接复用 cosign 验证器，claim 中的 digest 必须匹配被验证的 ref。

### 2.6 Fail-closed（`setNoMatchingPoliciesError`，`validator.go:404`）

```go
switch pcConfig.NoMatchPolicy {
case policycontrollerconfig.AllowAll:
    return nil
case policycontrollerconfig.DenyAll:
    return noMatchingPolicyError
case policycontrollerconfig.WarnAll:
    return noMatchingPolicyError.At(apis.WarningLevel)
default:
    // Fail closed.
    return noMatchingPolicyError
}
```

默认（未配置）也是 fail-closed。

## 3. “Admission 验证的对象 == 最终运行对象”如何保证

机制是**两层 + 一个平台承诺**：

```text
1. Mutating：tag -> digest，把对象规格改写成 content-addressed 引用
2. Validating：拒绝非 digest 引用；对 digest 引用做 cosign 验证，
   ClaimVerifier 保证签名/attestation 的 digest == 该引用 digest
3. 平台承诺：Kubernetes 按规格中的 digest 拉取；tag 之后如何移动不再影响运行对象
```

本地等价物：

```text
adopt()（验证 live artifact digest == 全链 digest）
  ≈ validating webhook
verify_at_mount()（重算 + expected 比对，然后 mount 同一路径）
  ≈ mutating webhook 的“把对象固定到 digest” + kubelet 按 digest 拉取
```

## 4. 我的理解

Policy Controller 的要点不是“某个验证函数很强”，而是**验证对象和运行对象共享同一个
content-addressed 引用**：验证发生在 digest 上，运行也发生在 digest 上，中间没有
可移动的名字。本地路径（验证同一 `artifact_dir` 后 bind mount 同一 `artifact_dir`）
共享同样的思路，但路径本身是可移动的字符串——靠 mount 前的第二次 digest 重算来
关闭窗口，而不是靠“对象已被固定为 digest”。

## 5. 值得借鉴 / 不值得借鉴

### 值得借鉴

1. **拒绝非 digest 引用**（`must be an image digest`）。本地 runtime 目前接受
   `artifact_dir` 路径，再靠 digest 验证；可以类比为“允许 tag 进 webhook，但验证
   前必须解析成 digest 并改写”。对本地来说即：**adopt 后 runtime 只应持有
   artifact_digest，路径只是定位器**。
2. **Mutating 先解析、Validating 再拒绝非 digest**：两阶段各管一段，职责清晰。
   本地的 `adopt`（验证）+ `verify_at_mount`（重新验证）已覆盖，但没有任何字段
   强制“运行时引用必须是 digest”。
3. **默认 fail-closed + 无匹配策略也拒绝**：本地 `MISSING_ADOPTION_STORE` /
   `UNISSUED_AUTHORITY` 等已 fail-closed；policy 匹配层面（image 无匹配 policy）
   对应本地 `policy not registered` 检查。
4. **多个匹配 policy 全部必须满足**：本地多个 decision/authority 场景已有
   `STALE_DECISION` / `later_promote` 逻辑，精神一致。

### 不直接借

1. **Kubernetes webhook 框架 / knative duck types**：与本地文件型 registry 无关。
2. **Policy 表达式（rego/cue）**：本地 policy 是注册表 + 版本 + frozen 标志，
   暂不需要通用策略引擎。
