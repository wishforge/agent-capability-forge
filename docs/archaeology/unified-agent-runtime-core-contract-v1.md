# Phase 5-E — Unified Agent Runtime Core Contract v1

> 阶段：Phase 5-E。唯一目标：把已经通过 AgentScope 2.0.2 与真实 pinned Codex 两个
> Backend 验证的公共语义，正式提炼为 Unified Agent Runtime Core Contract v1。
> 本阶段禁止新增 runtime code、禁止修改 runtime/EventStore/两个 adapter、
> 禁止实现 ExecutionAttempt、禁止接第三个 Backend、禁止 Evaluation /
> Regression / Promotion / UI / CLI。只冻结契约。
>
> 输入证据（已存在，不重新考古；仅当文档互相冲突时才允许回源验证）：
> - DSH：`13-event-sourcing-contract.md`、`14-turn-step-contract.md`、
>   `15-tool-waterfall-contract.md`、`16-causal-chain-contract.md`、
>   `17-semantic-runtime-model.md`、`25-phase4d-assumptions.md`、
>   `26-phase4d-report.md`
> - Capability：`python-cordis/12-capability-lifecycle.md`、
>   `python-cordis/13-capability-manager.md`
> - Codex：`20-unified-semantic-mapping.md`、`21-backend-portability-contract.md`、
>   `22-semantic-gap-decision.md`、`23-codex-adapter-boundary.md`、
>   `24-backend-neutral-assembly.md`、`25-phase5c-assumptions.md`、
>   `26-phase5c-report.md`、`27-phase5d-real-e2e.md`
> - 现有 runtime：`deepseek-harness/runtime/`（events / event_store / turn_step /
>   initiator / model_adapter / surface / tool_runtime / runtime / recovery /
>   compaction / backend/adapters/{agentscope,codex}）
>
> 状态词：CORE / CORE EXTENSION POINT / OPTIONAL EXTENSION /
> BACKEND-SPECIFIC / NOT PART OF CORE；EXACT / ADAPTER / LOSSY /
> BACKEND-SPECIFIC / MISSING / UNKNOWN。
>
> 最终状态：**PASS**（契约冻结）。PASS 只声明契约本身成立，不声明 runtime
> 实现成熟度；本契约 §19 的 open items 继续由后续阶段承载。

---

## 1. Purpose

把 AgentScope 2.0.2 与真实 pinned Codex 两个 Backend 已经验证的公共语义冻结为
Core Contract v1，并明确三层边界：

| 层 | 定义 | 是否可以因 backend 改变 |
| --- | --- | --- |
| CORE | 跨 backend 必须保持的统一语义 | 不可 |
| EXTENSION | 统一侧预留、但尚未被证据冻结为 Core 的语义承载点（schema 可扩展） | 仅以扩展点形式存在 |
| BACKEND-SPECIFIC | backend 原生语义，保留原样，只允许被翻译或暴露为 metadata | 保留 |

本契约不新增业务功能，不实现新 Runtime capability，不接第三个 Backend。

---

## 2. Core Semantic Model

一句话模型（继承 17 §0）：

```text
一次有因果归属、落在 Session/Turn/Step 边界内、穿过 Tool Waterfall、
并由 Capability Scope 提供资源所有权的执行；
其持久化真相是 append-only SessionEvent log，
模型可见性来自 Event Log -> Surface -> Model Context 的投影链。
```

Core 的六个支柱：

1. **Session**：durable execution history boundary。
2. **Turn / Step / Execution**：执行边界（持久化边界 + 运行时实例）。
3. **ToolCall / ToolResult**：工具执行语义。
4. **Capability / Scope / Effect**：资源所有权。
5. **Initiator / Lineage / Event Provenance**：因果归因（三者分离）。
6. **EventStore / Surface / ModelContext / Replay / Recovery**：持久化、投影、
   恢复机制。

Core 不包含：具体 backend 事件 schema、具体存储格式、agent loop 实现、
授权机制细节、sandbox/approval 具体策略、Evaluation/UI/CLI。

---

## 3. Core Objects

以下 18 个对象全部完成分类。分类依据：是否被两个 backend 共同验证、是否可被
统一契约独立表达、是否属于 backend 原生语义。

