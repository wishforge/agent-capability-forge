# Capability Forge vs Skill-only — 24-run Pilot Readiness Review

- 状态：REVIEW ONLY（未运行实验、未修改实验设计、未写实现代码、未修改 `src`）
- 日期：2026-08-14
- 审查对象：`research/experiments/capability-forge-vs-skill.md`（v0.2 Final Correction）
- 证据基线：
  - `docs/capability-forge-mvp-spec.md`（v0.3）
  - `research/artifact-contract/verified-task-artifact-bundle-v0.md`（P0 FROZEN）
  - `research/codex-runtime-capture/codex-runtime-capture-archaeology.md`
  - 其余 `research/*/…-archaeology.md`
  - 仓库文件清单、`src/` 状态、本机 CLI / Docker / Ollama 可用性检查

---

# 1. Executive Summary

**Pilot Readiness = NOT READY。**

当前仓库是“设计 + 考古 + 契约”仓库，不是可执行实验仓库：`src/` 为空，没有 experiment harness、没有 task fixtures、没有 oracle、没有 run record、没有成本采集、没有 sandbox 编排、没有模型/配置锁定。

已经具备的（READY）：

- 实验设计冻结（`capability-forge-vs-skill.md` v0.2）。
- VerifiedTaskArtifactBundle v0 契约冻结（P0 FROZEN）。
- Runtime capture point 考古完成（Builder hook、EVENT_CAPTURE 通道、RUNTIME_CHANGE 清单）。
- 容器运行时可用：Docker daemon 29.1.3 在运行，本机存在 `python:3.12-slim`、`debian:bookworm-slim`、`busybox` 等可作 base image 的镜像。
- Agent CLI 存在：`codex` 0.144.4（`codex exec` 可用）；yusing/codex（658630b）源码 clone 在 `<tmp>/yusing-codex`，但未构建出可运行 binary。

核心缺口（BLOCKED）：

- B3 最小 pipeline 不存在 → **implementation blocker**。
- Pilot 任务族无具体任务实例、无 fixture、无确定性 oracle。
- 无统一 run record、无成本 instrumentation、无 V / δ 预注册值。
- 无 model/config 锁定；Ollama 服务未运行（localhost:11434 拒绝连接）。
- 无 skill freeze/invoke 与 human-cost 记录机制。

---

# 2. B0 Readiness

状态：**PARTIAL**

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| Agent CLI 可调用 | READY | `/opt/homebrew/bin/codex`（0.144.4），`codex exec` 存在 |
| 可运行“Agent only”实验臂 | BLOCKED | 无 run harness、无任务 fixture、无模型端点验证 |
| 模型可用 | BLOCKED | 仓库无模型配置；`ollama` 已安装但服务未运行（连接 refused）；未验证任何推理端点 |
| 与 Pilot 任务接上 | BLOCKED | 无 2 个校准任务/族，无从谈 B0 success ∈ [0.2, 0.8] 校准 |

结论：有 agent 可执行文件，但没有“能跑 Pilot 的 B0 臂”。

---

# 3. B1 Readiness

状态：**BLOCKED**

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| curated Skill 可创建 | PARTIAL | Codex 平台原生支持 SKILL.md/skill 目录，但仓库内无任何 skill 资产或创建流程 |
| Skill freeze | BLOCKED | 无 freeze（不可变快照）机制 |
| Skill invoke / 注入 | BLOCKED | 无“skill 目录发现/注入”harness |
| human creation cost 可记录 | BLOCKED | 无 human minutes 记录器；无 B1 人时入口 |
| 3 train → 1 skill 形成周期 | BLOCKED | 无 train task fixtures；且 Pilot 文本用 2 个校准 formation tasks，与 §6 冻结的 3-task formation unit 需要先裁决（见 §11 P1） |

结论：平台能力存在，实验机制为零。

---

# 4. B2 Readiness

状态：**BLOCKED**

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| 固定 LLM input（Bundle/trajectory） | BLOCKED | 无 Artifact Builder，无 Bundle 产出；rollout JSONL 只在考古文档中分析过 |
| LLM 生成 1 个 skill 文档 + 示例 | BLOCKED | 无生成器 / 固定 prompt 模板 |
| skill freeze | BLOCKED | 同 B1 |
| 与 B3 共享同一 generation input | BLOCKED | Pilot 目标 4 无法验证，因为输入不存在 |

结论：B2 是 B3 的主对照之一，但目前只有设计文字。

---

# 5. B3 Readiness

状态：**BLOCKED — implementation blocker**

存在的最小闭环：

