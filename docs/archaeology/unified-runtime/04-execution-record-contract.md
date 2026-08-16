# 04 — Execution Record Contract（Phase 5-G）

> 阶段：Phase 5-G。只冻结 ExecutionRecord 语义，不实现 Evaluation Engine /
> Judge / Scoring；不修改已有 Runtime semantics。
> 输入证据：Phase 5-E Contract v1（`unified-agent-runtime-core-contract-v1.md`
> §3/§4/§5/§13/§14/§15）、Phase 5-F（`01-extension-audit.md` /
> `02-extension-assumptions.md` / `03-extension-report.md` +
> `runtime/extensions.py` / `runtime/recovery.py`）、Codex 07-10/27、
> DSH 07/08/10/11/17/20/24/26。
> 状态词：CORE / EXTENSION / BACKEND-SPECIFIC；EXACT / ADAPTER / LOSSY /
> BACKEND_SPECIFIC / PARTIAL / UNKNOWN / REQUIRED EXTENSION。

---

## 1. 定位

ExecutionRecord 是 EventStore 的 **evaluation-facing 投影**：

```text
Event Log（source of truth）
    ↓ 只读纯投影
ExecutionRecord（immutable）
    ↓ 只读
Evaluation
```

约束：

1. **不是第二 source of truth**：ExecutionRecord 是派生视图；一切权威事实仍
   在 Event Log。record 与 log 不一致时以 log 为准。
2. **不可变**：record 一旦生成即为 frozen；任何字段不随时间变化。
3. **不反向修改 Runtime**：record 不写回 EventStore / Session / Step /
   Capability / Tool ownership / Causality / attempt identity。
4. **不复制 raw event**：只保存事件引用（seq）与 backend 引用
   （`BackendEventRef`），不复制 backend raw event 本体。

---

## 2. 派生规则

```text
same log + same projection rules + same record version
    ⇒ same semantic ExecutionRecord
```

- 投影规则必须有版本：`record_version` + `projection_rule_version`，随
  ExecutionRecord 一起冻结；规则变更 = 新版本 record，不修改旧 record。
- record 由 log 可完全重建；重建不执行模型、不执行工具
  （Phase 5-E §10 REPLAY-01；runtime recovery.py replay）。
- Runtime 不消费 ExecutionRecord 做任何执行决策；EventStore 不依赖 record。

---

## 3. 逻辑层次

```text
Execution
  ↓
Attempts
  ↓
Steps
  ↓
Events
  ↓
Tools
  ↓
Backend References
  ↓
Outcome
```

允许附加（不改变上述主干）：

```text
Ownership
Causality
Context provenance
Replay reference
Lossiness
```

层次语义与 Phase 5-E §3/§4 一致：Step 是持久化边界，Execution 是该边界的
运行时实例；ExecutionAttempt 附着于 Execution，不改变 Turn/Step 语义。

---

## 4. 最小字段语义（不是 schema）

只冻结语义；不实现具体 schema。字段来源 = Evaluation 取得该事实的权威渠道。

