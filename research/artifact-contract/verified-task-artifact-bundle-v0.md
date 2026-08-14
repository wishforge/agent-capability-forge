# VerifiedTaskArtifactBundle v0 — Artifact Boundary Contract（P0 冻结版）

- 状态：**FROZEN（P0）**
- `schema_version`：`verified-task-artifact-bundle-v0`
- 日期：2026-08-14
- 证据基线（本阶段唯一证据宇宙，未搜索新项目）：
  - `../docs/capability-forge-mvp-spec.md`（简称 `[spec]`）
  - `research/codex-artifact/verified-task-artifact-archaeology.md`（`[codex-arch]`）
  - `research/atif/harbor-atif-archaeology.md`（`[harbor-arch]`）
  - `research/swe-agent/swe-agent-trajectory-archaeology.md`（`[swe-arch]`）
  - `research/artifact-boundary-comparison.md`（`[boundary]`）
  - `research/codex-runtime-capture/codex-runtime-capture-archaeology.md`（`[runtime-capture]`，P1-A）

证据标签：

- `DIRECT`：当前 Codex 持久化材料可直接获得或确定性推导。
- `RUNTIME_CAPTURE`：需要 Artifact Builder 在 turn 结束时的 runtime capture point 捕获，当前 rollout 不含。
- `OPEN_NULLABLE`：当前无证据，字段显式允许为空 / OPEN，禁止伪造。
- `EVENT_CAPTURE`：依赖 opt-in 事件捕获（`CODEX_ROLLOUT_TRACE_ROOT` → rollout-trace `ExecCommandBegin/End`）；默认 rollout 不含，未开启时按 OPEN_NULLABLE 处理。
- `RUNTIME_CHANGE`：需要最小 runtime 修改才能捕获（capture point 已确认）；v0 未 instrumented 时保持 null/gap，禁止伪造。
- `NEW DESIGN`：本契约新增设计。
- `ADAPTED`：借鉴 Harbor ATIF / SWE-agent `.traj` 的机制（strict schema、显式 id、reference + digest、validation、artifact boundary、replay separation），**不复制其 schema**。

---

# 1. Purpose

VerifiedTaskArtifactBundle v0 是 Capability Forge 的 **Artifact Boundary Contract**：定义 Artifact Builder 最终必须产出的 Bundle 形态——每个字段从哪里来、如何验证、哪些目前只能 OPEN。

Bundle 是 **Capabilityization 的 immutable input boundary**：

```text
Codex Runtime（一次 turn）
  │  rollout JSONL（packets / facts / turn_diff / session_meta）+ runtime-only capture
  ▼
Artifact Builder
  │  解析 rollout + 捕获 runtime-only + 计算 digest → 原子写
  ▼
VerifiedTaskArtifactBundle（sealed、immutable）
  │  + immutable Workspace Snapshot / Artifact References
  │  + User Confirmation + LLM Proposal
  ▼
Capabilityizer（独立环境，不接 live session / workspace）
```

P0 只冻结契约：不写 `src`，不实现 Artifact Builder、Sandbox、Capabilityizer、API、SQLite、Replay。

吸收的三个项目先例（只吸收机制，不复制结构）：

- Harbor ATIF：strict versioned schema（`extra: forbid`）、显式 id（`session_id` ≠ `trajectory_id`）、外部文件 path 引用、`result.json` 与 trajectory 分离、文件存在性校验。[harbor-arch] §12
- SWE-agent `.traj`：artifact 边界分离（`.traj` / `.pred` / `results.json`）、`replay_config` 自描述、evaluation 只消费最小 prediction。[swe-arch] §10
- Codex：`TurnDiffEvent.unified_diff`、`SessionMetaLine` / `TurnContextItem`、packet 文本协议、失败类脱敏 facts。[codex-arch] §8、§9.2

---

# 2. Non-Goals

以下内容 **不属于 P0**，本契约不定义其 schema 或实现：

- Capabilityization
- entrypoint extraction
- parameterization
- private-state removal
- test generation
- validation execution（Validator / Sandbox）
- evaluation（CapabilityEvaluation）
- promotion
- registry
- runtime invoke
- revoke
- Replay 执行引擎（只允许 `replay_reference`）
- Artifact Builder 实现、Sandbox 实现、API、SQLite、Capabilityizer 实现
- 修改 Codex 运行时 / rollout 格式 / 现有 research 文件

P0 也不解决：

- 统计泛化证明（Novel Input Test ≠ Statistical Generalization Proof）[spec] §11
- 自动 Capability Gap Detection、Marketplace、Distributed Registry、MCP Capability 等 MVP Non-Goals。[spec] §4

---

# 3. Bundle Invariants

## 3.1 六边界原则

```text
Trajectory
!= ArtifactSet
!= Review
!= VerificationEvidence
!= EvaluationResult
!= ReplayConfig
!= CapabilityCandidate
```

Bundle 可以 **引用** 这些对象中的必要事实，但 Bundle 本身不能变成其中任何一个：

- Bundle ≠ Trajectory：Bundle 引用 rollout 副本与 packet 文本，不携带完整 history。
- Bundle ≠ ArtifactSet：文件全文在外部 immutable snapshot，Bundle 只持有 path + digest + content_ref。
- Bundle ≠ Review：review 状态是事实字段，`result-review: approved` 不携带验证语义。
- Bundle ≠ VerificationEvidence：命令级证据是独立 section，Codex v0 只允许 `status=unknown`。
- Bundle ≠ EvaluationResult：evaluation 永不写回 Bundle。[harbor-arch] §9；[swe-arch] §8
- Bundle ≠ ReplayConfig：只允许 optional `replay_reference`；Replay ≠ Capability Reuse。
- Bundle ≠ CapabilityCandidate：Candidate / Manifest / Promotion state 禁止进入 Bundle。[spec] §6.2

## 3.2 Bundle 自身属性

Bundle 生成后：

- **immutable**：生成即 sealed，无后续状态迁移。[spec] §12
- **content-addressable where applicable**：`bundle_id` 为 UUIDv7（NEW DESIGN），外部大对象以内容 digest 命名。
- **digestable**：`bundle_digest` 覆盖 canonical `bundle.json`；每个外部 artifact 有独立 digest。
- **independently readable**：除自身 store 内的 immutable 文件外不依赖任何 live 路径。

## 3.3 Capabilityizer 输入边界

Capabilityizer 允许读取：

1. VerifiedTaskArtifactBundle
2. Bundle 引用的 immutable artifacts（workspace snapshot / file refs / rollout 副本）
3. User Confirmation
4. LLM Proposal

Capabilityizer 禁止：

- live session
- live Agent context
- live workspace path
- 当前 Codex process state

rollout 解析与 runtime-only 捕获全部属于 Artifact Builder。[boundary] §7

---

# 4. Root Schema

## 4.1 顶层 JSON

```json
{
  "schema_version": "verified-task-artifact-bundle-v0",
  "bundle_id": "019fxxxx-xxxx-7xxx-xxxx-xxxxxxxxxxxx",
  "identity": {},
  "execution": {},
  "artifacts": {},
  "review": {},
  "verification_evidence": {},
  "environment": {},
  "replay_reference": null,
  "security": {},
  "provenance": {}
}
```

## 4.2 顶层字段

| 字段 | 类型 | Required | Nullable | Immutable | 摘要 |
|---|---|---|---|---|---|
| `schema_version` | string（literal） | Y | N | Y | 固定为 `verified-task-artifact-bundle-v0` |
| `bundle_id` | string（UUIDv7） | Y | N | Y | Artifact Builder 生成，唯一 |
| `identity` | object | Y | N | Y | §5 |
| `execution` | object | Y | N | Y | §6（`final_phase` 含 `outcome` / `worker_packet_sequence`） |
| `artifacts` | object | Y | N | Y | §7 |
| `review` | object | Y | N | Y | §8 |
| `verification_evidence` | object | Y | N | Y | §9 |
| `environment` | object | Y | N | Y | §10 |
| `replay_reference` | object \| null | N（optional） | Y | Y | §11；v0 为 null |
| `security` | object | Y | N | Y | secrets policy marker（Validation Rule 11 需要） |
| `provenance` | object | Y | N | Y | §12 |

顶层与所有嵌套对象遵循 strict schema：**未知 key 一律拒绝**（ADAPTED：Harbor `extra: forbid`，[harbor-arch] §2）。Bundle 内禁止 Candidate / Capability Manifest / Promotion state / Evaluation Result / secrets / live workspace dependency。

---

# 5. Identity

## 5.1 逐字段契约