```text
Bundle → Capabilityizer → deterministic validation → evaluation → promote/reject → invoke
```

**不存在。** 明确标记：**implementation blocker**。

| 组件 | 状态 | 现状 |
|---|---|---|
| VerifiedTaskArtifactBundle 契约 | READY | P0 FROZEN（字段、禁止项、digest、validation rules 已冻结） |
| Artifact Builder | BLOCKED | 未实现；runtime-capture 考古已定位 hook（`run_sampling_request` 尾部），但无代码 |
| Capabilityizer | BLOCKED | 未实现 |
| Validator（S0/S1） | BLOCKED | 未实现；依赖独立 sandbox |
| Evaluator（golden + Novel Input + regression + independent reuse） | BLOCKED | 未实现 |
| Promotion gate（0/1） | BLOCKED | 未实现 |
| Registry + Discovery | BLOCKED | 未实现（无 SQLite、无 bundle store） |
| Runtime invoke / revoke | BLOCKED | 未实现；Docker 可用但无沙箱策略/镜像锁定 |

注：P0 契约冻结与考古完成是设计层面的 READY，不等于可运行闭环。

---

# 6. Runtime Readiness

状态：**BLOCKED**

| 检查项 | 状态 | 缺口 |
|---|---|---|
| same model | BLOCKED | 无模型锁定；Ollama 未运行；未验证任何端点 |
| same model config | BLOCKED | 无 config 文件 / 锁定机制 |
| same sandbox | PARTIAL | Docker daemon 29.1.3 可用、有 base image，但无 sandbox policy / image 锁定 |
| same timeout | BLOCKED | 设计要求 ≤30 min，无执行器实现 |
| same output limits | BLOCKED | 无输出截断配置 |
| same tool limits | BLOCKED | 无工具白名单/数量限制配置 |
| fresh environment | BLOCKED | 无 per-run 容器/workspace 创建 |
| reproducible seed/config | BLOCKED | 无配置存储；LLM seed/温度未定义 |

结论：runtime 意图在设计中，机制全部缺失。

---

# 7. Oracle Readiness

状态：**BLOCKED**（无任何任务实例）

仓库中不存在具体 task、fixture、expected output 或 check 命令。因此按族：

| 族 | 状态 | 说明 |
|---|---|---|
| F+（CSV → 清洗 → 统计报告） | BLOCKED | 无 fixture/expected output；oracle 模式可行（exit code + 文件 diff/check），但需任务实现后校准 |
| F−（仓库特定迁移缺陷修复） | BLOCKED | 无 repo/schema fixture；oracle 依赖每任务的 check 命令，契约漂移本身是被测特征 |
| F0（Markdown → HTML 报告） | BLOCKED | 无 fixture/expected output；声明式转换 oracle 较直接，但仍需定义 |

一旦任务存在，所有族都应先走 **ORACLE_REVIEW_REQUIRED**：

- F+：报告非确定性（时间戳、行序）需 review 比较语义。
- F−：每任务 check 命令需 review 是否真的 deterministic。
- F0：HTML 输出变异范围需 review。

当前 **READY 的任务为 0 个**。

---

# 8. Cost Instrumentation

状态：**BLOCKED**（设计 PARTIAL）

| 指标 | 状态 | 现状 |
|---|---|---|
| tokens | BLOCKED | 设计要求记录，无采集实现；rollout/runtime 来源未接入 harness |
| tool calls | BLOCKED | 同上 |
| latency | PARTIAL | 考古确认 `ExecCommandBegin/End` 含 duration（EVENT_CAPTURE，opt-in），但未实现采集 |
| human minutes | BLOCKED | 无记录器 |
| sandbox minutes | BLOCKED | 无 sandbox 生命周期计费 |
| creation cost | BLOCKED | 无 formation episode 成本汇总 |
| validation cost | BLOCKED | B3 validate/evaluate 未实现 |
| maintenance cost | BLOCKED | 无编辑/revoke/revalidate 事件记录 |
| wrong-capability cost | BLOCKED | 无错误 invoke/清理/修复记录 |
| V_low / V_mid / V_high | BLOCKED | 设计要求 pre-register，但仓库没有注册任何 V 值 |

结论：指标公式已冻结，instrumentation 为零；V sensitivity 目前无法应用。

---

# 9. Data Capture

状态：**BLOCKED**

不存在统一 run record：无 schema、无存储（JSONL/SQLite）、无写入器。设计 §7 只列了字段要求。

最小需要增加的 experiment harness（非代码，仅清单）：

