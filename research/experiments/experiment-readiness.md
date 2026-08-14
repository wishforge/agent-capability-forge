# Capability Forge vs Skill-only — 24-run Pilot Readiness Review

- 状态：READINESS SNAPSHOT（已运行 F+ rehearsal；未启动正式 Pilot、未修改实验设计、未修改 `src`）
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

**Pilot Readiness = READY（Formal Pilot = NOT STARTED）。**

历史：本文件早前快照结论为 NOT READY，依据是“设计 + 考古 + 契约”仓库状态（无 harness / fixture /
oracle / run record）。该结论已过时；相关 BLOCKED 项在下方标记为 resolved，不再删除历史事实。

当前 `pilot/` 已含可执行 harness 与 state 产物（`src/` 仍未修改）：B0/B1/B2/B3 均 READY，
Treatment Attribution Gate 与 F+ Rehearsal Gate 均 PASS。正式 24-run Pilot 尚未启动。

已经具备的（READY）：

- 实验设计冻结（`capability-forge-vs-skill.md` v0.2）。
- VerifiedTaskArtifactBundle v0 契约冻结（P0 FROZEN）。
- Runtime capture point 考古完成（Builder hook、EVENT_CAPTURE 通道、RUNTIME_CHANGE 清单）。
- B0：READY（`phase_future --arm b0`，treatment=none，与 formation 共用执行/记录路径）。
- B1：机制 READY、asset READY（human_minutes = 10）、freeze PASS、future rehearsal 2/2 PASS。
- B2：READY；B3：READY（原 implementation blocker 已 resolved）。
- Treatment Attribution Gate：PASS；F+ Rehearsal Gate：PASS（proofs 1-9 全部 PASS）。
- 容器运行时可用：Docker daemon 29.1.3 在运行，本机存在 `python:3.12-slim`、`debian:bookworm-slim`、`busybox` 等可作 base image 的镜像。
- Agent CLI 存在：`codex` 0.144.4（`codex exec` 可用）；yusing/codex（658630b）源码 clone 在 `<tmp>/yusing-codex`，但未构建出可运行 binary。

仍待（NOT STARTED / 本次快照未声明变更）：

- **Formal Pilot = NOT STARTED**：未启动 24-run Pilot；按 Pilot Gate 流程单独放行。
- §6-§10（Runtime / Oracle / Cost / Data Capture / Reproducibility）未在本次声明中更新，保留早前快照内容。
- §11 中未标记 resolved 的 P1/P2 项（V/δ 预注册、sandbox isolation policy、secret-scan、randomization 等）按原样保留。

---

# 2. B0 Readiness

状态：**READY**（此前 PARTIAL/BLOCKED → resolved，2026-08-14）

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| Agent CLI 可调用 | READY | `/opt/homebrew/bin/codex`（0.144.4），`codex exec` 存在 |
| 可运行“Agent only”实验臂 | READY | resolved：`phase_future --arm b0` 已实现，treatment=none；与 formation 的 codex 路径共用同一执行/记录机制 |
| 模型可用 | READY | resolved：F+ rehearsal 经 codex 实际执行 10 条 run 记录，oracle 全部 PASS |
| 与 Pilot 任务接上 | READY | resolved：F+ 校准/未来任务实例与 oracle 已存在并跑通（golden t1/t2、fplus-future-1/2） |

结论：B0 臂机制与 F+ 执行路径 READY；正式 Pilot 未启动。

---

# 3. B1 Readiness