| 对象 | 分类 | Semantic meaning | Lifecycle | Persistence | Replay | Backend portability |
| --- | --- | --- | --- | --- | --- | --- |
| Session | CORE | durable execution history boundary：header lineage + append-only event log（13 ES-01；17 §1） | 创建后跨 turn 存活；关闭/恢复后继续；Codex 侧同一时刻最多 1 个运行 task（20 §2.1） | header + log 持久化；log 为执行权威 | 从 log 重放；header lineage 可恢复 | DSH VERIFIED；Codex ADAPTER（thread ↔ Session）；AgentScope ADAPTER（Session 由 Unified runtime 持有） |
| Turn | CORE | 会话内有界执行单元：turn/start … turn/end{reason}，0..N Step（13 TURN-01/03；14 §1） | turn 内创建/闭合；blocked 为零步 turn（14 §1）；aborted/error/interrupted 均闭合 | turn/start、turn/end 事件持久化；reason 六值（completed/max-tokens/error/aborted/blocked/interrupted） | 从事件顺序重建 turn 序列 | DSH VERIFIED；AgentScope ADAPTER（runtime 记录）；Codex ADAPTER（公开 Task ↔ Turn；内部 run_turn 为 BACKEND-SPECIFIC，20 §2.2 Q2） |
| Step | CORE | 一次模型请求 + 该请求关联的工具活动；step/start … step/end（13 TURN-02；14 §2） | 由 model request 创建；模型失败重试在同一 Step 内重新 buildRequest，不新开 Step（14 TS-02）；step/end 经 finally 闭合（15 §6） | step/start、step/end 事件持久化 | 从事件重建 Step 序列；正常/interrupted VERIFIED | DSH VERIFIED；AgentScope ADAPTER（one reply = one Step，25 A3）；Codex ADAPTER/LOSSY（无原生 Step 对象，Adapter 按 sampling request 构造，可复现，20 §2.2 Q5） |
| Execution | CORE（runtime object，非持久化实体） | 一个逻辑模型请求 + 关联工具活动的运行时执行实例；Step 是持久化边界，Execution 是该边界的运行时实例（17 §3-1） | 随 model request 创建、随 step 闭合；不独立持久化 | 不持久化为对象；可观测物是 Step 事件（16 §1-D NOT FOUND） | replay 重建事件级语义，不重建 Execution 对象 | DSH VERIFIED；AgentScope ADAPTER（ModelAdapter stream）；Codex ADAPTER（sampling request + tool dispatch，20 §2） |
| ExecutionAttempt | CORE EXTENSION POINT | retry identity 的承载位置：model retry / backend retry / compaction retry / same-step 多次 sampling request（22 §7；本契约 §13） | 未实现；只冻结扩展点 | 未冻结（扩展点 schema） | 扩展点必须 replay-aware | 两侧均 MISSING；Codex compaction retry 跨 Step 是唯一已证明需求（20 §7.1 Q9） |
| ToolCall | CORE | tool/call（trace record）+ 运行时 ToolExecution（callId/rootCallId/parent/token）（15 §1；17 §1） | tool/call 先于执行边界 append（15 TW-02）；tool/result 在 step/end 前闭合 | tool/call 持久化；agent/rootCallId/parent 仅 code-mode 部分持久化（16 §6.1） | source_event_seqs 配对重建；Codex 以 call_id 配对（20 §4.2 Q2） | DSH VERIFIED；AgentScope ADAPTER（缓冲事件翻译）；Codex ADAPTER（call_id EXACT，step 归属 LOSSY） |
| ToolResult | CORE | tool/result（message + error{name,code} + meta）+ 运行时 success/failure union；模型可见（15 §1/§9） | 工具执行后 append；tool failure ≠ step/turn failure（15 TW-06） | tool/result 持久化；value/additionalContexts/concludesTurn 不落盘（15 §1） | result→call lineage 可重建 | DSH VERIFIED；AgentScope ADAPTER（state 一致性校验）；Codex ADAPTER/LOSSY（exec success 固定 true，20 §4.3） |
| Event | CORE（统一 SessionEvent）；backend raw event 为 BACKEND EVENT | 统一事件信封是跨 backend 的 execution truth 载体；backend raw event 保留原样，经 raw_event_ref 引用（本契约 §5/§15） | append-only；无 delete/update（13 I-01） | SessionEvent 持久化；backend raw event 属 backend 存储 | 统一事件可重放；raw ref 可回源 | DSH VERIFIED；AgentScope ADAPTER；Codex ADAPTER（rollout→unified，RawResponseItem 去重，20 §3.1 Q3） |
| EventStore | CORE | append-only execution history：append / read / reconstruct / replay（13 §13.1；runtime event_store.py） | 与 Session 同生命周期；open/close/reopen/repair_tail | 具体后端 JSONL / SQLite / DB / rollout 属 storage/backend concerns（本契约 §10） | 从 log 重建；repair 保留最长合法前缀 | 契约层 backend-neutral；存储实现 BACKEND-SPECIFIC |
| Surface | CORE | log 的有序投影；deriveMessages 输入；排除 trace/replay data（13 ES-02；14 §4） | 无独立生命周期；随 log 追加 / replacement 事件变化 | 不独立持久化；可重建 | same log + same projection rules ⇒ same messages（determinism 为 PARTIAL/INFERENCE，13 ES-04） | DSH VERIFIED；AgentScope ADAPTER；Codex ADAPTER（ContextManager 是 Surface+derive 合并实现，20 §7.1 Q2） |
| ModelContext | CORE（request-time 视图，非持久化实体） | 每次模型请求的输入：system + tools + runtime context + surface 派生 messages + current input（runtime compaction.ModelContext；17 §11） | 每次请求重建；不是第二 source of truth | 不持久化；request/header 是 durable surrogate | replay 后由 surface + 规则重建 | DSH/AgentScope/Codex 均 ADAPTER（budget/token 差异为 LOSSY，20 §7.1 Q8） |
| Capability | CORE | identity + scope + dependencies + install()/dispose()；runtime 注册与生命周期（python-cordis 13 §2/§3；17 §1） | CREATED→INSTALLING→ACTIVE；ACTIVE→DISPOSING→DISPOSED；reinstall = fresh instance + fresh scope（python-cordis 12 §6/§7） | runtime registry；不落 SessionEvent（schema OPEN，13 §13.3） | 不随 replay 恢复；必须重新 install | DSH NOT FOUND（无此对象）；AgentScope ADAPTER（Toolkit 可见性）；Codex MISSING（工具贡献者 ≠ Capability，20 §10） |
| Scope | CORE | 资源生命周期边界；每个 capability 恰好一个 owner scope（python-cordis 12 CAP-01/02） | install 创建；dispose 销毁；逆序 teardown、幂等、失败继续 | runtime-only；不持久化 | 不恢复；重新 install 建立 fresh scope | DSH NOT FOUND；AgentScope ADAPTER；Codex MISSING（session-scoped services 为 BACKEND-SPECIFIC，20 §5） |
| Effect | CORE | 任意副作用登记为 owner-scoped effect；逆序 teardown / 幂等 / 失败继续（python-cordis 12 §3/§5） | install 登记；scope dispose 回收 | 不持久化（audit 可另记录） | 不恢复 | 同 Scope |
| Initiator | CORE（runtime-only causal identity；ambient 存在性为 backend capability） | 进程内当前执行身份：live agent 对象 + ALS/ContextVar；不是持久化字段（16 §1/§2） | with_initiator 包住整个 driver kick 链；without_initiator 清共享边界（16 §2） | 不持久化（16 §6.2 NOT FOUND） | 不随 replay 恢复（17 UN-11） | DSH VERIFIED；AgentScope ADAPTER（with_initiator 贯穿）；Codex MISSING（无 ambient initiator；originator 不是身份，20 §6.1 Q1）→ LOSSY |
| Lineage | CORE | 因果/血缘集合：header parentSession/seedLength/delegationDepth/origin + sourceEventSeqs + call tree（16 §3/§6） | 跨 persisted 与 runtime；随 fork/resume 单调（16 §3.1） | header + 事件级 lineage 持久化 | 事件/header 级可重建；ambient 链不可恢复 | DSH VERIFIED；AgentScope ADAPTER（header lineage）；Codex ADAPTER（forked_from_id/parent_thread_id/InterAgentCommunication，20 §6.1 Q3/Q4） |
| Replay | CORE | 从事件历史重建/重放执行流；不重新执行模型/工具；replay ≠ evaluation（13 REPLAY-01/03/04） | 只读重建；可作为 resume 入口 | 依赖持久化 log | 核心能力本身 | DSH VERIFIED；AgentScope ADAPTER（不重执行）；Codex ADAPTER（resume/fork/rollback 为 backend-specific，不得等同，21 BP-07） |
| Recovery | CORE | crash repair：合成 tool/result + step/end + turn/end{interrupted}；TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN（13 §8；15 §11） | 崩溃/中断后追加合成闭合事件；不重写历史 | 合成事件 append-only；原始历史保留 | 修复后 log 仍可重放 | DSH VERIFIED；AgentScope ADAPTER（Unified recovery）；Codex MISSING 原生 marker → Adapter 保守 TOOL_OUTCOME_UNKNOWN（22 §4） |

