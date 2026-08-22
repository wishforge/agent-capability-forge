# 08 — Attempt State Machine

## Source evidence

| Baseline | What the source actually has | Status |
|---|---|---|
| DeepSeek Harness | Dynamic `Run`/`Attempt` records and `pluginRunId`; activation failures retain phase/diagnostic and rollback owned in-process resources (`deepseek-harness/execution-extension/01-plugin-boundary.md`, `06-event-recovery.md`, `07-identity-version-binding.md`). The registry is process-local. | PARTIALLY_PROVEN |
| Codex | `thread_id` is durable, `turn_id` is created for each resumed execution, and transport has request retries; no interactive Attempt entity (`codex/execution-extension/binding-host/08-resume-retry-attempt.md`). | PARTIALLY_PROVEN |
| OpenHands | Process, ACP session, and conversation are separate. A process can die while the session id remains loadable; conversation states include `RUNNING`, `PAUSED`, `FINISHED`, `ERROR`, etc. (`openhands/agent-server/03-process-vs-session-state.md`). | PARTIALLY_PROVEN |
| Pi / Claude | Session resume/fork and turn/query operations exist, but no Attempt object or lifecycle is exposed (`pi/execution-extension/09-resume-fork-recovery.md`; `claude/execution-extension/12-final-verdict.md`). | NOT_PROVEN |

## What can and cannot be established

The sources support these distinctions:

```text
Run/session lineage != one concrete dispatch
transport retry != new managed Attempt
resume != continuation of a live Attempt
fork != resume
process failure != side-effect failure
```

They do **not** establish one portable state machine. The only cross-project state that is directly supported is an observation boundary:

```text
created/started       -- dispatch observed
completed             -- terminal result persisted
failed/cancelled      -- terminal failure or cancellation persisted
unknown/lost          -- execution boundary closed without a trustworthy result
```

The names and legal transitions above are a minimal comparison vocabulary, not an OSS-defined contract. In particular, no source proves that a crash can continue the same Attempt. Codex resume creates a new turn; Pi creates a new runtime; OpenHands reloads a session in a new process; DeepSeek's Attempt is lost with its in-memory registry.

## Answers to the requested questions

| Question | Archaeology conclusion |
|---|---|
| Run → Attempt | DeepSeek has a local Run/Attempt-shaped relation; no durable cross-project relation is proven. |
| Retry | Request/transport retries may stay inside one local operation. A managed retry identity is not provided. |
| Resume | Restores session/history with a new live runtime or turn; same Attempt is NOT proven. |
| Fork | Pi/Claude/Codex create a new lineage/session/thread; a new managed Attempt is not explicitly modeled but same Attempt is not supported. |
| Crash recovery | Conservative unknown/error markers and explicit resume exist; supervisor-created replacement Attempts do not. |
| Side effects | Tool call/result linkage exists, but side-effect facts are not a durable Attempt ledger. |

## Final classification

`Attempt` is not an OSS-proven independent entity. It is a **Managed Runtime semantic required by the negative evidence**, with Extension observations and Supervisor reconciliation around it. Exact states, transition guards, lease/continuation rules, and terminal ownership remain `NOT_PROVEN`.

**Gate A: NOT CLOSED.**
