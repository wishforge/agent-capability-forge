# Codex Runtime Capture Point Archaeology

> 研究对象：yusing/codex（issue #32100 Orchestrated multi-agent mode PoC）
> 源码基线：`658630b2931ac841e2f1bc437daa1b931d173c0c`
> 本地 clone：`<tmp>/yusing-codex`
> 输入：`artifact-contract/verified-task-artifact-bundle-v0.md`、`codex-artifact/verified-task-artifact-archaeology.md`、`artifact-boundary-comparison.md`（均为冻结输入）
> 结论标记：`[SOURCE]` = 本次直接读源码验证；`[FROZEN]` = 冻结输入结论；`[OPEN]` = 当前源码无证据

---

# 1. Executive Summary

P0 的 OPEN 项中，有 3 项可以被推进到可执行的 capture point，2 项维持 OPEN，1 项获得了一个新的 EVENT_CAPTURE 通道：

1. **Final File Snapshot** → `RUNTIME_CAPTURE`。最终文件全文当前只存在于 `TurnDiffTracker` 内存（`baseline_by_path` / `current_by_path`，`turn_diff_tracker.rs:20-61`）与 workspace 磁盘；rollout 只持久化 unified diff。Builder 可以在 `run_sampling_request` 尾部（diff emit 之后、tracker drop 之前）按 diff 路径做磁盘快照；内存全文需要新增 accessor（可选 runtime change）。
2. **Final Phase Authority** → `RUNTIME_CHANGE`。最终有效 worker packet 是 `run_phases` 局部变量（`orchestrated.rs:199-410`），retry/supersede/truncation/signature-break 语义全部在内存；rollout 只有有序的 compact packet 文本，无法可靠反推最终权威状态。`[FROZEN]`
3. **Verification Command / Output** → `EVENT_CAPTURE`（opt-in）。root 阶段 exec 事件默认持久化；worker 阶段 exec 事件默认不持久化（`session/mod.rs:1831`），但已有 opt-in 通道：`CODEX_ROLLOUT_TRACE_ROOT` 开启后，`rollout-trace` 会把 `ExecCommandBegin/End`（含 command、stdout、stderr、exit_code、duration）写入 trace bundle，包括 worker 阶段（`rollout-trace/thread.rs:237-248`、`protocol_event.rs:260-274`）。
4. **Task Identity** → session/thread/turn 均为 `DIRECT`；`source_task_id` 维持 `OPEN`（本地 runtime 无 task 概念；wire 格式里的 `task_started`/`task_complete` 只是 turn 事件的别名，`protocol.rs:1322-1335`）。
5. **Environment Dependency** → 元数据 `DIRECT`（`TurnContextItem` + `WorldStateItem`）；dependency manifest `OPEN`。
6. **Secrets Boundary** → facts 已脱敏（`orchestrated_execution_facts.rs:297-316`）；packet / diff / stdout / stderr 均未脱敏；仓库内无通用 secrets scanner → v0 保持 `not_scanned + gap`，扫描实现 `OPEN`。
7. **Turn Completion / Builder Hook** → 唯一同时持有 final diff、root synthesis、identity、workspace 状态且 tracker 未 drop 的点是 `run_sampling_request` 尾部（`turn.rs:2518-2529`，root context）；final phase authority 需要额外 accumulator（`run_phases` 返回边界）。

**核心结论：Artifact Builder 的最佳 hook 是 `run_turn` → `run_sampling_request` 尾部（turn.rs:2527 之后）；最终 phase 权威必须由 `run_phases` 返回边界提供，不能从 rollout 猜。** `[FROZEN]`

---

# 2. Final File Snapshot Capture

## 2.1 逐问回答

1. **最终完整文件内容当前在哪里存在？**
   `TurnDiffTracker` 内存：`baseline_by_path` / `current_by_path`（`HashMap<TrackedPath, TrackedContent>`），`TrackedContent { content: String, revision: u64 }`（`turn_diff_tracker.rs:20-23, 53-54`）。同时以真实文件存在于 workspace 磁盘。**没有任何序列化全文**。

2. **是什么类型？**
   `TrackedContent { content: String, revision: u64 }`；`TrackedPath { environment_id: String, path: PathBuf }`（`turn_diff_tracker.rs:20-29`）。`content` 是 UTF-8 文本，不含二进制。

3. **生命周期从什么时候开始、什么时候结束？**
   每次 `run_turn` 调用创建（`turn.rs:210-212`），`run_turn` 返回时 drop（`turn.rs:489`）。注意：`RegularTask::run` 在 pending input 时会再次调用 `run_turn`（`tasks/regular.rs:73-88`），每次调用都是新 tracker —— 即 tracker 是 per run_turn call，不是 per user turn。磁盘文件继续存在。

4. **哪个函数可以读取？**
   diff：`TurnDiffTracker::get_unified_diff()`（`turn_diff_tracker.rs:115-117`）、`has_unified_diff()`（`:119-121`）。全文：**无公开 accessor**。`baseline_by_path` / `current_by_path` 是私有字段；同模块内部可读，外部只能通过新增方法。

5. **哪个函数之后这些内容会消失？**
   `run_turn` 返回（`turn.rs:489`）后 `Arc<TurnDiffTracker>` 被 drop。`invalidate()`（`turn_diff_tracker.rs:109-113`）只清 rendered diff / unified_diff，保留 baseline/current maps，但 `track_delta` 之后不再更新。

6. **是否只能获取 changed files？**
   是。tracker 只覆盖 apply_patch 路径；全文只对 `baseline_by_path ∪ current_by_path` 存在。未变更文件不在 tracker 中（但可以从磁盘读）。

7. **是否可以确定文件最终内容与 unified_diff 一致？**
   在 tracker 内部：一致。`unified_diff` 由同一 maps 渲染（`refresh_unified_diff`，`turn_diff_tracker.rs:123-183`），最终事件发送时再次 `get_unified_diff()`（`turn.rs:2518-2526`）。但 tracker 从不读磁盘（注释 `turn_diff_tracker.rs:48-49`）；非 exact delta 会 `invalidate()`（`turn_diff_tracker.rs:98-101`），之后无 diff；executable bit 不跟踪（mode 硬编码 `100644`，`turn_diff_tracker.rs:15`）。因此磁盘最终状态可能与 diff 不一致。

