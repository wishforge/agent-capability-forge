# 16 — DSH Causal Chain / Initiator Semantic Contract

> 对象：deepseek-ai/deepseek-harness @ `47f943859bef60e4160492346772ded9b24f765a`（2026-08-13，`git rev-parse HEAD` 一致）
> 阶段：Phase 3-D（Initiator / causal chain / async attribution / subagent lineage）；只做 contract，不实现
> 来源：本阶段直接读源码（`packages/core/agent`、`packages/core/agent-loop`、`packages/core/tools`、`packages/core/session`、`packages/subagent/*`、`packages/session-query`、`packages/session/session-persistence-jsonl`、`packages/code-runtime/*`、`packages/workflow/*`）+ 复用 01/03/05/06/08/10/13/14/15/99 已证明事实
> 状态词：VERIFIED（本次源码直接确认）/ PARTIAL（部分路径确认）/ NOT FOUND（当前基线不存在）/ INFERENCE（推导）/ UNKNOWN（无证据）/ DESIGN_PROPOSAL（设计建议，非 DSH 语义）

---

## 0. Coverage Audit

| # | Semantic | Evidence | Status |
| --- | --- | --- | --- |
| 1 | currentInitiator | `AgentRegistry` 方法 + `AsyncLocalStorage`（`packages/core/agent/src/index.ts:234-264,309-357,640-701`） | VERIFIED |
| 2 | Initiator identity | 是 live `Agent` 对象引用，不是 traceId/spanId/parentId/sessionId；`ToolExecutionInput.agent` 为显式副本（`core/agent/src/index.ts:305-330`；`core/tools/src/index.ts:314-330`） | VERIFIED |
| 3 | parent-child relation | `SessionHeader.parentSession` + `delegationDepth` + `seedLength` + `origin`（`core/session/src/types.ts:61-98`；`subagent/src/child-agent.ts:101-121`） | VERIFIED |
| 4 | async propagation | Promise/async 内经 `AsyncLocalStorage` 传播；worker/subprocess/job 边界靠显式 `agent`/`parent` 字段，不是 ambient ALS（`core/agent-loop/src/agent.ts:192`；`core/tools/src/code-mode.ts:471-480`；`subagent/src/types.ts:110`） | PARTIAL |
| 5 | subagent attribution | 进程内 session-backed 子级有持久化 header lineage + `subagent/descriptor` 事件；`subagent/start|end` 是 Cordis 生命周期事件，不入 SessionEvent | PARTIAL |
| 6 | tool attribution | `exec.agent` 运行时必带；`tool/call|result` 持久化 turn/step；nested code-mode 持久化 rootCallId/parentCallId/subCallId | VERIFIED（direct）/ PARTIAL（nested step 归属为 INFERENCE） |
| 7 | session binding | 事件日志本身按 Session 组织；`tool/call` 数据内无 sessionId 字段 | VERIFIED |
| 8 | turn/step binding | `tool/call`/`tool/result` 数据带 `turn`/`step`；无 stepId 字段，`sourceEventSeqs` 配 call→result（`core/session/src/types.ts:279-300`；`core/agent-loop/src/tool-calls.ts:260-288`） | VERIFIED |
| 9 | cross-task propagation | 背景 job 在工具执行时捕获 `exec.agent` 为 `parent`，任务边界后仍显式携带（`subagent/tool-subagent/src/index.ts:370,406-412`）；无 ambient ALS 跨任务证据 | PARTIAL |
| 10 | causal chain completion | 可从事件 + header 推导完成（`tool/result`、`turn/end`、`subagent/end`）；无显式 chain-completion 记录/initiator id | PARTIAL |
| 11 | replay preservation | 事件级 `sourceEventSeqs` + header lineage + seed 边界可重放；ambient initiator 不持久化，不能回放 | PARTIAL（session/event 级 VERIFIED，initiator 级 NOT FOUND） |
| 12 | crash/recovery preservation | 崩溃修复合成 `tool/result`+`step/end`+`turn/end{interrupted}`；header lineage 在持久化 header 中；ambient initiator 无恢复机制 | PARTIAL |

无 CONFLICTING 项。

---

## 1. Initiator Definition

**Initiator 是：A（对象）+ C（Context）的组合，不是 ID。**

源码事实：

