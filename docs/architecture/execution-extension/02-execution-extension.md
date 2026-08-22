# 02 — Execution Extension

本文件只定义职责和信息流，不设计代码接口。

## Input from Managed Runtime

Extension 接收一次受控执行所需的上下文：

- execution intent（要执行的目标）
- Binding information（当前允许使用的 agent/provider/session 绑定）
- capability requirements（需要的能力与约束）
- isolation requirements（文件、网络、凭证、租户等约束）
- 可选的 workspace、恢复点或父级 lineage reference

这些输入是执行约束，不是 Extension 对 Run、Attempt 或 trust 的最终裁决权。

## Primitives

Extension 暴露以下原语：

```text
process   session   transport   tool   event   workspace
```

原语可包含本地 lifecycle、cancellation、cleanup、reconnect、checkpoint/resume/fork hook；这些机制的范围限于 Extension 能直接观察的 live execution。

## Output to Managed Runtime

Extension 返回可关联到当前执行的事实或引用：

- execution events
- tool results and tool-specific receipts/probes（若有）
- session state
- process state
- execution artifacts / references
- failure, disconnect, timeout 或 cancellation signals

返回的是观察结果，不是 durable outcome、artifact trust 或 recovery verdict。

## Non-ownership

Extension 不决定：

- 一个 Run 是否完成
- 一个 Attempt 是否可继续或必须新建
- Binding 是否跨 epoch 延续
- artifact 是否可信
- UNKNOWN 后是否重试、补偿或人工介入
- 选用哪一档 isolation policy

