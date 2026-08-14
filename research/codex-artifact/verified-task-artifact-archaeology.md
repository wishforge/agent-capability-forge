# Verified Task Artifact Archaeology

> 研究对象：OpenAI Codex issue #32100（yusing 提交的 Orchestrated multi-agent mode PoC）与 fork `yusing/codex` 的真实源码。
> 源码基线：`yusing/codex` HEAD `658630b2931ac841e2f1bc437daa1b931d173c0c`（2026-07-12 01:23:10 +0800），本地 clone 于 `<tmp>/yusing-codex`。
> 结论类型标记：`[SOURCE]` = 源码事实；`[ISSUE]` = issue #32100 文档；`[OPEN]` = 源码中找不到、明确标注为开放问题。

---

# 1. Executive Summary

当前代码（yusing/codex，即 issue #32100 描述的 PoC）中 **不存在** `WorkerResult`、`VerifiedTaskArtifact`、`Verification` 之类的结构化、可序列化类型。真实存在的机器可读材料是：

1. **Worker Result** = 私有结构 `PhasePacket { text: String, truncated: bool, execution_facts: OrchestratedExecutionFacts }`，其中 `text` 是自然语言 packet（以 `worker: complete` / `worker: incomplete` 开头），只存在于内存，不实现 serde。[SOURCE]
2. **Execution Facts** = `OrchestratedExecutionFacts`（`Vec<OrchestratedExecutionFact>`），仅记录 worker 阶段**失败类**命令（exit failure、可执行文件缺失、cwd 无效、路径缺失），有界、脱敏；不实现 serde，只渲染成 `<orchestrated_execution_facts>…</orchestrated_execution_facts>` 文本片段写入 history/rollout。[SOURCE]
3. **changed files / verification**：没有结构化字段。changed files 只有两个真实载体：worker packet 文本中的自然语言声明，以及 `TurnDiffTracker` 生成的 unified diff 字符串（经 `EventMsg::TurnDiff` 事件输出并持久化）。verification 没有任何运行时结构，只有 packet 文本声明 + `result-review: approved/revise` 状态解析。[SOURCE]
4. **持久化边界**：packet 文本与 facts 片段以 `RolloutItem::ResponseItem` 写入 `~/.codex/sessions/YYYY/MM/DD/rollout-{ts}-{thread_id}.jsonl`；role 阶段采样产生的工具/agent/TurnDiff 事件不持久化（`persist=false`），`OrchestratedRoleUpdated` 与 root 阶段的 `TurnDiff` 事件持久化；SQLite 只存线程元数据，不存这些结构。[SOURCE]

因此，**Capability Forge 的 Capabilityizer 当前没有现成的 "Verified Task Artifact Bundle" 可接收**。v0 必须由 Capabilityizer 自己从 rollout JSONL（或运行期捕获）组装；worker packet / result-review packet / execution facts / unified diff 是唯一可直接消费的持久化材料，stdout/stderr、成功命令的 exit code、最终文件全文、结构化 verification 结果均不在当前产物中。

---

# 2. Source Evidence

## 2.1 仓库与 issue 归属

- issue #32100 位于 **openai/codex** 仓库，标题 *"Orchestrated multi-agent mode PoC"*，作者 yusing，2026-07-10 创建，状态 open，标签 `enhancement` / `CLI` / `subagent`。[ISSUE]
  - https://github.com/openai/codex/issues/32100
- `yusing/codex` 仓库没有 #32100（GitHub API 返回 404）。[ISSUE]
- fork 源码 HEAD：`658630b`（2026-07-12），README 仍为 openai/codex 官方 README（“Codex CLI is a coding agent from OpenAI”），确认是 openai/codex 的 fork。[SOURCE]
- issue 正文引用的路径 `codex-rs/core/src/session/orchestrated/prompts.rs` 与当前 HEAD 不一致：当前 HEAD 的提示词在 `codex-rs/prompts/src/orchestrated.rs` + `codex-rs/prompts/templates/orchestrated/*.md`。以源码为准。[SOURCE]

## 2.2 核心证据文件

| 文件 | 作用 |
| --- | --- |
| `codex-rs/core/src/session/orchestrated.rs` | 编排状态机、PhasePacket、状态解析、phase 压缩 |
| `codex-rs/core/src/context/orchestrated_execution_facts.rs` | Execution Facts 结构、ledger、文本渲染 |
| `codex-rs/core/src/session/mod.rs` | history 替换、rollout 持久化、send_event 持久化策略 |
| `codex-rs/core/src/session/turn.rs` | run_turn 主循环、root synthesis 触发、TurnDiff 事件 |
| `codex-rs/core/src/turn_diff_tracker.rs` | changed files 的真实跟踪器（unified diff） |
| `codex-rs/protocol/src/protocol.rs` | RolloutItem / EventMsg / TurnDiffEvent / OrchestratedRoleUpdatedEvent 的 serde |
| `codex-rs/protocol/src/models.rs` | ResponseItem / ContentItem 的 serde |
| `codex-rs/rollout/src/recorder.rs` | rollout JSONL 文件路径 |
| `codex-rs/thread-store/src/local/live_writer.rs`、`read_thread.rs` | JSONL 与 SQLite 元数据的边界 |
| `codex-rs/prompts/templates/orchestrated/*.md` | worker / result-review / orchestrator 的 packet 协议契约 |
| `codex-rs/core/tests/suite/multi_agent_mode.rs` | 端到端测试：持久化 history 只含 compact packet、facts 片段 |

---

# 3. Worker Result Data Model

## 3.1 真实类型：PhasePacket（不是 WorkerResult）

`codex-rs/core/src/session/orchestrated.rs:48-76`：

```rust
#[derive(Clone, Copy, Eq, PartialEq)]
enum Phase {
    TaskContract,
    Explorer,
    WorkerPlan,
    PlanReview,
    PlanEvidence,
    WorkerExec,
    ResultReview,
}

pub(super) enum Outcome {
    Skipped,
    Completed,
    Stopped,
}

struct PhasePacket {
    text: String,
    truncated: bool,
    execution_facts: OrchestratedExecutionFacts,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum WorkerStatus {
    Complete,
    Incomplete,
    Invalid,
}
```

