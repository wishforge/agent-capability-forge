# 09 Phase 9-B.2 Design Gaps（只给问题与不变量，不给实现）

格式：Problem / Evidence / Industry mechanism / Current gap / Recommended invariant。

---

## GAP-1 运行意图只有名字，没有预期 digest

**Problem**
Runtime 以 `b3_entry.json["name"]` 解析要运行的候选；记录里只有
`name` + `capability_id`，没有“预期 artifact digest / seal digest”。

**Evidence**
`harness.py:633` 写入 `{"name", "capability_id"}`；`harness.py:689`
`registry.discover(..., name)`；adopt 验证的是“解析出来的对象”，不是“原本要运行的对象”。

**Industry mechanism**
SLSA 把 package name 的 expectations 与 provenance 的 artifact digest 分离
（verifying-artifacts.md “Expectations”）；Policy Controller 强制对象本身是 digest
引用（validator.go:1309）。

**Current gap**
如果把 name 指向另一个合法 promoted candidate，系统会完整验证并运行它，且所有
记录一致地指向它——没有对账点。

**Recommended invariant**
运行请求必须携带“预期 artifact digest”（或 seal digest）；runtime 解析后必须比对
“预期 digest == 解析对象的 digest”，不一致即 BLOCK。名字只能用于定位，不能用于确认意图。

---

## GAP-2 指针类文件不在 trust anchor 覆盖内

**Problem**
Registry entry（`family/name.json`）、`b3_entry.json`、`frozen_root` 路径都不是
trust anchor 的锚定对象。

**Evidence**
`integrity_anchor_violations`（adoption_authority.py:123）只计算
`store_digest / authority_manifest_digest / revocation_manifest_digest`；
registry 目录里的 entry 与 state 里的 b3_entry.json / frozen/ 不在其中。

**Industry mechanism**
SLSA 建议消费者在 download/install 时验证（verifying-artifacts.md）；Cosign 先
`ResolveDigest` 再验证（verify.go:670），把可变指针换成不可变 digest。

**Current gap**
应用层靠 digest 全等兜底；但同写者若同时改写 entry + store + ledger（未 seal 或
锚也被写），digest 一致性可被重写。anchored store 不覆盖 entry/frozen，属于
“锚定范围不完整”。

**Recommended invariant**
Trust anchor（或等价锚）必须覆盖：store + authorities + revocation events +
registry entries + frozen records/snapshots；无法覆盖的路径必须显式声明为
应用层边界（当前已是 UNKNOWN），不得宣称已防御。

---

## GAP-3 issuer 是字符串，不是密码学身份

**Problem**
Authority 的 “谁批准” 只有 `issuer_id` + env allowlist；没有签名，authority_id
是确定性 hash。

**Evidence**
`adoption_authority.py:45 authority_id_for` = sha256(candidate|version|decision)；
`issuer_allowed`（:281）在 allowlist 未设置时放行（legacy deterministic 模式）；
trust anchor 是 digest 文件不是签名。

**Industry mechanism**
in-toto：functionary 公钥签名 link（verifylib.py:402）；Cosign：证书链到 trusted
root + SAN/issuer 策略（verify.go:369,441）；SLSA：roots of trust 是
(public key, builder.id) 对。

**Current gap**
当前模型假设“能写 store + ledger + anchor 的人就是可信任写者”；在单机 pilot
边界内成立，但不能作为对外发布身份。

**Recommended invariant**
如果 authority 要成为跨进程/跨机器的信任对象，其“身份断言”必须由不可伪造的
签名承载（签名内容至少覆盖 authority 全字段 digest）；否则保持当前
“应用层信任边界内确定性 hash”并明确声明。

---

## GAP-4 seal 的 schema/version 未进入 seal_digest

**Problem**
`seal_digest` 覆盖 candidate 核心 + 三个 digest，但 record 级
`schema` / `seal_version` 只作为独立字段校验。

**Evidence**
`seal_digest()`（capabilityizer.py:114）payload 不含 `SEAL_SCHEMA` / `SEAL_VERSION`；
`verify_frozen`（:315）单独比较 record 的 schema/seal_version。

**Industry mechanism**
DSSE：payloadType 必须进入被签名输入（PAE），否则可发生 type confusion
（protocol.md）；envelope.md 要求验证字节原样进入应用层。

**Current gap**
当前 record 有 write-once 保护，实际风险低；但若未来允许 schema 迁移或外部读取，
“类型标签不在内容 hash 内”就是 DSSE 明确警告过的模式。

**Recommended invariant**
被 seal 的内容必须包含其 schema 标识与版本（等价于把 SEAL_SCHEMA/SEAL_VERSION
纳入 seal_digest payload）；读取方必须以“验证过的同一份字节”进入消费逻辑。

---

## GAP-5 运行对象是可变目录，不是内容寻址快照

**Problem**
Runtime bind mount 的是 registry 下可变目录（`entry["artifact_dir"]`），
靠 verify_at_mount 的“验证-即用”窗口兜底。

**Evidence**
`harness.py:750` mounts `(artifact_dir, "/artifact", True)`；sandbox.py:22 直接
`docker run -v host:container:ro`；phase9b1 报告承认 OS bind-mount 竞态 = UNKNOWN。

**Industry mechanism**
Policy Controller：mutating 把 tag 固定为 digest，Kubelet 从内容寻址 registry 拉取
（validator.go:1103）；容器镜像是不可变字节（digest 即身份）。

**Current gap**
目录在两次 digest 计算之间仍可被同权限进程修改；且 promote 时复制的是目录快照，
但该快照没有 digest 命名的不可变副本。

**Recommended invariant**
Runtime 执行对象必须是**内容寻址的不可变引用**（例如 digest 命名的快照目录，
或镜像/归档层），而不是一个可变的、以路径命名的目录；若保留目录挂载，必须
在挂载前一刻从不可变快照派生。

---

## GAP-6 多 artifact 的 intake 清单尚未成为契约

**Problem**
canonical digest 依赖显式 allowlist，但 Pilot 固定为 `["main.py"]`；清单来源
是 `freeze_candidate_dir` 内部硬编码。

**Evidence**
`freeze_candidate_dir`（capabilityizer.py:534）构造
`"files": allowlist = ["main.py"]`；`capabilityize` 只写一个 main.py。

**Industry mechanism**
in-toto：materials/products 由 functionary 显式记录，布局规则验证
（runlib.py:69; verifylib.py:1014）。

**Current gap**
不是当前路径的身份漏洞（allowlist 固定反而更小），但多文件/多目录 Candidate
一旦引入，allowlist 必须来自 intake 契约，否则 digest 覆盖范围将取决于调用方。

**Recommended invariant**
artifact digest 的覆盖范围（allowlist）必须由 schema 定义并随 candidate 一起
seal；运行时不得接受“非声明文件不影响 digest”的宽松语义（当前 exact layout
已满足）。

---

## 汇总

| Gap | 严重度 | 是否必须进入 9-B.2 |
|---|---|---|
| GAP-1 预期 digest 缺失 | 中（审计/意图漂移） | 建议 |
| GAP-2 anchor 覆盖不完整 | 中（边界声明问题） | 建议（先定边界） |
| GAP-3 issuer 无签名 | 低（单机边界内可接受） | 视发布需求 |
| GAP-4 seal schema 不进 digest | 低 | 顺手修正 |
| GAP-5 可变目录运行时 | 中（TOCTOU 残余） | 建议（快照化） |
| GAP-6 allowlist 契约 | 低-中（未来多文件时） | 与 intake 一起做 |
