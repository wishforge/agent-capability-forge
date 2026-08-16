# 03 — Phase 5-F Report：ExecutionAttempt + Backend Extension Runtime

> 阶段目标：把 Phase 5-E 冻结的三个 Extension Points 落到 runtime：
> ExecutionAttempt、BackendEventRef、BackendMetadata/Lossiness。
> 不接第三个 backend，不扩大 Semantic Core。

## 1. 变更

- 新增 `runtime/extensions.py`：`ExecutionAttempt`、`Execution`、
  `BackendEventRef`、`BackendMetadata`（含 EXACT/SYNTHETIC/LOSSY、
  RUNNING/SUCCEEDED/FAILED/ABORTED）。
- `events.py`：新增 trace 事件 `execution/attempt/start` / `end`
  （为什么是 core event：attempt lifecycle 必须持久化且 replay-aware；
  metadata-only 无法承载 end status，会造成 replay 推断——见 01 §8）。
- `runtime.py`：每次 `adapter.stream` 创建 attempt；compaction retry 在同一
  Step/Execution 上开新 attempt；TURN_START 携带 adapter 级
  `backend_metadata`；stream 事件携带 `backend_event_ref` 进入 SessionEvent。
- `model_adapter.py`：四个 stream 事件类型可选携带 ref/metadata（backend-neutral）。
- `tool_runtime.py`：`ToolCall` 可携带 ref/metadata，TOOL_CALL 事件持久化。
- `backend/adapters/codex.py`：`BackendMappingMetadata` 改为共享
  `BackendMetadata` 子类；全部 ref 升级为 `BackendEventRef`。
- `backend/adapters/agentscope.py`：新增 `mapping_metadata` 与每事件 ref；
  修复同一 reply 内 `tool_calls` 状态泄漏（max_iters>1 时第二次 ModelFinal
  错误携带上一次的 tool call）——这是 adapter 自身 bug 修复，不触碰 core。
- `recovery.py`：repair 为未闭合 attempt 合成 `ABORTED/interrupted`；
  replay 重建 `ReplayExecution` / `ReplayAttempt`。
- 新增 `tests/test_phase5f.py`（17 tests）。

## 2. 判定问题

1. **ExecutionAttempt 是否真正独立于 Step？**
   YES。attempt 是独立对象 + 独立 trace 事件；同一 Step 可含多 attempt，
   attempt 不改变 Step identity；多 Step backend（Codex）每 Step 一个
   execution，attempt 可跨 execution 通过 `parent_execution_id` 链接。

2. **Compaction retry 是否正确表达成 Attempt？**
   YES。golden：overflow → compaction → A1=FAILED → A2=SUCCEEDED，
   Turn=1 / Step=1 / Execution=1 / Attempts=2（`test_golden_compaction_retry`）。

3. **Attempt 是否可持久化？**
   YES。`execution/attempt/start|end` 进入 EventStore JSONL，payload 含
   execution_id / attempt_id / attempt_number / parent_execution_id / reason /
   status / started_at / ended_at / backend refs。

4. **Replay 是否保持 identity？**
   YES。replay 返回相同 execution_id、attempt_id、attempt_number、status；
   不重编号（`test_replay_preserves_attempt_identity`）。

5. **BackendEventRef 是否 backend-neutral？**
   YES。`extensions.BackendEventRef` 无 backend import；Codex 与 AgentScope
   都只通过它表达 backend 事件引用；统一事件只保存 reference，不复制 raw
   event。

6. **Lossiness 是否显式？**
   YES。`BackendMetadata.mapping_quality + missing_semantics +
   backend_event_ref`；Codex 六项与 AgentScope 三项在 TURN_START
   backend_metadata 持久化，attempt/end 与 tool/call 保留 raw ref。

7. **Core 是否仍然 backend-neutral？**
   YES。core 文件（events/event_store/surface/compaction/tool_runtime/
   turn_step/initiator/recovery/runtime/model_adapter/extensions）源码 0 处
   `codex` / `agentscope`；无 backend 分支；core 不读取 backend_metadata 决定
   生命周期（`test_core_never_reads_backend_metadata`）。

8. **AgentScope/Codex 是否共享 extension？**
   YES。两个 adapter 都构造 `BackendEventRef`/`BackendMetadata` 并经
   AgentRuntime 生成 attempt 事件；事件序列跨 backend 一致
   （`test_agentscope_attempt` / `test_codex_attempt` / 5-D cross-backend）。

9. **Tool side-effect retry 是否安全？**
   YES。`retry_safe` 守卫保持；side effect 已发生时 attempt 以
   `ABORTED / UNSAFE_RETRY_BLOCKED` 结束且不创建第二个 attempt，
   tool 只执行一次（`test_tool_side_effect_blocks_unsafe_retry`）。
   compensation 留作 future capability。

10. **哪些仍是 assumption？**
    A1–A8 见 `02-extension-assumptions.md`；关键未覆盖项：
    Codex 跨 Step compaction retry fixture 不存在（字段已冻结，未直接验证），
    通用 backend error retry policy 未新增，AgentScope 事件 id 稳定性限于
    2.0.2。

## 3. 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | PASS（14 invariants） |
| Phase 2 kernel | PASS（40/40） |
| Phase 4-A | PASS |
| Phase 4-B | PASS |
| Phase 4-C | PASS |
| Phase 4-D | PASS |
| Phase 5-B.1 | PASS |
| Phase 5-C | PASS |
| Phase 5-D | PASS |
| Phase 5-F（新增） | PASS（17/17） |

运行方式：

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py \
  docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -q
python3 -m unittest discover -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
```

## 4. Final Verdict

**PASS**

- ExecutionAttempt 独立成立；compaction retry 使用 Attempt；replay 保留
  attempt identity；BackendEventRef 成立；Lossiness 可见；AgentScope/Codex
  共用 extension；Semantic Core 仍 backend-neutral；全部旧测试继续 PASS。
- 无 UNIFIED CORE GAP；无第三个 backend；未修改 Codex / AgentScope 本体；
  未进入 Phase 6。
