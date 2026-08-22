# 05 — Artifact and Recovery

## Artifact

四个概念必须分开：

```text
Artifact Identity      = 哪一个对象
Artifact Provenance    = 它从哪里产生、经过哪些 Attempt
Artifact Integrity     = 当前内容是否与声明一致
Artifact Trust         = Runtime 是否接受它作为可用输入/输出
```

Artifact 属于 Managed Runtime 的 durable lineage；Attempt 负责产生或引用它，Extension 只报告 artifact/reference 和可观察的 metadata。Runtime trust boundary 负责 provenance、integrity verification 与 trust decision；Infrastructure/Provider 可提供 attestation，但不能替 Runtime 作最终接受决定。

当前不预设 digest 算法、trust anchor、manifest 格式或 artifact store。

## Recovery facts

```text
execution result != side-effect fact
```

必须区分：

- `SUCCESS`：执行结果可信；不自动推导外部副作用已提交，除非有对应事实。
- `FAILURE`：执行报告失败；仍不自动推导没有副作用。
- `UNKNOWN`：结果传递或观察不足，无法判断副作用事实。

Extension 可提供 tool-specific receipt、idempotency key、verification probe 或 undo hook；它们是能力，不是统一保证。Runtime 记录事实和 recovery policy；Supervisor 在 UNKNOWN 后作 reconciliation。

副作用分类：

- **idempotent**：重复执行语义安全
- **deduplicatable**：可用 operation identity 抑制重复
- **verifiable**：可查询真实提交状态
- **compensatable**：存在有意义的反向动作
- **non-compensatable**：不能可靠撤销

这些属性可以同时成立，也可以都不成立。没有 receipt/verification 时，不得伪造 SUCCESS；没有安全 compensation 时，不得自动补偿。

## Recovery ownership

Runtime 决定 durable outcome、retry admission、human gate 和终止语义；Supervisor 执行 reconciliation、verification、compensation orchestration；Extension 仅执行并报告可观察事实。
