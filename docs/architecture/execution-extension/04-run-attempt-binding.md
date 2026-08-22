# 04 — Run / Attempt / Binding

## Run

Run 表示用户想完成的 durable execution：目标、意图、约束和整体 lineage。Run 可以包含多个实际执行尝试：

```text
Run
 ├── Attempt 1
 ├── Attempt 2
 └── Attempt 3
```

Run 的完成不等于某一次 transport 或 process 成功；它由 Managed Runtime 根据 Attempt 事实和验证策略决定。

## Attempt

Attempt 表示一次由 Runtime 负责归因的实际 dispatch。它承载开始、执行、终止、结果和 side-effect observation 的边界。

最小状态词汇为 `CREATED`、`STARTED`、`COMPLETED`、`FAILED`、`CANCELLED`、`UNKNOWN`；状态名和转移 guard 是本架构的 DESIGN DECISION，不能声称由 OSS 证明。

- **retry**：transport/request retry 可留在同一 Attempt 内；Runtime policy retry 建立新的 Attempt。
- **resume**：恢复 session/history 是 Extension primitive；默认不证明原 Attempt 仍在继续，须由 Runtime 明确归因。
- **fork**：产生新的 lineage，必须是新的 Attempt（可复制输入和 provenance，不复制 identity）。
- **crash recovery**：若不能证明原执行边界与 side effects，原 Attempt 进入 UNKNOWN，Supervisor 决定新 Attempt、验证、补偿、人工 gate 或终止。

## Binding

Binding 表示当前 Attempt 实际绑定到哪个 Agent、Provider、Session 与 Capability set。它包含：

- binding identity
- owner（Managed Runtime）
- lifecycle（admit、active、stale、retired）
- capability compatibility decision
- mutation / migration history
- epoch / version marker

## Epoch and migration

考古只证明 provider/model/package 会被重建或变更，没有证明跨项目的 epoch contract。因此本架构作出以下 DESIGN DECISION：

> 一个 active Attempt 只能观察到一个 immutable Binding epoch。

若 provider、agent、session identity 或 capability set 发生影响执行语义的变化，Runtime 不在原 Attempt 内静默切换；它结束或标记原 Attempt，并以新 epoch 建立新的 Attempt。纯 transport retry 不改变 epoch。resume/fork/migration 是否可继承输入 provenance，不能继承 active Attempt identity。

epoch 编号、迁移原子性、恢复时的 stale detection 仍是 Open Decisions（见 07）。