8. **是否存在外部进程修改 workspace 导致 snapshot 不一致？**
   存在且必然可能。`track_delta` 只消费 apply_patch delta（`turn_diff_tracker.rs:93-107`）；shell 命令（`echo > file`）、MCP、extension 写入、用户并发修改都不会进入 tracker。磁盘是最终权威，diff 是 apply_patch 变更的权威，两者可漂移。

9. **推荐的 capture point 是哪个 symbol？**
   `TurnDiffTracker::get_unified_diff`（diff）+ 新增 `TurnDiffTracker` 全文/路径快照 accessor（如需内存精确内容）；Builder 无 runtime change 的等价路径是：`run_sampling_request` 尾部按最终 diff 的路径从磁盘读。捕获位置：**`run_sampling_request` 尾部（turn.rs:2518-2527 之后，2529 return 之前，root context）**。

10. **capture 应该发生在 diff emit 前、后，还是 turn 完成后？**
    在 diff emit 之后、run_turn 返回之前。原因：diff emit 时 tracker 是最终状态（`turn.rs:2518-2527`）；turn 完成后 tracker 已 drop，只能读磁盘（仍可行，但拿不到 in-memory 精确内容）。

## 2.2 关键约束

- 单环境：diff 路径是相对 display root（git root 或 cwd）的显示路径（`turn_diff_tracker.rs:373-385`），可用 `TurnContextItem.cwd` 近似解析回磁盘路径；多环境会加 `{environment_id}/` 前缀（`:380-383`），display roots 本身（git root 探测，`turn.rs:493-509`）不持久化。
- deleted 文件无法从磁盘快照；只能靠 diff 头 `deleted file mode` 判定（`turn_diff_tracker.rs:337-341`）。
- renamed 在 tracker 中通过 `origin_by_current_path` 配对（`:291-307`），diff 表现为 origin→dest 的 pair，无显式 rename 头。

**Recommended Capture Point:**
`run_sampling_request` tail — `turn.rs:2518-2527`（root context），数据源 `TurnDiffTracker`（`turn_diff_tracker.rs:50-61`）+ 磁盘快照。

---

# 3. Final Phase Authority

## 3.1 逐问回答

1. **最终 worker packet 的 authoritative state 存在哪里？**
   `run_phases` 局部变量：`PhasePacket { text, truncated, execution_facts }`（`orchestrated.rs:65-69`），direct 路径在 `orchestrated.rs:224-267`，reviewed 路径在 `:346-403`。`Outcome`（Skipped/Completed/Stopped）由 `run_for_input` 返回（`orchestrated.rs:59-63, 149-197`）。全部在内存，不实现 serde，不持久化。

2. **一个 worker retry 多次后，哪个 packet 是最终有效 packet？**
   触发 `break` 的那一个：direct 路径 `!truncated && worker_status == Complete`（`orchestrated.rs:236-238`）；reviewed 路径 `worker_status == Complete && !review_packet.truncated && review_approved`（`:371-376`）；其它 break：evidence 循环（`:256-258`）、retry signature 重复（`:263-265, 379-383`）、owner root/user（`:401`）、truncated（`:303-304, 358-359`）、循环耗尽（`MAX_WORK_REVISIONS=2`，`:37`）。具体哪一个取决于运行期分支，rollout 无法可靠判定。

3. **ResultReview revise 后旧 packet 是否仍然存在？**
   存在。每个 phase 结束后 `compact_phase_history` 把 packet（含被 revise 的旧 worker packet）写入 history 并持久化到 rollout（`orchestrated.rs:617-655` → `replace_orchestrated_phase_history`，`session/mod.rs:2892-2907`）。

4. **superseded packet 怎么区分？**
   没有标记。rollout 中只有出现顺序；“哪个是最终有效”必须重放状态机，而 break 原因（signature 重复、truncated 布尔、Outcome）不在 rollout。`[FROZEN]`

5. **truncation 是否影响 final validity？**
   影响。direct 与 reviewed 路径都要求最终 packet `!truncated`（`orchestrated.rs:236, 358, 372`）；truncated packet 永远不能成为最终有效 packet。但 `truncated` 布尔不持久化，rollout 侧只能靠文本后缀反推（`:43-46, 694-718`），存在边界歧义。

6. **final phase authority 是否可以从 rollout 推断？**
   不能。`[FROZEN]` 具体原因：a) `truncated` 布尔不持久化；b) worker status Invalid 时无 review packet；c) retry signature 依赖 `facts.progress_signature`（`orchestrated.rs:412-425`），而 facts 片段只在有更新时写入且只保留最新快照（`:636-648`）；d) `Outcome::Stopped`（phase 内错误）不体现在 packet 序列里。

7. **如果不能，runtime capture 点是什么？**
   `run_phases` 返回边界（`orchestrated.rs:409`）或 `run_for_input` 的 `run_phases(...).await` 之后（`orchestrated.rs:170-197`）。此处捕获：最终 WorkerExec `PhasePacket`（text/truncated/execution_facts）、最终 ResultReview 判定（approved/revise+owner）、retry 计数、是否因 retry signature break、最终 `Outcome`。

## 3.2 明确结论

**不要从 rollout 猜最终有效 Worker Packet。** `[FROZEN]`

**Recommended Final Phase Capture Point:**
`run_phases` return boundary — `orchestrated.rs:409`（被 `run_for_input` 于 `orchestrated.rs:170-179` 调用处）。最小 runtime change：让 `run_phases` / `run_for_input` 返回最终 `PhasePacket` + 判定状态，或写入 `TurnContext` 上的 accumulator。

---

# 4. Verification Evidence

## 4.1 完整链路

