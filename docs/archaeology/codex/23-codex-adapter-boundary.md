# 23 — Codex Adapter Boundary（Phase 5-B）

> 目标：定义最小 Codex Adapter 边界 + Lossiness Contract。只做设计合同，不实现。
> 依据：`22-semantic-gap-decision.md` + `20-unified-semantic-mapping.md` + `21-backend-portability-contract.md`。
> 本文件不新增考古，不修改任何 runtime / contract / source。

---

## 1. 总则

`CodexAdapter` = 纯翻译层：把 Codex rollout / 运行时事件翻译成 Unified SessionEvent，
并把损失显式暴露。Adapter 不拥有语义，不修改语义。

### 1.1 允许做什么

| 能力 | 内容 |
| --- | --- |
| source event parsing | 读 RolloutItem（SessionMeta / ResponseItem / EventMsg / Compacted / WorldState / TurnContext / InterAgentCommunication） |
| dedupe | `EventMsg::RawResponseItem` vs `RolloutItem::ResponseItem` 去重 |
| Step reconstruction | sampling request 分段 → adapter-derived Step；`step_id` 标为构造值 |
| call/result pairing | call_id 配对（exec / MCP / apply_patch / dynamic tool） |
| error normalization | 按工具类型 → `ToolResult(is_error)` + 粗粒度 reason |
| causality mapping | SessionMeta fork/parent + InterAgentCommunication → unified lineage |
| compaction mapping | `CompactedItem` → replacement 语义 + backend metadata |
| replay mapping | resume / fork / rollback → 历史重建语义 + backend 标记 |
| crash inference | unmatched call + interrupted turn → `TOOL_OUTCOME_UNKNOWN`（ADAPTER/INFERENCE） |
| raw_event_ref | 每个 Unified event 可携带 rollout path + line + item type |

### 1.2 不允许做什么

| 事项 |
| --- |
| 改 EventStore append-only / surface / compaction 语义 |
| 改 Turn/Step 核心语义（Turn = 0..N Step；Step = 一次模型请求 + 该请求的工具活动） |
| 改 Capability ownership（不推导 owner、不自动映射 Capability） |
| 改 Causality contract（不发明 `initiator_id`） |
| 修改 DSH contracts（13-17 / 21） |
| 修改 AgentScope adapter / Semantic Core / 在 core 对象加 backend import |
| 修改 Codex source；用 fork PoC 证明官方语义 |
| 为统一而合并或压平 backend-specific 语义 |

---

## 2. Lossiness Contract

三原则：

- **VISIBLE**：lossiness 可枚举，消费方可查询。
- **AUDITABLE**：每个有损翻译可回源（`raw_event_ref`）。
- **REPLAY-AWARE**：replay 后 lossiness 与 metadata 不消失。

### BackendMappingMetadata（contract only，不实现）

```json
{
  "backend": "codex",
  "mapping_quality": "LOSSY",
  "missing_semantics": [
    "STEP_BOUNDARY_PERSISTED",
    "EXEC_FAILURE_STRUCTURED_SUCCESS",
    "CHUNK_TO_MESSAGE_LINEAGE",
    "CRASH_OUTCOME_NATIVE_MARKER",
    "AMBIENT_INITIATOR",
    "COMPACTION_RETRY_SAME_STEP"
  ],
  "raw_event_ref": {
    "rollout_path": "sessions/2026/08/16/rollout-xxx.jsonl",
    "line": 42,
    "item_type": "ResponseItem"
  }
}
```

规则：

1. session 级 metadata 记录 `mapping_quality` + `missing_semantics`；
2. 每个 Unified event 可携带 `raw_event_ref`（不改变 event 主语义）；
3. 未映射 / 有损项必须出现在 `missing_semantics`，禁止静默丢失；
4. 若 Codex 基线行为改变，先重核 20 / 22 再更新 metadata。

---

## 3. Extension Semantics（contract only，不实现）

| Extension | 契约要点 |
| --- | --- |
| ExecutionAttempt | `parent_execution_id` + `attempt_no`；连接 compaction pre/post Step；不修改 Turn/Step |
| BackendEventRef | rollout path + line + item type；每事件可选 |
| BackendMetadata | backend / mapping_quality / missing_semantics / raw_event_ref；session 级 |

当前 Unified SessionEvent schema 无这些字段；实现前需要 schema 扩展（Phase 5-C），不是语义修改。

---

## 4. Core / Extension / Backend Split

| 层 | 成员 | 可否由 Adapter 改变 |
| --- | --- | --- |
| Core semantics | Session/Turn/Step、EventStore append-only、Surface 投影、Tool failure 分层、Capability ownership、durable lineage、compaction replacement | 不可 |
| Extension semantics | ExecutionAttempt、BackendEventRef、BackendMetadata | 仅 schema 扩展承载 |
| Backend semantics | Codex CompactedItem/window_ids、rollback marker、fork copy/reference、sandbox denial fallback、originator、rollout trace graph；DSH currentInitiator、TOOL_NOT_STARTED 判定、waterfall 阶段细节 | 保留原样，仅 metadata 可见 |

---

## 5. 实现前验收条件（Phase 5-C）

1. `runtime.py` 改为 adapter interface（21 BP-01 解除 PARTIAL），core 对象 0 backend import。
2. 任一 Codex rollout 可翻译为 Unified SessionEvent，每事件可回源。
3. Step 构造规则可复现：同一 rollout + 同一规则 ⇒ 同一 Step 序列。
4. lossiness 清单可枚举；有损项不伪装成 VERIFIED。
5. `TOOL_OUTCOME_UNKNOWN` 只由 inference 规则产生，标注 ADAPTER/INFERENCE。
6. 不新增 backend import / 分支到 core 对象。

---

## 6. Final Status

**PARTIAL**：Adapter 边界与 Lossiness Contract 已冻结；不进入实现。
