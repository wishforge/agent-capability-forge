# Agent Capability Forge — MVP Specification

状态：Draft v0.2（本轮只产设计文档，不写 `src`）
日期：2026-08-14
仓库：`<home>/big-wish`

## 证据基础

- Codex #32100：<https://github.com/openai/codex/issues/32100>；实现 <https://github.com/yusing/codex>，重点 `codex-rs/core/src/session/orchestrated.rs`
- DeepSeek Harness：<https://github.com/deepseek-ai/deepseek-harness>，commit `47f943859bef60e4160492346772ded9b24f765a`；重点 `packages/extensions/cordis-host-runner/`、`packages/extensions/tool-cordis/`、`packages/extensions/cordis-client-runner/`、`vendor/cordis/`
- 本仓库考古证据：
  - `research/source-baseline.md`
  - `research/codex/codex-32100-worker-result.md`
  - `research/deepseek/deepseek-harness-capability-archaeology.md`
  - `research/deepseek/deepseek-harness-dynamic-plugin-lifecycle-archaeology.md`

证据标签：

- `[DIRECTLY SUPPORTED]`：直接来自 research / source evidence
- `[ADAPTED]`：从源码机制改编
- `[NEW DESIGN]`：本 MVP 自己的设计
- `[OPEN QUESTION]`：当前证据不足

---

## 1. Problem

`[DIRECTLY SUPPORTED]` Codex #32100 的 Worker Result（PhasePacket）是一个 **Verified Task Execution Artifact**：它携带 text、truncation 信息与 execution_facts（changed files、verification、failures、risks），并经过 ResultReview 门禁。它证明“这一次任务做对了”，但没有 Capability Identity、Capability Version、Registry、独立 Invocation、Future Discovery 或 Promotion（codex-32100-worker-result.md:6-10）。

`[DIRECTLY SUPPORTED]` DeepSeek Harness 的 Dynamic Cordis Plugin 提供了接近能力运行时的最小原语：`define → package/version → run → tool/fiber → stop → undefine`，并有明确的 Run/Attempt/Plugin 对象模型（dynamic-plugin-lifecycle-archaeology.md:3-4, 19）。但它不是 Capability Forge：

- Registry 是 memory-only，进程重启即丢失（capability-archaeology.md:11；lifecycle-archaeology.md:15）。
- define 输入是源码字符串，不是“已验证任务产物”到可复用能力的转换。
- 没有 Promotion、Discovery、持久化 Evaluation、Revoke 后不可调用的语义。
- Sandbox 明确“不是安全边界”（lifecycle-archaeology.md:14.1）。

缺口：从“一次性做对的任务产物”到“可验证、可注册、可发现、可独立调用、可复用、可撤销的正式 Capability”之间没有通路。另一个缺口是：把 Verified Task Artifact 直接复制成 Candidate 不是 Capabilityization——候选必须经过识别可复用行为、提取 entrypoint、参数化、剥离任务私有状态、提取契约、生成测试的变换，否则只是原 workspace 的快照，不是可独立复用的能力。

---

## 2. Product Hypothesis

唯一假设：

> 一个已经完成并验证成功的 Task Execution Artifact，可以被 Capability Forge 转换成一个可验证、可注册、可发现、可独立调用、可复用、可撤销的正式 Capability。

MVP 用 S0-S4 五个验收条件证明该假设；不做自动 Capability Gap Detection。`[NEW DESIGN]`

---

## 3. Goals

- G1：`/forge` 把 Verified Task Artifact 转成 CapabilityCandidate：识别可复用行为 → 提取 entrypoint → 参数化 → 去除任务私有状态 → 提取契约 → 生成测试，产出 manifest + implementation + tests + provenance。`[NEW DESIGN]`
- G2：Candidate 能脱离原 Task / 原 Agent 上下文独立验证（PASS/FAIL）（S1），且不依赖原 Task 私有状态（S0）。`[NEW DESIGN]`
- G3：Promoted Capability 持久化，能被未来 Task 发现并独立调用（S2 + S3）。`[NEW DESIGN]`
- G4：Revoked Capability 无法再次调用（S4）。`[NEW DESIGN]`
- G5：严格区分 Task Verification 与 Capability Evaluation（Result Review ≠ Capability Promotion）。`[DIRECTLY SUPPORTED]`

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
- 本轮不写 `src`、不实现 API / DB / Sandbox / production code

