# 01 — Boundary

## Execution Extension

Execution Extension 是向 Managed Runtime 提供受控执行原语的边界。它负责可观察、可取消、可清理的 live execution，包括：

- process lifecycle
- session lifecycle
- transport
- tool invocation
- event stream
- workspace / execution environment primitives

它可以声明 capability、返回执行事实，并暴露 tool-specific receipt、probe、idempotency 或 undo hook（若底层工具支持）。

它不是：

- durable Run owner
- Attempt lifecycle owner
- Binding authority
- global recovery authority
- artifact trust authority
- Supervisor

## Managed Runtime

Managed Runtime 是 durable execution semantics 的 owner。它定义并持久化 Run、Attempt、Binding、artifact provenance、capability compatibility decision、recovery semantics 与 isolation policy，并将 Extension 的事实归并到这些语义中。

## Supervisor

Supervisor 是 Managed Runtime 内负责 reconciliation 的控制平面机制。它观察 desired state 与实际执行事实，处理 restart、UNKNOWN resolution、termination 与 compensation orchestration。它不替代 Extension 执行 process/session/tool，也不把一次 transport retry 自动提升为一次新的 durable Attempt。

## Boundary rule

```text
Execution Extension reports execution facts.
Managed Runtime decides durable semantics.
Supervisor reconciles durable desired and observed state.
```

考古没有证明任何 OSS 已提供完整的上述 durable contract；这里的实体与策略属于本架构。
