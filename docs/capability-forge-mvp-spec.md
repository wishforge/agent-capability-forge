# Agent Capability Forge — MVP Specification

状态：Draft v0.3（本轮只产设计文档，不写 `src`）
日期：2026-08-14
仓库：`<home>/big-wish`

## 证据基础

v0.3 只使用已完成的三轮 code archaeology 与一份边界对比，不引入新项目、不搜索新资料：

- `research/codex-artifact/verified-task-artifact-archaeology.md`：Codex（yusing/codex @ `658630b`）rollout JSONL / PhasePacket / execution facts / TurnDiff / 持久化边界
- `research/atif/harbor-atif-archaeology.md`：Harbor ATIF（main @ `ac398bb`）Trajectory / ToolCall / artifacts / result.json / load_trajectory
- `research/swe-agent/swe-agent-trajectory-archaeology.md`：SWE-agent（v1.1.0 @ `3ea751c`）`.traj` / history / info / replay_config / preds.json / results.json
- `research/artifact-boundary-comparison.md`：三项目 Artifact Boundary 对比与 VerifiedTaskArtifactBundle v0 建议

v0.2 中 DeepSeek Harness 的 Dynamic Cordis Plugin 证据在本版不再作为设计来源：v0.3 的证据宇宙收窄为上述四个文件，原 DeepSeek 相关 `[ADAPTED]` 引用改为 `[NEW DESIGN]` 或改为 Harbor / SWE-agent 支持的 `[ADAPTED]`。

证据标签：

- `[DIRECTLY SUPPORTED]`：直接来自上述 research / source evidence
- `[ADAPTED]`：从源码机制改编
- `[NEW DESIGN]`：本 MVP 自己的设计
- `[OPEN QUESTION]`：当前证据不足

---

## 1. Problem

`[DIRECTLY SUPPORTED]` Codex 的 Worker Result 实际是内存私有结构 `PhasePacket`（text + truncated + execution_facts），不实现 serde；机器可读的持久化材料只有 rollout JSONL 中的 phase packet 文本、`<orchestrated_execution_facts>` 片段、`unified_diff` 与 session/turn 身份元数据。`result-review: approved` 只是模型对 worker packet 文本的审查判断，不是命令级 verification PASS（verified-task-artifact-archaeology.md §3、§5、§7）。

`[DIRECTLY SUPPORTED]` Harbor ATIF 是结构化 Trajectory，但 Trajectory ≠ Capability Artifact：文件在 `artifacts/`、评估在 `result.json`、replay 只是会话种子（harbor-atif-archaeology.md §13.9、§1）。

`[DIRECTLY SUPPORTED]` SWE-agent `.traj` 自带 `replay_config`，但 evaluation 只消费 `preds.json`，不读 `.traj`；replay 是全新环境重新执行，不是能力复用（swe-agent-trajectory-archaeology.md §6、§8）。

缺口：从“一次性执行证据”到“可验证、可注册、可发现、可独立调用、可复用、可撤销的正式 Capability”之间没有通路。根因之一是 v0.2 把 Execution Evidence、Artifact、Review、Verification、Evaluation、Replay、Candidate 的边界混在一起。v0.3 用三个新边界补这条通路：

- `Artifact Builder`：从 Codex rollout + runtime-only 数据捕获执行证据；
- `VerifiedTaskArtifactBundle`：密封、immutable 的 Capabilityization 输入；
- `CapabilityCandidate`：Capabilityization 的输出，永远不在 Bundle 内。

`[NEW DESIGN]` 把 Bundle（或任何执行产物）直接复制成 Candidate 不是 Capabilityization——候选必须经过识别可复用行为、提取 entrypoint、参数化、剥离任务私有状态、提取契约、生成测试的变换，否则只是原 workspace 的快照，不是可独立复用的能力。

---

## 2. Product Hypothesis

唯一假设：

> 一个已经完成并通过审查/验证的执行，被 Artifact Builder 捕获为 immutable VerifiedTaskArtifactBundle 后，可以被 Capability Forge 转换成一个可验证、可注册、可发现、可独立调用、可复用、可撤销的正式 Capability。

MVP 用 S0-S4 五个验收条件证明该假设；不做统计意义上的泛化声明；不做自动 Capability Gap Detection。`[NEW DESIGN]`

---

## 3. Goals

- G1：Artifact Builder 从 Codex rollout JSONL 解析 packets / facts / identity，获取 TurnDiff，在 turn 结束时捕获 runtime-only 数据与最终 workspace snapshot / file references（捕获后作为 Bundle 引用的 immutable artifact），计算 digest 并原子写 VerifiedTaskArtifactBundle。`[NEW DESIGN]`
- G2：`/forge`（Capabilityizer）以 Bundle + immutable Workspace Snapshot / Artifact References + User Confirmation + LLM Proposal 为输入，产出 CapabilityCandidate（识别可复用行为 → 提取 entrypoint → 参数化 → 去除任务私有状态 → 提取契约 → 生成测试）。`[NEW DESIGN]`
- G3：Candidate 能脱离原 Task / 原 Session / 原 Agent Context / 原 Workspace private state 独立验证（S0 + S1）。`[NEW DESIGN]`
- G4：Promoted Capability 持久化，能被未来 Task 发现并独立调用（S2 + S3）。`[NEW DESIGN]`
- G5：Revoked Capability 无法再次调用（S4）。`[NEW DESIGN]`
- G6：严格区分 Review、VerificationEvidence、Capability Evaluation（`result-review: approved` ≠ Task Verification PASS ≠ Capability Evaluation PASS ≠ Promotion）。`[DIRECTLY SUPPORTED]`

---

## 4. Non-Goals

`[NEW DESIGN]` MVP 明确排除：

- 自动 Capability Gap Detection
- Capability Marketplace
- Multi-Agent Capability Sharing
- Distributed Registry
- Kubernetes Operator / Temporal
- Multi-instance Scheduling
- Capability Self-Evolution
- Capability Composition
- MCP Capability Generation
- 自动 Promotion
- 复杂 Human Approval UI
- 版本更新 / 升级 / rollback API（MVP 每 Capability 只有一个版本）
- Replay 执行引擎（MVP 只保留 `replay_reference`，不实现 replay）
- 大规模评测平台
- 本轮不写 `src`、不实现 API / DB / Sandbox / production code

---

## 5. User Stories

1. 用户完成了一个任务（如“读取 CSV，清洗数据，生成统计报告”），Artifact Builder 在 turn 结束时自动捕获 VerifiedTaskArtifactBundle；用户输入 `/forge`，Bundle 被 Capabilityizer 转成以后可复用的能力。`[NEW DESIGN]`
2. 用户希望 Candidate 在脱离原任务的情况下被独立验证，再决定是否信任。`[NEW DESIGN]`
3. 用户在新任务中按名字发现并调用已 Promote 的能力，得到正确结果。`[NEW DESIGN]`
4. 用户撤销一个能力后，再次发现与调用都必须失败。`[NEW DESIGN]`

