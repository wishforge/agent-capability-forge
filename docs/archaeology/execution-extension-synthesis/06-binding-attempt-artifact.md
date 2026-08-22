# Binding / Attempt / Artifact

## Binding

**结论：YES，必须是一等 durable entity。** `[DESIGN REQUIREMENT]`

Object ID 只标识对象：DeepSeek 的 `pluginId/packageId/pluginRunId`、OpenHands 的 `acp_session_id`、Codex 的 provider id/turn id 都没有同时绑定 Agent composition、Session epoch、artifact、runtime、attempt 与 compatibility decision。[DEEPSEEK][OPENHANDS][CODEX]

最小语义（非 API）：`binding_id` 代表一次被接受的装配决定，至少关联 agent/preset、session + epoch、extension artifact reference、capability decision、execution/run、current attempt、isolation class 与 provenance。它可放在 Managed Runtime/Control Plane，不属于 extension implementation object。

## Attempt

**结论：YES，独立于 Run；但精确状态机仍需 targeted investigation。** `[DESIGN REQUIREMENT][INFERENCE]`

- `Run`：一次 logical execution/activation 的外层记录。
- `Attempt`：Run 为获得一次实际执行结果而进行的第 N 次 worker/dispatch effort。
- Retry：同一 Run 创建新的 Attempt。
- Explicit resume：通常创建新的 Run/Attempt，除非 runtime 明确声明是继续未完成 Attempt；不能从 session resume 自动推断。
- Crash：先关闭/标记原 Attempt 为 `UNKNOWN` 或 `LOST`，再由 Supervisor 决定新 Attempt；不能把新进程默认为同一 Attempt。
- Recovery：不是新 Attempt 本身，而是对 lost/unknown Attempt 的 reconciliation decision。

证据边界：Pi/Claude 无 Attempt；Codex 的 `turn` 近似 execution、batch `attempt_count` 非交互 attempt；DeepSeek `pluginRunId` 是 process-local activation diagnostic；所以以上是安全的最小平台语义，不是 OSS 现状。[PI][CLAUDE][CODEX][DEEPSEEK]

## Artifact

**结论：digest 属于 Managed Runtime trust contract；Extension 提供可验证 descriptor，双方共享字段。** `[DESIGN REQUIREMENT]`

最小 identity 需要 `name`（人类选择）、`version`（兼容/发布语义）、`revision`（源码/build provenance，可选）、`digest`（实际 bytes integrity，必须用于受信恢复）以及 `artifact URI`（取回位置）。`source code` 不是 identity 本身。

`Version != Integrity`：所有项目有版本字符串或 package/provider metadata，但没有恢复时强制 exact artifact 的统一证据。[PI][DEEPSEEK][OPENHANDS][CODEX][CLAUDE]
