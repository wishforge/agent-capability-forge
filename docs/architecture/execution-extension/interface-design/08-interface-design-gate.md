# 08 — Interface Design Gate

## API

已能表达 create/start/retry/resume/cancel/verify/reconcile，以及 Run、Attempt、Binding、Artifact、Recovery 的 read/update/action 边界；retry/resume 均创建新 Attempt，transport retry 可留在同一 Attempt。

## CRD

`AgentRun`、`AgentBinding`、`ArtifactReference` 覆盖 Kubernetes reconciliation；Attempt、BindingEpoch、Recovery、Supervisor observation 不被不必要地拆成 CRD。spec 只表达 desired state，status 保存 observed/durable state；`UNKNOWN` 只在 status/history。

## Persistence

Run、Attempt、BindingEpoch、Artifact provenance、Recovery decision 与必要 Supervisor facts 可持久化并重建 Runtime semantic state；handle/process/session 仅为可过期 observation。

## Concurrency / idempotency

所有核心 commands 有 request identity、idempotency key 与 operation journal；generation/resource version、transition version 与 fencing token 防止 duplicate action、stale Supervisor、stale Attempt writer 和旧 epoch admission。

## Recovery

UNKNOWN、receipt、verification、compensation、reconciliation decision 均为 durable append-only knowledge；重启后先重建语义，再 verify，禁止 unresolved UNKNOWN 上 blind retry。

## Adapter

Adapter 仅提供 start/observe/tool/event/terminate/inspect 等 live primitives 与事实；不拥有 Run、Attempt、Binding、trust 或 recovery authority。

## Audit

Runtime state、execution event、audit event 分离；最小 provenance 可沿 Run → Attempt → BindingEpoch → Extension → Artifact/Side Effect → Recovery 完整追踪。

## Open parameters carried forward

epoch 编号与迁移原子性、digest/manifest/trust anchor、tool-class receipt/operation-id/probe/compensation contract、isolation classes/attestation、lease/heartbeat/timeout、retention/freshness/budget、部分成功 outcome 与 human-gate policy 仍未定。这些参数不得破坏已列 invariants，进入 implementation 时必须逐项落定。

## Final gate

```text
READY FOR IMPLEMENTATION WITH OPEN PARAMETERS
```

原因：API、CRD、logical persistence、并发/幂等、恢复、adapter 与审计边界已闭合；剩余开放项是实现参数，不再阻塞接口实现，但必须在实现前显式决策并记录。
