# Artifact Boundary Comparison — VerifiedTaskArtifactBundle v0

> 输入范围：仅使用三个 research 文件（`research/codex-artifact/verified-task-artifact-archaeology.md`、`research/atif/harbor-atif-archaeology.md`、`research/swe-agent/swe-agent-trajectory-archaeology.md`）。未搜索新项目，未写 src，未修改 capability-forge-mvp-spec.md。
>
> 结论标记：
> - **DIRECTLY SUPPORTED**：该项目源码中存在该结构，语义直接对应。
> - **ADAPTED**：存在，但粒度/语义需要改造或边界不完整。
> - **OPEN**：不存在，或无法从持久化材料确定。
>
> 证据格式：`<仓库内路径>:<行号> <symbol>`；所有证据来自上述三个 research 文件的源码锚点，未新增外部证据。

## 0. 第一原则

**Trajectory、Artifact、Verification、Evaluation、Replay、Capability 是六个不同对象，禁止合并进同一个对象。**

本报告的所有边界判断以此为前提：Bundle 可以 *引用* 前五者，但不能 *成为* 其中任何一个；Candidate 是第六者，永远在 Bundle 之外。

---

## 1. Source-by-Source Comparison

### 1.1 Codex（yusing/codex @ `658630b`，issue #32100 PoC）

| Concern | 真实结构 | 标记 | 证据 |
| --- | --- | --- | --- |
| Execution Record root | 无 `WorkerResult`/`ExecutionRecord` 类型；持久化根是 rollout JSONL 的 `RolloutItem` 枚举；worker 阶段内存对象是私有 `PhasePacket` | ADAPTED | `codex-rs/protocol/src/protocol.rs:3171-3186 RolloutItem`；`codex-rs/core/src/session/orchestrated.rs:65-69 PhasePacket`；research §3.1（`rg "WorkerResult"` 零命中） |
| Step | 无 Step 类型；`Phase` 枚举 + 压缩后的 `ResponseItem::Message`（packet）是 phase 级步骤 | ADAPTED | `orchestrated.rs:48-54 Phase`；`models.rs:932-958 ResponseItem::Message` |
| Tool Call | 运行时存在 `exec_command` handler 与 ledger；role 阶段工具事件不持久化，无结构化 ToolCall 记录 | ADAPTED（运行时）/ OPEN（持久化） | `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs:197-229`；`session/mod.rs:1778-1832 send_event` |
| Observation | 只有失败类、有界、脱敏的 `<orchestrated_execution_facts>` 文本片段；无 stdout/stderr/成功命令 | ADAPTED | `codex-rs/core/src/context/orchestrated_execution_facts.rs:216-266 ContextualUserFragment`、`:233-235` |
| Workspace/File | `TurnContextItem.cwd/workspace_roots` 持久化；`TurnDiffTracker` 内存持有文件全文但从不序列化 | ADAPTED | `protocol.rs:3249-3293 TurnContextItem`；`turn_diff_tracker.rs:20-61 TrackedContent` |
| Diff/Patch | `TurnDiffEvent.unified_diff` 字符串（路径 + hunks + blob oid） | DIRECTLY SUPPORTED | `protocol.rs:3688-3691 TurnDiffEvent`；`turn.rs:2518-2526` |
| Verification | 无 Verification 结构；只有 worker/result-review packet 文本状态 + 模型审查判断 | OPEN | `worker.md:1,7`；`result_review.md:1`；`orchestrated.rs:435-483` |
| Evaluation | 无 evaluator/reward；Result Review 是模型文本判断，不是评估结果 | OPEN | `orchestrated.rs:449-455 review_approved`；research §5.2 |
| Replay Config | 无 replay config；resume 只保留 compact packets | OPEN | `codex-rs/core/tests/suite/multi_agent_mode.rs:1680-1787` |
| Identity | `SessionMetaLine.session_id`、`TurnContextItem.turn_id`、rollout 文件名含 conversation id | DIRECTLY SUPPORTED | `protocol.rs:3134-3168 SessionMetaLine`、`protocol.rs:3249-3253`；`rollout/recorder.rs:1500-1527` |
| Environment | cwd/workspace_roots/network/permission 元数据；无依赖清单/快照 | ADAPTED | `protocol.rs:3239-3293 TurnContextNetworkItem/TurnContextItem`；`world_state/environment.rs:246-281` |
| Retry/Attempt | `MAX_WORK_REVISIONS=2` + retry signature 防死循环；无持久化 attempt 索引 | ADAPTED | `orchestrated.rs:412-425 retry_signature/worker_retry_signature`、`:263-265`、`:379-383` |
| Persistence | `~/.codex/sessions/YYYY/MM/DD/rollout-{ts}-{thread_id}.jsonl`，`RolloutItem` JSONL；SQLite 只存线程元数据 | DIRECTLY SUPPORTED | `session/mod.rs:3137-3144 persist_rollout_response_items`；`live_writer.rs:115-133`；`read_thread.rs:30-70` |

