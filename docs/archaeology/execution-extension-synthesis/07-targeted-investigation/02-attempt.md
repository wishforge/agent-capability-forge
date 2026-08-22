# 02 — Attempt

## Evidence

- DeepSeek `packages/extensions/cordis-host-runner/src/types.ts:104-162` has Run/Attempt-shaped activation diagnostics, but `registry.ts:36-70` stores them in process memory; it is not a durable Run/Attempt ledger (`PARTIALLY_PROVEN`).
- Codex `core/src/rollout/*` and `agent_jobs.attempt_count` distinguish turn/批处理 retries, but `binding-host/08-resume-retry-attempt.md` confirms no first-class interactive Attempt (`PARTIALLY_PROVEN`).
- Pi `core/agent-loop/src/agent.ts` and Claude `sdk.d.ts` expose turn/query/session operations but no Attempt entity (`NOT_PROVEN`).
- OpenHands `ACPAgent` separates conversation, process and ACP session, but no durable Attempt lifecycle (`openhands/.../03-process-vs-session-state.md`, `10-execution-ownership.md`; `NOT_PROVEN`).

## Minimal semantic model

```text
Run = logical execution requested by the caller
Attempt = one concrete dispatch/worker effort for that Run

Run 1 ── Attempt 1 (SUCCEEDED | FAILED | UNKNOWN | LOST)
     └─ Attempt 2 (retry/re-dispatch, new identity)
```

Retry creates a new Attempt. Resume of durable session/history is not evidence that the same Attempt continues; unless the target runtime has an explicit lease/continuation proof, resume creates a new Attempt or remains blocked. Fork creates a new Run lineage and new Attempt. Crash closes the old Attempt as `UNKNOWN` or `LOST`; the Supervisor decides whether to create another Attempt. Completion/failure and side-effect receipts are attributed to the Attempt that issued them.

**Is Attempt independent from Run? YES.** The independence is `PROVEN` as a required semantic boundary by cross-project negative evidence, but exact state names and continuation rules remain `CONDITIONAL` until target policy is selected.

Owner: Managed Runtime owns identity and lifecycle; Extension reports primitive observations; Supervisor decides reconciliation/new dispatch.
