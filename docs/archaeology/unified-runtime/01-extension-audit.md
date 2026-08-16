# 01 — Phase 5-F Extension Audit（只读审计）

> 范围：`docs/archaeology/deepseek-harness/runtime/` 现有实现 + Phase 5-E
> Contract v1（`docs/archaeology/unified-agent-runtime-core-contract-v1.md`）。
> 本文件只做审计，不做设计重写。状态词：VERIFIED / PARTIAL / UNKNOWN /
> DESIGN PROPOSAL。

## 1. 当前 runtime 是否已有 execution identity？

**PARTIAL（无显式对象，只有派生身份）**

- `turn_step.py`：`Execution` 只存在于 Contract 与文档；runtime 没有
  `Execution` 对象，没有 `execution_id` 字段。
- 运行时“一次逻辑执行”的隐式身份是 `Step.step_id`（`turn_step.Step`）与
  `agent/request` 事件（`runtime.py`），但没有显式 `execution_id`。
- Contract v1 §3：Execution = CORE（runtime object，非持久化实体）。

## 2. Step 是否已经可以区分多次 request？

**PARTIAL**

- 同一 Step 内的模型重试（`runtime.py` 内层 `while True`）可以发生多次
  `adapter.stream`，但 log 里只有 `agent/request` / `request/header`，没有
  “第几次 request”的持久化身份。
- Codex Adapter 把一次 sampling request 构造为一个 Step（`codex.py`
  `_Segment`），跨 request 的 Step 可区分；但“这些 request 是否属于同一逻辑
  执行”不可表达。

## 3. tool call 是否已经有 execution identity？

**NO**

- `tool_runtime.ToolCall` 有 `call_id` / `root_call_id` / `parent_call_id`，
  归因到 turn/step（事件字段），但没有 `execution_id` / `attempt_id`。
- 需要 Phase 5-F 把 tool call 与 attempt 连接起来（至少可审计）。

## 4. compaction retry 当前如何标识？

**PARTIAL**

- `compaction.py`：`CompactionEngine.overflow_retries` 计数器 +
  `retry_safe(store)` 守卫；`runtime.py` 内层循环重建 `mctx` 并 `continue`。
- retry 身份只存在于运行时内存（同 Step 重建请求），没有任何持久化 attempt
  record；崩溃/重启后无法区分 A1/A2。

## 5. replay 如何识别一次 execution？

**PARTIAL**

- `recovery.replay` 只重建 Turn/Step/Tool（`ReplayTurn` / `ReplayStep` /
  `ReplayToolResult`）；Execution 对象不重建（Contract v1 §3 明确 Execution
  不持久化为对象）。
- 没有 attempt 级 replay 数据；compaction retry 的“同一步重试”在 replay 后
  无法恢复。

## 6. AgentScope / Codex adapter 当前有没有自己的 event id？

**VERIFIED（backend 侧有；统一侧没有）**

- AgentScope 2.0.2 事件：`TextBlockDeltaEvent.reply_id/block_id`、
  `ToolCall*Event.tool_call_id`、`ModelCallEndEvent.reply_id` 等稳定 id
  （`agentscope.event` 源码确认）。
- Codex rollout：JSONL 行号 + `item_type` + `call_id` 稳定；Adapter 已有
  `BackendMappingMetadata.raw_event_ref`（dict：path + line + item type），
  但只在 adapter 内存中，不进入 EventStore。
- 统一侧没有 `BackendEventRef` 类型；`raw_event_ref` 只是 dict，无质量标记
  （EXACT/SYNTHETIC/LOSSY）。

## 7. 现有 BackendMappingMetadata 是否已存在？

**VERIFIED（Codex-only）**

- `backend/adapters/codex.py`：`BackendMappingMetadata`（backend /
  mapping_quality / missing_semantics / raw_event_ref / source_event_type），
  六个 missing_semantics 已枚举（23 §2）。
- AgentScope Adapter 没有等价 metadata；`mapping_metadata` 不在 core。

## 8. 现有 event schema 是否有 metadata 扩展空间？

**VERIFIED**

- `SessionEvent.payload` 是自由 `Mapping`，JSONL 持久化不限制键；
- 事件类型可追加（`events.py` 常量），非 surface 事件不会进入模型历史
  （`SURFACE_EVENT_TYPES` 白名单）；
- `EventStore._encode/_decode` 对 payload 原样序列化，无需改动即可承载
  attempt / ref / metadata。

## 结论

- 无 TRUE UNIFIED CORE GAP：Step 语义、Turn/Step 边界、append-only、surface
  投影都不需要改变。
- 需要实现三个 extension：`ExecutionAttempt`（持久化 + replay identity）、
  `BackendEventRef`（统一引用类型 + 质量标记）、`BackendMetadata`（lossiness
  容器，core 不读取）。
- 不需要第三个 backend、不修改 Codex / AgentScope 本体、不进入 Phase 6。