---

## 5. User Stories

1. 用户完成了一个被验证的任务（如“读取 CSV，清洗数据，生成统计报告”），得到 Verified Task Artifact；输入 `/forge`，希望把它变成以后可复用的能力。`[NEW DESIGN]`
2. 用户希望 Candidate 在脱离原任务的情况下被独立验证，再决定是否信任。`[NEW DESIGN]`
3. 用户在新任务中按名字发现并调用已 Promote 的能力，得到正确结果。`[NEW DESIGN]`
4. 用户撤销一个能力后，再次调用必须失败。`[NEW DESIGN]`

---

## 6. Core Concepts

### 6.1 Verified Task Artifact

`[DIRECTLY SUPPORTED]` 来自 Codex orchestration：Task Contract → Explore → Plan → Review → Worker → Verification → Worker Result / Execution Facts → Result Review → Root Synthesis。Worker Result 是受限 PhasePacket（text + truncation + execution_facts），不是 Capability。

MVP 把它视为 Capabilityizer 的 read-only 输入包（source artifact）：artifact 文件（来自 changed files + verification）+ 验证记录 + source task id + source execution id。确切机器可读格式见 Open Questions。

### 6.2 Task Verification vs Capability Evaluation

`[DIRECTLY SUPPORTED]` Task Verification 证明“这次任务做对了”（ResultReview 门禁）。Capability Evaluation 证明“脱离原 Task 后能被未来重复正确调用”（含 S0 独立复用场景）。两者不等价；Result Review ≠ Capability Promotion。

### 6.3 Capabilityization

`[NEW DESIGN]` Capabilityization 是把 Verified Task Artifact 转换成 CapabilityCandidate 的变换过程，不是文件复制：

```
Verified Task Artifact
→ Identify Reusable Behavior
→ Extract Entrypoint
→ Parameterize
→ Remove Task-private State
→ Extract Contract
→ Generate Tests
→ CapabilityCandidate
```

- Identify Reusable Behavior：从 changed files + verification 记录识别可复用的行为，由用户显式确认，不自动猜测。
- Extract Entrypoint：确定稳定入口（command + workdir）。
- Parameterize：把硬编码输入（文件路径、参数、常量）转成 contract.input / args；entrypoint 只能通过 contract 声明的输入运行。
- Remove Task-private State：剥离原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件、未声明 secret、未声明 environment dependency。
- Extract Contract：固定 input contract / output contract（文件、args、stdout、exit code）。
- Generate Tests：从已验证调用捕获 golden tests，并为 Evaluation 准备 held-out case 与独立复用场景（S0）。

因此 CapabilityCandidate 不是原 Task workspace 的简单复制品。

职责边界：LLM 只负责 propose reusable behavior / entrypoint / parameterization；deterministic validation 负责 enforce contract / private-state isolation / permissions / resource limits。LLM 不得单独决定 Candidate 合法。

Capabilityization 以 source artifact 为 read-only 输入，产出 forged artifact；绝不修改 source Task artifact。

### 6.4 Register / Activate / Revoke

`[ADAPTED]` 从 DeepSeek 的 Disposer（撤销注册表项）、Stop（暂停、保留定义）、Undefine（永久删除）区分而来：

- Register：写入 Registry，产生可发现性。
- Activate Instance：创建 CapabilityInstance（`activating → running`）；不改变 Capability 自身状态。
- Revoke：若 instance running 先 stop；标记 Registry 不可调用（tombstone）。

### 6.5 Discovery ≠ Gap Detection

`[NEW DESIGN]` Discovery 是显式查找：新任务按能力名查询 Registry。MVP 不做自动扫描任务需求、自动注入能力。

### 6.6 单实例

`[ADAPTED]` 一个 Promoted Capability 最多一个 running CapabilityInstance，对应 DeepSeek `DynamicCordisPlugin.run` 单值（lifecycle-archaeology.md:12.1）。`running` 只描述 Instance status，不是 Capability state。

---

## 7. Domain Objects