| 字段 | 类型 | Required | Nullable | Codex 当前可获得？ | 来源 | RUNTIME_CAPTURE？ | OPEN？ | Immutable |
|---|---|---|---|---|---|---|---|---|
| `bundle_id` | UUIDv7 | Y | N | 否（新结构） | Artifact Builder 在 seal 时生成 | Y（capture point §16.1） | N | Y |
| `source_task_id` | string \| null | Y | Y | 否 | Codex 无 task 概念；不得用 thread_id 冒充 | 未来（§16.8） | Y | Y |
| `source_execution_id` | string \| null | Y | Y | 否 | Artifact Builder 为一次 turn 执行分配；≠ session/thread/turn/bundle | Y（capture point §16.1） | N（字段存在；值可为 null） | Y |
| `session_id` | string | Y | N | 是 | `SessionMetaLine.session_id`（缺失时从 `id` 回填）[codex-arch] §7.4 | N | N | Y |
| `thread_id` | string | Y | N | 是 | rollout 文件名 `rollout-{ts}-{thread_id}.jsonl`；thread-store 元数据 [codex-arch] §7.1、§8.3 | N | N | Y |
| `turn_id` | string \| null | Y | Y | 部分 | `TurnContextItem.turn_id?`；持久化 packet 消息 id / passthrough [codex-arch] §7.4、§8.3 | N | 允许 null（rollout 缺省时） | Y |
| `producer` | string | Y | N | 是 | 执行 runtime 身份：`codex-cli-fork` + mode `orchestrated`（基线 [codex-arch] §2.1） | N | N | Y |
| `producer_commit` | string | Y | N | 是 | 源码基线 commit `658630b2931ac841e2f1bc437daa1b931d173c0c` [codex-arch] §2.1 | N | N | Y |
| `generated_at` | string（ISO8601） | Y | N | 是（需捕获） | turn 执行完成时刻（run_turn 返回时），不是 seal 时刻 | Y（capture point §16.1） | N | Y |

## 5.2 Identity 禁止事项

- `bundle_id`、`source_execution_id`、`session_id`、`thread_id`、`turn_id` **禁止互相混用**。
- Harbor 先例：`session_id` 是 run 级、可被多个文档共享；`trajectory_id` 是文档级。Bundle 沿用同一原则——session/thread 标识执行上下文，`bundle_id` 只标识密封文档。[harbor-arch] §7、§12.6
- `source_task_id` 在 Codex 当前无来源；v0 必须为 null + `provenance.gaps` 记录 `task_id`。禁止把 `thread_id` 或 `turn_id` 写成 `source_task_id`。

P1-A 已确认（`[runtime-capture] §5`）：

- `session_id`：`SessionMeta.session_id`（`codex-rs/protocol/src/protocol.rs:3056`），本 fork 创建时 = thread_id（`codex-rs/rollout/src/recorder.rs:179-181`）。
- `thread_id`：`SessionMeta.id`（`codex-rs/protocol/src/protocol.rs:3057`）；rollout 文件名 `rollout-{ts}-{conversation_id}.jsonl`（`codex-rs/rollout/src/recorder.rs:1519`）。
- `turn_id`：`TurnContext.sub_id`（`codex-rs/core/src/session/turn_context.rs:105,381`）；packet 消息 passthrough（`codex-rs/core/src/session/mod.rs:2817-2820`）。
- wire 协议中的 `task_started` / `task_complete` 是 `TurnStarted` / `TurnComplete` 的 serde 别名（`codex-rs/protocol/src/protocol.rs:1322-1323,1333-1335`）——是 turn 事件，**不是 task id**；`source_task_id` 维持 null + gap `task_id`。

---

# 6. Execution

## 6.1 Schema

```json
{
  "rollout_ref": {
    "path": "execution/rollout.jsonl",
    "digest": "sha256:...",
    "source": "runtime_capture"
  },
  "phases": [
    {
      "phase": "task-contract | explorer | worker-plan | plan-review | plan-evidence | worker | result-review",
      "sequence": 1,
      "packet": "worker: complete\n...",
      "packet_ref": null,
      "truncated": false,
      "status": "complete | incomplete | invalid | approved | revise | direct | evidence-needed | unknown",
      "owner": "worker | explorer | root | user | null",
      "source": "rollout"
    }
  ],
  "final_phase": {
    "phase": "worker | result-review",
    "outcome": "completed | stopped | skipped",
    "worker_status": "complete | incomplete | invalid",
    "worker_packet_sequence": 1,
    "result_review_status": "approved | revise | none",
    "correction_owner": "worker | explorer | root | user | null",
    "authority": "runtime_capture",
    "truncated": false,
    "retry_count": 0,
    "captured_at": "2026-08-14T..."
  },
  "root_synthesis": {
    "text": "orc: ...",
    "truncated": false,
    "source": "rollout"
  }
}
```

## 6.2 逐项定义