| 字段 | 语义 | 来源 | 当前状态 |
| --- | --- | --- | --- |
| `execution_id` | 一次逻辑执行的 durable identity；replay 不改变 | `execution/attempt/start|end` payload；当前 Python runtime 以 step_id 为 execution_id | VERIFIED（5-F A1/A6） |
| `session_id` / `turn_id` / `step_id` | 执行边界归属 | 统一事件字段 | VERIFIED |
| `attempts[]` | 1..N 次尝试；attempt_number 连续；parent_execution_id 表达 retry 链接 | attempt 事件 + replay `ReplayAttempt` | VERIFIED（5-F 03 §2.2/2.4） |
| `event_refs[]` | record 中每条事实指向 Event Log 的 seq；tool/result→tool/call 用 `source_event_seqs` | 统一事件 | VERIFIED |
| `tool_calls[]` / `tool_results[]` | 工具证据（见 §8） | `tool/call` / `tool/result` 事件 | VERIFIED（部分字段 PARTIAL） |
| `outcome` | 三层分离的执行结果（见 §5） | turn/end reason + attempt status + tool is_error 派生 | VERIFIED 语义；字段值按证据派生 |
| `initiator_ref` | 谁导致执行；只允许 durable reference | 当前：ambient initiator 不持久化；durable surrogate = header lineage + source_event_seqs | PARTIAL / REQUIRED EXTENSION |
| `causality_refs` | parent / root / source event 引用 | `source_event_seqs`、attempt `parent_execution_id`、call tree `root_call_id/parent_call_id` | VERIFIED（durable 部分） |
| `ownership_refs` | 该执行消耗/使用了谁拥有的 Capability | 当前：`ToolRegistration.owner` / Capability→Scope→Effect 仅在 runtime，不落事件；Codex 为 BACKEND-SPECIFIC | PARTIAL / REQUIRED EXTENSION |
| `backend_refs[]` | 每个统一事实可回源 backend raw event | `BackendEventRef`（backend / event_id / event_type / reference / quality） | VERIFIED（5-F 03 §2.5） |
| `mapping_metadata` | adapter 级映射/lossiness 容器 | `BackendMetadata`；TURN_START / attempt/end / tool 事件持久化 | VERIFIED |
| `context_provenance` | 哪些 events / surface nodes 形成 request-time context | 见 §7 | PARTIAL / REQUIRED EXTENSION |
| `replay_ref` | 指向源 log（session + event 范围 + record/projection 版本），供 Evaluation 请求 Replay | 派生 | VERIFIED |
| `timestamps` | 事件时间 / attempt start-end | 统一事件 + attempt payload | VERIFIED |
| `cost` / `usage` | token / duration / cost | 统一事件目前无 usage 事件；Codex rollout 有 token_count / duration_ms（raw）；AgentScope 部分 backend 事件有 usage | UNKNOWN（除非 backend ref 提供可靠来源；否则标 UNKNOWN，不伪造） |

---

## 5. Outcome 语义

**Execution Outcome ≠ Step Outcome ≠ Turn Outcome**；三者不得混成一个 status。

```text
Tool failure   ≠ Step failure   ≠ Turn failure
```

- Tool outcome：来自 `tool/result` 的 `is_error` + `error_code`；
- Attempt outcome：来自 `execution/attempt/end` 的 `status`
  （RUNNING / SUCCEEDED / FAILED / ABORTED）；
- Step outcome：由 attempt、tool、model error 事实派生；无独立 step failure
  事件（Phase 5-E §4；17 §9）→ 证据不足时标 UNKNOWN；
- Turn outcome：来自 `turn/end` reason 六值（completed / max-tokens / error /
  aborted / blocked / interrupted）；
- Execution outcome：由 attempts + steps + turn 派生。

统一枚举只冻结语义，不发明状态：

```text
SUCCESS / PARTIAL / FAILED / ABORTED / UNKNOWN
```

规则：现有 runtime 证据不足以支持某个值时，只标 `UNKNOWN`，不得猜测
SUCCESS/FAILED。`任务结束 ≠ 任务成功`。

---

## 6. Evaluation 不可变边界

Evaluation 对 ExecutionRecord / EventStore / Runtime 全部 **READ ONLY**：

可以：

- 读取 ExecutionRecord；
- 读取 raw event reference（经 `event_refs` / `backend_refs` 回源）；
- 读取 backend metadata 与 lossiness；
- 读取 tool outputs；
- 读取 context provenance；
- 请求 Replay（只读重建，不重执行）。

不能：

- 修改 EventStore；
- 修改 Session / Step；
- 修改 Capability / Scope / Effect；
- 修改 Tool ownership；
- 修改 Causality；
- 修改 attempt identity；
- 依赖 ambient runtime ContextVar（见 §9）。

---

## 7. Context / Model Visibility