- `currentInitiator(): Agent | undefined` 返回 **live `Agent` 对象**（`packages/core/agent/src/index.ts:309-312`）。它不是 traceId/spanId/parentId/sessionId；`Agent.id` 与 `session.id` 同值，但 initiator 本身是对象引用，不是该 id 的字符串。
- 载体是进程内 `AsyncLocalStorage<Agent | undefined>`（`index.ts:259`），并配一个 `AsyncLocalStorage<InitiatorRun>` 跟踪边界嵌套链 `{ active, parent }`（`index.ts:234-237,260`）。因此实现上同时是"当前 agent 对象" + "异步 context" + "嵌套栈（仅用于 teardown drain）"。
- 类注释明确：**"Initiator methods provide same-process causal attribution only. Ambient presence is neither liveness proof nor authorization; subjects and owners remain explicit, as does identity at worker, process, persistence, and wire boundaries."**（`index.ts:253-257`）
- 工具边界上，initiator 被显式复制为 `ToolExecutionInput.agent?: Agent`（`packages/core/tools/src/index.ts:314-330`），`ToolExecution` 追加 registry 私有 `token` 与必填 `rootCallId`（`index.ts:379-384,1364-1390`）。

结论：

```text
A. 一个对象？  —— 是：live Agent 对象（VERIFIED）
B. 一个 ID？   —— 否：API 返回 Agent 对象；Agent.id 是身份但不是 initiator 本身（VERIFIED）
C. 一个 Context？ —— 是：AsyncLocalStorage 进程内异步 context（VERIFIED）
D. 一个 execution record？ —— 否：无独立 record 类型（NOT FOUND）
E. 一个 stack/chain？ —— 部分：InitiatorRun 有 parent 链，但只服务 teardown drain，不暴露为因果链 API（PARTIAL）
F. 多个字段组合？ —— 运行时组合：Agent 对象 + ALS context + 工具输入上的显式 agent/rootCallId/parent（VERIFIED）
```

---

## 2. currentInitiator

### 2.1 谁设置、谁读取

| 问题 | 答案 | 状态 |
| --- | --- | --- |
| 谁设置？ | `ReactLoopAgent.wakeDriver()`：`this.loopCtx.agents.withInitiator(this, () => this.kick())`（`packages/core/agent-loop/src/agent.ts:192`）。每个 agent 的一次 driver 生命周期（turn/step/tool 执行链）是一个 initiator boundary。 | VERIFIED |
| 谁读取？ | `executeToolCalls()` 用 `requireInitiator()` 取 agent（`packages/core/agent-loop/src/tool-calls.ts:67,130`）；`tool-goal` 权限校验用 `currentInitiator() !== agent`（`packages/goal/tool-goal/src/authority.ts:56`）；`web-search-deepseek` 可选读取以定位 session（`packages/web/web-search-deepseek/src/index.ts:118`）。 | VERIFIED |
| 什么时候创建？ | 每次 idle → running 的 wake 创建（`agent.ts:176-193`）。 | VERIFIED |
| 什么时候清理？ | `withoutInitiator()` 显式隐藏（`core/agent/src/index.ts:352-357`）；schedule 队列与 goal-round 用它在共享定时器/泵上清边界（`packages/schedule/schedule/src/runtime.ts:110`；`packages/goal/goal-round-driver/src/index.ts:215`）；服务 disposed 时 `disable()` 两个 ALS（`index.ts:626-636`）。ALS `.run()` 返回时自动恢复外层。 | VERIFIED |
| async 边界如何传播？ | 同进程 Promise/async 链经 `AsyncLocalStorage` 自动继承；`withInitiator` 包装整个 `kick()` 返回的 Promise，driver 的所有 await 延续都在边界内。 | VERIFIED（同进程）/ PARTIAL（跨线程/进程，见 §4） |
| 新 Agent / subagent 是否生成新的 initiator？ | 是。子 agent 自己的 `wakeDriver` 用 `withInitiator(this, …)` 建立自己的边界；子级执行时 `currentInitiator()` = 子 agent，父 agent 通过 `SubagentStartRequest.parent` 显式传入（`subagent/src/types.ts:110`）。 | VERIFIED |
| tool execution 是否继承？ | 是。直接工具调用在 `executeToolCalls` 内 `requireInitiator()` 后写入每个 `ToolExecutionInput.agent`（`tool-calls.ts:67-78`）。nested code-mode 调用复制外层 `exec.agent`（`code-mode.ts:471-480`）。 | VERIFIED |
| nested execution 是否 push/pop？ | ALS `.run()` 嵌套即 push/pop；`InitiatorRun.parent` 记录嵌套链供 teardown drain（`index.ts:640-651`）。 | VERIFIED（实现机制）/ 无对外 push/pop API |

### 2.2 真实调用链

