# Capability Forge vs Skill-only Pipeline — Hypothesis Validation / Experiment Design

状态：Design only（本轮不写 `src`、不实现 Capability Forge、不修改 `docs/capability-forge-mvp-spec.md` 的 P0 Contract、不改变任何现有架构决策）
版本：v0.2（Final Correction）
日期：2026-08-14

术语沿用 [capability-forge-mvp-spec.md](../../docs/capability-forge-mvp-spec.md)：VerifiedTaskArtifactBundle、CapabilityCandidate、S0-S4、CapabilityEvaluation、Novel Input Test、independent reuse。

---

## 0. 研究问题

> Capability Forge 相比成熟 Skill-only pipeline，是否存在**可测量**的增量价值？

"增量价值"操作化为：在相同任务族、相同观测窗口内，Net Value 与未来任务成功率同时更好（或等价且成本更低）。实验必须是**可证伪**的：所有阈值在运行前注册，观测结果直接映射到唯一结论。

## 1. Baselines

| 臂 | 定义 | 形成机制 | 复用机制 |
|---|---|---|---|
| B0 | Agent only | 无 | 无；每个任务从零解决 |
| B1 | Agent + curated Skill | 3 个 train 任务（1 formation episode）→ 人类专家写 **1 个** skill，**frozen**（计 human cost） | skill 目录发现/注入 |
| B2 | Agent + generated Skill | 3 个 train 的 Bundle/trajectory（1 formation episode）→ LLM 直接生成 **1 个** skill 文档 + 示例；无确定性验证、无沙箱评估、无 promotion gate | skill 目录发现/注入 |
| B3 | Agent + Execution-derived Capability Forge | 3 个 train Bundles → 一次 Capabilityizer proposal → **1 个 Candidate** → Validator（S0/S1）→ Evaluator（golden + Novel Input Test + regression + independent reuse）→ 0/1 promote → Registry → invoke/revoke | Registry discovery + 沙箱 invoke |

B2 与 B3 共享同一个"从执行派生"的 LLM 生成输入（同一 Bundle/trajectory）；系统差是 governed / validated pipeline：deterministic validation / evaluation / promotion / registry / revoke。因此 **B2 vs B3 是 H2 的主对照**。

**B3 的 Registry / Revoke 保留，但解释范围受限**：它们是真实 Capability Forge pipeline 的组成部分，本实验不是"证明 Registry / Revoke 的独立商业价值"。本实验主要比较 **B2（naive execution-derived self-generation）** vs **B3（governed / validated execution-derived formation pipeline）**。Registry / Revoke 在本实验中的作用：提供真实 promotion / discovery / invoke 生命周期、记录治理成本、产生必要的 maintenance / revoke / false-promotion observations。由于没有 `B3_without_registry` 或 `B3_without_revoke` 的 factorial ablation，结果不得解释为"Registry 单独创造了 X% 的价值"。

## 2. Hypotheses

三个维度拆成明确角色：

- **Primary economic endpoint：Net Value（NV）**
- **Reliability gate：future-task success**
- **Safety / negative-transfer gate：trap / regression**

**Forge Worth Doing = Economic Superiority AND Reliability Non-Inferiority vs Best Skill AND Safety Non-Inferiority vs B0。**

定义（`best_skill` = max(B1, B2) 对应指标）：

- **Economic Superiority**：`NV(B3) − best_skill_NV > δ_NV`
- **Reliability Non-Inferiority vs Best Skill**：`future-task success(B3) ≥ best_skill_success − 5pp`
- **Safety Non-Inferiority vs B0**：trap/regression 不劣于 B0 超过 5pp

非补偿规则（对 H0 / H1 / 所有 decision rules 生效）：

1. NV 不自动补偿 reliability loss。
2. 高 NV 不能购买显著 success degradation。
3. 任何 reliability / safety gate failure，都不能仅靠经济收益翻转为 Forge PASS。