```text
exec_command handler (exec_command.rs:109)
  → ledger begin (worker only, :197-229)
  → manager.exec_command (process_manager.rs:408)
  → ExecCommandToolOutput { exit_code, raw_output, wall_time, ... } (tools/context.rs:311-323)
  → ToolEmitter → CommandExecutionItem (protocol/items.rs:183-214)
  → ItemStarted/ItemCompleted + legacy ExecCommandBegin/End (tools/events.rs:95-125, 544-570; legacy_events.rs:156-200)
  → send_event (session/mod.rs:1778-1832)
      ├─ persist = orchestrated_role.is_none() (:1831)
      ├─ rollout-trace record_tool_call_event（无条件，需 CODEX_ROLLOUT_TRACE_ROOT）(rollout-trace/thread.rs:237-248)
      └─ 事件进 tx_event client channel (session/mod.rs:2018-2026)
  → worker 阶段结束后 compact_phase_history 丢弃原始工具历史 (orchestrated.rs:617-655)
```

## 4.2 逐问回答

1. **成功命令 exit code 在哪里？**
   `ExecCommandToolOutput.exit_code`（`tools/context.rs:320`）、`CommandExecutionItem.exit_code`（`protocol/items.rs:207`）、`ExecCommandEndEvent.exit_code`（`protocol.rs:3552`）、`ExecToolCallOutput.exit_code`（`protocol/exec_output.rs:41`）。成功命令 `exit_code == 0` 不产生 facts（`exec_command.rs:432-441`）。

2. **stdout 在哪里？**
   `CommandExecutionItem.stdout` / `ExecCommandEndEvent.stdout` / `ExecToolCallOutput.stdout`（`protocol/items.rs:198`、`protocol.rs:3545`、`exec_output.rs:42`）。worker 阶段：事件内瞬时存在；root 阶段：随事件持久化。

3. **stderr 在哪里？**
   同 stdout：`CommandExecutionItem.stderr`（`protocol/items.rs:201`）、`ExecCommandEndEvent.stderr`（`protocol.rs:3547`）、`ExecToolCallOutput.stderr`（`exec_output.rs:43`）。aggregated 输出在 `aggregated_output`（`protocol.rs:3550`）。

4. **command 原文在哪里？**
   `CommandExecutionItem.command: Vec<String>`（`protocol/items.rs:188`）、`ExecCommandBegin/EndEvent.command`（`protocol.rs:3506, 3532`）、`ExecCommandToolOutput.hook_command`（`tools/context.rs:322`）、`ExecCommandRequest.command`（exec_command.rs:407-426）。

5. **duration 在哪里？**
   `ExecToolCallOutput.duration`（`exec_output.rs:45`）、`CommandExecutionItem.duration`（`protocol/items.rs:210`）、`ExecCommandEndEvent.duration`（`protocol.rs:3555`）、`ExecCommandToolOutput.wall_time`（`tools/context.rs:314`）。

6. **是否存在统一结构体？**
   存在：`ExecToolCallOutput`（`protocol/exec_output.rs:40-47`）是统一执行结果；`CommandExecutionItem`（`protocol/items.rs:183-214`）是统一 UI/事件结构；`ExecCommandEndEvent`（`protocol.rs:3520-3560`）是统一持久化事件结构。三者均含 command/cwd/stdout/stderr/aggregated/exit_code/duration。

7. **生命周期到哪里结束？**
   worker 阶段：事件进 client channel +（opt-in）trace bundle；模型可见的函数响应进入 phase history，随后被 `compact_phase_history` 替换（`orchestrated.rs:617-655`）→ 默认 rollout 中消失。root 阶段：`orchestrated_role.is_none()` → 事件持久化到 rollout（`session/mod.rs:1831, 2006-2016`）。

8. **role phase 为什么/何时不持久化？**
   `send_event`：`let persist = turn_context.orchestrated_role.is_none();`（`session/mod.rs:1831`）；`record_conversation_items` 同样跳过（`:2886-2888`）。设计意图是内部 phase 流量压缩成有界 packet（`orchestrated.rs:617-655`；facts 文案明确 “Raw commands and tool output were discarded”，`orchestrated_execution_facts.rs:233-235`）。

9. **在不修改 Codex runtime 的情况下，Artifact Builder 能否获得这些数据？**
   部分可以：root 阶段直接读 rollout 的 `event_msg / exec_command_begin|end`（DIRECT）；worker 阶段默认 rollout 没有，若运行期设置 `CODEX_ROLLOUT_TRACE_ROOT`（`rollout-trace/thread.rs:44`），trace bundle 中有完整 `ExecCommandBegin/End`（含 stdout/stderr/exit_code/duration，`protocol_event.rs:147-258, 260-274`）→ EVENT_CAPTURE；无 trace 环境只能拿到 facts（失败类、脱敏、无输出）与 worker packet 文本声明 → OPEN。

10. **如果必须改 runtime，最小改动点是什么？**
    让 worker 阶段 exec 事件持久化：`session/mod.rs:1831` 的 `persist` 判定（例如对 `EventMsg::ExecCommandBegin/End` 放行）；或在 `exec_command.rs:431-443` 的 `Ok(response)` 分支写入 verification evidence（此时 exit_code + raw_output 都在手）。

## 4.3 A–E 分类

| 分类 | 内容 |
|---|---|
| A. 当前可从 rollout 读取 | root 阶段 `ExecCommandBegin/End` 事件、root 阶段 function response items、worker 失败 facts 片段、worker packet 文本声明 |
| B. 当前只在 runtime memory | worker 阶段 `ExecCommandToolOutput`（raw_output、exit_code、wall_time）与 `ExecToolCallOutput` |
| C. 当前事件可以捕获 | 全部阶段 `EventMsg::ExecCommandBegin/End`（tx_event 流）；`CODEX_ROLLOUT_TRACE_ROOT` 开启时持久化为 trace bundle |
| D. 当前已经丢失 | 无 trace 时 worker 阶段 stdout/stderr、成功 exit code、命令原文（phase 压缩后） |
| E. 需要 runtime change | 默认 rollout 持久化 worker 阶段 exec 事件（`session/mod.rs:1831`）或 verification evidence 结构化写入 |

**Verification Capture Feasibility:**
`EVENT_CAPTURE`（`CODEX_ROLLOUT_TRACE_ROOT` opt-in；root 阶段直接读 rollout）。无 trace 时 worker 阶段为 `OPEN`；默认持久化需要 `RUNTIME_CHANGE`。