| 字段 | 定义 |
|---|---|
| `rollout_ref` | Bundle 引用的 immutable rollout 副本（reference + digest）。源文件是 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` [codex-arch] §7.1；Builder 复制入 store，Bundle 内**不存 live 绝对路径**。 |
| `phases[]` | 从 rollout 按文本前缀提取的 phase packet，按出现顺序编号。`packet` 内嵌（packet 有界：8192 字节 / PlanEvidence 1000 token [codex-arch] §3.3），不再加 `packet_ref`。 |
| `phase` | 角色常量枚举 [codex-arch] §8.1。 |
| `sequence` | rollout 内出现顺序，1 起连续。 |
| `packet` | packet 原文（截断后的文本）。 |
| `packet_ref` | 本契约保留字段，v0 恒为 `null`（packet 有界、内嵌）。 |
| `truncated` | 由文本末尾 `[packet truncated: ...]` 后缀确定性反推 [codex-arch] §8.1。 |
| `status` | 与运行时同一语法解析的状态（`worker_status` / `review_approved` / `correction_owner` 等）[codex-arch] §8.1。 |
| `owner` | `result-review: revise` 下一行 `owner:` 解析值，否则 null [codex-arch] §5.2。 |
| `source` | 固定 `"rollout"`（v0 所有 packet 均来自 rollout）。 |
| review packet | 由 `phases[]` 中 `phase="result-review"` 的 packet 承载，解析后的语义字段见 §8；不单独复制。 |
| `final_phase` | **唯一权威最终状态**（见 6.3；含 `outcome` / `worker_packet_sequence`）。v0 未改 runtime 时整对象为 null。 |
| `final_phase.outcome` | `run_phases` authoritative runtime state 的最终结果：`completed \| stopped \| skipped`；不得按 rollout packet 顺序推断。 |
| `final_phase.worker_packet_sequence` | `execution.phases[]` 中最终有效 Worker packet 的 `sequence`（integer）；无有效 Worker packet 时为 `null`；由 runtime state 确定，rollout packet 顺序不得用于推断。 |
| `root_synthesis` | phase 之后首条 `orc:` 前缀 assistant 消息；不存在时为 null [codex-arch] §6.5、§9.2。 |

## 6.3 最终有效 Worker Packet 如何确定

**结论：`run_phases` runtime 状态是唯一权威。** `run_phases` 包含 retry（`MAX_WORK_REVISIONS=2`）、supersede、truncation、retry signature 防死循环等语义；rollout 只有压缩后的 packet 序列，**不能**从 rollout 反推最终有效 worker packet。[codex-arch] §6.3-6.4、§10.3.2

P1-A 已确认（`[runtime-capture] §3`）：break 原因（retry signature 重复、truncated 布尔、`Outcome::Stopped`）不持久化；`compact_phase_history` 会保留被 revise 的旧 worker packet（`codex-rs/core/src/session/orchestrated.rs:617-655`）且无 supersede 标记。因此 **rollout packet 顺序不能确定最终 effective worker packet；必须依赖 runtime phase state**。Capture point：`run_phases` 返回边界（`codex-rs/core/src/session/orchestrated.rs:409`），被 `run_for_input` 于 `orchestrated.rs:170-179` 调用处。

**runtime capture point（§16.2）**：Artifact Builder 在 `run_phases` 返回边界（`orchestrated.rs:409`）捕获：

- 最终 `Outcome`（`Completed / Stopped / Skipped`）→ `final_phase.outcome`
- 最终有效 Worker packet 在 `execution.phases[]` 中的 `sequence`（无有效 packet 为 null）→ `final_phase.worker_packet_sequence`
- 最终 WorkerExec `PhasePacket`（text、truncated、execution_facts）
- 最终 ResultReview 判定（approved / revise + owner）
- retry 计数与是否因 retry signature 提前 break

该状态需经 accumulator（或 `run_phases` / `run_for_input` 返回值）带到 Builder hook（§16.1）；Resolution = **RUNTIME_CHANGE**。v0（未 instrumented 的 Codex）：`final_phase = null`，`provenance.gaps` 必须含 `final_phase_authority`。禁止从 rollout 猜测最终状态。

---

# 7. Artifacts

## 7.1 Schema

```json
{
  "unified_diff": "diff --git a/... b/...\n...",
  "files": [
    {
      "path": "src/main.py",
      "previous_path": null,
      "status": "added | modified | deleted | renamed",
      "digest": "sha256:...",
      "content_ref": "artifacts/files/sha256:...",
      "media_type": "text/x-python",
      "size_bytes": 1234,
      "executable": false
    }
  ]
}
```

## 7.2 核心原则

- **path ≠ content**：`path` 只是位置标识。
- **digest ≠ content**：`digest` 是校验值，不是内容载体。
- **content_ref → immutable file snapshot**：`content_ref` 指向 artifact store 内 content-addressed 文件，Bundle 不携带 workspace 全文。[boundary] §5.3

## 7.3 字段契约

| 字段 | Required | Nullable | 来源 | Resolution |
|---|---|---|---|---|
| `unified_diff` | Y | N | `EventMsg::TurnDiff` / `TurnDiffEvent.unified_diff` [codex-arch] §8.3 | DIRECT |
| `files[]` | Y（可为空数组） | — | 最终文件 snapshot + diff 路径解析 [codex-arch] §9.1 | RUNTIME_CAPTURE |
| `path` | Y | N | 相对 workspace root 的路径（diff 解析） | DIRECT（diff 有路径时） |
| `previous_path` | N | Y | 仅 `status=renamed` 时填旧路径 | RUNTIME_CAPTURE（diff 解析） |
| `status` | Y | N | `added / modified / deleted / renamed`（由 diff 解析，normalization 为 NEW DESIGN） | DIRECT |
| `digest` | 条件必填 | Y | `sha256` 最终文件内容；deleted 为 null | RUNTIME_CAPTURE |
| `content_ref` | 条件必填 | Y | `artifacts/files/<digest>`；deleted 为 null | RUNTIME_CAPTURE |
| `media_type` | 条件必填 | Y | Builder 由扩展名 / 内容推断；未知可为 null | RUNTIME_CAPTURE |
| `size_bytes` | 条件必填 | Y | snapshot stat；deleted 为 null | RUNTIME_CAPTURE |
| `executable` | N | Y | 最终文件 mode 的 executable 位（NEW DESIGN：供 P1 entrypoint extraction 使用；`mode` 未引入，权限保真需要时再加） | RUNTIME_CAPTURE |

deleted / renamed 语义：

- `status=deleted`：`digest`、`content_ref`、`media_type`、`size_bytes`、`executable` 必须为 null（没有外部 artifact）。
- `status=renamed`：`path` = 新路径，`previous_path` = 旧路径；`digest`/`content_ref` 指向新内容（内容未变时指向同一 digest 文件）。

一致性规则：

- `files[]` 非空时，每个非 deleted 文件必须有 `digest + content_ref`。
- `unified_diff` 非空但 `files[]` 为空：允许，但 `provenance.gaps` 必须含 `final_file_snapshot`。
- `files[].digest` 与 `content_ref` 文件名一致（`content_ref` 必须以 `sha256:` digest 命名）。

P1-A 已确认（`[runtime-capture] §2`）：`files[]` 的 capture point 是 **`run_sampling_request` 尾部（`codex-rs/core/src/session/turn.rs:2518-2529`，root context：`turn_context.orchestrated_role.is_none()`）**——最终 `TurnDiff` emit 之后、tracker drop 之前，按最终 diff 路径从磁盘读文件做 sha256（deleted 除外）；内存全文 maps 在 `codex-rs/core/src/turn_diff_tracker.rs:20-61`（`baseline_by_path` / `current_by_path`，无公开 accessor）。Resolution = **RUNTIME_CAPTURE**（磁盘快照无需 runtime change；内存精确内容 accessor 可选）。

---

# 8. Review

```json
{
  "worker_status": "complete | incomplete | invalid",
  "result_review_status": "approved | revise | none",
  "correction_owner": "worker | explorer | root | user | null",
  "interpretation": "model_review_only"
}
```

| 字段 | Required | Nullable | 来源 | Resolution |
|---|---|---|---|---|
| `worker_status` | Y | N | packet 文本解析（`worker: complete/incomplete`，否则 invalid）[codex-arch] §8.1 | DIRECT |
| `result_review_status` | Y | N | packet 文本解析（`result-review: approved/revise`；无则 `none`）[codex-arch] §5.2 | DIRECT |
| `correction_owner` | Y | Y | revise 下一行 `owner:` 解析 [codex-arch] §5.2 | DIRECT |
| `interpretation` | Y | N | 常量 `"model_review_only"`（NEW DESIGN） | DIRECT |

**语义冻结：**

`result-review: approved` 只能表示“模型 review 认可 Worker packet”（模型文本判断），**绝对不能表示 Task Verification PASS**，更不能表示 Capability Evaluation PASS 或 Promotion。[codex-arch] §5.2；[spec] §6.5

Review 与 VerificationEvidence 是独立 section；Review 不可用作命令级验证证据。

---

# 9. VerificationEvidence

## 9.1 Schema

```json
{
  "status": "unknown | complete",
  "command": null,
  "exit_code": null,
  "stdout_ref": null,
  "stderr_ref": null,
  "checker_result": null,
  "evidence_digest": null,
  "evidence_refs": [],
  "gaps": ["verification_evidence: no structured command-level evidence in Codex v0"],
  "captured_at": null
}
```

| 字段 | Type | Required | Nullable | Immutable | 来源 / Resolution |
|---|---|---|---|---|---|
| `status` | enum | Y | N | Y | 默认 `"unknown"`；开启 trace 且 Builder 捕获到可复验 evidence 时可为 `"complete"`（Rule 10） | EVENT_CAPTURE |
| `command` | string | Y | Y | Y | 命令级验证命令；来自 `ExecCommandBegin/EndEvent.command`；status=unknown 时必须 null，禁止伪造 | EVENT_CAPTURE |
| `exit_code` | int | Y | Y | Y | 来自 `ExecCommandEndEvent.exit_code`（root 阶段 rollout DIRECT / worker 阶段 trace）；成功命令 exit_code=0 不产生 facts [codex-arch] §9.1-5 | EVENT_CAPTURE |
| `stdout_ref` | `{path, digest} \| null` | Y | Y | Y | 外部 evidence 文件引用（来自 `ExecCommandEndEvent.stdout`）；status=unknown 时必须 null | EVENT_CAPTURE |
| `stderr_ref` | `{path, digest} \| null` | Y | Y | Y | 同上（来自 `ExecCommandEndEvent.stderr`） | EVENT_CAPTURE |
| `checker_result` | object \| null | Y | Y | Y | `{checker, verdict, detail_ref?, digest?}`；runtime 无 checker，由未来独立 checker 提供；status=unknown 时必须 null | OPEN_NULLABLE |
| `evidence_digest` | string \| null | Y | Y | Y | 全部 evidence 文件集合 digest；有 evidence 时 Builder 计算 | EVENT_CAPTURE |
| `evidence_refs` | array | Y | N（可为 `[]`） | Y | 每个元素 `{path, digest, role}`；v0 默认 `[]`，trace 开启后可填充 | EVENT_CAPTURE |
| `gaps` | array[string] | Y | N | Y | 缺失项记录；status=unknown 时必须非空 | RUNTIME_CAPTURE |
| `captured_at` | string \| null | Y | Y | Y | 捕获时刻；无 evidence 时 null | EVENT_CAPTURE |

## 9.2 Codex 当前事实与禁止项

- Codex 默认 rollout **没有稳定结构化 command-level verification artifact**；只有 worker packet 文本声明 + Result Review 模型判断。[codex-arch] §5
- root 阶段：`send_event` 中 `persist = orchestrated_role.is_none()`（`codex-rs/core/src/session/mod.rs:1831`）→ root 阶段 `ExecCommandBegin/End` 已持久化于 rollout（DIRECT）。
- worker 阶段：默认不持久化（同上）；设置 `CODEX_ROLLOUT_TRACE_ROOT`（`codex-rs/rollout-trace/src/thread.rs:44`）后，rollout-trace 全阶段（含 worker）写入 `ExecCommandBegin/End`（`codex-rs/rollout-trace/src/thread.rs:237-248`），payload 含 command / stdout / stderr / exit_code / duration（`codex-rs/rollout-trace/src/protocol_event.rs:260-274`，`ExecCommandBegin/EndTracePayload` `:147-258`）→ **EVENT_CAPTURE**；这些字段可以作为 **worker phase execution evidence**。
- 无 trace 环境：worker 阶段为 OPEN（失败 facts + packet 文本声明），v0 保持 `status = "unknown"`、`evidence_refs = []`、`gaps = [...]`。
- **禁止伪造** `exit_code`、`stdout`、`stderr`、`checker_result`、`evidence_digest`。
- `status = "complete"` 仅在 Builder 持有可复验 `evidence_refs` 时使用（Validation Rule 10）；`command/stdout/stderr/exit_code/duration` 来自 trace / rollout 事件，不是模型文本声明。
- runtime capture point（§16.4）：Artifact Builder 订阅 `EventMsg::ExecCommandBegin/End` 或读取 trace bundle；未来可选最小 runtime change：`session/mod.rs:1831` 放行 exec 事件。

---

# 10. Environment

## 10.1 Schema

```json
{
  "cwd": "<home>/big-wish/research",
  "workspace_roots": ["<home>/big-wish/research"],
  "network": {
    "allowed_domains": [],
    "denied_domains": []
  },
  "permission_policy": {
    "approval_policy": "OnRequest",
    "sandbox_policy": "read-only",
    "permission_profile": "workspace-write"
  },
  "environment_snapshot_ref": {
    "path": "environment/snapshot.json",
    "digest": "sha256:..."
  },
  "dependency_manifest_ref": null
}
```

## 10.2 逐项判定

| 字段 | Required | Nullable | 判定 | 来源 |
|---|---|---|---|---|
| `cwd` | Y | N | DIRECT | `TurnContextItem.cwd`（`AbsolutePathBuf`，持久化）[codex-arch] §7.4、§8.3 |
| `workspace_roots` | array \| null | Y | DIRECT（字段可选，缺失为 null） | `TurnContextItem.workspace_roots?` [codex-arch] §8.3 |
| `network` | object \| null | Y | DIRECT（字段可选） | `TurnContextNetworkItem{allowed_domains, denied_domains}` [codex-arch] §8.3 |
| `permission_policy` | object \| null | Y | DIRECT（字段可选） | `TurnContextItem.approval_policy / sandbox_policy / permission_profile` [codex-arch] §8.3 |
| `environment_snapshot_ref` | object \| null | Y | RUNTIME_CAPTURE | Builder 在 turn 结束写 `environment/snapshot.json`（cwd/shell/roots/policy 等环境上下文快照）；未实现则 null + gap `environment_snapshot` |
| `dependency_manifest_ref` | object \| null | Y | OPEN_NULLABLE | Codex 无 dependency manifest；v0 必须 null + gap `dependency_manifest` [codex-arch] §9.1-9 |

注意：

- workspace path 本身 **不是** 完整 environment；`cwd / workspace_roots` 只是元数据。
- 不得声称 Codex 当前已存在 dependency manifest。
- `environment_snapshot_ref` 指向 Bundle store 内的 immutable 快照，不是 live workspace。

---

# 11. ReplayReference

```json
{
  "kind": "rollout | command_sequence | environment_reconstruction",
  "ref": { "path": "...", "digest": "sha256:..." },
  "description": null
}
```

| 字段 | Required | Nullable | 判定 |
|---|---|---|---|
| `replay_reference`（整体） | N（optional） | Y | OPEN_NULLABLE；v0 Codex producer 必须为 null |
| `kind` | 条件必填 | N | 枚举：rollout / command_sequence / environment_reconstruction |
| `ref` | 条件必填 | N | reference + digest |
| `description` | N | Y | 人类可读说明 |

语义冻结：

- ReplayReference 只能是：trajectory/rollout reference、command sequence reference、environment reconstruction reference。
- **Replay ≠ Capability Invoke**：replay 是重放原执行；invoke 是用新 input 调用 promoted capability。[spec] §6.10
- **Replay ≠ Reuse**：`replay_reference` 不作为 Capabilityizer 的复用输入，不参与 invoke。
- v0 不实现 replay；Codex 无 replay config（[codex-arch] §9.1-9；[boundary] §3），因此 `replay_reference = null`，`provenance.gaps` 含 `replay_reference`。

---

# 12. Provenance

## 12.1 Schema

```json
{
  "source_artifact_digest": "sha256:...",
  "source_rollout_digest": "sha256:...",
  "workspace_snapshot_digest": "sha256:...",
  "bundle_digest": "sha256:...",
  "producer": "codex-artifact-builder-v0",
  "producer_commit": null,
  "generated_at": "2026-08-14T...",
  "gaps": []
}
```

## 12.2 Digest 映射（哪个 digest 对哪个 artifact）

| Digest | 对应 artifact | 计算方式 |
|---|---|---|
| `source_rollout_digest` | `execution/rollout.jsonl`（rollout 副本） | sha256(rollout 文件内容) |
| `workspace_snapshot_digest` | `artifacts/files` snapshot manifest（path → digest 有序清单） | sha256(canonical JSON of manifest) |
| `source_artifact_digest` | **source artifact set**：`{source_rollout_digest, workspace_snapshot_digest, environment_snapshot_digest, verification_evidence.evidence_digest}` | sha256(canonical JSON of digest-set)，即 digest-of-digests |
| `bundle_digest` | canonical `bundle.json` | 下述 8 步规范化算法（计算时自身固定 null） |

禁止混淆：

- `source_*_digest` 只指 **read-only 输入**；Bundle 内不存在 forged digest。
- `forged_artifact_digest` 属于 Capability Candidate / Manifest（P1），永远不写入 Bundle。[spec] §8、§17
- 外部 artifact 内容变化会改变对应 digest；`bundle_digest` 覆盖这些 digest 字段本身，不覆盖外部文件内容（外部文件完整性由其自身 digest 验证）。

**`bundle_digest` 计算算法（P0 冻结）：**

1. 对 sealed `bundle.json` 做 canonical JSON 序列化。
2. 所有 key 递归排序（lexicographic order）。
3. 使用紧凑表示（compact，无多余空白）。
4. 序列化输出无尾随换行。
5. 计算时 `provenance.bundle_digest` 固定为 `null`（禁止自引用参与）。
6. 对规范化字节串计算 SHA-256。
7. 以 `sha256:<hex>` 写回 `provenance.bundle_digest`（seal 后固定）。
8. 验证时重复步骤 1-6 的相同规范化流程，与记录值比对。

## 12.3 字段契约

| 字段 | Type | Required | Nullable | Resolution |
|---|---|---|---|---|
| `source_artifact_digest` | string | Y | N | RUNTIME_CAPTURE（Builder 计算） |
| `source_rollout_digest` | string | Y | N | RUNTIME_CAPTURE |
| `workspace_snapshot_digest` | string | Y | N | RUNTIME_CAPTURE |
| `bundle_digest` | string | Y | N | RUNTIME_CAPTURE |
| `producer` | string | Y | N | DIRECT（常量 `codex-artifact-builder-v0`，NEW DESIGN） |
| `producer_commit` | string \| null | Y | Y | OPEN_NULLABLE（Builder 实现提交；P0 无实现，可为 null） |
| `generated_at` | string（ISO8601） | Y | N | RUNTIME_CAPTURE（seal 时刻） |
| `gaps` | array[string] | Y | N | RUNTIME_CAPTURE；必须覆盖所有 OPEN_NULLABLE 项 |

`identity.generated_at` = 执行完成时刻；`provenance.generated_at` = Bundle seal 时刻。二者不同义。

`bundle_digest` 计算时自身固定为 `null`，SHA-256 后写回真实 digest（算法见 §12.2）；验证时重复相同规范化流程。

---

# 13. Validation Rules

确定性校验，逐条冻结。任何一条 FAIL → Bundle 拒绝进入 Capabilityization。

| # | Rule | 校验方法 | FAIL 条件 | v0 状态 |
|---|---|---|---|---|
| 1 | `schema_version` | 精确匹配 literal | 非 `verified-task-artifact-bundle-v0` | FROZEN |
| 2 | `bundle_id` | UUIDv7 格式 + store 内唯一 | 格式非法 / 重复 | FROZEN |
| 3 | required fields | presence + type + unknown-key 拒绝（`extra: forbid`，ADAPTED [harbor-arch] §2） | 缺字段 / 类型错 / 未知 key | FROZEN |
| 4 | digest format + `bundle_digest` canonical recompute | 全部 digest 匹配 `^sha256:[0-9a-f]{64}$`；`bundle_digest` 按 §12.2 规范化流程重算（key 排序、紧凑 JSON、无尾随换行、计算时 `provenance.bundle_digest=null`）与记录值一致 | 格式不符 / 重算不一致 | FROZEN |
| 5 | reference resolution | 所有 ref 为 store 相对路径；禁止绝对路径、`..`、`file://` | 无法解析 | FROZEN |
| 6 | immutable artifact existence | 每个 content_ref / ref 指向的文件存在且可读 | 缺失 | FROZEN |
| 7 | file digest match | 重算每个外部文件 sha256 与记录值比对 | 不一致 | FROZEN |
| 8 | phase ordering + final-phase runtime authority | `phases[].sequence` 1 起连续；phase 流转符合 `run_phases` 状态机（含 retry 循环）；`final_phase` 只允许 `authority=runtime_capture` 或整对象 null；`outcome` 枚举 completed/stopped/skipped；`worker_packet_sequence` 为 null 或指向存在的 `phase="worker"` 条目且与 runtime 最终有效 packet 一致 | 顺序非法 / 无 runtime authority 却填充 final_phase / `outcome` 枚举外 / `worker_packet_sequence` 越界、指向非 worker 条目或与 runtime 最终有效 packet 不一致 | FROZEN（v0 无 authority 时 final_phase 必须 null） |
| 9 | review status grammar | `worker_status` / `result_review_status` / `correction_owner` 枚举 + 与 packet 文本一致 | 枚举外值 / 与文本矛盾 | FROZEN |
| 10 | verification status grammar | `status=unknown` ⇒ command/exit_code/stdout_ref/stderr_ref/checker_result 为 null、evidence_refs=[]、gaps 非空；`status=complete` ⇒ evidence_refs 非空且 evidence_digest 存在 | 伪造字段 / unknown 却有证据 / complete 无证据 | FROZEN |
| 11 | secrets policy marker | `security` 必须存在；`scan_status` 枚举；`not_scanned` ⇒ gaps 含 `secrets_scan`；`scanned` ⇒ scan_ref + scan_digest 存在 | marker 缺失 / 状态矛盾 / 未扫描却声称扫描 | FROZEN |
| 12 | no live workspace dependency | 所有 ref 相对 store 解析；`cwd/workspace_roots` 仅作元数据，不作为 ref 解析依据 | 引用 live 路径 / 绝对路径 ref | FROZEN |
| 13 | no Candidate / Capability / Promotion state inside Bundle | schema 禁止字段存在性检查（Candidate、Manifest、Promotion、Evaluation Result 等 key 出现即 FAIL；未知 key 由 Rule 3 兜底） | 出现任何禁止对象 | FROZEN |