- **H0：Skill-only 足够。** 非 Forge Worth Doing：`NV(B3) − best_skill_NV ≤ δ_NV`，且 B3 future-task success 与最佳 skill 臂相差 ≤ 5pp（Reliability vs Best Skill 非劣），且 trap/regression 不劣于 B0 超过 5pp（Safety vs B0 非劣）。
- **H1：Execution-derived Capability Formation 有显著增量价值。** Economic Superiority AND Reliability Non-Inferiority vs Best Skill AND Safety Non-Inferiority vs B0 同时成立。
- **H2：Governed / validated formation pipeline 优于 naive execution-derived self-generation。** 两层判定：
  - **第一层（改善证据）**：B3 vs B2 在以下 improvement metrics 中至少两项达到阈值：valid reuse rate（≥ +20pp）、wrong-capability cost（≤ −50%）、future-task success（≥ +5pp）、Net Value（≥ +δ_NV）。
  - **第二层（安全闸门，必须全部通过）**：Reliability Non-Inferiority vs B2：`future-task success(B3) ≥ future-task success(B2) − 5pp`；Safety Non-Inferiority vs B2：trap/regression(B3) 不劣于 B2 超过 5pp。
  - 第一层满足但任一安全闸门失败 → **H2 = FAIL**。

  H2 只裁决 B3 vs B2 的 governance / validation pipeline 本身是否有增量价值；B3 相比最佳 Skill baseline（B1/B2）的业务增量价值由 H1 裁决，二者不混用。

## 3. Task Population

宇宙：可在本地沙箱完成、有确定性判定 oracle 的 agent 任务（无网络、无 secret、无 live-workspace 依赖，单次 ≤ 30 min）。

抽样为**构造性分层**，不是随机样本——三个层对应三种必须裁决的场景：

| 层 | 特征 | 示例族 |
|---|---|---|
| F+ 正例族 | 高复用、稳定可执行契约 | "CSV → 清洗规则 → 统计报告"：同族共享 input/output schema，每任务仅数据/参数不同 |
| F− 负例族 | 低复用、高方差或任务私有状态 | "修复本仓库特定迁移缺陷 / 一次 incident"：每次 repo/schema 不同，形成的"能力"容易变成任务私有快照 |
| F0 skill 足够族 | 声明式、指令可完全覆盖 | "按规则把 Markdown 转成 HTML 报告"：无需要沙箱调用的可执行 artifact |

## 4. Task Selection Criteria

1. 确定性 oracle：exit code + 输出文件/diff 比对，或 check 命令 exit 0。
2. Pilot 难度 / oracle / 可执行性校准（见 Pilot 节）：Pilot 在每族 2 个**校准 formation task 实例**上要求 B0 success ∈ [0.2, 0.8]（避免地板/天花板效应）。此规则只用于 Pilot 校准；Pilot 成功率不得用于主实验效应估计、主实验结果、第三个 formation task 的删除/替换，或 held-out / trap 的调参。
3. 契约稳定性：F+ / F0 同族共享 input/output schema；F− 的契约漂移或任务私有状态本身就是被测特征。
4. 沙箱可行性：无网络 / secret / live workspace 依赖；单次 timeout ≤ 30 min。
5. 可形成性：完成 3 个 train 任务（1 formation episode）后尝试生成 1 个 skill/capability；F− 允许形成失败——失败本身是观测点。
6. 复用频率分层：F+ / F0 设计 r ≥ 3；F− 设计 r ≈ 1。
7. Trap 设计：每个族有 1 个与另一族表面相似、但契约不同的任务（触发错误复用，测 wrong-capability cost）。

## 5. Repeatability / Reuse Frequency

- `r_arm` = 观测窗口内该臂实际遇到的可应用未来任务数（记录值，不预设）。
- `reuse_rate` = 实际使用 skill/capability 的可应用任务数 / 可应用任务数。
- `valid_reuse_rate` = 使用且成功的任务数 / 使用任务数。
- 收支平衡条件：`r ≥ 1 + (formation + validation + maintenance) / per-reuse-savings`。实验逐族记录实际比值，不做假设。

## 6. Train / Held-out Split

| 族 | formation（train） | in-family held-out | cross-family trap |
|---|---|---|---|
| F+ | 3 | 3 | 1 |
| F− | 3 | 3 | 1 |
| F0 | 3 | 3 | 1 |
| 合计 | 9 | 9 | 3 |