Evaluation 必须能区分三层：

| 层 | 定义 | 当前事实 |
| --- | --- | --- |
| Agent actually saw | request-time model context 的真实内容 | `request/header` durable surrogate 记录 model + tools；surface 可重建；system / runtime_context / current_input 不落盘 → **PARTIAL** |
| Agent could have seen | 该时刻 active surface（含 compaction replacement） | Event Log + surface 规则可重建；derive_messages determinism 为 PARTIAL/INFERENCE（Phase 5-E §11） → **PARTIAL** |
| Raw execution history | 完整 append-only 事件历史 | VERIFIED |

`context_provenance` = 哪些 events / surface nodes 形成这次 context；当前
runtime 无法精确提供完整 provenance → 标 `PARTIAL / REQUIRED EXTENSION`，
不得假设。

---

## 8. Tool Evidence

Evaluation 必须能回答“Agent 调用了什么”，至少：

```text
tool identity
call identity
arguments
result
is_error
attempt
event references
backend source reference
```

当前事实：

| 字段 | 来源 | 状态 |
| --- | --- | --- |
| call_id / name / arguments / root / parent | `tool/call` payload | VERIFIED |
| tool_call_id / content / is_error / error_code | `tool/result` payload | VERIFIED |
| result → call 配对 | `source_event_seqs`（或 Codex call_id） | VERIFIED |
| attempt 归属 | tool 事件所在 turn/step + 相邻 attempt 事件 | VERIFIED（语义层可关联） |
| backend source reference | `backend_event_ref` / `backend_metadata` | VERIFIED |
| ownership / authorization | 未持久化 | REQUIRED EXTENSION |
| concludes_turn / additional_contexts | runtime-only，不落盘 | PARTIAL（需要时扩展） |

Codex `EXEC_FAILURE_STRUCTURED_SUCCESS`：exec success 固定 true，属
LOSSY；Evaluation 不得把它当精确错误信号（Phase 5-E §15）。

---

## 9. Causality

Evaluation 需要回答“为什么这个 Tool 会发生”，只允许依赖 **durable
evidence / references**：

```text
initiator
parent
root
source event
```

- durable 层：`source_event_seqs`、attempt `parent_execution_id`、
  call tree（root/parent）、session header lineage（parent_session /
  seed_length / delegation_depth）；
- **禁止**：Evaluation 读取 ambient runtime ContextVar；
- ambient initiator 不持久化、replay 不恢复（Phase 5-E §7；17 §7）；
  Codex 无 ambient initiator（AMBIENT_INITIATOR = LOSSY）；
- 当前 Python EventStore 不持久化 session header lineage（Phase 4-B A11）
  → header 级因果关系标 `PARTIAL / REQUIRED EXTENSION`。

---

## 10. Ownership

Evaluation 需要回答“这个执行消耗/使用了谁拥有的 Capability”，所以需要
`owner reference`。但：

```text
owner ≠ initiator ≠ authorized principal
```

- 三者不得合并成一个字段，不得互相推导（Phase 5-E §6/§8）；
- 当前：`ToolRegistration.owner` 与 Capability→Scope→Effect 仅在 runtime
  registry，不进入 Event Log；replay 不恢复；
- Codex 工具贡献者 ≠ Capability，owner 为 session-scoped services，
  保留 BACKEND-SPECIFIC metadata；
- 因此 `ownership_refs` 标 `PARTIAL / REQUIRED EXTENSION`：若 Evaluation
  需要 durable owner，必须由 runtime 在 tool/call 或 attempt 事件写入
  owner reference。

---

## 11. Lossiness

`BackendMetadata` 冻结为 Evaluation 可见容器：

```text
backend
mapping_quality   # EXACT | ADAPTER | LOSSY | BACKEND_SPECIFIC | UNKNOWN
missing_semantics # 可枚举缺失清单
backend_event_ref # 可回源
```

原则（Phase 5-E §15）：

