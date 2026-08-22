# Verdict

**NEEDS TARGETED INVESTIGATION**

The cross-project evidence is sufficient to freeze the *shape and ownership* of a minimal Boundary candidate, but not the exact Attempt state machine, crash/recovery contract, or artifact trust policy. Therefore do not enter API/CRD/schema freeze yet.

# What OSS Has Converged On

- Scoped lifecycle composition and disposal.
- Agent-loop/request/tool/event seams that can affect or observe execution.
- Tool mediation with cancellation, permission/exposure, normalization and observations.
- Durable session/history or event streams with resume; fork exists in several systems.
- Process/transport primitives can be hosted independently of the agent loop.

These are **OSS-proven Execution Mechanisms**, not a Managed Control Boundary. `[MULTI-PROJECT]`

# What OSS Has Not Solved

No reference proves a durable Extension Binding, content-addressed artifact integrity/provenance, one cross-layer Execution identity, durable Attempt entity, semantic capability negotiation, supervisor/reconciliation, generic side-effect recovery, or uniform isolation policy. `[MULTI-PROJECT]`

# Execution Extension Boundary Candidate

`Execution Extension` is a runtime composition boundary exposing scoped lifecycle, agent-loop, tool, event and session-association seams. It is not a giant Control Plane interface and not necessarily a single persistent object. Extension mechanism stays inside; managed binding/attempt/supervision stay outside. `[INFERENCE][DESIGN REQUIREMENT]`

# Managed Runtime Boundary

Managed Runtime/Control Plane owns durable Binding, Execution/Run and Attempt identity, artifact verification/provenance, capability compatibility decisions, isolation enforcement, desired-vs-actual supervision, and recovery/reconciliation. It persists decisions and correlates events/artifacts; it does not need to own every extension hook implementation. `[DESIGN REQUIREMENT]`

# Binding / Attempt / Artifact Model

- Binding: **YES, first-class durable entity**; object ID is not binding identity.
- Attempt: **YES, independent of Run**; retry creates a new attempt; crash marks old attempt lost/unknown before a supervisor may create another; explicit resume semantics require targeted confirmation.
- Artifact: name/version/revision/URI aid selection/provenance; digest supplies integrity. Digest is a shared contract with Runtime as trust/enforcement owner. `[DESIGN REQUIREMENT]`

# Capability Model

Extension declares required/optional capabilities and isolation constraints. Runtime computes compatibility against its own/provider/tool capabilities, persists the decision in Binding, and re-evaluates on bind/resume/upgrade/downgrade. DI, registry presence and feature flags alone are not negotiation. `[MULTI-PROJECT][DESIGN REQUIREMENT]`

# Supervisor / Recovery Boundary

Error handling and retry remain local execution concerns. Resume rebuilds from durable history. Recovery reconciles lost/unknown execution and external side effects. Supervisor owns desired-vs-actual detection and chooses restart, new Attempt, resume, compensation, UNKNOWN/human gate or termination. It is **outside** Execution Extension, though extensions may expose idempotency/probe/cleanup hooks. `[MULTI-PROJECT][DESIGN REQUIREMENT]`

# Remaining Unknowns

1. Exact Attempt states and whether any target operation may continue the same Attempt after crash.
2. Binding epoch/version semantics during extension upgrade and session resume.
3. Artifact trust anchor, digest algorithm, provenance minimum and rollback policy.
4. Tool-specific side-effect receipts/idempotency/compensation contract.
5. Required isolation classes for trusted vs untrusted extensions.

# Recommendation

Freeze the boundary *candidate* as an architectural direction, then run targeted investigations for the five unknowns above. Do not freeze production API, CRD or schema until those results are recorded.