- 唯一任务共 **21** 个；held-out 与 trap 绝不进入 formation。
- **Formation unit（冻结）**：每个 Task Family = 3 formation tasks → **1 formation episode** → 1 unified artifact/experience input → **1 Skill / 1 CapabilityCandidate**。所有 formation cost 按 1 个 formation episode 计算。
- **Future tasks（冻结）**：每族固定 4 个 unique future tasks = 3 unique in-family held-out + 1 unique cross-family trap。**unique tasks ≠ observations**：如需 ≥ 6 observations，只对已冻结的 4 个任务做 independent repeated runs，不得新增或修改 task definition。
- **Main-study task manifest（Pilot PASS 后正式锁定）**：每族 3 formation tasks + 3 in-family held-out + 1 cross-family trap = 21 unique tasks。Pilot 的 2 个 formation tasks 为"校准用途"，与 Main-study formation tasks（"正式实验用途"）分离，详见 Pilot 节。
- B1：人类在 3 个 train 完成后、看任何 held-out 前写 1 个 curated skill 并 freeze；时间计入 formation cost。
- B2：LLM 从 3 个 train 的 Bundle/trajectory（同一 formation episode 输入）生成 1 个 skill；无验证 gate。
- B3：3 个 train Bundles → 一次 Capabilityizer proposal → 1 个 Candidate；仅 evaluation PASS 且用户确认者 promote 0/1；失败 / revoke 全部计入成本与 maintenance。
- B0：无 formation。

## 7. Evaluation Protocol

1. **Pre-registration**：运行前锁定 families / tasks / oracles / budgets / δ；禁止用 held-out 调参。
2. **运行**：4 臂交错或随机顺序；相同模型、相同环境、相同 timeout / output limits；每次 fresh sandbox。
3. **每 run 记录**：outcome、tokens、tool calls、latency、human interventions、是否发现并使用了 skill/capability、invoke 结果。
4. **判定**：deterministic oracle；人工 observer 只记录、不干预。
5. **变异性**：held-out / trap 任务若 pilot 显示成功率波动 > 20%，对已冻结任务做 independent repeated runs 至多 3 次，取多数/均值（不新增/修改 task definition）。
6. **时序**：每族 formation 完成后才运行该族 held-out 与对应 trap。

## 8. Success Metrics

| 指标 | 定义 / 测量 |
|---|---|
| first-task success rate | 每族第 1 个任务（formation 前）成功率；确认 4 臂起点可比 |
| future-task success rate | in-family held-out 成功率（formation 后、能力可用时） |
| held-out task success | cross-family trap 成功率（含未使用能力时 = 普通成功率） |
| token cost | 每任务平均 token（输入 + 输出）；formation 成本单独计 |
| tool calls | 每任务平均 tool call 数；另计每个成功任务的 tool call 数 |
| latency | 每任务 wall-clock p50 / p90 |
| capability/skill formation cost | 每个 formation episode（3 train → 1 artifact）的 LLM tokens + human time + 计算（tokens×价 + 人时×价 + 沙箱分钟×价） |
| validation cost | B3：deterministic validate + evaluate 运行（含 failed candidate）；B2：0（无验证）；B1：skill review 人时 |
| maintenance cost | 窗口内 skill 编辑 / re-forge / revoke / revalidation 的次数 × 成本 |
| human intervention | 每 formation 与每任务的人工动作数（确认、manifest 编辑、审批、修复），分类型计数 |
| negative transfer / regression | trap success vs B0 trap success；同族 regression = 使用能力后失败但 B0 能完成的任务占比 |
| false promotion rate | 被 promote 的 Capability 中，在 future held-out / trap 中造成 harmful reuse 的比例；至少记录 promoted count、harmful promoted count、false promotion rate |
| reuse rate / valid reuse rate | 见 §5 |

False Promotion Rate 只统计被 promote 后造成 harmful reuse（错误 invoke / 结果劣于 B0 / 产生额外清理修复成本）的 Capability，与 ordinary regression（B0 同样失败或与 promoted 能力无关的失败）分开记录，不混为一谈。

## 9. Net Value

按臂、按族、按观测窗口计算；聚合时跨族求和：

```
TaskValue_arm(task) = V(task) × 1[success] − execution_cost_arm(task)
NV_arm = Σ_task (TaskValue_arm − TaskValue_B0) − formation_cost − validation_cost − maintenance_cost − wrong_capability_cost
```

