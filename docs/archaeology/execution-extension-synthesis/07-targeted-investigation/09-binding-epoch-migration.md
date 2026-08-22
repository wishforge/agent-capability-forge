# 09 — Binding Epoch Migration

## Evidence

| Baseline | Observed mutation/reconstruction | Status |
|---|---|---|
| Codex | Provider is reconstructed from config; endpoint/auth are materialized at request time. Resume keeps the thread but creates a new turn and reads provider configuration again (`codex/execution-extension/binding-host/01-binding-source-map.md`, `08-resume-retry-attempt.md`). | PROVEN mutation/reconstruction; NOT_PROVEN epoch |
| Pi | `setModel`, provider registration and runtime replacement mutate live selection; resume/fork dispose the old runtime and create new extension instances (`pi/execution-extension/04-extension-api.md`, `09-resume-fork-recovery.md`). | PROVEN local mutation; NOT_PROVEN epoch |
| OpenHands | ACP session id survives process replacement; model/config fields are restored by the host. No immutable binding record is persisted (`openhands/agent-server/03-process-vs-session-state.md`, `11-extension-host-mapping.md`). | PARTIALLY_PROVEN |
| DeepSeek | `currentPackageId` / `nextPackageId` distinguish successful and in-progress package activation, but the registry is process-local and has no durable binding (`deepseek-harness/execution-extension/01-plugin-boundary.md`, `07-identity-version-binding.md`). | PARTIALLY_PROVEN |
| Claude | `resume`, model and session options are public SDK inputs; no immutable binding or epoch is declared (`claude/execution-extension/12-final-verdict.md`). | NOT_PROVEN |

## Direct answer

**Can Binding mutate?** The OSS systems mutate or reconstruct provider/model/package selection. None exposes a durable `Binding` whose mutation semantics can be transferred across projects.

**Does Binding require an epoch/version boundary?** No source proves such a boundary. A version string, package id, session id, or new process is not an epoch by itself.

## Relationship table

| Event | OSS evidence | Managed meaning that is *not* source-proven |
|---|---|---|
| Same provider/session/runtime continues | Local handle may be reused | `same binding` |
| Provider/model/capability changes | Pi/Codex/DeepSeek can change local selection | whether this is `new binding` or `new epoch` |
| Resume | New live runtime/turn is created while session/thread may persist | whether it inherits binding or creates `new epoch` |
| Retry | Transport/request retry can be internal | whether it inherits binding and Attempt identity |
| Fork | New session/thread lineage in several systems | whether it clones binding or requires `new binding` |
| Crash/recovery | Session can be reloaded; dynamic state can disappear | stale-binding detection and re-admission |

No source provides stale-binding detection, atomic migration, epoch numbers, or a rule that retry/resume/fork must inherit or replace a binding.

## Final classification

OSS proves **local selection mutation and runtime reconstruction**, while disproving the assumption that an immutable durable Binding already exists. `same binding` / `new binding` / `new epoch` / `new Attempt` remain Managed Runtime policy choices.

**Gate B: NOT CLOSED.**