```text
Agent A 被唤醒
  └─ ReactLoopAgent.wakeDriver()
       └─ ctx.agents.withInitiator(A, () => A.kick())     agent.ts:192
            └─ ALS.run(InitiatorRun{parent: 外层}, ALS.run(A, kick))
                 ├─ turn() → step() → buildRequest()      （继承 A）
                 ├─ executeToolCalls()
                 │    └─ ctx.agents.requireInitiator() = A  tool-calls.ts:67
                 │         └─ ToolExecutionInput { agent: A, signal, callId }
                 │              └─ ToolRuntime.createExecution()
                 │                   └─ rootCallId = exec.rootCallId ?? callId  index.ts:1368
                 │                        └─ nested code-mode sub-dispatch
                 │                             └─ 复制 agent + rootCallId + parent=token  code-mode.ts:471-480
                 └─ kick() 返回 → ALS 恢复外层             （runWithInitiator 计数释放）
```

---

## 3. Parent / Child Lineage

### 3.1 持久化 lineage（VERIFIED）

子 agent 会话的 `SessionHeader` 持久化四个 lineage 字段（`packages/core/session/src/types.ts:61-98`）：

| 字段 | 含义 |
| --- | --- |
| `parentSession?: SessionId` | 父 session id（fork/seed lineage） |
| `seedLength?: number` | 继承的父事件前缀长度；区分父历史与子工作 |
| `origin?: 'subagent'` | 粗粒度产品分类，仅导航用，不是 continuable 证明 |
| `delegationDepth?: number` | 递归预算；父 depth+1，持久化以在 restart/resume 后单调 |

写入点：`childSessionMeta(parent, childDepth, lineageSeedLength)`（`packages/subagent/subagent/src/child-agent.ts:101-121`）。深度计算：`resolveChildDepth(parent) = delegationDepthOf(parent) + 1`（`child-agent.ts:48-56`）；`delegationDepthOf = max(header.delegationDepth ?? 0, options.subagentDepth ?? 0)`（`subagent/src/depth.ts:29-42`）。因此**resume 的父级不能伪装成 top-level**。

### 3.2 进程内 spawn / fork（VERIFIED）

- `subagent-spawn-in-process`：子级全新 session，无 seed（`packages/subagent/subagent-spawn-in-process/src/index.ts:42-52`）。
- `subagent-fork-in-process`：子级以父 session 的**已完成 turn 前缀**为 seed，截到最后一个 `turn/end`，当前 in-flight turn 不入 seed（`packages/subagent/subagent-fork-in-process/src/index.ts:45-58`）。
- 子级创建统一走 `startInProcessRun` → `ctx.agents.create({ meta: childSessionMeta(...), seed?, agentOptions })`（`packages/subagent/subagent-in-process-driver/src/index.ts:90-130`）。
- 子级初始 turn 内追加 `subagent/descriptor` SessionEvent（mode/provider/label/可选 composition），log-only、不进模型历史、跨 compaction 保留（`subagent/src/descriptor.ts:30-65,298-316`；`subagent-in-process-driver/src/index.ts:78-86`）。

### 3.3 回答六问

1. **C 能否追溯到 B？** 能（进程内 session-backed）：C 的 `parentSession` = B.session.id；`tool/call|result` 在 C 自己的 session log 内。运行时 C 的 `exec.agent` = C。OUT-OF-PROCESS 子级（ACP/Codex/Claude/SDK）在 harness store 无子 Session，只有 parent-namespace run id（PARTIAL / NOT FOUND）。
2. **B 能否追溯到 A？** 能：header 链 `parentSession` 递归，`session-query.traceSession()` 从持久化 records 重建 ancestors/descendants，遇缺失 parent 返回 `complete:false`，遇环报 `SESSION_QUERY_INVALID_LINEAGE`（`packages/session-query/session-query/src/tracing.ts:100-240`）。
3. **是否存在显式 parent-child lineage？** 是（VERIFIED）：header 字段 + `subagent/descriptor` + `subagent/start|end`（后者为 Cordis 事件，见 §6）。
4. **lineage 是否写入 SessionEvent？** 部分：header 不是事件；`subagent/descriptor` 是事件但不含 parent id；事件级 lineage 是 `sourceEventSeqs` 与 `tool/code-dispatch*` 的 root/parent/sub call id（VERIFIED，§6）。
5. **lineage 是否影响 model-visible history？** 否。lineage 数据（header、descriptor、code-dispatch、boundaries）均不进 `deriveMessages()`；模型历史只有 `user/message`、`assistant/message`、`tool/result`（13/14；`descriptor.ts:37-43` 明确 "log-only: no surfaceOp, never enters model history"）。父级收到的 settlement notice 是**显式投递**的 `user/message`（source=`subagent-settled`），不是自动 lineage（`continuation.ts:1390-1450`）。
6. **lineage 是否仅用于 audit / attribution？** 还用于授权（cold resume 校验 exact live parent，`continuation.ts:878-930`）、递归预算（delegationDepth）、导航/枚举（`list-children`/`list-descendants`）、生命周期投递（settlement 发往 durable parent id）。所以不是纯 audit（VERIFIED）。

