# 07 — Final Decision (Phase 1 baseline)

Phase 2 closure is recorded in [13-archaeology-decision.md](13-archaeology-decision.md). This file remains the Phase 1 synthesis; the later gate result supersedes its wording where they differ.

## A. What OSS already provides

- Scoped lifecycle and disposal (Pi ExtensionRunner, DeepSeek Cordis Fiber, Claude hooks/query, OpenHands ACP process host).
- Agent/tool/event seams and tool mediation.
- Durable session/history/event persistence with resume; fork in Pi/Claude/DeepSeek paths.
- Process, transport, cancellation and reconnect primitives.
- Workspace, credential and provider hooks, but with project-specific ownership.

## B. What OSS repeatedly does not provide

Across the five baselines no complete reference proves a durable Binding entity, cross-layer Run/Attempt identity, content-addressed artifact trust, persisted compatibility decision, supervisor/reconciliation loop, generic side-effect recovery, or uniform isolation policy. These are `PROVEN` negative findings within the searched source baselines, not claims of impossibility.

## C. What Managed Runtime must own

Durable Binding and epoch; Run and independent Attempt identity; artifact digest/provenance verification; capability compatibility decision and recheck; isolation selection/enforcement; durable outcome/unknown facts; recovery policy and audit correlation.

## D. What Execution Extension must own

Scoped process/session/transport/tool/event primitives; extension-local lifecycle and cancellation; declared requirements/offers; observable workspace/result/checkpoint hooks; tool-specific receipt/probe/idempotency hooks where available. It must not own the durable binding, final compatibility decision, supervisor or recovery verdict.

## E. What Supervisor must own

Observe desired vs actual state; detect missing/dead/drifted workers; reconcile Binding/Attempt/artifact state; decide restart/new Attempt, resume, compensation, `UNKNOWN`, human review or termination; enforce retry and cleanup budgets.

## Cross-project matrix

| Concern | Project evidence | Primitive | Durable semantic | Owner | Status |
|---|---|---|---|---|---|
| Binding | Pi/DeepSeek/Codex/Claude reports; OpenHands ACP mapping | provider/session/process selection | immutable binding + epoch | Managed Runtime | NOT_PROVEN in OSS / required |
| Attempt | DeepSeek `pluginRunId`; Codex turn/batch counter | activation/turn/retry | independent Attempt lifecycle | Managed Runtime | PARTIALLY_PROVEN / required |
| Artifact | Package/version, command, workspace, cli metadata | artifact/workspace/result/checkpoint references | digest + provenance + verification | Runtime trust boundary | PARTIALLY_PROVEN / required |
| Capability | Cordis injection; OpenHands/Claude feature flags; Codex caps | dependency/feature discovery | compatibility decision persisted in Binding | Shared declaration, Runtime decision | PARTIALLY_PROVEN / required |
| Recovery | session repair, transport reconnect, process close | error/retry/resume/reconnect | side-effect-aware reconciliation | Runtime policy + Supervisor | PARTIALLY_PROVEN / required |
| Isolation | VM/context, container, process, permission/network seams | process/sandbox/credential mechanism | explicit isolation class and enforcement | Runtime + Infrastructure | PARTIALLY_PROVEN / required |

## F. Intentionally out of scope

API method names, wire protocol, CRD/database schema, digest algorithm/trust anchor, universal side-effect compensation, retry backoff numbers, artifact build system, and a claim of exactly-once execution.

## Final gate

```text
Execution Extension Boundary:
[ lifecycle + process + session + transport + tool + event primitives;
  scoped cancellation/cleanup; declarations and recovery hooks ]

Managed Runtime Boundary:
[ durable Binding/epoch, Run, Attempt, artifact identity/provenance,
  compatibility decision, isolation policy, durable outcome facts ]

Supervisor Boundary:
[ desired-vs-actual reconciliation, restart/new Attempt, compensation,
  UNKNOWN/human gate, cleanup and termination ]

Durable Entities Required:
[ Binding, Run, Attempt, Artifact/Provenance, Compatibility Decision,
  Outcome/Recovery Record ]

Remaining Unknowns:
[ exact Attempt state machine; binding epoch transition rules;
  artifact trust anchor/digest policy; tool-specific receipts and
  required isolation classes ]

Decision:
NEEDS MORE ARCHAEOLOGY
```

Reason: ownership is now clear enough to start a design review, but four policy choices above remain intentionally unresolved. The prior `NEEDS TARGETED INVESTIGATION` status is therefore closed as a scoped investigation result, not promoted to `READY FOR DESIGN`.