要点：

- 全仓库没有名为 `WorkerResult` 的类型。`rg "WorkerResult"` 零命中。[SOURCE]
- `PhasePacket` 是 `session` 模块私有结构，**不派生 Serialize/Deserialize**，只在 `run_phases` / `run_phase` / `compact_phase_history` 之间传递。[SOURCE]
- "Worker Result" 事实上的含义 = `PhasePacket`（当 `phase == Phase::WorkerExec`）：`text` 是模型输出的 worker packet 文本，`execution_facts` 是该时刻 ledger 的快照。[SOURCE]

## 3.2 Packet 文本协议（机器可解析的部分）

worker packet 的状态前缀解析（`orchestrated.rs:457-483`）：

```rust
fn worker_status(packet: &str) -> WorkerStatus {
    let packet = packet.strip_prefix("orc:").map(str::trim_start).unwrap_or(packet);
    if packet_has_status(packet, WORKER_ROLE_NAME, "complete") { WorkerStatus::Complete }
    else if packet_has_status(packet, WORKER_ROLE_NAME, "incomplete") { WorkerStatus::Incomplete }
    else { WorkerStatus::Invalid }
}

fn packet_has_status(packet: &str, role: &str, status: &str) -> bool {
    // 要求以 "{role}:" 开头，随后紧跟 status，且下一个字符是空白 / ';' / ':' 或结尾
}
```

role 常量（`codex-rs/core/src/agent/role.rs:30-36`）：

```rust
pub(crate) const WORKER_ROLE_NAME: &str = "worker";
pub(crate) const EXPLORER_ROLE_NAME: &str = "explorer";
pub(crate) const TASK_CONTRACT_ROLE_NAME: &str = "task-contract";
pub(crate) const WORKER_PLAN_ROLE_NAME: &str = "worker-plan";
pub(crate) const PLAN_REVIEW_ROLE_NAME: &str = "plan-review";
pub(crate) const PLAN_EVIDENCE_ROLE_NAME: &str = "plan-evidence";
pub(crate) const RESULT_REVIEW_ROLE_NAME: &str = "result-review";
```

因此机器可确认的只有：`worker: complete` / `worker: incomplete` / 其它（Invalid）。`worker` 之后的正文（summary、changed files、verification、risks）**没有任何解析代码**。[SOURCE]

## 3.3 Packet 的提取与截断

- `phase_packet`（`orchestrated.rs:657-673`）：从 phase 期间新增的 history 中，从后向前找第一条以 `"{role}:"` 开头的 assistant 文本；没有则以最后一条 assistant 文本兜底；没有则生成 `"{role}: no final packet produced"`。[SOURCE]
- `truncate_packet`（`orchestrated.rs:694-718`）：普通 phase 上限 8192 字节（`MAX_PACKET_BYTES`，第 42 行），PlanEvidence 单独 1000 token 上限；截断时在文本末尾追加 `[packet truncated: …]` 后缀，`truncated=true`。[SOURCE]
- `truncated` 布尔值只在内存；持久化后只能通过文本中的截断后缀反推。[SOURCE]

---

# 4. Execution Facts Data Model

## 4.1 真实类型

`codex-rs/core/src/context/orchestrated_execution_facts.rs:8-47`：

```rust
/// Bounded, redacted execution evidence retained after orchestrated phase compaction.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct OrchestratedExecutionFacts {
    facts: Vec<OrchestratedExecutionFact>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct OrchestratedExecutionFact {
    generation: u64,
    fingerprint: String,       // Sha1(command + "\0" + cwd) 前 16 hex，见 :49-60
    cwd: String,               // safe_path 处理
    outcome: OrchestratedExecutionOutcome,
    executions: u8,
    suppressed_retries: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum OrchestratedExecutionOutcome {
    ExecutableUnavailable { executable: String },
    InvalidWorkingDirectory { path: String },
    MissingPath { path: String },
    ExitFailure { code: i32 },
}
```

没有 `#[derive(Serialize, Deserialize)]`；这些类型是 `pub(crate)`，只存在于进程内存。[SOURCE]

## 4.2 Ledger 语义（失败专用）

- `OrchestratedExecutionLedger`（`:42-47`）是 per-turn 的 `Arc<Mutex<…>>`，挂在 `TurnContext` 上（`codex-rs/core/src/session/turn_context.rs:132`、`580`）。[SOURCE]
- 只在 **worker 阶段** 生效：`exec_command.rs:197` `(turn.orchestrated_role == Some(WORKER_ROLE_NAME)).then(|| …)`。[SOURCE]
- `record_exit` 只在 `exit_code != 0` 时调用（`exec_command.rs:432-441`）；exit 0 的成功命令**不产生 fact**。[SOURCE]
- 相同 fingerprint + outcome 的重复失败会 `executions += 1`，并被 `begin_command` 抑制（返回 `Suppress`，工具输出改为 `suppressed unchanged deterministic failure: …`，`exec_command.rs:215-227`）；非 ExitFailure 的确定性失败会累加 `suppressed_retries`。[SOURCE]
- `invalidate()`（`router.rs:231`）在非 exec 事件改变状态时清空事实并推进 generation。[SOURCE]

## 4.3 文本渲染（唯一序列化形式）

实现 `ContextualUserFragment`（`orchestrated_execution_facts.rs:216-266`），`role="user"`，标记：

```text
<orchestrated_execution_facts> … </orchestrated_execution_facts>
```

每行格式（`:240-261`）：

```text
- phase=worker tool=exec_command commandFingerprint={16hex} effectiveCwd="{quoted}" outcome={label}[ executable="{name}" | path="{path}" | code={code}] executions={n} suppressedRetries={n}
```

`outcome` label（`:121-130`）：`executableUnavailable` / `invalidWorkingDirectory` / `missingPath` / `exitFailure`。

