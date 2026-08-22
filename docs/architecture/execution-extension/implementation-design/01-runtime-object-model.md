# 01 — Runtime Object Model

## Evidence and ownership rule

`ARCHAEOLOGY EVIDENCE`：既有文档支持 Runtime/Extension/Supervisor 的边界；以下对象划分、字段可变性与 authority 是 `DESIGN DECISION`，不是 OSS schema。

Managed Runtime 是所有 durable semantic objects 的 owner。Supervisor 只拥有 reconciliation decision；Execution Extension 只报告 live execution facts。对象 identity 由 Runtime 创建，不能用 process、session、transport handle 替代。

## Logical objects

| Object | Identity / immutable fields | Mutable fields / lifecycle | References / authority |
|---|---|---|---|
| **Run** | `run_id`、目标、创建 lineage、初始约束 | outcome、current phase、Attempt links、recovery history；`OPEN → EXECUTING → WAITING_RECOVERY → terminal` | owns Attempt set；Runtime-only transition authority |
| **Attempt** | `attempt_id`、`run_id`、creation lineage、exactly one `binding_epoch_id` | state、execution facts、terminal outcome、handle reference、recovery links；`PENDING → STARTING → RUNNING/WAITING/UNKNOWN/terminal` | Runtime creates/mutates; Supervisor may request new Attempt but not mutate old identity |
| **Binding** | `binding_id`、logical agent/provider intent | lifecycle `admit → active → stale → retired`、epoch links、compatibility facts | Runtime owns; each epoch is immutable |
| **BindingEpoch** | `epoch_id`、`binding_id`、provider/agent/session identity、capability/isolation snapshot | none after admission | Runtime creates/freezes; Attempt holds exactly one read-only reference |
| **Artifact** | `artifact_id`、declared kind/name, content identity evidence | provenance links, integrity observations, trust verdict, replacement status | Runtime owns identity/trust; Extension only reports reference/metadata |
| **RecoveryRecord** | `recovery_id`、Run/Attempt scope、cause/boundary | observation, receipt, verification, decision, compensation status | Runtime durably records; Supervisor appends observations and executes orchestration |
| **SupervisorObservation** | observation id, source, observed-at, related object | fact classification, freshness, reconciliation result | Supervisor owns observation; Runtime decides semantic transition |

## Non-negotiable references

```text
Run 1 ── * Attempt
Attempt 1 ── 1 BindingEpoch
Binding 1 ── * BindingEpoch
Artifact provenance ── producing Attempt (+ source lineage for derived copies)
RecoveryRecord ── Run and/or Attempt
```

An execution handle is an ephemeral reference from Attempt to Extension; it is never an Attempt identity. A terminal object is append-only as historical fact; later recovery creates a new record or Attempt rather than rewriting history.
