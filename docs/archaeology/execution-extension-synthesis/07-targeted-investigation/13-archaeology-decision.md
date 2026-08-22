# 13 — Archaeology Decision

## Execution Extension

Across the baselines, the reusable primitives are:

```text
process / session / transport / tool / event
scoped cancellation and cleanup
workspace/credential/provider hooks
resume/fork/history or event persistence where the project supports it
tool-specific receipt/probe/undo hooks where available
```

These are mechanisms, not a durable control-plane identity or trust decision.

## Managed Runtime

The negative evidence requires durable semantics that no baseline supplies as a complete contract:

```text
Binding and any epoch boundary
Run and independent Attempt identity/lifecycle
artifact identity, provenance, verification and trust decision
compatibility decision and re-check
isolation selection/enforcement
execution outcome versus side-effect fact
```

This is a boundary conclusion, not a proposed API, CRD, schema, or implementation.

## Supervisor

The sources do not contain a generic supervisor. The missing reconciliation boundary is the responsibility to:

```text
observe desired vs actual process/session/Attempt state
classify crash/disconnect as UNKNOWN when facts are insufficient
reconcile receipts/probes before retry
choose replacement Attempt, resume, compensation, human gate, cleanup, or termination
```

The exact algorithm and persistence shape are not established by OSS.

## Gate result

| Gate | Result | Reason |
|---|---|---|
| A — Attempt lifecycle | NOT CLOSED | No portable Attempt state machine or continuation rule. |
| B — Binding epoch | NOT CLOSED | Local mutation/reconstruction exists; epoch boundary is absent. |
| C — Artifact trust | NOT CLOSED | Metadata exists; immutable identity and trust verification do not. |
| D — UNKNOWN and side effects | NOT CLOSED | Unknown marking is proven; receipt/idempotency/compensation contract is not. |
| E — Isolation ownership | NOT CLOSED | Mechanisms and partial owners exist; no common levels or selection policy. |

## Final decision

```text
NEEDS MORE ARCHAEOLOGY
```

This phase closes the investigation questions as **explicit evidence gaps**. It does not justify `READY FOR DESIGN`: all five gates require Managed Runtime policy that cannot be claimed as source-proven. The next bounded step may therefore discuss our design boundary, but must label these semantics as ours rather than OSS behavior.

## Remaining unknowns

1. Exact Attempt states, leases, terminal transitions, and whether any operation can continue an Attempt after crash.
2. Binding epoch numbering and inheritance rules for mutation, retry, resume, fork, and recovery.
3. Trust anchor, digest/identity format, provenance minimum, replacement and rollback policy.
4. Receipt/idempotency/operation-journal contract and verification/compensation authority per tool class.
5. Required isolation classes and policy mapping for trusted, untrusted, multi-tenant, networked, and credentialed extensions.