脱敏：`safe_path`（`:297-316`）对含 `://`、`@`、`?`、`#`、`=` 的路径替换为 `<redacted>`，控制字符替换为空格，并截断到 120 字节。测试 `orchestrated_execution_facts_tests.rs:19-48` 证明 URL 与 `secret` 不会出现在渲染结果中；`multi_agent_mode.rs:598-601` 证明 `--password super-secret-value` 不进入 review 输入。[SOURCE]

注意：facts 片段只在 `take_update()` 有更新时写入 history（`orchestrated.rs:636-648`）；如果 worker 阶段没有任何失败命令，phase 压缩后**不会**出现 facts 片段。[SOURCE]

---

# 5. Verification Data Model

## 5.1 结论：没有 Verification 结构

全仓库（core/context/session/prompts）不存在 `Verification`、`verification_result`、`Verified*` 类型或 serde 字段。[SOURCE]

唯一的 "verification" 相关类型是协议里的 `ModelVerification` / `ModelVerificationEvent`（`codex-rs/protocol/src/protocol.rs:1305-1306`），那是 **Responses API 的账号级模型验证事件**，与任务验证无关。[SOURCE]

## 5.2 实际存在的验证机制 = 文本协议 + 模型判断

1. worker prompt 要求：*"run required verification … Final packet begins exactly `worker: complete` when every completion criterion and check passes"*，并 *"Include summary, changed files, verification commands and results, failures, unresolved risks"*（`prompts/templates/orchestrated/worker.md:1,7`）。[SOURCE]
2. result-review prompt 要求：*"Treat concrete changed-file, command, and result statements in the worker packet as execution evidence"*，并 *"Reject a truncated packet, missing required tests, reported failed checks, unresolved correctness gaps, scope drift, or an incomplete worker status"*（`prompts/templates/orchestrated/result_review.md:1`）。[SOURCE]
3. 运行时只解析两个状态位（`orchestrated.rs:449-455`）：
   - `result-review: approved` → `review_approved`
   - `result-review: revise` + 下一行 `owner: worker|explorer|root|user` → `correction_owner`（`:435-447`）
4. 没有任何代码解析/校验 "verification commands and results" 的内容；验证是否通过完全由 Result Review 模型的文本判断决定。[SOURCE]
5. issue #32100 也明确把 Result Review 描述为模型审查而非 verifier：[ISSUE] *"Result Review checks a valid Worker packet against the contract and approved plan … concrete command and result statements in the Worker packet are the review evidence."*

## 5.3 A–E 概念区分（基于源码）

| 概念 | 真实对应 | 形态 |
| --- | --- | --- |
| A. Task Verification 的输入 | worker packet 文本 + `OrchestratedExecutionFacts` 片段 + task-contract/plan/explorer 等 compact packet | history 中的文本消息 |
| B. Worker Result | `PhasePacket{ text=worker packet, truncated, execution_facts }` | 内存结构；text 落 history/rollout |
| C. Execution Facts | `OrchestratedExecutionFacts`（失败类、有界、脱敏） | 内存 + 文本片段 |
| D. Result Review | `PhasePacket{ text=result-review packet }` + 运行时解析出的 approved/revise+owner | 内存 + 文本落 history/rollout |
| E. Capability Forge 需要的 Artifact | **不存在**；需要 Capabilityizer 从 rollout + runtime 组装 | 见 §10 |

---

# 6. Worker -> Review -> Synthesis Call Chain

## 6.1 入口

`turn.rs:208-227`：`run_turn` 创建 `TurnDiffTracker`（:210-212）后调用 `orchestrated::run_for_input`；`Outcome::Completed` 则 `orchestrated_phases_ran = true`，随后**继续进入正常采样循环**（:239-267），即 root synthesis 不是 `run_phases` 内的一个 Phase。[SOURCE]

## 6.2 Reviewed 路径（orchestrated.rs:199-410）

```text
run_phases
  → Phase::TaskContract        (:207-216)  run_phase + packet
  → Phase::Explorer            (:276-285)
  → Phase::WorkerPlan          (:293-302)
  → Phase::PlanReview          (:306-337)  approved? / evidence-needed? / revise
  → Phase::PlanEvidence        (:323-332)
  → loop (MAX_WORK_REVISIONS=2):
      → Phase::WorkerExec      (:347-356)  run_phase → worker PhasePacket
      → worker_status(text)    (:357)
      → Phase::ResultReview    (:361-370)  run_phase → review PhasePacket
      → review_approved?       (:371-376)
      → correction_owner?      (:377-401)
          owner: worker → 重试 worker
          owner: explorer → Phase::Explorer，清空 retry signature
          owner: root/user/None → break
  → emit_role_update(None)     (:407)
```

每个 `run_phase`（:512-604）：

```text
记录 history_baseline → emit_role_update(role) → 构造 role TurnContext
（Explorer/Worker 强制 approval_policy=OnRequest，Explorer/PlanEvidence 强制 read-only，:534-549）
→ run_sampling_request（最多 MAX_PHASE_STEPS=32 次采样，:560-593）
→ compact_phase_history（:595-601）
```

## 6.3 Phase 压缩与 packet 落 history（orchestrated.rs:617-655）

`compact_phase_history`：

1. 取 `after_items[baseline.len()..]` 作为 phase 原始 items；
2. `phase_packet` 提取 packet 文本 → `truncate_packet`；
3. 构造 `ResponseItem::Message{ role:"assistant", content:[OutputText{ packet.text }] }`；
4. worker 阶段从 ledger 取 `facts()` 和 `take_update()`；有更新时追加 `ContextualUserFragment::into(facts_update)`（即 `role:"user"` + `<orchestrated_execution_facts>` 文本）；
5. `replace_orchestrated_phase_history(turn_context, baseline, retained_items)`（:649）；
6. 返回 `PhasePacket { execution_facts, ..packet }`。