---

## 4. Execution Model

冻结：

```text
Session
  ↓
Turn
  ↓
Step
  ↓
Execution
  ↓
ExecutionAttempt          （CORE EXTENSION POINT，不实现）
```

工具路径：

```text
Execution
  ↓
ToolCall
  ↓
ToolResult
```

明确约束：

1. **Step 是持久化边界，Execution 是该边界的运行时实例**（17 §3-1）。Execution
   不持久化为独立对象；其可观测物是 Step 事件。
2. **Tool failure ≠ Step failure ≠ Turn failure**（17 §9；15 TW-06）：
   tool failure / timeout / deny / approval-reject / guard-reject 落为
   `tool/result isError`，step/turn 继续；只有内部 scheduler/runtime failure
   才可能上升为 step/turn error（15 §5）；model failure 是独立维度，可 step
   内重试或 turn/end{error}（14 §5）。
3. **Execution retry ≠ Step identity mutation**（22 §7；21 CTX-07）：
   - 同 Step retry（DSH model retry / compaction overflow retry）不新开 Step，
     不改变 Step identity；
   - 跨 Step retry（Codex compaction 后新 sampling request）保留原生 Step 边界，
     不得合并 Step 来伪造同 Step retry；retry identity 由 ExecutionAttempt
     扩展点承载。
4. Turn/Step 边界与 reason 词汇：completed / max-tokens / error / aborted /
   blocked / interrupted（14 §1）。Codex 无 max-tokens/blocked 显式枚举，stop
   hook 不产生 blocked turn/end —— 属 LOSSY，Adapter 不得伪造（20 §9.2 Q1）。
5. 崩溃尾部修复顺序固定：合成 tool/result → step/end → turn/end{interrupted}
   （15 §11；runtime recovery.py）。

---

## 5. Event Model

统一事件至少支持以下类型：

| 事件 | 类别 | 角色 |
| --- | --- | --- |
| turn/start、turn/end | CORE EVENT（trace） | Turn 边界；turn/end 携带 reason |
| step/start、step/end | CORE EVENT（trace） | Step 边界 |
| model/request | CORE EVENT（trace） | 运行时 agent/request；durable surrogate 是 request/header（17 §4） |
| assistant/chunk | TRACE EVENT | 原始流块；不进模型历史 |
| assistant/message | CORE EVENT（model-visible） | 组装后的模型消息；source_event_seqs → chunks |
| tool/call | TRACE EVENT | 工具调用记录；不进模型历史 |
| tool/result | CORE EVENT（model-visible） | 工具结果；source_event_seqs → call |
| user/message | CORE EVENT（model-visible） | 用户输入/附加上下文 |
| llm/retry、llm/retry-started | TRACE EVENT | 模型重试轨迹（14 §3） |
| compaction/start、compaction/summary、compaction/end、compaction/prune | PROJECTION EVENT | 改变 surface 投影；不截断 log（13 §6） |
| approval/asked、approval/decided、permission/preset、sandbox/mode | BACKEND EVENT / audit | 审计/策略记录；模型不可见（15 §12） |
| Codex RolloutItem（ResponseItem / EventMsg / Compacted / WorldState / TurnContext / InterAgentCommunication） | BACKEND EVENT | raw source；经 Adapter 翻译，raw_event_ref 可回源（23 §1） |
| AgentScope AgentEvent（ReplyStart / ModelCallStart / TextBlockDelta / ToolCall* / ToolResult* / ReplyEnd） | BACKEND EVENT | 调度层事件；Adapter 翻译，Thinking/DataBlock 为 LOSSY（25 §1） |