---

## 4. Async Propagation

| 边界 | 传播方式 | 状态 |
| --- | --- | --- |
| Promise / async（同进程） | `AsyncLocalStorage` 自动继承；`withInitiator` 包装整个 driver Promise | VERIFIED |
| task / job（同进程） | 工具执行时把 `exec.agent` 捕获为 `parent` 传给 job 的 `run()`；子 agent 的 `SubagentStartRequest.parent` 显式携带 | VERIFIED（显式字段）；ambient ALS 跨 job 是否保留无证据 → UNKNOWN |
| worker thread（code-runtime） | worker 只执行程序；工具 binding 经 `WorkerToHost.call` 回到 host 调度，host 侧 nested dispatch 显式复制 `agent`/`rootCallId`/`parent`（`code-runtime-worker-thread/src/protocol.ts:1-70`；`core/tools/src/code-mode.ts:471-480`） | VERIFIED（attribution 保留）；ALS 不跨线程 → NOT FOUND |
| subprocess subagent | 无 ALS 传播；父级通过 `SubagentStartRequest.parent`（进程内）或 cwd/provider/model（进程外）显式传递；进程外 run id 是 parent-namespace | PARTIAL |
| 共享 timer/queue/pool | `withoutInitiator()` 显式清边界，防止首个初始化者污染共享子系统（`schedule/src/runtime.ts:110`；`goal-round-driver/src/index.ts:215`） | VERIFIED |

关键结论：**DSH 的 async context ≠ 全量 causal propagation。** 同进程 Promise/async 用 ALS；跨 worker/subprocess/job 靠显式字段（`agent`、`parent`、`rootCallId`、`SubagentStartRequest.parent`），不依赖 ambient context。任何 Python 实现若宣称 async propagation，必须同时定义这两个机制。

---

## 5. Session / Turn / Step Binding

关系（复用 13/14/15）：

```text
Session（一个 append-only SessionEvent log，header.id = session id）
   └── Turn（turn/start … turn/end{reason}）
        └── Step（step/start … step/end；一次模型请求 + 该请求的工具活动）
             └── Tool Call（tool/call + tool/result，sourceEventSeqs 配对）
                  └── Initiator（运行时 exec.agent，不持久化）
```

绑定证据（VERIFIED）：

- `tool/call` data：`{ turn, step, callId, name, arguments }`（`packages/core/session/src/types.ts:279`）。
- `tool/result` data：`{ turn, step, message, error?, meta? }`，事件信封 `sourceEventSeqs` 指向 call seq（`types.ts:291-300`；`packages/core/agent-loop/src/tool-calls.ts:262-288`）。
- **sessionId 不在事件 data 内**：事件日志本身就是 session 的；`SessionHeader.id` 在持久化 header 中（`types.ts:61-98`）。
- **initiator_id 不在事件 data 内**：`exec.agent` 只在运行时对象，`appendToolCall` 不写它（`tool-calls.ts:260-268`）。
- nested code-mode 子调用事件带 `rootCallId/parentCallId/subCallId`，但**不带 turn/step**；step 归属由"追加在父 run_code 执行内"推导（`core/tools/src/types.ts:8-56`；`core/tools/src/code-mode.ts:510-540`）→ INFERENCE。

因此：一个 Tool Call **没有** `{session_id, turn_id, step_id, initiator_id}` 四字段同现记录（NOT FOUND）。它拥有的是：隐含 session（所在 log）+ 显式 turn/step + 运行时 `exec.agent`。**Initiator 是独立于 session/turn/step 对象的因果身份，且只在运行时存在。**

---

## 6. Event Persistence

### 6.1 什么持久化、什么不持久化