可执行性说明：规则 6/7 需要 artifact store 存在（P1）；规则 8 的 final-phase 部分需要 runtime capture point（§16.2）。规则本身已冻结；当前不能执行的部分标记 OPEN，不猜测。

---

# 14. Storage Layout

逻辑布局（不实现；`<bundle_id>` 为密封后目录）：

```text
artifact-contract/
  verified-task-artifact-bundle-v0.md   # 本契约
  bundles/<bundle_id>/
    bundle.json                         # 唯一 sealed 文档（含 provenance、security）
    artifacts/
      files/<sha256:...>                # 最终文件内容，content-addressed
    execution/
      rollout.jsonl                     # rollout 副本
    verification/
      evidence/<sha256:...>             # 未来命令级证据（v0 无）
    environment/
      snapshot.json                     # 环境上下文快照
    replay/                             # 未来 replay 引用目标（v0 无）
```

Sealing：`bundle.json` 按 §12.2 算法计算 `bundle_digest`（canonical JSON、key 排序、紧凑、无尾随换行；计算时 `provenance.bundle_digest=null`），SHA-256 后写回真实 digest，Bundle 即 sealed、immutable；验证时重复相同规范化流程重算比对（Rule 4）。

Inline / Reference / External 划分：

| 内容 | 存放 | 理由 |
|---|---|---|
| `schema_version`、`bundle_id`、identity、review 状态、verification status/gaps、environment 元数据、provenance digests、security marker | inline（bundle.json） | 小、结构化、schema 核心 |
| phase packet 文本、`unified_diff` | inline（bundle.json） | packet 有界（[codex-arch] §3.3）；diff 是机器可读小文本 |
| `rollout_ref`、`environment_snapshot_ref`、`dependency_manifest_ref`、verification `stdout_ref/stderr_ref/evidence_refs`、`files[].content_ref`、`replay_reference.ref` | reference（bundle.json 内仅 path+digest） | 大对象 / 可内容寻址 |
| 文件全文、rollout 副本、环境快照、验证输出 | external immutable artifact（store 内 `<digest>` 命名） | 引用优于嵌入；避免 Harbor 大 content 与 SWE 非原子写缺陷 [harbor-arch] §13.7；[swe-arch] §11.1 |

