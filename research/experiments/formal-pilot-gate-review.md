# Formal Pilot Gate Review

- 状态：REVIEW ONLY（未运行正式 Pilot；未修改实验设计、P0 Contract、Architecture Decision、`src/`、B0/B1/B2/B3 实现）
- 日期：2026-08-14
- 审查对象：
  - `research/experiments/capability-forge-vs-skill.md`（Experiment Design v0.2，FROZEN）
  - `research/experiments/pilot-architecture.md`（Option B Architecture，FROZEN）
  - `research/artifact-contract/verified-task-artifact-bundle-v0.md`（P0 Bundle Contract，FROZEN）
  - `research/experiments/pilot-minimal-implementation-design.md`（实现设计；含未裁决的 R2）
  - `pilot/` 当前工作树（harness / manifest / config / fixtures / state / gates）
- 证据基线说明：`pilot/`、`research/experiments/experiment-readiness.md`、`tests/` 存在未提交改动；本审查按当前工作树内容取证，不把未提交状态当作已锁定。

---

# Executive Summary

**B0/B1/B2/B3 臂机制、Treatment Attribution Gate、F+ Rehearsal Gate 在 F+ 范围内成立：**

- `pilot/state/fplus_rehearsal_gate.json`：gate=PASS，proofs 1-9 全部 PASS。
- `pilot/state/treatment_attribution_gate.json`：gate=PASS，blockers=[]（B1/B2/B3 future runs 共 6 条，全部 VALID）。
- B1 curated skill 已冻结：`pilot/state/b1_skill_ref.json`，digest `sha256:63d2119423...f0f49`，human_minutes=10。
- B2 generated skill 已冻结：`pilot/state/skill_ref.json`，digest `sha256:405faf4d4e...06a`。
- B3 已 promote：`capability_id=cap-d24c50c27fa8`，artifact digest `sha256:657057ac446...75f6`，invoke exit_code=0。
- `tests/test_minimal.py` 11 个 unit tests 全部通过（本次复核 OK）。

**但 Formal Pilot 的参数冻结不成立：**

- F− / F0 任务族完全缺失（无 fixture / oracle / manifest 条目 / trap）。
- 所有族的 trap relationship 均未实例化。
- Pilot 范围未冻结：冻结设计为 24 runs（A）；实现设计 R2 提出 +12 trap probes = 36 runs（B），无裁决记录。
- Model / Runtime Config 未冻结（temperature=null、seed=null、无 tool limits、agent sandbox image/network 未钉死）。
- Pricing 未 pre-register（当前全部 0 价，明确标注 rehearsal）。
- V / δ 仅有 F+ 正式值，F− / F0 缺失。
- Task manifest 未 immutable / 未 digest-pin；main-study manifest 按设计仍未锁定。
- Randomization 未冻结（seed=null；无 repeated-run 工具/记录字段）。
- Stop Conditions 未实现（无 pilot 级 stop-on-condition 逻辑）。

**FORMAL PILOT GATE = NOT READY**

---

# Gate Matrix

