# 07 — Observability and Audit

## Three distinct streams

| Kind | Meaning | Mutation/retention |
|---|---|---|
| Runtime state | 当前 durable semantic state 与 transition | Runtime authoritative；版本化并保留历史 |
| Execution event | Extension/provider 观察到的 live fact | 可重放/抽样；影响语义的事实必须进入 durable record |
| Audit event | 谁在何时基于何证据执行了哪个 command/decision | append-only；不可用状态覆盖 |

## Minimum auditable events

```text
Run created
Attempt created
BindingEpoch selected/frozen/stale
Execution started
Execution observation / event gap
UNKNOWN entered
Verification started/completed
Recovery decision
Compensation requested/completed
New Attempt scheduled/created
Artifact registered/verified/trust changed
Run completed/cancelled/failed/unknown
```

每个事件至少关联 `event_id`、occurred/recorded time、actor/source、tenant、Run/Attempt/epoch、operation id、semantic version/fence 与 evidence reference。敏感 payload 只保存最小安全引用/摘要，不能把凭证或完整 secret 写入 audit。

## Provenance chain

```text
Run
 ↓
Attempt
 ↓
BindingEpoch
 ↓
Execution Extension observation
 ↓
Artifact / Side Effect fact
 ↓
Recovery decision
```

Artifact 还必须记录 producing Attempt；派生/复制 artifact 记录 source lineage。receipt、verification 与 compensation 各自标明 source、freshness、trust，不能把 audit event 当作 execution success。
