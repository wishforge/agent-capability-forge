# 11 — Side-Effect Receipt / Compensation

## Evidence by failure case

| Case | What sources do | What sources do not do | Status |
|---|---|---|---|
| A. Effect completed, result lost | DeepSeek session repair records an unmatched tool call as `TOOL_OUTCOME_UNKNOWN` and asks for verification before retry (`deepseek-harness/execution-extension/06-event-recovery.md`). | No generic receipt or proof of completion. | PARTIALLY_PROVEN |
| B. Effect may have completed, process crashed | OpenHands preserves the ACP session id; Pi/Codex allow explicit resume; none reconciles an external effect (`openhands/agent-server/03-process-vs-session-state.md`; `pi/execution-extension/09-resume-fork-recovery.md`). | No operation journal/idempotency lookup/receipt protocol. | NOT_PROVEN |
| C. Result says failure, effect happened | Tool failures are normalized as observations; Codex generally returns tool failure to the model rather than automatically rerunning (`deepseek-harness/execution-extension/04-tool-runtime.md`; `codex/03-tool-sandbox-observation.md`). | No independent side-effect fact that can override the execution result. | PARTIALLY_PROVEN |
| D. Retry after `UNKNOWN` | DeepSeek explicitly avoids fabricated success and advises verification; Codex transport retry is request-level, not side-effect-aware. | No duplicate-prevention or compensation contract. | PROVEN negative |

## Result versus fact

The archaeology proves the distinction:

```text
execution result = what the extension/transport reported
side-effect fact  = what the external system actually committed
```

`UNKNOWN` means the first is insufficient to establish the second. It is not equivalent to “the side effect did not happen,” and it is not a success receipt.

## Required answers

| Mechanism | OSS evidence | Boundary conclusion |
|---|---|---|
| Receipt | Tool call/result events exist; provider/tool-specific receipts are not generic. | Extension may expose one; no portable receipt exists. |
| Idempotency key / operation id | No cross-project contract found. | NOT_PROVEN. |
| Effect journal | Session logs record observations, not external commit facts. | NOT_PROVEN. |
| Verification | DeepSeek asks the model/tool to verify after unknown. | Verification is a hook/behavior, not a managed protocol. |
| Compensation | In-process resource rollback exists in DeepSeek; external side-effect compensation is absent. | Supervisor compensation is NOT_PROVEN. |
| Reconciliation | No supervisor or desired-vs-actual effect reconciler is present. | Managed Runtime/Supervisor must define it if required. |

Ownership is therefore only a boundary inference: Extension can execute and expose tool-specific receipt/probe/undo hooks; Managed Runtime records outcome facts and retry policy; Supervisor decides reconciliation, compensation, human gate, or termination. The exact contract is not source-proven.

**Gate D: NOT CLOSED.**
