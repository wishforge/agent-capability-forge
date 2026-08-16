# 09 — Durable Evidence Report（Phase 5-H）

> 阶段：Phase 5-H。目标：把“实时运行时知道的信息”升级为
> “Replay / Audit / Evaluation 之后仍可证明的信息”。
> 产物：`07-durable-evidence-audit.md`、`08-durable-evidence-assumptions.md`、
> `runtime/extensions.py`（InitiatorRef / OwnerRef）、`runtime/tool_runtime.py`
> （tool/call + tool/result 写入 refs）、`runtime/runtime.py`
> （request/header + attempt 写入 initiator_ref / context_provenance）、
> `runtime/recovery.py`（ReplayAttempt 扩展 + ExecutionRecord 投影）、
> `runtime/tests/test_phase5h_durable_evidence.py`（16 tests）。

## 1. 变更

### 最小语义

```text
InitiatorRef { ref, source=ADAPTER_DERIVED, parent_ref=None }
OwnerRef     { owner_type, owner_id }
```

- `initiator_ref`：写入 `request/header`、`execution/attempt/start|end`、
  `tool/call`、`tool/result`。
- `owner_ref`：写入 `tool/call`、`tool/result`；来源为
  `ToolRegistration.owner`（owner_type=capability）。
- `context_provenance`：写入 `execution/attempt/start` payload：
  `request_ref`（指向 request/header seq）、`source_event_refs` /
  `surface_refs`（active surface seqs）、`current_input_ref`、
  `runtime_context_ref=None`、`quality=PARTIAL`、`missing_semantics`。
- `ExecutionRecord`：`record_version=5h.1` + `projection_rule_version=v1`，
  纯投影（`build_execution_record`），含 initiator_ref / owner_refs /
  attempts / tools / events / backend_refs / context_provenance。

没有新增事件类型；没有把完整 Model Context 复制进 Event Log；
没有把 Capability lifecycle 写入 Execution Event Log；没有修改
Codex / AgentScope source。

## 2. 十问回答

### 1. Initiator 是否可持久化？

**是（ADAPTER_DERIVED）**。`InitiatorRef.ref` 来自 AgentRuntime 配置的
`InitiatorContext.agent_id`，以普通 JSON dict 写入事件；不持久化 Python
对象、不依赖 ContextVar 作为持久化身份。replay 后从 log 可读回。

### 2. Owner 是否可持久化？

**是（registration-derived）**。`OwnerRef(owner_type="capability",
owner_id=ToolRegistration.owner)` 写入 tool/call + tool/result；replay 后
可读回。语义稳定性依赖 assumption A2。

### 3. Owner / Initiator / Authorization 是否保持分离？

**是**。三个维度仍为独立字段/概念：`initiator_ref`、`owner_ref`、
`authorized_principal`（本阶段不持久化，事件层保持 OPEN）。
测试 `test_authorized_principal_separate` 验证三者不合并、不互相推导。

### 4. Tool Call 能否回答“谁触发、谁拥有”？

**能**。`tool/call` payload 同时携带 `initiator_ref` 与 `owner_ref`；
`tool/result` 也携带两份 refs，失败归因不需要回查 call 事件。

### 5. Context Provenance 是否可持久化？

**是（PARTIAL）**。attempt/start 持久化 request ref、source event refs、
surface refs、current input ref；system_prompt / runtime_context 无 durable
snapshot，显式标记 `missing_semantics`，不把“可重建 surface”写成
“原始 context exact snapshot”。

### 6. Replay 后 attribution 是否一致？

**是（本 runtime 覆盖范围）**。close → reopen → replay 后，
`initiator_ref`、`owner_ref`、`context_provenance`、backend refs 均一致；
attempt identity 不重编号。测试：`test_initiator_survives_replay`、
`test_owner_survives_replay`、`test_context_provenance_survives_replay`。

### 7. AgentScope 是否支持？

**是（ADAPTER_DERIVED）**。AgentScope 工具经 `ToolRuntime.execute` 落
`initiator_ref` / `owner_ref` / backend ref；attempt/start 带 context
provenance。`test_agentscope_durable_evidence` 通过。

### 8. Codex 是否支持？

**是（ADAPTER_DERIVED + LOSSY 保留）**。Codex 无原生 ambient initiator；
Unified runtime overlay 赋值 `InitiatorRef(source=ADAPTER_DERIVED)`，
`BackendEventRef` 保持可回源；六项 missing_semantics 不变。
`test_codex_durable_evidence` / `test_backend_ref_preserved` /
`test_lossiness_preserved` 通过。

### 9. 哪些字段是 adapter-derived？

```text
initiator_ref       ADAPTER_DERIVED（AgentScope / Codex 均非 backend 原生）
owner_ref           tool_registration（Unified overlay，非 backend 原生）
context_provenance  PARTIAL（surface refs 是 log 事实；system/runtime 缺失）
```

### 10. 最大剩余 Evaluation Evidence Gap 是什么？

**完整 request-time context 快照**。当前 provenance 能证明“Agent 当时基于
哪些历史事件/输入”，但不能重建 system_prompt 与 runtime_context 的 exact
内容；这两者需要独立的 durable snapshot 语义（且不得与 Event Log 混成
source of truth）才能从 PARTIAL 升级。

## 3. 最终判定

**PASS**

- initiator_ref 可持久化（ADAPTER_DERIVED）
- owner_ref 可持久化（capability / tool_registration）
- owner != initiator，authorization 保持分离（OPEN，不伪造）
- tool attribution 可恢复（tool/call + tool/result）
- context provenance 有明确证据（PARTIAL，显式 missing）
- replay 保留 attribution（close/reopen/replay）
- AgentScope / Codex 都能提供最小 evidence
- ExecutionRecord 可读取 durable evidence（immutable 纯投影）
- Core 仍 backend-neutral（无 backend import 进 core）

**PARTIAL 项**：context provenance 完整快照、owner 语义稳定性、
parent_initiator_ref（无证据不写入）、scope/effect refs。

无 UNIFIED CORE GAP：未修改 Codex / AgentScope source，未接第三个
Backend，未实现 Evaluation Engine / Judge / Scoring / RCA。

## 4. 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | PASS（14/14 invariants） |
| Phase 2 kernel | PASS（40/40） |
| Phase 4-A / 4-B / 4-C / 4-D | PASS（并入 runtime suite） |
| Phase 5-B.1 / 5-C / 5-D / 5-F / 5-G | PASS（并入 runtime suite） |
| Phase 5-H（新增） | PASS（16/16） |

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py \
  docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -q
python3 -m unittest discover -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
```

结果：runtime 共 116 tests（100 旧 + 16 新）全部 OK。