1. **Lossiness visible**：未映射项必须出现，禁止静默丢失；
2. **Lossiness auditable**：可经 raw ref 回源；
3. **Lossiness replay-aware**：replay 后 metadata 与缺失清单不消失。

当前清单：Codex 六项、AgentScope 三项（Phase 5-E §15；5-F 02 A5）。
**LOSSY 不得被 Evaluation 当成 EXACT**；跨 record 比较必须携带
mapping_quality，否则比较结果是假精度。

---

## 12. Replay

冻结：

```text
same execution
    ↓ replay（不重执行模型/工具）
same semantic record
```

要求：

1. Execution identity（execution_id / attempt_id / attempt_number）不随
   replay 改变（5-F 03 §2.4）；
2. semantic record（attempts / steps / tools / outcome / lossiness /
   causality refs）可重建；
3. backend-specific raw representation 允许不同（例如 raw ref 的 file
   offset 在恢复后可重新解析），但必须保持可回源；
4. ambient initiator / capability effects 不随 replay 恢复，record 中相应
   字段保持 PARTIAL/UNKNOWN；
5. record 必须携带 `replay_ref`（源 log 范围 + record/projection 版本），
   使 Evaluation 可请求相同语义的 replay。

---

## 13. AgentScope / Codex 交叉对比

| 字段 | AgentScope | Codex | 可跨 backend 复用 |
| --- | --- | --- | --- |
| execution_id / attempt | ADAPTER（one reply = one Step；同 Step retry） | ADAPTER（sampling request = Step；跨 Step 用 parent_execution_id） | 语义一致；形态 ADAPTER |
| tool identity / arguments | ADAPTER（缓冲翻译） | call_id EXACT；step 归属 LOSSY | 可复用 |
| tool is_error | ADAPTER（state 校验） | LOSSY（EXEC_FAILURE_STRUCTURED_SUCCESS） | 需带质量标记 |
| backend ref | EXACT | EXACT / SYNTHETIC | 可复用 |
| lossiness | 三项缺失清单 | 六项缺失清单 | 容器可复用；清单 backend-specific |
| initiator | ADAPTER（unified overlay） | LOSSY（MISSING） | 不可等同 |
| ownership | ADAPTER（Toolkit 可见性） | BACKEND_SPECIFIC | 不可等同 |
| context provenance | PARTIAL | PARTIAL | 语义相同，精度均不足 |
| usage/cost | UNKNOWN（统一层） | raw 可用，统一层 UNKNOWN | 只允许引用 |

结论：统一 Evaluation 逻辑可跨 backend 复用 **语义层**；backend-specific /
LOSSY 字段必须带标记消费。

---

## 14. 验收（04 部分）

| # | 标准 | 结果 |
| --- | --- | --- |
| 1 | ExecutionRecord 不成为第二 source of truth | PASS（纯投影 + 不可变 + 无写回） |
| 2 | Evaluation 与 Runtime read-only 分离 | PASS（边界冻结） |
| 3 | ExecutionAttempt 能进入 Evaluation | PASS（attempt 事件 + replay 重建） |
| 4 | Tool evidence 可追溯 | PASS（call/result + source_event_seqs + backend ref） |
| 5 | Causality 不依赖 ambient runtime | PASS（契约只允许 durable refs；initiator 数据本身 PARTIAL） |
| 6 | Ownership 与 Causality 分离 | PASS（owner ≠ initiator ≠ principal；owner_ref REQUIRED EXTENSION） |
| 7 | Lossiness 对 Evaluation 可见 | PASS（BackendMetadata 持久化 + replay-aware） |
| 8 | Replay 能重建 semantic record | PASS（identity 稳定；raw representation 可不同） |
| 9 | AgentScope/Codex 都可以产生 Evaluation input | PASS（两 backend 事件序列一致；差异显式标记） |
| 10 | 无需修改 Core execution semantics | PASS（本文件只定义投影契约） |