与示例布局的差异（明确说明）：

- 不单独写 `provenance.json`：provenance 内嵌 bundle.json，避免双文档漂移。
- 不单独写 `artifacts/diff.patch`：`unified_diff` 内嵌；需要 patch 文件时由消费端从 bundle.json 导出（YAGNI）。
- 不把多个 Bundle 直接堆在 `artifact-contract/` 根：用 `bundles/<bundle_id>/` 隔离。

---

# 15. Field Mapping Matrix

Resolution 取值仅：`DIRECT` / `RUNTIME_CAPTURE` / `EVENT_CAPTURE` / `RUNTIME_CHANGE` / `OPEN_NULLABLE`。

| Bundle Field | Required | Source | Evidence | Resolution | Immutable | Digest | Notes |
|---|---|---|---|---|---|---|---|
| `schema_version` | Y | 契约常量 | [spec] §7.1；ADAPTED Harbor [harbor-arch] §12.1 | DIRECT | Y | 计入 bundle_digest | literal `verified-task-artifact-bundle-v0` |
| `bundle_id` | Y | Builder 生成 UUIDv7 | NEW DESIGN | RUNTIME_CAPTURE | Y | 计入 bundle_digest | ≠ session/thread/turn/execution id |
| `identity.source_task_id` | Y（可 null） | 无 | Codex 无 task 概念；wire `task_started/task_complete` = `TurnStarted/TurnComplete` 别名 `protocol.rs:1322-1323,1333-1335` [runtime-capture] §5 | OPEN_NULLABLE | Y | — | 禁止用 thread_id / turn_id 冒充；gap `task_id` |
| `identity.source_execution_id` | Y（可 null） | Builder 为一次 turn 分配 | NEW DESIGN | RUNTIME_CAPTURE | Y | — | ≠ bundle_id |
| `identity.session_id` | Y | `SessionMetaLine.session_id`（回填 `id`） | [codex-arch] §7.4；`SessionMeta.session_id` `protocol.rs:3056`、`recorder.rs:179-181` [runtime-capture] §5 | DIRECT | Y | — | run 级；本 fork 中 = thread_id |
| `identity.thread_id` | Y | rollout 文件名 / thread-store | [codex-arch] §7.1、§8.3；`SessionMeta.id` `protocol.rs:3057`、`recorder.rs:1519` [runtime-capture] §5 | DIRECT | Y | — | ≠ task id |
| `identity.turn_id` | Y（可 null） | `TurnContextItem.turn_id?` / 消息 passthrough | [codex-arch] §7.4、§8.3；`TurnContext.sub_id` `turn_context.rs:105,381`、`session/mod.rs:2817-2820` [runtime-capture] §5 | DIRECT | Y | — | rollout 缺失时 null |
| `identity.producer` | Y | 执行 runtime 身份 | [codex-arch] §2.1 | DIRECT | Y | — | `codex-cli-fork` + mode |
| `identity.producer_commit` | Y | 源码基线 commit | [codex-arch] §2.1 | DIRECT | Y | — | `658630b...` |
| `identity.generated_at` | Y | run_turn 完成时刻 | [codex-arch] §6.1 | RUNTIME_CAPTURE | Y | — | 执行时刻，非 seal 时刻 |
| `execution.rollout_ref` | Y | Builder 复制 rollout 入 store | [codex-arch] §7.1 | RUNTIME_CAPTURE | Y | sha256（rollout） | 外部 immutable 引用 |
| `execution.phases[]` | Y | rollout packet 提取 | [codex-arch] §9.2.1 | DIRECT | Y | packet 计入 bundle_digest | 有序 |
| `phases[].phase` | Y | 角色枚举 | [codex-arch] §8.1 | DIRECT | Y | 同上 | — |
| `phases[].packet` | Y | rollout `response_item` 文本 | [codex-arch] §6.3 | DIRECT | Y | 同上 | 内嵌；有界 |
| `phases[].truncated` | Y | 截断后缀反推 | [codex-arch] §3.3、§8.1 | DIRECT | Y | 同上 | 文本歧义低风险 |
| `phases[].status` | Y | 与运行时同一语法解析 | [codex-arch] §8.1 | DIRECT | Y | 同上 | 枚举 |
| `phases[].owner` | Y（可 null） | revise 下一行 owner | [codex-arch] §5.2 | DIRECT | Y | 同上 | — |
| `phases[].sequence` | Y | rollout 顺序 | [codex-arch] §6.3 | DIRECT | Y | 同上 | 1 起连续 |
| `phases[].source` | Y | 常量 `rollout` | NEW DESIGN | DIRECT | Y | 同上 | v0 固定 |
| `execution.final_phase` | Y（可 null） | `run_phases` runtime outcome | [codex-arch] §6.2-6.4；`run_phases` 返回边界 `orchestrated.rs:409` [runtime-capture] §3 | RUNTIME_CHANGE | Y | — | rollout 顺序不能确定最终有效 packet；未 instrumented 时 null + gap；禁止猜测 |
| `execution.final_phase.outcome` | Y | `run_phases` 最终 `Outcome` | [runtime-capture] §3；`run_phases` 返回边界 `orchestrated.rs:409` | RUNTIME_CHANGE | Y | — | completed / stopped / skipped；rollout 顺序不得用于推断 |
| `execution.final_phase.worker_packet_sequence` | Y（可 null） | `run_phases` 最终有效 Worker packet 的 `phases[].sequence` | 同上 | RUNTIME_CHANGE | Y | — | 无有效 Worker packet 为 null；不得按 rollout 顺序推断 |
| `execution.root_synthesis` | Y（可 null） | 首条 `orc:` assistant 消息 | [codex-arch] §6.5 | DIRECT | Y | 计入 bundle_digest | 不存在时 null |
| `artifacts.unified_diff` | Y | `TurnDiffEvent.unified_diff` | [codex-arch] §8.3 | DIRECT | Y | 计入 bundle_digest | 内嵌；可为空串 |
| `artifacts.files[]` | Y（可为空） | 最终文件 snapshot + diff 解析 | [codex-arch] §9.1-1/2；`run_sampling_request` 尾部 `turn.rs:2518-2529`、tracker maps `turn_diff_tracker.rs:20-61` [runtime-capture] §2 | RUNTIME_CAPTURE | Y | 每文件 digest | 空数组 + gap 若未捕获 |
| `files[].path` | Y | diff 路径 / snapshot | [codex-arch] §9.1-7 | DIRECT | Y | — | 相对 workspace root |
| `files[].status` | Y | diff 解析（normalized） | [codex-arch] §10.2 | DIRECT | Y | — | added/modified/deleted/renamed |
| `files[].previous_path` | N | rename 旧路径 | NEW DESIGN | RUNTIME_CAPTURE | Y | — | 仅 renamed |
| `files[].digest` | 条件必填 | snapshot 文件 sha256 | [codex-arch] §9.1-2 | RUNTIME_CAPTURE | Y | sha256（文件） | deleted 为 null |
| `files[].content_ref` | 条件必填 | store `artifacts/files/<digest>` | [boundary] §5.1 | RUNTIME_CAPTURE | Y | 与 digest 同名 | deleted 为 null |
| `files[].media_type` | 条件必填（可 null） | Builder 推断 | ADAPTED Harbor `ImageSource.media_type` [harbor-arch] §6 | RUNTIME_CAPTURE | Y | — | 未知可为 null |
| `files[].size_bytes` | 条件必填（可 null） | snapshot stat | NEW DESIGN | RUNTIME_CAPTURE | Y | — | deleted 为 null |
| `files[].executable` | N（可 null） | mode executable 位 | NEW DESIGN（供 P1 entrypoint） | RUNTIME_CAPTURE | Y | — | 未引入 `mode` |
| `review.worker_status` | Y | packet 解析 | [codex-arch] §8.1 | DIRECT | Y | 计入 bundle_digest | — |
| `review.result_review_status` | Y | packet 解析 | [codex-arch] §5.2 | DIRECT | Y | 同上 | approved/revise/none |
| `review.correction_owner` | Y（可 null） | packet 解析 | [codex-arch] §5.2 | DIRECT | Y | 同上 | — |
| `review.interpretation` | Y | 常量 `model_review_only` | NEW DESIGN | DIRECT | Y | 同上 | approved ≠ Verification PASS |
| `verification_evidence.status` | Y | 默认 `"unknown"`；trace 开启后可为 `"complete"` | [codex-arch] §5；[spec] §6.4；[runtime-capture] §4（`CODEX_ROLLOUT_TRACE_ROOT`） | EVENT_CAPTURE | Y | — | 无 evidence 时 unknown + gaps |
| `verification_evidence.command` | Y（可 null） | `ExecCommandBegin/EndEvent.command` | [codex-arch] §9.1-4；`protocol.rs:3506,3532`；trace `thread.rs:237-248` [runtime-capture] §4 | EVENT_CAPTURE | Y | — | 禁止伪造 |
| `verification_evidence.exit_code` | Y（可 null） | `ExecCommandEndEvent.exit_code` | [codex-arch] §9.1-5；`protocol.rs:3552`；`exec_output.rs:41` [runtime-capture] §4 | EVENT_CAPTURE | Y | — | 禁止伪造 |
| `verification_evidence.stdout_ref` | Y（可 null） | `ExecCommandEndEvent.stdout` | [codex-arch] §9.1-6；`protocol.rs:3545` [runtime-capture] §4 | EVENT_CAPTURE | Y | sha256（若存在） | 禁止伪造 |
| `verification_evidence.stderr_ref` | Y（可 null） | `ExecCommandEndEvent.stderr` | [codex-arch] §9.1-6；`protocol.rs:3547` [runtime-capture] §4 | EVENT_CAPTURE | Y | sha256（若存在） | 禁止伪造 |
| `verification_evidence.checker_result` | Y（可 null） | 无（runtime 无 checker） | [codex-arch] §5 | OPEN_NULLABLE | Y | sha256（若存在） | 未来独立 checker |
| `verification_evidence.evidence_digest` | Y（可 null） | 有 evidence 时 Builder 计算 | [codex-arch] §5；[runtime-capture] §4 | EVENT_CAPTURE | Y | sha256（evidence 集合） | 禁止伪造 |
| `verification_evidence.evidence_refs` | Y（可 `[]`） | trace / rollout exec 事件 | [spec] §6.4；[runtime-capture] §4 | EVENT_CAPTURE | Y | 每项 sha256 | v0 默认 `[]`；开启 trace 后填充 |
| `verification_evidence.gaps` | Y | Builder 缺失清单 | NEW DESIGN | RUNTIME_CAPTURE | Y | — | unknown 时非空 |
| `verification_evidence.captured_at` | Y（可 null） | 捕获时刻 | NEW DESIGN | EVENT_CAPTURE | Y | — | 无 evidence 时 null |
| `environment.cwd` | Y | `TurnContextItem.cwd` | [codex-arch] §7.4 | DIRECT | Y | — | 元数据，非 live 依赖 |
| `environment.workspace_roots` | Y（可 null） | `TurnContextItem.workspace_roots?` | [codex-arch] §8.3 | DIRECT | Y | — | 缺失为 null |
| `environment.network` | Y（可 null） | `TurnContextNetworkItem` | [codex-arch] §8.3 | DIRECT | Y | — | 缺失为 null |
| `environment.permission_policy` | Y（可 null） | approval/sandbox/permission_profile | [codex-arch] §8.3 | DIRECT | Y | — | 缺失为 null |
| `environment.environment_snapshot_ref` | Y（可 null） | Builder 写 snapshot.json | [codex-arch] §10.3.4 | RUNTIME_CAPTURE | Y | sha256 | null + gap 若未实现 |
| `environment.dependency_manifest_ref` | Y（可 null） | 无 | [codex-arch] §9.1-9 | OPEN_NULLABLE | Y | sha256（若存在） | v0 null + gap |
| `replay_reference` | N（optional） | 无；v0 null | [codex-arch] §9.1-9；[swe-arch] §6 | OPEN_NULLABLE | Y | sha256（若存在） | Replay ≠ Reuse |
| `security.secrets_policy` | Y | 常量（禁止内嵌 secrets） | [codex-arch] §9.1-10；NEW DESIGN | DIRECT | Y | 计入 bundle_digest | — |
| `security.scan_status` | Y | v0 `not_scanned` | [codex-arch] §9.1-10；无通用 scanner（facts 脱敏 `orchestrated_execution_facts.rs:297-316`；`thread_resume_redaction.rs:6-39` 非通用）[runtime-capture] §7 | OPEN_NULLABLE | Y | — | scanned 需 scan_ref/digest；不虚构 scanner |
| `security.scan_ref` | N（可 null） | 未来扫描报告 | NEW DESIGN | OPEN_NULLABLE | Y | sha256（若存在） | v0 null |
| `security.scan_digest` | N（可 null） | 未来扫描报告 digest | NEW DESIGN | OPEN_NULLABLE | Y | sha256 | v0 null |
| `provenance.source_artifact_digest` | Y | digest-of-digests（§12.2） | NEW DESIGN | RUNTIME_CAPTURE | Y | sha256 | 只指 read-only 输入 |
| `provenance.source_rollout_digest` | Y | rollout 副本 sha256 | [codex-arch] §7.1 | RUNTIME_CAPTURE | Y | sha256 | — |
| `provenance.workspace_snapshot_digest` | Y | files snapshot manifest sha256 | [boundary] §5.1 | RUNTIME_CAPTURE | Y | sha256 | — |
| `provenance.bundle_digest` | Y | canonical bundle.json sha256 | NEW DESIGN | RUNTIME_CAPTURE | Y | sha256（自身） | seal 后固定 |
| `provenance.producer` | Y | 常量 `codex-artifact-builder-v0` | NEW DESIGN | DIRECT | Y | 计入 bundle_digest | ≠ identity.producer |
| `provenance.producer_commit` | Y（可 null） | Builder 实现 commit（P1） | NEW DESIGN | OPEN_NULLABLE | Y | — | P0 可为 null |
| `provenance.generated_at` | Y | seal 时刻 | NEW DESIGN | RUNTIME_CAPTURE | Y | 计入 bundle_digest | ≠ identity.generated_at |
| `provenance.gaps` | Y | Builder 缺失清单 | NEW DESIGN | RUNTIME_CAPTURE | Y | 计入 bundle_digest | 覆盖全部 OPEN_NULLABLE |