| 因果身份 | 持久化 | 证据 |
| --- | --- | --- |
| `currentInitiator`（Agent 对象/ALS） | 否 | 纯进程内；`packages/core/agent/src/index.ts:253-257,259` |
| `ToolExecutionInput.agent` | 否（`tool/call` 事件无此字段） | `core/agent-loop/src/tool-calls.ts:260-268`；`core/session/src/types.ts:279` |
| `ToolExecutionInput.rootCallId/parent/token` | 部分：`tool/code-dispatch-start`/`tool/code-dispatch` 持久化 root/parent/sub call id（仅 code-mode nested）；`parent` token 不落盘 | `core/tools/src/types.ts:8-56`；`core/tools/src/code-mode.ts:471-540` |
| Session 级 parent-child lineage | 是：`SessionHeader` 写入 JSONL header line（`session/session-persistence-jsonl/src/format.ts:30-105`），SQLite 同属持久化后端（复用 06 §1.4） | VERIFIED |
| `subagent/descriptor`（mode/provider/label/composition） | 是：SessionEvent，log-only | `subagent/src/descriptor.ts:30-65` |
| `subagent/start` / `subagent/end` | 否（SessionEvent 层面 NOT FOUND）：Cordis 生命周期事件，带 runId/provider/id/local，parent-scoped dispatch | `subagent/src/lifecycle.ts:86-160`；`subagent/src/invariant.ts:17-59` |
| 事件级 lineage `sourceEventSeqs` | 是（chunk→message、call→result、replace→replaced） | `core/session/src/types.ts:341-432`；13 ES-05 |

### 6.2 结论

**causal identity 持久化为两层，不是一条 initiator_id 字段：**

1. Session/Agent 层：`SessionHeader.parentSession/delegationDepth/seedLength/origin` + `subagent/descriptor`；
2. Event 层：`sourceEventSeqs`（同 session 事件间）+ `tool/code-dispatch*`（nested 工具调用树）。

`currentInitiator` 本身与 `exec.agent` **不持久化**。执行因果（谁发起的运行时引用）与历史投影（谁可以被 replay 推导为发起者）必须分开。

---

## 7. Replay / Fork

| 问题 | 答案 | 状态 |
| --- | --- | --- |
| causal identity 是否持久化？ | 会话级 lineage 持久化（header）；事件级 sourceEventSeqs 持久化；ambient initiator 不持久化 | PARTIAL |
| replay 时是否恢复？ | `SessionStore.create({seed})` / `ctx.agents.resume()` 恢复事件 + header；`session/end-seed` 标记继承边界；`session-query` 只读重放 | VERIFIED（事件/header 级） |
| fork 后 lineage 怎么处理？ | fork 子级 header 记 `parentSession` + `seedLength`，seed = 父已完成 turn 前缀；fork 前缀在创建时捕获一次，cold resume 重放子级自己的日志，不重新 fork 父新历史（`subagent-fork-in-process/src/index.ts:45-58,99-109`） | VERIFIED |
| compaction 是否影响 causal lineage？ | 事件日志 append-only，replacement 保留 `sourceEventSeqs`；compaction 只改 surface 投影；header lineage 独立于事件日志 | VERIFIED（复用 13 COMP-01/02/I-03） |
| event replacement 是否保留 causal identity？ | 是：replace 追加新事件，`sourceEventSeqs` 指向被替换节点（13 §3.2/§6） | VERIFIED |
| 运行时 initiator 链能否 replay？ | 否：不持久化，replay 只能从 session id + 事件顺序 + header lineage 重建"谁"的会话，不能重建 ambient context | NOT FOUND（恢复机制不存在） |

**execution causality 与 history projection 的区分**：可重放的是"事件 + 会话级 lineage + 显式 call 树"；不可重放的是"进程内 ambient initiator"。

---

## 8. Failure Attribution

Initiator 的归因能力（结合 08）：

| 对象 | Initiator 能否帮助定位 | 状态 |
| --- | --- | --- |
| Agent / Session | 能：`exec.agent` 或 `requireInitiator()` 给出精确 live Agent；失败事件落在该 agent 的 session log | VERIFIED |
| Turn / Step | 能：`tool/call`/`tool/result`/`turn/end` 带 turn/step（`core/session/src/types.ts:279-300`） | VERIFIED |
| Tool | 能到工具级：callId/name + error `{name,code}`（`tool-calls.ts:260-288`）；nested code-mode 可到 subCallId | VERIFIED（工具身份）/ PARTIAL（根因） |
| Model / Prompt / Skill / Capability | 否：无归因组件；`LlmFailure.code` 只到 model 错误类型；Prompt/Skill/Capability 无字段 | NOT FOUND（自动归因）/ PARTIAL（error code 粗分类） |
| Sandbox / Context | 粗分类：`SANDBOX_UNAVAILABLE`、`CONTEXT_WINDOW_EXCEEDED_CODE` 等 | PARTIAL |
| 根因（为什么这条 prompt/工具导致失败） | 否：08 结论 Level 2 + 部分 Level 3；无 root-cause 引擎 | NOT FOUND |