状态：**READY**（此前 BLOCKED → resolved，2026-08-14）

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| curated Skill 可创建 | READY | resolved（此前 PARTIAL/BLOCKED）：`pilot/skills/curated/F+/csv-clean-statistical-report/SKILL.md` 与 `pilot/skills/frozen/B1/...` 已存在 |
| Skill freeze | PASS | resolved（此前 BLOCKED）：`phase_b1_freeze` → `pilot/state/b1_skill_ref.json`，digest `sha256:63d2119423...f0f49`，frozen_at 2026-08-14T13:04:34Z |
| Skill invoke / 注入 | READY | resolved（此前 BLOCKED）：`phase_future --arm b1` 走确定性注入 + attribution gate；B1 future rehearsal 2/2 VALID |
| human creation cost 可记录 | READY | resolved（此前 BLOCKED）：`pilot/b1_curated_skill.json` 与 `b1_readiness.json` 记录 `human_minutes = 10` |
| 3 train → 1 skill 形成周期 | READY | resolved（此前 BLOCKED）：F+ rehearsal 按 Pilot 设计跑 2 个校准 formation tasks（4 formation runs）→ 1 个 frozen skill；Main-study 的 3-task formation unit 保持设计冻结（仅裁决，未改设计） |

结论：**B1 asset blocker = RESOLVED**；机制与资产均 READY，human cost = 10 minutes。

---

# 4. B2 Readiness

状态：**READY**（此前 BLOCKED → resolved，2026-08-14）

| 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|
| 固定 LLM input（Bundle/trajectory） | READY | resolved（此前 BLOCKED）：`pilot/state/bundle_store/bundles/` 4 个 sealed bundles，digest equality 成立（proof 3） |
| LLM 生成 1 个 skill 文档 + 示例 | READY | resolved（此前 BLOCKED）：`pilot/state/skill_ref.json` + `pilot/skills/frozen/F+/csv-clean-statistical-report/` 已生成 |
| skill freeze | PASS | resolved（此前 BLOCKED）：同 B1，frozen skill digest `sha256:405faf4d...` |
| 与 B3 共享同一 generation input | READY | resolved（此前 BLOCKED）：generation_input digest + 4 bundle refs 出现在全部 formation records（proof 3） |

结论：B2 READY；F+ future 2/2 oracle PASS 且 treatment VALID。

---

# 5. B3 Readiness

状态：**READY**（此前 implementation blocker → resolved，2026-08-14）

存在的最小闭环：

```text
Bundle → Capabilityizer → deterministic validation → evaluation → promote → Registry → sandbox invoke
```

已由 F+ rehearsal 跑通（`fplus_rehearsal_gate.json` proofs 1-9 全部 PASS）。

| 组件 | 状态 | 现状 |
|---|---|---|
| VerifiedTaskArtifactBundle 契约 | READY | P0 FROZEN（字段、禁止项、digest、validation rules 已冻结） |
| Artifact Builder | READY | resolved：`bundle_store/bundles/` 4 个 sealed bundles（artifact snapshot + rollout + digest） |
| Capabilityizer | READY | resolved：`pilot/state/llm_proposal.json` + `candidates/F+/csv-clean-statistical-report/manifest.json` 已产出 |
| Validator（S0/S1） | READY | resolved：`candidates/.../validation.json` PASS（sandbox 内执行） |
| Evaluator（golden + Novel Input + regression + independent reuse） | READY | resolved：`evaluation.json` PASS；novel input 结果见 `sandbox_out/evaluation/` |
| Promotion gate（0/1） | READY | resolved：candidate 已 promote 至 `pilot/state/registry/F+/csv-clean-statistical-report.json` |
| Registry + Discovery | READY | resolved：registry entry + artifact 已存在 |
| Runtime invoke / revoke | READY（invoke）/ 未覆盖（revoke） | resolved：sandbox invoke exit_code=0（`cbx-...` sandbox_id）；revoke 未在 F+ rehearsal 覆盖（历史缺口保留） |

注：P0 契约与考古未变；契约冻结已推进到可运行闭环，P0 Bundle Contract 本身仍未修改。

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

## P0（早期快照：没有这些，Pilot 一行都跑不了；2026-08-14 已全部 RESOLVED）

