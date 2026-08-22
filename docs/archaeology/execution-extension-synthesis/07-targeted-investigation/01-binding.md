# 01 — Binding

## Evidence

| Project / source | Primitive | Finding | Status |
|---|---|---|---|
| Pi `core/session/src/types.ts:20-30,61-99`; `core/agent-loop/src/agent.ts:80-95` | Agent/Session IDs, provider selection | `SessionId == Agent.id`; provider/model runtime exists, but no durable record joining extension, provider, session epoch and artifact (`pi/.../06-model-provider-binding.md`, `12-final-verdict.md`). | NOT_PROVEN |
| DeepSeek `packages/extensions/cordis-host-runner/src/registry.ts:16-70`; `src/types.ts:9-19,104-162` | `pluginId`, `packageId`, `pluginRunId`, Fiber | Dynamic Plugin/Package/Run/Attempt are explicit but process-local `Map` state; `AgentRegistry.resume()` does not recreate them (`deepseek/.../07-identity-version-binding.md`). | PARTIALLY_PROVEN |
| OpenHands `openhands-agent-server/.../acp_agent.py` and `.../conversation.py` (mapped in `01-server-source-map.md`) | ACP session/process/transport | Server mirrors ACP session and owns conversation lifecycle, not immutable provider/extension binding (`openhands/.../10-execution-ownership.md`). | PARTIALLY_PROVEN |
| Codex `core/src/config/mod.rs:571-603,3660-3672`; `core/src/session/mod.rs:690`; `model-provider/src/provider.rs:308` | Config → SharedModelProvider → request Provider | Binding is reconstructed from config; `SessionMeta` stores provider id, not full binding; no Binding entity (`codex/.../01-binding-source-map.md`). | PARTIALLY_PROVEN |
| Claude `sdk.d.ts`: `query`, `Options`, `resume`, `sessionId` | SDK options/session | Provider/model/session options and resume exist; declarations expose no immutable binding object or binding persistence. | NOT_PROVEN |

## Judgment

**Is Binding a first-class durable entity? YES.** This is a Managed Runtime requirement, not an OSS-proven feature. A binding is the durable admission decision that joins logical agent/provider/model/session epoch, extension artifact reference, compatibility decision, Run and current Attempt, plus isolation class. It is owned by Managed Runtime/Control Plane; the Extension receives a scoped binding context and does not mint or mutate the durable identity.

Binding is immutable for an active epoch. A provider or extension upgrade creates a new binding epoch (or explicit rejected transition); retry does not silently change it. On restart, the supervisor reloads the binding and revalidates artifact/capability before activation. If the exact binding cannot be reconstructed, state is `UNKNOWN`/blocked rather than silently selecting a new provider.

Confidence: `PROVEN` for the negative OSS result; `CONDITIONAL` for epoch/revalidation policy.