因此 **Result Review 的输入不是原始工具调用，而是压缩后的 packet 文本 + facts 片段**；测试 `multi_agent_mode.rs:1680-1733` 验证 orchestrator 输入只包含 compact packets 而不含 worker 工具输出。[SOURCE]

## 6.4 重试签名（防死循环）

- `worker_retry_signature`（:417-425）= `worker_status + packet.text + execution_facts.progress_signature()`；
- `retry_signature`（:412-415）= worker signature + review packet text；
- 相同签名重复则 break（:263-265、:379-383）。[SOURCE]

## 6.5 Root Synthesis（真实机制）

`run_phases` 返回后，`run_turn` 的主循环继续以 root turn context 采样（`turn.rs:239-267`），每次采样前 `add_sampling_instruction`（`turn.rs:1181`）在无 `orchestrated_role` 时注入 `ORCHESTRATED_ORCHESTRATOR` 提示词（`orchestrated.rs:485-495`）。orchestrator 提示词要求：*"Internal phase packets are not client-visible; your response is the only user-visible assistant result"*，成功时短合成（`orc:` 前缀），失败/耗尽时只报剩余修正（`prompts/templates/orchestrated/orchestrator.md:1`）。[SOURCE]

所以 "Root Synthesis" 不是新 Phase，而是 phase 压缩后、root 模型对保留 packet 的一次常规采样。[SOURCE]

## 6.6 TurnDiff 事件

每次采样请求完成时 `should_emit_turn_diff = true`（`turn.rs:2327`）；`run_sampling_request` 结束时从 `TurnDiffTracker` 取 unified diff 并 `send_event(EventMsg::TurnDiff(TurnDiffEvent{ unified_diff }))`（`turn.rs:2518-2526`）。worker/root 期间所有 apply_patch 变更都会累积在同一个 tracker 里，因此最终事件包含整个用户 turn 的 net diff。[SOURCE]

---

# 7. Serialization / Persistence Boundary

## 7.1 逐项结论

| 载体 | 是否包含 worker/result-review packet / facts | 证据 |
| --- | --- | --- |
| 内存 | 是：`PhasePacket`、`OrchestratedExecutionLedger`、`TurnDiffTracker` 全文内容 | orchestrated.rs:65-69, 638; turn.rs:210 |
| session history（模型可见） | 是：packet 消息 + facts 片段（phase 压缩后） | session/mod.rs:2892-2907; orchestrated.rs:617-655 |
| JSON 序列化（作为结构体） | 否：PhasePacket / Facts / Ledger 均无 serde | orchestrated.rs:65; orchestrated_execution_facts.rs:8-22 |
| JSONL rollout 文件 | 是：packet/facts 以 `RolloutItem::ResponseItem` 持久化 | session/mod.rs:2905, 3137-3144; protocol.rs:3171-3186 |
| event（客户端 API 流） | 部分：role 阶段采样事件不持久化；`OrchestratedRoleUpdated` 与 root 阶段 TurnDiff 持久化 | session/mod.rs:1778-1832, 2006-2016 |
| 文件（rollout） | 是：`~/.codex/sessions/YYYY/MM/DD/rollout-{ts}-{thread_id}.jsonl` | recorder.rs:1500-1527 |
| 数据库 | 否：SQLite 只存线程元数据，history 始终从 JSONL 读取 | thread-store live_writer.rs:115-133; read_thread.rs:30-70 |
| API 返回 | 是（间接）：thread read 从 RolloutItem 构建 turns；事件经 EventMsg 流式返回 | app-server thread_lifecycle.rs:736-746; session/mod.rs:2018-2025 |

## 7.2 关键代码

`session/mod.rs:2871-2890`（普通记录）：`orchestrated_role.is_some()` 时跳过 rollout 持久化，只进内存 history + 客户端。

`session/mod.rs:2892-2907`（phase 压缩持久化）：

```rust
pub(crate) async fn replace_orchestrated_phase_history(&self, turn_context: &TurnContext,
    mut baseline: Vec<ResponseItem>, packets: Vec<ResponseItem>) {
    let prepared_packet = self.prepare_conversation_items_for_history(turn_context, &packets);
    baseline.extend_from_slice(prepared_packet.as_ref());
    { /* state.replace_history(baseline, reference_context_item) */ }
    self.persist_rollout_response_items(prepared_packet.as_ref()).await;
}
```

`session/mod.rs:1778-1832`（send_event）：role phase 的 agent 消息被抑制不下发客户端；`let persist = turn_context.orchestrated_role.is_none();`。role 阶段采样期间的事件用 `role_turn_context`（orchestrated_role=Some）发送，因此不写 rollout；`emit_role_update` 用 `root_turn_context` 发送（orchestrated.rs:522, 606-615），所以每次 `OrchestratedRoleUpdated`（含中间 role 与最终 None）都会持久化。[SOURCE]

## 7.3 Rollout JSONL 的真实 serde 形状

`protocol.rs:3171-3186`：

```rust
#[derive(Serialize, Deserialize, Debug, Clone, JsonSchema, TS)]
#[serde(tag = "type", content = "payload", rename_all = "snake_case")]
pub enum RolloutItem {
    SessionMeta(SessionMetaLine),
    ResponseItem(ResponseItem),
    InterAgentCommunication(InterAgentCommunication),
    InterAgentCommunicationMetadata { trigger_turn: bool },
    Compacted(CompactedItem),
    TurnContext(TurnContextItem),
    WorldState(WorldStateItem),
    EventMsg(EventMsg),
}
```

因此持久化后每行 JSON 形如：

```json
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"worker: complete\n..."}]}}
{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"<orchestrated_execution_facts>\n..."}]}}
{"type":"event_msg","payload":{"type":"turn_diff","unified_diff":"diff --git ..."}}
{"type":"event_msg","payload":{"type":"orchestrated_role_updated","turn_id":"...","role":"worker"}}
```

