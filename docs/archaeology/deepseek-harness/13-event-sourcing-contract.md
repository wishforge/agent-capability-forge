# 13 — DSH Event-Sourcing Semantic Contract

> 基线：deepseek-ai/deepseek-harness @ `47f943859bef60e4160492346772ded9b24f765a`（2026-08-13）
> 证据来源：02 / 05 / 10 / 99 / verification-01（本阶段不重新考古，不重复搜索已证明语义）
> 状态词：VERIFIED / PARTIAL / NOT FOUND / CONFLICTING / INFERENCE
> 本文件是冻结契约：已有考古证据 → 转成 contract；无证据的语义 → 标 UNKNOWN，禁止写成 VERIFIED。

---

## 0. Coverage Matrix

| # | Semantic | Evidence | Status | Confidence |
| --- | --- | --- | --- | --- |
| 1 | SessionEvent log append-only 且为执行权威 | 02 §1-2；99 §3 | VERIFIED | High |
| 2 | Surface 是投影 | 02 §3（`surface.ts:85` 明确 boundaries/chunks/usage/errors 是 trace/replay data，不是 history） | VERIFIED | High |
| 3 | 模型可见消息可从持久化历史重建 | 02 §2-3；10 §2（resume/fork/seed 重放） | VERIFIED（日志级） | High |
| 4 | deriveMessages 确定性 | 02 §3（`index.ts:726-749` 有序纯投影）；无显式确定性保证/测试 | INFERENCE | Medium |
| 5 | assistant/message、tool/result 保留 lineage | 02 §2（`types.ts:270-290` sourceEventSeqs） | VERIFIED | High |
| 6 | 事件日志不截断、无物理删除 | 02 §2,4 | VERIFIED | High |
| 7 | replace 是新事件，保留 sourceEventSeqs | 02 §4（`types.ts:211-219` surfaceOp replace） | VERIFIED | High |
| 8 | compaction = projection replacement | 02 §4,6；99 §6 | VERIFIED | High |
| 9 | tool-result pruning 同一范式 | 02 §4 | VERIFIED | High |
| 10 | compaction 事务标记 + 失败分类 | 02 §6（`compaction/src/index.ts:28-49,96-108`） | VERIFIED | High |
| 11 | checkpoint 在副作用前落盘、fail-closed | 05 §1（`session-checkpoint-policy/src/index.ts:75-106`） | VERIFIED | High |
| 12 | 崩溃尾部合成修复事件 | 05 §1（`repair.ts:31-134`） | VERIFIED | High |
| 13 | flush == fsync | 05 未提供证据 | NOT FOUND | — |
| 14 | 事件级 replay 可恢复 | 10 §2 | VERIFIED | High |
| 15 | 无产品级 Trajectory 对象 | 99 §6；10 §2 | VERIFIED | High |
| 16 | replay ≠ 任务质量评估 | 10 §2；99 §7 | VERIFIED | High |
| 17 | Turn/Step 边界事件可见 | 02 §2（`types.ts:126-315`）；99 §2 | VERIFIED | High |
| 18 | session clear 默认路径完整语义 | 02 §4（仅 `SessionStartSource` 含 `'clear'`） | PARTIAL | Low |
| 19 | fork 复制数据 vs 引用 | 10 §2（只确认 fork 入口，无机制描述） | NOT FOUND | — |
| 20 | 多 backend 持久化顺序严格一致 | 未覆盖 | NOT FOUND | — |
| 21 | compaction 全边缘场景原子性 | 02 §6（有失败分类，无原子性证明） | PARTIAL | Low |

无 CONFLICTING 项：verification-01 复核未发现冲突。

---

## 1. Purpose

把已有 DSH Event Sourcing 考古结果冻结为 Python 下一阶段的语义契约：

- 明确哪些语义已 VERIFIED、哪些是 INFERENCE、哪些仍 UNKNOWN；
- 明确 DELETE / REPLACE / MASK / PROJECTION 的边界，不混用；
- 建立 Capability Runtime（lifecycle truth）与 DSH Event Store（execution truth）的概念边界；
- 只产出 contract，不实现任何对象。

