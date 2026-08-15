# 17 — DSH Semantic Runtime Integration Contract（Phase 3-E）

> 阶段：Phase 3-E（DSH Semantic Runtime Model）；只做 contract，不实现 runtime
> 输入：13 Event Sourcing / 14 Turn-Step / 15 Tool Waterfall / 16 Causal Chain（DSH 冻结契约）
>       + python-cordis 10 Recommendation / 12 Capability Lifecycle / 13 Capability Manager（Capability Ownership）
> 方法：整合既有契约，不重新考古、不重复已有结论；引用以契约编号为准
> 状态词：VERIFIED / PARTIAL / INFERENCE / DESIGN PROPOSAL / OPEN QUESTION / REQUIRED / NOT FOUND / UNKNOWN
> 最终状态：PARTIAL — 统一组合已冻结；open items 未定，实现前必须显式声明为 assumption

---

## 0. 统一模型一句话

Event Sourcing 提供**持久化真相**，Turn/Step 提供**执行边界**，Tool Waterfall 提供**执行语义**，
Causal Chain 提供**谁导致执行**（runtime ambient + durable lineage），Capability Ownership 提供**谁拥有资源**。

统一核心是 **Execution**：

```text
一次有因果归属、落在 Session/Turn/Step 边界内、穿过 Tool Waterfall、
并由 Capability Scope 提供资源所有权的执行；
其持久化真相是 SessionEvent log，模型可见性来自 projection。
```

| 契约 | 提供维度 | 在统一模型中的角色 |
| --- | --- | --- |
| 13 Event Sourcing | durable truth | SessionEvent log = source of truth；Surface = 投影；Replay/Recovery 的基础 |
| 14 Turn / Step | execution boundary | Session → Turn → Step 嵌套边界；Step = 一次模型请求 + 其工具活动 |
| 15 Tool Waterfall | execution semantics | Execution 的工具路径：pre-execute → approval → guard → execute → post-execute → result |
| 16 Causal Chain | attribution | Initiator（ambient）+ Lineage（durable header / sourceEventSeqs / call tree） |
| python-cordis 10/12/13 | ownership | Capability → Scope → Effect；Tool/Worker/Service 的创建与销毁归 owner |

---

## 1. 统一语义对象模型

分类：persisted entity / runtime object / projection / context / lifecycle object / causal object。
不要求每个对象最终成为 Python class；分类决定谁需要存储、谁需要运行、谁是纯函数、谁只是进程内载体。

| 对象 | 统一角色 | 分类 | 状态 |
| --- | --- | --- | --- |
| Session | durable execution history boundary：header（id/lineage）+ append-only log；同时有 live session runtime object | persisted entity + context | VERIFIED（13 ES-01） |
| Turn | turn/start … turn/end{reason} 边界；0..N Step | lifecycle object / boundary；persisted as events；无独立 turn 实体 | VERIFIED（14 §1）；显式 turnId NOT FOUND |
| Step | step/start … step/end；一次模型请求 + 该请求的工具活动 | lifecycle object / boundary + runtime runner；persisted as events；无 stepId | VERIFIED（14 §2）；显式归属字段 INFERENCE |
| Execution | 一个逻辑模型请求 + 关联工具活动的运行时执行实例 | runtime object + causal object；不持久化为对象，可观测物是事件 | VERIFIED（13/14/15 组合）；独立 execution record NOT FOUND（16 §1-D） |
| ToolCall | 持久化 `tool/call`（trace record）+ 运行时 `ToolExecution`（callId/agent/rootCallId/parent/token） | persisted record + runtime object | VERIFIED（15 §1） |
| ToolResult | 持久化 `tool/result`（message + error{name,code} + meta）+ 运行时 success/failure union | persisted record + runtime object + projection source（model-visible） | VERIFIED（15 §1/§9） |
| Capability | identity + scope + dependencies + install()/dispose()；runtime 注册与生命周期 | lifecycle object + runtime object（record 在 manager registry，instance 在 runtime） | VERIFIED（python-cordis 13 §2/§3）；DSH 无此对象（NOT FOUND） |
| Scope | 资源生命周期边界；每个 capability 恰好一个 owner scope | lifecycle object / ownership boundary（runtime only） | VERIFIED（python-cordis 12 CAP-01/02）；不持久化 |
| Effect | 任意副作用登记为 owner-scoped effect；逆序 teardown / 幂等 / 失败继续 | lifecycle object（ownership） | VERIFIED（python-cordis 12/13）；SessionEvent schema OPEN QUESTION |
| Initiator | 进程内当前执行身份：live agent 对象 + ALS/ContextVar | causal object + context（runtime only） | VERIFIED（16 §1/§2）；不持久化（NOT FOUND） |
| Lineage | 因果/血缘关系集合：header parentSession/seedLength/delegationDepth、sourceEventSeqs、code-dispatch call tree、exec.agent | 跨 persisted 与 runtime 的 causal object | VERIFIED（16 §3/§6） |
| Event | 统一区分 SessionEvent（persisted source-of-truth）vs runtime lifecycle event（Cordis，不落 SessionEvent） | persisted entity（SessionEvent）/ runtime event | VERIFIED（13 §3.1；16 §6.1） |
| Surface | log 的有序投影；deriveMessages 输入；排除 trace/replay data | projection（可重建，非独立权威） | VERIFIED（13 ES-02）；determinism PARTIAL |
| Projection | 派生视图概念；surface / model-visible messages 都是投影产物 | projection（非实体） | VERIFIED（13 §4） |