---

# 5. Task Identity

## 5.1 逐问回答

1. **session_id 的来源**
   `SessionMeta.session_id: SessionId`（`protocol.rs:3056`）。创建时 `RolloutRecorderParams::new` 设 `session_id = conversation_id.into()`（`recorder.rs:179-181`），即本 fork 中 session_id == thread_id（UUIDv7）。旧 rollout 缺 `session_id` 时从 `id` 回填（`protocol.rs:3158-3164`）。持久化于 `session_meta` item。

2. **thread_id 的来源**
   `ThreadId`（`protocol/thread_id.rs:16-18`，UUIDv7）；`SessionMeta.id: ThreadId`（`protocol.rs:3057`）；rollout 文件名 `rollout-{ts}-{conversation_id}.jsonl`（`recorder.rs:1519`），`conversation_id` 类型即 `ThreadId`（`recorder.rs:1492, 170`）。

3. **turn_id 的来源**
   `TurnContext.sub_id`（`turn_context.rs:105`）。真实用户 turn：请求处理器生成 UUIDv7（`handlers.rs:218`；`session/mod.rs:1240`）；内部 auto-compact：`auto-compact-N`（`session/mod.rs:1230-1235`）。持久化于 `TurnContextItem.turn_id`（`turn_context.rs:381`）、packet 消息 passthrough（`session/mod.rs:2817-2820`）、`OrchestratedRoleUpdatedEvent.turn_id`（`protocol.rs:1994`）、`TurnCompleteEvent.turn_id`（`tasks/mod.rs:770`）。

4. **task_id 是否真实存在**
   本地 orchestrated runtime 不存在 task 概念。`rg task_id` 命中均为独立 crate `codex-cloud-tasks` / `backend-client`（云任务子系统），不接入本地 session。wire 协议中 `EventMsg::TurnStarted` serde 别名 `task_started`、`TurnComplete` 别名 `task_complete`（`protocol.rs:1322-1323, 1333-1335`）——wire 上的 “task” 就是 turn。`[SOURCE]`

5. **如果不存在，哪个字段最接近 source_task_id？**
   最近似的是 `thread_id`（一次任务执行的容器），但禁止用 thread_id 冒充 source_task_id（`[FROZEN]` 契约 §5.2）。v0 保持 null + gap。

6. **source_execution_id 应该使用什么？**
   运行时不存在；由 Artifact Builder 在 capture 时分配（每次 `run_turn` 捕获会话一个 execution id），与 session/thread/turn/bundle id 均不同。`[FROZEN]`

7. **哪些字段 runtime 已持久化？**
   session_id、thread_id（SessionMeta + 文件名）、turn_id（TurnContextItem + packet passthrough + 事件）、cwd/workspace_roots/network/permission（TurnContextItem）、model（TurnContextItem.model）。全部在 rollout。

8. **哪些字段只能在 capture 时绑定？**
   `source_execution_id`、`generated_at`（执行完成时刻）、Builder 的 bundle_id。`source_task_id` 在 runtime 增加 task 概念前永远 null。

## 5.2 Task Identity Mapping Matrix

| Bundle 字段 | Runtime 真实字段 | 来源（file:symbol:line） | 持久化 | 映射判定 |
|---|---|---|---|---|
| `session_id` | `SessionMeta.session_id` | `protocol.rs:3056 SessionMeta`；`recorder.rs:179-181`（= thread_id） | rollout `session_meta` | DIRECT |
| `thread_id` | `SessionMeta.id` / rollout 文件名 `conversation_id` | `protocol.rs:3057`；`recorder.rs:1519` | rollout | DIRECT |
| `turn_id` | `TurnContext.sub_id` | `turn_context.rs:105, 381`；`session/mod.rs:2817-2820`；`tasks/mod.rs:770` | rollout | DIRECT |
| `source_task_id` | 无 | 本地 session 无 task 概念；cloud-tasks `TaskId` 不接入 | — | OPEN（null + gap） |
| `source_execution_id` | 无 | 需 Builder 分配 | capture 时 | RUNTIME_CAPTURE |
| task-contract phase identity | 无独立 id；phase 名称 + turn_id | `orchestrated.rs:48-57 Phase`；packet 消息 passthrough `turn_id`（`session/mod.rs:2819`） | rollout packet | turn_id 可绑定，无 task id |
| wire “task” 语义 | `TurnStarted`/`TurnComplete` 别名 | `protocol.rs:1322-1323, 1333-1335` | rollout event | 是 turn 的别名，非 task |

---

# 6. Environment Dependency

## 6.1 逐问回答

1. **当前 runtime 能知道哪些环境事实？**
   `TurnContextItem`：cwd、workspace_roots、approval_policy、sandbox_policy、permission_profile、network（allowed/denied domains）、current_date、timezone、model、effort、collaboration_mode、multi_agent_mode（`protocol.rs:3249-3293`）。`WorldStateItem`：环境快照渲染（cwd/shell/status/network/filesystem/subagents，`world_state/environment.rs:246-290`）。运行时另有 `TurnEnvironmentSnapshot`（environment_id、cwd、shell，`turn_context.rs:119`）和每命令 `CommandExecutionItem.cwd`。

2. **cwd 是否权威？**
   `TurnContextItem.cwd` 是 session/turn 根 cwd 的权威持久化值（`turn_context.rs:376-383`）；但每个命令可用 `workdir` 覆盖，实际执行 cwd 在 `ExecCommandBeginEvent.cwd` / facts `effectiveCwd`（`protocol.rs:3508`；`orchestrated_execution_facts.rs:241`）。对命令级依赖，TurnContext.cwd 不是权威。

3. **workspace_roots 是否权威？**
   是（权限 profile 物化语义，`protocol.rs:3254-3257`；`environment_context.rs:34-44`）。但 diff 的 display root 是 git root 探测结果（`turn.rs:493-509`），不持久化；多环境时 diff 路径带 environment_id 前缀（`turn_diff_tracker.rs:373-385`），反向解析需要运行时 display roots。

4. **network policy 是否权威？**
   `TurnContextNetworkItem.allowed_domains / denied_domains` 持久化（`protocol.rs:3239-3243`），是 turn 级网络策略权威；实际网络请求经过 managed proxy，执行记录中不枚举每次请求域名。