`ResponseItem`（`models.rs:932-958`）与 `ContentItem`（`models.rs:842-857`）均为 `#[serde(tag="type", rename_all="snake_case")]`；Message 的 `id`/`phase`/`internal_chat_message_metadata_passthrough` 为 `Option` 且 `skip_serializing_if=Option::is_none`。packet 压缩时构造的 id 为 `None`（`orchestrated.rs:627-635`），但 `prepare_conversation_items_for_history`（session/mod.rs:2810-2826）会在持久化边界补 `internal_chat_message_metadata_passthrough.turn_id`，并在 `item_ids_enabled()` 时补 `id`（`msg_{uuid7}`，:2839-2861）；因此持久化 JSON 通常含 `id` + `turn_id`（取决于配置）。[SOURCE]

`EventMsg`（`protocol.rs:1275-1279`）：`#[serde(tag="type", rename_all="snake_case")]`。

`TurnDiffEvent`（`protocol.rs:3688-3691`）：`pub struct TurnDiffEvent { pub unified_diff: String }`。

`OrchestratedRoleUpdatedEvent`（`protocol.rs:1992-1998`）：`turn_id: String` + `role: Option<String>`，`EventMsg::OrchestratedRoleUpdated`（`protocol.rs:1326`）。[SOURCE]

## 7.4 身份与 workspace 元数据（独立于 packet）

- `TurnContextItem`（`protocol.rs:3249-3293`）：`turn_id?`、`cwd: AbsolutePathBuf`、`workspace_roots?`、`current_date?`、`timezone?`、`permission_profile?`、`network?`、`model` 等，按真实用户 turn 持久化（`session/mod.rs:3128`）。[SOURCE]
- `SessionMetaLine`（`protocol.rs:3134-3168`）：flatten `SessionMeta` + `git`；`session_id` 缺失时从 `id` 回填。rollout 文件名含 `conversation_id`（recorder.rs:1519）。[SOURCE]
- facts 中的 `effectiveCwd` 是脱敏 cwd；`TurnDiffTracker.display_path` 在多个 environment 时给 diff 路径加 `{environment_id}/` 前缀（turn_diff_tracker.rs:373-385）。[SOURCE]

---

# 8. Actual Machine-Readable Fields

## 8.1 Packet 文本（role: status 前缀）

运行时实际解析的字段（`orchestrated.rs:435-483`）：

| 语法 | 值 | 来源 |
| --- | --- | --- |
| `worker: complete` | WorkerStatus::Complete | orchestrated.rs:462 |
| `worker: incomplete` | WorkerStatus::Incomplete | orchestrated.rs:464 |
| 其它 `worker: …` | WorkerStatus::Invalid | orchestrated.rs:467 |
| `result-review: approved` | review 通过 | orchestrated.rs:449-451 |
| `result-review: revise` | review 不通过 | orchestrated.rs:435-439 |
| 下一行 `owner: worker|explorer|root|user` | CorrectionOwner | orchestrated.rs:440-445 |
| `evidence-needed:`（worker/plan-review 包内） | 请求证据 | orchestrated.rs:244, 454 |
| `task-contract: direct` | 直接执行路径 | orchestrated.rs:218 |
| 文本末尾 `[packet truncated: …]` | 截断标记（持久化侧反推） | orchestrated.rs:43-46, 694-718 |

## 8.2 Execution Facts 文本字段

`<orchestrated_execution_facts>` 片段内（orchestrated_execution_facts.rs:240-261）：

`phase`（固定 `worker`）、`tool`（固定 `exec_command`）、`commandFingerprint`、`effectiveCwd`、`outcome`、`executable`（仅 ExecutableUnavailable）、`path`（仅 InvalidWorkingDirectory/MissingPath）、`code`（仅 ExitFailure）、`executions`、`suppressedRetries`。

没有 stdout/stderr、没有成功命令、没有命令原文。[SOURCE]

## 8.3 结构化 JSON 字段（serde 名）

| 类型 | serde 字段（实际 JSON key） | 来源 |
| --- | --- | --- |
| `RolloutItem` | `type` / `payload`，变体名 snake_case（`response_item`、`event_msg`、`session_meta`、`turn_context`、`world_state`、`compacted`、`inter_agent_communication`、`inter_agent_communication_metadata`） | protocol.rs:3171-3186 |
| `ResponseItem::Message` | `type="message"`、`id?`、`role`、`content`、`phase?`、`internal_chat_message_metadata_passthrough?` | models.rs:932-958 |
| `ContentItem::InputText/OutputText` | `type="input_text"|"output_text"`、`text` | models.rs:842-857 |
| `EventMsg::TurnDiff` | `type="turn_diff"`、`unified_diff` | protocol.rs:1429, 3688-3691 |
| `EventMsg::OrchestratedRoleUpdated` | `type="orchestrated_role_updated"`、`turn_id`、`role?` | protocol.rs:1326, 1992-1998 |
| `TurnContextItem` | `turn_id?`、`cwd`、`workspace_roots?`、`current_date?`、`timezone?`、`approval_policy`、`sandbox_policy`、`permission_profile?`、`network?`、`model`、`comp_hash?`、`personality?`、`collaboration_mode?`、`multi_agent_version?`、`multi_agent_mode?`、`realtime_active?`、`effort?`、`summary` | protocol.rs:3249-3293 |
| `TurnDiffEvent` | `unified_diff` | protocol.rs:3688-3691 |

---

# 9. What Capability Forge Can Reliably Consume

## 9.1 九个判断题（按用户清单）