MVP 只定义 5 个 Domain Object。Manifest、Contract、Tests、Provenance 是嵌入/附属于这些对象的 value objects；Registry row 和 Sandbox 是基础设施，不单独建模。

### 7.1 CapabilityCandidate

`[NEW DESIGN]`（校验对象形态 `[ADAPTED]` 自 `SkillCandidate`/`SkillDefinition`）

- `candidate_id`：稳定标识。
- `manifest`：Capability Manifest v0.1。
- `implementation`：提取并参数化后的实现（entrypoint + 声明保留的文件）；不是原 workspace 副本。
- `tests`：golden test cases。
- `provenance`：来源记录。
- `state`：`candidate | validating | validated | failed`。
- 可修改：用户在 `/forge` 期间可编辑 manifest / tests。

`[NEW DESIGN]` Candidate 不携带原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件；未声明 secret / environment dependency 在 Capabilityization 阶段即被剥离。

### 7.2 Capability

`[NEW DESIGN]`（稳定身份 `[ADAPTED]` 自 `DynamicCordisPlugin.pluginId`）

- `capability_id`：跨版本稳定。
- `name`：唯一，kebab-case（`[ADAPTED]` 自 Skill name grammar）。
- `description`。
- `current_version_id`：当前（MVP 唯一）版本指针，不是 runtime 状态。
- `state`：`promoted | revoked`（Capability 自身没有 runtime process / active 状态）。
- `availability`：`available | unavailable`（Registry 根据 forged artifact 存在性 + `forged_artifact_digest` 校验派生的健康标记，不是 Capability state）。
- 不持有运行时资源；运行时资源属于 Instance。

### 7.3 CapabilityVersion

`[ADAPTED]` 不可变版本，对应 `DynamicCordisDefinition`（packageId = 版本身份）与 `currentPackageId` 指针（lifecycle-archaeology.md:7）。

- `version_id`：MVP 恒为 `v1`。
- `capability_id`。
- `manifest`、`forged_artifact_digest`、`tests`、`evaluation_id`、`created_at`。
- 创建后不可变；MVP 无 update/rollback API。

### 7.4 CapabilityInstance

`[ADAPTED]` 一次激活，对应 `DynamicCordisRun`（fiber/handlers 属于 Run 而非 Plugin，lifecycle-archaeology.md:13）。

- `instance_id`：每次激活新建。
- `version_id`。
- `sandbox`、`process`、`status`：`activating | running | stopped | failed`。
- `started_at`、`timeout`、`output`。
- 一个 Capability 最多一个 running instance。
- Instance 生命周期不影响 Capability state；`running` 只存在于 Instance status。

### 7.5 CapabilityEvaluation

`[NEW DESIGN]`

- `evaluation_id`。
- `candidate_id` / `version_id`。
- `test_cases`、`expected_outputs`、`pass_rate`、`regression`、`independent_reuse`（S0 场景 PASS/FAIL）、`verdict`（PASS/FAIL）、`promotion_rule`、`evaluated_at`。
- 不可变，随 Version 持久化。

为什么 5 个够：Manifest/Contract/Tests/Provenance 没有独立生命周期，只是 Candidate/Version 的数据；Registry 操作不是对象；Sandbox 是执行环境。增加对象只会引入并行生命周期，违反 YAGNI。`[NEW DESIGN]`

---

## 8. Capability Manifest v0.1