---

## 2. 统一关系模型

### CONTAINS

| 关系 | semantic meaning | lifecycle implication | persistence implication | replay implication |
| --- | --- | --- | --- | --- |
| Session → Turn | session 是 durable history boundary；turn 是其中一段有界执行 | turn 在 session 内创建/闭合；session 跨多个 turn | `turn/start`/`turn/end` 在 session log；无显式 turnId（顺序 + seq 定界） | 扫描事件重建 turn 序列（正常/aborted/error/interrupted VERIFIED；blocked 为零步 turn） |
| Turn → Step | step 嵌套在 turn 内；0..N Step | step 由 model request 创建、step/end 闭合；aborted/error 也写 step/end（15 §6） | `step/start`/`step/end` 事件；无 stepId/turnId 显式字段 | 事件顺序重建；显式归属为 INFERENCE（14 TS-01） |
| Step → ToolCall | 该 step 的模型请求引发的工具调用属于该 step | call 落在 open step；`tool/result` 先于 `step/end` | `tool/call|result` 带数字 turn/step；result.sourceEventSeqs → call.seq | 直接调用可重建；nested code-mode 子调用无 turn/step → INFERENCE（16 §5） |

### CAUSES

| 关系 | semantic meaning | lifecycle implication | persistence implication | replay implication |
| --- | --- | --- | --- | --- |
| Initiator → Execution | 谁导致执行（runtime causal attribution） | initiator boundary 随 driver kick 创建/结束；不拥有资源 | `exec.agent` 不写入事件（NOT FOUND）；durable surrogate = header lineage + turn/step + sourceEventSeqs | ambient initiator 不可回放；只能重建会话级归属（16 §7） |
| Agent → Child Agent | 父 agent 创建/触发子 agent 执行 | 子有自己的 initiator；父通过 parentSession/owner 关联 | header parentSession/seedLength/delegationDepth + `subagent/descriptor` | header 级可恢复；ambient 父子 initiator 不可恢复 |
| Step → Tool Call | 该 step 的模型请求触发 tool call | call/result 生命周期在 step 内 | `tool/call` 的 turn/step 数字 | 直接调用归属可重建 |

### OWNS