---

## 6. Core Concepts

### 6.1 执行证据对象分离

`[NEW DESIGN]`（对象落点 `[DIRECTLY SUPPORTED]` / `[ADAPTED]`）七个对象必须分离，禁止合并进同一个对象：

Trajectory ≠ ArtifactSet ≠ Review ≠ VerificationEvidence ≠ EvaluationResult ≠ ReplayConfig ≠ CapabilityCandidate

| 对象 | 定义 | 证据落点 |
|---|---|---|
| Trajectory / Transcript | 一次执行的顺序记录（messages / steps / actions / observations） | Codex rollout packets；Harbor `Trajectory`；SWE-agent `.traj` |
| ArtifactSet | 执行产生的文件 / 变更（diff、patch、artifacts） | Codex `unified_diff`；Harbor `artifacts/`；SWE-agent `.patch` / `.pred` |
| Review | 模型对 worker packet 的审查判断（worker_status / result_review_status / correction_owner） | Codex `result-review: approved` 解析 |
| VerificationEvidence | 命令级、可复验的证明（status / verification command / exit_code / stdout_ref / stderr_ref / checker_result / evidence_digest / evidence_refs / gaps） | Codex `[OPEN QUESTION]`（v0 producer 允许 `status=unknown` / `evidence_refs=[]` / `gaps=[...]`）；Harbor verifier logs；SWE-agent results.json（间接） |
| EvaluationResult | 能力级判定（pass rate / verdict） | Codex 无；Harbor `result.json`；SWE-agent `results.json` |
| ReplayConfig | 可重建原始执行的环境 + 动作输入 | Codex 无；Harbor `load_trajectory`；SWE-agent `replay_config` |
| CapabilityCandidate | 可复用的 entrypoint + contract + implementation + tests | 三项目均无 → `[NEW DESIGN]` |

### 6.2 VerifiedTaskArtifactBundle

`[NEW DESIGN]` Bundle 是 Capabilityization 的 **immutable 输入边界**，职责：

- Execution transcript / packets
- Artifact references
- Review evidence 与 verification_evidence（两个独立 section）
- Environment metadata
- Provenance
- Optional replay reference

Bundle 不是 Capability；Bundle 不包含 Candidate、Capability Manifest、Promotion state、Evaluation Result、secrets、live workspace dependency、完整历史默认输入、无限 stdout/stderr。大对象一律 reference + digest。

结构见 §7.1。

### 6.3 Artifact Builder

`[NEW DESIGN]` 新增核心 Module：

- 从 Codex rollout JSONL 解析 packets / facts / identity
- 获取 TurnDiff
- 在 turn 结束时捕获 runtime-only 数据（最终文件全文 / 引用、最终 phase 状态、验证输出、成功命令 exit code 等）
- 捕获最终 workspace snapshot / file references
- 捕获 verification evidence（MVP 能做到则捕获；否则记入 `provenance.gaps`）
- 计算 digest
- 原子写 Bundle

职责边界：

- Artifact Builder = Execution evidence reconstruction / capture
- Capabilityizer = Capability extraction / transformation

Capabilityizer 不应直接读取 live Codex session / 当前 Codex process state；rollout 解析与 runtime-only 捕获全部属于 Artifact Builder。

### 6.4 Review ≠ VerificationEvidence

`[DIRECTLY SUPPORTED]` + `[OPEN QUESTION]`

Review（模型判断）：

- `worker_status`：`complete | incomplete | invalid`
- `result_review_status`：`approved | revise | none`
- `correction_owner`：`worker | explorer | root | user | null`

VerificationEvidence（命令级、可复验的确定性证据）：

- `status`：`complete | unknown`（Codex v0 producer 允许 `unknown`）
- `verification_command`
- `exit_code`
- `stdout_ref` / `stderr_ref`
- `checker_result`
- `evidence_digest`
- `evidence_refs`（Codex v0 producer 允许 `[]`）
- `gaps`（Codex v0 producer 必须记录缺失项）

Bundle schema 只定义 verification_evidence 的字段、类型与引用约定。Codex 当前没有稳定的结构化 verification command / exit_code / stdout / stderr / checker result，因此该 section 在 Codex v0 producer 中允许 `status = unknown`、`evidence_refs = []`、`gaps = [...]`；禁止伪造 command / exit_code / stdout / stderr。

`result-review: approved` 只能表示“模型 review 认可 Worker packet”，**不能等价于 “Task Verification PASS”**。Codex 当前源码没有命令级 verification evidence（只有 worker packet 文本声明 + 模型审查），因此 VerificationEvidence 在 Codex 侧标记 `[OPEN QUESTION]`，MVP 不虚构字段内容。

### 6.5 Task Verification vs Capability Evaluation

`[DIRECTLY SUPPORTED]` Task Verification 在当前 Codex 源码中 = Result Review 的模型审查判断 + worker packet 声称的 verification 文本；它不是命令级确定性验证。Capability Evaluation 证明“脱离原 Task 后能被未来重复正确调用”（含 S0 独立复用场景）。两者不等价；核心不变量：

`result-review: approved` ≠ Task Verification PASS ≠ Capability Evaluation PASS ≠ Promotion

（Review ≠ VerificationEvidence；CapabilityEvaluation 是 Candidate / Version 的下游对象，Promotion 是用户显式确认后的状态迁移。）

### 6.6 Capabilityization

`[NEW DESIGN]` Capabilityization 是把 Bundle 转换成 CapabilityCandidate 的变换过程，不是文件复制：

```
VerifiedTaskArtifactBundle
+ immutable Workspace Snapshot / Artifact References
+ User Confirmation
+ LLM Proposal
→ Identify Reusable Behavior
→ Extract Entrypoint
→ Parameterize
→ Remove Task-private State
→ Extract Contract
→ Generate Tests
→ CapabilityCandidate
```

- Identify Reusable Behavior：从 Bundle 的 packets + diff + review 状态识别“这次做了什么”；是否可复用由用户显式确认，不自动猜测。
- Extract Entrypoint：确定稳定入口（command + workdir）；需要 immutable workspace snapshot 引用（Bundle 引用的 artifact）提供最终文件形态。
- Parameterize：把硬编码输入（文件路径、参数、常量）转成 contract.input / args；entrypoint 只能通过 contract 声明的输入运行。
- Remove Task-private State：剥离原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件、未声明 secret、未声明 environment dependency。
- Extract Contract：固定 input contract / output contract（文件、args、stdout、exit code）。
- Generate Tests：从已验证调用捕获 golden tests，并为 Evaluation 准备 Novel Input Test 与 independent reuse scenario（S0）。

Workspace Snapshot 是 Bundle 引用的 immutable source artifact，不是 Capabilityizer 对原 workspace 的 live dependency：

```
VerifiedTaskArtifactBundle
    └── artifacts.files[].content_ref
            ↓
       immutable workspace snapshot

Capabilityizer
    ↓
only reads bundle + immutable referenced artifacts
```