---

## 2. Source of Truth

**ES-01 — Persisted SessionEvent history is the source of truth.**

Status: **VERIFIED**（High）

证据：02 §1-2 内存权威 `Session.log`（`SessionEvent[]`）+ 持久化插件（JSONL/SQLite）订阅 `session/event` 落盘；99 §3 明确 "State = SessionEvent 日志 + 持久化后端"；10 §2 事件级 replay 完整。原始路径：`packages/core/session/src/index.ts`、`packages/session/session-persistence-jsonl`、`session-persistence-sqlite`。

**ES-02 — Surface is a projection.**

Status: **VERIFIED**（High）

证据：02 §3 — `core/session/src/surface.ts:85` 明确 "turn/step boundaries, chunks, usage, errors are trace/replay data, not history"；`deriveMessages()` 按 surface 节点顺序派生，surface 由 log 派生，不是独立权威存储。

**ES-03 — Model-visible messages are reconstructable from persisted history.**

Status: **VERIFIED**（日志级，High）；精确重启重建路径 PARTIAL（见 §12-8）

证据：02 §2-3 — `assistant/chunk`、`assistant/message`、`tool/call`、`tool/result`、`request/header` 全部持久化；10 §2 — resume/fork/seed 可从事件日志重放；`assistant/message.sourceEventSeqs` 指向 chunk、`tool/result.sourceEventSeqs` 指向 call。

**ES-04 — deriveMessages is deterministic given the same source history and projection rules.**

Status: **PARTIAL（实现级 INFERENCE）**（Medium）

证据：02 §3 — 实现是有序遍历 surface 的纯投影（`core/session/src/index.ts:726-749`）。没有显式 determinism 保证、没有测试证明跨版本/跨输入确定性。契约按 "same log + same projection rules ⇒ same messages" 接受，但作为 INFERENCE 而不是 VERIFIED。

**ES-05 — assistant/message and tool/result preserve source event lineage.**

Status: **VERIFIED**（High）

证据：02 §2 — `assistant/message` 记录 `sourceEventSeqs` 指向其 `assistant/chunk`；`tool/result` 记录 `sourceEventSeqs` 指向 `tool/call`（`types.ts:270-290`）。替换事件同样保留被替换节点（§6）。

---

## 3. Event Model

### 3.1 已确认事件类型（VERIFIED，02 §2 / `types.ts:126-315`）

| 类别 | 事件 | 契约角色 |
| --- | --- | --- |
| 边界 | `turn/start`、`turn/end`、`step/start`、`step/end` | Turn/Step 边界；trace/replay data，不属于模型历史 |
| 用户 | `user/message` | 模型可见 |
| 模型 | `assistant/chunk`、`assistant/message` | chunk 是原始流块（不可直接进入历史）；message 是模型可见节点，lineage 指向 chunks |
| 工具 | `tool/call`、`tool/result` | call/result 成对；result lineage 指向 call；result 模型可见 |
| 请求 | `request/header`、`request/context` | header 重建 provider/model/system/tools/config；context 记录 contextWindow |
| 替换 | `compaction/summary`、`compaction/prune` | 阴影事件 + `surfaceOp: replace` |
| 种子 | `session/end-seed` | seed 边界（继承历史 vs 本次运行） |
| 重试 | `llm/retry`、`llm/retry-started` | 模型重试事件持久化（05 §1） |

### 3.2 Append-only / Replacement Semantics（VERIFIED）

- Event log **append-only**：02 §2/§4，日志本身不截断。
- **replace 是新事件**：`surfaceOp: {op:'replace'}` 追加进日志；原事件不物理删除（02 §4，`types.ts:211-219`）。
- **sourceEventSeqs 保留**：被替换节点、chunk→message、call→result 的 lineage 均保留。
- **compaction 是 projection replacement**：改的是 surface，不是 log。
- **tool-result pruning 同一范式**：超长工具结果替换为保留首尾的剪枝版，记录 `compaction/prune`。

