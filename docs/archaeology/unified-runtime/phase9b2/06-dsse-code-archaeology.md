# 06 DSSE 代码考古

仓库：`https://github.com/secure-systems-lab/dsse`
固定 commit：`1d3370f62565bca041e97c8310b873ac340edc2e`（2026-07-23）
证据来源：规范本身（这是 spec 仓库，`envelope.md` + `protocol.md` + `envelope.proto`）。

## 1. Envelope

`envelope.md`（v1.0.2）标准 JSON envelope：

```json
{
  "payload": "<Base64(SERIALIZED_BODY)>",
  "payloadType": "<PAYLOAD_TYPE>",
  "signatures": [{
    "keyid": "<KEYID>",
    "sig": "<Base64(SIGNATURE)>"
  }]
}
```

字段规则：

```text
payload / payloadType / signature.sig   REQUIRED（即使空也必须设置）
signature.keyid                         OPTIONAL，MUST NOT 用于安全决策
未知字段                                MUST ignore
```

## 2. PAE 与签名定义

`protocol.md`：

```text
SIGNATURE = Sign(PAE(UTF8(PAYLOAD_TYPE), SERIALIZED_BODY))

PAE(type, body) =
  "DSSEv1" + SP + LEN(type) + SP + type + SP + LEN(body) + SP + body
```

其中 `LEN(s)` = 字节长度的 ASCII 十进制、无前导零；`type` 是 opaque、大小写敏感的
payloadType。

验证协议（原文行为）：

```text
1. 解码 SERIALIZED_BODY / PAYLOAD_TYPE / SIGNATURE；失败即拒绝
2. （可选）用 KEYID 缩小候选公钥；KEYID 本身不参与安全判断
3. 用 PAE(UTF8(PAYLOAD_TYPE), SERIALIZED_BODY) 验签；失败即拒绝
4. 拒绝不支持的 PAYLOAD_TYPE
5. 按 PAYLOAD_TYPE 解析 SERIALIZED_BODY；失败即拒绝
```

## 3. 为什么 DSSE 不只是 hash payload？

普通签名（`Sign(payload)`）不认证 payload 的**解释方式**。同一字节可以被两个应用
解释成不同结构（例如一个是 in-toto statement，另一个是任意 JSON 配置），导致
type confusion。

DSSE 把 `payloadType` 放进被签名的 PAE：

```text
payloadType 是 Authenticated 参数（协议表格：PAYLOAD_TYPE  Required=Yes  Authenticated=Yes）
keyid 是 Unauthenticated 参数（Required=No  Authenticated=No）
```

因此攻击者不能：

```text
1. 把 payload 从类型 A 改标为类型 B（payloadType 变了 -> 验签失败）
2. 把 payload 字节替换为另一个同类型字节（字节变了 -> 验签失败）
3. 通过 keyid 伪装身份（keyid 不被签名）
```

Envelope 还有一个强制要求（`envelope.md` Security considerations / `protocol.md`）：

```text
Implementations MUST ensure that the same payload bytes that are verified are
the ones sent to the application layer. In particular, implementations MUST
NOT re-parse the envelope after verification to pull out the payload.
```

即：验证后的 payload 字节必须原样进入应用层，不能“验完再重新解析 envelope 拿 payload”，
否则验证对象和消费对象可以不一致——这正是 TOCTOU/rebinding 的元数据版本。

## 4. 对 Candidate Seal 的借鉴价值

本地 seal（`capabilityizer.py:114 seal_digest`）已经是
`sha256(canonical_json(frozen core + artifact_digest + manifest_digest + tests_digest))`：

```text
类比 DSSE：
  SERIALIZED_BODY   ~ candidate 核心字段 + digest 集合
  PAYLOAD_TYPE      ~ schema_version（在 FROZEN_CORE_KEYS 内，已进 payload）
  SIGNATURE         ~ seal_digest（本地是 HMAC-less digest，不是密码学签名）
```

观察（如实）：

- 已借鉴：schema 语义被纳入被 hash 的 payload（`schema_version` 在
  `FROZEN_CORE_KEYS` 中），所以把同一 candidate 改成另一个 schema 会改变
  seal_digest。
- 未完全对齐：record 级 `schema`（`"frozen-candidate-v1"`）与 `seal_version`
  （`"v1"`）**不在 seal_digest 的计算范围内**，只在 `verify_frozen`
  （capabilityizer.py:315）里作为 record 字段单独校验。当前攻击面小（record 本身
  由 write-once 保护），但按 DSSE 原则，类型/版本标签应与内容一起被认证。
- 当前 seal 无密码学签名；`seal_digest` 是完整性摘要，不是“谁 seal 的”证据。
  DSSE 的 PAE 结构本身不要求签名算法，只要求 payloadType 进签名输入；本地若未来
  给 authority 加签名，应把 `schema_version`（含 seal schema/version）放入被签内容。

## 5. 值得借鉴 / 不值得借鉴

### 值得借鉴

1. **类型/版本标签必须是被认证内容的组成部分**：建议 seal_digest 把
   `SEAL_SCHEMA` / `SEAL_VERSION` 纳入计算（当前只是 record 字段）。
2. **验证字节必须原样进入消费层，禁止验后重解析**：本地 runtime 已经满足
   （digest 在 verify 后直接与 mount 对象比对），可把该原则写成 contract 注释，
   防止未来重构引入“验 A 用 B”。
3. **keyid/名字类字段不可作安全决策**：对应本地结论——`candidate_id` / `name`
   是标签，不能单独作安全身份。

### 不直接借

1. **JSON envelope 的 base64 编码约定**：本地是 flat JSON 文件，无必要。
2. **多签名 threshold 模型**：当前单 issuer 模型，不需要 `(t,n)`。