5. **permission profile 是否权威？**
   是（turn 级）；但命令可请求 `sandbox_permissions` / `additional_permissions` override（`exec_command.rs:305-374`），这些 override 不持久化。

6. **是否能枚举实际使用过的环境依赖？**
   不能完整枚举。可近似：rollout/trace 中 `ExecCommandBegin/End` 的 command + cwd + shell（root 阶段；worker 阶段需 trace）；facts 只有失败类 fingerprint。无完整命令清单。

7. **是否能枚举环境变量依赖？**
   不能。`shell_environment_policy`（`protocol/shell_environment.rs`）是配置，不随 turn 持久化；`ExecCommandRequest.env`（`process_manager.rs:1108-1119`）不写入事件。

8. **是否能枚举 secret 依赖？**
   不能，且不应枚举。facts 对疑似 secret 路径直接 `<redacted>`（`orchestrated_execution_facts.rs:297-316`）。

9. **是否有 dependency manifest？**
   无。`[SOURCE]` `dependency_manifest_ref` 保持 null + gap（契约 §10）。

10. **哪些只能保持 OPEN？**
    依赖清单（env vars、secrets、隐式工具链/运行时依赖）、可重建的环境快照语义。

## 6.2 三类概念区分

| 概念 | 现状 | 载体 |
|---|---|---|
| Environment Metadata | DIRECT | `TurnContextItem`（protocol.rs:3249-3293）、`WorldStateItem`（protocol.rs:3188-3194）、`TurnContextNetworkItem` |
| Environment Dependency Manifest | OPEN | 不存在；`dependency_manifest_ref = null + gap` |
| Environment Snapshot | RUNTIME_CAPTURE | Builder 在 turn 结束写 `environment/snapshot.json`（契约 §10.1）；runtime 本身无此文件 |

---

# 7. Secrets Boundary

## 7.1 逐问回答

1. **facts 哪些已经脱敏？**
   cwd/path/executable 经 `safe_path`（`orchestrated_execution_facts.rs:297-316`）：含 `://`、`@`、`?`、`#`、`=` 的路径整体替换为 `<redacted>`，控制字符替换，截断 120 字节；command 原文只存 Sha1 fingerprint（`:49-60`）；测试证明 URL 与 `--password super-secret-value` 不进入渲染（`orchestrated_execution_facts_tests.rs:19-48`；`multi_agent_mode.rs:598-601`）。

2. **worker packet 哪些没有脱敏？**
   全部没有。packet 是模型自由文本（`orchestrated.rs:65-69`），运行时无 secrets 过滤；packet 文本原样写入 rollout（`session/mod.rs:2905`）。

3. **unified diff 是否可能包含 secrets？**
   是。diff 是文件内容（`turn_diff_tracker.rs:309-366`），无任何脱敏；文件里若有 token/secret 则进 rollout。

4. **stdout/stderr 是否可能包含 secrets？**
   是。`ExecCommandEndEvent.stdout/stderr/aggregated_output`（`protocol.rs:3544-3550`）与 rollout-trace payload（`protocol_event.rs:198-217`）均为原样文本，仅截断不脱敏。

5. **Bundle sealing 前还是 artifact capture 前做 scan？**
   两者都应是 seal 前：scan 覆盖 inline 内容（packet、diff、root synthesis、metadata）与将要引用的外部 artifact（files、stdout/stderr、snapshot），scan 通过后才能计算 `bundle_digest` 并 seal。`[FROZEN]` 契约 §16.5。

6. **v0 应该 fail / redact / reject / not_scanned + gap？**
   `not_scanned + gap`。契约 Validation Rule 11 冻结：`scan_status=not_scanned` ⇒ `gaps` 含 `secrets_scan`；未实现 scanner 前禁止声称 scanned。`[FROZEN]`

7. **最小实现在哪里？**
   Builder 侧（seal 前策略），不属 runtime；若未来改 runtime，最小点是 packet/diff 生成处（`orchestrated.rs:627-635`、`turn_diff_tracker.rs:335-365`）。v0 不实现。

8. **是否已有可复用 scanner？**
   没有通用 scanner。`thread_resume_redaction.rs` 只是针对远程客户端的 MCP/image 响应脱敏（`app-server/src/request_processors/thread_resume_redaction.rs:6-39`），不扫描 packet/diff/output；`safe_path` 是私有、facts 专用。不能凭常识发明 scanner；源码无 → OPEN。`[SOURCE]`

---

# 8. Turn Completion

## 8.1 候选点比较

| 候选 | 含义 | 能否拿到 final phase authority | final diff | root synthesis | identity | workspace state | 评价 |
|---|---|---|---|---|---|---|---|
| A. WorkerExec 完成 | `orchestrated.rs:236-238` / `371-375` break | 部分（worker packet 在局部） | 否（后续 root 采样可能再改文件） | 否 | 是 | 否 | 太早 |
| B. ResultReview approved | `orchestrated.rs:371-376` | 部分（review packet 在局部） | 否 | 否 | 是 | 否 | 太早 |
| C. run_phases 完成 | `orchestrated.rs:409` | 是（唯一权威点） | 否 | 否 | 是 | 否 | final-phase 权威在此，其余不足 |
| D. root synthesis 完成 | `run_turn` loop `!needs_follow_up` break（`turn.rs:402-445`） | 否（已丢） | 已由 `run_sampling_request` 内部 emit（`turn.rs:2518-2526`），tracker 仍活 | 是（`last_agent_message`） | 是 | tracker + 磁盘 | 接近，但 final-phase 已丢 |
| E. entire run_turn 完成 | `turn.rs:489` 返回 | 否 | 事件已持久化，tracker 已 drop | 是 | 是 | 仅磁盘 | tracker 全文丢失 |

## 8.2 逐问回答

1. **哪个点意味着 task execution 已经完整结束？**
   `run_turn` 返回（`turn.rs:489`）之后、`on_task_finished` 发出 `TurnComplete` 时（`tasks/mod.rs:563-777`）是完整结束；若按“阶段执行完成”算，`run_phases` 返回（`orchestrated.rs:409`）是 orchestrated task 执行完成的点，但 root synthesis 尚未发生。

