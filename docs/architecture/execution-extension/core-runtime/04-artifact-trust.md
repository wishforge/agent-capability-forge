# 04 — Artifact Trust

## Four separate predicates

- **Artifact Identity**：哪一个 artifact 对象；由 Runtime 赋予稳定 identity。路径、URI、版本名可以是引用，不能单独证明内容 identity。
- **Artifact Provenance**：artifact 由哪个 Run/Attempt/Binding Epoch 产生或引用，并经过哪个 Execution Extension 观察。
- **Artifact Integrity**：当前 bytes/manifest 是否与声明一致，以及是否在读取/恢复时被替换。
- **Artifact Trust**：Runtime 是否接受该 artifact 作为后续输入、输出或恢复依据。

**ARCHAEOLOGY EVIDENCE**：已有系统只有部分 path/package/version/session metadata，未证明完整 creator→execution→Attempt provenance 或 reload verification。

## Digest and trust anchor

`artifact_digest` 属于 integrity evidence，也可参与 content-addressed identity；它证明特定 bytes 与 digest 一致，不证明来源、权限、语义安全或外部 side effect。

Runtime 信任 artifact 的最小依据是：稳定 identity、完整 provenance、内容 integrity verification，以及符合当前 policy 的 trust decision。cryptographic digest 是通常必要的完整性依据，但并非单独充分。

候选 trust anchor（**OPEN PARAMETER**）包括 immutable snapshot、cryptographic digest、signed metadata、attestation；具体组合按 artifact class 决定。Provider/Infrastructure 可提供 attestation，最终 trust owner 仍是 Managed Runtime。

## Rollback

Artifact replacement/rollback 由 Managed Runtime 决定并由 Supervisor 编排验证。恢复 artifact 只改变可消费的 bytes/lineage；它不撤销已经发生的 world-state side effect。side-effect rollback 必须有独立 receipt、verification 与 compensation 语义，二者不能混同。

不可信或 provenance 不完整的 artifact 必须阻断消费，进入 verify、replacement、人工 gate 或终止路径；不能以“能读取”代替“可信”。

**OPEN PARAMETER**：digest algorithm、manifest 最小字段、签名/attestation policy、artifact store 与替换窗口不在本阶段定义。