`[NEW DESIGN]`（字段来源 `[ADAPTED]`：SkillSummary 的 name/description、DynamicCordisDefinition 的 name/purpose、timeout-policy 的 timeoutMs、guard 的权限白名单；provenance 字段来自 PhasePacket 的 task/execution identity）

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
    "source_task_id": "task-...",
    "source_execution_id": "exec-...",
    "source_artifact_digest": "sha256:...",
    "forged_artifact_digest": "sha256:...",
    "forge_timestamp": "2026-08-14T..."
  }
}
```

校验规则：`name` 必须唯一且 kebab-case；`entrypoint.command` 必须存在于 forged artifact；`contract.input/output` 必须可解析；`tests` 非空；`sandbox.permissions` 必须在允许集内；`provenance` 必须完整且同时包含 `source_artifact_digest` 与 `forged_artifact_digest`（source artifact 为 read-only 输入，forged artifact 为 Capabilityization 产物）；`env` / `secrets` 只允许声明 Capability 运行所需的显式依赖，`implementation` 引用的任何环境变量 / secret 必须已声明（未声明者 validation FAIL）。

---

## 9. Capabilityization Flow

Verified Task Artifact → Identify Reusable Behavior → Extract Entrypoint → Parameterize → Remove Task-private State → Extract Contract → Generate Tests → CapabilityCandidate。`[NEW DESIGN]`

| 问题 | MVP 答案 |
|---|---|
| 输入是什么？ | Verified Task Artifact bundle（read-only source artifact）：artifact 文件（来自 execution_facts.changed_files + verification 记录）、source task id、source execution id。确切 JSON 形状 `[OPEN QUESTION]` |
| 输出是什么？ | CapabilityCandidate：manifest draft + implementation（提取后参数化的实现，不是原 workspace 副本）+ tests + provenance |
| 如何识别可复用行为？ | 从 changed files + verification 记录识别；用户显式确认“可复用”，绝不自动猜测。`[NEW DESIGN]` |
| 如何确定 entrypoint？ | `/forge` 要求用户确认。若 changed files 中恰好一个可执行文件，预填并让用户确认；多个候选则必须由用户选择，绝不猜测。`[NEW DESIGN]` |
| 如何参数化？ | 把硬编码输入（文件路径、参数、常量）转成 `contract.input` / args；entrypoint 只能通过 contract 声明的输入运行。`[NEW DESIGN]` |
| 如何去除 Task-private state？ | 剥离原 workspace 私有路径、原 session 状态、原 Agent context、原任务临时文件、未声明 secret、未声明 environment dependency；白名单只保留 contract 声明的输入输出。`[NEW DESIGN]` |
| 如何生成 input/output contract？ | 从已验证调用的输入输出对生成：input = 输入文件 + 参数；output = 输出文件 + exit code + stdout。生成 JSON Schema 草稿，用户在 validation 前可编辑。`[NEW DESIGN]` |
| 如何生成 tests？ | golden tests：从已验证执行捕获 input/expected 对。Evaluation 阶段另需 ≥1 个 held-out case（未在原 Task 中出现过的输入）+ 1 个 independent reuse scenario（S0）。`[NEW DESIGN]` |
| 如何记录 provenance？ | 写入 `manifest.provenance`：`source_artifact_digest`（read-only 输入）+ `forged_artifact_digest`（Capabilityization 产物）；source Task artifact 绝不修改；不保存完整 trajectory。`[DIRECTLY SUPPORTED]` + `[NEW DESIGN]` |
| LLM 与 deterministic validation 的边界？ | LLM 只 propose reusable behavior / entrypoint / parameterization；deterministic validation 负责 enforce contract / private-state isolation / permissions / resource limits；LLM 不得单独决定 Candidate 合法。`[NEW DESIGN]` |
| 如何避免一次性 Artifact 被当作 Capability？ | 四个门禁：(1) 用户显式确认“可复用”；(2) golden tests 非空；(3) evaluation 必须通过 held-out case 与 independent reuse scenario；(4) entrypoint 必须参数化且无任务私有依赖——硬编码绝对路径 / 依赖原 workspace / session / Agent context / 临时文件者 validation 失败（S0）。`[NEW DESIGN]` |

---

## 10. Validation

Candidate 验证在脱离原 Task / Agent 上下文的独立沙箱中运行，输出 PASS / FAIL 及原因。所有判定均为 deterministic validation；LLM 只 propose，不得单独决定 Candidate 合法。`[NEW DESIGN]`（检查项形态 `[ADAPTED]` 自 `validateCandidate` / `validateDefinition` / `precheckCode` / timeout-policy）

| 检查 | 方法 | 失败条件 |
|---|---|---|
| Manifest schema | 按 v0.1 schema 解析 | 缺字段 / name 非法 / 版本非法 |
| Entrypoint | 文件存在、可执行、沙箱内可启动 | 文件缺失 / 启动失败 / 依赖原任务私有状态 |
| Task-private state（S0） | 在无原 workspace / session / Agent context / 临时文件的隔离沙箱中，仅提供 contract 声明的输入运行；静态检查绝对路径与私有引用 | 引用原 workspace 私有路径 / session / Agent context / 任务临时文件 |
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

`[DIRECTLY SUPPORTED]` 严格区分：

- Task Verification：证明这次任务做对了（Codex ResultReview / execution_facts.verification）。
- Capability Evaluation：证明这个能力脱离原 Task 后可以被未来重复正确调用——评估“未来复用能力”，不是再次证明原 Task 做对了。

MVP 定义（`[NEW DESIGN]`），至少包括四类证据：

- golden tests：来自 Capabilityization 的已验证 input/expected 对。
- held-out case：≥1 个未在原 Task 中出现过的输入。
- regression：evaluation 必须重新通过全部 validation golden tests。
- independent reuse scenario：新 Session、新 Input，脱离原 Task / Session / Workspace 私有状态调用（S0）。

- expected output：确定性比较（exit code + 输出文件 + stdout）；或用户提供的 check 命令（exit 0 为通过）。
- pass rate：passed / total。
- promotion rule：`PASS` 当且仅当 golden 100% + held-out 100% + regression 通过 + independent reuse 通过；promotion 仍需用户显式确认，不自动执行。

Evaluation 结果写入 `CapabilityEvaluation` 并随 Version 持久化。

### 11.1 S0 Independence Test

`[NEW DESIGN]` MVP 核心验收测试：

```
Task A → 完成并验证 → /forge → Candidate
→ 删除 / 隔离：原 workspace、原 session、原 Agent context、原临时输入文件
→ 准备 Task B：新 Session、新 Input
→ 调用 Candidate
→ Candidate 必须仍然成功
```

如果 Candidate 仍然依赖原 Task 私有状态（workspace 路径 / session / Agent context / 临时输入文件 / 未声明 secret / 未声明 env dependency）：Validation = FAIL。

S0 是 MVP 成立的五个验收条件之一；在 Validation 与 Evaluation 两个阶段都执行。

---

## 12. Lifecycle

Capability 状态机：`Candidate → Validating → Validated → Promoted → Revoked`。CapabilityInstance 状态机：`Activating → Running → Stopped / Failed`。`[NEW DESIGN]`（状态语义 `[ADAPTED]` 自 `CordisRunStatus`、`currentPackageId` 保留、`undefine` 删除）

Capability 与 Instance 正交：Invoke / Stop / 失败只改变 Instance status，不改变 Capability state；stop 后 Capability 仍为 `promoted`，可再次激活。

| Transition | Trigger | Precondition | Action | Success state | Failure state |
|---|---|---|---|---|---|
| candidate → validating | `/forge validate` | candidate 存在；manifest schema 合法 | 运行全部验证检查 | `validated` | `failed`（含原因） |
| validating → validated | 验证完成 | 全部检查 PASS | 记录验证结果 | `validated` | `failed` |
| validated → promoted | `/forge promote`（用户显式） | validation PASS；evaluation PASS | 创建 Capability + CapabilityVersion v1；写入 Registry；复制 forged artifact 到 registry 存储 | `promoted`（可发现，无实例） | 停留在 `validated`；无部分写入 |
| invoke（Capability 不变） | invoke | state=`promoted`；availability=`available`；未 revoked | 创建 CapabilityInstance（`activating` → `running`）；启动沙箱进程 | instance `running`；capability 仍 `promoted` | instance `failed`；capability 仍 `promoted`，可重试 |
| stop（Capability 不变） | stop | instance `running` | kill 进程；清理实例 | instance `stopped`；capability 仍 `promoted` | instance `failed`；capability 仍 `promoted`，可重试 stop |
| promoted → revoked | `/forge revoke` | Registry 存在 | 若 instance running 先 stop；成功后写 tombstone | `revoked`（不可发现、不可调用） | 状态不变；stop 失败可重试 |

`promoted` + `unavailable` 时 invoke 不创建实例，直接失败并返回 `artifact unavailable`。`revoked` 是终态；重新获得能力必须重新 `/forge` 生成新 Candidate。`[NEW DESIGN]`

---

## 13. Registry

`[NEW DESIGN]`（目标选择 `[ADAPTED]`：Skill artifact 持久 + SkillRegistry 内存证明“注册表可内存、artifact 可落盘”，但 DynamicCordisRegistry 的 memory-only 是必须修复的缺口）

MVP 用 SQLite 单文件 + 本地 forged artifact 目录，不引入 distributed registry：

- 存储：SQLite `capabilities.db`；forged artifact 存 `registry/artifacts/<capability_id>/<version>/`；manifest 以 JSON 存 DB。
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

`[ADAPTED]` 借鉴 Dynamic Plugin 的最小生命周期：CapabilityVersion → CapabilityInstance → Sandbox → Invoke → Stop（lifecycle-archaeology.md:17-18）。

| 项 | MVP 定义 |
|---|---|
| activation | 从 promoted version 创建 Instance；一个 Capability 最多一个 running Instance（启动新实例前先 stop 旧实例，同 `startFresh` 先 retract）`[ADAPTED]` |
| execution | 按 `entrypoint.command` 启动；输入按 contract 提供（文件 / args / stdin）`[NEW DESIGN]` |
| timeout | 按 `sandbox.limits.timeout_seconds` 硬杀；默认 60s `[ADAPTED]`（timeout-policy / vmTimeoutMs） |
| output limit | stdout/stderr 截断到 `output_bytes`，exit code 保留 `[NEW DESIGN]` |
| filesystem boundary | forged artifact 只读挂载；仅 contract 声明的输出目录可写 `[NEW DESIGN]` |
| permission boundary | deny-by-default；网络默认关闭；只允许 manifest 声明的能力 `[ADAPTED]`（guard 白名单 + 更强的 OS 边界） |
| stop | kill 进程 + 清理沙箱 + instance `stopped` `[ADAPTED]`（`stop()` 保留定义） |
| revoke | 若 instance running 先 stop；+ Registry tombstone `[ADAPTED]`（`undefine()` 先 retract 再删除）+ `[NEW DESIGN]`（持久化 tombstone） |

Runtime restart 后：Capability 仍然可发现、可调用；running Instance 消失（ephemeral），下次调用重新创建。

---

## 15. Sandbox

`[NEW DESIGN]` 关键约束：DeepSeek 的 `node:vm` / closure 遮蔽明确不是安全边界（lifecycle-archaeology.md:14.1），因此 MVP 不复用它做隔离，只借鉴其 guard 思想（compile-only precheck、白名单、deny-by-default）。

MVP Sandbox：

- OS 级隔离：容器运行时（Docker / podman）或等价机制；每次调用一个全新 Sandbox。
- 无容器运行时：validation 与 invocation 一律 FAIL（fail-closed），不做“降级到裸进程”的伪安全模式。
- 网络默认关闭；forged artifact 目录只读；仅 contract 输出目录可写；强制 timeout 与 output limit。
- Sandbox 与 Instance 同生命周期：激活时创建，stop/revoke 时销毁。

---

## 16. Persistence

`[ADAPTED]`（ephemeral 边界沿用 DeepSeek：Run/Fiber/Handler 属于激活期）+ `[NEW DESIGN]`（补齐 DeepSeek 缺失的持久化）

| 对象 | 持久化 |
|---|---|
| Capability | 持久（SQLite） |
| CapabilityVersion | 持久（SQLite + manifest） |
| manifest | 持久（SQLite JSON + forged artifact 目录） |
| forged artifact | 持久（registry/artifacts，含 `forged_artifact_digest`） |
| CapabilityEvaluation | 持久（SQLite） |
| CapabilityInstance | ephemeral（进程 + 运行上下文） |

Runtime restart 后：Capability 可发现、可调用；Instance 需重新激活。`[DIRECTLY SUPPORTED]` 佐证：DynamicCordisRegistry 重启丢失是现状缺口，Skill artifact 文件本身可持久。

---

## 17. Provenance

`[DIRECTLY SUPPORTED]` + `[NEW DESIGN]`

Capability 至少记录：

| 字段 | 来源 |
|---|---|
| source task id | Codex Task/Turn/Phase identity `[DIRECTLY SUPPORTED]` |
| source execution id | Worker Execution / PhasePacket `[DIRECTLY SUPPORTED]` |
| `source_artifact_digest` | read-only 输入：execution_facts.changed_files + 校验 `[DIRECTLY SUPPORTED]` |
| `forged_artifact_digest` | Capabilityization 产物；绝不修改 source Task artifact `[NEW DESIGN]` |
| forge timestamp | `[NEW DESIGN]` |
| tests | Capabilityization 生成 `[NEW DESIGN]` |
| evaluation | CapabilityEvaluation `[NEW DESIGN]` |
| version | CapabilityVersion `[NEW DESIGN]` |

source artifact 是 read-only 输入；Capabilityization 产出 forged artifact，绝不修改 source Task artifact。不保存完整 trajectory（Phase History Retention ≠ Capability Persistence，`[DIRECTLY SUPPORTED]`）。

---

## 18. End-to-End Scenario

任务：“读取 CSV，根据规则清洗数据并生成统计报告。”

| # | 步骤 | Observable outcome |
|---|---|---|
| 1 | Agent 完成任务 | Task verification PASS；ResultReview 通过 |
| 2 | 得到 Verified Task Artifact | source artifact 文件（read-only）+ verification 记录 + source task/execution id 落盘 |
| 3 | 用户触发 `/forge` | Capabilityizer 运行；用户确认 entrypoint |
| 4 | 生成 Capability Candidate | candidate_id；manifest + implementation + tests + provenance 生成 |
| 5 | 生成 manifest / implementation / tests | 三者在 candidate 目录存在；manifest schema 合法 |
| 6 | Sandbox validation | `/forge validate` 返回 PASS；state → validated |
| 7 | Capability evaluation | golden + held-out 全过；pass rate 100%；CapabilityEvaluation PASS |
| 8 | Promote | `/forge promote` 确认后：Capability + v1 写入 Registry；state → promoted |
| 9 | Registry 持久化 | SQLite 行 + forged artifact 落盘；进程重启后仍在（重启后 discovery 仍命中） |
| 10 | 新 Task 发现 Capability | 新任务按名字 `discovery` 返回该能力（显式查询，非自动注入） |
| 11 | Invoke | 创建 Instance；沙箱启动 entrypoint；传入新 CSV |
| 12 | 得到正确结果 | 输出文件 + exit code 符合 contract 期望 |
| 13 | Revoke | `/forge revoke`：实例停止；Registry tombstone |
| 14 | 再次调用失败 | `discovery` 不返回该能力；invoke 返回 “capability revoked” |

---

## 19. Acceptance Criteria

| # | 验收条件 | 可观察证据 |
|---|---|---|
| S0 | Generalization / Independence | Candidate 脱离原 Task / Agent / Workspace 私有状态后仍成功；held-out case 与 independent reuse scenario（S0 Independence Test）通过 |
| S1 | Independent Validation | `/forge validate` 在无原 Task / Agent 上下文下返回 PASS；坏 entrypoint 的 candidate 返回 FAIL（验证具备判别力） |
| S2 | Persistent Discovery | Promoted + available 的 Capability 持久化（含进程重启）；默认 discovery 命中 |
| S3 | Independent Reuse | 新 Task 按名字发现 Capability，以新输入独立调用并返回正确输出 |
| S4 | Revoke | revoke 后默认 discovery 不命中；invoke 明确失败 |

S0 ∧ S1 ∧ S2 ∧ S3 ∧ S4 = PASS 时 MVP 成立。`[NEW DESIGN]`

---

## 20. Failure Cases

| 场景 | 期望行为 | 状态 |
|---|---|---|
| Manifest 非法 / entrypoint 缺失 | validation FAIL，原因可读 | candidate `failed`；不进 Registry |
| golden test 失败 | validation FAIL | candidate `failed` |
| held-out case 失败 | evaluation FAIL | 停留在 `validated`；可修后重评 |
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

```
/forge (CLI / session command)
  → Capabilityizer     → CapabilityCandidate（目录）
  → Validator          → PASS/FAIL（沙箱执行 tests）
  → Evaluator          → CapabilityEvaluation（golden + held-out）
  → Registry           → SQLite + registry/artifacts
  → Discovery          → 按名字查找 state=promoted 且 availability=available
  → Runtime            → CapabilityInstance → Sandbox → Invoke/Stop
  → Revoke             → stop + tombstone