**当前 attribution level：Agent/Session/Turn/Step/Tool-identity 可精确定位（VERIFIED）；根因定位停在 error type/reason（PARTIAL）。** Initiator 把失败绑定到发起会话与调用位置，但不回答模型/prompt/skill/capability 层面的原因。

---

## 9. Ownership vs Causality

两者在源码中**显式正交**：

| 维度 | DSH 机制 | 证据 |
| --- | --- | --- |
| Ownership（谁负责生命周期） | `AgentRegistry.enter(agent, owner)`：owner = 创建该 agent 的 live agent 或 undefined（runtime root）；`isOwnedBy(id, owner)` 精确校验；`roots()` 过滤 owner===undefined。owner 独立于 durable session lineage | `packages/core/agent/src/index.ts:474-486,589-597,613-620` |
| Causality（谁触发了执行） | `currentInitiator()`/`requireInitiator()` ambient ALS + `ToolExecutionInput.agent`；工具注册/scope 是另一层"工具归属" | `core/agent/src/index.ts:305-330`；`core/tools/src/index.ts:314-330` |
| Tool ownership | `tools.register()/restrict()/guard()` = 注册/可见性/否决权（15 §13） | 15 §13 |
| 因果树 | `rootCallId/parent` = nested 工具调用归属（`createExecution` 默认 root=callId；code-mode 传播） | `core/tools/src/index.ts:1364-1390`；`code-mode.ts:471-480` |

源码原话：

- `enter()`：owner 是 "runtime ownership, not the resumed session's durable parent lineage"（`index.ts:470-473`）。
- initiator： "Ambient presence is neither liveness proof nor authorization; subjects and owners remain explicit"（`index.ts:253-257`）。

结论：**`owner_scope ≠ initiator`（VERIFIED）。** Python 实现不得把 capability/lifecycle owner 当作 causal initiator，也不得把 durable parentSession 当作 runtime owner。

---

## 10. Semantic Invariants

### CC-01..CC-08（最小 causal contract 设计）

| # | Invariant | Status |
| --- | --- | --- |
| CC-01 | Every attributed execution has a causal initiator or explicit root | VERIFIED（agent-driven tool path：`requireInitiator()` + `exec.agent`；nested：`rootCallId = rootCallId ?? callId`）。agentless path 无 ambient initiator，需要显式 agent 的工具会拒绝（`tool-subagent`、`send_message`） |
| CC-02 | Child execution preserves parent causal lineage | VERIFIED（session 级 header lineage + fork seed + descriptor）；PARTIAL（ambient initiator：子级 driver 用自己的 initiator，父级不继承） |
| CC-03 | Async boundaries preserve causal attribution where supported | PARTIAL（Promise/async 同进程 VERIFIED；worker/subprocess/job 靠显式 agent/parent/rootCallId，不靠 ALS） |
| CC-04 | Tool execution remains attributable to the initiating Agent/Step | VERIFIED（direct：exec.agent + turn/step 持久化）；PARTIAL（nested code-mode：agent 保留，step 归属由 enclosure 推导，事件无 turn/step） |
| CC-05 | Ownership and causality are independent dimensions | VERIFIED（§9 源码注释 + 两套机制） |
| CC-06 | Causal lineage does not automatically become model-visible context | VERIFIED（surface/deriveMessages 仅 user/assistant/tool-result；header/descriptor/code-dispatch/boundaries 全部 trace-only；settlement notice 是显式投递） |
| CC-07 | Replay preserves causality where source data supports it | VERIFIED（事件 + header + sourceEventSeqs + code-dispatch 树可重放）；UNKNOWN（ambient initiator 不可重放；跨 backend 顺序一致性仍是 13 §12-6） |
| CC-08 | Fork does not silently destroy parent lineage | VERIFIED（fork 前缀 + parentSession/seedLength/delegationDepth + cold resume 授权 exact parent） |

### 其他核心不变式（VERIFIED）