### 1.2 Harbor ATIF（main @ `ac398bb`）

| Concern | 真实结构 | 标记 | 证据 |
| --- | --- | --- | --- |
| Execution Record root | `Trajectory` Pydantic 模型，一个 JSON 文档，通常为 `<trial>/agent/trajectory.json` | DIRECTLY SUPPORTED | `src/harbor/models/trajectories/trajectory.py:12-106 Trajectory` |
| Step | `Step` 模型：`step_id`（1 起连续）、source、message、tool_calls、observation、metrics | DIRECTLY SUPPORTED | `step.py:14-91 Step`；`trajectory.py:119-129` |
| Tool Call | `ToolCall{tool_call_id, function_name, arguments, extra}` | DIRECTLY SUPPORTED | `src/harbor/models/trajectories/tool_call.py:8-31 ToolCall` |
| Observation | `ObservationResult{source_call_id, content, subagent_trajectory_ref, extra}`；无 stdout/stderr/exit status 字段 | DIRECTLY SUPPORTED（schema）/ ADAPTED（反馈保真度） | `observation_result.py:11-42 ObservationResult`；research §5 |
| Workspace/File | 非图片文件在 ATIF 外：`<trial>/artifacts/` + `manifest.json`；图片经 `ImageSource.path` 引用，不内嵌 | ADAPTED | `src/harbor/models/trial/paths.py:195-226`；`content.py:11-25 ImageSource` |
| Diff/Patch | 无 diff 字段；patch 只能进 `content`/`extra` | OPEN | `observation_result.py:23-29`；research §5 |
| Verification | 不在 trajectory 内；verifier 结果在 `<trial>/result.json` / `verifier/` 日志 | ADAPTED（存在但分离） | `src/harbor/models/verifier/result.py:4-7 VerifierResult.rewards`；`trial/result.py:61-97` |
| Evaluation | `VerifierResult.rewards` 写入 `<trial>/result.json`，与 trajectory 分离 | DIRECTLY SUPPORTED | `trial/trial.py:419`；`models/trial/paths.py:267-270` |
| Replay Config | `agent.load_trajectory`（run 级配置）；ATIF replay = 会话种子转换，非位级环境重放 | ADAPTED | `src/harbor/models/trial/config.py:110`；`agents/installed/base.py:1044-1075` |
| Identity | `session_id`（run 级，可共享）vs `trajectory_id`（文档级，子代理必填）；`step_id` 文档内连续 | DIRECTLY SUPPORTED（schema）/ OPEN（`trajectory_id` 无生产者使用） | `trajectory.py:28-60`、`:131-161`；research §7 |
| Environment | ATIF 无环境快照/环境 schema；只有 `Agent{name, version, model_name, tool_definitions}` | OPEN | `src/harbor/models/trajectories/agent.py:8-32 Agent` |
| Retry/Attempt | 无 attempt/retry 模型；只有 `continued_trajectory_ref` 续链 + `-cont-N` 文件 | ADAPTED | `trajectory.py:78-81`；`terminus_2.py:1875-1878` |
| Persistence | 每 episode 写 `trajectory.json`（或 `trajectory.cont-N.json`），`extra: forbid` 严格校验 | DIRECTLY SUPPORTED | `terminus_2.py:1889-1959 _dump_trajectory`；`utils/trajectory_validator.py:106-202` |