---

# 16. Codex Runtime Capture Points

| # | Capture Point | 捕获内容 | 源码锚点 | v0 状态 | Owner |
|---|---|---|---|---|---|
| 16.1 | turn 结束（Builder hook） | execution_id、`generated_at`、最终 workspace 状态、seal 时刻 + final phase accumulator（16.2） | `run_sampling_request` 尾部 `turn.rs:2518-2529`（root context：`orchestrated_role.is_none()`）[runtime-capture] §8-9 | RUNTIME_CAPTURE | Artifact Builder |
| 16.2 | `run_phases` 返回边界 | 最终 `Outcome`（→ `final_phase.outcome`）、最终有效 Worker packet 的 `phases[].sequence`（→ `final_phase.worker_packet_sequence`）、最终 WorkerExec `PhasePacket`、ResultReview 判定、retry/truncation/signature 状态（**唯一 final-phase authority**；rollout packet 顺序不能确定最终 effective packet） | `run_phases` return `orchestrated.rs:409`（被 `run_for_input` 调用 `orchestrated.rs:170-179`）[runtime-capture] §3 | RUNTIME_CHANGE（accumulator / 返回值）；v0 未 instrumented → `final_phase=null` + gap | Artifact Builder（runtime 侧） |
| 16.3 | turn 结束文件捕获 | 按最终 diff 路径做磁盘 snapshot + digest（deleted 除外）；内存全文 maps 当前不序列化 | `run_sampling_request` 尾部 `turn.rs:2518-2529`；`turn_diff_tracker.rs:20-61,309-366` [runtime-capture] §2 | RUNTIME_CAPTURE（磁盘快照无需 runtime change；内存 accessor 可选）→ 未实现时 `files[]=[]` + gap | Artifact Builder |
| 16.4 | 验证命令执行事件 | command、stdout、stderr、exit_code、duration → verification evidence 文件 + digest | `CODEX_ROLLOUT_TRACE_ROOT`（`rollout-trace/thread.rs:44`）→ 全阶段 `ExecCommandBegin/End`（`thread.rs:237-248`；`protocol_event.rs:260-274`）；root 阶段 rollout DIRECT（`session/mod.rs:1831,2006-2016`）；可选最小 runtime change `session/mod.rs:1831` [runtime-capture] §4 | EVENT_CAPTURE（trace opt-in）；无 trace 时 worker 阶段 OPEN → `status=unknown` + gaps | Artifact Builder / 未来 checker |
| 16.5 | seal 前 secrets 扫描 | packet 文本 + `unified_diff` 的 secrets policy 扫描 | facts 已脱敏（`orchestrated_execution_facts.rs:297-316`）；packet/diff 未脱敏；无通用 scanner（`thread_resume_redaction.rs:6-39` 非通用）[runtime-capture] §7 | v0 `scan_status=not_scanned` + gap `secrets_scan`；不虚构 scanner | Artifact Builder（策略） |
| 16.6 | turn 结束环境依赖捕获 | dependency manifest（当前不存在） | `TurnContextNetworkItem` 仅网络元数据 [codex-arch] §8.3 | v0 `dependency_manifest_ref=null` + gap | Artifact Builder（未来） |
| 16.7 | replay 引用捕获 | command sequence / environment reconstruction（当前不存在 replay config） | [swe-arch] §6 为 ADAPTED 参考 | v0 `replay_reference=null` + gap | Artifact Builder（未来） |
| 16.8 | task identity 捕获 | `source_task_id`（Codex 无 task 概念；wire `task_started/task_complete` 是 `TurnStarted/TurnComplete` 别名） | `protocol.rs:1322-1323,1333-1335`；[runtime-capture] §5 | v0 null + gap `task_id`；session/thread/turn = DIRECT | Runtime（未来） |