禁止：

- Capabilityizer → 原 Session
- Capabilityizer → 原 Agent Context
- Capabilityizer → 原 Workspace live path
- Capabilityizer → 当前 Codex process state

Capabilityizer 必须在独立环境中完成。

职责边界：LLM 只负责 propose reusable behavior / entrypoint / parameterization；deterministic validation 负责 enforce contract / private-state isolation / permissions / resource limits。LLM 不得单独决定 Candidate 合法。

### 6.7 Register / Activate / Revoke

`[NEW DESIGN]`（三项目均无此抽象，artifact-boundary-comparison.md §4）

- Register：写入 Registry，产生可发现性。
- Activate Instance：创建 CapabilityInstance（`activating → running`）；不改变 Capability 自身状态。
- Revoke：若 instance running 先 stop；标记 Registry 不可调用（tombstone）。

### 6.8 Discovery ≠ Gap Detection

`[NEW DESIGN]` Discovery 是显式查找：新任务按能力名查询 Registry。MVP 不做自动扫描任务需求、自动注入能力。

### 6.9 单实例

`[NEW DESIGN]` 一个 Promoted Capability 最多一个 running CapabilityInstance。`running` 只描述 Instance status，不是 Capability state。

### 6.10 Replay vs Capability Invoke

`[ADAPTED]` SWE-agent 有 `replay_config`（全新环境重执行动作），Harbor 有 `load_trajectory`（会话种子转换），Codex 当前没有 replay config（`[OPEN QUESTION]`）。

v0.3 结论：

- `replay_reference` = optional reference，不阻塞 MVP。
- Replay = reproduce / re-execute 原始执行。
- Capability Invoke = 对 promoted capability 以新 input/context 执行。
- Replay ≠ Capability Reuse。

---

## 7. Domain Objects

MVP 只定义 6 个 Domain Object：VerifiedTaskArtifactBundle、CapabilityCandidate、Capability、CapabilityVersion、CapabilityInstance、CapabilityEvaluation。Artifact Builder / Validator / Evaluator / Registry / Runtime 是 Module，不单独建模为对象；Manifest、Contract、Tests、Provenance 是嵌入/附属于这些对象的 value objects。

### 7.1 VerifiedTaskArtifactBundle

`[NEW DESIGN]`（引用策略 `[ADAPTED]`：Harbor `artifacts/` 与图片 path+media_type 引用、SWE-agent 独立文件落盘）

```text
VerifiedTaskArtifactBundle v0
├── schema_version
├── bundle_id
├── identity          # session/thread/turn/runtime/commit/rollout reference —— immutable
├── execution         # phase packets + status + root synthesis —— immutable，引用 rollout
├── artifacts         # unified_diff 内嵌；files[] 引用 —— immutable
├── review            # worker_status / result_review_status / correction_owner —— immutable
├── verification_evidence  # status / command / exit_code / stdout_ref / stderr_ref / checker_result / evidence_digest / evidence_refs / gaps —— Codex v0 producer 允许 status=unknown / evidence_refs=[] / gaps=[...]，禁止伪造
├── environment       # cwd / workspace_roots / network / policy 元数据 + snapshot reference —— immutable
├── replay_reference  # optional —— immutable
└── provenance        # producer / generated_at / input refs / digests / gaps —— immutable
```

`artifacts.files[]` 至少包含：

```json
{
  "path": "src/main.py",
  "status": "added | modified | deleted | renamed",
  "digest": "sha256:...",
  "content_ref": "bundles/<bundle_id>/files/<digest>",
  "media_type": "text/x-python"
}
```

只保存 path + digest 不够：必须同时给出 `content_ref` 与 `media_type`，使消费端可定位大对象而不把内容嵌入 Bundle。

Bundle 中不允许：

- CapabilityCandidate
- Capability Manifest
- Promotion state
- Evaluation Result
- secrets
- live workspace dependency
- 完整历史作为默认输入
- 无限 stdout/stderr

Bundle 在生成后 immutable；Evaluation Result 与 Promotion 永不回写 Bundle。

### 7.2 CapabilityCandidate

`[NEW DESIGN]`（校验对象形态 `[ADAPTED]`：Harbor `TrajectoryValidator` 严格 schema 校验）

- `candidate_id`：稳定标识。
- `manifest`：Capability Manifest v0.1。
- `implementation`：提取并参数化后的实现（entrypoint + 声明保留的文件）；不是原 workspace 副本。
- `tests`：golden test cases。
- `provenance`：来源记录（含 `source_bundle_id`）。
- `state`：`candidate | validating | validated | failed`。
- 可修改：用户在 `/forge` 期间可编辑 manifest / tests。

`[NEW DESIGN]` Candidate 不携带原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件；未声明 secret / environment dependency 在 Capabilityization 阶段即被剥离。Candidate 不在 Bundle 内。

### 7.3 Capability

`[NEW DESIGN]`（稳定身份 `[ADAPTED]`：SWE-agent `info.swe_agent_hash/version` 提供版本化身份先例）

- `capability_id`：跨版本稳定。
- `name`：唯一，kebab-case。
- `description`。
- `current_version_id`：当前（MVP 唯一）版本指针，不是 runtime 状态。
- `state`：`promoted | revoked`（Capability 自身没有 runtime process / active 状态）。
- `availability`：`available | unavailable`（Registry 根据 forged artifact 存在性 + `forged_artifact_digest` 校验派生的健康标记，不是 Capability state）。
- 不持有运行时资源；运行时资源属于 Instance。

### 7.4 CapabilityVersion

`[ADAPTED]`（不可变版本 + `schema_version`：Harbor ATIF 严格版本化 schema；`version_id` MVP 恒为 `v1`）

- `version_id`：MVP 恒为 `v1`。
- `capability_id`。
- `manifest`、`forged_artifact_digest`、`tests`、`evaluation_id`、`created_at`。
- 创建后不可变；MVP 无 update/rollback API。

### 7.5 CapabilityInstance

`[NEW DESIGN]`（一次激活）

- `instance_id`：每次激活新建。
- `version_id`。
- `sandbox`、`process`、`status`：`activating | running | stopped | failed`。
- `started_at`、`timeout`、`output`。
- 一个 Capability 最多一个 running instance。
- Instance 生命周期不影响 Capability state；`running` 只存在于 Instance status。

### 7.6 CapabilityEvaluation

`[NEW DESIGN]`

- `evaluation_id`。
- `candidate_id` / `version_id`。
- `test_cases`、`expected_outputs`、`pass_rate`、`regression`、`novel_input_test`（S0 场景 PASS/FAIL）、`independent_reuse`（S0 场景 PASS/FAIL）、`verdict`（PASS/FAIL）、`promotion_rule`、`evaluated_at`。
- 不可变，随 Version 持久化；**不写回 Bundle**。

为什么 6 个够：Manifest/Contract/Tests/Provenance 没有独立生命周期，只是 Candidate/Version 的数据；Registry 操作不是对象；Sandbox 是执行环境。增加对象只会引入并行生命周期，违反 YAGNI。`[NEW DESIGN]`