| # | 问题 | 结论 | 真实载体与证据 |
| --- | --- | --- | --- |
| 1 | 是否已包含 changed files | **部分（非结构化）**：没有 changed files 字段/列表；只有 packet 文本声明 + unified diff 字符串 | worker.md:7; turn_diff_tracker.rs:115-121; turn.rs:2518-2526 |
| 2 | 是否包含最终文件内容 | **否**：`TurnDiffTracker` 在内存中持有 baseline/current 全文（turn_diff_tracker.rs:20-23, 50-61），但从不序列化全文；持久化只有 diff 文本；world state 也不含文件全文（只渲染 workspace roots + permission profile） | turn_diff_tracker.rs:309-366; environment_context.rs:11-72 |
| 3 | 是否只有 diff / metadata | 是：最终机器可读变更材料 = `unified_diff: String`（路径 + hunks + blob oid），无结构化 file list/metadata | protocol.rs:3688-3691 |
| 4 | 是否包含 verification command/result | **否（仅文本声明）**：worker packet 文本包含 "verification commands and results" 的自然语言声明，无任何解析/校验 | worker.md:7; result_review.md:1; orchestrated.rs 无 verification 解析 |
| 5 | 是否包含 exit code | **部分**：失败命令的 exit code 在 facts（`ExitFailure{code}`、不可执行→127、路径类→1，orchestrated_execution_facts.rs:106-113）；成功命令的 exit code 只存在于瞬时 exec 工具输出/事件，role 阶段不持久化 | exec_command.rs:432-441; session/mod.rs:1831 |
| 6 | 是否包含 stdout/stderr | **否（故意丢弃）**：facts 片段明确写 "Raw commands and tool output were discarded"；facts 只保留 fingerprint/cwd/outcome/executions/suppressedRetries | orchestrated_execution_facts.rs:233-235 |
| 7 | 是否包含 workspace 路径 | **部分**：facts 有 `effectiveCwd`（脱敏）；`TurnContextItem.cwd` / `workspace_roots` 持久化；diff 路径相对 display roots | orchestrated_execution_facts.rs:241; protocol.rs:3250-3257; turn_diff_tracker.rs:373-385 |
| 8 | 是否包含 session / task identity | **部分（旁路元数据 + 消息元数据，不在 packet 文本内）**：rollout 文件名含 thread/conversation id；`SessionMetaLine.session_id`；`TurnContextItem.turn_id`；event `id = sub_id`；持久化 packet 消息带 `id` + passthrough `turn_id` | recorder.rs:1519; protocol.rs:3134-3168, 3249-3253; session/mod.rs:1827-1830, 2810-2826 |
| 9 | 是否包含 environment dependency | **否**：没有依赖清单；仅有 `TurnContextNetworkItem{allowed_domains, denied_domains}`（protocol.rs:3239-3243）、world-state 环境上下文（cwd/shell/workspace_roots）、多环境 diff 路径前缀 | protocol.rs:3239-3243; environment_context.rs:11-72; world_state/environment.rs:246-281 |
| 10 | 是否包含 secrets 引用 | **否**：facts 对 URL/@/?#=/控制字符脱敏，测试证明 secret 不出现；但 worker packet 是自由文本，运行时无 secrets 过滤 | orchestrated_execution_facts.rs:297-316; orchestrated_execution_facts_tests.rs:19-48 |

## 9.2 Capabilityizer 可直接消费的持久化材料

1. **phase packets**：从 rollout `RolloutItem::ResponseItem` 中按文本前缀提取 `task-contract:` / `explorer:` / `worker-plan:` / `plan-review:` / `plan-evidence:` / `worker:` / `result-review:` 消息。[SOURCE]
2. **packet 状态**：`worker: complete|incomplete`、`result-review: approved|revise`、`owner:`、截断后缀 —— 与运行时解析器使用同一语法（orchestrated.rs:435-483）。[SOURCE]
3. **execution facts**：解析 `<orchestrated_execution_facts>` 片段（仅失败类、有界、脱敏）。[SOURCE]
4. **unified diff**：从 `event_msg / turn_diff` 读取（root 阶段持久化的最终 net diff）。[SOURCE]
5. **身份与 cwd**：`session_meta`、`turn_context`、rollout 文件名。[SOURCE]
6. **root synthesis 文本**：phase 之后、`orc:` 前缀的最终 assistant 消息（普通 turn 流程持久化，session/mod.rs:2886-2888）。[SOURCE]

---

# 10. VerifiedTaskArtifactBundle v0

> 原则：只装当前源码**已持久化或可从持久化材料确定性推导**的字段；其余标 `OPEN`，并注明必须从 runtime 再取。

## 10.1 JSON Schema 草案

```json
{
  "schema_version": "verified-task-artifact-bundle-v0",
  "bundle_id": "uuid-v7",
  "producer": {
    "runtime": "codex-cli-fork",
    "repo": "yusing/codex",
    "commit": "658630b2931ac841e2f1bc437daa1b931d173c0c",
    "mode": "orchestrated",
    "generated_at": "ISO8601"
  },
  "task_identity": {
    "session_id": "string",
    "thread_id": "string",
    "turn_id": "string",
    "rollout_path": "string",
    "user_prompt": "string"
  },
  "workspace": {
    "cwd": "string",
    "workspace_roots": ["string"]
  },
  "phases": [
    {
      "phase": "task-contract | explorer | worker-plan | plan-review | plan-evidence | worker | result-review",
      "packet": "string",
      "truncated": "boolean",
      "status": "complete | incomplete | invalid | approved | revise | unknown",
      "owner": "worker | explorer | root | user | null"
    }
  ],
  "execution_facts": [
    {
      "generation": 0,
      "command_fingerprint": "string",
      "effective_cwd": "string",
      "outcome": "exitFailure | executableUnavailable | invalidWorkingDirectory | missingPath",
      "exit_code": 1,
      "executable": "string | null",
      "path": "string | null",
      "executions": 1,
      "suppressed_retries": 0
    }
  ],
  "verification": {
    "worker_status": "complete | incomplete | invalid",
    "review_status": "approved | revise | none",
    "final_review_owner": "worker | explorer | root | user | null",
    "verification_claims": [],  "verification_commands_and_results_from_packet": "OPEN",
    "exit_codes_success": "OPEN",
    "stdout_stderr": "OPEN"
  },
  "changes": {
    "unified_diff": "string",
    "changed_files_structured": "OPEN"
  },
  "root_synthesis": {
    "text": "string",
    "status": "completed | stopped | error"
  },
  "gaps": ["string"]
}
```

## 10.2 字段来源