---

# 17. OPEN Questions

（P1-A 已关闭 1-4、7 的捕获事实，见 §19；5、6、8 维持 OPEN。）

1. **final file capture**：~~最终文件全文必须由 Builder 在 turn 结束捕获（16.3）还是由 Capabilityizer 从外部 snapshot 读取？~~ → **已关闭（§19）**：Builder 在 `run_sampling_request` 尾部（`turn.rs:2518-2529`）按最终 diff 路径磁盘快照；未 instrumented 时 `files[]=[]` + gap。[spec] §23.1
2. **verification evidence**：~~命令级证据是重跑验证命令还是捕获运行期输出？~~ → **已关闭（§19）**：捕获运行期事件（EVENT_CAPTURE，trace opt-in）；无 trace 时 `status=unknown` + `gaps`。[spec] §23.2
3. **final phase authority**：`run_phases` runtime 状态是唯一权威；Builder 需要 runtime 暴露 final status（16.2）。→ **已关闭（§19）**：Resolution = RUNTIME_CHANGE，capture point = `orchestrated.rs:409`；v0 无该 hook 时 `final_phase=null`，禁止 rollout 反推。[spec] §23.3
4. **secret scanning**：统一 secrets 策略（16.5）未实现；v0 只冻结 marker 与 gap，不声称扫描。→ **已关闭（§19）**：源码确认无通用 scanner；保持 `not_scanned + gap`，不虚构 scanner。
5. **replay**：Codex 无 replay config；v0 只保留 `replay_reference=null`。Harbor / SWE 的 replay 机制仅作 ADAPTED 参考。
6. **environment dependency manifest**：Codex 无依赖清单（16.6）；v0 `dependency_manifest_ref=null` + gap。
7. **source_task_id**：Codex 无独立 task id；v0 null + gap。→ **已关闭（§19）**：wire `task_started/task_complete` 为 turn 别名（`protocol.rs:1322-1335`），不是 task id；若未来 runtime 增加 task 概念，需重新定义与 thread/turn 的关系。
8. **files[].executable / media_type**：capture 语义已冻结；实际识别规则（extension / mode 位）留 P1 实现。

---

# 18. P0 Exit Assessment

| # | Exit Condition | 判定 | 依据 |
|---|---|---|---|
| 1 | Contract Frozen | **PASS** | §4-§14：root schema、identity、execution、artifacts、review、verification_evidence、environment、replay_reference、provenance、validation、storage layout 全部固定 |
| 2 | Producer Mapping Complete | **PASS** | §5-§12、§15：每个字段有 Source + Evidence（DIRECT / RUNTIME_CAPTURE / EVENT_CAPTURE / RUNTIME_CHANGE / OPEN_NULLABLE） |
| 3 | Required Field Resolution Complete | **PASS** | §15：全部 required 字段均明确属于 DIRECT / RUNTIME_CAPTURE / EVENT_CAPTURE / RUNTIME_CHANGE / OPEN_NULLABLE；verification_evidence 默认 `status=unknown / evidence_refs=[] / gaps=[...]`，trace 开启后可 `complete` |
| 4 | Validation Rules Frozen | **PASS** | §13：13 条确定性规则全部冻结；不可执行部分明确 OPEN，不猜测 |
| 5 | Capabilityizer has no live-workspace dependency | **PASS** | §3.3、§10、§13 Rule 12：Capabilityizer 只读 Bundle + 引用的 immutable artifacts + User Confirmation + LLM Proposal；禁止 live session / live Agent context / live workspace path / 当前 Codex process state |

## P0 = **PASS**

通过前提（必须保持）：