### 3.3 四词严格区分

| 词 | 定义 | DSH 现状 |
| --- | --- | --- |
| DELETE | 物理删除或墓碑删除源事件 | NOT FOUND：无物理删除、无 tombstone 语义证据 |
| REPLACE | 追加新事件并让投影指向新节点，源事件保留 | VERIFIED：`surfaceOp.replace` + `compaction/summary`、`compaction/prune` |
| MASK | 事件级隐藏/打码语义 | NOT FOUND：spill 的长文本外置是内容存储策略（locator 引用），不是事件级 mask，不归入本词 |
| PROJECTION | 从 log 派生的视图；投影规则变化不影响 log | VERIFIED：surface 即投影；compaction/prune 是投影变化 |

---

## 4. Surface Projection

- Surface 是 log 的**有序投影**，是 `deriveMessages` 的输入（02 §3）。
- Surface 明确**排除** turn/step boundaries、chunks、usage、errors —— 这些是 trace/replay data，不是模型历史（`surface.ts:85`）。
- Surface 不是第二 source of truth；它是可重建的派生视图。
- Surface 只能通过**追加 replacement 事件**改变；不能原地编辑。

---

## 5. deriveMessages

- 角色：**纯投影函数** —— 按 surface 节点顺序把 `user/message`、`assistant/message`、`tool/result` 派生为模型消息（02 §3，`index.ts:726-749`）。
- 请求头（provider/model/system/tools/config）由 `request/header` 重建（02 §3，`agent.ts:441-453`）—— 属于请求组装，不是历史派生。
- 本轮 runtime-context 快照与用户输入由 agent loop 追加（02 §1），不属于 deriveMessages。
- Determinism：实现级 INFERENCE（见 ES-04），契约要求 same log + same projection rules ⇒ same messages。

---

## 6. Replacement / Compaction

**COMP-01 — Compaction does not truncate source event history.**

Status: **VERIFIED**（High）。证据：02 §4 — 日志只追加 replacement 事件；"事件日志本身不截断"。

**COMP-02 — Compaction changes future model-visible surface.**

Status: **VERIFIED**（High）。证据：02 §3/§4 — 模型历史由 surface 派生，summary/prune 替换 surface 节点后，后续 deriveMessages 输出改变。

**COMP-03 — Compaction writes explicit transactional events.**

Status: **VERIFIED**（标记级，High）；原子性边界 UNKNOWN。
证据：02 §6 — `compaction/start…end` 事务标记（`compaction/src/index.ts:96-108`）。"事务"指显式 start/end 事件对；跨 backend 崩溃时的原子性无证据（见 §12-5）。

**COMP-04 — Compaction failure has explicit categories.**

Status: **VERIFIED**（High）。证据：02 §6 — `busy / cancelled / changed / summary / commit / persistence`（`compaction/src/index.ts:28-49`）。

### Compaction 触发契约（VERIFIED，02 §6）

1. `agent/pre-step` 压力触发：`thresholdRatio` / `retainRatio` / `retainTokens`；
2. `agent/request-error` 且 failure.code == `CONTEXT_WINDOW_EXCEEDED_CODE`：先压缩，surface 前进则返回 `{kind:'retry'}`，受 `maxOverflowRetries` 限制（05 §1）。

Tool-result pruner 遵循同一范式：替换超长结果 + `compaction/prune` 阴影事件。

---

## 7. Checkpoint

| 阶段 | 语义 | 状态 |
| --- | --- | --- |
| event appended | 事件已追加到内存 `Session.log` | VERIFIED |
| event persisted | persistence 插件收到 `session/event` 并落盘 | VERIFIED（JSONL/SQLite 订阅） |
| flush completed | 落盘完成即对应用可恢复 | PARTIAL：无 fsync 证据；**不假定 flush == fsync** |
| durable checkpoint | checkpoint 在模型/工具副作用前写入；失败则 fail-closed，不调用模型/工具 | VERIFIED（`session-checkpoint-policy/src/index.ts:75-106`） |
| crash recovery boundary | 重启/resume 时修复未闭合尾部（`repair.ts:31-134`） | VERIFIED |