2. **哪个点能同时拿到 final phase authority、final diff、root synthesis、identity、workspace state？**
   没有任何单点。最接近的组合：final phase authority 在 `run_phases` 返回边界（`orchestrated.rs:409`）；final diff + root synthesis + identity + tracker/workspace 在 `run_sampling_request` 尾部（`turn.rs:2518-2527`）。两者之间隔着 root sampling，必须把 authority 从 `run_phases` 带出来（accumulator 或返回值）。

3. **哪个点不会丢失 runtime-only execution evidence？**
   `run_phases` 返回边界捕获 authority；`run_sampling_request` 尾部捕获文件快照。命令级证据需要在 exec 事件发生时订阅（trace/event 流），两个点都无法恢复已压缩的 worker 工具输出。

4. **哪个点最适合作为未来 Artifact Builder hook？**
   `run_sampling_request` 尾部（`turn.rs:2518-2527`，root context：`turn_context.orchestrated_role.is_none()`），在 TurnDiff emit 之后、return 之前。理由：tracker 未 drop、最终 diff 已生成、`SamplingRequestResult.last_agent_message`（root synthesis）在 `outcome` 中、`turn_context` 完整、磁盘 workspace 未变。final-phase authority 通过 `run_phases` 返回边界提前捕获后一起组装。

5. **是否需要在 turn 内建立 accumulator？**
   需要，但范围很小：只对 final phase authority（最终 worker/review packet + retry/truncation/signature 状态）和（如走事件流）verification evidence。文件快照与 root synthesis 不需要 accumulator。

---

# 9. Recommended Artifact Builder Hook

**exact symbol：** `run_sampling_request`（`turn.rs:1142`）尾部的 TurnDiff emit 块之后 —— `turn.rs:2518-2527`，条件 `turn_context.orchestrated_role.is_none()`（root context）。

理由：

1. 此处 `TurnDiffTracker` 仍被 `turn_diff_tracker` 参数持有（`turn.rs:1146`），`get_unified_diff()` 返回最终 net diff（`turn.rs:2519-2522`）；
2. `SamplingRequestResult.last_agent_message`（root synthesis）已确定（`turn.rs:2020, 2311-2337`）；
3. `turn_context` 提供全部 identity 与 environment metadata（`turn_context.rs:376-390`）；
4. 此时点之后，tracker 在 `run_turn` 返回时 drop（`turn.rs:489`），runtime-only 全文从此消失；
5. final phase authority 需由 `run_phases` 返回边界（`orchestrated.rs:409`）提供，通过 accumulator 带到这里 —— 这是唯一需要 runtime change 的部分。

若不允许改 runtime：Builder 在 turn 结束后从 rollout（packet/diff/identity）加磁盘快照（按 diff 路径）组装；final_phase 保持 null + gap，verification 保持 unknown + gap（契约 v0 语义不变）。`[FROZEN]`

---

# 10. P0 Open Items Resolution Matrix

| P0 OPEN | Current Evidence | Capture Point | Status | Required Runtime Change | P1 Impact |
|---|---|---|---|---|---|
| Final File Snapshot（`files[]` 全文 + digest + content_ref） | `TurnDiffTracker.baseline_by_path/current_by_path` 内存全文（`turn_diff_tracker.rs:20-61`）；不序列化；磁盘文件存在 | `run_sampling_request` 尾部（`turn.rs:2527`，root）按最终 diff 路径做磁盘快照；或新增 tracker accessor 取内存全文 | RUNTIME_CAPTURE | 不需要（磁盘快照）；内存精确内容需 accessor（可选） | P1 entrypoint extraction / private-state removal 依赖最终全文；多环境 display roots 不持久化，需 capture 时绑定 |
| Final Phase Authority | `run_phases` 局部 `PhasePacket` + retry/signature/Outcome（`orchestrated.rs:199-410, 412-425`）；rollout 只有有序 packet 文本，不能反推 `[FROZEN]` | `run_phases` 返回边界（`orchestrated.rs:409`）→ accumulator → builder hook | RUNTIME_CHANGE | 需要：`run_phases`/`run_for_input` 返回最终权威结构或写 TurnContext accumulator | P1 validation Rule 8（final_phase 非 null）依赖；无则 v0 final_phase=null |
| Verification Command / Output | root 阶段 `ExecCommandBegin/End` 已持久化（`session/mod.rs:1831`）；worker 阶段默认丢失；opt-in `CODEX_ROLLOUT_TRACE_ROOT` 全阶段持久化（`rollout-trace/thread.rs:44, 237-248`；`protocol_event.rs:260-274`） | 事件订阅（`EventMsg::ExecCommandBegin/End`，`protocol.rs:1381-1389`）或 trace bundle；最小 runtime change：`session/mod.rs:1831` 放行 exec 事件 | EVENT_CAPTURE（trace opt-in）；默认 rollout 仅 root 阶段 DIRECT，worker 阶段 OPEN | 默认 worker 阶段持久化需要（`session/mod.rs:1831`）；trace env 是部署配置 | P1 契约 extraction / test generation 需要命令级证据；无则 status=unknown |
| Task Identity（source_task_id） | 本地 runtime 无 task 概念；wire `task_started/task_complete` 是 turn 别名（`protocol.rs:1322-1335`）；session/thread/turn 全部 DIRECT | capture 时绑定 `source_execution_id`；`source_task_id` 无来源 | OPEN（source_task_id）/ DIRECT（session/thread/turn） | 未来 runtime task 概念才需要 | 阻止跨任务归因；v0 null + gap |
| Environment Dependency | 元数据 DIRECT（`TurnContextItem`，`protocol.rs:3249-3293`；`WorldStateItem`，`protocol.rs:3188-3194`）；无 manifest；env/secrets 依赖不可枚举 | Builder 写 `environment/snapshot.json`（契约 §10.1）；manifest 无来源 | DIRECT（metadata）/ OPEN（manifest） | manifest 需要 runtime 记录命令 env | replay / contract extraction 依赖；v0 `dependency_manifest_ref=null` |
| Secrets Boundary | facts 脱敏（`orchestrated_execution_facts.rs:297-316`）；packet/diff/output 未脱敏；无通用 scanner | seal 前 scan（Builder 侧）；v0 `not_scanned + gap` | OPEN（scanner 实现） | Builder 侧实现；runtime 无需 | Bundle 进入 Capabilityizer 前的泄露风险；v0 marker 合法 |
| Turn Completion / Builder Hook | `run_sampling_request` 尾部同时持有 final diff + synthesis + identity + tracker（`turn.rs:2518-2527`）；`on_task_finished` 为 lifecycle 终点（`tasks/mod.rs:563-777`） | `run_sampling_request` 尾部（root context）+ `run_phases` 返回边界 | RUNTIME_CAPTURE（hook 位置已定） | final-phase accumulator 需要 | Builder 实现时序（P1 首个任务） |
| `source_execution_id` / `generated_at` | runtime 无该字段 | Builder capture 时分配（同一 hook） | RUNTIME_CAPTURE | 不需要 | 无；v0 字段已冻结 |

