# 26 — Phase 5-C Report：Minimal Codex Backend Adapter

> 基线：openai/codex `279b93242cfef379e65da97e87e44b83c5934fd7`
> 新增：`runtime/backend/adapters/codex.py`、`runtime/tests/test_phase5c_codex.py`、
> `runtime/tests/fixtures/codex_{golden,lossy,error}.jsonl`、本报告 + 25。
> 兼容性改动：`model_adapter.py` docstring 移除 “Codex later” 字样（无语义变化），
> 使 Backend Independence Audit 大小写敏感/不敏感均为 0 命中。

## 1. CodexAdapter 是否成立？

成立（最小边界）。`CodexAdapter` 实现现有 `ModelAdapter.stream()` 契约，解析
pinned rollout JSONL：assistant message → `ModelChunk` + `ModelFinal`，
`custom_tool_call` / `function_call` → `ModelToolCallEvent`，生命周期事件 →
turn/error metadata。真实工具执行留在 Unified ToolRuntime
（`delegates_tools=False`），Golden Path（查询库存 → 采购建议 → 最终答案）完整跑通。

## 2. Semantic Core 是否零 Codex dependency？

是。`rg -i "codex"` 在 `runtime.py`、`model_adapter.py` 及全部 core 对象文件
（events/event_store/surface/compaction/tool_runtime/turn_step/initiator/recovery）
均为 0 命中。Codex 引用只存在于 `backend/adapters/codex.py`、测试与 fixtures。
未修改任何 semantic core 行为；仅 docstring 清洁。

## 3. Session / Turn / Step 是否成功映射？

成功（ADAPTER）。Session ← rollout 文件；Turn ← `task_started`…`task_complete`；
Step ← 每个 sampling request（assistant message + tool activity），`step_id`
由 Unified runtime 分配。Golden fixture 产生 1 Turn / 3 Step，结构可复现。

## 4. Tool Call / Result 是否成功映射？

成功。Codex call_id 保留为 Unified call_id；`tool/call` → `tool/result` 由
Unified ToolRuntime 建立 `source_event_seqs` 配对；rollout 内 call↔output
配对写入 `call_metadata`（EXACT 或 LOSSY），raw_event_ref 可回源。

## 5. Error 是否可转换？

可转换（两层）。Codex fatal `EventMsg::Error` → `ModelRequestError` →
`turn/end{error}`；DSH 工具异常 → `ToolResult(is_error=True)` 且 turn 继续。
Codex rollout 不持久化结构化成功标志，因此 Codex 原生工具失败为 LOSSY，
不伪造字段。

## 6. Lossiness 是否可见？

可见且可测。`BackendMappingMetadata`（backend / mapping_quality /
missing_semantics / raw_event_ref / source_event_type）挂在 adapter 的
session / turn / step / call / error 五层；`missing_semantics` 为 23 §2 六项
清单；`test_codex_lossiness_visible` 直接断言。

## 7. Persistence 是否成立？

成立。Unified EventStore（path JSONL）完整记录 Codex 驱动执行；close →
reopen → last_seq / surface / rebuild 一致（`test_codex_persistence`）。
Codex rollout 与 Unified log 并存。

## 8. Replay 是否成立？

成立。reopen 后 `replay()` 重建 Session / Turn / Step / Tool Call / Result /
Final Answer，结构一致，且不二次执行真实工具（执行计数保持不变，
`test_codex_replay`）。

## 9. Ownership / Causality 是否保持分离？

保持分离。Owner：Unified ToolRegistration.owner（如 `ERP`）为 Capability 侧；
Codex backend 资源标 BACKEND_SPECIFIC，不映射为 Capability。Causality：
Codex 无 ambient initiator（MISSING 进 lossiness 清单），live initiator 由
Unified `with_initiator("agent-c")` 赋值（ADAPTER ASSIGNMENT）；工具内
`require_initiator()` 看到 Unified 身份，测试验证二者不同源。

## 10. 哪些仍然未实现？

- 真实 Codex executable / process / library E2E（当前为 FIXTURE TEST）
- 多 turn rollout、`task_aborted` → `turn/end{aborted}`
- Codex 原生 tool output 作为权威 tool/result（当前由 Unified ToolRuntime 执行）
- ExecutionAttempt、compaction / fork / rollback / subagent / sandbox 映射
- `TOOL_NOT_STARTED` / crash unknown-outcome 精确判定

## 11. 哪些是 Backend-Specific？

- rollout JSONL 作为 raw source；Codex `codex_error_info` 错误分类
- session-scoped 资源 owner；无 Capability / Scope / Effect 等价物
- 无 ambient initiator；originator 不是 agent 身份
- exec `success` 不持久化；sampling request 即 Step 边界的构造规则

## Final Status

**PARTIAL**（非 PASS）：存在明确 LOSSY / MISSING / BACKEND-SPECIFIC 语义，
且执行源是 fixture 而非真实 Codex E2E；Semantic Core contract 零修改，
全部既有测试（Phase 1 / 2 / 4-A / 4-B / 4-C / 4-D / 5-B.1）继续 PASS。
