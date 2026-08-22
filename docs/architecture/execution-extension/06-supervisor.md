# 06 — Supervisor

Supervisor 与 Execution Extension 的边界是：

```text
Execution Extension: 执行 live primitives
Supervisor: 观察 durable state，修复 desired/actual 不一致
```

## Reconciliation loop

```text
observe durable state + execution facts
        ↓
detect drift / missing fact / stale handle
        ↓
classify (recoverable | UNKNOWN | terminal)
        ↓
restart / new Attempt / verify / compensate / terminate
```

Supervisor 负责重启决定、reconciliation、UNKNOWN resolution、compensation orchestration 与 termination，并遵守 retry、cleanup、人工审批预算。

## Cases

- **process crash**：确认进程事实；无法确认副作用时保留 UNKNOWN，不直接重放。
- **session disconnect**：区分 transport 断开与 session/Attempt 终止；按 Binding epoch 规则恢复或新建 Attempt。
- **event loss**：以 durable checkpoints、receipt 或 verification 补事实；缺失时标为 UNKNOWN。
- **UNKNOWN**：先 verification，再按副作用分类选择新 Attempt、人工 gate、compensation 或终止。
- **stuck Attempt**：基于 lease/heartbeat/timeout 等 Runtime policy 重新归因，不能只看 live process。
- **stale binding**：拒绝继续使用旧 epoch，迁移到新 Attempt 或终止。
- **artifact inconsistency**：阻断消费，进入 trust verification/replacement/rollback 流程。

Supervisor 不拥有 Provider 的执行实现，也不把“进程已重启”当作“Run 已恢复”。
