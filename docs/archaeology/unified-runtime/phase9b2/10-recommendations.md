# 10 Recommendations（ADOPT / ADAPT / DO NOT ADOPT）

依据：`01`（本地链）、`02-06`（外部源码）、`07-09`（对照与 gap）。

## ADOPT（机制正确且本地可直接采用/已等价，最小改动）

### R1 运行时“预期对象”用 digest 记录

- 来源：Policy Controller（validator.go:1309 拒绝非 digest）、SLSA（subject digest
  与名字分离）。
- 内容：运行请求记录预期 `artifact_digest`（可选 seal_digest）；runtime 解析后必须
  比对预期 digest 与解析对象 digest。
- 解决：GAP-1。

### R2 trust anchor 覆盖范围显式化

- 来源：Cosign/Sigstore trusted root 是全部验证的前提（verify.go:76）。
- 内容：把 registry entries + frozen records 纳入锚定清单，或明确写成
  “不锚定、同写者边界内”的声明，二选一，不许含糊。
- 解决：GAP-2。

### R3 seal 的 schema/version 进入 seal_digest

- 来源：DSSE PAE（protocol.md）。
- 内容：`SEAL_SCHEMA` / `SEAL_VERSION` 纳入 seal_digest payload；verify 继续全量
  重算。
- 解决：GAP-4。

### R4 runtime 执行对象改为内容寻址引用

- 来源：Policy Controller mutating（validator.go:1103）+ OCI digest 不可变性。
- 内容：promote 后保存 digest 命名的不可变快照（或归档），runtime 从快照派生挂载，
  而不是每次复用可变目录路径。
- 解决：GAP-5 的残余 TOCTOU。

## ADAPT（机制正确，但需按本地模型裁剪）

### R5 in-toto 式 step continuity 清单

- 借鉴：MATCH 的“路径 + hash 双匹配”（verifylib.py:645）与队列 + DISALLOW
  （verifylib.py:1014）。
- 裁剪：本地是线性链，不需要 layout DSL；当 Candidate 出现多产物/多中间步骤时，
  用“上一步产物清单 == 下一步输入清单”替换目前隐式的 digest 全等。

### R6 SLSA 式期望值验证

- 借鉴：builder/signer 配对 + externalParameters 必须被下游验证
  （verifying-artifacts.md Step 1-2）。
- 裁剪：本地没有 builder.id；等价物是 `issuer_id + artifact_identity +
  policy_ref` 的固定组合。若未来引入签名，应把“issuer 只能签 canonical identity”
  作为显式配对约束。

### R7 Cosign 式身份策略字段

- 借鉴：身份匹配 = subject(SAN) AND issuer，且任一不匹配即失败（verify.go:441）。
- 裁剪：本地 issuer 是 env 字符串；当前保持字符串 allowlist，但契约上应写清楚
  “issuer 是应用层身份，不是密码学身份”，并预留 issuer_type 扩展（已有
  `issuer_type` 字段）。

### R8 DSSE 验证字节契约

- 借鉴：验证字节必须原样进入消费层（envelope.md Security considerations）。
- 裁剪：本地 `verify_at_mount -> docker_launch` 已满足；把它写成 runtime guard
  的 contract 注释/测试断言，防止未来重构把“验证 A 运行 B”悄悄引入。

## DO NOT ADOPT（不应引入）

### N1 in-toto 完整 layout / 阈值 / 子布局模型

本地是单线性链；layout DSL、GPG key 管理、threshold 是过度建模。等真正出现
多分支供应链再评估。

### N2 SLSA L1-L3 平台安全模型

本地没有多租户 build platform；L3 的“平台传递闭包”文档化价值大于当前实现价值。

### N3 Sigstore 全套（Fulcio / Rekor / TUF / OCI）

单机 pilot 没有公钥基础设施；整套引入会重写 trust 模型，收益不匹配。
对外发布 Candidate 时再评估。

### N4 Kubernetes webhook / knative 框架

与文件型 registry 无关；Policy Controller 的**机制**已抽象成 R1/R4，
不需要其运行时。

### N5 DSSE JSON envelope / (t,n) 多签名

本地 flat JSON 不需要 base64 envelope；单 issuer 不需要阈值签名。

## 优先级建议

```text
P0（下一阶段最小集）：
  R1 预期 digest + R4 内容寻址快照 + R2 锚定范围声明
P1：
  R3 seal schema/version + R8 验证字节契约
P2（视发布需求）：
  R5 多产物清单 + R6/R7 身份配对与签名
```

其中 R3/R8 是几行级改动；R1/R4 是 contract 级改动，需要先做设计评审
（属于 Phase 9-B.2 的“先研究事实，再决定实现”）。