1. **Run orchestrator**：按 arm/run 启动 agent、注入任务、控制 timeout/output limits、记录顺序。
2. **Task manifest loader**：加载冻结的 fixture/task/oracle 清单。
3. **Run record schema + writer**：覆盖 run_id、task_id、arm、formation_id、model、seed、sandbox、result、oracle、cost、skill/capability usage、regression、trap、false promotion。
4. **Oracle runner**：执行 check/比较，产出 PASS/FAIL。
5. **Cost collector**：tokens、tool calls、latency、human minutes、sandbox minutes、formation/validation/maintenance/wrong-capability 成本。
6. **Sandbox launcher**：每 run 新建容器、关闭网络、挂载 fixture、输出目录可写。

---

# 10. Reproducibility

状态：**BLOCKED**

| 检查项 | 状态 | 现状 |
|---|---|---|
| fresh sandbox | PARTIAL | Docker 可用，无 per-run 编排 |
| no network | BLOCKED | 无网络关闭策略；任务 fixture 也不存在 |
| no secrets | PARTIAL | 仓库无 secret；无 secret-scan gate（契约只允许 `not_scanned + gap`） |
| no live workspace | BLOCKED | 无 fixture 快照/挂载机制 |
| fixed fixtures | BLOCKED | 无 |
| immutable task manifest | BLOCKED | 无 manifest 文件与校验 |
| deterministic oracle | BLOCKED | 无 |
| random order recorded | BLOCKED | 无 order/seed 记录 |

---

# 11. Blocking Dependencies

## P0（没有这些，Pilot 一行都跑不了）

1. **Experiment harness / orchestrator**：24 runs 的启动、固定配置注入、顺序/随机记录、结果回收。
2. **Pilot task fixtures + immutable manifest + deterministic oracles**：3 族 × 2 校准任务；每任务有输入、expected output、check 命令。
3. **B3 最小 pipeline 实现（implementation blocker）**：Artifact Builder → Capabilityizer → Validator → Evaluator → promote/reject → Registry → sandbox invoke。B2 的固定 generation input 也依赖 Artifact Builder。
4. **Run record + cost instrumentation**：统一 schema、存储、采集器。

## P1（Pilot 质量/可比性依赖）

5. **Model / config 锁定**：选择并验证同一推理端点与模型（Ollama 当前未运行），锁定 model config、timeout、output/tool limits。
6. **B1 skill 机制**：curated skill 的创建、freeze、注入、invoke，以及 human minutes 记录。
7. **Sandbox isolation policy**：Docker 上的网络关闭、只读 artifact、可写输出目录、资源限制，并锁定 base image。
8. **Pilot formation episode 规模裁决**：Pilot 文本为“2 个校准 formation tasks/族”，§6 冻结 formation unit 为“3 train → 1 artifact”。运行前需明确 Pilot 的 B1/B2/B3 formation 用 2 还是 3 个任务（仅裁决，不改设计）。
9. **预注册 V_low / V_mid / V_high 与 δ_NV 档位值**：Pilot 目标 8 要求验证 sensitivity 可运行，但当前无值。

## P2（防线完整性）

10. **Secret-scan gate**：写 Bundle 前的扫描（当前只能 `not_scanned + gap`）。
11. **Randomization / repeated-runs 工具**：随机顺序记录；held-out/trap 波动 >20% 时 ≤3 次独立重复的执行与记录机制。

---

# 12. Minimal Implementation Before Pilot

按 P0 顺序的最小集合（不包含主实验功能）：

| # | 最小件 | 覆盖 blocker |
|---|---|---|
| 1 | Run orchestrator（4 arm × 每 run fresh 环境） | P0-1 |
| 2 | 3 族 × 2 任务的 fixture + oracle + immutable manifest | P0-2 |
| 3 | Artifact Builder（产出 Bundle 供 B2/B3 共享输入） | P0-3 |
| 4 | B3：Capabilityizer → Validator → Evaluator → promote → Registry → invoke | P0-3 |
| 5 | Run record writer + cost collector | P0-4 |
| 6 | Model/config 锁定 + B1 skill freeze/invoke + human-cost 记录 | P1-5 / P1-6 |
| 7 | Docker sandbox policy（network off、只读/可写边界、limits） | P1-7 |

---

**Pilot Readiness = NOT READY**

P0 阻塞项：experiment harness、task fixtures/oracles/manifest、B3（含 Builder）最小 pipeline、run record + cost instrumentation。

P1 阻塞项：model/config 锁定、B1 skill 机制与 human-cost、sandbox isolation policy、Pilot formation 规模裁决、V/δ 预注册值。

P2 阻塞项：secret-scan gate、randomization/repeated-runs 工具。
