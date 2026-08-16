# 08 — Durable Evidence Assumptions（Phase 5-H）

> 依据：`07-durable-evidence-audit.md`（实现前基线）+ Phase 5-E Contract v1
> §6/§7/§8/§15 + Phase 5-F 01-03 + Phase 5-G 04-06。
> 状态词：VERIFIED / PARTIAL / UNKNOWN / DESIGN PROPOSAL。实现后的状态
> 只表示“本 runtime 的 durable evidence 形态”，不表示 backend 原生事实。

| # | Assumption | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| A1 | stable initiator identity：`InitiatorRef.ref` 使用 AgentRuntime 收到的 `InitiatorContext.agent_id` 字符串；调用方负责保证其稳定 | PARTIAL | 无独立 agent identity schema；只冻结 ref 语义，不假设 ID 格式（Phase 5-H §4/§5） |
| A2 | capability reference stability：`ToolRegistration.owner` 字符串按稳定 capability id 解释 | PARTIAL | 当前 runtime 与 python-cordis capability registry 无链接校验；注册方契约未验证 |
| A3 | owner identity after restart：`owner_ref` 以 `{owner_type, owner_id}` 持久化在 tool/call + tool/result，replay 可读 | VERIFIED（持久化）/ PARTIAL（语义） | `test_owner_survives_replay`；语义稳定性依赖 A2 |
| A4 | context provenance reconstruction：`request_ref + source_event_refs + surface_refs + current_input_ref` 可持久化重建；system_prompt / runtime_context 无 durable snapshot | PARTIAL | `context_provenance` 写在 attempt/start；quality=PARTIAL；missing=RUNTIME_CONTEXT_SNAPSHOT / SYSTEM_PROMPT_SNAPSHOT |
| A5 | request header semantics：`request/header` 仍是 `agent/request` 的 durable surrogate，现额外携带 `initiator_ref`；`context_provenance.request_ref` 指向该事件 seq | VERIFIED（实现） | 无新事件类型；append-only 与既有事件序列不变 |
| A6 | adapter-derived initiator：AgentScope 与 Codex 均无原生 durable agent identity，Unified runtime 赋值的 initiator 标 `ADAPTER_DERIVED` | VERIFIED | `InitiatorRef.source=ADAPTER_DERIVED`；两个 backend 测试断言 |
| A7 | adapter-derived owner：owner 来自 Unified `ToolRegistration.owner`（tool_registration），不是 backend 原生 ownership | PARTIAL | Codex 原生 owner 是 session-scoped services（BACKEND_SPECIFIC）；本阶段只持久化 Unified overlay 的 owner ref |
| A8 | backend-specific identity：`BackendEventRef` 在 tool/call、tool/result、attempt/end 保留；AgentScope/Codex 各自 ref 可回源 | VERIFIED | `test_backend_ref_preserved`；Codex raw_event_ref line 7 |
| A9 | replay determinism：same log + same projection rules ⇒ same ExecutionRecord；`derive_messages` 确定性仍为 INFERENCE | PARTIAL | Phase 5-E §19 Q3；`build_execution_record` 是纯投影 |
| A10 | event schema extension：新字段写入现有 payload（initiator_ref / owner_ref / context_provenance），不新增事件类型、不改变 surface / attempt identity | VERIFIED | `events.py` payload 自由；既有 100 个 runtime 测试全 PASS |

## 显式保留的 gap

- `authorized_principal`：事件层仍无字段（Phase 5-E §19 Q7），本阶段不伪造。
- `parent_initiator_ref`：Python runtime 无 parent/child 证据，永不写入。
- `scope_ref` / `effect_ref`：runtime 无持久化 identity，暂不实现。
- 完整 request-time context exact snapshot：不允许把 Model Context 复制进
  Event Log（Phase 5-H §24），因此 quality 保持 PARTIAL。
