# 09 — Implementation Design Gate

## Checklist

- **Object model — CLOSED**：Run、Attempt、Binding、BindingEpoch、Artifact、RecoveryRecord、SupervisorObservation 的 identity、references、owner 与 mutation authority 已明确。
- **Transition authority — CLOSED**：Runtime 是唯一 semantic state transition authority；Supervisor 提交 reconciliation decision；Extension 只报告事实。
- **Identity — CLOSED**：Run、Attempt、BindingEpoch、Artifact identity stable；execution handle/process/session id 不替代 Attempt identity。
- **Extension contract — CLOSED**：Runtime 输入 epoch/intent/capability/isolation；Extension 输出可归因 facts/references，双方没有 durable ownership 重叠。
- **Recovery — CLOSED WITH OPEN PARAMETERS**：UNKNOWN、verification、receipt、idempotency、compensation 与 append-only decision 已可实现；tool-class details 仍开放。
- **Persistence — CLOSED**：Run/Attempt/epoch/artifact provenance/recovery decisions 必须 durable；live handle/transport 可重建。
- **Supervisor — CLOSED**：拥有 reconciliation、verification/compensation orchestration、new Attempt scheduling、termination，不拥有 identity 或 provider internals。

## Core invariants

```text
I1  Run identity is stable.
I2  Attempt identity is stable.
I3  An Attempt executes under one immutable BindingEpoch.
I4  Extension execution handle is not Attempt identity.
I5  Artifact provenance identifies its producing Attempt.
I6  UNKNOWN is durable runtime knowledge state, not FAILURE.
I7  Supervisor may create a new Attempt but never mutates old Attempt identity.
I8  Recovery decisions are durable.
I9  Execution Extension may be replaced/restarted without changing Run/Attempt identity.
I10 Managed Runtime can reconstruct semantic state after Extension process loss.
```

## Evidence classification

已有 OSS/archaeology 只支持执行 primitive、局部 retry/resume/repair 与事实缺失边界；本目录中的对象、authority、immutable epoch、trust/recovery vocabulary 是 `DESIGN DECISION`。以下保持 `OPEN PARAMETER`：Attempt timeout/lease/heartbeat；epoch numbering 与迁移原子性；digest algorithm、manifest、trust anchor 与 artifact backend；receipt retention、verification timeout、operation/idempotency contract、compensation budget；isolation catalog/selection matrix/attestation；Supervisor retry、human gate 与 event retention。

## Final gate

```text
READY FOR API / CRD / DB DESIGN
```

理由：内部对象、identity、ownership、transition authority、Runtime↔Extension/Supervisor boundary、durability 与 recovery semantics 已闭合。开放参数只能在这些 invariants 内具体化；API、CRD、DB 设计阶段必须显式承接并记录这些参数，不能反向改变核心语义。