### 1.3 SWE-agent（v1.1.0 @ `3ea751c`）

| Concern | 真实结构 | 标记 | 证据 |
| --- | --- | --- | --- |
| Execution Record root | `.traj` 单文件：顶层 `environment / trajectory / history / info / replay_config`；运行时返回 `AgentRunResult{info, trajectory}` | DIRECTLY SUPPORTED | `sweagent/agent/agents.py:762-777 get_trajectory_data`；`sweagent/types.py:100-102 AgentRunResult` |
| Step | `TrajectoryStep` TypedDict，8 字段：action/observation/response/state/thought/execution_time/query/extra_info | DIRECTLY SUPPORTED | `sweagent/types.py:44-58 TrajectoryStep`；`agents.py:1220-1231 add_step_to_trajectory` |
| Tool Call | step 级无 tool_calls；`action` 字符串在 step，`tool_calls/thinking_blocks` 只在 `HistoryItem` | ADAPTED | `types.py:44-79`；`agents.py:714-746 add_step_to_history` |
| Observation | `TrajectoryStep.observation`（字符串）+ `state`（open_file/working_dir/diff）；`exit_status` 只在全局 `info` | DIRECTLY SUPPORTED | `types.py:44-58`；`agents.py:1255-1258` |
| Workspace/File | `.traj` 不存文件内容；repo 由环境重建；patch 单独落盘 | ADAPTED | `sweagent/environment/swe_env.py:21-43 EnvironmentConfig`；`run/hooks/apply_patch.py:76-90 _save_patch` |
| Diff/Patch | `info.submission`（`/root/model.patch` 内容）冗余落 `.pred` / `.patch` / `preds.json` | DIRECTLY SUPPORTED | `run/common.py:370-380 save_predictions`；`run/merge_predictions.py:13-46` |
| Verification | 无结构化 verification；验证命令只是普通 action + observation | OPEN | `types.py:44-58`；research §8 |
| Evaluation | 只消费 `preds.json` → `sb-cli` → `results.json`；不读 `.traj` | DIRECTLY SUPPORTED | `run/hooks/swe_bench_evaluate.py:43-123` |
| Replay Config | `replay_config` = 完整 `RunSingleConfig` 序列化进 `.traj`；replay 是全新环境重执行动作 | DIRECTLY SUPPORTED | `agents.py:775`；`run/run_replay.py:96-120,138-162,173-180`；`agent/models.py:464-525 ReplayModel.query` |
| Identity | `instance_id` 由 problem statement 派生（Github 或 sha256 前 6 位）；无独立文档 id；`info` 有 hash/version | ADAPTED | `environment/problem_statement.py:86,119,147`；`types.py:82-98 AgentInfo` |
| Environment | `.traj` 只存 `environment: <name>`；完整规格在 `replay_config.env`（deployment/repo/base_commit） | ADAPTED | `agents.py:776`；`swe_env.py:21-43`；`environment/repo.py:21-38` |
| Retry/Attempt | `RetryAgent`：`attempts` 数组 + `best_attempt_idx` + `attempt_<i>` 子目录 + 环境 hard reset | DIRECTLY SUPPORTED | `agents.py:315-381`、`:390-441`；`swe_env.py:128-133 hard_reset` |
| Persistence | 每步全量覆写 `.traj`（非原子）；config/logs/pred 独立文件 | DIRECTLY SUPPORTED（含缺陷） | `agents.py:779-787 save_trajectory`；`run_single.py:188-208` |

---

## 2. Artifact Boundary Matrix

前三列是事实；Forge 列只给 v0 边界指针，设计依据见 §5。