---

## 8. Capability Manifest v0.1

`[NEW DESIGN]`（字段来源 `[ADAPTED]`：Harbor `Agent{name, version}`、`schema_version`；SWE-agent `AgentInfo` 版本/hash；provenance 来自 Bundle identity）

```json
{
  "manifest_version": "0.1",
  "capability": {
    "name": "csv-clean-report",
    "description": "读取 CSV，按规则清洗并生成统计报告",
    "version": 1
  },
  "entrypoint": {
    "command": ["python", "main.py"],
    "workdir": "artifact"
  },
  "contract": {
    "input": {
      "files": ["data/*.csv"],
      "args": {"rules": "object"}
    },
    "output": {
      "files": ["report/*.md"],
      "stdout": "string",
      "exit_code": 0
    }
  },
  "env": {},
  "secrets": [],
  "tests": [
    {"id": "t1", "input": {"files": ["data/sample.csv"], "args": {"rules": {}}}, "expected": {"files": ["report/report.md"]}}
  ],
  "sandbox": {
    "permissions": {"network": false, "fs_write": ["/work/output"]},
    "limits": {"timeout_seconds": 60, "output_bytes": 1048576}
  },
  "provenance": {
    "source_bundle_id": "bundle-...",
    "source_artifact_digest": "sha256:...",
    "source_task_id": "task-...",
    "source_execution_id": "exec-...",
    "forged_artifact_digest": "sha256:...",
    "forge_timestamp": "2026-08-14T..."
  }
}
```

校验规则：`name` 必须唯一且 kebab-case；`entrypoint.command` 必须存在于 forged artifact；`contract.input/output` 必须可解析；`tests` 非空；`sandbox.permissions` 必须在允许集内；`provenance` 必须完整且同时包含 `source_bundle_id`、`source_artifact_digest` 与 `forged_artifact_digest`（Bundle 为 read-only 输入，forged artifact 为 Capabilityization 产物）；`env` / `secrets` 只允许声明 Capability 运行所需的显式依赖，`implementation` 引用的任何环境变量 / secret 必须已声明（未声明者 validation FAIL）。

Manifest 属于 Candidate / Version，不属于 Bundle。

---

## 9. Capabilityization Flow

`[NEW DESIGN]`

```
VerifiedTaskArtifactBundle + immutable Workspace Snapshot / Artifact References + User Confirmation + LLM Proposal
→ Identify Reusable Behavior → Extract Entrypoint → Parameterize → Remove Task-private State → Extract Contract → Generate Tests
→ CapabilityCandidate
```

| 问题 | MVP 答案 |
|---|---|
| 输入是什么？ | VerifiedTaskArtifactBundle（immutable 输入边界）+ immutable Workspace Snapshot / Artifact References + User Confirmation + LLM Proposal。rollout 解析与 runtime-only 捕获属于 Artifact Builder，Capabilityizer 不读 live Codex session。`[NEW DESIGN]` |
| 输出是什么？ | CapabilityCandidate：manifest draft + implementation（提取后参数化的实现，不是原 workspace 副本）+ tests + provenance |
| 如何识别可复用行为？ | 从 Bundle 的 packets + diff + review 状态识别；用户显式确认“可复用”，绝不自动猜测。`[NEW DESIGN]` |
| 如何确定 entrypoint？ | `/forge` 要求用户确认；immutable workspace snapshot 引用（Bundle 引用的 artifact）提供最终文件形态。若 changed files 中恰好一个可执行文件，预填并让用户确认；多个候选则必须由用户选择，绝不猜测。`[NEW DESIGN]` |
| 如何参数化？ | 把硬编码输入（文件路径、参数、常量）转成 `contract.input` / args；entrypoint 只能通过 contract 声明的输入运行。`[NEW DESIGN]` |
| 如何去除 Task-private state？ | 剥离原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件、未声明 secret、未声明 environment dependency；白名单只保留 contract 声明的输入输出。`[NEW DESIGN]` |
| 如何生成 input/output contract？ | 从已验证调用的输入输出对生成：input = 输入文件 + 参数；output = 输出文件 + exit code + stdout。生成 JSON Schema 草稿，用户在 validation 前可编辑。`[NEW DESIGN]` |
| 如何生成 tests？ | golden tests：从已验证执行捕获 input/expected 对。Evaluation 阶段另需 ≥1 个 Novel Input Test（未在原 Task 中出现过的输入）+ 1 个 independent reuse scenario（S0）。`[NEW DESIGN]` |
| 如何记录 provenance？ | 写入 `manifest.provenance`：`source_bundle_id` + `source_artifact_digest`（read-only 输入）+ `forged_artifact_digest`（Capabilityization 产物）；Bundle 绝不修改；不保存完整 trajectory。`[DIRECTLY SUPPORTED]` + `[NEW DESIGN]` |
| LLM 与 deterministic validation 的边界？ | LLM 只 propose reusable behavior / entrypoint / parameterization；deterministic validation 负责 enforce contract / private-state isolation / permissions / resource limits；LLM 不得单独决定 Candidate 合法。`[NEW DESIGN]` |
| 如何避免一次性 Artifact 被当作 Capability？ | 四个门禁：(1) 用户显式确认“可复用”；(2) golden tests 非空；(3) evaluation 必须通过 Novel Input Test 与 independent reuse scenario；(4) entrypoint 必须参数化且无任务私有依赖——硬编码绝对路径 / 依赖原 workspace / session / Agent context / 临时文件者 validation 失败（S0）。`[NEW DESIGN]` |

---

## 10. Validation

Candidate 验证在脱离原 Task / Agent 上下文的独立沙箱中运行，输出 PASS / FAIL 及原因。所有判定均为 deterministic validation；LLM 只 propose，不得单独决定 Candidate 合法。Validation evidence 产出在 Bundle 外，不写回 Bundle。`[NEW DESIGN]`

| 检查 | 方法 | 失败条件 |
|---|---|---|
| Manifest schema | 按 v0.1 schema 解析 | 缺字段 / name 非法 / 版本非法 |
| Entrypoint | 文件存在、可执行、沙箱内可启动 | 文件缺失 / 启动失败 / 依赖原任务私有状态 |
| Task-private state（S0 Independence） | 在无原 workspace / session / Agent context / 临时文件的隔离沙箱中，仅提供 contract 声明的输入运行；静态检查绝对路径与私有引用 | 引用原 workspace 私有路径 / session / Agent context / 任务临时文件 |
| Secrets / env dependencies | 检查 `implementation` 引用的环境变量与 secret 是否都在 manifest 声明 | 引用未声明 secret / environment dependency |
| Input/Output schema | 按 contract 生成样例调用 | contract 不可解析 / 样例调用失败 |
| Tests | 沙箱内运行全部 golden tests | 任一失败 |
| Sandbox execution | 每次测试在隔离沙箱中执行 | 逃逸 / 越界写入 / 网络被禁用却请求网络 |
| Permissions | manifest 声明的权限 ⊆ 允许集 | 未声明权限（deny-by-default） |
| Resource limits | 强制 timeout 与 output limit | 超时 / 输出超限 / 非零退出 |