契约要求：**除非补上源码证据，Python 实现不得声明 "flush 即 durable"**。

---

## 8. Crash Recovery

- 崩溃尾部修复：`interruptedTurnClosers()` 合成 `tool/result` + `step/end` + `turn/end{interrupted}` 事件（05 §1，`repair.ts:31-134`）。修复是**追加合成事件**，不重写历史。
- 两个不确定性标记（VERIFIED 存在性；判定边界 PARTIAL）：

| 状态 | 含义 | 不确定性 |
| --- | --- | --- |
| `TOOL_NOT_STARTED` | `tool/call` 已记录，但没有证据表明执行开始 | 低（副作用大概率未发生），但 crash window 使"绝对未发生"无法证明 |
| `TOOL_OUTCOME_UNKNOWN` | 执行可能已开始/已产生副作用，但结果丢失 | 高；模型被提示只对只读/幂等操作重试（05 §1，PARTIAL） |

- 二者必须存在的原因：crash 后工具副作用边界不可知，模型需要区分"可安全重试"与"仅可只读/幂等重试"，防止重复副作用。

---

## 9. Fork / Resume / Replay

**REPLAY-01 — History can be replayed from event history.**

Status: **VERIFIED**。证据：10 §2 — `SessionStore.create({seed})` / `ctx.agents.resume`（`core/session/src/index.ts:422,478`）；`session-query` 只读重放（`session-query/src/index.ts:139-145`）；`llm-replay` 流快照重放（`test-support/llm-replay/src/index.ts:194-266`）。

**REPLAY-02 — Fork preserves lineage.**

Status: **VERIFIED**（seed 边界 + sourceEventSeqs）。证据：02 §4 — `seedLength` / `session/end-seed` 区分继承历史与本次运行；§2 sourceEventSeqs 保留事件 lineage。fork 是复制数据还是引用：UNKNOWN（见 §12-3）。

**REPLAY-03 — Replay does not require a separate product-level Trajectory object.**

Status: **VERIFIED**。证据：99 §6 / 10 §2 — 无产品级 Trajectory；UI trajectory 是展示层，`llm-replay` 是开发者测试工具。

**REPLAY-04 — Event replay != task-quality evaluation.**

Status: **VERIFIED**。证据：10 §2 — `llm-replay` 只验证模型流快照，不评估任务结果；99 §7 — 无自动 evaluator。Replay 可作为 evaluation 的输入，但 replay 本身不产生质量判断。

---

## 10. Turn / Step

**TURN-01 — Turn/Step boundaries are event-visible.**

Status: **VERIFIED**。`turn/start`、`turn/end`、`step/start`、`step/end` 是持久化事件（`types.ts:126-315`）；边界属于 trace/replay data，不进入模型历史（`surface.ts:85`）。

**TURN-02 — A Step corresponds to one model request and associated tool activity.**

Status: **VERIFIED**。证据：99 §2 / 02 §1 — step = `buildRequest` → 一次模型流 → tool calls/results → `step/end`；重试在同一 step 重新 buildRequest（05 §1）。

**TURN-03 — A Turn may contain multiple Steps.**

Status: **VERIFIED**。证据：99 §2 — `tool/result` → `additionalContexts` → next-step inbox → 下一 step（`agent.ts:395-399`）。

最小语义：

```text
Turn ─ 0..N Step
  Turn/start ─ Step/start ─ 1 model request ─ assistant stream ─ tool call/result* ─ Step/end ─ ... ─ Turn/end{reason}
```

---

## 11. Semantic Invariants