| Concern | Codex | Harbor | SWE-agent | Forge v0 |
| --- | --- | --- | --- | --- |
| trajectory | rollout JSONL `RolloutItem`；压缩 packet 文本，无结构化 step/tool | ATIF `Trajectory`：step/tool/observation 全结构化 | `.traj`：trajectory + history + info 并存 | `execution` 节：packet 级提取 + 引用，不复制完整 history（§5） |
| tool execution | role 阶段事件不持久化；仅失败 facts | `ToolCall` + `source_call_id` 同 step 校验 | `action` 字符串 + history 内 tool_calls | 不进入 v0 Bundle；如需由 rollout 引用（OPEN） |
| observation | 失败类 facts 片段；无 stdout/stderr | `ObservationResult.content` 不透明字符串；无 exit status | `observation` + `state`；exit_status 在 info | 脱敏 facts 可进；原始 stdout/stderr 不进（runtime-only，§5） |
| files | 不持久化全文；`TurnContextItem` 有 roots | `artifacts/` + manifest；图片 path 引用 | 环境内 repo；无文件引用 | path + digest 引用；全文不进 Bundle（§5） |
| diff | `TurnDiffEvent.unified_diff` | 无 diff 字段 | `info.submission` + `.patch`/`.pred` | unified_diff 内嵌（§5） |
| output | root synthesis `orc:` 文本 | 最后 agent step message（隐式约定） | `response` + `.pred` | root synthesis 进 `execution`；评估输出不进（§6） |
| verification | 仅 packet 文本声明 + review 文本判断 | verifier 日志/result.json，与 trajectory 分离 | 无结构化验证；评估外部化 | review 状态内嵌；命令级证据仅引用（§5） |
| evaluation | 无 | `result.json` rewards | `results.json` | 不进 Bundle（§6） |
| replay | 无 replay config | `load_trajectory` 会话种子 | `replay_config` 重执行 | 引用形式；Codex 侧 OPEN（§5） |
| environment | cwd/roots/network/policy 元数据 | 无环境 schema | `replay_config.env` 可重建规格 | 元数据内嵌 + snapshot 引用；依赖清单 OPEN（§5） |
| provenance | session/turn id + rollout 文件名 | session_id + trajectory_id | instance_id + info hash/version | `provenance` 必填：producer/digests/gaps（§5） |

---

## 3. Common Abstractions

只识别三个项目都存在的抽象。结论：**6 个共同、3 个不共同**。

| 抽象 | Codex | Harbor | SWE-agent | 判定 |
| --- | --- | --- | --- | --- |
| Execution | rollout `RolloutItem` / `PhasePacket` | `Trajectory` | `.traj` / `AgentRunResult` | 共同（root 语义不同：流、文档、文件） |
| Step | `Phase` + packet（phase 级） | `Step` + `step_id`（消息级） | `TrajectoryStep`（动作级） | 共同（粒度不同） |
| Tool | 运行时 `exec_command`，无持久化 ToolCall | `ToolCall` 结构化 | `action` + history `tool_calls` | 概念共同；结构化记录仅 Harbor 有 → Forge 需自建 |
| Observation | 失败 facts 文本片段 | `ObservationResult` | `observation` + `state` | 共同（保真度差异大） |
| Artifact | unified diff | `artifacts/` + manifest | patch / pred | 共同（形态不同） |
| Environment | TurnContext 元数据 | 无（仅 Agent 配置） | `replay_config.env` | **不共同**：Harbor 缺失 |
| Identity | session_id / turn_id | session_id / trajectory_id / step_id | instance_id | 共同（语义不统一） |
| Evaluation | 无（Result Review 是文本判断） | `result.json` rewards | `results.json` | **不共同**：Codex 缺失 |
| Replay | 无 | 会话种子（load_trajectory） | 重执行（replay_config） | **不共同**：Codex 缺失 |

