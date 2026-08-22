# Execution Extension / Managed Runtime Architecture

本目录定义 Phase 3 的架构边界。它基于
`docs/archaeology/execution-extension-synthesis/` 及其
`07-targeted-investigation/` 的证据；不定义 API、CRD、数据库 schema 或实现。

核心结论：Execution Extension 提供受控执行原语，Managed Runtime 拥有 durable
execution semantics，Supervisor 在 Managed Runtime 内负责 reconciliation。

阅读顺序：

1. [01-boundary.md](01-boundary.md)
2. [02-execution-extension.md](02-execution-extension.md)
3. [03-managed-runtime.md](03-managed-runtime.md)
4. [04-run-attempt-binding.md](04-run-attempt-binding.md)
5. [05-artifact-and-recovery.md](05-artifact-and-recovery.md)
6. [06-supervisor.md](06-supervisor.md)
7. [07-design-gate.md](07-design-gate.md)
8. [core-runtime/README.md](core-runtime/README.md) — Phase 4 Core Runtime Semantic Model

这是一份语义边界文档，不是 API / CRD / DB 设计。
