# Cross-Project Matrix

状态只用：`PROVEN / PARTIAL / NOT FOUND / UNCLEAR / NOT APPLICABLE`。单元格描述语义，不把同名对象当作同一层。

`Common?` 表示跨项目是否有相同语义；`Managed Runtime Required?` 中 `PROVEN` 表示由本轮综合推导为 v1 必须边界，`PARTIAL` 表示只有其中一部分需要托管，`NOT FOUND` 表示不应额外提升为 Managed Runtime boundary。

| Capability / Boundary | Pi | DeepSeek Harness | OpenHands | Codex | Claude | Common? | Managed Runtime Required? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Plugin lifecycle | PARTIAL (module factory/load/invalidate) | PROVEN (Cordis Fiber effects) | NOT FOUND (hard-wired ACP host) | NOT FOUND | NOT APPLICABLE | PARTIAL | NOT FOUND |
| Extension lifecycle | PROVEN (load/bind/events/recreate) | PARTIAL (composed seams, dynamic state process-local) | PARTIAL (ACP process host lifecycle) | NOT FOUND | PARTIAL (hooks/query lifecycle) | PARTIAL | PROVEN |
| Agent loop seam | PROVEN | PROVEN | PARTIAL (host triggers, external agent owns loop) | PARTIAL (turn/exec seams) | PARTIAL (query/hooks) | PROVEN | NOT FOUND |
| Tool registration | PROVEN | PROVEN | NOT FOUND on ACP path; MCP forwarded | PARTIAL | PARTIAL | PROVEN | NOT FOUND |
| Tool interception | PARTIAL (policy/provider/tool events) | PROVEN (waterfalls) | PARTIAL (permission/cancel) | PARTIAL | PROVEN (`CanUseTool`) | PROVEN | PROVEN |
| Tool runtime | PROVEN | PROVEN | NOT FOUND in host; external agent owns | PARTIAL (exec-server commands) | PARTIAL (external/SDK tool path) | PARTIAL | NOT FOUND |
| Session | PROVEN durable history + live coordinator split | PROVEN event-sourced Session | PROVEN external ACP id mirrored by server | PROVEN durable thread | PROVEN durable UUID transcript | PROVEN | PARTIAL |
| Persistence | PROVEN JSONL | PARTIAL (plugin-configured event persistence) | PROVEN state/events | PROVEN rollout/state DB | PROVEN transcript/store | PROVEN | PROVEN |
| Resume | PROVEN explicit rebuild | PROVEN history resume; dynamic extension not restored | PROVEN ACP load_session after process restart | PROVEN manual new process/thread turn | PROVEN session reattach | PROVEN | PROVEN |
| Fork | PROVEN new session/id | PROVEN child event prefix | UNCLEAR in ACP mapping | PARTIAL | PROVEN new session UUID | PARTIAL | NOT FOUND |
| Event model | PROVEN typed runtime/session events | PROVEN append-only causal events | PROVEN normalized ACP events | PROVEN rollout/exec events | PROVEN hooks/stream sequence | PROVEN | PROVEN |
| Run identity | NOT FOUND | PARTIAL (`pluginRunId`, process-local) | PARTIAL (conversation/process) | PARTIAL (thread/turn approximation) | NOT FOUND | PARTIAL | PROVEN |
| Attempt identity | NOT FOUND | PARTIAL (activation diagnostic, non-durable) | NOT FOUND | PARTIAL (`attempt_count` batch only) | NOT FOUND | NOT FOUND | PROVEN |
| Artifact identity | NOT FOUND (path metadata) | PARTIAL (package id, no digest) | PARTIAL (pinned command/version, no enforcement) | PARTIAL (cli_version/commit, no digest) | NOT FOUND | PARTIAL | PROVEN |
| Binding identity | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND | PROVEN |
| Capability negotiation | NOT FOUND | NOT FOUND (DI/service availability) | PARTIAL static capability gates | NOT FOUND (flags/limits) | PARTIAL protocol feature discovery | NOT FOUND | PROVEN |
| Supervisor | NOT FOUND | NOT FOUND | NOT FOUND (no monitor) | NOT FOUND for agent; PARTIAL exec transport | NOT FOUND | NOT FOUND | PROVEN |
| Automatic recovery | NOT FOUND | NOT FOUND (repair/steer only) | NOT FOUND | PARTIAL transport retry/manual resume | NOT FOUND | NOT FOUND | PROVEN |
| Isolation | PARTIAL trust/in-process | PARTIAL VM, not OS | PARTIAL containerized host, no per-process | PARTIAL sandbox execution | PARTIAL permission boundary | PARTIAL | PROVEN |

语义读法：`Session` 的共性是 durable conversation/event history；没有项目证明它自动保存 live runtime state、extension memory 或 external side effects。[MULTI-PROJECT]