结论：Environment、Evaluation、Replay 不能被当作三项目共有的既有抽象直接复用；Forge 必须自己定义，且只能以 Harbor/SWE 为 ADAPTED 参考。

---

## 4. Capability Forge-Specific Requirements

| 需求 | Harbor 现状 | SWE-agent 现状 | Forge 必须额外拥有 | 证据 |
| --- | --- | --- | --- | --- |
| reusable behavior | 无；ATIF 是 transcript，任务/verifier/capability 都在 trajectory 外 | 无；`.traj` 是一次 run 的记录 | `Candidate` 抽象：entrypoint + contract + implementation + params | Harbor research §13.9「Trajectory ≠ capability artifact」；SWE research §10 |
| entrypoint | 无显式入口；final answer 是「最后一条 agent step」隐式约定 | 无显式入口；replay 从 history 顺序取动作 | 显式 entrypoint 字段 + 提取规则 | Harbor `harbor-atif2otel/convert.py:121-125`；SWE `run_replay.py:138-162` |
| contract | 无任务契约；`extra: forbid` 只是格式契约 | 无任务契约 | 机器可检查的 contract（输入/输出/前置条件） | ATIF `trajectory.py:106`；SWE 无对应 symbol |
| implementation artifact | `artifacts/` 存文件，无「哪个文件是实现」语义 | patch 是最终变更，无入口映射 | 实现文件引用 + digest + 入口映射 | Harbor `paths.py:195-226`；SWE `info.submission`（`types.py:82-98`） |
| provenance | session/trajectory id 标识 transcript | instance_id + hash/version | 从 Bundle → Candidate 的完整溯源链（source bundle id → candidate id） | Harbor `trajectory.py:28-60`；SWE `types.py:82-98 AgentInfo` |
| validation evidence | verifier 结果在 result.json，与 candidate 无绑定 | sb-cli 结果在 results.json，与 candidate 无绑定 | evidence 与 candidate 可关联（独立存储但绑定引用） | Harbor `trial/result.py:61-97`；SWE `swe_bench_evaluate.py:94-105` |
| capability evaluation | 只评估任务结果 | 只评估 patch 是否正确 | 评估 candidate 在未见过任务上的可复用性 | 三项目均无 → **OPEN** |
| promotion eligibility | 无 | 无 | 门槛定义（验证通过 + 评估达标） | 三项目均无 → **OPEN** |
| capability identity | 无 | 无 | `capability_id` + version | 三项目均无 → **OPEN** |

---

## 5. VerifiedTaskArtifactBundle v0

只定义 Bundle 边界，不定义最终 Capability Manifest。

### 5.1 结构

```text
VerifiedTaskArtifactBundle（密封、v0）
├── identity        # bundle/session/thread/turn/runtime/commit —— immutable
├── execution       # phase packets + 状态 + root synthesis —— immutable，引用 rollout
├── artifacts       # unified_diff 内嵌；文件 path+digest 引用 —— immutable
├── verification    # review 状态 + verification evidence 引用 —— immutable after capture
├── environment     # cwd/workspace_roots/network/policy 元数据 + snapshot 引用 —— immutable
├── replay          # rollout/命令序列/环境重建引用 —— immutable；Codex 侧 OPEN
└── provenance      # producer/generated_at/输入 refs/digests/gaps —— immutable
```

### 5.2 字段边界