```

模块职责：

- Capabilityizer：输入 Verified Task Artifact → Candidate。
- Validator：独立验证 Candidate。
- Evaluator：能力级评估。
- Registry：持久化 Capability/Version/Evaluation。
- Runtime + Sandbox：激活、执行、停止。

本轮不写代码；后续实现建议布局 `src/forge/`（见 Implementation Phases）。

---

## 22. Implementation Phases

| 阶段 | 范围 | 退出条件 |
|---|---|---|
| P1 | Manifest v0.1 + 5 个 Domain Object 类型 + Capabilityizer | 输入 Verified Task Artifact → 完整 Candidate（S0） |
| P2 | Validator + Sandbox runner | 独立 validation PASS/FAIL（S1） |
| P3 | SQLite Registry + promote + 持久化 + discovery | 重启后仍可发现；默认 discovery 只返回 promoted + available（S2） |
| P4 | Runtime invoke/stop | 新 Task 以新输入独立调用并返回正确输出（S3） |
| P5 | revoke + E2E 场景 + failure cases | revoke 后不可调用（S4）；14 步全部有 observable outcome |

每个阶段先做该阶段最小可运行闭环，不提前实现后续阶段能力。`[NEW DESIGN]`

---

## 23. Open Questions

1. `[OPEN QUESTION]` Verified Task Artifact 的机器可读确切格式：`execution_facts` / verification 记录在 `yusing/codex` `orchestrated.rs` 中的具体 JSON 字段尚未验证。P1 前需要一次 targeted verification，否则 Capabilityizer 输入契约只能按假设实现。
2. `[OPEN QUESTION]` 目标机器是否具备容器运行时（Docker / podman）？Sandbox fail-closed 设计依赖它。
3. `[OPEN QUESTION]` 输出比较语义：非确定性输出（时间戳、行序）如何比较？MVP 先取“用户提供 check 命令”作为逃生口。
4. `[OPEN QUESTION]` Discovery 匹配：MVP 按名字精确匹配；是否需要 description 关键词匹配，等 S2 通过后再决定。
5. `[OPEN QUESTION]` `/forge` 的集成面：作为 Codex session 扩展（tool）还是独立 CLI？影响 P1 的入口实现。
6. `[OPEN QUESTION]` 版本更新 / rollback API：MVP 明确只有 v1；DeepSeek 的 current/next 指针方案（lifecycle-archaeology.md:7-8）留作后续版本，不在 MVP。
7. `[OPEN QUESTION]` Promotion 确认形式：MVP 用 CLI 显式确认；不建复杂 Human Approval UI。

---

## v0.2 Final Consistency Notes

1. **Capability lifecycle**：Capability 状态机为 `Candidate → Validating → Validated → Promoted → Revoked`；CapabilityInstance 为 `Activating → Running → Stopped / Failed`。全文删除 Capability=Active 旧语义；“capability active”一律改为 instance running；Capability 不持有 runtime process（版本指针改为 `current_version_id`）。
2. **Acceptance Criteria**：S0-S4 重新定义为 S0 Generalization / Independence、S1 Independent Validation、S2 Persistent Discovery、S3 Independent Reuse、S4 Revoke；MVP 成立条件为 S0 ∧ S1 ∧ S2 ∧ S3 ∧ S4 = PASS。
3. **Implementation Phases**：P1 → S0、P2 → S1、P3 → S2、P4 → S3、P5 → S4；revoke 移入 P5，全文 S 引用同步（含 Goals、Open Questions）。
4. **Capabilityizer boundary**：LLM 只 propose reusable behavior / entrypoint / parameterization；deterministic validation 负责 enforce contract / private-state isolation / permissions / resource limits；LLM 不得单独决定 Candidate 合法。
5. **Discovery**：只有 `state=promoted` 且 `availability=available` 的 Capability 出现在默认 discovery；`promoted + unavailable` 不出现在默认 discovery，direct invoke 必须失败并返回 `artifact unavailable`。
6. **Provenance / artifact**：source artifact（read-only）→ Capabilityization → forged artifact；manifest 同时记录 `source_artifact_digest` 与 `forged_artifact_digest`；Capabilityization 绝不修改 source Task artifact。