1. 每个 agent driver 只有一个进程内 initiator boundary，覆盖整条 kick 链（`agent.ts:192`）。
2. 直接工具调用的 `exec.agent` 恒等于 driver 的 initiator（`tool-calls.ts:67-78`）。
3. 子 agent 的 `parentSession` 恒等于创建时 `request.parent.session.id`（`child-agent.ts:101-121`；`types.ts:110`）。
4. 持久化 header lineage 是单调深度：resume 后 `delegationDepthOf` 取 header 与 options 的 max（`depth.ts:29-42`）。
5. `subagent/descriptor` 只追加一次且首个权威；log-only，不进模型历史（`descriptor.ts:298-316`）。
6. nested code-mode 的 subCallId→rootCallId 映射不可变（invariant 强制，`core/tools/src/invariant.ts:38-56`）。
7. ownership（registry owner）与 causality（initiator/exec.agent）不互推（§9）。

---

## 11. Verified Facts

1. `currentInitiator`/`requireInitiator`/`withInitiator`/`withoutInitiator` 存在且基于 `AsyncLocalStorage`（`core/agent/src/index.ts:259-264,309-357`）。
2. 设置点唯一（agent-loop driver）：`wakeDriver → withInitiator(this, kick)`（`agent.ts:192`）。
3. 工具执行从 ambient initiator 取 agent 并写入每个 `ToolExecutionInput.agent`（`tool-calls.ts:67-78`）。
4. `ToolExecutionInput` 有 `rootCallId?`/`parent?`；`ToolExecution` 有必填 `rootCallId` + registry token（`core/tools/src/index.ts:314-330,379-384`）。
5. code-mode nested dispatch 复制 `agent`/`rootCallId`/`parent`，并持久化 `tool/code-dispatch-start`/`tool/code-dispatch`（`code-mode.ts:471-540`；`core/tools/src/types.ts:8-56`）。
6. `SessionHeader` 持久化 `parentSession/seedLength/origin/delegationDepth/agentPreset`（`core/session/src/types.ts:61-98`；`session-persistence-jsonl/src/format.ts:30-105`）。
7. 子 agent 创建统一经 `childSessionMeta` 打 lineage/depth 标记（`child-agent.ts:101-121`）。
8. fork 子级 seed = 父已完成 turn 前缀；cold resume 不重 fork（`subagent-fork-in-process/src/index.ts:45-58,99-109`）。
9. `subagent/descriptor` 是持久化 SessionEvent；`subagent/start|end` 是 Cordis 生命周期事件（非 SessionEvent）（`descriptor.ts:30-65`；`lifecycle.ts:86-160`）。
10. cold resume 用 `loaded.meta.parentSession` 做 exact-live-parent 授权（`continuation.ts:878-930`）。
11. settlement notice 经 durable `parentSession` 投递为 `subagent-settled` source 的 user message（`continuation.ts:1390-1450`）。
12. `session-query.traceSession` 从持久化 header 重建祖先/后代树，缺失 parent 显式 partial、环显式失败（`session-query/src/tracing.ts:100-240`）。
13. `withoutInitiator` 用于共享子系统边界（schedule、goal-round）（`schedule/src/runtime.ts:110`；`goal-round-driver/src/index.ts:215`）。
14. 崩溃修复合成事件保留事件级可重放性；header lineage 独立于事件日志（复用 05 §1、13 §8）。
15. ownership 与 durable lineage/initiator 三向独立（`core/agent/src/index.ts:253-257,470-486`）。

## 12. Unknowns

| # | Unknown | 当前证据 | 状态 |
| --- | --- | --- | --- |
| 1 | 每个事件是否持久化 initiator_id | 无；`tool/call` 只有 turn/step/callId/name/arguments | NOT FOUND |
| 2 | ambient ALS 是否跨 job/task 队列自动保留 | 工具捕获 `parent` 显式字段；ALS 跨 `jobs.start` 的 run 回调传播无源码证据 | UNKNOWN |
| 3 | ALS 是否跨 worker MessagePort 回调自动传播 | 无依赖此路径的代码；nested dispatch 全部显式传 agent/rootCallId | NOT FOUND（不作为设计假设） |
| 4 | out-of-process（ACP/Codex/Claude/SDK）子级是否在子进程内记录 parentSession | 子 session id 在 wire 内私有；未发现 parentSession 传递 | NOT FOUND / UNKNOWN |
| 5 | `subagent/start|end` 是否有默认持久化消费者 | 只见 Cordis event + invariant + telemetry 消费；无 SessionEvent 落盘 | NOT FOUND |
| 6 | 崩溃后 initiator 链恢复 | 无机制；修复只合成事件 | NOT FOUND |
| 7 | nested code-mode 子调用的 step 归属字段 | 事件无 turn/step；由 enclosure 推导 | UNKNOWN（INFERENCE） |
| 8 | `subagent/descriptor` 在 compaction 替换后的保留 | append-only 语义推导保留；本轮未直接验证 | INFERENCE（Medium） |
| 9 | `currentInitiator` 在 Cordis fiber/effect 边界的精确传播 | 同进程 ALS 理论覆盖；Cordis fiber 机制未逐点验证 | INFERENCE（Medium） |
| 10 | 跨 backend（JSONL/SQLite）lineage 查询顺序/一致性 | 13 §12-6 未决 | UNKNOWN |

