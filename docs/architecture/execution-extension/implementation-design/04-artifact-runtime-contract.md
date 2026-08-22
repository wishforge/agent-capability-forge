# 04 — Artifact Runtime Contract

Runtime 将以下四个判断分开承载：

| Concern | Contract owner | Meaning |
|---|---|---|
| Artifact identity | Runtime | 哪一个逻辑 artifact；由稳定 identity 与 content evidence 关联 |
| Provenance | Runtime | producing Run/Attempt/BindingEpoch、Extension observation、source lineage |
| Integrity | Runtime verification | 当前 bytes/manifest 是否匹配声明、读取时是否被替换 |
| Trust | Runtime policy | 是否接受为输入、输出或 recovery evidence |

`ARCHAEOLOGY EVIDENCE`：已有材料只支持部分 path/package/version/session metadata；完整 creator→Attempt provenance 与 trust gate 是 `DESIGN DECISION`。

## Operations

1. **Register**：Runtime 为新 artifact 建立 identity，附加 producing Attempt 或 source lineage；Extension 仅提交 reference/metadata。
2. **Attach provenance**：记录 creator → execution → Attempt → epoch 链；复制/派生 artifact 另记 source，不复制 identity。
3. **Calculate/verify digest**：Runtime 或受信 verifier 产生 integrity evidence；digest 证明 bytes 一致，不证明来源、权限或副作用。
4. **Decide trust**：Runtime 根据 identity、完整 provenance、integrity evidence、policy/attestation 作 trust verdict。
5. **Detect replacement**：不匹配时阻断消费，记录 inconsistency，交由 Supervisor verify/replacement/rollback；artifact restore 不等于 world-state compensation。

不得把 artifact content、artifact reference、artifact trust decision 合并为一个字段或一个事实。object storage、manifest、trust anchor、digest algorithm 均为 `OPEN PARAMETER`。