| 字段 | 必填 | immutable | path/reference | digest | Codex 现状 |
| --- | --- | --- | --- | --- | --- |
| `schema_version` + `bundle_id` | 是 | 是 | 内嵌 | bundle 自身 hash | 无（新结构） |
| `identity`（session/thread/turn/runtime/commit/rollout_path） | 是 | 是 | rollout_path 为引用 | rollout digest | DIRECT（session_meta/turn_context/文件名） |
| `execution`（packets + statuses + root synthesis） | 是 | 是 | 内嵌 + rollout 引用 | rollout digest | DIRECT（文本可推导） |
| `artifacts.unified_diff` | 是 | 是 | 内嵌 | 可选 | DIRECT（`TurnDiffEvent`） |
| `artifacts.files[]`（changed files 引用） | 是 | 是 | path 引用 | **必填** | OPEN（全文不持久化，Builder 捕获） |
| `verification.review_status`（worker/result-review） | 是 | 是 | 内嵌 | — | DIRECT（文本状态） |
| `verification.evidence[]`（命令级证据引用） | 有条件必填 | 是 | path 引用 | **必填** | OPEN（当前只有模型文本判断） |
| `environment`（cwd/roots/network/policy/snapshot ref） | 是 | 是 | snapshot 为引用 | snapshot digest | ADAPTED（元数据有，依赖清单无） |
| `replay`（引用） | 是（引用形式） | 是 | path/命令序列引用 | 必填 | OPEN（无 replay config） |
| `provenance`（producer/generated_at/gaps） | 是 | 是 | 内嵌 | bundle digest | DIRECT |

### 5.3 哪些数据不能进入 Bundle

| 数据 | 原因 | 证据 |
| --- | --- | --- |
| 完整 history / 全部工具调用文本 | 私有状态 + 噪声；三项目都把 process 与 transcript 分离 | Codex role 事件不持久化（`session/mod.rs:1778-1832`）；SWE history 与 trajectory 分离（`agents.py:481-483`） |
| secrets / API keys / tokens | 泄露风险；facts 已脱敏但 packet/diff 是自由文本 | `orchestrated_execution_facts.rs:297-316 safe_path`；research §9.1-10 |
| workspace 全文 | 体积 + 私有状态；Codex 明确不序列化 | `turn_diff_tracker.rs:20-61`；`environment_context.rs:11-72` |
| 全量 stdout/stderr | 有界原则；Codex 故意丢弃 | `orchestrated_execution_facts.rs:233-235` |
| evaluation result | 可变、属于下游输出 | Harbor result.json 分离（`trial/result.py:61-97`）；SWE results.json 分离（`swe_bench_evaluate.py:94-105`） |
| promotion 状态 | 可变、不属于输入 | 三项目均无此抽象 |
| Capability Manifest / Candidate | 输出不是输入 | §6 |

### 5.4 哪些字段只能 runtime 提供

| 数据 | 为什么 | Codex 现状 |
| --- | --- | --- |
| 最终文件全文 | diff 无法反推全文 | `TurnDiffTracker` 内存有、不序列化（`turn_diff_tracker.rs:20-61,309-366`） |
| 最终 phase 状态 | `run_phases` 状态机是唯一权威（重试/截断/supersede） | 内存状态（`orchestrated.rs:224-267,346-403`） |
| 成功命令 exit code / stdout/stderr | role 阶段事件不持久化 | 无（`session/mod.rs:1831`；`exec_command.rs:432-441`） |
| environment dependency manifest | 无依赖清单 | 无（仅 `TurnContextNetworkItem`） |
| replay 命令序列 / 环境重建信息 | 无 replay config | 无 |

**结论：v0 Bundle 不是「从 rollout 被动导出」，而是 Artifact Builder 在 turn 结束时主动捕获 runtime-only 数据后组装。**

---

## 6. Artifact vs Transcript

六个对象必须分离：

| 对象 | 定义 | 落点证据 |
| --- | --- | --- |
| Trajectory / Transcript | 一次执行的顺序记录（messages/steps/actions/observations） | Codex rollout packets；Harbor `Trajectory`；SWE `.traj` |
| ArtifactSet | 执行产生的文件/变更（diff、patch、artifacts） | Codex `unified_diff`；Harbor `artifacts/`；SWE `.patch`/`.pred` |
| VerificationEvidence | 命令级、可复验的证明（命令 + 输出 + 退出码） | Codex **OPEN**；Harbor verifier logs；SWE observation/results（间接） |
| EvaluationResult | 奖励/分数/判定 | Codex **OPEN**；Harbor `result.json`；SWE `results.json` |
| ReplayConfig | 可重建执行的环境 + 动作输入 | Codex **OPEN**；Harbor `load_trajectory`；SWE `replay_config` |
| CapabilityCandidate | 可复用的 entrypoint + contract + implementation + params | 三项目均 **OPEN** |

