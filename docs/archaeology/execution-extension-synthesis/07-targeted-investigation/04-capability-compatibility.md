# 04 — Capability Compatibility

## Evidence

- Pi `core/agent-loop/src/agent.ts`, `06-model-provider-binding.md`, `07-capability-permission.md`: provider/model selection, tool filtering and permission hooks; no offer/accept compatibility transaction (`NOT_PROVEN`).
- DeepSeek `vendor/cordis/src/fiber.ts:238-263,310-319`; `cordis-host-runner/src/guard.ts:700-779`: dependency injection and guarded service access; missing services wait/fail, but this is availability, not semantic negotiation (`PARTIALLY_PROVEN`).
- OpenHands provider registry `provider-registry/*` and ACP capability mapping: static capability gates and protocol discovery, no persisted cross-layer decision (`PARTIALLY_PROVEN`).
- Codex `core/config`, provider/model metadata and sandbox enforcement: static flags/limits and startup validation, no handshake deciding whether a particular Extension contract is compatible (`PARTIALLY_PROVEN`).
- Claude `sdk.d.ts` protocol `capabilities`, tool permissions and feature flags: declaration/discovery, no durable compatibility decision (`PARTIALLY_PROVEN`).

## Decision ownership

**Where should compatibility be decided? Shared boundary, with Runtime decision ownership.**

1. Extension declares required/optional protocol, model, tool, session and isolation capabilities.
2. Provider/Infrastructure reports what it can actually provide.
3. Managed Runtime computes `compatible / incompatible / review`, persists the decision in Binding, and fail-closes if required capabilities are absent.
4. Supervisor rechecks on bind, resume, upgrade/downgrade and reports drift.

The Extension may reject an invalid local call, but it cannot unilaterally authorize a managed execution. Provider metadata or DI presence is evidence input, not the final decision.

Status: ownership conclusion `PROVEN` by repeated absence of a shared decision plus positive partial gates; exact capability vocabulary `NOT_PROVEN`.