| 字段 | 来源（真实文件 + 行号） | 支持度 |
| --- | --- | --- |
| `phases[].packet` | rollout `response_item`（assistant, `output_text`），构造于 orchestrated.rs:627-635 | **DIRECT** |
| `phases[].status` / `owner` | packet 文本用运行时同一语法解析（orchestrated.rs:435-483） | **DIRECT（文本可推导）** |
| `phases[].truncated` | 文本末尾截断后缀反推；bool 本身不持久化（orchestrated.rs:43-46, 694-718） | **DIRECT（可推导）** |
| `execution_facts` | `<orchestrated_execution_facts>` 片段（orchestrated_execution_facts.rs:240-261） | **DIRECT（文本可推导）** |
| `changes.unified_diff` | `event_msg / turn_diff`（protocol.rs:3688-3691; turn.rs:2518-2526） | **DIRECT** |
| `workspace.cwd/workspace_roots` | `turn_context`（protocol.rs:3249-3257; session/mod.rs:3128） | **DIRECT** |
| `task_identity` | `session_meta` + rollout 文件名 + `turn_context.turn_id` + event id（recorder.rs:1519; protocol.rs:3134-3168; session/mod.rs:1827-1830） | **DIRECT** |
| `root_synthesis.text` | phase 后首条 `orc:` assistant 消息（orchestrator.md:1; turn.rs:239-267） | **DIRECT（文本可推导）** |
| `verification.verification_claims` | worker packet 自由文本，无 schema | **OPEN** |
| `verification` 结构化验证结果 | 不存在（§5） | **OPEN** |
| `changes.changed_files_structured` | 不存在 | **OPEN** |
| 最终文件全文 | 不持久化（§9.1-2） | **OPEN** |
| 成功命令 exit code / stdout/stderr | role 阶段事件不持久化（session/mod.rs:1831） | **OPEN** |
| environment dependency manifest | 不存在 | **OPEN** |
| secrets 引用 | facts 脱敏；packet 未脱敏 | **OPEN（需要运行期策略）** |

## 10.3 Capabilityizer 必须从原 Codex runtime 再取的数据

1. **rollout JSONL 路径 / thread 读取**：bundle 不携带历史；需要 thread store 或 `~/.codex/sessions/…` 定位（thread-store read_thread.rs:30-70; recorder.rs:1500-1527）。
2. **最终 phase 状态的权威判定**：runtime 的 `run_phases` 是唯一权威状态机（重试签名、截断、supersede 语义）；消费者需要重放 packet 序列或从 runtime 捕获，才能回答"哪个 worker packet 是最终有效 packet"（orchestrated.rs:224-267, 346-403）。
3. **stdout/stderr 与成功命令 exit code**：只在瞬时 exec 事件里存在；如需，必须在运行期订阅事件或改造 runtime 持久化（exec_command.rs:432-441; session/mod.rs:1831）。
4. **最终文件全文**：rollout 只有 diff；需在任务结束时读取 workspace（或运行期捕获 TurnDiffTracker 内存全文，turn_diff_tracker.rs:50-61）。
5. **verification 的"真实证据"**：当前只有模型文本判断；如 Capabilityizer 需要命令级验证证据，需在 runtime 记录 verification 命令输出或重跑验证。

---

# 11. Gaps / Open Questions

1. **没有 WorkerResult / Artifact 类型**：PoC 没有定义任何可序列化的任务产物类型（§3.1）。
2. **没有结构化 changed files**：unified diff 可解析出路径，但 add/update/delete/rename 语义与 per-file 元数据必须自己从 diff 解析（turn_diff_tracker.rs:309-366）。
3. **没有结构化 verification**：verification 命令、结果、通过标准全部在自然语言 packet 中；runtime 不校验（§5）。
4. **成功命令不可追溯**：facts 只记录失败；成功命令的 exit code 0 / stdout / stderr 均无持久化（§4.2, §9.1-5/6）。
5. **truncated 布尔不持久化**：只能靠文本后缀反推；如果模型在截断边界恰好包含该字符串会产生歧义（低风险，未处理）（§3.3）。
6. **facts 片段不是 JSON**：机器读取需要文本解析；marker 文本可能被模型回写混淆（context-fragments 只做文本匹配，fragment.rs:57-63）。
7. **身份字段不在 packet 内**：session/turn 身份需要旁路元数据关联（§9.1-8）。
8. **secrets 边界不一致**：facts 脱敏，但 packet 与 diff 是自由文本/原始 diff，可能包含 secret；Capabilityizer 需要自己的脱敏策略（§9.1-10）。
9. **fork 是 PoC**：issue 明确 "not a claim of production readiness"；提交基线 2026-07-12，上游 openai/codex main 可能与 fork 分歧。[ISSUE]
10. **`result-review: approved` 不等于"验证通过"**：它是模型对 packet 文本的审查判断，不是 verifier 执行结果（§5.2）。

---

# 12. Evidence Index

## 源码（yusing/codex @ 658630b）