分类规则：

1. **CORE EVENT**：统一 SessionEvent schema 中承载 execution truth 的事件；
   所有 Core 语义依赖它们。
2. **BACKEND EVENT**：backend 原生事件。允许 `raw_event_ref` 引用；不要求全部
   变成 Core event（20 §3.1；21 BP-03）。
3. **TRACE EVENT**：持久化但从不进入模型历史（boundaries/chunks/usage/errors/
   request/header/retry/descriptor，14 §4）。
4. **PROJECTION EVENT**：只改变 surface 投影的 replacement 事件；log 本身
   不截断、原事件保留、source_event_seqs 保留（13 I-03/04/05）。

约束：

- `agent/request` 是 runtime-only 事件；其 durable 职责由 `request/header`
  承担，不得混为一个事件（17 §4）。
- 模型可见内容只能是 `user/message`、`assistant/message`、`tool/result`
  的 surface 派生（14 §4）。
- backend 事件与 core 事件的关系是“引用/翻译”，不是“强制合并”。

---

## 6. Ownership

冻结：

```text
Capability
  ↓ owns
Scope
  ↓ owns
Effect
```

约束：

1. **Ownership 独立于 Initiator 与 Authorization**：
   `owner ≠ initiator ≠ authorized_principal`（17 §5；16 CC-05）。三者不得
   合并成一个字段，也不得互相推导（16 §9）。
2. **Capability lifecycle 与 Agent execution lifecycle 是两个正交维度**
   （17 UN-12）：capability 可跨多个 turn ACTIVE；一个 step 可调用多个
   capability 提供的工具。
3. **Backend-specific ownership 与 Unified ownership overlay 共同存在**：
   - AgentScope：工具注册/可见性由 adapter 经 public API 管理；统一
     Capability/Scope/Effect 由 Unified Runtime 持有（python-cordis 13 §8）。
   - Codex：资源 owner 是 session-scoped services（MCP runtime /
     UnifiedExecProcessManager / ApprovalStore / skills/plugins/extensions），
     保留为 BACKEND-SPECIFIC metadata；不得把 Codex 工具贡献者自动映射成
     Capability（20 §5；22 §5）。
4. Replay 不恢复 ownership state；必须重新 install（17 §7）。

---

## 7. Causality

冻结三个独立概念：

| 概念 | 定义 | 持久化 | Replay |
| --- | --- | --- | --- |
| Ambient Initiator | 进程内当前执行身份（live agent 对象 + ALS/ContextVar） | 否（16 §6.2） | 不恢复（17 UN-11） |
| Durable Lineage | header parentSession/seedLength/delegationDepth/origin + sourceEventSeqs + call tree | 是（16 §6.2） | 可重建（事件/header 级） |
| Event Provenance | 每个统一事件可回源到 backend raw event（raw_event_ref） | 是（21 BP-03/14） | 保持可回源（23 §2） |

约束：

1. Core **不要求所有 backend 都有 ambient initiator**；Codex 无 ambient
   initiator（MISSING），其 `originator` 是产品来源串，不是 agent 身份
   （20 §6.1 Q1）。
2. Core 一旦产生 execution attribution，必须允许表达：`initiator`、
   `parent`、`root`、`source event`（17 §2 CAUSES；16 CC-01/02）。
3. Backend 可 EXACT / PARTIAL / LOSSY，但**不能静默伪造**：
   - DSH：direct path EXACT（exec.agent + turn/step + sourceEventSeqs）；
     nested code-mode step 归属 INFERENCE。
   - AgentScope：Unified with_initiator 贯穿 run_turn（26 §2.5）。
   - Codex：durable lineage ADAPTER；live initiator 只能由 Unified runtime
     overlay 赋值并标注 ADAPTER ASSIGNMENT（25；26 §9），durable 层不得
     发明 initiator_id（20 §6.1 Q6）。

---

## 8. Authorization

冻结：

```text
owner（谁负责生命周期）
  ≠
initiator（谁导致执行）
  ≠
authorized_principal（谁有权执行）
```

Core 只冻结正交性，不冻结具体机制（17 §5；15 §3）：

| Backend | 机制 | 分类 |
| --- | --- | --- |
| DSH | ApprovalService（allowed-once/rejected/cancelled/unavailable）+ ToolGuard（单调否决）+ session sandbox policy（工具体消费） | VERIFIED / BACKEND-SPECIFIC 形态 |
| AgentScope | PermissionContext allow rules；Phase 4-D 全部 ALLOW；RequireUserConfirm / RequireExternalExecution NOT_SUPPORTED | ADAPTER / LOSSY（25 A1/A8） |
| Codex | ToolOrchestrator approval stage + Guardian 自动审查 + permission profile/sandbox policy | ADAPTER（20 §11） |

约束：

- 统一事件层没有已验证的 authorized_principal 字段；现有可观测物是
  approval/policy 类事件（15 §12；17 §12-7）。属 OPEN QUESTION，不伪造。