| # | Invariant | 状态 |
| --- | --- | --- |
| I-01 | 事件日志 append-only：无原地修改、无物理删除 | VERIFIED |
| I-02 | 模型可见历史是 (log + projection rules) 的函数 | PARTIAL（deriveMessages determinism 为 INFERENCE） |
| I-03 | lineage 保留：chunk→message、call→result、替换→被替换节点（sourceEventSeqs） | VERIFIED |
| I-04 | 替换只追加新事件，原事件不可变 | VERIFIED |
| I-05 | compaction/prune 只改变投影（surface），不改变 log | VERIFIED |
| I-06 | crash 修复只追加合成闭合事件，不重写历史 | VERIFIED |
| I-07 | replay 不需要产品级 Trajectory 对象 | VERIFIED |
| I-08 | Turn/Step 边界事件可见；边界不是模型历史 | VERIFIED |
| I-09 | Replay ≠ Evaluation | VERIFIED |

---

## 12. Known Unknowns

| # | 未知项 | 当前证据 | 状态 |
| --- | --- | --- | --- |
| 1 | session clear 默认路径完整语义 | 仅 `SessionStartSource` 含 `'clear'`（`runtime-types.ts:92`），未追到默认运行路径 | UNKNOWN（PARTIAL） |
| 2 | flush 的精确 durability boundary | 无 fsync 证据；flush ≠ fsync | UNKNOWN |
| 3 | fork 复制 event data 还是 reference | 只有 fork 入口（`index.ts:478`） | UNKNOWN |
| 4 | replay 的 deterministic 边界 | 事件级快照可重放；模型/工具重跑、跨版本确定性无证据 | UNKNOWN（PARTIAL） |
| 5 | compaction 所有边缘错误场景中的原子性 | 有失败分类，无事务原子性证明 | UNKNOWN |
| 6 | persistent event ordering 在全部 backend 下严格一致 | JSONL/SQLite 各自落盘，无跨 backend 顺序一致性证据 | UNKNOWN |
| 7 | deriveMessages 形式化确定性 | 纯投影实现（INFERENCE），无测试/保证 | UNKNOWN（PARTIAL） |
| 8 | resume 时 persisted log → surface 重建的精确路径 | resume 已确认，重建机制未展开 | UNKNOWN（PARTIAL） |
| 9 | checkpoint 自身 durability（fsync/介质） | checkpoint 存在且 fail-closed，durability 未证明 | UNKNOWN |
| 10 | TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN 的精确判定边界 | 状态存在（VERIFIED），如何判定 started/unknown 未展开 | UNKNOWN（PARTIAL） |
| 11 | compaction 失败分类后的各分支恢复状态 | 分类 VERIFIED，busy/cancelled/changed 分支语义未展开 | UNKNOWN（PARTIAL） |

---

## 13. Python Implementation Requirements

### 13.1 下一阶段最少对象（契约级，不实现）

1. **EventStore** — append-only SessionEvent 日志 + 持久化 adapter；禁止 delete/update；保留 sourceEventSeqs。
2. **SessionEvent schema** — turn/step 边界、user/assistant/tool/request 事件、replacement 事件、seed 边界。
3. **Surface** — 有序投影；明确排除 trace/replay data（boundaries/chunks/usage/errors）。
4. **deriveMessages** — 纯投影：surface → 模型消息；request/header → 请求头重建。
5. **CompactionEngine** — pressure + context-overflow 触发；追加 replacement 事件；失败分类 busy/cancelled/changed/summary/commit/persistence；tool-result pruner 同范式。
6. **Checkpoint / Repair** — 副作用前 checkpoint（fail-closed）；崩溃尾部合成 `tool/result` + `step/end` + `turn/end{interrupted}`；`TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN`。
7. **Resume / Fork / Seed** — replay 入口，lineage 保留。
8. **Turn/Step runner** — 一个 step = 一次模型请求 + 关联工具活动；turn 可含 N steps。

明确不需要：产品级 Trajectory 对象、evaluator、capability lifecycle 合并。

### 13.2 与 Capability Runtime 的概念边界

```text
Capability Runtime = lifecycle truth
    (capability install / dispose / tool registration / worker start)

DSH Event Store = execution truth
    (user/message, assistant/message, tool/call, tool/result, request/header)
```

