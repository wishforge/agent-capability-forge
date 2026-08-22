# Core Runtime Semantic Model

本目录把 Phase 3 的边界推进为 Managed Runtime 的语义模型。本阶段只定义实体、状态、转移、不变量、ownership 与 recovery；不定义 API、REST、SDK、CRD、数据库 schema、migration 或实现。

## 阅读顺序

1. [01-run-semantics.md](01-run-semantics.md)
2. [02-attempt-state-machine.md](02-attempt-state-machine.md)
3. [03-binding-epoch.md](03-binding-epoch.md)
4. [04-artifact-trust.md](04-artifact-trust.md)
5. [05-recovery-semantics.md](05-recovery-semantics.md)
6. [06-isolation-policy.md](06-isolation-policy.md)
7. [07-supervisor-semantics.md](07-supervisor-semantics.md)
8. [08-runtime-semantic-model.md](08-runtime-semantic-model.md)

## Evidence labels

- **ARCHAEOLOGY EVIDENCE**：由已有 archaeology 或 architecture 文档直接支持。
- **DESIGN DECISION**：本 Managed Runtime 的规范性选择，不是 OSS 事实。
- **OPEN PARAMETER**：核心语义已限定边界，但仍需按部署或 tool class 选择。

## Core Runtime Semantic Gate

| Gate | 判断 | 依据 |
|---|---|---|
| A — Run semantics | CLOSED | Run/Attempt lineage、retry、resume、fork、completion 与 UNKNOWN 已定义。 |
| B — Attempt state machine | CLOSED | 状态、合法转移、crash continuation、retry 与 terminal rules 已定义。 |
| C — Binding epoch | CLOSED WITH OPEN PARAMETERS | active Attempt 的不可变 epoch 规则已定；编号格式与迁移原子性仍开放。 |
| D — Artifact trust | CLOSED WITH OPEN PARAMETERS | identity/provenance/integrity/trust 与 rollback 边界已定；digest/anchor 仍开放。 |
| E — UNKNOWN / recovery | CLOSED WITH OPEN PARAMETERS | UNKNOWN、receipt、verification、compensation 已定；tool-class contract 仍开放。 |
| F — Isolation ownership | CLOSED WITH OPEN PARAMETERS | policy/selection/enforcement/verification ownership 已定；具体 levels/matrix 仍开放。 |
| G — Supervisor | CLOSED | reconciliation、restart、verify、compensate、terminate ownership 已定。 |

**结论：READY FOR IMPLEMENTATION DESIGN WITH EXPLICIT OPEN PARAMETERS**

