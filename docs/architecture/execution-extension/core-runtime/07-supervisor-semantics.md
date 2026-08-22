# 07 — Supervisor Semantics

## Definition and loop

Supervisor 是 Managed Runtime 内的 reconciliation control-plane mechanism：

```text
observe durable state
        ↓
detect inconsistency
        ↓
reconcile
        ↓
restart / recover / verify / compensate / terminate
```

**ARCHAEOLOGY EVIDENCE**：已有项目提供局部 restart/resume/repair，但没有通用 Supervisor；以下 ownership 是本架构设计。

## Cases

- process crash：先确认 live fact；副作用不明则旧 Attempt `UNKNOWN`，不直接 `FAILED` 或重放。
- session disconnect：区分 transport 断开、session 可恢复与 Attempt 边界已闭合；跨 epoch 不续接旧 Attempt。
- event loss：用 durable checkpoint、receipt、probe 或外部审计补事实；不能补足则保持 UNKNOWN。
- UNKNOWN：先 verification；再按 idempotent/deduplicatable/verifiable/compensatable 分类选择新 Attempt、人工 gate、compensation 或 terminate。
- stale Binding：拒绝继续使用旧 epoch，冻结/终止旧 Attempt 并建立新 epoch/new Attempt。
- artifact mismatch：阻断消费，进入 trust verification/replacement/rollback；不把 restore artifact 当 world-state rollback。
- stuck Attempt：根据 lease/heartbeat/timeout 与 durable evidence 归因，不能只看 live process。
- failed recovery：保留 recovery history，避免无限重试；进入人工 gate 或 terminal outcome。

## Ownership boundary

Supervisor 拥有 reconciliation decision、recovery orchestration、verification/compensation scheduling 与 termination decision。它不拥有 provider execution primitive、Run identity、Attempt identity 或 artifact content 本身；它可以安排新 Attempt，但不能 mutate 旧 Attempt identity，也不能把“进程已重启”写成“Run 已恢复”。