| 文件 | 行 | 内容 |
| --- | --- | --- |
| `codex-rs/core/src/session/orchestrated.rs` | 36-76 | 常量、Phase、PhasePacket、WorkerStatus |
| 同文件 | 149-197 | run_for_input 入口、Outcome |
| 同文件 | 199-410 | run_phases 状态机（direct/reviewed、重试、ResultReview） |
| 同文件 | 412-425 | retry_signature / worker_retry_signature（facts.progress_signature） |
| 同文件 | 427-483 | CorrectionOwner、review_approved、worker_status、packet_has_status |
| 同文件 | 485-510 | add_sampling_instruction（orchestrator prompt 注入） |
| 同文件 | 512-604 | run_phase（history baseline、role context、采样循环） |
| 同文件 | 606-615 | emit_role_update（OrchestratedRoleUpdated 事件） |
| 同文件 | 617-655 | compact_phase_history（packet 构造 + facts 片段 + replace/persist） |
| 同文件 | 657-718 | phase_packet 提取、assistant_message_text、truncate_packet |
| `codex-rs/core/src/context/orchestrated_execution_facts.rs` | 8-47 | OrchestratedExecutionFacts/Fact/Outcome/Key/Start/Ledger 定义 |
| 同文件 | 49-60 | command fingerprint（Sha1）与命令元数据 |
| 同文件 | 62-119 | from_exit、exit_code、suppression_diagnostic |
| 同文件 | 121-130 | outcome label |
| 同文件 | 131-205 | ledger begin/record/invalidate/facts/take_update |
| 同文件 | 207-266 | progress_signature、ContextualUserFragment 渲染（marker + 行格式） |
| 同文件 | 268-320 | command_metadata、safe_path、quoted（脱敏） |
| `codex-rs/core/src/session/mod.rs` | 1778-1832 | send_event：role 抑制 + `persist = orchestrated_role.is_none()` |
| 同文件 | 2006-2016 | send_event_raw_with_persistence → RolloutItem::EventMsg |
| 同文件 | 2810-2826, 2839-2861 | prepare_conversation_items_for_history：补 turn_id / item id（`msg_{uuid7}`） |
| 同文件 | 2871-2907 | record_conversation_items / replace_orchestrated_phase_history |
| 同文件 | 3137-3144 | persist_rollout_response_items |
| 同文件 | 3564-3570 | persist_rollout_items → live_thread.append_items |
| `codex-rs/core/src/session/turn.rs` | 208-227 | run_turn 入口调用 run_for_input |
| 同文件 | 239-267 | phase 后继续 root 采样循环 |
| 同文件 | 1181 | add_sampling_instruction 注入点 |
| 同文件 | 2026-2027, 2311-2327 | should_emit_turn_diff 置位（采样完成） |
| 同文件 | 2518-2526 | TurnDiffEvent 发送 |
| `codex-rs/core/src/session/turn_context.rs` | 132, 580 | orchestrated_execution_ledger 字段与初始化 |
| `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs` | 197-229 | worker 阶段 ledger begin/suppress |
| 同文件 | 432-441 | exit_code != 0 才 record_exit |
| `codex-rs/core/src/tools/router.rs` | 231 | ledger.invalidate |
| `codex-rs/core/src/turn_diff_tracker.rs` | 20-61 | TrackedContent / TrackedPath / TurnDiffTracker |
| 同文件 | 93-121 | track_delta / invalidate / get_unified_diff |
| 同文件 | 309-366 | render_diff（unified diff + blob oid） |
| 同文件 | 373-385 | display_path（多 environment 前缀） |
| `codex-rs/protocol/src/protocol.rs` | 1275-1279 | EventMsg serde tag/rename |
| 同文件 | 1326 | EventMsg::OrchestratedRoleUpdated |
| 同文件 | 1429 | EventMsg::TurnDiff |
| 同文件 | 1992-1998 | OrchestratedRoleUpdatedEvent 字段 |
| 同文件 | 3134-3168 | SessionMetaLine / session_id 回填 |
| 同文件 | 3171-3186 | RolloutItem serde（tag=type, content=payload） |
| 同文件 | 3239-3293 | TurnContextNetworkItem / TurnContextItem |
| 同文件 | 3688-3691 | TurnDiffEvent |
| `codex-rs/protocol/src/models.rs` | 842-857 | ContentItem serde |
| 同文件 | 932-958 | ResponseItem::Message serde |
| `codex-rs/context-fragments/src/fragment.rs` | 46-113 | ContextualUserFragment / into() → user InputText message |
| `codex-rs/rollout/src/recorder.rs` | 1500-1527 | `~/.codex/sessions/YYYY/MM/DD/rollout-{ts}-{conversation_id}.jsonl` |
| `codex-rs/thread-store/src/local/live_writer.rs` | 115-133 | append_items → RolloutRecorder（JSONL 优先于 SQLite） |
| `codex-rs/thread-store/src/local/read_thread.rs` | 30-70 | SQLite 只读元数据，history 从 rollout 读取 |
| `codex-rs/app-server/src/request_processors/thread_lifecycle.rs` | 736-746 | RolloutItem → Thread turns（API 返回） |
| `codex-rs/prompts/src/orchestrated.rs` | 1-12 | prompt 常量（include_str） |
| `codex-rs/prompts/templates/orchestrated/worker.md` | 1-7 | worker 契约：changed files / verification / packet 状态 |
| `codex-rs/prompts/templates/orchestrated/result_review.md` | 1 | result-review 契约：approved/revise + owner 行 |
| `codex-rs/prompts/templates/orchestrated/orchestrator.md` | 1 | root synthesis 契约（`orc:`、短合成、不复制 packet） |
| `codex-rs/core/src/agent/role.rs` | 30-36 | role 名字符串常量 |
| `codex-rs/core/src/context_manager/history_tests.rs` | 447-454 | facts 片段不是 turn boundary |
| `codex-rs/core/src/context/orchestrated_execution_facts_tests.rs` | 19-93 | facts 渲染、脱敏、边界、suppress/invalidate |
| `codex-rs/core/src/context/environment_context.rs` | 11-72 | FileSystemContext 只含 workspace_roots + permission profile，不含文件内容 |
| `codex-rs/core/src/context/world_state/environment.rs` | 246-281 | 环境上下文渲染：cwd/shell/status |
| `codex-rs/core/tests/suite/multi_agent_mode.rs` | 540-619 | facts 片段进入 review 输入、secret 不泄漏、suppress 语义 |
| 同文件 | 1680-1787 | orchestrator 只收 compact packets；rollout 只含 compact packet；resume 后仍只含 packets |

## Issue / 网络证据

| 来源 | 日期 | 内容 |
| --- | --- | --- |
| https://github.com/openai/codex/issues/32100 | 2026-07-10 | "Orchestrated multi-agent mode PoC"，yusing；描述 phase 流程、packet 语义、Result Review、Root Synthesis；声明 PoC 非生产就绪 |
| https://api.github.com/repos/yusing/codex/issues/32100 | 2026-08-14 查询 | 404（fork 仓库无此 issue） |
