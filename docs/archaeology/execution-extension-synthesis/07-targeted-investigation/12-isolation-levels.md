# 12 — Isolation Levels

## Observed mechanisms (not invented levels)

| Observed mechanism | Source evidence | What it isolates | Owner evidence |
|---|---|---|---|
| In-process extension / Fiber | DeepSeek Cordis Fiber and guarded context | lifecycle/effect scope; not OS boundary | Extension/runtime composition |
| `node:vm` guarded host | DeepSeek dynamic Host Package | language/context access; not process or kernel isolation (`deepseek-harness/execution-extension/04-tool-runtime.md`) | Extension host |
| Child process + stdio ACP | OpenHands ACP Agent | process/transport boundary, while child inherits server host/container filesystem/network (`openhands/agent-server/05-workspace-runtime-boundary.md`, `06-acp-transport.md`) | Agent server / Infrastructure |
| Server container / Docker workspace | OpenHands deployment/workspace | container and mount boundary for the server/workspace; local workspace may have no boundary | Infrastructure |
| Process/RPC child client | Pi RPC client | child process and JSONL transport; no automatic supervisor/isolation policy (`pi/execution-extension/08-process-rpc-lifecycle.md`) | Host/client |
| Sandbox/permission/network policy | Codex and Pi tool seams | tool admission, approval, network/filesystem policy | Runtime/provider-specific policy |
| Credential injection | OpenHands secret registry and Codex/Claude auth paths | scoped credential materialization; no uniform vault/zeroization guarantee | Runtime/Infrastructure/provider |

## No source-defined Level 0…N taxonomy

The projects use different words and boundaries. None defines a portable ordered isolation scale covering process, session, workspace, filesystem, network, credential, tenant, tool, and container isolation. Therefore this document intentionally does **not** assign “Level 0/1/2” labels: doing so would be design, not archaeology.

## Ownership conclusion

| Concern | Evidence-backed owner boundary | Confidence |
|---|---|---|
| Process/session/transport mechanics | Extension or host owns live handles and cleanup it can observe. | PARTIALLY_PROVEN |
| Tool permission/execution | Extension/provider mediates; host policy can gate. | PROVEN locally, not uniform |
| Workspace/filesystem/container/network/tenant boundary | Infrastructure supplies the mechanism; projects do not expose a common managed policy. | PARTIALLY_PROVEN |
| Credential isolation | Host/runtime/provider injects scoped credentials; no common trust contract. | PARTIALLY_PROVEN |
| Selection of an isolation class | No OSS owner or persisted decision is proven. | NOT_PROVEN |

The only safe cross-project conclusion is that isolation is an explicit Managed Runtime/Infrastructure concern, not an incidental consequence of having a process, VM, or `node:vm`. Required classes for trusted/untrusted extensions remain unknown.

**Gate E: NOT CLOSED.**