- approval/guard/permission 在 DSH 中三个概念可区分（15 §3）；Codex 中
  approval 是执行流水线 stage、Guardian 是外部策略（20 §4.2 Q7）。统一契约
  不得要求两者使用同一机制（本契约 §12/§14）。

---

## 9. Persistence

Core 冻结：

```text
append-only execution history
  必须支持：append / read / reconstruct / replay
```

约束：

1. 事件日志 append-only：无原地修改、无物理删除、无 tombstone（13 I-01/§3.3）。
2. `compaction/prune` 与 `surfaceOp.replace` 是“追加新事件 + 改变投影”，
   不是 DELETE（13 §3.3）。
3. 具体存储（JSONL / SQLite / DB / rollout / other）全部属于 storage/backend
   concerns；Core 契约不绑定存储格式（17 §10）。
4. 现状：Unified EventStore（JSONL）是 Unified 侧 source of truth；Codex
   rollout 作为 raw source 并存，不互相替代（26 §7；27 §5）。
5. durability 边界：flush ≠ fsync；fsync/介质级持久化无证据
   （13 §12-2；runtime event_store.py PHASE-4B ASSUMPTION A1）——保持 UNKNOWN，
   不得声明“flush 即 durable”。

---

## 10. Replay

冻结（13 REPLAY-01..04；17 §7）：

1. **Replay 从事件历史重建 execution semantics，不重新执行模型/工具**
   （runtime recovery.py；27 §5：exec 计数不增长）。
2. **Replay 不恢复 ambient process state**：ambient initiator、capability
   effects、runtime inbox 均不恢复（17 UN-11）。
3. **Replay ≠ Evaluation**：replay 可喂给 evaluation，但不产生质量结论
   （13 REPLAY-04）。
4. **Codex resume/fork/rollback ≠ Unified replay**：resume = 历史重建；
   fork = copied/referenced 前缀；rollback = `ThreadRolledBack` marker + 重建。
   Adapter 必须带 backend-specific 标记，不得等同（21 BP-07；20 §8）。
5. fork seed 只取已完成 turn 前缀；header 记录 seed_length；冷恢复校验
   parent_session（16 §3/§7）。
6. crash 后 TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN：存在性 VERIFIED；
   精确判定边界 UNKNOWN；当前实现保守标记 OUTCOME_UNKNOWN（13 §8；
   runtime recovery.py）。

---

## 11. Context

冻结严格三层：

```text
Event Log
  ↓
Surface Projection
  ↓
Model Context
```

约束：

1. **Event Log ≠ Surface ≠ Model Context**（13 ES-01/02；17 §11）：
   - Event Log：append-only source of truth；
   - Surface：log 的有序投影（可重建，非独立权威）；
   - Model Context：请求时视图（system + tools + runtime context + surface
     派生 messages + current input），每次请求重建，不持久化。
2. **Compaction 改变 future projection，不删除 source history**
   （13 COMP-01/02）：`compaction/summary` + `surfaceOp.replace` 追加进 log，
   原事件与 source_event_seqs 保留。
3. Codex `ContextManager/for_prompt` 是 Surface+derive 的合并实现，不是独立
   Surface 对象（20 §7.1 Q2）；Unified 契约仍按三层表达。
4. `derive_messages` 确定性：契约按 “same log + same rules ⇒ same messages”
   接受，但作为 INFERENCE/PARTIAL，不写成 VERIFIED（13 ES-04；
   runtime surface.py 以 implementation assumption 实现）。

---

## 12. Tool Model

Core 只冻结：

| Core 项 | 定义 | 证据 |
| --- | --- | --- |
| Tool Call | 稳定 call identity + 参数 + 归属（turn/step + sourceEventSeqs 或 call_id 配对） | 15 TW-01/02；20 §4.2 |
| Tool Result | success/failure union + content + error{name,code} + meta | 15 §1/§9 |
| Tool Failure | 落为 tool/result isError；不隐式结束 step/turn（scheduler failure 除外） | 15 TW-06；17 §9 |
| Tool Identity | callId + name + 可选 rootCallId/parent | 15 §1；16 §5 |
| Tool Attribution | 归因到 Agent/Session/Turn/Step/Tool-identity；不得声明 Model/Prompt/Skill/Capability 根因 | 16 §8 |

以下项跨 backend 不一致，属 EXTENSION 或 BACKEND-SPECIFIC，Core 不强制统一
（22 §9；15 §15）：

| 项 | DSH | AgentScope | Codex |
| --- | --- | --- | --- |
| approval | ApprovalService seam + audit 事件 | 当前全 ALLOW（LOSSY） | ExecApprovalRequirement + approval 事件 |
| guard | ToolGuard 单调否决 | 无独立 guard | Guardian 自动审查 |
| sandbox | sandbox policy（工具体消费） | 未使用（MISSING） | denial 自动降级 SandboxType::None（BACKEND-SPECIFIC） |
| timeout | timeoutMs + TOOL_TIMEOUT | 无显式证据 | 默认 10s + timeout_ms |
| parallelism | isConcurrencySafe + maxParallelToolCalls | 未显式验证 | parallel dispatch |
| fallback | 无自动 tool retry（NOT FOUND） | 无 | sandbox denial 自动降级（特有） |

---

## 13. ExecutionAttempt

**判定：CORE EXTENSION POINT**（不是 Core 对象，不是 Backend-specific）。

理由：

1. **DSH/AgentScope 不需要独立对象**：model retry / compaction retry 在同一
   Step 内重新 buildRequest，Step identity 不变（14 TS-02；25 A5/A6）；
   没有独立 execution/attempt record（16 §1-D NOT FOUND）。
