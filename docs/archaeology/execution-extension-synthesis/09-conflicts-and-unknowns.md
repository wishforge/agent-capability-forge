# Conflicts and Unknowns

| Conflict / unknown | Evidence A | Evidence B | Why they differ | Safer model / status |
| --- | --- | --- | --- | --- |
| Session means runtime or history | Pi/DeepSeek/Claude sessions are durable logs and resume rebuilds runtime | OpenHands mirrors external ACP session while conversation/process state is separate | product layers name both “session” | Treat Session identity/history separate from live Runtime state. RESOLVED semantic rule |
| Run vs Attempt | DeepSeek `pluginRunId` covers activation/latest diagnostic; Codex turn approximates execution | Pi/Claude have no attempt; Codex batch counter is not interactive | local implementation scopes differ | Require managed Run + Attempt, mark exact transitions unresolved. OPEN |
| Resume vs recovery | All projects support some history/session resume | DeepSeek explicitly says crash-tail repair is not automatic recovery; no supervisor | durable transcript is easier than side-effect reconciliation | Resume only rebuilds from facts; Recovery requires supervisor. RESOLVED |
| Extension vs Plugin | DeepSeek has Cordis Plugin and composed Extension boundary; Pi has module factory; OpenHands has no generic plugin host | same words refer to composition, registry metadata, or process host | layer mismatch | Do not define Plugin == Extension; use Extension as boundary, Plugin as mechanism-specific term. RESOLVED |
| Version as artifact identity | OpenHands/Codex pin/version metadata exists | no digest or restore enforcement across all references | release metadata vs bytes integrity | `version != integrity`; digest required by runtime. RESOLVED |
| Capability support | OpenHands/Claude expose feature flags; DeepSeek DI; Codex static caps | none provides universal negotiated authorization set | feature detection and dependency availability are not compatibility contract | Extension declares, runtime decides/persists. RESOLVED |
| Process death detection | OpenHands detects on next protocol call; Pi RPC rejects on child exit; Codex transport has reconnect | none owns complete desired-state reconciliation | transport owner differs from supervisor | Detection is not supervision; supervisor remains missing. RESOLVED |
| Artifact exactness policy | reports show absence of digest | target security/isolation policy not investigated in this phase | evidence is negative, policy is deployment-specific | Need targeted investigation before Freeze. OPEN |
| Crash side-effect state | DeepSeek records `TOOL_OUTCOME_UNKNOWN` | no project proves generic idempotency/receipt/compensation | external effects are tool-specific | Runtime must model UNKNOWN and require tool-specific probe/compensation. OPEN |

Final unknowns are intentionally narrow: Attempt state transitions, binding epoch semantics, and artifact trust/recovery policy for the target Managed Runtime.
