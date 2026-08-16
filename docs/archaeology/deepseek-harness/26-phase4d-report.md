# 26 — Phase 4-D Report: Real Agent Loop + AgentScope 2.0 Python

> 阶段结论：**PASS**（AgentScope + Deterministic Model + DSH Semantic Runtime
> + Tool + Persistence + Compaction + Replay 完整闭环）
> AgentScope 版本：`2.0.2`（base conda env，public API only）
> 变更：新增 `runtime/model_adapter.py`、`runtime/tests/test_phase4d.py`、
> `25-phase4d-assumptions.md`；升级 `runtime/runtime.py`
> （RuntimeCoordinator 委托给新的 AgentRuntime 流驱动 loop）

## 1. 验证结果

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | `ALL INVARIANTS PASS`（14/14 checks） |
| Phase 2（semantic + bridge + lifecycle + manager） | 40/40 PASS |
| Phase 4-A | 15/15 PASS |
| Phase 4-B | 14/14 PASS |
| Phase 4-C | 20/20 PASS |
| Phase 4-D | 13/13 PASS |

## 2. 目标回答

1. **AgentScope 是否可以作为 execution substrate？** 是。AgentScope 2.0.2
   的 `Agent.reply_stream` / `Toolkit` / `FunctionTool` / `ChatModelBase`
   足以承载 model execution、streaming 与 public tool dispatch；DSH 通过
   adapter 消费公开事件流驱动 Step 边界。
2. **Semantic Runtime 是否保持 AgentScope-independent？** 是。
   `AgentRuntime` 只见 `ModelChunk / ModelFinal / ModelToolCallEvent /
   ModelToolResultEvent / ModelRequestError`；AgentScope 只存在于
   `model_adapter.AgentScopeModelAdapter` 内。semantic core 没有 import
   AgentScope 私有 API。
3. **Real model 是否进入统一 request/response contract？** 是。
   `ModelAdapter` 是唯一 runtime 接口；deterministic callable 与
   AgentScope-compatible `ChatModelBase` 都经 `stream(ctx, model_context)`
   进入同一 loop。真实网络模型未在本阶段调用（25 A7）。
4. **Tool call 是否正确进入 DSH Tool Waterfall？** 是。AgentScope 的工具
   wrapper 委托 `ToolRuntime.execute`，`pre_execute → approval → guard →
   execute → post_execute → finalize` 全部经过；`tool/call` + `tool/result`
   由 ToolRuntime 写入事件日志，AgentScope 的 `ToolResultEndEvent.state`
   做一致性校验。
5. **Initiator 是否正确贯穿 Agent Loop？** 是。`with_initiator` 包住整个
   `run_turn`，AgentScope 工具 wrapper 在同一 async chain 内执行，
   `require_initiator()` 返回 `agent-a`；run 结束后 ContextVar 清空。
6. **Persistence 是否保留完整 execution history？** 是。JSONL EventStore
   记录 user/turn/step/request-header/chunk/message/tool/compaction 事件；
   reopen 后 seq 数、事件类型（`agent/request` → `request/header`）与
   surface 完全一致。
7. **Context compaction 是否真正触发 retry？** 是。
   `test_context_overflow_compaction_retry` 证明：第一次 request 抛
   `CONTEXT_WINDOW_EXCEEDED` → `CompactionEngine.handle_request_error` →
   replacement events 持久化 → surface 重建 → 第二次 request 使用 compacted
   context → 工具成功执行；`overflow_retries == 1`，工具副作用只发生一次。
8. **Restart/replay 是否得到一致 history？** 是。reopen 后
   `rebuild_session` / `replay` 恢复相同 turn/step/tool lineage，
   `test_real_agentscope_replay` 与 `test_compaction_persisted_surface` 覆盖。
9. **AgentScope 哪些能力存在 public API gap？** 无 core 事件总线（只有
   `reply_stream`）；`Toolkit` 无 per-tool unregister；无公开 deterministic
   mock model；无 model error 事件（错误以异常抛出）；无 public
   confirmation/external execution 的一体化支持（Phase 4-D 未使用）；
   `FunctionTool` 对 `**kwargs` 只生成空 schema。
10. **哪些仍只是 Phase-4D assumptions？** 25-phase4d-assumptions.md
    A1–A12：真实网络模型行为、provider 精确 error/token、部分流失败回滚、
    AgentScope 内部事件、外部确认/外部执行工具、多进程并发、Agent 每 Step
    重建策略、one reply = one Step、unknown tool 合成 result、流式 last
    chunk 约定等。

## 3. Golden E2E 断言

`test_golden_inventory_procurement_e2e` 完整验证：User → Turn 1 → Step 1 →
`inventory.lookup`（owner=ERP）→ Step 2 → `procurement.suggest` → Final
Answer → Turn End；断言 event order、owner、initiator、tool lineage、
surface、final context、persistence、replay 全部成立。

## 4. 结论

**PASS** — Phase 4-D 最小 scope 完成：AgentScope 2.0.2 public API +
确定性 AgentScope-compatible model + DSH Semantic Runtime + Tool Waterfall +
JSONL persistence + compaction→retry + replay 全链路成立，且 Phase 1 / Phase 2 /
Phase 4-A / 4-B / 4-C 全部保持 PASS。

PASS 不声明真实网络模型与生产部署行为；未决边界全部记录在
25-phase4d-assumptions.md。按阶段指令，完成后停止，不进入 Phase 5。