| # | 检查项 | 状态 | 证据 / 缺口 |
|---|---|---|---|
| 1 | Task Families（F+ / F− / F0：formation、held-out、trap、deterministic oracle） | **BLOCKED** | F+ 有 formation（fplus-cal-1/2）、held-out/future（fplus-future-1/2）、确定性 oracle（`pilot/oracles/check.py`），但无 trap fixture / trap manifest 条目；F−、F0 无任何 fixture、oracle、manifest 条目 |
| 2 | Pilot Scope（A=24 或 B=36） | **BLOCKED** | 冻结设计 `capability-forge-vs-skill.md` Pilot 节 = 24 runs（3 families × 4 arms × 2 校准 formation tasks），即 A；`pilot-minimal-implementation-design.md` R2 提出 +12 trap probes = 36 runs（B），标注"本设计自决"，无任何文档/状态记录裁决 R2；当前 harness 只有 F+ 单族 rehearsal 编排，无 24/36-run pilot 执行器 |
| 3 | B0/B1/B2/B3 机器可验证 | **BLOCKED**（F+ 范围内 PARTIAL） | B0：`validate_treatment` 可验证 treatment=none/used=false（仅 unit test，无实际 B0 run record）；`phase_formation` 只接受 b2/b3，Pilot 的 B0 校准 formation runs 不可跑。B1/B2/B3：F+ future runs 全部 VALID（见 Attribution Gate）；但 F−/F0 无任何 arm 资产；B3 的 `treatment.used=true` 为无条件赋值，不校验 invoke_result.exit_code |
| 4 | Model / Runtime Config 冻结 | **BLOCKED** | `pilot/config.json`：provider=deepseek、model=deepseek-v4-flash、reasoning_effort=max、temperature=null、seed=null、timeout_seconds=900、output_bytes=1048576、sandbox.image=python:3.12-slim、network=false。缺口：temperature/seed 未定值；无 tool limits；agent run 走 `codex exec -s workspace-write`（原生沙箱），Docker image/network=false 只作用于 oracle/B3 invoke，不等于 agent sandbox 锁定；无不可变标记，config 未提交 |
| 5 | Pricing pre-register | **BLOCKED** | `pilot/config.json` prices 全部 0.0，`price_note="rehearsal: USD rates zeroed until official provider rates are locked"`；正式 input/output/human/sandbox 价格未锁定，rehearsal 0 价仍在将被使用的 config 中 |
| 6 | V / delta 冻结 | **BLOCKED** | `pilot/manifest.json` 仅 F+ 有 values low=50 / mid=100 / high=200，deltas [0.05, 0.10, 0.20]；F−、F0 无 V_low/V_mid/V_high 与 δ 正式值 |
| 7 | Task Manifest immutable / frozen | **BLOCKED** | `pilot/manifest.json` 仅 F+，role=calibration，无 trap；无 manifest digest / commit 锁定；main-study 21-task manifest 按冻结设计在 Pilot PASS 后才锁定（当前必然未冻结）；Pilot 校准任务与 main-study 选择分离仅为设计文本，无机制强制 |
| 8 | Randomization 可记录 | **BLOCKED** | run record 有 `order`（实际已记录）；seed 字段存在但 config seed=null；实现设计固定顺序 B0→B1→B2→B3、task1→task2，无随机/交错；repeated-run 政策（≤3 次独立重复）只有设计文本，无执行工具/重复索引记录字段 |
| 9 | Treatment Attribution | **PASS（仅 F+ 范围）** | B1/B2：`run_record.validate_treatment` 强制 mounted_digest == expected_digest == treatment.digest；B3：强制 invoke evidence 存在 + capability_id 与 ref 一致 + artifact_digest 与 digest 一致 + sandbox_id 存在；gate PASS 6/6。Caveat：B3 `used=true` 与 invoke 成功无关（exit_code 不参与 gate）；F−/F0 无覆盖 |
| 10 | Stop Conditions | **BLOCKED** | harness 无 pilot 级 stop 逻辑：INVALID_TREATMENT 只在事后 gate 报告；oracle 不稳定仅记录 stable=false；task execution failure 记录 ERROR 后继续；pricing missing 不检查（0 价直接通过）；manifest mutation 不检查；attribution mismatch 不停 |

---

# Blocking Items

1. **F− / F0 任务族缺失**：无 formation tasks、held-out tasks、oracle；`pilot/fixtures/` 仅 F+。
2. **Trap relationship 全部缺失**：3 个族都没有 trap fixture / manifest 条目；Pilot 目标 6（trap 触发验证）不可达。
3. **Pilot 范围未冻结**：冻结设计 = 24 runs（A）；R2 的 36 runs（B）未裁决；当前无 24/36-run 执行器（harness 仅 F+ rehearsal）。
4. **B0/B1 校准 formation 路径不可运行**：`phase_formation` 仅支持 b2/b3；B0 无任何已执行 run record；B1 无校准 formation 编排（只有 future 注入路径）。
5. **Model / Runtime Config 未冻结**：temperature=null、seed=null、无 tool limits；agent sandbox image/network 未锁定；config 未提交、无不可变标记。
6. **Pricing 未 pre-register**：input/output token、human minute、sandbox minute 价格全部为 0（rehearsal 占位），正式价格未锁定。
7. **V / δ 正式值不全**：仅 F+ 有 V_low/V_mid/V_high 与 5%/10%/20%；F−、F0 缺失。
8. **Task manifest 未 immutable**：pilot manifest 无 digest 锁定；main-study manifest 按设计仍未锁定；校准任务污染防护无机制强制。
9. **Randomization 未冻结**：seed=null；无随机/交错顺序执行；independent repeated run 政策无执行与记录工具。
10. **Stop Conditions 未实现**：INVALID_TREATMENT / oracle ambiguity / task execution failure / pricing missing / manifest mutation / attribution mismatch 均不会 stop。

