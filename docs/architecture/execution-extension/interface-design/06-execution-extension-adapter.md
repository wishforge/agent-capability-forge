# 06 — Execution Extension Adapter

这是 Runtime 与 Codex / Claude / Pi 等 adapter 的 logical boundary，不是 SDK 或语言接口。

## Inputs

```text
ExecutionIntent
BindingEpoch (read-only snapshot/reference)
IsolationPolicy
CapabilityRequirements + compatibility decision reference
operation identity (when tool contract requires it)
workspace / checkpoint / resume or fork lineage reference (optional)
```

## Logical capabilities

| Method/capability | Purpose | Output |
|---|---|---|
| `start` | 建立 process/session/tool execution boundary | handle + attributed start observation |
| `observe` | 读取 live state、events、receipt/probe facts | ExecutionObservation |
| `send tool request` | 发送带 operation identity 的 tool intent | tool result/receipt/probe capability |
| `receive event` | 接收或重放 transport/event fact | attributed event observation |
| `terminate` | 请求取消、停止、清理 live primitive | termination observation |
| `inspect` | 查询 handle/session/process 能见事实 | freshness/state observation |

Adapter 可声明 `reconnect`、`checkpoint`、`resume`、`verify`、`compensate` 等 capabilities；声明不等于成功保证，Runtime 记录实际 observation 与 trust。

## Output contract

Adapter 只报告可归因的 `ExecutionObservation`、`ArtifactReference`、tool receipt/probe/undo hook、failure/disconnect/timeout/cancellation、process/session/transport state。每个 observation 应带 Run/Attempt/epoch/operation correlation；无法归因时 Runtime 记录 observation gap/UNKNOWN。

## Non-ownership

Adapter 不得成为 Run owner、Attempt owner、Binding authority、artifact trust authority 或 recovery authority。它不能决定 terminal outcome、跨 epoch migration、retry admission、compensation 是否安全。规则固定为：

```text
Extension reports facts.
Runtime owns durable semantics.
Supervisor reconciles and orchestrates.
```