| 关系 | semantic meaning | lifecycle implication | persistence implication | replay implication |
| --- | --- | --- | --- | --- |
| Capability → Scope | 每个 capability 恰好一个 owner scope；所有 effect 归 scope | install 创建 scope；dispose 销毁 scope；reinstall = fresh instance + fresh scope | runtime registry；不落 SessionEvent | 不能从事件恢复；重新 install 建立新 scope |
| Scope → Effect | effect 的创建/销毁由 scope 逆序管理 | install 登记；scope dispose 逆序 teardown（幂等/失败继续） | 不持久化（audit 可另记录） | 不能恢复；必须重新注册 |
| Capability → Tool/Worker/Service | capability 通过 effect 注册 tool/worker/service；dispose 撤销 | 工具可用性随 install/dispose 变化 | DSH 工具注册不落 SessionEvent；request/header 快照可捕获工具集变化（INFERENCE） | 工具集从 runtime 重装恢复，不从事件恢复 |

### PROJECTS

| 关系 | semantic meaning | lifecycle implication | persistence implication | replay implication |
| --- | --- | --- | --- | --- |
| Event Log → Surface | surface 是 log 的有序派生视图 | 无独立生命周期；随 log 追加/replacement 事件变化 | log 持久化；surface 可重建 | 用 log + 投影规则重建 |
| Surface → Model-visible Messages | deriveMessages 纯投影 | 无 | 无独立存储 | same log + same rules ⇒ same messages（determinism PARTIAL，13 ES-04） |

### DEPENDS_ON

| 关系 | semantic meaning | lifecycle implication | persistence implication | replay implication |
| --- | --- | --- | --- | --- |
| Capability A → Capability B | A 依赖 B；install 先 B 后 A；unload 先 A 后 B | dependent 未卸载前 provider 不能 finalize；shared provider 有 active dependents 时禁止 silent unload | manager registry 依赖边（runtime）；失败/卸载时幂等移除 | 依赖图由 runtime 重建，不来自事件 |

---

## 3. 统一 Execution Model

```text
Session
  ↓
Turn
  ↓
Step
  ↓
Execution
  ├── Model Request
  │     request/header snapshot → assistant/chunk* → assistant/message
  └── Tool Calls
        └── Tool Waterfall
              ├── pre-execute   (allow | deny | ask)
              ├── approval      (allowed-once | rejected | cancelled | unavailable)
              ├── guard         (单调否决；无 force-allow)
              ├── execute       (tool body + signal + timeout + concurrency)
              ├── post-execute  (accept | block)
              └── result        (success | failure → tool/result)

Execution ← Initiator / Causal Chain        （runtime exec.agent；durable header lineage）
Tool / Worker / Service ← Capability Ownership（Scope → Effect）
```

统一语义：

1. **Step 是持久化边界，Execution 是该边界的运行时实例**。一次逻辑模型请求 + 该请求的工具活动 = 一个 Step；模型失败重试在同一 Step 内重新 buildRequest，不新开 Step（14 TS-02；05 §1）。
2. **Tool Waterfall 是 Execution 的工具路径，不是独立对象**。它把一次 tool call 从 gate 到 result 的语义固定为显式阶段（15 TW-03/05）。
3. **Causal Chain 从两个层面挂到 Execution**：runtime 层是 `exec.agent`/ambient initiator；durable 层是 header lineage + turn/step + sourceEventSeqs。两层不合并（16 §6.2）。
4. **Capability Ownership 决定 Execution 使用的工具/worker/service 是否存在**，但不决定 Execution 的语义；dispose 撤销的是注册与资源，不是执行流水线本身（15 §13；python-cordis 12 §2）。
5. **Execution causality ≠ resource ownership**。owner 回答“谁负责创建/销毁”，initiator 回答“谁导致执行”，authorized principal 回答“谁有权执行”（见 §5）。

---

## 4. 统一 Event Model

### 事件分类

| 类别 | 定义 | 成员 |
| --- | --- | --- |
| A. Source-of-truth event | append-only SessionEvent，是执行权威 | 全部持久化 SessionEvent（13 ES-01） |
| B. Projection event | 改变投影的 replacement 事件，log 本身不截断 | `compaction/summary`、`compaction/prune`（13 §3.2/§6） |
| C. Trace-only event | 持久化但从不进入模型历史 | boundaries、chunk、call、usage/error、request/header、descriptor、retry、approval/policy（14 §4） |
| D. Runtime lifecycle event | 运行时生命周期信号，默认不落 SessionEvent | `agent/request`（waterfall hook）、`subagent/start|end`、worker/start|stop、capability/install|dispose |
| E. Audit-only event | 审计/策略记录；可持久化但模型不可见 | `approval/asked`、`approval/decided`、`permission/preset`、`sandbox/mode`；capability/worker 若落盘默认归此类 |
| F. Model-visible event | 经 surface 派生为模型消息的集合 | `user/message`、`assistant/message`、`tool/result`（13/14） |