Validation 结果：

- PASS：state → `validated`。
- FAIL：state → `failed`，保留 artifact 与原因供用户检查；不进入 Registry。

---

## 11. Evaluation

`[DIRECTLY SUPPORTED]` + `[NEW DESIGN]` 严格区分：

- Review：模型对 worker packet 的审查判断（`result-review: approved`），不是确定性验证。
- VerificationEvidence：命令级可复验证据；Codex 当前 `[OPEN QUESTION]`。
- Capability Evaluation：证明这个能力脱离原 Task 后可以被未来重复正确调用——评估“未来复用能力”，不是再次证明原 Task 做对了。

MVP 定义（`[NEW DESIGN]`），至少包括四类证据：

- golden tests：来自 Capabilityization 的已验证 input/expected 对。
- Novel Input Test：≥1 个未在原 Task 中出现过的输入。
- regression：evaluation 必须重新通过全部 validation golden tests。
- independent reuse scenario：新 Session、新 Input，脱离原 Task / Session / Workspace 私有状态调用（S0）。

`[NEW DESIGN]` **Novel Input Test ≠ Statistical Generalization Proof**。MVP 的测试数量用于证明 Capabilityization → Validation → Evaluation → Reuse → Revoke 的闭环成立，不用于证明统计意义上的泛化能力。

- expected output：确定性比较（exit code + 输出文件 + stdout）；或用户提供的 check 命令（exit 0 为通过）。
- pass rate：passed / total。
- promotion rule：`PASS` 当且仅当 golden 100% + Novel Input Test 100% + regression 通过 + independent reuse 通过；promotion 仍需用户显式确认，不自动执行。

Evaluation 结果写入 `CapabilityEvaluation` 并随 Version 持久化；**不写回 Bundle**。

### 11.1 S0 Independence Test

`[NEW DESIGN]` MVP 核心验收测试：

```
Task A → 完成并捕获 Bundle → /forge → Candidate
→ 删除 / 隔离：原 workspace、原 session、原 Agent context、原临时输入文件
→ 准备 Task B：新 Session、新 Input（Novel Input Test）
→ 调用 Candidate
→ Candidate 必须仍然成功
```

如果 Candidate 仍然依赖原 Task 私有状态（workspace 路径 / session / Agent context / 临时输入文件 / 未声明 secret / 未声明 env dependency）：Validation = FAIL。

S0 是 MVP 成立的五个验收条件之一；在 Validation 与 Evaluation 两个阶段都执行。S0 证明“独立性”，不证明统计泛化。

---

## 12. Lifecycle

Bundle 生命周期：`generated → sealed（immutable）→ consumed by Capabilityizer`；没有后续状态迁移，Evaluation / Promotion 不回写 Bundle。`[NEW DESIGN]`

Capability 状态机：`Candidate → Validating → Validated → Promoted → Revoked`。CapabilityInstance 状态机：`Activating → Running → Stopped / Failed`。`[NEW DESIGN]`

Capability 与 Instance 正交：Invoke / Stop / 失败只改变 Instance status，不改变 Capability state；stop 后 Capability 仍为 `promoted`，可再次激活。

| Transition | Trigger | Precondition | Action | Success state | Failure state |
|---|---|---|---|---|---|
| candidate → validating | `/forge validate` | candidate 存在；manifest schema 合法 | 运行全部验证检查 | `validated` | `failed`（含原因） |
| validating → validated | 验证完成 | 全部检查 PASS | 记录验证结果（Bundle 外） | `validated` | `failed` |
| validated → promoted | `/forge promote`（用户显式） | validation PASS；evaluation PASS | 创建 Capability + CapabilityVersion v1；写入 Registry；复制 forged artifact 到 registry 存储 | `promoted`（可发现，无实例） | 停留在 `validated`；无部分写入 |
| invoke（Capability 不变） | invoke | state=`promoted`；availability=`available`；未 revoked | 创建 CapabilityInstance（`activating` → `running`）；启动沙箱进程 | instance `running`；capability 仍 `promoted` | instance `failed`；capability 仍 `promoted`，可重试 |
| stop（Capability 不变） | stop | instance `running` | kill 进程；清理实例 | instance `stopped`；capability 仍 `promoted` | instance `failed`；capability 仍 `promoted`，可重试 stop |
| promoted → revoked | `/forge revoke` | Registry 存在 | 若 instance running 先 stop；成功后写 tombstone | `revoked`（不可发现、不可调用） | 状态不变；stop 失败可重试 |

`promoted` + `unavailable` 时 invoke 不创建实例，直接失败并返回 `artifact unavailable`。`revoked` 是终态；重新获得能力必须重新 `/forge` 生成新 Candidate。`[NEW DESIGN]`

---

## 13. Registry

`[NEW DESIGN]`（artifact 文件落盘 `[ADAPTED]`：Harbor `artifacts/` + manifest、SWE-agent 独立 `.traj/.pred/.patch` 文件；Registry 本身三项目均无）

MVP 用 SQLite 单文件 + 本地 forged artifact 目录，不引入 distributed registry：

- 存储：SQLite `capabilities.db`；forged artifact 存 `registry/artifacts/<capability_id>/<version>/`；manifest 以 JSON 存 DB；Bundle 存 `registry/bundles/<bundle_id>/`（不可变）。
- 操作：
  - `register(capability, version, manifest, forged_artifact)`：Promote 时执行；重名拒绝。
  - `lookup(name|id)`：返回 Capability + current version。
  - `version_lookup(capability_id, version)`：返回 manifest / tests / forged artifact。
  - `discovery(name)`：只返回 `state=promoted` 且 `availability=available` 的 Capability；`promoted + unavailable` 不出现在默认 discovery；MVP 按名字精确匹配。
  - `revoke(capability_id)`：tombstone。
- direct invoke 规则：`promoted + unavailable` 时 invoke 必须失败并返回 `artifact unavailable`。
- 重启后 Registry 完整保留；Instance 不在此层。

---

## 14. Runtime

`[NEW DESIGN]`（每次全新执行环境 `[ADAPTED]`：SWE-agent 每次 run/replay 重建全新 `SWEEnv` + `hard_reset`）

| 项 | MVP 定义 |
|---|---|
| activation | 从 promoted version 创建 Instance；一个 Capability 最多一个 running Instance（启动新实例前先 stop 旧实例）`[NEW DESIGN]` |
| execution | 按 `entrypoint.command` 启动；输入按 contract 提供（文件 / args / stdin）`[NEW DESIGN]` |
| timeout | 按 `sandbox.limits.timeout_seconds` 硬杀；默认 60s `[NEW DESIGN]` |
| output limit | stdout/stderr 截断到 `output_bytes`，exit code 保留 `[NEW DESIGN]` |
| filesystem boundary | forged artifact 只读挂载；仅 contract 声明的输出目录可写 `[NEW DESIGN]` |
| permission boundary | deny-by-default；网络默认关闭；只允许 manifest 声明的能力 `[NEW DESIGN]` |
| stop | kill 进程 + 清理沙箱 + instance `stopped` `[NEW DESIGN]` |
| revoke | 若 instance running 先 stop；+ Registry tombstone `[NEW DESIGN]` |