2. **Codex 证明需要一个承载位置**：compaction 后开启新 sampling request =
   新 Step（20 §7.1 Q9）；Unified 若只保留 Step 边界则丢失 retry 身份，
   强行合并则修改 Step 语义（22 §7）。
3. **字段未验证**：两侧都没有可被证据冻结的 attempt schema，因此只冻结
   扩展点，不冻结最终字段。

契约占位（**非最终 schema**，实现前需补证据或显式声明为 assumption）：

```text
execution_id        # 被重试的逻辑执行
attempt_id          # 本次尝试
attempt_number      # 第几次尝试
parent_execution_id # 前序尝试（或触发本次尝试的执行）
reason              # retry 原因（model/backend/compaction/...）
```

约束：

- ExecutionAttempt 附着于 Execution（运行时），不修改 Turn/Step 语义
  （22 §7；21 BP-10）。
- Execution retry ≠ Step identity mutation：同 Step retry 不需要 attempt
  对象；跨 Step retry 必须用 attempt 连接，Adapter 不得合并 Step。
- 扩展点必须 replay-aware：replay 后 attempt 链接与 lossiness 不消失
  （23 §2；本契约 §15）。
- 本阶段禁止实现 ExecutionAttempt（Phase 5-E 禁止范围）。

---

## 14. Backend Extension Points

| Candidate | 分类 | 依据 | 契约要点 |
| --- | --- | --- | --- |
| ExecutionAttempt | CORE EXTENSION POINT | 22 §7：compaction retry 跨 Step 身份 | §13；不实现 |
| BackendEventRef | CORE EXTENSION POINT | 21 BP-03；23 §3；codex adapter 的 raw_event_ref | 每个统一事件可携带 backend raw 引用（路径+行号+类型），不改变事件主语义 |
| BackendMetadata | CORE EXTENSION POINT | 21 BP-06；23 §2；codex adapter 的 BackendMappingMetadata | 可枚举 lossiness + backend fact 快照；概念字段见 §15 |
| ErrorDetail | OPTIONAL EXTENSION | 22 §8：当前 tool/result.error + BackendMetadata 足够 | 有跨 backend 归一化错误 taxonomy 需求时再定 |
| RecoveryCapability | OPTIONAL EXTENSION（具体能力 BACKEND-SPECIFIC） | 22 §8；20 §8（Codex resume/fork/rollback） | Core 只冻结统一 repair；backend 自身 recovery 语义由 backend 声明 |
| AuthorizationCapability | OPTIONAL EXTENSION（具体机制 BACKEND-SPECIFIC） | 15 §3/§4；20 §11 | Core 只冻结 owner≠initiator≠principal；approval/guard/permission 机制不统一 |
| ToolCapability | OPTIONAL EXTENSION（具体控制 BACKEND-SPECIFIC） | 本契约 §12 | approval/guard/sandbox/timeout/parallelism/fallback 跨 backend 不一致时留在扩展/backend 层 |

不能全部升级成 CORE：只有 ExecutionAttempt / BackendEventRef / BackendMetadata
三个被两个 backend 的公共需求验证为统一侧必须承载；其余按需扩展。

---

## 15. Lossiness Contract

冻结统一概念 **BackendMappingMetadata**（不实现具体 schema；现有 codex
adapter 实现只是可行性证据，23 §2）：

```text
backend            # backend 标识
mapping_quality    # EXACT | ADAPTER | LOSSY | BACKEND_SPECIFIC | UNKNOWN
raw_event_ref      # backend raw source 引用（可回源）
missing_semantics  # 有损/缺失语义清单，可枚举
backend_metadata   # backend 原生事实快照（可选）
```

三原则：

1. **Lossiness visible**：映射质量与缺失语义可被消费方枚举；未映射项必须
   出现，禁止静默丢失（21 BP-06；23 §2）。
2. **Lossiness auditable**：每个有损翻译可经 raw_event_ref 回源到 backend
   raw event（21 BP-14）。
3. **Lossiness replay-aware**：replay 后 metadata 与缺失清单不消失
   （23 §2；26 §6/§8）。

当前已验证的 Codex 缺失语义（六项，23 §2；26 §6）：

```text
STEP_BOUNDARY_PERSISTED
EXEC_FAILURE_STRUCTURED_SUCCESS
CHUNK_TO_MESSAGE_LINEAGE
CRASH_OUTCOME_NATIVE_MARKER
AMBIENT_INITIATOR
COMPACTION_RETRY_SAME_STEP
```

---

## 16. Portability Invariants

| # | Invariant | 状态 |
| --- | --- | --- |
| CORE-01 | Semantic core does not depend on a backend. | VERIFIED（runtime core 对象 0 backend import，24 §2/§4；26 §2） |
| CORE-02 | Backend adapter may synthesize missing semantic boundaries. | VERIFIED（Codex Step 构造；AgentScope one reply = one Step，22 §2；25 A3） |
| CORE-03 | Synthetic boundaries must be marked as adapter-derived. | VERIFIED（step_metadata mapping_quality=ADAPTER，27 §4） |
| CORE-04 | Backend-specific semantics must remain recoverable. | VERIFIED（raw_event_ref + backend metadata，21 BP-03/14；26 §6） |
| CORE-05 | Lossiness must be explicit. | VERIFIED（BackendMappingMetadata + missing_semantics 六项，23 §2；26 §6） |
| CORE-06 | Ownership != Causality != Authorization. | VERIFIED（16 CC-05；17 §5；20 §6.2） |
| CORE-07 | Event history is distinct from projection. | VERIFIED（13 ES-02；surface.ts:85；21 BP-08） |
| CORE-08 | Replay must rebuild semantics without silently inventing backend facts. | VERIFIED（22 §4：TOOL_OUTCOME_UNKNOWN 只由 inference 规则产生；不伪造 TOOL_NOT_STARTED） |
| CORE-09 | Backend replacement must not require rewriting Capability lifecycle semantics. | VERIFIED（python-cordis 12/13；21 BP-04/09；20 §10） |
| CORE-10 | Backend-specific behavior must not silently redefine Core semantics. | VERIFIED（22 BP-15；23 §1.2 不允许清单） |
| CORE-11 | Retry identity must be expressible independently from Step identity. | VERIFIED（扩展点：22 §7；本契约 §13） |
| CORE-12 | Raw backend evidence should remain referenceable. | VERIFIED（21 BP-03/14；raw_event_ref，26 §6） |