说明：F 不是独立存储类别，而是 A 的投影子集；同一事件可同时属于 A 和 F（如 `tool/result`）。

### 指定事件分析

| 事件 | 分类 | 持久化 | 模型可见 | 状态 |
| --- | --- | --- | --- | --- |
| turn/start、turn/end | A + C | SessionEvent | 否 | REQUIRED（14 §1/§3 schema 已冻结） |
| step/start、step/end | A + C | SessionEvent | 否 | REQUIRED（14 §2/§3） |
| agent/request | D | **不持久化**；durable surrogate 是 `request/header` | 否 | REQUIRED（保持 runtime-only；不得当 SessionEvent 写） |
| assistant/chunk | A + C | SessionEvent；sourceEventSeqs → assistant/message | 否 | REQUIRED（13 §3.1） |
| assistant/message | A + F | SessionEvent | 是 | REQUIRED（13/14） |
| tool/call | A + C | SessionEvent（turn/step/callId/name/arguments） | 否 | REQUIRED（15 §1） |
| tool/result | A + F | SessionEvent（message/error/meta + sourceEventSeqs） | 是 | REQUIRED（15 §1/§9） |
| turn/end | A + C | SessionEvent（reason 六值） | 否 | REQUIRED（14 §1） |
| capability/install | D/E | **schema 未定** | 否（默认） | runtime 状态机：REQUIRED（python-cordis 13 §3）；进 SessionEvent：OPEN QUESTION；audit 落盘：DESIGN PROPOSAL |
| capability/dispose | D/E | **schema 未定** | 否（默认） | 同上：OPEN QUESTION / DESIGN PROPOSAL；不得在 §9 open question 前自行定 schema |
| worker/start | D/E | 非 SessionEvent（类比 `subagent/start|end`，16 §6.1） | 否 | OPEN QUESTION（是否 audit 持久化）；DESIGN PROPOSAL（若需要 audit 记录） |
| worker/stop | D/E | 同上 | 否 | OPEN QUESTION / DESIGN PROPOSAL |

统一原则：

1. **A/B/C/F 是 SessionEvent domain，D 是 runtime/Cordis domain**；两者是否合并保持 13 §13.3 的 OPEN QUESTION。
2. `agent/request` 的持久化职责由 `request/header` 承担；runtime hook 与 durable snapshot 不混为一个事件。
3. Capability 事件最终 schema **不在此阶段决定**；只允许标 REQUIRED（runtime 层）/ OPEN QUESTION（SessionEvent 层）/ DESIGN PROPOSAL（audit 层）。

---

## 5. 三个独立维度

| 维度 | 问题 | 机制 | durable? | 状态 |
| --- | --- | --- | --- | --- |
| Lifecycle / Ownership | 谁负责资源何时创建和销毁？ | DSH：`AgentRegistry.enter(agent, owner)`；Python：PluginScope + EffectRegistry（python-cordis 12 §2） | 否（runtime registry） | VERIFIED（16 §9；python-cordis CAP-03） |
| Execution / Causality | 谁导致这次执行发生？ | DSH：`currentInitiator()`/ALS + `ToolExecutionInput.agent`；durable surrogate 是 header lineage + sourceEventSeqs | ambient 否；lineage 是 | VERIFIED（16 §1/§6） |
| Security / Authorization | 谁有权执行这个动作？ | DSH：ApprovalService + ToolGuard + sandbox policy（session 级 policy 由工具体消费） | policy 状态有事件（approval/policy、sandbox/mode） | VERIFIED（15 §3/§4） |