Replay ≠ Invoke：invoke 使用 promoted capability + 新输入；`replay_reference` 只是原执行的引用，不参与 invoke。`[ADAPTED]`（SWE-agent `replay_config` / Harbor `load_trajectory` 语义区分）

Runtime restart 后：Capability 仍然可发现、可调用；running Instance 消失（ephemeral），下次调用重新创建。

---

## 15. Sandbox

`[NEW DESIGN]` Harbor 与 SWE-agent 都没有“能力沙箱”边界（Harbor `node:vm` 类机制不存在；SWE-agent 的隔离是 run/replay 级全新环境重建）。MVP 只借鉴 SWE-agent“每次全新环境”的思想，不复用其作为能力安全边界。

MVP Sandbox：

- OS 级隔离：容器运行时（Docker / podman）或等价机制；每次调用一个全新 Sandbox。
- 无容器运行时：validation 与 invocation 一律 FAIL（fail-closed），不做“降级到裸进程”的伪安全模式。
- 网络默认关闭；forged artifact 目录只读；仅 contract 输出目录可写；强制 timeout 与 output limit。
- Sandbox 与 Instance 同生命周期：激活时创建，stop/revoke 时销毁。

---

## 16. Persistence

`[ADAPTED]`（SWE-agent `.traj/.pred/.patch/results.json` 独立文件、Harbor `artifacts/` + `result.json` 分离）+ `[NEW DESIGN]`

| 对象 | 持久化 |
|---|---|
| VerifiedTaskArtifactBundle | 持久（`registry/bundles/` 或等价 artifact store），生成后不可变 |
| Capability | 持久（SQLite） |
| CapabilityVersion | 持久（SQLite + manifest） |
| manifest | 持久（SQLite JSON + forged artifact 目录） |
| forged artifact | 持久（registry/artifacts，含 `forged_artifact_digest`） |
| CapabilityEvaluation | 持久（SQLite），不写回 Bundle |
| CapabilityInstance | ephemeral（进程 + 运行上下文） |

Runtime restart 后：Capability 可发现、可调用；Instance 需重新激活。`[DIRECTLY SUPPORTED]` 佐证：Harbor `result.json` 与 SWE-agent `preds.json/results.json` 均为独立持久文件，重启不丢失。

---

## 17. Provenance

`[DIRECTLY SUPPORTED]` + `[NEW DESIGN]`

Capability 至少记录：

| 字段 | 来源 |
|---|---|
| source bundle id | Bundle identity / `bundle_id` `[NEW DESIGN]` |
| source task id | Codex Task/Turn/Phase identity `[DIRECTLY SUPPORTED]` |
| source execution id | rollout / session 身份 `[DIRECTLY SUPPORTED]` |
| `source_artifact_digest` | read-only 输入：Bundle digest `[NEW DESIGN]` |
| `forged_artifact_digest` | Capabilityization 产物；绝不修改 source Bundle `[NEW DESIGN]` |
| forge timestamp | `[NEW DESIGN]` |
| tests | Capabilityization 生成 `[NEW DESIGN]` |
| evaluation | CapabilityEvaluation `[NEW DESIGN]` |
| version | CapabilityVersion `[NEW DESIGN]` |

Bundle 是 read-only 输入；Capabilityization 产出 forged artifact，绝不修改 source Bundle。不保存完整 trajectory（Phase History Retention ≠ Capability Persistence，`[DIRECTLY SUPPORTED]`）。Evaluation Result 与 Promotion state 永不写回 Bundle；Bundle 生成后 immutable。

---

## 18. End-to-End Scenario

任务：“读取 CSV，根据规则清洗数据并生成统计报告。”

| # | 步骤 | Observable outcome |
|---|---|---|
| 1 | Agent 完成任务 | worker packet `worker: complete`；Result Review 通过（模型审查判断，不是命令级 verification PASS） |
| 2 | Artifact Builder 捕获 | 解析 rollout packets/facts/identity + TurnDiff；turn 结束时捕获 runtime-only 数据与 immutable workspace snapshot refs；计算 digest；原子写 Bundle |
| 3 | 得到 VerifiedTaskArtifactBundle | bundle_id + schema_version；identity/execution/artifacts/review/verification_evidence/environment/replay_reference/provenance 各 section 存在；verification_evidence 允许 status=unknown / evidence_refs=[] / gaps=[...]；sealed immutable |
| 4 | 用户触发 `/forge` | Capabilityizer 在独立环境读取 Bundle + immutable workspace snapshot refs；用户确认 entrypoint 与可复用性 |
| 5 | 生成 Capability Candidate | candidate_id；manifest + implementation + tests + provenance 生成 |
| 6 | 生成 manifest / implementation / tests | 三者在 candidate 目录存在；manifest schema 合法；provenance 含 `source_bundle_id` |
| 7 | Sandbox validation | `/forge validate` 返回 PASS；state → validated |
| 8 | Capability evaluation | golden + Novel Input Test + regression + independent reuse 全过；pass rate 100%；CapabilityEvaluation PASS（不回写 Bundle） |
| 9 | Promote | `/forge promote` 确认后：Capability + v1 写入 Registry；state → promoted |
| 10 | Registry 持久化 | SQLite 行 + forged artifact + Bundle 落盘；进程重启后 discovery 仍命中（S2） |
| 11 | 新 Task 发现 Capability | 新任务按名字 `discovery` 返回该能力（显式查询，非自动注入） |
| 12 | Invoke | 创建 Instance；沙箱启动 entrypoint；传入新 CSV |
| 13 | 得到正确结果 | 输出文件 + exit code 符合 contract 期望（S3） |
| 14 | Revoke | `/forge revoke`：实例停止；Registry tombstone |
| 15 | 再次调用失败 | `discovery` 不返回该能力；invoke 返回 “capability revoked”（S4） |

---

## 19. Acceptance Criteria

| # | 验收条件 | 可观察证据 |
|---|---|---|
| S0 | Independence | Candidate 不依赖原 Task / Session / Agent Context / Workspace private state；Novel Input Test 与 independent reuse scenario 通过 |
| S1 | Independent Validation | `/forge validate` 在无原 Task / Agent 上下文下 deterministic 地区分 valid / invalid candidate；坏 entrypoint 的 candidate 返回 FAIL |
| S2 | Persistent Discovery | Promoted + available 的 Capability 持久化（含进程重启）；默认 discovery 命中 |
| S3 | Independent Reuse | 新 Task + 新 input 按名字发现 Capability 并独立调用，返回正确输出 |
| S4 | Revoke | revoke 后默认 discovery 不命中；invoke 明确失败 |

