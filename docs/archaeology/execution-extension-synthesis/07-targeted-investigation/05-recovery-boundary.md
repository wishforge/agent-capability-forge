# 05 — Recovery Boundary

## Observed cases

| Case | Extension primitive evidence | Managed semantic required | Status |
|---|---|---|---|
| Process crashed before result | Pi/Claude/OpenHands transport/process close; Codex exit/reconnect; DeepSeek error events | mark Attempt `UNKNOWN/LOST`, reconcile desired vs actual, choose new Attempt or stop | PARTIALLY_PROVEN |
| Tool ran, result delivery failed | DeepSeek `core/session/src/repair.ts:89-131` records `TOOL_OUTCOME_UNKNOWN`; tool event/result persistence in `tool-calls.ts` | do not blind retry; probe receipt/idempotency/compensation | PROVEN for unknown marking; policy not proven |
| Side effect happened, completion unknown | no project proves generic exactly-once; DeepSeek explicitly avoids fabricated success | Runtime owns side-effect policy and human/compensation gate | PROVEN negative |
| Session disconnected | ACP reconnect/load_session; Codex transport replay/manual resume; Pi/Claude resume | distinguish transport reconnect from Attempt recovery | PARTIALLY_PROVEN |
| Workspace changed, checkpoint absent | workspace/process ownership reports only; no uniform checkpoint contract | artifact/workspace digest and snapshot reconciliation | NOT_PROVEN |
| Partial/inconsistent provider result | provider-specific errors/retries exist | persist partial fact, classify outcome, prevent duplicate side effect | PARTIALLY_PROVEN |

## Boundary

```text
Execution Extension: process/session/transport/tool/event primitives;
  close/cancel hooks; receipts/probes when the tool can provide them.
Managed Runtime: durable Run/Attempt facts, binding/artifact checks,
  unknown-state policy and recovery decision.
Supervisor: desired-vs-actual reconciliation; restart/new Attempt,
  compensation or human gate; cleanup and escalation.
```

Retry is a local operation retry. Resume rebuilds from durable history. Neither is supervisor recovery. The supervisor must not infer success from a missing result. Side-effect-aware recovery is therefore a shared contract, with final policy outside the Extension.

Status: primitive detection `PROVEN`; complete recovery algorithm `NOT_PROVEN` and intentionally outside archaeology.
