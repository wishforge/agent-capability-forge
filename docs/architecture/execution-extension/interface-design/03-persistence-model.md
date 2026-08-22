# 03 — Persistence Model

以下是 logical records，不是 SQL schema、column、index 或 migration。

| Record | Identity | Durable state / lifecycle | Required references |
|---|---|---|---|
| RunRecord | `run_id` | intent, lineage, phase/outcome, semantic version, timestamps, provenance | tenant/request identity；Attempt/Recovery/Artifact refs |
| AttemptRecord | `attempt_id` | Run link, immutable epoch ref, state transitions, intent, outcome, handle observations | exactly one `run_id`、exactly one `epoch_id` |
| BindingEpochRecord | `epoch_id` | frozen agent/provider/session/capability/isolation snapshot, compatibility evidence, created/retired timestamps | one `binding_id`；immutable after admission |
| ArtifactRecord | `artifact_id` | kind/identity evidence, locator, provenance, integrity observations, trust/replacement state | producing Run/Attempt/epoch；source lineage for derived copies |
| RecoveryRecord | `recovery_id` | cause/boundary, UNKNOWN, receipt, verification, decision, compensation, policy version | Run and/or Attempt/epoch；operation identity |
| SupervisorRecord | `observation_id` / `decision_id` | observed fact, freshness, lease/heartbeat evidence, reconciliation decision and execution result | target Run/Attempt/epoch/artifact/recovery |

每个 record 至少携带创建/观察/更新时间、provenance source、semantic version，以及 append-only transition/decision history 或可重建的等价证据。普通 mutable status 不能删除历史事实。

## Invariants

```text
Run identity stable
Attempt identity stable
Attempt belongs to exactly one Run
Attempt references exactly one BindingEpoch
BindingEpoch immutable
Artifact provenance names producing Attempt
Recovery decision durable
```

Execution handle/process/session/transport locator 只作为可过期 observation；Extension 丢失后可重建或标 stale。持久层必须仍能重建 Run/Attempt/epoch/recovery semantic state。

`generation`/`version` 是 record concurrency metadata，不改变 domain state；terminal Attempt、epoch 与历史 RecoveryRecord 采用 append-only 语义。