S0 ∧ S1 ∧ S2 ∧ S3 ∧ S4 = PASS 时 MVP 成立。`[NEW DESIGN]`

`[NEW DESIGN]` S0 只证明独立性，不声称统计意义上的 generalization；Novel Input Test ≠ Statistical Generalization Proof。

---

## 20. Failure Cases

| 场景 | 期望行为 | 状态 |
|---|---|---|
| Bundle 生成失败 / digest 不一致 / 写入非原子 | Builder 不产出 Bundle，报错可重试；绝不产生半成品 Bundle | 无 Bundle 进入 Capabilityization |
| Bundle 包含禁止对象（Candidate / Manifest / Promotion state / Evaluation Result / secrets） | Builder 拒绝写入；校验 FAIL | Bundle 不生成 |
| Manifest 非法 / entrypoint 缺失 | validation FAIL，原因可读 | candidate `failed`；不进 Registry |
| golden test 失败 | validation FAIL | candidate `failed` |
| Novel Input Test 失败 | evaluation FAIL | 停留在 `validated`；可修后重评 |
| independent reuse scenario 失败 | evaluation FAIL（S0 不通过） | 停留在 `validated` |
| 未 evaluation 就 promote | 拒绝 | 停留在 `validated` |
| invoke 超时 / 输出超限 / 非零退出 | 调用失败，返回原因；实例清理 | capability `promoted`；instance `failed` |
| 越界写文件 / 请求网络 | 被沙箱拒绝 | instance `failed` |
| stop 失败 | 报告错误；可重试 | instance `failed`；capability 仍 `promoted`，可重试 stop |
| revoke 时 stop 失败 | revoke 不执行（先 stop 成功再 tombstone） | 状态不变 |
| 重名 register | register 失败 | 已有 capability 不变 |
| 进程重启 | 能力可发现可调用；实例需重建 | instance 消失；capability 持久 |
| forged artifact 文件缺失 | 默认 discovery 不返回；direct invoke 返回 `artifact unavailable`；记录诊断 | Capability 保持 `promoted`；`availability=unavailable`（MVP 接受，日志告警） |

---

## 21. MVP Architecture

`[NEW DESIGN]` 本地单进程，无网络服务：

```text
Codex Runtime
  │  rollout JSONL（packets / facts / turn_diff / session_meta）+ runtime-only capture
  ▼
Artifact Builder
  │  解析 rollout + 捕获 runtime-only + 计算 digest → 原子写
  ▼
VerifiedTaskArtifactBundle   ← immutable 输入边界
  │  + immutable Workspace Snapshot / Artifact References
  │  + User Confirmation
  │  + LLM Proposal
  ▼
Capabilityizer（独立环境，不接 live session / workspace）
  ▼
CapabilityCandidate
  ▼
Validator（独立沙箱 → PASS/FAIL）
  ▼
Evaluator（golden + Novel Input Test + regression + independent reuse → CapabilityEvaluation）
  ▼
Promotion（用户显式确认）
  ▼
Registry → SQLite + registry/artifacts
  → Discovery → Runtime → Sandbox → Invoke/Stop → Revoke
```

模块职责：

- Artifact Builder：Codex rollout → VerifiedTaskArtifactBundle（execution evidence reconstruction / capture）。
- Capabilityizer：Bundle + immutable workspace snapshot refs + 用户确认 + LLM proposal → Candidate（capability extraction / transformation）。
- Validator：独立验证 Candidate（S0 + S1）。
- Evaluator：能力级评估（CapabilityEvaluation，不回写 Bundle）。
- Registry：持久化 Bundle 引用 / Capability / Version / Evaluation。
- Runtime + Sandbox：激活、执行、停止、撤销。

本轮不写代码；后续实现建议布局 `src/forge/`（见 Implementation Phases）。

---

## 22. Implementation Phases

### P0 — Artifact Contract

范围：

- VerifiedTaskArtifactBundle v0 schema（schema_version / bundle_id / identity / execution / artifacts / review / verification_evidence / environment / replay_reference / provenance）
- immutable 边界与禁止字段
- reference + digest 约定（含 `artifacts.files[]` 的 path / status / digest / content_ref / media_type）
- 证据标签与 `gaps` 记录
- verification_evidence schema（status / command / exit_code / stdout_ref / stderr_ref / checker_result / evidence_digest / evidence_refs / gaps）；Codex v0 producer 允许 `status=unknown`、`evidence_refs=[]`、`gaps=[...]`，禁止伪造命令级字段
- Capabilityizer 输入边界：只读 Bundle + Bundle 内/引用的 immutable artifact + User Confirmation + LLM Proposal；禁止 live session / live workspace / 当前 Codex process state 依赖
- targeted verification：rollout JSONL 字段、runtime-only 捕获点（final file capture、verification evidence、final phase authority、secret scanning、replay）

P0 Exit Condition：

- VerifiedTaskArtifactBundle v0 contract frozen
- Codex producer mapping complete
- every required field has one of：
    - DIRECT
    - runtime capture point
    - explicit OPEN / nullable
- bundle validation rules frozen
- Capabilityizer has no live-workspace dependency

即：

1. **contract frozen**：schema 字段 / 类型 / required / optional 全部固定。
2. **producer mapping complete**：每个字段都有明确来源——rollout / TurnDiff / TurnContext / runtime capture / 或显式 OPEN。
3. **required field resolution complete**：每个 required field 必须满足三者之一——当前有 DIRECT 证据；或有明确的 runtime capture point；或显式允许为空 / OPEN（如 verification_evidence 在 Codex v0 producer 为 `status=unknown`、`evidence_refs=[]`、`gaps=[...]`）。
4. **validation rules frozen**：schema validation、digest、reference、immutable boundary 已定义。
5. **Capabilityizer boundary frozen**：Capabilityizer 只读 Bundle + Bundle 内/引用的 immutable artifact + User Confirmation + LLM Proposal；不允许 live session / live workspace / 当前 Codex process state 依赖。

### P1 — Artifact Builder + Capabilityizer

范围：

- Artifact Builder：rollout 解析（packets / facts / identity）、TurnDiff、runtime-only capture、immutable workspace snapshot refs、digest、原子写 Bundle
- Manifest v0.1
- 6 个 Domain Objects
- Capabilityizer：reusable behavior identification、entrypoint extraction、parameterization、task-private state removal、contract extraction、test generation、provenance

P1 Exit Condition：

> CapabilityCandidate Complete

也就是：

```
VerifiedTaskArtifactBundle
+ immutable Workspace Snapshot / Artifact References
+ User Confirmation
+ LLM Proposal
→ Capabilityizer
→ 完整 CapabilityCandidate
```

Candidate 必须包含：

- manifest
- forged implementation
- entrypoint
- input/output contract
- tests
- provenance（含 `source_bundle_id`）
- `source_artifact_digest`
- `forged_artifact_digest`

