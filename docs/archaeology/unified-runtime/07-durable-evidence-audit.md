# 07 — Durable Evidence Audit（Phase 5-H）

> 阶段：Phase 5-H。本文件在修改任何 runtime 代码前完成，只审计当前
> `docs/archaeology/deepseek-harness/runtime/` 与 Phase 5-E/5-F/5-G 契约
> 的 durable evidence 基线。状态词：VERIFIED / PARTIAL / NOT FOUND /
> INFERENCE。禁止在审计阶段把 gap 写成 VERIFIED。

## 1. Initiator 是否只存在 ContextVar？

**VERIFIED（当前基线）**

- `initiator.py`：`InitiatorContext` + `_current` ContextVar + `with_initiator()`
  是唯一的 initiator 载体。
- `runtime.py`：`AgentRuntime.initiator` 只是构造参数；`run_turn` 用
  `with_initiator(self.initiator)` 包住整个 driver 链。
- 没有任何 initiator ref 写入 EventStore；`request/header`、attempt、
  `tool/call`、`tool/result` payload 均无 initiator 字段。

结论：initiator 存在性 VERIFIED，durable initiator ref **NOT FOUND**。

## 2. Execution Event 是否包含 durable initiator ref？

**NOT FOUND**

- `agent/request`（落盘 `request/header`）payload 只有 `model` / `tools`。
- `execution/attempt/start|end` payload 只有 execution/attempt identity、
  reason、status、时间、backend refs，没有 initiator。
- `turn/start`、`step/start`、`assistant/message`、`tool/*` 均无 initiator。

## 3. Tool Call 是否有 durable owner ref？

**NOT FOUND**

- `tool_runtime.py`：`ToolRegistration.owner` 是运行时注册字段，
  `tool/call` 事件 payload 不写 owner。
- `ToolCall` dataclass 没有 owner ref 字段。
- Codex adapter 的 `ownership_metadata` 是 backend-specific 内存对象，
  不进入统一事件。

## 4. Capability Identity 是否持久化？

**NOT FOUND**

- Capability 生命周期由 `python-cordis/kernel/manager.py` runtime registry
  持有，`CapabilityDescriptor.id` 不写入 SessionEvent。
- runtime 工具注册只保留 `owner` 字符串，未验证其是否为稳定 capability id。

## 5. Scope Identity 是否持久化？

**NOT FOUND**

- `PluginScope` 是 runtime-only 对象；replay 不恢复（Phase 5-E §6）。
- 事件层无 scope ref。

## 6. Effect Identity 是否持久化？

**NOT FOUND**

- `EffectRegistry`（python-cordis 12 §3）只存在于 runtime scope；
  事件层无 effect ref。

## 7. Backend Event Ref 是否可以关联 owner / initiator？

**PARTIAL**

- `BackendEventRef` 已持久化在 `tool/call`、`tool/result`、attempt/end、
  turn/start 的 payload 中（Phase 5-F）。
- 但事件里没有 owner / initiator 字段可供 ref 关联；backend ref 只能回源
  raw event，不能回答“谁触发 / 谁拥有”。

## 8. Request Header 是否能识别 Context Snapshot？

**PARTIAL**

- `request/header` 是 `agent/request` 的 durable surrogate，记录
  model + tools。
- 不记录 request-time surface 事件 refs、current input ref、
  runtime context ref；无法回答“当时看到了哪些历史事实”。
- `derive_messages()` 可从 log 重建 surface，但完整 request-time context
  快照（system / runtime_context / current_input）无持久化证据。

## 9. derive_messages() 的输入是否能从 Persisted Events 重建？

**PARTIAL / INFERENCE**

- surface 事件（user/message、assistant/message、tool/result）全部在
  append-only log 中，可重建（Phase 5-E §11）。
- `derive_messages` 确定性是 Phase 5-E §19 的 INFERENCE / PARTIAL，不是
  VERIFIED。
- system_prompt / runtime_context / current_input 不是事件，重建的只是
  “could have seen”的 surface，不是 request-time exact snapshot。

## 10. Replay 后能否恢复完整 Attribution？

**NOT FOUND（完整归因）/ PARTIAL（现有 durable 部分）**

- replay 已可恢复：Session/Turn/Step、attempt identity、tool call/result
  lineage、backend refs、lossiness（Phase 5-F）。
- 不可恢复：initiator ref、owner ref、context provenance；replay 后
  Evaluation 无法从 log 回答“谁触发 / 谁拥有 / 当时看到了什么”。

## 结论

Phase 5-H 需要把三类证据从 runtime-only 变成 durable：

```text
initiator_ref        NOT FOUND
owner_ref            NOT FOUND
context provenance   PARTIAL / REQUIRED EXTENSION
```

以上均不是 VERIFIED；实现必须显式标 ADAPTER_DERIVED / PARTIAL，不得伪造
backend 原生身份。