1. **Experiment harness / orchestrator**：24 runs 的启动、固定配置注入、顺序/随机记录、结果回收。→ **RESOLVED**：`pilot/harness.py` 已实现；`pilot/state/run_records.jsonl` 含 10 条完整记录（4 formation + 2 B1 + 2 B2 + 2 B3 future）。
2. **Pilot task fixtures + immutable manifest + deterministic oracles**：3 族 × 2 校准任务；每任务有输入、expected output、check 命令。→ **RESOLVED（F+ 范围）**：golden t1/t2 + fplus-future-1/2 已实例化，oracle 全部 PASS 且 stable；F−/F0 未在本次声明范围。
3. **B3 最小 pipeline 实现（implementation blocker）**：Artifact Builder → Capabilityizer → Validator → Evaluator → promote/reject → Registry → sandbox invoke。B2 的固定 generation input 也依赖 Artifact Builder。→ **RESOLVED**：F+ rehearsal proofs 1-9 全部 PASS。
4. **Run record + cost instrumentation**：统一 schema、存储、采集器。→ **RESOLVED**：`run_records.jsonl`、`cost.json`、`cost_events.jsonl`、`nv_report.json` 已产出。

## P1（Pilot 质量/可比性依赖）

5. **Model / config 锁定**：选择并验证同一推理端点与模型（Ollama 当前未运行），锁定 model config、timeout、output/tool limits。
6. **B1 skill 机制**：curated skill 的创建、freeze、注入、invoke，以及 human minutes 记录。→ **RESOLVED**：机制 READY；asset READY（`pilot/b1_curated_skill.json`，human_minutes = 10）；freeze PASS；B1 future rehearsal 2/2 PASS；`pilot/state/b1_readiness.json` = READY。
7. **Sandbox isolation policy**：Docker 上的网络关闭、只读 artifact、可写输出目录、资源限制，并锁定 base image。
8. **Pilot formation episode 规模裁决**：Pilot 文本为“2 个校准 formation tasks/族”，§6 冻结 formation unit 为“3 train → 1 artifact”。运行前需明确 Pilot 的 B1/B2/B3 formation 用 2 还是 3 个任务（仅裁决，不改设计）。→ **RESOLVED（仅裁决，未改设计）**：Pilot 按设计用 2 个校准 tasks/族；F+ rehearsal 已按此跑通（4 formation runs → 1 frozen skill/candidate）；Main-study 的 3 train → 1 artifact 保持冻结。
9. **预注册 V_low / V_mid / V_high 与 δ_NV 档位值**：Pilot 目标 8 要求验证 sensitivity 可运行，但当前无值。

## P2（防线完整性）

10. **Secret-scan gate**：写 Bundle 前的扫描（当前只能 `not_scanned + gap`）。
11. **Randomization / repeated-runs 工具**：随机顺序记录；held-out/trap 波动 >20% 时 ≤3 次独立重复的执行与记录机制。

---

# 12. Minimal Implementation Before Pilot

按 P0 顺序的最小集合（不包含主实验功能）：

（以下为早前快照的“实施前”计划，保留作历史；1-6 在 F+ 范围内已实现并经 rehearsal 验证，7 未在本次声明中标记为 resolved。）

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

**Pilot Readiness = READY（Formal Pilot = NOT STARTED）**

历史：早前快照为 NOT READY；对应 BLOCKED 项已标记 resolved，事实保留。

P0 阻塞项：全部 RESOLVED（F+ rehearsal 验证）。

P1 阻塞项：B1 skill 机制与 human-cost 已 RESOLVED（human_minutes = 10）；Pilot formation 规模已裁决（2 个校准 tasks）；model/config 锁定、sandbox isolation policy、V/δ 预注册值按原快照保留。

P2 阻塞项：secret-scan gate、randomization/repeated-runs 工具。

---

# 13. Treatment Attribution Hardening（2026-08-14 更新）

状态：本更新解决“B2 oracle=PASS 但 skill_used=false”导致的 treatment attribution 缺口。
只修改 `pilot/`、`tests/` 与本文档；未修改 `docs/`、`src/forge/*`、P0 Bundle Contract、
Runtime Boundary Architecture Decision、`research/artifact-contract/*`。未运行 24/84 主实验。

## 13.1 run_record_v1：treatment 字段

每条 run record 新增 `treatment` 对象：