显式约束：

```text
owner ≠ initiator ≠ authorized_principal
```

- `owner` 是 registry/scope 关系；`initiator` 是 ambient 执行身份；`authorized_principal` 是授权主体。
- 三者不得合并成一个字段，也不得互相推导（16 §9 源码注释：owner 不是 durable lineage；ambient initiator 既不是 liveness proof 也不是 authorization）。
- Python 实现必须分别建模：lifecycle owner（Capability/Scope）、causal initiator（ContextVar + 显式字段）、authorization（policy/approval 层）。

---

## 6. 统一 async model

| 边界 | 是什么 | 机制 | 能承担 | 不能承担 |
| --- | --- | --- | --- | --- |
| Ambient initiator | 进程内 current execution identity | ALS / ContextVar；`with_initiator(agent, op)` 覆盖整个 driver kick 链（16 §2） | 同进程 Promise/async 链的因果传播 | persistent lineage、ownership、authorization |
| Capability Scope | resource lifecycle boundary | PluginScope + EffectRegistry；install/dispose 界定（python-cordis 12） | 资源创建/销毁归属 | ambient propagation、session history |
| Session | durable execution history boundary | SessionEvent log + header | 事件历史、replay、模型投影 | runtime ownership、当前执行身份 |

统一语义：

1. **ContextVar/AsyncLocalStorage 只能承担“进程内 ambient initiator”**，不能自动承担 persistent lineage、ownership、authorization。
2. 跨 worker/subprocess/job/MessagePort 边界必须显式传 `agent`/`parent`/`root_call_id`（或 `SubagentStartRequest.parent`），不依赖 ambient context（16 §4）。
3. 共享 timer/queue/pool 边界用 `without_initiator()` 清空 ambient，防止污染（16 §4）。
4. Replay 后 ambient initiator **不会自然存在**；只有重新运行 agent driver（再次 `with_initiator`）才能重建（16 §7；§7 of this doc）。

---

## 7. 统一 replay model

| # | 恢复什么 | 恢复方式 | 状态 |
| --- | --- | --- | --- |
| 1 | Session event history | 从持久化 log 重放 | VERIFIED（13 REPLAY-01） |
| 2 | Surface projection | 用 log + 投影规则重建（surface 是派生视图） | VERIFIED；determinism PARTIAL（13 ES-04） |
| 3 | Turn/Step boundaries | 从事件重建（正常/aborted/error/interrupted；blocked 零步 turn） | VERIFIED（14 §1/§5；15 §6 更新 aborted/error 也有 step/end） |
| 4 | Tool call/result lineage | sourceEventSeqs + callId + code-dispatch call tree | VERIFIED（直接调用）；nested step 归属 INFERENCE（16 §5） |
| 5 | Persistent parentSession lineage | header parentSession/seedLength/delegationDepth/origin | VERIFIED（16 §3/§7） |
| 6 | Ambient currentInitiator | **不能从事件恢复**；只能由重新运行 driver 重建（with_initiator） | NOT FOUND as replay mechanism（16 §12-6） |
| 7 | Capability ownership state | **不能从事件恢复**；必须 runtime 重新 install，fresh scope/generation | SessionEvent 层 NOT FOUND；python-cordis reinstall VERIFIED（12 §6；13 §6） |

不能恢复：

- 进程内 ambient initiator 链 / ALS context（16 §7）；
- in-flight 工具副作用边界（`TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN` 只能标记，不能判定绝对状态，13 §8）；
- 已注册的 capability effects / live workers（重新 install 才重建）；
- runtime inbox/queue 等非持久化状态（agent 层，不在此契约内）。

统一原则：**Replay 恢复 durable execution semantics，不恢复 ambient process state（UN-11）**。

---

## 8. 统一 lifecycle + execution boundary

正常组合：

```text
Capability install
  ↓
Tool becomes available（request/header 快照可捕获工具集变化）
  ↓
Step
  ↓
Tool Call（Execution 内穿过 Waterfall）
  ↓
Capability still ACTIVE
  ↓
Tool Result
  ↓
Step End
```