注意：

P1 不负责证明 Sandbox Independence。

### P2 — Validator + Sandbox

范围：

- independent sandbox
- deterministic validation
- task-private-state checks（S0 Independence）
- permission checks
- resource limits
- golden tests

P2 Exit Condition：

> S0 Independence + S1 Independent Validation

S0：Candidate 脱离原 Task / Session / Agent Context / Workspace 私有状态后仍能运行。

S1：Validator 可以 deterministic 地区分 valid / invalid candidate。

### P3 — Evaluation

范围：

- CapabilityEvaluation（golden + Novel Input Test + regression + independent reuse）
- promotion rule（PASS 条件 + 用户显式确认）
- 结果持久化，且不回写 Bundle

P3 Exit Condition：

> CapabilityEvaluation PASS

### P4 — Registry + Persistence + Discovery

范围：SQLite Registry + promote + 持久化（含 Bundle 存储）+ discovery。

Exit Condition：

> S2 Persistent Discovery

### P5 — Runtime + Invoke + Revoke + E2E

范围：Runtime invoke/stop、revoke、E2E 场景、failure cases。

Exit Condition：

> S3 Independent Reuse + S4 Revoke

每个阶段先做该阶段最小可运行闭环，不提前实现后续阶段能力。`[NEW DESIGN]`

---

## 23. Open Questions

1. `[OPEN QUESTION]` **final file capture**：最终文件全文从哪里来——Artifact Builder 在 turn 结束时捕获，还是 Capabilityizer 读取 Bundle 引用的 immutable workspace snapshot（不允许读取 live workspace）？Codex 当前只持久化 unified diff（`TurnDiffTracker` 内存有全文、不序列化）。P0 必须确定捕获点，否则 Bundle `artifacts.files[].content_ref` 无法成立。
2. `[OPEN QUESTION]` **verification evidence**：Codex 当前只有模型文本声明（worker packet + `result-review`），无命令级 verification command / exit_code / stdout/stderr。v0 的 VerificationEvidence 是重跑验证命令，还是捕获运行期输出？当前只能以 `status=unknown`、`evidence_refs=[]`、`gaps=[...]` 表示。
3. `[OPEN QUESTION]` **final phase authority**：`run_phases` 状态机（retry / supersede / truncation）是唯一权威；Artifact Builder 需要 runtime 暴露最终 phase 状态，否则多 worker packet 时无法判定哪个是最终有效 packet。
4. `[OPEN QUESTION]` **secret scanning**：execution facts 已脱敏，但 packet / diff 是自由文本；Bundle 写入前是否需要统一 secrets 扫描，P0 的 `gaps` 如何记录。
5. `[OPEN QUESTION]` **replay**：Codex 无 replay config；SWE-agent `replay_config` 与 Harbor `load_trajectory` 只是 `[ADAPTED]` 参考。MVP 只保留 `replay_reference`；是否以及如何实现 replay 不在 MVP 阻塞范围。
6. `[OPEN QUESTION]` **reuse/generalization evidence**：Novel Input Test ≠ Statistical Generalization Proof；跨任务可复用性需要 N 个 Bundle + evaluation 证据，MVP 不声称统计泛化，P1 是否只做 candidate extraction、不做 promotion。
7. `[OPEN QUESTION]` 目标机器是否具备容器运行时（Docker / podman）？Sandbox fail-closed 设计依赖它。
8. `[OPEN QUESTION]` 输出比较语义：非确定性输出（时间戳、行序）如何比较？MVP 先取“用户提供 check 命令”作为逃生口。
9. `[OPEN QUESTION]` Discovery 匹配：MVP 按名字精确匹配；是否需要 description 关键词匹配，等 S2 通过后再决定。
10. `[OPEN QUESTION]` `/forge` 的集成面：作为 Codex session 扩展（tool）还是独立 CLI？影响 P1 的入口实现。
11. `[OPEN QUESTION]` Promotion 确认形式：MVP 用 CLI 显式确认；不建复杂 Human Approval UI。

---

## v0.3 Final Consistency Notes

1. **Bundle immutable input boundary**：VerifiedTaskArtifactBundle 生成后 immutable；Evaluation Result 与 Promotion state 永不写回 Bundle；Bundle 不包含 Candidate / Capability Manifest / Promotion state / Evaluation Result / secrets / live workspace dependency / 完整历史默认输入 / 无限 stdout/stderr。
2. **Terminology sweep**：执行证据输入一律称 VerifiedTaskArtifactBundle；独立输入用例更名为 Novel Input Test；S0 更名为 Independence，不再使用 Generalization 表述。
3. **Review ≠ VerificationEvidence**：`result-review: approved` 只是模型 review 认可 Worker packet，不等于 Task Verification PASS ≠ Capability Evaluation PASS ≠ Promotion；命令级 verification evidence 在 Codex 侧标记 `[OPEN QUESTION]`，Codex v0 producer 允许 `status=unknown` / `evidence_refs=[]` / `gaps=[...]`，不虚构字段。
4. **Capabilityizer boundary**：输入 = Bundle + immutable Workspace Snapshot / Artifact References + User Confirmation + LLM Proposal；只读 Bundle 内/引用的 immutable artifact；禁止读取 live session / 原 Agent Context / 原 workspace live path / 当前 Codex process state；rollout 解析与 runtime-only 捕获属于 Artifact Builder。
5. **Replay optional**：replay = optional reference；Replay（重放原执行）≠ Capability Invoke（以新输入调用 promoted capability）≠ Capability Reuse。
6. **P0-P5 与 S0-S4 对齐**：P0 = contract frozen + Codex producer mapping complete + required field resolution complete + validation rules frozen + Capabilityizer 无 live-workspace dependency；P1 = CapabilityCandidate Complete；P2 = S0 + S1；P3 = CapabilityEvaluation PASS；P4 = S2；P5 = S3 + S4。
7. **S0-S4 语义**：S0 Independence（不声称统计泛化；Novel Input Test ≠ Statistical Generalization Proof）、S1 Independent Validation（deterministic 区分 valid/invalid）、S2 Persistent Discovery、S3 Independent Reuse（新 Task + 新 input）、S4 Revoke（discovery 与 invoke 都失败）。
8. **Domain boundary**：Bundle → Capabilityizer → Candidate；CapabilityEvaluation 是 Candidate 的下游对象；Evaluation / Promotion 不回写 Bundle。
9. **Architecture**：Artifact Builder 出现在架构图中（Codex Runtime → Artifact Builder → Bundle → Capabilityizer → Candidate → Validator → Evaluator → Promotion）。
10. **证据标签**：新 Bundle / Artifact Builder / Capabilityizer boundary 标 `[NEW DESIGN]`；借鉴 Harbor / SWE-agent 机制标 `[ADAPTED]`；Codex 当前不存在的能力标 `[OPEN QUESTION]`；不把 inferred design 写成 DIRECTLY SUPPORTED。
