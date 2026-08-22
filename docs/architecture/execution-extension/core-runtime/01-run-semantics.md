# 01 — Run Semantics

## Definition

**ARCHAEOLOGY EVIDENCE**：已有边界文档把 Run 描述为用户想完成的 durable execution，Attempt 是一次实际 dispatch；跨项目并未证明完整的 durable Run contract。

**DESIGN DECISION**：Run 是一个 logical durable execution。它保存用户目标、约束、lineage、Attempt 集合、最终 outcome 与 recovery history。Run 不是 process、session 或 transport。

```text
Run R
 ├── Attempt 1
 ├── Attempt 2
 └── Attempt N
```

Run identity 在创建时产生，贯穿所有 retry/recovery/fork lineage；Attempt identity 不可替代 Run identity。

## Lifecycle

Run 依次经历 `OPEN`、`EXECUTING`、`WAITING_RECOVERY`，最后为 `SUCCEEDED`、`FAILED`、`CANCELLED` 或 `UNKNOWN`。`UNKNOWN` 表示 Run 的 durable outcome 尚不能判定，不表示失败。

- 创建 Run 只创建 logical execution，不自动宣称已有 execution。
- 一个 Attempt terminal 后，Runtime 可创建下一个 Attempt；旧 Attempt 保留为历史事实。
- Run `SUCCEEDED` 需要足够的 Attempt result 与必要的 artifact/side-effect verification。
- Run `FAILED` 需要 Runtime 判定目标未完成且不再继续恢复；一次 process/tool failure 不足以单独完成 Run failure。
- Run `CANCELLED` 是接受取消并完成终止语义后的 outcome。
- Run `UNKNOWN` 是证据不足且尚未安全归因；Supervisor 必须先 reconciliation 或进入人工 gate。

## Retry, resume, fork

- **transport/request retry**：同一 Attempt 内部的 live operation retry，不改变 Run 或 Attempt identity。
- **managed retry**：新的 Attempt，仍属于同一 Run；只能在旧 Attempt 已 terminal，或 UNKNOWN 已按 policy 解析/隔离后发生。
- **resume**：恢复 session/history 或 checkpoint 的执行输入；默认创建新 Attempt。它可继承 provenance，但不继承旧 Attempt identity。
- **fork**：新的 logical lineage，创建新的 Run；其首个 Attempt 可复制输入/父 Run provenance，但不得复制 identity。若产品将 fork 视为同一业务目标，必须另行声明，这里不默认。

## Completion

Run completion 是 Managed Runtime 对目标、Attempt 结果、artifact trust 与 side-effect facts 的 durable verdict，不是 Extension 返回一个成功字符串，也不是进程退出码。

**OPEN PARAMETER**：是否允许业务定义“部分成功”或多输出 Run outcome；本阶段只要求最终 outcome 不能绕过验证与 UNKNOWN contract。