关系定义：

1. **Capability lifecycle 控制工具的可用性（注册/撤销），不控制工具执行语义**；工具一旦可执行，就走统一 Waterfall（15 §13）。
2. **Capability 的 INSTALL/ACTIVE/DISPOSE 与 Agent 的 TURN/STEP/TOOL CALL 是两个正交维度**（UN-12）：一个 capability 可以跨多个 turn 保持 ACTIVE；一个 step 可以调用多个 capability 提供的工具。
3. `Capability.dispose()` 恰好发生在 **Tool Call 正在执行**：

```text
状态：OPEN QUESTION
证据：DSH 无 capability 概念（NOT FOUND）；Phase 2 覆盖 install 回滚、依赖 teardown、
并发 dispose、reinstall，但没有“in-flight tool call + dispose 同时发生”的契约或测试。
结论：不得自行设计；实现前必须补契约或显式声明为 assumption。
```

4. `Scope.dispose()` 撤销 background worker（python-cordis 12 §3/§5：worker stop 是 effect，回滚路径已验证取消/结束）与 in-flight tool call 的取消是**不同问题**：worker 停止有本地证据；工具执行中 dispose 仍为 OPEN QUESTION。

---

## 9. 统一 Failure Model

| 失败类型 | 事件表现 | Step 影响 | Turn 影响 | Session 影响 | 状态 |
| --- | --- | --- | --- | --- | --- |
| Capability install failure | runtime FAILED + 已收集 effects 逆序回滚 | 无（安装阶段） | 无 | 无 | VERIFIED（python-cordis 12 §5；13 §5） |
| Capability dispose failure | reverse teardown 失败继续（primitive 层） | 无直接证据 | 无直接证据 | 无 | PARTIAL / UNKNOWN |
| Tool failure | `tool/result` isError（error{name,code}） | 继续 | 继续 | 无 | VERIFIED（15 §11） |
| Internal scheduler failure | 不伪造未启动结果；向 loop 抛错 | step 异常（经 finally 写 step/end） | `turn/end{error}` | 无 | VERIFIED（15 §5/§11） |
| Model failure | `LlmFailure` + `agent/request-error` + llm-retry | step 内重试（同 step 重新 buildRequest） | 重试耗尽 → `turn/end{error}` | 无 | VERIFIED（14 §5；05 §1） |
| Step failure | **无独立 step-level failure 事件**；“step failure”是派生的可观测结论 | — | 落在 tool/result isError 或 turn/end reason | 无 | PARTIAL（14 §7；DESIGN PROPOSAL 若加状态对象） |
| Turn failure | `turn/end{error|aborted|blocked|interrupted}` | 零步或闭合 | 终止 | 无 | VERIFIED（14 §1/§5） |
| Session failure | persistence/backend/durability 失败 | 超出事件语义 | 超出事件语义 | 影响恢复与 replay | UNKNOWN（13 §12：fsync、跨 backend ordering） |

统一原则（保持 Phase 3-C 结论）：

```text
Tool failure ≠ Step failure ≠ Turn failure
```

- tool failure / timeout / deny / approval-reject / guard-reject → `tool/result` isError，step/turn 继续（15 §11）；
- 只有 scheduler/internal failure 才可能上升到 step/turn error（15 §5）；
- model failure 是独立维度：可 step 内重试或终止 turn（14 §5）；
- capability failure 影响资源可用性；若发生在工具执行中 → OPEN QUESTION（§8-3）。

---

## 10. Unified Semantic Invariants

