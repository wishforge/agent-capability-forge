# 25 — Phase 5-C Assumptions（Minimal Codex Backend Adapter）

> 状态词：VERIFIED / PARTIAL / UNKNOWN / INFERENCE / PHASE-5C-DESIGN
> 基线：Codex `279b93242cfef379e65da97e87e44b83c5934fd7`（2026-08-11）；
> 实现：`deepseek-harness/runtime/backend/adapters/codex.py` +
> `runtime/tests/test_phase5c_codex.py` + `runtime/tests/fixtures/*.jsonl`。

## Assumptions

| 项 | 状态 | 结论 |
| --- | --- | --- |
| Codex integration boundary | VERIFIED | 采用 rollout JSONL（RolloutItem schema，`history/src/lib.rs:30`；`RolloutLine` 形状 `history/src/tests.rs:12`）。不修改 Codex source；不使用 library API / process / mock。 |
| Codex event source | VERIFIED | 以 `RolloutItem::ResponseItem` 为 canonical source；`EventMsg` 只消费 `task_started` / `task_complete` / `error` 生命周期事件。`EventMsg::UserMessage` / `RawResponseItem` 按 20 §3.1 Q3 视为投影副本，忽略（去重）。 |
| fixture vs real E2E | PARTIAL | 本阶段是 **FIXTURE TEST**：fixture 按 pinned schema 手工构造并核对 serde 形状；本环境未运行真实 Codex executable。 |
| Step synthesis | PHASE-5C-DESIGN | 每个 sampling request = 一个 assistant `ResponseItem` + 其后的 tool activity，构造一个 Unified Step；`step_id` 由 Unified runtime 分配；`step_mapping=ADAPTER`；无原生 step 事件（20 §2）。 |
| Tool pairing | PARTIAL | Codex call_id 保留并透传为 Unified call_id；rollout 内 call↔output 按 call_id 配对：成对 = EXACT，无配对 = LOSSY 且不猜测。实际执行结果由 Unified ToolRuntime 产生（`delegates_tools=False`），Codex 原生 output 仅作为 raw evidence。 |
| Error normalization | PARTIAL | `EventMsg::Error`（fatal）→ `ModelRequestError` → `turn/end{error}`；DSH 工具失败 → `ToolResult(is_error=True)`。Codex rollout 不持久化结构化 success（`FunctionCallOutputPayload::serialize` 只写 body），因此 Codex 原生工具失败只能 LOSSY，不伪造字段。 |
| Causality assignment | INFERENCE | Codex 无 ambient initiator（20 §6）；live 执行由 Unified `with_initiator` 赋值，明确为 **ADAPTER ASSIGNMENT**，不是 Codex native semantics。SessionMeta 的 parent/fork lineage 已存在但本阶段 golden path 未消费。 |
| Ownership boundary | VERIFIED | Codex backend 资源（session-scoped services）= BACKEND_SPECIFIC；Unified Capability-owned tool 通过 `ToolRegistration(owner=...)` 在 ToolRuntime 注册；不把 Codex 资源映射成 Capability。 |
| Persistence boundary | VERIFIED | Unified EventStore 是 Unified 侧 source of truth（close/reopen/rebuild/replay 已测）；Codex rollout 文件作为 raw source 并存，不互相替代。 |
| Lossiness | VERIFIED | `BackendMappingMetadata` 暴露 backend / mapping_quality / missing_semantics / raw_event_ref / source_event_type；session、turn、step、call、error 五层都有元数据；`missing_semantics` 固定为 23 §2 的六项清单。 |

## 未实现的 Phase 5-C 之外语义

ExecutionAttempt、Tool unknown-outcome heuristic、Full Capability overlay、
Codex fork / rollback / compaction / subagent / full sandbox mapping 均未实现
（按阶段指令 19 节）。
