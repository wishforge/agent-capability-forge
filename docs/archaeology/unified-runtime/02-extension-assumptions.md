# 02 — Phase 5-F Extension Assumptions

> 依据：Phase 5-E Contract v1 §13/§14/§15 的扩展点占位。每项标注
> VERIFIED / PARTIAL / UNKNOWN / DESIGN PROPOSAL，与 03-report 交叉引用。

| # | Assumption | 状态 | 证据 |
| --- | --- | --- | --- |
| A1 | Attempt lifecycle：每次 model/backend stream 调用 = 一个 attempt；同一 Execution 可有 1..N attempts；状态 RUNNING / SUCCEEDED / FAILED / ABORTED | VERIFIED | `runtime.py` `_start_attempt/_end_attempt`；`execution/attempt/start|end` 事件；golden 测试 A1 FAILED → A2 SUCCEEDED |
| A2 | Attempt persistence：attempt 以 trace 事件持久化进 EventStore JSONL；不改变 surface | VERIFIED | `events.py` 新增两个事件；EventStore payload 原样序列化；`test_replay_preserves_attempt_identity` |
| A3 | Backend event id stability：AgentScope reply_id/block_id/tool_call_id 稳定；Codex rollout 行号+type+call_id 稳定（fixture 级） | VERIFIED（两 backend）/ UNKNOWN（其它 backend） | `agentscope.event` 源码字段；`codex.py` `_ref`；fixture 测试 |
| A4 | Synthetic event references：adapter 构造的边界（Codex Step）标 `quality=SYNTHETIC`；真实 raw item 标 EXACT；无稳定 id 时可回落为 file offset/sequence | VERIFIED | `codex.py` `_Segment.metadata`（SYNTHETIC）；call/output ref（EXACT）；AgentScope `_ref`（EXACT） |
| A5 | Lossiness semantics：mapping_quality + missing_semantics + backend_event_ref 可见、可审计、replay 后不消失 | VERIFIED | `BackendMetadata`；turn/start + attempt/end 持久化 metadata；Codex 六项、AgentScope 三项缺失清单 |
| A6 | Replay behavior：replay 重建 Execution → Attempt 树，identity（execution_id/attempt_id/attempt_number）不重编号；runtime Execution 对象本身不重建（Contract v1 §3） | VERIFIED | `recovery.py` `ReplayExecution/ReplayAttempt`；replay 测试 |
| A7 | Tool side-effect retry boundary：同 Execution 重试前必须 `retry_safe`；已有 side effect 时禁止新 attempt，标 `ABORTED / UNSAFE_RETRY_BLOCKED`；compensation 是 future capability | VERIFIED（当前 runtime 语义） | `compaction.retry_safe`；`runtime.py` decision 分支；`test_tool_side_effect_blocks_unsafe_retry` |
| A8 | Backend metadata immutability：extension 容器 frozen；metadata 只 observe/audit/debug/replay reference，core 不读取它决定 Session/Turn/Step/Ownership/Causality | VERIFIED | `extensions.py` frozen dataclasses；append-only；`test_core_never_reads_backend_metadata`（core 文件 0 backend 名字） |

## 显式保留的 DESIGN PROPOSAL / UNKNOWN

- **Codex 跨 Step compaction retry 链接**：`parent_execution_id` 字段已
  冻结在 `ExecutionAttempt`，runtime 同 Execution 重试（AgentScope/DSH 路径）
  已用 `parent_execution_id = execution_id` 表达；Codex “新 sampling request =
  新 Step”的 compaction retry fixture 不存在，因此跨 Execution 链接尚未被
  Codex fixture 直接覆盖（DESIGN PROPOSAL）。
- **通用 backend error retry policy**：除 compaction overflow 外，runtime
  不新增重试策略；若 adapter 未来允许 timeout/transient retry，attempt 事件
  已能表达 A N FAILED → A N+1（DESIGN PROPOSAL）。
- **AgentScope 事件 id 在非 2.0.2 版本的稳定性**：UNKNOWN，升级前重核。