| # | Invariant | 状态 |
| --- | --- | --- |
| UN-01 | Every execution belongs to exactly one Session/Turn/Step boundary where supported | PARTIAL — 直接调用 VERIFIED；nested code-mode 子调用 step 归属 INFERENCE（16 §5） |
| UN-02 | Every runtime effect has an explicit lifecycle owner | VERIFIED（python-cordis CAP-03；10 §5）；DSH 无统一 effect registry，owner 机制来自 Phase 2 semantic layer |
| UN-03 | Every attributed execution has an initiator or explicit root | VERIFIED（16 CC-01） |
| UN-04 | Ownership and causality are independent | VERIFIED（16 CC-05） |
| UN-05 | Authorization is independent from both ownership and causality | VERIFIED（机制层：approval/guard/sandbox policy 独立于 owner/initiator，15 §3/§4；16 §9） |
| UN-06 | Model-visible history is derived from event history / projections | VERIFIED（13 ES-03）；deriveMessages determinism PARTIAL |
| UN-07 | Tool execution passes through explicit waterfall semantics | VERIFIED（15 TW-03/05） |
| UN-08 | Tool failure is not implicitly Step/Turn failure unless the execution contract says so | VERIFIED（15 TW-06；scheduler failure 除外） |
| UN-09 | Nested capability effects cannot outlive their owner scope | VERIFIED（python-cordis CAP-04/06/10；13 §5 rollback） |
| UN-10 | Causal lineage may outlive ambient runtime context through durable lineage records | VERIFIED（16 §6.2/§7：header + sourceEventSeqs 持久化，ambient 不持久化） |
| UN-11 | Replay restores durable execution semantics, not ambient process state | VERIFIED（16 §7；本契约 §7） |
| UN-12 | Capability lifecycle and Agent execution lifecycle are separate dimensions | VERIFIED（概念分离，13 §13.2；15 TW-10）；event domain 合并仍 OPEN QUESTION |

---

## 11. 统一 Runtime Boundary

```text
                    DSH Semantic Runtime
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   Event Sourcing      Execution Model    Capability Model
        │                  │                  │
   Session/Event       Turn/Step         Capability
   Surface             Tool Call         Scope
   Replay              Waterfall         Effect
   Recovery            Initiator         Dependency
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ↓
                    Agent Runtime
                           ↓
                  AgentScope 2.0
```

边界说明：

1. **DSH Semantic Runtime 是契约层，不是进程**：三个模型共享一个统一 Event Model（§4）与三个独立维度（§5）。
2. **Agent Runtime 是执行层**：消费语义层实现 agent loop / model adapter / tool executor（python-cordis 10 §7）。
3. **AgentScope 2.0 是调度/dispatch substrate**：Phase 2-B 只通过 public API 桥接（`adapters.agentscope`），语义层不 import AgentScope（13-capability-manager §8）；该桥是本地 Python 证据，DSH 源码无对应桥（15 §14，INFERENCE）。
4. 三个模型不互相包含：Event Sourcing 不知道 ownership；Execution Model 不知道授权主体；Capability Model 不知道模型消息。统一只发生在 Execution 交点（§3）。

---

## 12. Final Verdict

**PARTIAL** — 统一组合已冻结：

- Event Sourcing + Turn/Step + Tool Waterfall + Causal Chain + Capability Ownership 可在一个 Execution 交点上统一，且各契约的 VERIFIED 事实彼此兼容（无 CONFLICTING 项）。
- 统一模型本身没有新考古，没有新实现；它只是把四份 DSH 契约 + Phase 2 ownership 契约按 15 个对象、5 类关系、6 类事件、3 个维度组织起来。

必须显式带入 Python 实现的 open items：

1. Capability lifecycle 事件是否/如何进入 SessionEvent（OPEN QUESTION，13 §13.3）；
2. `Capability.dispose()` 与 in-flight Tool Call 的并发语义（OPEN QUESTION，§8-3）；
3. ambient initiator 不随 replay 恢复；initiator 归因只能到会话/事件级（16 §7）；
4. `deriveMessages` 形式化确定性（PARTIAL，13 ES-04）；
5. 工具结果/compaction 的持久化字段缺口（`concludesTurn`、`additionalContexts` 无事件字段，15 §1/§10）；
6. session 级 durability（fsync、跨 backend ordering）未证明（UNKNOWN，13 §12）；
7. authorization principal 在事件层无显式字段；只有 approval/policy 事件（15 §3/§4）。

PASS 条件：上述 7 项在 Python 设计中显式声明为 assumption 或补契约证据，不写成 VERIFIED。