关系图：

```text
Codex Runtime（一次 turn）
  │  packets / facts / turn_diff / session_meta（rollout）
  ▼
Artifact Builder ── 捕获 runtime-only：最终文件、最终 phase 状态、验证输出、replay 引用
  ▼
VerifiedTaskArtifactBundle   ← 密封：identity/execution/artifacts/verification/environment/replay/provenance
  │                           （引用 ArtifactSet 与 VerificationEvidence，但不等于它们）
  ▼
Capabilityizer（Bundle + workspace snapshot）
  ▼
CapabilityCandidate           ← 不在 Bundle 内
  ├─ Validator ── 产出 validation evidence（Bundle 外）
  └─ Evaluator ── 产出 evaluation result（Bundle 外）
  ▼
Promotion（Bundle 外）
```

不变量：

1. Bundle 只能包含不可变的事实；`review_status` 是事实，`approved 即验证通过` 是推断，后者进 Validator。
2. EvaluationResult 永远不写回 Bundle；Bundle 被 Evaluator 消费，不被 Evaluator 修改。
3. CapabilityCandidate 由 Capabilityizer 产出，Bundle 不包含 Candidate。

---

## 7. Capabilityizer Input Boundary

| # | 任务 | 输入判定 | 说明 / 证据 |
| --- | --- | --- | --- |
| 1 | identify reusable behavior | **Bundle 足够**（单任务候选）；跨任务可复用性 = Bundle×N + evaluation，**当前无法证明** | packet + diff + review 状态足以识别「这次做了什么」；可复用性没有现成评估数据（§4） |
| 2 | entrypoint extraction | **Bundle + workspace snapshot** | diff 有路径但无最终文件全文，无法确定入口符号；`turn_diff_tracker.rs:20-61,309-366` |
| 3 | parameterization | **Bundle + workspace snapshot + user input + LLM inference** | 哪些值是可参数化输入需要对照原 prompt 与实现推断，参数边界需用户确认 |
| 4 | private-state removal | **Bundle + runtime metadata + secrets policy** | Bundle 有 cwd/network/policy 与脱敏 facts，但 packet/diff 未脱敏（`orchestrated_execution_facts.rs:297-316`；research §9.1-10） |
| 5 | contract extraction | **Bundle + workspace snapshot + verification evidence**；Codex 当前**无法证明** | 契约必须可验证；当前只有模型 review 文本（§5.2），无命令级证据 |
| 6 | test generation | **Bundle + workspace snapshot + runtime metadata + verification evidence**；Codex 当前**无法证明** | 需要入口、环境重建、验证命令；SWE `replay_config` 是 ADAPTED 参考，Codex 无 |

---

## 8. Minimal MVP Boundary

### 8.1 职责分配

| 职责 | 负责方 | 边界 |
| --- | --- | --- |
| 从 rollout 解析 packets/facts/diff/identity；捕获 runtime-only 数据；计算 digest；原子写 Bundle | Artifact Builder | 不改 runtime，不改 rollout 格式 |
| 识别行为、提取 entrypoint、参数化、去私有状态、提取契约、生成测试 | Capabilityizer | 只读 Bundle + workspace snapshot，不接 live session |
| 校验 entrypoint/contract 与实现一致；重跑验证命令 | Validator | 产出 validation evidence，写回 Bundle 外 |
| 在 held-out 任务上评估 candidate | Evaluator | 产出 evaluation result，Bundle 外 |
| 决定 promotion | Promotion gate | 不进入 v0 范围 |

### 8.2 什么必须进入 Bundle

identity、execution（packets + 状态 + root synthesis）、artifacts（unified_diff + changed files 引用 + digest）、verification（review 状态 + evidence 引用）、environment 元数据、replay 引用、provenance。

