# 06 — Isolation / Ownership

## Evidence and ownership

| Resource | Primitive evidence | Required owner | Confidence |
|---|---|---|---|
| sandbox/container/VM | OpenHands runs ACP agent inside server container (`agent-server/05-workspace-runtime-boundary.md`); DeepSeek VM/context guard; Codex sandbox flags; Pi/Claude permission/process boundaries | Infrastructure provides mechanism; Managed Runtime selects/enforces isolation class; Extension declares minimum | PROVEN boundary, policy partial |
| process/session/transport | OpenHands `ACPAgent` and conversation lifecycle; Codex exec-server; Pi RPC; Claude bridge/CLI | Extension owns scoped live mechanism; Runtime owns admission and lease; Supervisor owns restart/cleanup after loss | PARTIALLY_PROVEN |
| workspace/patch/checkpoint | OpenHands workspace owner and project artifact reports; other projects expose paths/events without common snapshot identity | Runtime owns durable artifact/provenance policy; infrastructure performs storage | NOT_PROVEN common contract |
| credentials/network | OpenHands credential injection (`04-credential-boundary.md`); provider-specific auth in Codex/Claude | Runtime/Infrastructure owns secret and network policy; Extension consumes scoped handles | PARTIALLY_PROVEN |
| tool execution | Pi/DeepSeek/Claude permission and tool seams | Extension executes/mediates; Runtime policy authorizes; Supervisor handles unknown side effects | PROVEN |

## Final ownership rule

Extension owns lifecycle mechanics, scoped process/session/transport/tool/event hooks, and cleanup it can observe. Managed Runtime owns capability admission, binding, Attempt identity, artifact trust, timeout policy and isolation-class enforcement. Supervisor owns desired-vs-actual reconciliation, restart, retry budget, cleanup after crash, and final recovery/compensation decision. Provider supplies model/protocol capabilities and provider-side receipts; Infrastructure owns container/VM/network/secret primitives.

No project proves that an in-process extension, VM, container and process are equivalent isolation. Treat isolation class as an explicit managed decision, not an incidental implementation detail.
