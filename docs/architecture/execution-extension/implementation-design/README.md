# Core Runtime Implementation Design

本目录把 `core-runtime/` 的语义转换为内部实现契约。它只定义 logical objects、ownership、生命周期、状态转移、extension boundary 与 durability responsibility；不定义 production code、REST/API、CRD、数据库 schema、migration、ORM 或 SDK。

## Reading order

1. [01-runtime-object-model.md](01-runtime-object-model.md)
2. [02-attempt-runtime-contract.md](02-attempt-runtime-contract.md)
3. [03-binding-runtime-contract.md](03-binding-runtime-contract.md)
4. [04-artifact-runtime-contract.md](04-artifact-runtime-contract.md)
5. [05-recovery-runtime-contract.md](05-recovery-runtime-contract.md)
6. [06-supervisor-runtime-contract.md](06-supervisor-runtime-contract.md)
7. [07-execution-extension-contract.md](07-execution-extension-contract.md)
8. [08-persistence-responsibility.md](08-persistence-responsibility.md)
9. [09-implementation-design-gate.md](09-implementation-design-gate.md)

## Evidence boundary

`ARCHAEOLOGY EVIDENCE` 来自既有 archaeology/architecture；`DESIGN DECISION` 是本 Runtime 的规范性实现选择；`OPEN PARAMETER` 只能在这些不变量内选择，不能悄悄改变语义。