---

## 17. AgentScope vs Codex Comparison

最终表（列值见 §2 状态词；`Core` 列 = 该语义在 Core Contract 中的层）：

| Semantic | Core | AgentScope | Codex | Status |
| --- | --- | --- | --- | --- |
| Session | CORE | ADAPTER（runtime 持有；AgentScope state 是每 step 一次性投影，25 A2） | ADAPTER（thread ↔ Session；rollout 持久化） | ADAPTER |
| Turn | CORE | ADAPTER（runtime 记录；ExceedMaxIters/ReplyEnd 仅流信号，25 A3） | ADAPTER（公开 Task ↔ Turn；内部 run_turn BACKEND-SPECIFIC） | ADAPTER |
| Step | CORE | ADAPTER（one reply = one Step，max_iters=1） | ADAPTER/LOSSY（sampling request 构造；无原生 step 事件） | ADAPTER |
| Execution | CORE | ADAPTER（ModelAdapter stream） | ADAPTER（sampling request + tool dispatch） | ADAPTER |
| ExecutionAttempt | CORE EXTENSION POINT | MISSING（重试同 Step，无 attempt） | MISSING（compaction retry 新 Step，需扩展点） | CORE EXTENSION POINT |
| ToolCall | CORE | ADAPTER（ToolCallStart/Delta/End 缓冲翻译） | ADAPTER（call_id EXACT；step 归属 LOSSY） | ADAPTER |
| ToolResult | CORE | ADAPTER（ToolResultStart/Text/End + state 校验） | ADAPTER/LOSSY（exec success 固定 true） | ADAPTER/LOSSY |
| Event | CORE | ADAPTER（Thinking/DataBlock LOSSY，25 §1） | ADAPTER（rollout→unified；RawResponseItem 去重） | ADAPTER |
| Persistence | CORE（append-only 契约） | ADAPTER（Unified EventStore；backend 不另存语义历史） | ADAPTER（rollout raw + Unified log 并存） | ADAPTER |
| Replay | CORE | ADAPTER（不重执行） | ADAPTER（统一 replay；resume/fork/rollback 不等同） | ADAPTER |
| Context | CORE | ADAPTER（per-step rebuild from surface） | ADAPTER（ContextManager = Surface+derive 合并） | ADAPTER |
| Compaction | CORE（replacement/projection） | ADAPTER（CompactionEngine same-step retry） | ADAPTER/LOSSY（CompactedItem 新事实；retry 新 Step；无事务事件/sourceEventSeqs） | LOSSY |
| Ownership | CORE（Capability→Scope→Effect） | ADAPTER（Toolkit 可见性；统一 runtime overlay） | BACKEND-SPECIFIC（session 服务；无 Capability/Scope/Effect） | BACKEND-SPECIFIC |
| Causality | CORE（Initiator/Lineage/Provenance 分离） | ADAPTER（with_initiator 贯穿 run_turn） | LOSSY（无 ambient initiator；durable lineage ADAPTER） | LOSSY |
| Authorization | CORE（正交维度；机制不冻结） | ADAPTER（PermissionContext；Phase 4-D 全 ALLOW） | ADAPTER（approval stage + Guardian + permission profile） | ADAPTER |
| Sandbox | EXTENSION / BACKEND-SPECIFIC | MISSING（Phase 4-D 未使用） | BACKEND-SPECIFIC（denial 自动降级 SandboxType::None） | BACKEND-SPECIFIC |
| Approval | OPTIONAL EXTENSION | LOSSY（当前全 ALLOW；RequireUserConfirm NOT_SUPPORTED） | ADAPTER（ExecApprovalRequirement + approval 事件） | ADAPTER |

说明：表中无 EXACT 行，因为两个 backend 都需要翻译/构造；EXACT 只出现在
字段级（例如 Codex call_id、call↔output 配对、AgentScope TextBlockDelta →
assistant/chunk，25 §1 / 27 §4）。

---

## 18. Non-Core Semantics

不属于 Core Contract v1：

1. **Backend 原生事件 schema**：Codex RolloutItem、AgentScope AgentEvent。
2. **具体存储格式**：JSONL / SQLite / DB / rollout。
3. **Agent loop / dispatch 实现**：AgentScope reply_stream 接线（one reply =
   one Step）、Codex `run_turn` 内部控制边界、工具调度器细节。
4. **Model provider 行为**：真实 provider 错误码、token 计费、流式 chunk
   边界（25 A7）。
5. **Tool 执行控制机制**：approval / guard / sandbox / timeout / parallelism /
   fallback 的具体实现（本契约 §12）。
6. **Completion vs Verification / Evaluation**：Core 不合并 completion 与
   verification；不引入 evaluator（13 REPLAY-04；20 §9）。