1. Bundle 是 Capabilityization 的 immutable input boundary。
2. `result-review: approved` ≠ Task Verification PASS ≠ Capability Evaluation PASS ≠ Promotion。
3. `verification_evidence.status=unknown` 是显式允许状态，不是实现缺陷。
4. `final_phase` 无 runtime authority 时必须为 null；不得从 rollout 猜最终状态。
5. Replay ≠ Reuse；Candidate / Promotion 永不进入 Bundle。
6. 所有 OPEN_NULLABLE 字段必须同步写入 `provenance.gaps`，禁止静默留空。

OPEN 项不阻塞 P0（契约冻结），但它们是 P1 的 runtime capture 实现清单（§16.2-16.8）。P1-A 已关闭 1-4、7 的捕获事实（§19）；本契约 v0 schema 未扩大。

---

# 19. P1-A Capture Closure

- 状态：**CLOSED**（P1-A Codex Runtime Capture Point Archaeology 已确认并回写）
- 输入：`research/codex-runtime-capture/codex-runtime-capture-archaeology.md`（`[runtime-capture]`；源码基线 `658630b2931ac841e2f1bc437daa1b931d173c0c`，本地 clone `<tmp>/yusing-codex`）
- 边界：Bundle v0 root structure **未扩大**（`final_phase` 新增 `outcome` / `worker_packet_sequence`，仍无新增 Domain Object）；P1/P2/P3/P4/P5 与 Capabilityizer scope **未修改**。

## Resolved（捕获事实已确认，Resolution 已回写）

1. **Final File Snapshot** → `RUNTIME_CAPTURE`
   - Capture point：`run_sampling_request` 尾部（`codex-rs/core/src/session/turn.rs:2518-2529`，root context：`turn_context.orchestrated_role.is_none()`），最终 `TurnDiff` emit 之后、tracker drop 之前，按最终 diff 路径从磁盘读文件做 sha256（deleted 除外）。
   - 内存全文 maps：`codex-rs/core/src/turn_diff_tracker.rs:20-61`（`baseline_by_path` / `current_by_path`；无公开 accessor，可选 runtime change）。
   - 落点：§7.3、§15、§16.3。

2. **Final Phase Authority** → `RUNTIME_CHANGE`
   - Capture point：`run_phases` 返回边界（`codex-rs/core/src/session/orchestrated.rs:409`；被 `run_for_input` 于 `orchestrated.rs:170-179` 调用）。
   - 捕获：最终 `Outcome`（→ `final_phase.outcome`）、最终有效 Worker packet 的 `phases[].sequence`（→ `final_phase.worker_packet_sequence`；无有效 packet 为 null）、最终 WorkerExec `PhasePacket`（text/truncated/execution_facts）、ResultReview 判定（approved/revise + owner）、retry 计数、retry signature break 状态。
   - **rollout packet 顺序不能确定最终 effective worker packet；必须依赖 runtime phase state。**（break 原因不持久化：retry signature `orchestrated.rs:412-425`、truncated 布尔、`Outcome::Stopped`；`compact_phase_history` 保留被 revise 的旧 packet `orchestrated.rs:617-655`，无 supersede 标记。）
   - 实现：`run_phases` / `run_for_input` 返回最终权威结构，或写 `TurnContext` accumulator 带到 Builder hook（§16.1）。
   - 落点：§6.1-6.3、§13 Rule 8、§15、§16.2。

3. **VerificationEvidence** → `EVENT_CAPTURE`
   - Source：`CODEX_ROLLOUT_TRACE_ROOT`（`codex-rs/rollout-trace/src/thread.rs:44`）→ `record_tool_call_event` 全阶段（含 worker）写入 `ExecCommandBegin/End`（`codex-rs/rollout-trace/src/thread.rs:237-248`）。
   - Payload：command / stdout / stderr / exit_code / duration（`codex-rs/rollout-trace/src/protocol_event.rs:147-258`；匹配 `:260-274`）——**可以作为 worker phase execution evidence**。
   - root 阶段：rollout 直接可读（`codex-rs/core/src/session/mod.rs:1831` persist 判定、`:2006-2016` 持久化）。
   - 无 trace：worker 阶段保持 OPEN → `status=unknown` + gaps，禁止伪造。
   - 落点：§9、§13 Rule 10、§15、§16.4。

4. **Task Identity** → `session_id` / `thread_id` / `turn_id` = `DIRECT`；`source_task_id` = `OPEN` / null
   - `session_id`：`SessionMeta.session_id`（`protocol.rs:3056`；`recorder.rs:179-181` 创建时 = thread_id）。
   - `thread_id`：`SessionMeta.id`（`protocol.rs:3057`）；rollout 文件名（`recorder.rs:1519`）。
   - `turn_id`：`TurnContext.sub_id`（`turn_context.rs:105,381`）；packet passthrough（`session/mod.rs:2817-2820`）。
   - **不要把 `turn_started` / `turn_complete` 当 task_id**：它们是 `TurnStarted` / `TurnComplete` 的 serde 别名（`protocol.rs:1322-1323,1333-1335`），是 turn 事件。
   - 落点：§5、§15、§16.8。

5. **Secrets** → 保持 `not_scanned + gap`
   - facts 已脱敏（`codex-rs/core/src/context/orchestrated_execution_facts.rs:297-316` `safe_path`）；packet / diff / stdout / stderr 未脱敏。
   - 仓库无通用 secrets scanner（`thread_resume_redaction.rs:6-39` 仅远程客户端 MCP/image 响应脱敏，非通用）→ **不虚构 scanner**；v0 `scan_status=not_scanned` + gap `secrets_scan`。
   - 落点：§13 Rule 11、§15、§16.5。

6. **Artifact Builder Hook** → `run_sampling_request` tail + final phase accumulator
   - Hook：`run_sampling_request` 尾部（`turn.rs:2518-2529`）唯一同时持有 final diff（tracker 未 drop）、root synthesis（`SamplingRequestResult.last_agent_message`）、identity、workspace state。
   - Final phase authority 在 `run_phases` 返回边界（`orchestrated.rs:409`），需经 accumulator 带到该 hook（唯一必须的 runtime change）。
   - 落点：§16.1、§16.2。

## Runtime Change（v0 未 instrumented 时保持 null/gap）

1. **Final phase authority（必须）**：让 `run_phases`（`orchestrated.rs:199`）在 `orchestrated.rs:409` 返回最终 `PhasePacket` + `Outcome` + 最终有效 Worker packet 的 `sequence` + ResultReview 判定 + retry/truncation/signature 状态，或写 `TurnContext` accumulator。未实现 → `final_phase=null` + gap（Rule 8）。
2. **Worker 阶段 exec 事件默认持久化（可选）**：`session/mod.rs:1831` 放行 `EventMsg::ExecCommandBegin/End`；当前已有 opt-in 等价通道 `CODEX_ROLLOUT_TRACE_ROOT`，属部署配置。
3. **内存 tracker accessor（可选）**：`turn_diff_tracker.rs:20-61` maps 私有；磁盘快照已覆盖 v0 需求，accessor 仅在需要内存精确全文时添加。

## P1 Implementation Notes

- **`bundle_digest` canonicalization（Builder）**：seal 时严格执行 §12.2 算法——canonical JSON、key 排序、紧凑表示、无尾随换行，计算时 `provenance.bundle_digest=null`，SHA-256 后写回真实 digest；验证时重复相同规范化流程（Rule 4）。
- **`worker_packet_sequence`（runtime capture）**：`run_phases` 返回边界（§16.2）同时提供最终有效 Worker packet 的 `phases[].sequence` 与最终 `Outcome`，经 accumulator 带到 Builder hook（§16.1）。

## Open（维持 OPEN，不阻塞 P0）

1. `source_task_id`：等待 runtime 引入 task 概念（OPEN/null + gap）。
2. Secrets scanner：无现成实现（OPEN；`not_scanned + gap`）。
3. Environment dependency manifest：无来源（OPEN；`dependency_manifest_ref=null` + gap）。
4. Replay config：无来源（OPEN；`replay_reference=null`）。
5. `checker_result`：runtime 无 checker（OPEN_NULLABLE；由未来独立 checker 提供）。
6. 多环境 display roots 持久化：diff display path 依赖未持久化的 roots（`turn.rs:493-509`）；capture 时需绑定。

## P0 阻塞状态

- **无 P0 阻塞项。** P0 仍为 **PASS**（§18 全部 Exit Condition 不变）。
- P1-A 关闭项不改 v0 schema / Domain Objects / P1-P5 / Capabilityizer scope。
- P1 依赖（非 P0 阻塞）：final phase authority 的 `RUNTIME_CHANGE`（§16.2）与 worker 验证证据的 trace 部署（§16.4）是 P1 实现清单中的前置项。