---

# 11. P1 Risks

1. **最终文件快照漂移**：tracker 不读磁盘（`turn_diff_tracker.rs:48-49`），外部进程写入不会进 diff；Builder 磁盘快照与 `unified_diff` 可能不一致 → 需在 Bundle 中明确 `files[]` 来源为“磁盘最终状态”，diff 为“apply_patch 变更”，并记录 gap。
2. **多环境路径不可逆**：diff display path 的多 environment 前缀（`turn_diff_tracker.rs:380-383`）依赖未持久化的 display roots（`turn.rs:493-509`）→ capture 时不绑定就无法还原磁盘路径。
3. **final phase authority 缺失**：不改 runtime 则 v0 只能 `final_phase=null`，Rule 8 的 ordering/finality 校验无法执行。
4. **worker 阶段验证证据依赖 opt-in 环境变量**：`CODEX_ROLLOUT_TRACE_ROOT` 是部署配置；未开启时 P1 拿不到命令级证据，只能退到 packet 文本声明。
5. **secrets 边界不一致**：packet/diff/stdout 未脱敏而 facts 已脱敏；Bundle 若直接内嵌 packet/diff，泄露面在 Capabilityizer 之前无法收敛。
6. **run_turn 多次调用**：pending input 会触发新 tracker（`tasks/regular.rs:73-88`），单个用户 turn 可能产生多个 run_turn 快照；Bundle 的“一次执行”边界必须明确为 per run_turn call。
7. **rollout-trace 不是默认 rollout**：trace bundle 与 rollout JSONL 是两条持久化路径（`rollout-trace/thread.rs:44-118`），Builder 需要同时消费两个来源，或部署时强制开启 trace。

---

# 12. Evidence Index

## 源码（yusing/codex @ 658630b）

| 文件 | 行 | Symbol / 内容 |
|---|---|---|
| `codex-rs/core/src/session/orchestrated.rs` | 36-46 | `MAX_WORK_REVISIONS=2`、`MAX_PACKET_BYTES=8192`、truncated 后缀常量 |
| 同文件 | 48-76 | `Phase`、`Outcome`、`PhasePacket` |
| 同文件 | 149-197 | `run_for_input`（Outcome 映射、phase error → Stopped） |
| 同文件 | 199-410 | `run_phases`（direct/reviewed、retry、ResultReview、supersede） |
| 同文件 | 412-425 | `retry_signature` / `worker_retry_signature` |
| 同文件 | 435-483 | `correction_owner` / `review_approved` / `worker_status` / `packet_has_status` |
| 同文件 | 512-604 | `run_phase`（baseline、role context、采样循环） |
| 同文件 | 617-655 | `compact_phase_history`（packet + facts 片段 + replace/persist） |
| 同文件 | 657-718 | `phase_packet` / `truncate_packet` |
| `codex-rs/core/src/session/turn.rs` | 142-489 | `run_turn`（tracker 生命周期 210-212；phase 后 root 循环 239-267） |
| 同文件 | 493-509 | `turn_diff_display_roots`（display roots 不持久化） |
| 同文件 | 1142-1151 | `run_sampling_request` 签名 |
| 同文件 | 2026-2027, 2311-2337 | `should_emit_turn_diff` 置位 / `last_agent_message` |
| 同文件 | 2518-2529 | 最终 `TurnDiff` emit → return（推荐 hook 点） |
| `codex-rs/core/src/turn_diff_tracker.rs` | 20-61 | `TrackedContent` / `TrackedPath` / `TurnDiffTracker`（全文 maps） |
| 同文件 | 93-117 | `track_delta` / `invalidate` / `get_unified_diff` |
| 同文件 | 123-183 | `refresh_unified_diff` |
| 同文件 | 309-366 | `render_diff`（unified diff + blob oid，mode 硬编码） |
| 同文件 | 373-385 | `display_path`（多 environment 前缀） |
| `codex-rs/core/src/session/mod.rs` | 1778-1832 | `send_event`：role 抑制 + `persist = orchestrated_role.is_none()` |
| 同文件 | 2006-2016 | `send_event_raw_with_persistence` → `RolloutItem::EventMsg` |
| 同文件 | 2810-2826 | `prepare_conversation_items_for_history`（turn_id passthrough + item id） |
| 同文件 | 2871-2907 | `record_conversation_items`（role 不持久化）/ `replace_orchestrated_phase_history`（packet 持久化） |
| 同文件 | 3127-3129, 3725-3728 | `RolloutItem::TurnContext` 持久化 |
| `codex-rs/core/src/session/turn_context.rs` | 105 | `sub_id` |
| 同文件 | 376-390 | `to_turn_context_item`（turn_id = sub_id） |
| `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs` | 197-229 | worker ledger begin / suppress |
| 同文件 | 376-402 | `intercept_apply_patch`（tracker 传入） |
| 同文件 | 431-443 | `record_exit`（仅 exit_code != 0） |
| `codex-rs/core/src/tools/context.rs` | 39, 311-323 | `SharedTurnDiffTracker` / `ExecCommandToolOutput` |
| `codex-rs/core/src/tools/events.rs` | 95-125 | `emit_exec_command_begin` → `CommandExecutionItem` |
| 同文件 | 467-570 | `ExecCommandResult` / `emit_exec_end` |
| 同文件 | 572-621 | `emit_patch_end`（track_delta + TurnDiff） |
| `codex-rs/core/src/context/orchestrated_execution_facts.rs` | 8-47 | Facts / Fact / Outcome / Ledger |
| 同文件 | 49-60 | fingerprint（Sha1(command+cwd)） |
| 同文件 | 216-266 | marker 渲染（“Raw commands and tool output were discarded”） |
| 同文件 | 297-316 | `safe_path`（脱敏） |
| `codex-rs/core/src/context/environment_context.rs` | 11-72 | `FileSystemContext`（roots + profile，无文件内容） |
| `codex-rs/core/src/context/world_state/environment.rs` | 246-290 | 环境渲染（cwd/shell/status） |
| `codex-rs/core/src/tasks/regular.rs` | 37-89 | `RegularTask::run`（run_turn 循环） |
| `codex-rs/core/src/tasks/mod.rs` | 563-800 | `on_task_finished`（TurnComplete 发出点） |
| `codex-rs/protocol/src/protocol.rs` | 1279-1429 | `EventMsg`（TurnDiff 1429；ExecCommandBegin/End 1381/1389） |
| 同文件 | 3055-3103 | `SessionMeta`（session_id / id） |
| 同文件 | 3134-3168 | `SessionMetaLine`（session_id 回填） |
| 同文件 | 3171-3186 | `RolloutItem` serde |
| 同文件 | 3239-3293 | `TurnContextNetworkItem` / `TurnContextItem` |
| 同文件 | 3494-3560 | `ExecCommandBeginEvent` / `ExecCommandEndEvent` |
| 同文件 | 3688-3691 | `TurnDiffEvent` |
| `codex-rs/protocol/src/items.rs` | 183-214 | `CommandExecutionItem` |
| `codex-rs/protocol/src/exec_output.rs` | 40-47 | `ExecToolCallOutput`（统一结构） |
| `codex-rs/protocol/src/legacy_events.rs` | 156-200 | `CommandExecutionItem::as_legacy_begin/end_event` |
| `codex-rs/protocol/src/thread_id.rs` / `session_id.rs` | 16-18 / 15-17 | `ThreadId` / `SessionId` |
| `codex-rs/rollout/src/recorder.rs` | 1498-1527 | 文件名 `rollout-{ts}-{conversation_id}.jsonl` |
| `codex-rs/rollout-trace/src/thread.rs` | 44 | `CODEX_ROLLOUT_TRACE_ROOT` |
| 同文件 | 237-248 | `record_tool_call_event`（全阶段，opt-in） |
| `codex-rs/rollout-trace/src/protocol_event.rs` | 147-258 | `ExecCommandBegin/EndTracePayload`（stdout/stderr/exit_code/duration） |
| 同文件 | 260-274 | `tool_runtime_trace_event` 匹配 |
| `codex-rs/app-server/src/request_processors/thread_resume_redaction.rs` | 6-39 | 仅远程客户端 MCP/image 响应脱敏，非通用 scanner |