7. **产品级 Trajectory / UI / CLI / Regression / Promotion**。
8. **Codex 特有语义**：CompactedItem/window_ids、ThreadRolledBack marker、
   fork Copied/Referenced、sandbox denial fallback、originator、rollout trace
   graph、session-scoped 资源 owner（22 §9）。
9. **DSH 特有语义**：currentInitiator ambient、TOOL_NOT_STARTED 精确判定、
   step/start-end 原生事件、waterfall 阶段词汇、compaction 事务事件
   （22 §9）。

---

## 19. Open Questions

| # | Open Question | 状态 |
| --- | --- | --- |
| 1 | Capability lifecycle 事件是否进入 SessionEvent | OPEN（13 §13.3；17 §12-1） |
| 2 | Capability.dispose() 与 in-flight tool call 的并发语义 | OPEN（17 §8-3） |
| 3 | deriveMessages 形式化确定性 | PARTIAL / INFERENCE（13 ES-04） |
| 4 | flush/fsync durability boundary | UNKNOWN（13 §12-2） |
| 5 | ExecutionAttempt 最终字段与持久化位置 | OPEN（本契约 §13；扩展点已冻结） |
| 6 | TOOL_NOT_STARTED 精确判定边界 | UNKNOWN（13 §12-10；当前保守 OUTCOME_UNKNOWN） |
| 7 | authorized principal 的事件级表达 | OPEN（15 §12；20 §11 MISSING） |
| 8 | 跨 backend persistent ordering 严格一致 | UNKNOWN（13 §12-6） |
| 9 | 显式 step_id/turn_id 是否进入统一事件 schema | OPEN（DSH 用数字；Python runtime 已用显式 id；14 §9-4） |
| 10 | 普通 deny 的持久化失败身份是否足以支撑 replay 路由 | UNKNOWN（15 §11/UNKNOWN） |

Open questions 不阻塞 v1 冻结；实现前必须显式声明为 assumption，不得写成
VERIFIED（17 §12；14 §10-7）。

---

## 20. v1 Acceptance Criteria & Final Verdict

### Acceptance Criteria

| # | Criterion | Evidence | Result |
| --- | --- | --- | --- |
| 1 | AgentScope 能映射 | Phase 4-D PASS（26）；跨 backend golden path 事件序列一致（27 §6） | ✅ |
| 2 | Codex 能映射 | Phase 5-C fixture PASS（26）；Phase 5-D 真实 pinned Codex E2E PASS（27） | ✅ |
| 3 | 不需要修改 Semantic Core | 24（seam 修复）+ 26/27（core 对象 0 backend import、零语义修改） | ✅ |
| 4 | Ownership / Causality 可保持正交 | 16 CC-05；17 §5；20 §6.2；runtime initiator.py 与 ToolRegistration.owner 分离 | ✅ |
| 5 | Event / Surface / Context 分离 | 13 ES-01/02/03；本契约 §11；deriveMessages determinism 作为 open item 显式声明 | ✅（契约层） |
| 6 | Backend-specific semantics 可保留 | 22 §9；codex adapter ownership_metadata / raw refs / rollout 并存 | ✅ |
| 7 | Lossiness 可显式表达 | 23 §2 + 26 §6 + 27 §4（六项 missing_semantics 可枚举、可回源、replay 保留） | ✅ |
| 8 | Retry identity 有承载位置 | 22 §7 → ExecutionAttempt 冻结为 CORE EXTENSION POINT（本契约 §13） | ✅ |

### Final Verdict

**PASS** — Unified Agent Runtime Core Contract v1 冻结完成。

- **Core Semantics**：Session / Turn / Step / Execution / ToolCall / ToolResult /
  Event / EventStore / Surface / ModelContext / Capability / Scope / Effect /
  Initiator / Lineage / Replay / Recovery；append-only execution history；
  Event Log → Surface → Model Context；Tool failure ≠ Step failure ≠ Turn
  failure；Ownership ≠ Causality ≠ Authorization；compaction = projection
  replacement。
- **Core Extension Points**：ExecutionAttempt（retry identity）、BackendEventRef
  （raw_event_ref）、BackendMetadata（lossiness 容器）。
- **Backend-specific Semantics**：Codex CompactedItem/window_ids、
  ThreadRolledBack、fork Copied/Referenced、sandbox denial fallback、
  originator、rollout trace graph、session-scoped 资源 owner、run_turn 控制
  边界；DSH currentInitiator、TOOL_NOT_STARTED 判定、step/start-end 原生
  事件、waterfall 阶段词汇、compaction 事务事件；AgentScope one-reply
  接线与 PermissionContext 形态。
- **Unresolved Questions**：§19 十项（lifecycle 事件域、dispose 并发、
  deriveMessages 确定性、fsync durability、ExecutionAttempt schema、
  TOOL_NOT_STARTED 判定、authorized principal 表达、跨 backend ordering、
  step/turn 显式 id、deny 身份）。
- **Why AgentScope + Codex validate portability**：AgentScope 证明
  “Semantic Core 可驱动一个真实调度 backend”（4-D）；Codex 证明
  “Semantic Core 可承载一个语义不完全对齐的真实 backend，且只通过
  Adapter + 显式 lossiness 翻译”（5-D real E2E）。两个方向覆盖了
  “backend 完全映射”与“backend 有损映射”两种形态，且都不需要修改
  Semantic Core —— 这正是 v1 需要验证的 portability 边界。

按阶段指令，契约冻结后停止；不进入实现。
