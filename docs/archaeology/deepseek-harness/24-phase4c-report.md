# 24 — Phase 4-C Report: Context Projection + Compaction

> 阶段结论：**PASS**（仅 Phase 4-C 最小 scope；不等于完整 DSH compaction /
> token-meter / retry / atomicity 语义）
> 基线：`afb0d0a` + Phase 4-A / 4-B runtime（工作区未提交内容保持不变）
> 变更：`runtime/events.py`（surface_op + compaction 事件类型）、
> `runtime/event_store.py`（surface_op JSONL roundtrip）、
> `runtime/surface.py`（replace fold + 校验）、新增 `runtime/compaction.py`、
> 新增 `runtime/tests/test_phase4c.py`、新增 23-phase4c-assumptions.md 与本报告

## 1. 验证结果

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | `ALL INVARIANTS PASS`（14/14 checks） |
| Phase 2（semantic + bridge + lifecycle + manager） | 40/40 PASS |
| Phase 4-A | 15/15 PASS |
| Phase 4-B | 14/14 PASS |
| Phase 4-C | 20/20 PASS |

## 2. 目标回答

1. **Compaction 是否删除 source events？** 否。Event Log append-only；
   每次 compaction 只追加 `compaction/start → compaction/summary →
   replacement user/message → compaction/end` 四个事件，原事件全部保留
   （`test_original_events_preserved`）。
2. **Surface 是否可冷启动重建？** 是。`SurfaceProjection` 从事件序列 fold
   出 active nodes，按顺序应用 replace；restart 后只依赖 JSONL 事件即可
   得到同一 compacted surface（`test_restart_rebuild_same_compacted_surface`）。
3. **Model context 是否只来自 projection？** 是。`build_model_context()`
   只用 `derive_messages()`；compaction 只改变 projection，原始 log 不直接
   进入 model messages（`test_derive_messages_after_compaction`）。
4. **Tool-result pruning 是否独立成立？** 是。`prune_tool_result()` 不依赖
   `CompactionEngine`；追加 `compaction/prune` + 替换 `tool/result`
   （`surface_op replace [seq,seq]`、`source_event_seqs=(seq,)`、仅 content
   变化），原 tool/result 保留（`test_tool_result_pruning` /
   `test_pruning_preserves_source_event`）。
5. **Pressure/overflow 两条 trigger 是否成立？** 是。`maybe_compact()`
   （pre-step pressure）与 `handle_request_error("CONTEXT_WINDOW_EXCEEDED")`
   （overflow）都进入 `CompactionEngine → RetryDecision`；测试覆盖
   pressure、overflow、非 overflow 错误、already compacted（max retries）、
   busy、cancelled。
6. **Retry safety 是否成立？** 是。`retry_safe()` 检查最近一次 model
   request 之后是否已有 `assistant/message`、`tool/call` 或 `tool/result`；
   有则 `NO_RETRY`，禁止无条件重试同一 Step
   （`test_retry_not_allowed_after_tool_side_effect`）。
7. **Restart 后 compacted surface 是否一致？** 是。compact-before-restart
   与 compact-after-restart 的事件序列和 `derive_messages()` 完全一致；
   不依赖内存状态（`test_restart_rebuild_same_compacted_surface`）。
8. **Capability state 是否仍与 model context 分离？** 是。capability
   install/dispose 不写 SessionEvent；模型只能看到 tool schema 与
   `tool/result` projection，capability 私有 state 不进入任何 message
   （`test_capability_state_not_in_model_context`）。
9. **哪些仍是 assumption？** A1–A13（23-phase4c-assumptions.md）：token
   estimate、test summarizer、summary schema、replacement generation、
   concurrency guard、atomicity boundary、overflow retry 未接 agent loop、
   pruning representation、implicit append marker、事件顺序、balanced cut、
   failure classification、context builder。

## 3. 实现范围

- `events.py`：`SessionEvent.surface_op`（`None|'append'|{op:replace,start,end}`）；
  新增 `compaction/start|summary|end|prune` 事件类型。
- `event_store.py`：JSONL 编解码持久化 `surface_op`；旧行缺省为 `None`。
- `surface.py`：replace fold（active node identity = seq）；校验 replace
  边界在 active surface、`source_event_seqs` 覆盖全部被替换节点、
  `tool/result` 替换只允许改 content；非 surface 事件禁止携带 `surface_op`。
- `compaction.py`（新增）：`TokenMeter` / `CompactionPlan` / `RetryDecision` /
  `CompactionEngine` / `deterministic_summarizer` / `prune_tool_result` /
  `retry_safe` / `build_model_context`；失败分类
  `busy / cancelled / changed / summary / commit / persistence`。
- `tests/test_phase4c.py`（新增）：20 个测试覆盖用户指定清单 + 附加项。

## 4. 结论

**PASS** — Phase 4-C 最小 scope 完成：Context Projection + Compaction 闭环
（Event Log → Surface → TokenMeter → ContextPressure → CompactionEngine →
Replacement Events → Surface rebuild → derive_messages → Retry）成立，
且 Phase 1 / Phase 2 / Phase 4-A / Phase 4-B 全部保持 PASS。

PASS 不代表已证明完整 DSH context-engine 语义；未决边界全部记录在
23-phase4c-assumptions.md（A1–A13）。按阶段指令，完成后停止，不进入
Phase 4-D。