本契约只冻结 **execution truth**。两者不得强行合并；lifecycle 事件不进入 SessionEvent，除非出现模型可见需求（见 open questions）。

### 13.3 Open Questions

1. Capability lifecycle 事件是否进入 SessionEvent？——初始立场：不进入；保持独立 audit 记录，直到出现模型可见需求。
2. 哪些 lifecycle 事件对模型可见？——默认 audit-only；tool registration 变化若影响工具 schema，可能经 `request/header` 可见（INFERENCE，无直接证据）。
3. 哪些只能 audit？——install / dispose / worker start 默认 audit-only。
4. Capability generation 是否写入 request/context？——DSH 中 `request/header` 快照 system/tools/config；若 generation 改变工具集，会被该快照捕获（INFERENCE，无直接证据）。
5. Capability state 是否需要在 replay 中恢复？——replay 只恢复事件历史；capability state 属 runtime，需单独恢复机制（OPEN）。

---

## 14. Final Verdict

1. **DSH Event Log 是否已被充分证明为 source of truth？** 是（执行层 VERIFIED）：append-only SessionEvent 日志 + 持久化 + resume/fork/replay。但 durability（fsync）、跨 backend ordering 仍 UNKNOWN，故是"执行语义充分、持久化边界未满"。
2. **Model-visible ≡ Logged 是否达到 VERIFIED？** 否（PARTIAL）。模型可见 = log → surface → deriveMessages 已 VERIFIED；但严格等价依赖 deriveMessages 确定性（INFERENCE）和重启重建路径（PARTIAL），不能宣称 VERIFIED。
3. **Surface 的准确角色？** 有序投影（VERIFIED）：log 与模型历史之间的派生视图，排除 trace/replay data；不是第二 source of truth；只能通过 replacement 事件改变。
4. **deriveMessages 的准确角色？** 纯投影函数：surface → 模型可见消息；请求头另由 request/header 重建。确定性是实现级 INFERENCE，非契约级 VERIFIED。
5. **Compaction 是 delete 还是 replacement/projection？** replacement + projection（VERIFIED）：追加 `surfaceOp.replace` 新事件 + 阴影事件，原事件保留、sourceEventSeqs 保留；DELETE 无证据，MASK 无证据。
6. **Checkpoint / recovery 哪些已 VERIFIED？** 副作用前 checkpoint + fail-closed（VERIFIED）；崩溃尾部合成修复（VERIFIED）；TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN 存在性（VERIFIED）；fsync / durable boundary（NOT FOUND → UNKNOWN）。
7. **Replay 与 evaluation 的边界？** replay = 从事件历史重建/重放执行流（含流快照测试）；evaluation = 任务质量判断。Replay 可喂给 evaluation，但不产生质量结论；DSH 无产品级 evaluator。
8. **Turn / Step 的最小语义？** Turn = 会话内单元（start/end + reason），含 0..N Step；Step = 一次模型请求 + 关联工具活动（start/end）；边界事件可见但非模型历史。
9. **Python 下一阶段最少对象？** EventStore、SessionEvent schema、Surface、deriveMessages、CompactionEngine、Checkpoint/Repair、Resume/Fork/Seed、Turn/Step runner。不需要 Trajectory / evaluator / capability 合并。
10. **哪些关键语义仍 UNKNOWN？** flush 精确 durability（fsync）、fork 复制 vs 引用、replay deterministic 边界、compaction 边缘原子性、跨 backend persistent ordering、session clear 默认路径；另有 deriveMessages 形式化确定性、TOOL_NOT_STARTED/OUTCOME_UNKNOWN 判定边界、checkpoint 自身 durability。

**最终状态：PARTIAL**

契约本身已冻结且与 02/05/10/99/verification-01 一致；但 durability、determinism、ordering 等关键语义仍无源码证据。PASS 需要：补 fsync/持久化证据，或显式接受这些 UNKNOWN 为设计假设并写进 Python 实现要求。
