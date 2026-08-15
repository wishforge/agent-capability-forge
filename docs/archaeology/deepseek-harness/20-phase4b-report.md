# 20 — Phase 4-B Report: Persistence + Replay + Recovery

> 阶段结论：**PASS**（仅 Phase 4-B 最小 scope；不等于完整 DSH durability / replay / resume semantics）
> 基线：`f04559a` + Phase 4-A runtime（工作区未提交内容保持不变）
> 变更：`runtime/event_store.py` 扩展 JSONL persistence；新增 `runtime/recovery.py`；新增 `runtime/tests/test_phase4b.py`；新增 19-phase4b-assumptions.md 与本报告

## 1. 验证结果

| Suite | 结果 |
| --- | --- |
| Phase 4-A | 15/15 PASS |
| Phase 2 | 40/40 PASS |
| Phase 1 probe | `ALL INVARIANTS PASS`（14/14 checks） |
| Phase 4-B | 14/14 PASS |

## 2. 实现范围

- `EventStore(session_id, path=None)`：`path=None` 保持 Phase 4-A 内存行为；设置 path 后每个 append 写一行 UTF-8 JSON（显式 `seq / event_type / session_id / turn_id / step_id / payload / timestamp / source_event_seqs`，`sort_keys` 稳定序列化）。
- 持久化 API：`open / close / flush / read_all / read_from / repair_tail`；`append / append_many / last_seq` 兼容 Phase 4-A。
- 序列约束：append 拒绝非 0 且非 next_seq 的 seq（重复/跳号）；reload 校验 seq 从 1 连续。
- `repair_tail()`：截断到首个无效行起始，保留最长完整前缀（A3）。
- `AGENT_REQUEST` 落盘映射为 `REQUEST_HEADER`（A12）。
- `recovery.py`：`rebuild_session / replay / find_unresolved_tools / repair_interrupted_turn / resume`。
- 中断 turn 修复：合成 `tool/result`（`is_error`，`error_code=TOOL_OUTCOME_UNKNOWN`）→ `step/end` → `turn/end{reason: interrupted}`，顺序与 DSH repair 一致（15 §11）。

## 3. Crash 场景覆盖

| CASE | 场景 | 覆盖 |
| --- | --- | --- |
| CASE-01 | crash after turn/start | `test_crash_after_each_boundary`（cut=`turn/start`） |
| CASE-02 | crash after step/start | 同上（cut=`step/start`） |
| CASE-03 | crash after agent/request | 同上（cut=`agent/request`） |
| CASE-04 | crash after assistant/chunk | 同上（cut=`assistant/chunk`） |
| CASE-05 | crash after tool/call | 同上（cut=`tool/call`） |
| CASE-06 | crash before tool/result | 同上（与 CASE-05 同一日志状态） |
| CASE-07 | partial JSONL tail | `test_partial_tail_repair` |
| CASE-08 | garbled final line | `test_garbled_tail_repair` |
| CASE-09 | duplicate seq attempt | `test_duplicate_seq_rejected` |
| CASE-10 | restart after complete turn | `test_restart_after_complete_turn` |

## 4. 目标回答

1. **JSONL append-only 是否成立** — 成立（implementation contract）。每事件一行、只追加；无 update/delete 方法；reload 只读；`repair_tail` 只截断无效尾部。不声明等于 DSH durable append-only 的完整语义。
2. **sequence 是否稳定** — 稳定。append 分配 `last_seq()+1`；reopen 后 N/N+1/N+2 不变；继续 append 得 N+3；重复与跳号被拒绝（`test_sequence_continuity` / `test_duplicate_seq_rejected`）。
3. **partial tail 是否可修复** — 可修复。`open()` 加载完整前缀；`repair_tail()` 截断无效尾部、保留最后一个完整 event、恢复正常 append（`test_partial_tail_repair` / `test_garbled_tail_repair`）。策略为 A3。
4. **session 是否可重建** — 可重建。`rebuild_session()` 从 Event Log（唯一 source of truth）恢复 session_id、event sequence、turn/step 边界、tool call/result lineage、`request_header`（A12 映射）。`parent_session / delegation_depth / seed_length` 不在 Phase 4-A 事件中，只恢复默认值（A11）。
5. **surface 是否可重建** — 可重建。同一份 log：run 1 的 `derive_messages()` == restart 后 rebuild 的 `derive_messages()`（`test_rebuild_surface`）。这是 Phase 4-B implementation invariant，不是 DSH guarantee（13 ES-04 为 INFERENCE）。
6. **replay 是否成立** — 成立。`replay()` 纯投影重建 turn/step、request header、assistant message、tool call/result（含 `source_event_seqs` lineage），不重跑模型/工具（`test_replay_history`）。Replay ≠ Re-execution。
7. **tool outcome unknown 是否可识别** — 可识别。`tool/call` 无 `tool/result` → `TOOL_OUTCOME_UNKNOWN`；修复合成 `tool/result` + `step/end` + `turn/end{interrupted}`（`test_tool_call_without_result` / `test_tool_outcome_unknown_repair`）。`TOOL_NOT_STARTED` 定义但从不判定：Phase 4-A 无 execution-started marker（A4）。
8. **restart 后是否能够 resume** — 能。`resume()` 执行 reload → `repair_tail()` → 合成闭合中断 turn → `rebuild_session()` → 新 turn 继续确定性 mock 执行；未决工具不重跑（`test_resume_after_interrupted_turn` / `test_restart_after_complete_turn` / CASE-01..06）。
9. **Phase 4-A semantic contract 是否保持** — 保持。15/15 Phase 4-A tests PASS；Session → Turn → Step、Tool Waterfall、tool failure ≠ step failure ≠ turn failure、ownership ≠ causality、initiator、surface projection、event source of truth 均未改变。只扩展 `EventStore` 构造参数（`path=None` 时行为不变）并新增独立 `recovery.py`。
10. **哪些仍然只是 Phase 4-B implementation assumptions** — A1–A12（见 19-phase4b-assumptions.md）：fsync、JSONL 兼容、tail repair 策略、TOOL_OUTCOME_UNKNOWN 重建、resume 点、fork、跨 backend 顺序、事务原子性、replay 确定性边界、schema 迁移、header lineage 持久化、agent/request → request/header 映射。
11. **durability 哪些仍 UNKNOWN** — `flush == fsync` 无证据；checkpoint 自身 durability；跨 backend 持久化顺序；fork 复制 vs reference；compaction 全边缘原子性；`TOOL_NOT_STARTED` 精确判定；Python 侧 header lineage 持久化；事件 schema 迁移。**JSONL write success ≠ durable fsync**（A1）。

## 5. 结论

**PASS** — Phase 4-B 最小 scope 完成：JSONL append-only persistence、稳定 sequence、
tail repair、session/surface reconstruction、replay、`TOOL_OUTCOME_UNKNOWN` 修复、
restart/resume 均成立，且 Phase 4-A / Phase 2 / Phase 1 probe 全部保持 PASS。

PASS 不代表已证明完整 DSH durability / replay / resume semantics；
未决边界全部记录在 19-phase4b-assumptions.md（A1–A12）。

按阶段指令，完成后停止，不进入 Phase 4-C。