```json
{
  "type": "skill | capability | none",
  "used": true | false,
  "ref": "<skill name | capability_id>",
  "digest": "sha256:<digest>",
  "evidence": {"kind": "skill_injection | capability_invoke", "...": "..."}
}
```

- B0：`type=none, used=false`
- B1/B2：`type=skill`；used 由 harness 注入记录决定，不再依赖 agent 最后一条消息文本
- B3：`type=capability`；used=true 且必须携带 capability_id / digest / invoke evidence

## 13.2 机器可验证证据

- B2：harness 把 frozen skill 复制进 run 的 `CODEX_HOME/skills/<name>`，记录 mounted path、
  mounted digest、frozen digest 与 digest_match。证据为 harness-level injection record，确定性，
  不解析 Codex rollout。
- B3：记录 registry capability_id、artifact_dir、artifact digest、Docker sandbox_id、
  invoke command 与 invoke result（exit_code/stdout/stderr）。

## 13.3 Treatment Attribution Gate

- B1/B2：`used==true` AND `ref` 非空 AND `digest` 非空 AND skill injection evidence 存在且
  mounted digest == frozen digest == treatment.digest；否则 `INVALID_TREATMENT`。
- B3：`used==true` AND `capability_id` 非空 AND digest/version 非空 AND invoke evidence 存在
  （sandbox_id + capability_id 一致 + artifact digest 一致）；否则 `INVALID_TREATMENT`。
- 输出：`pilot/state/treatment_attribution_gate.json`；并作为 rehearsal gate proof 9。

## 13.4 Tests

`tests/test_minimal.py::TestTreatmentAttribution` 覆盖：
B2 缺 skill evidence、B2 skill_used=false、B3 缺 capability invoke、B3 wrong capability digest、
B0 treatment=none、valid B2、valid B3。当前 11 个 unit tests 全部通过。

## 13.5 B0/B1/B2/B3 Readiness（本轮实现后的状态）

- B0：READY。`phase_future --arm b0` 为 agent-only future task，treatment=none；与 formation
  的 codex 路径共用同一执行/记录机制。
- B1：机制 READY，资产 **RESOLVED（此前 BLOCKED → operator asset 已提供）**。`phase_b1_freeze`
  已实现 frozen curated skill → digest → `b1_skill_ref.json`；`phase_future --arm b1` 走与 B2
  相同的确定性注入 + attribution gate。`pilot/b1_curated_skill.json`（`name`、`family=F+`、
  `human_minutes=10`、`human_confirmed=true`）与 `pilot/skills/curated/F+/csv-clean-statistical-report/SKILL.md`
  已存在；`pilot/state/b1_readiness.json` = READY；B1 future rehearsal 2/2 PASS（treatment VALID）。
- B2：READY（此前 BLOCKED → resolved）。frozen skill + injection evidence + treatment VALID，F+ future 2/2 PASS。
- B3：READY（此前 implementation blocker → resolved）。formation → candidate → validation → evaluation →
  promotion → registry → sandbox invoke 闭环跑通，F+ future 2/2 PASS。

## 13.6 F+ Rehearsal 重跑结果

全新 `pilot/state`（旧 state 备份为 `pilot/state.pre-attribution-20260814`，未提交 Git）重跑：

- 4 formation runs：oracle 全部 PASS、stable
- B1 future runs（fplus-future-1/2）：oracle PASS，skill_used=true，treatment VALID
- B2 future runs（fplus-future-1/2）：oracle PASS，skill_used=true，treatment VALID
- B3 future runs（fplus-future-1/2）：oracle PASS，capability_used=capability_id，
  invoke result exit_code=0，treatment VALID
- `fplus_rehearsal_gate.json`：PASS，proofs 1-9 全部 PASS
- `treatment_attribution_gate.json`：PASS，blockers=[]

**Formal Pilot = NOT STARTED**。此前的“正式 Pilot 前需完成 B1 curated skill 输入”要求已满足
（B1 asset blocker = RESOLVED）；正式 Pilot 仍须按 Pilot Gate 流程单独放行，本次未启动。
