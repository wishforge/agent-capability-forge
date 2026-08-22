# 08 — Runtime Semantic Model

## Entities and relationships

```text
Run
 |
 +-- Attempt -------------------- immutable identity
 |     |
 |     +-- Binding Epoch -------- exactly one per Attempt
 |     |
 |     +-- Artifact provenance -- producing Attempt
 |     |
 |     +-- Execution Extension -- reports facts only
 |
 +-- Recovery history ----------- UNKNOWN/verification/compensation facts
 |
 +-- Supervisor reconciliation -- decisions and orchestration
```

- `Run` 是 logical durable execution；拥有整体目标、lineage 与最终 outcome。
- `Attempt` 是一次归因的 execution boundary；同一 Run 可有多个 Attempt。
- `Binding` 是逻辑绑定；`BindingEpoch` 是不可变执行语义版本。
- `Artifact` 有 identity/provenance/integrity/trust 四个分离判断。
- `Recovery` 记录 execution state 与 side-effect state 的分离、UNKNOWN、verification、compensation 与 terminal decision。
- `Supervisor` 观察 durable state 与 Extension facts，做 reconciliation，不执行 provider primitive。

## State machines

Run：`OPEN -> EXECUTING -> WAITING_RECOVERY -> SUCCEEDED | FAILED | CANCELLED | UNKNOWN`。

Attempt：`PENDING -> STARTING -> RUNNING <-> WAITING -> SUCCEEDED | FAILED | CANCELLED`，证据不足进入 `UNKNOWN -> RESOLVING -> terminal/new Attempt`。

Binding：`admit -> active -> stale -> retired`；每个 active Attempt 固定一个 epoch。

Recovery：`UNKNOWN -> observe/verify -> VERIFIED -> derive outcome | compensate | new Attempt | human gate`。

## Core invariants

1. **I1（DESIGN）**：Every Attempt belongs to exactly one Run。
2. **I2（DESIGN）**：Every Attempt executes under exactly one immutable Binding Epoch。
3. **I3（DESIGN）**：Attempt identity never changes。
4. **I4（DESIGN）**：Artifact provenance points to exactly one producing Attempt；外部复制/派生 artifact 必须另记 source lineage。
5. **I5（DESIGN）**：UNKNOWN does not imply FAILURE or SUCCESS。
6. **I6（DESIGN）**：Retry after unresolved side effect cannot assume the effect did not happen。
7. **I7（DESIGN）**：Supervisor may create or schedule a new Attempt, but cannot mutate old Attempt identity。
8. **I8（ARCHITECTURE EVIDENCE + DESIGN）**：Execution Extension reports execution facts; it does not own durable Run/Attempt semantics。
9. **I9（DESIGN）**：terminal Attempt cannot return to active execution。
10. **I10（DESIGN）**：active Attempt cannot observe multiple Binding Epochs。

## Evidence boundary and open parameters

Architecture/archaeology 已证明的是 execution primitives、局部 resume/retry/repair 以及 UNKNOWN 的负面边界；上述 lifecycle、immutable epoch、trust gate、recovery vocabulary 与 ownership 是本 Managed Runtime 的 DESIGN DECISION。具体 digest/attestation、epoch numbering/migration atomicity、tool-class receipt/idempotency/compensation、isolation levels/matrix、lease/timeout 仍是 OPEN PARAMETER。

本阶段不将任何上述参数落成 REST API、CRD、SDK、数据库 schema 或实现接口。