---

## 13. Python Runtime Requirements

只做需求提取，不实现。严格区分：

### 13.1 REQUIRED BY DSH（与源码语义对齐的最小集）

1. **Initiator identity**：一个 live agent/session 对象引用（或等价稳定 id + 对象解析），不是 traceId 字符串；API 形态 `current() -> Agent | None`、`require() -> Agent`。
2. **causal context**：进程内异步 context（Python 等价物：`contextvars.ContextVar` + `copy_context()`/`contextvars` 任务传播）；`with_initiator(agent, operation)` 与 `without_initiator(operation)` 语义；返回的 Promise/task 边界计数与 teardown drain。
3. **async propagation mechanism**：同进程 asyncio task/Promise 链自动继承；**跨线程/进程不得宣称自动传播**，必须在边界用显式字段（agent/parent/root_call_id）。
4. **parent-child chain**：持久化 session header 字段 `parent_session` / `seed_length` / `origin` / `delegation_depth`；子级创建时深度 = parent+1，resume 后取 max(header, runtime) 保持单调。
5. **session/turn/step binding**：`tool/call` 与 `tool/result` 事件携带 `turn`/`step`；result 用 `source_event_seqs` 指向 call；无需在事件内重复 session_id。
6. **event attribution**：工具执行对象携带 `agent` + 可选 `root_call_id`/`parent`；nested 调用必须复制 agent/root_call_id，必要时持久化 `tool/code-dispatch-start`/`tool/code-dispatch` 式事件（root/parent/sub call id）。
7. **ownership ≠ causality**：lifecycle owner、durable parent_session、runtime initiator 三个字段分开；不互推。
8. **replay/fork 契约**：fork seed 只取已完成 turn 前缀；header 记录 seed_length；cold resume 必须校验持久化 parent_session 与 exact live parent；replay 只保证事件/header 级因果，不保证 ambient context。
9. **失败归因边界**：只能声明"归因到 Agent/Session/Turn/Step/Tool-identity"，不得声明 Model/Prompt/Skill/Capability 根因。

### 13.2 DESIGN PROPOSAL（DSH 没有，Python 若加必须标注为扩展）

| 扩展 | 理由 |
| --- | --- |
| 每个事件持久化 `initiator_id` | DSH NOT FOUND；会让 replay 的因果归因更强，但改变事件 schema |
| OpenTelemetry spans / trace context 传播 | DSH 只有 opt-in OTel 日志，无 span/trace 语义（06 §1.4） |
| 跨进程 trace id / W3C propagation | DSH 子进程边界无此机制 |
| causal chain completion 事件（root→leaf→ack） | DSH 无；现有可观测物是 `tool/result`、`turn/end`、`subagent/end` 的组合 |
| 把 `subagent/start|end` 写成 SessionEvent | DSH 当前是 Cordis 生命周期事件；写入 session 会改变事件域（13 §13.3 open） |
| `step_id` 显式字段 | DSH 只有数字 turn/step + 嵌套顺序；显式 id 是 Python 扩展 |

---

## Final Verdict

**PARTIAL**

契约已冻结，且核心事实是源码直接确认的：`currentInitiator` = 进程内 live `Agent` 对象 + `AsyncLocalStorage` 异步 context（VERIFIED）；会话级 parent-child lineage 持久化并可在 replay/fork/cold-resume 中恢复（VERIFIED）；工具归因到 initiating agent/turn/step 在直接路径成立（VERIFIED）；ownership 与 causality 正交（VERIFIED）。

PARTIAL 的原因：

1. ambient initiator 不持久化，replay 只能重建会话/事件级因果，不能重建进程内 initiator 链；
2. cross-thread / subprocess / job 边界靠显式字段而非 ambient ALS，`async context = full causal propagation` 不成立；
3. out-of-process 子级在 harness store 无持久化 parent lineage 记录（NOT FOUND）；
4. nested code-mode 子调用的 step 归属无显式字段（INFERENCE）；
5. `subagent/start|end` 不落 SessionEvent。

PASS 需要：显式接受上述 UNKNOWN 为 Python 设计假设，并保证 Python 实现不把 "context propagation" 写成 "全量因果传播"。
