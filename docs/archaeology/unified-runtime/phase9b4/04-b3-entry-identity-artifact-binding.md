# 04 b3_entry identity ↔ artifact binding

## verified_artifact_dir 来自哪里

```text
adopt report["verified_artifact_dir"]            <- Runtime 派生（guard:444）
   └─ 入参 artifact_dir = entry["artifact_dir"]  <- Registry 派生（harness:750, registry.py promote 写入）
        └─ 该目录字节必须 == frozen record artifact_digest（frozen_artifact_violations）
           └─ frozen seal_digest 必须 == authority.seal_digest（anchored）
```

结论：verified_artifact_dir 本身是 **Runtime-derived**，其路径值来自 registry entry；
系统证明 "目录属于同一四元组 identity" 的方式是 **字节 digest 全等**，不是路径名。
路径可以变，digest 不能变。

## 如果 b3_entry 被改成另一个目录

b3_entry v2 没有 artifact path / verified_artifact_dir / mount_source 字段（见 harness.py:636-641）。
probe P12 证明注入这些字段会被忽略。因此 "只改 b3_entry 的 locator" 在 canonical 路径上
只有 `name` 一个可改点，而 name 单独改会被四元组比对 REJECT（P6）。

## identity-to-runtime-object binding 状态

| 绑定 | 机制 | 状态 |
|---|---|---|
| Authority → artifact bytes | authority.artifact_digest；adopt 每次重算 + frozen 快照比对 | 闭合 |
| Registry entry → authority | BINDING_KEYS 全等 + ARTIFACT_DIGEST_MISMATCH 重验 | 闭合 |
| b3_entry 四元组 → adopt report | identity_violations 逐字段 | 闭合（单字段） |
| b3_entry "运行意图" → 具体候选 | 无锚定来源；name 决定 discover | **开放** |
| mount source → verified path | mount_source 比对 + harness 使用 report 唯一路径 | 闭合（O1 的 verify→bind 窗口除外） |

## 问题区分（不混为一谈）

- 问题 1 State Tampering：b3_entry 被改但 Runtime 仍验证并运行 A → REJECT（单字段）。
- 问题 2 Identity Drift：b3_entry A → Runtime B → ALLOW（整对象一致替换）。**security gap**。
- 问题 3 Locator Rebinding：identity A + path B → REJECT。**不是 gap**。

所以 Phase 9-B.3 的四元组 contract 已经闭合 "identity == artifact"，
但没有闭合 "intent == identity"：运行意图的选择点（b3_entry.name）不受任何锚定保护。

