# Targeted Investigation

## Scope

本阶段只验证 Binding、Attempt、Artifact/Provenance、Capability Compatibility、Recovery Boundary、Isolation/Ownership。结论来自既有源码考古报告；没有写生产代码、API、CRD 或数据库 schema。

## Evidence convention

- `PROVEN`: 源码/实验直接支持。
- `PARTIALLY_PROVEN`: 只覆盖局部路径或局部生命周期。
- `NOT_PROVEN`: 在给定 commit 和搜索范围内没有证据。
- `CONTRADICTED`: 证据与候选假设冲突。

项目基线：Pi 0.84.2（`docs/archaeology/pi/execution-extension/README.md`）；DeepSeek Harness `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`；OpenHands SDK `b3569aaf104ac8f804ccee49fbed4b1b1e4d52b4`；Codex `536f86e5cc9ec1ff38457d099bf320b9d08eeeba`；Claude SDK 为本地 `@anthropic-ai/claude-agent-sdk` 声明文件（实现不可读，结论限于声明）。

## Primitive / managed semantic rule

`process / session / transport / tool / event / workspace / checkpoint / resume / fork` 是 Extension 可提供的 execution primitives；`durable identity / binding / attempt lifecycle / artifact trust / compatibility decision / reconciliation / side-effect policy / isolation policy` 是 Managed Runtime 语义。名称相同不表示层级相同。

## Decision gate

只有 01–06 的 ownership 和生命周期都达到 `PROVEN` 或明确的 `CONDITIONAL`，才可进入 Runtime architecture/design。当前结论见 [07-final-decision.md](07-final-decision.md)。

## Phase 2 closure matrix

| Concern | Evidence | Primitive | Managed Semantic | Owner | Confidence |
|---|---|---|---|---|---|
| Attempt lifecycle | DeepSeek local Run/Attempt; Codex new turn on resume; OpenHands independent process/session/conversation; Pi/Claude no Attempt | run/turn/session/process/diagnostic | independent Attempt states and terminal attribution | Managed Runtime + Supervisor | PARTIALLY_PROVEN |
| Binding epoch | Codex request-time provider materialization; Pi model/runtime mutation; resume rebuilds live runtime; no epoch object | provider/session/package/runtime handle | same binding vs new binding/epoch on mutation, resume, fork, recovery | Managed Runtime | NOT_PROVEN |
| Artifact trust | paths, versions, package ids, workspace/revision metadata; no common digest or reload verification | package/version/path/workspace/checkpoint | identity, provenance, verification, trust decision | Managed Runtime trust boundary | PARTIALLY_PROVEN |
| Side-effect receipt | Tool call/result logs and DeepSeek `TOOL_OUTCOME_UNKNOWN`; no generic receipt/idempotency/journal | tool call/result/event/probe hook | side-effect fact distinct from execution result | Extension hook + Runtime facts + Supervisor | PARTIALLY_PROVEN |
| Compensation | DeepSeek in-process rollback only; no external effect compensation or reconciler | disposer/cleanup/undo hook | compensation, human gate, or termination after UNKNOWN | Supervisor | NOT_PROVEN |
| Isolation | in-process/VM, child process, container, workspace, credential and tool policy appear separately | process/VM/container/workspace/network/credential/tool seams | explicit isolation class and enforcement | Infrastructure + Managed Runtime | PARTIALLY_PROVEN |

Detailed closure reports: [08 Attempt](08-attempt-state-machine.md), [09 Binding](09-binding-epoch-migration.md), [10 Artifact](10-artifact-trust-policy.md), [11 Side effects](11-side-effect-receipt-compensation.md), and [12 Isolation](12-isolation-levels.md).