---

# Frozen Parameters

以下内容当前已冻结或有 F+ 级机器证据，正式 Pilot 可直接沿用：

| 参数 | 值 / 证据 |
|---|---|
| Experiment Design | `capability-forge-vs-skill.md` v0.2 Final Correction（24-run Pilot 公式、4 臂定义、H0/H1/H2、decision rules、non-compensation） |
| Option B Architecture | `pilot-architecture.md` = PASS（Option B Reconnected） |
| P0 Bundle Contract | `verified-task-artifact-bundle-v0.md` = FROZEN（13 条 validation rules） |
| B1 human cost | human_minutes=10（`pilot/b1_curated_skill.json`、`pilot/state/b1_readiness.json`） |
| B1 curated skill digest | sha256:63d21194230038fb81976a48e13df154541e7d9d6f1fb7cf937854a50b9f0f49 |
| B2 generated skill digest | sha256:405faf4d4e3ff7221cc5bdac3b8808879ce89bafc105af17562221280338a06a |
| B3 capability / artifact digest | capability_id=cap-d24c50c27fa8；artifact sha256:657057ac446b2ce8bd6a52daa94a378af8594819233c564f5f15be0a89c775f6 |
| Treatment Attribution rules | `pilot/run_record.py::validate_treatment`；`treatment_attribution_gate.json` = PASS |
| F+ Rehearsal Gate | `fplus_rehearsal_gate.json` = PASS（proofs 1-9） |
| F+ 校准任务与 oracle | fplus-cal-1/2、fplus-future-1/2、fplus-novel/novel2 + `pilot/oracles/check.py` |
| F+ V / δ 档位 | values low=50 / mid=100 / high=200；deltas 5% / 10% / 20% |
| F+ 生成输入一致性 | generation_input_digest sha256:2e081441e7...；proposal_digest sha256:9f8415c696...；B2/B3 共享 |
| 沙箱 fail-closed（oracle/B3 invoke） | `src/forge/sandbox.py`：docker 不可用即异常；`--network none`；timeout/output 截断 |

---

# Stop Conditions

用户要求的 stop-on-condition 与当前实现对照：

| 条件 | 要求 | 当前状态 |
|---|---|---|
| INVALID_TREATMENT | stop | 无 stop；只在 `phase_cost_report` 事后输出 gate FAIL |
| oracle ambiguity | stop | 无 stop；记录 stable=false 后继续 |
| task execution failure | stop | 无 stop；记录 oracle=ERROR 后继续（B3 validation/evaluation 失败会抛错中止单阶段，但不是 pilot 级 stop 语义） |
| pricing missing | stop | 无检查；0 价配置直接参与 NV 计算 |
| manifest mutation | stop | 无 manifest digest / 校验 |
| attribution mismatch | stop | 无 stop；仅事后 gate |

---

# Final Decision

**FORMAL PILOT GATE = NOT READY**

10 个检查项中 9 项 BLOCKED / PARTIAL，仅 Treatment Attribution（F+ 范围）PASS。F+ rehearsal 证明的是"单族、单轮、机制可跑通"，不是"Formal Pilot 参数可冻结"。正式 Pilot 放行前必须由设计/契约层裁决以下事项，且本审查不修改任何设计去消除 blocker：

- 冻结 Pilot 范围（A：24 runs，或裁决 R2 后 B：36 runs）。
- 补齐 F−、F0 与 3 个 trap 的 fixture / oracle / manifest。
- 冻结 model / runtime config（temperature、seed、tool limits、agent sandbox image/network）。
- pre-register 正式价格与全部族的 V_low/V_mid/V_high、δ 档。
- 锁定 immutable task manifest（digest + 提交）。
- 实现并记录 randomization / repeated-run 政策。
- 实现 pilot 级 stop conditions。
