# 08 — Persistence Responsibility

`ARCHAEOLOGY EVIDENCE`：已有架构只确认 durable entity 边界而未提供统一存储 contract；下表是 `DESIGN DECISION` 的 persistence responsibility，不是 DB schema。

本阶段只划分 durability，不定义 DB table、column、index、ORM 或 migration。

| Semantic | Durable? | Owner | Minimum responsibility |
|---|---|---|---|
| Run identity/intent/lineage/outcome | YES | Runtime | stable identity and final/recovery history |
| Attempt identity/state/lineage | YES | Runtime | every transition and terminal fact |
| Binding identity and BindingEpoch | YES | Runtime | immutable snapshot and compatibility decision |
| Artifact identity/provenance/integrity/trust | YES | Runtime | creator chain, verification and trust verdict |
| Recovery decision/receipt/verification/compensation | YES | Runtime | append-only evidence and policy decision |
| Supervisor observation | AS NEEDED | Supervisor → Runtime | durable when needed for recovery/audit/semantic transition |
| Process/execution handle | NO / reconstructable | Extension | live locator only; stale/rebuild permitted |
| Session transport state | NO / reconstructable | Extension | reconnect/transport detail, not Attempt identity |
| Transient event stream | NO, unless needed for recovery | Extension/Runtime | persist only if it closes an evidence gap |

Durable records must preserve identity, causal references, transition authority and evidence required to reconstruct after Extension loss. Ephemeral state may be discarded only when Runtime can still classify the semantic result safely; otherwise it becomes a durable observation gap/UNKNOWN. Retention, event checkpoint granularity、snapshotting and replay format are `OPEN PARAMETER`。
