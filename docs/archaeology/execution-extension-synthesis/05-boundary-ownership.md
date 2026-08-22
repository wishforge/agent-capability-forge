# Boundary Ownership

| Capability | Extension owns? | Managed Runtime owns? | Shared? | Reason |
| --- | --- | --- | --- | --- |
| Plugin lifecycle | Yes, local mechanism | lifecycle admission/teardown authority | Shared | Extension creates reversible effects; runtime scopes/records them |
| Tool hooks | Yes | policy, cancellation, observation | Shared | Hook is seam; runtime decides whether it may execute |
| Session association | No durable ownership | Yes | Shared contract | Extension receives scoped session; runtime persists association |
| Artifact identity | Descriptor only | Yes | Shared | Extension declares source/build/provenance; runtime verifies digest/trust |
| Binding | No | Yes | No | Binding joins agent/session/execution/artifact/capability decision |
| Attempt | No | Yes | No | Attempt is managed execution lifecycle, not plugin activation |
| Capability check | Declares requirements/offers | Decides compatibility and records result | Yes | Declaration ≠ negotiation |
| Supervisor | No | Yes | No | Supervisor observes desired vs actual state, outside hook mechanism |
| Recovery | Provides idempotency/verification hooks | Yes | Shared | Runtime chooses retry/resume/compensate/UNKNOWN/stop |
| Isolation | Declares constraints | Selects/enforces class | Shared | VM/process/container policy is host authority |

## Ownership rule

`Execution Extension` 是一个 **runtime boundary/composition**, 不是 Control Plane 的总接口。它暴露最少的 lifecycle + agent/tool/event seams，并携带 session/execution context；Managed Runtime 在外侧持有 durable identity, binding, compatibility, supervision and recovery policy。[INFERENCE]