- `V(task)` = business_value_if_success，每族在实验开始前 pre-register（见下方 V sensitivity）；成功时计入，失败计 0。
- `execution_cost` = tokens×p_token + human_min×p_human + sandbox_min×p_sandbox；原始指标（tokens、latency、tool calls、human minutes）始终报告，USD 折算只是汇总层。
- `formation_cost` = 1 个 formation episode（3 train → 1 artifact）的创建成本：B1 含人类写 skill，B2 含 LLM 生成，B3 含一次 Capabilityizer proposal + Candidate 成本。
- `validation_cost` = B3：deterministic validate + evaluate（含 failed candidate）；B2：0（无验证）；B1：skill review 人时。
- `wrong_capability_cost` = 错误 invoke / 清理 / 修复 / 回滚等直接成本；成功/失败的价值差已由 `TaskValue` delta 覆盖，不重复计 V 惩罚。
- Task-level delta 支持：**B0 FAIL / B3 PASS → 正收益**；**B0 PASS / B3 FAIL → 负收益**。
- 成功率同时作为独立 decision gate（§11），不因 NV 内含价值差而取消双门槛。
- **Non-compensation**：NV 不自动补偿 reliability loss；高 NV 不能购买显著 success degradation；任何 reliability / safety gate failure 都不能仅靠经济收益翻转为 Forge PASS。

### V sensitivity（必须）

每个 task family 在实验开始前 pre-register `V_low` / `V_mid` / `V_high`（或一个 frozen V + sensitivity analysis）。结论必须在 low / mid / high V 下分别报告，验证结论是否依赖 business-value 假设；若结论翻转或进入等价带，标记为 value-sensitive，不得声称 "Forge 已被证明"。

## 10. Cases

| Case | 层 | 预期 | 什么观测会推翻预期 |
|---|---|---|---|
| Positive | F+ | B3 的 NV 与 future success 均胜出 | 即使高复用、稳定契约族，B3 仍不优于最佳 skill 臂 → Forge 增量价值不存在 |
| Negative | F− | formation 失败或 NV(B3) ≤ 0，wrong-capability cost 可见 | F− 上 B3 仍显著胜出 → 假设比预期更强 |
| Skill is enough | F0 | B1 ≈ B3，H0 成立 | F0 上 B3 显著更优 → Forge 价值超出可执行能力本身 |

每个族独立裁决；最终结论按聚合 + 分层两个粒度给出。

### Registry / Revoke 解释范围

84-run 主实验验证的是完整 governed formation pipeline 的综合处理效果，不识别 Registry 或 Revoke 的独立因果贡献。（"The 84-run main study tests the governed formation pipeline as a composite treatment; it does not identify the isolated causal contribution of Registry or Revoke."）实验没有设计 `B3_without_registry` 或 `B3_without_revoke` 的 factorial ablation，因此结果不得解释为"Registry 单独创造了 X% 的价值"。

## 11. Decision Rules

阈值（pre-registered）：`δ_NV = 10% × TCO_best`（最佳 skill 臂在窗口内的总拥有成本，aggregate），并做 `δ = 5% / 10% / 20%` sensitivity；成功率等价带 ±5pp；trap 劣化容忍 ≤ 5pp vs B0；小样本下同时要求效应量达阈值（p 值仅作报告，不单独作裁决）。

三个维度按角色分别裁决（与 §2 一致）：

- **Economic Superiority**：`NV(B3) − best_skill_NV > δ_NV`
- **Reliability Non-Inferiority vs Best Skill**：`future-task success(B3) ≥ best_skill_success − 5pp`
- **Safety Non-Inferiority vs B0**：trap/regression 不劣于 B0 超过 5pp

**Forge Worth Doing = 三者同时成立**。NV 不自动补偿 reliability loss；高 NV 不能购买显著 success degradation；任何 reliability / safety gate failure 都不能仅靠经济收益翻转为 Forge PASS。

**Decision Robustness（δ_NV sensitivity）**：分别用 `δ_NV = 5% / 10% / 20%` 裁决；三档结论一致才报告 robust。若不同 → 标记为 **threshold-sensitive**，不得声称 "Forge 已被证明"，只报告各档结论与翻转点。

| 观测条件 | 结论 |
|---|---|
| Economic Superiority AND Reliability Non-Inferiority vs Best Skill AND Safety Non-Inferiority vs B0 | **Forge 值得做**（accept H1） |
| 非 Economic Superiority（`NV(B3) − best_skill_NV ≤ δ_NV`），且 Reliability vs Best Skill / Safety vs B0 均非劣 | **Skill 已经足够**（accept H0） |
| 非 Forge Worth Doing，但 H2 成立（B3 vs B2：至少两项 improvement metrics 达到阈值——valid reuse ≥ +20pp、wrong-cap cost ≤ −50%、future success ≥ +5pp、NV ≥ +δ_NV——且 Reliability vs B2 / Safety vs B2 均非劣），且 B3 形成+验证成本 > B2 | **Forge 只做 Skill Generator / Evaluator**：保留执行→生成→确定性评估，砍掉 runtime/registry invoke 侧 |
| 仅 F+ 满足 Forge Worth Doing，F−/F0 不满足 | Forge 值得做，但**只对高复用、可执行契约的任务族启用** |

