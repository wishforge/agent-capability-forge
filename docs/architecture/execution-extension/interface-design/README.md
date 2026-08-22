# API / CRD / Persistence Interface Design

本目录把 `core-runtime/` 与 `implementation-design/` 的冻结语义映射到外部 API、Kubernetes CRD、logical persistence、并发/幂等、恢复、adapter 与审计边界。

本阶段只做 design；不包含 REST、SQL、migration、Go struct、CRD YAML、controller 或 SDK。

## Reading order

1. [01-api-resource-model.md](01-api-resource-model.md)
2. [02-crd-resource-model.md](02-crd-resource-model.md)
3. [03-persistence-model.md](03-persistence-model.md)
4. [04-idempotency-and-concurrency.md](04-idempotency-and-concurrency.md)
5. [05-recovery-persistence.md](05-recovery-persistence.md)
6. [06-execution-extension-adapter.md](06-execution-extension-adapter.md)
7. [07-observability-and-audit.md](07-observability-and-audit.md)
8. [08-interface-design-gate.md](08-interface-design-gate.md)

## Source of truth

`core-runtime/` 与 `implementation-design/` 是 semantic / ownership source of truth。这里的 resource、record、operation 与 adapter 名称是 logical contract，不得把 execution handle 当成 Attempt identity，也不得把 `UNKNOWN` 改写为 `FAILURE`。