### 8.3 什么明确不进入

完整 history、secrets、workspace 全文、全量 stdout/stderr、evaluation result、promotion 状态、Capability Manifest / Candidate。

不扩展到 Marketplace / K8s / Temporal / distributed registry。

---

## Recommended Architecture

```text
Codex Runtime
   │  rollout JSONL（packets/facts/turn_diff/session_meta）
   ▼
Artifact Builder
   │  捕获 runtime-only（最终文件、最终 phase 状态、验证输出、replay 引用）
   │  计算 digest → 原子写 Bundle
   ▼
VerifiedTaskArtifactBundle   ← 密封、immutable、七个 section
   │
   ▼
Capabilityizer               ← 只读 Bundle + workspace snapshot
   │
   ▼
Candidate                    ← entrypoint / contract / params / tests
   │
   ▼
Validator                    ← 校验 + 重跑验证，产出 validation evidence（Bundle 外）
   │
   ▼
Evaluator                    ← held-out 评估，产出 evaluation result（Bundle 外）
   │
   ▼
Promotion
```

---

## Top 5 Design Decisions

1. **v0 不新增 Codex 运行时类型**：Artifact Builder 从 rollout + runtime 捕获组装 Bundle；PoC 无 `WorkerResult`/serde 类型，改 runtime 是 P1 之后的事（evidence：`orchestrated.rs:65-69 PhasePacket`；research §10.3）。
2. **Bundle 是密封边界对象**：identity/execution/artifacts/verification/environment/replay/provenance 全部 immutable；evaluation 与 promotion 永不进 Bundle（evidence：Harbor result.json 分离 `trial/result.py:61-97`；SWE preds.json 分离 `common.py:370-380`）。
3. **Verification ≠ Review**：`result-review: approved` 是模型文本判断，Bundle 只把它记录为 claim；命令级证据单独引用，由 Validator 验证（evidence：`orchestrated.rs:449-455`；Harbor verifier logs；SWE `results.json`）。
4. **引用优于嵌入**：diff 内嵌，文件全文/rollout/history 用 path + digest；避免 ATIF 大 content（`observation_result.py:23-29`）与 SWE 非原子写（`agents.py:779-787`）的已知缺陷。
5. **Capabilityizer 的输入是 Bundle + workspace snapshot，不是 live session**：Bundle 必须携带身份、diff、review 状态、环境元数据与 runtime 引用，使 Capabilityizer 脱离原 Task/Session/Workspace 私有状态；Bundle 缺的 runtime-only 数据由 Builder 在 turn 结束时补齐（evidence：Codex `turn_diff_tracker.rs:20-61`；research §10.3）。

---

## Open Questions Before P1

1. **最终文件全文从哪里来**：Artifact Builder 运行期捕获 vs Capabilityizer 时读 workspace snapshot？Codex 当前只持久化 diff（`turn_diff_tracker.rs:20-61,309-366`）。
2. **verification evidence 的 v0 定义**：重跑 verification 命令 vs 捕获命令输出？Codex 当前只有模型文本声明（`worker.md:1,7`；`result_review.md:1`）。
3. **权威最终 phase 状态由谁写入**：`run_phases` 状态机（重试/supersede）是唯一权威；Builder 需要 runtime 暴露 final status，否则多 worker packet 时无法判定哪个是最终有效 packet（`orchestrated.rs:224-267,346-403`）。
4. **统一脱敏策略**：facts 已脱敏，packet/diff 未脱敏（`orchestrated_execution_facts.rs:297-316`）；Bundle 写入前是否需要统一 secrets 扫描。
5. **可复用性证据门槛**：单 turn Bundle 只能出 Candidate；跨任务可复用需要 N 个 Bundle + evaluation；P1 是否只做 candidate extraction、不做 promotion。
6. **Codex 侧 replay 形态**：SWE 有 `replay_config`、Harbor 有 `load_trajectory`、Codex 无；P1 的 replay 是否降级为「rollout 引用 + 最终文件引用」。