---

# 13. Final Answers

1. **Artifact Builder 最适合挂在哪个 exact symbol？**
   `run_sampling_request` 尾部 TurnDiff emit 之后（`turn.rs:2518-2527`，root context：`turn_context.orchestrated_role.is_none()`）；final phase 权威由 `run_phases` 返回边界（`orchestrated.rs:409`）提供。

2. **是否需要 runtime accumulator？**
   只需要一个极小的：final phase authority（最终 worker/review PhasePacket、retry 计数、signature-break 原因）。文件快照、root synthesis、identity 不需要 accumulator。

3. **最终文件 snapshot 怎么拿？**
   在 hook 点按最终 `unified_diff` 的路径从磁盘读取并做 sha256（deleted 除外）；要内存精确内容需给 `TurnDiffTracker` 加 accessor（`turn_diff_tracker.rs:53-54` 的 maps 目前私有）。

4. **final phase authority 怎么拿？**
   让 `run_phases`（`orchestrated.rs:199`）在 `:409` 返回最终 worker `PhasePacket` + ResultReview 判定 + retry/truncation/signature 状态；不 instrumented 时 v0 保持 `final_phase=null` + gap，禁止从 rollout 反推。`[FROZEN]`

5. **verification evidence 当前能拿多少？**
   root 阶段：直接读 rollout `event_msg / exec_command_begin|end`（DIRECT）。worker 阶段：默认拿不到；设 `CODEX_ROLLOUT_TRACE_ROOT` 后 trace bundle 全量包含（EVENT_CAPTURE）；无 trace 时只有失败 facts + packet 文本声明（OPEN）。

6. **task id 是否存在？**
   不存在。wire 的 `task_started` / `task_complete` 是 turn 事件别名（`protocol.rs:1322-1335`）；`source_task_id` v0 必须 null + gap，`thread_id` 是最近似但禁止冒充。`[FROZEN]`

7. **environment dependency 哪些能拿？**
   元数据（cwd、workspace_roots、network、permission profile、shell/model）DIRECT；实际使用的命令/cwd 可从 rollout（root）或 trace（worker）近似枚举；env var 依赖、secret 依赖、dependency manifest 均 OPEN。

8. **secrets scan 放在哪？**
   Bundle seal 前，Builder 侧扫描 inline 内容 + 外部 ref；v0 `not_scanned + gap`；仓库内无通用 scanner 可复用，扫描实现 OPEN。

9. **哪些仍然阻塞 P1？**
   final phase authority（必须 RUNTIME_CHANGE）、worker 阶段 verification evidence 默认持久化（需 RUNTIME_CHANGE 或强制 trace env）、secrets scanner（需 Builder 实现）、environment dependency manifest（需 runtime 记录）。

10. **哪些可以延后到 P2/P3？**
    `source_task_id`（等待 runtime task 概念）、replay config、dependency manifest 的完整语义、多环境 display roots 的持久化、in-memory tracker accessor（磁盘快照已覆盖 v0 需求）。