## Pilot（主实验前置阶段）

**24 runs** = 3 families × 4 arms × 2 校准 formation tasks。

Pilot 定位：**Pilot 难度 / oracle / 可执行性校准**。Pilot 的 2 个 formation tasks 与 Main-study 的 3 个 formation tasks 是"校准用途" vs "正式实验用途"。Pilot 成功率**不得**用于：
- 主实验效应估计或主实验结果；
- 第三个 formation task 的删除或替换；
- held-out / trap 的调参。

目标：
1. 验证 oracle 稳定
2. 验证任务难度（B0 success ∈ [0.2, 0.8]）
3. 验证 B1 human cost 可记录
4. 验证 B2/B3 共享同一 generation input
5. 验证 Bundle 足够支撑 B3
6. 验证 trap 能触发错误复用
7. 验证 NV 可计算
8. 验证 V / δ_NV sensitivity 可运行

Pilot 结果**不进入主实验结论**。

**Pilot PASS 后**：正式锁定 main-study task manifest（每族 3 formation + 3 in-family held-out + 1 cross-family trap = 21 unique tasks），此后不得修改主实验任务，除非 Pilot 发现：
- oracle 不确定；
- task 无法执行；
- task 不满足预注册约束。

若发生上述结构性问题：记录为 **Pilot Design Failure**，重新生成并重新 Pilot。

## 12. 最小实验规模、任务数量、观察周期

- **任务族**：3（F+ / F− / F0）。
- **唯一任务数**：21 unique tasks = 每族（3 formation + 3 in-family held-out）+ 3 cross-family trap；每族 4 个 unique future tasks（3 in-family held-out + 1 trap）。
- **运行数**：4 臂 × 21 = **84 runs（主实验，Pilot Gate PASS 后）**；held-out/trap 波动 > 20% 时对已冻结任务做 independent repeated runs，至多 3 次 → 至多 120 runs（不得新增/修改 task definition）。
- **Formation 周期**：9 次 formation episodes（3 族 × 3 train → 1 episode）；另有 Pilot 24 runs（3 families × 4 arms × 2 校准 formation tasks；不计入主实验、不计入 21 unique tasks）。
- **最小观察周期**：≥ **2 周**；每族 4 个 unique future tasks。如需 ≥ 6 observations，仅对这 4 个冻结任务做 independent repeated runs（unique tasks ≠ observations）；窗口内若出现维护/revoke 事件，延伸至事件闭环，最长 6 周。

## 13. 最终 Decision Rule

1. 若聚合满足 §11 第一行 → 实现 Forge（继续 P0-P5），并把 F+ 作为首发验证族。
2. 若聚合满足第二行 → 停止 Forge 主线，维持 skill-only pipeline。
3. 若聚合满足第三行 → 把 Forge 收窄为 Skill Generator / Evaluator，不建 runtime/registry。
4. 若仅分层成立 → 按族裁剪启用范围，不全局推广。

最小实验是 **go/no-go 决策门槛**，不是统计意义上的泛化证明（与 spec 的 "Novel Input Test ≠ Statistical Generalization Proof" 一致）。若结果落在等价带内需要更高置信度，再扩展为 5 族 ×（5 train + 10 transfer + 2 trap）/ 臂。

第 3 行的 "H2 成立" 指两层判定全部通过：B3 vs B2 至少两项 improvement metrics 达标，且 Reliability vs B2 / Safety vs B2 均非劣；任一安全闸门失败 → H2 = FAIL。

## Pilot Gate

- **Pilot PASS** → 正式锁定 main-study task manifest（families / tasks / oracles / measurement / V 档 / δ 档）→ 执行 **84-run main study**。
- **Pilot FAIL** → **不得进入主实验**；仅当发现结构性问题（oracle 不确定 / task 无法执行 / 不满足预注册约束）时，记录 **Pilot Design Failure**，重新生成并重新 Pilot；测量/校准流程问题只修 Pilot 自身，不得修改 main-study task manifest。
