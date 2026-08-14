# Formal Pilot Specification

- 状态：**BLOCKED**（实验协议定义 = FROZEN；依赖真实业务输入的字段 = BLOCKED）
- 日期：2026-08-14
- 版本：v1
- 范围：仅冻结 Formal Pilot 的实验协议；不运行实验、不写 `src`、不修改 P0 Contract、不修改 Architecture Decision、不实现新的实验功能。
- 冻结输入：
  - `research/experiments/capability-forge-vs-skill.md`（v0.2 Final Correction，FROZEN）
  - `research/experiments/pilot-minimal-implementation-design.md`（R1/R2/R3 裁决）
  - `research/experiments/formal-pilot-gate-review.md`（gate 证据）
  - `pilot/config.json`、`pilot/manifest.json`、`pilot/run_record.py`（rehearsal 证据）

---

## 1. Pilot Scope（FROZEN）

**Formal Pilot = 36 runs = 24 formation runs + 12 trap probes。**

- 24 formation runs = 3 families × 4 arms × 2 calibration formation tasks。
- 12 trap probes = 3 families × 4 arms × 1 trap probe。
- 此即实现设计 R2 的 36-run 裁决；R2 被接受，原冻结文本中的 24-run formation 公式不变，trap probes 是 Pilot-scoped 附加。
- **trap probes 不进入主实验 effect estimate**；calibration formation runs 同样不进入（见 §4）。
- Pilot 结果不进入 main-study 结论；Pilot 唯一作用是校准难度 / oracle / 可执行性 / trap 触发 / NV 与 sensitivity 可运行。

## 2. Task Families（FROZEN）

| 族 | 定义 | 被测特征 |
|---|---|---|
| F+ | 高复用、稳定可执行契约（如 CSV → 清洗规则 → 统计报告） | 同族共享 input/output schema，任务间仅数据/参数不同 |
| F− | 低复用、高方差或任务私有状态（如仓库特定迁移缺陷 / 一次 incident） | 契约漂移或任务私有状态本身是被测特征；形成失败是观测点 |
| F0 | 声明式、指令可完全覆盖（如 Markdown → HTML 报告） | 无需要沙箱调用的可执行 artifact，skill-only 应足够 |

任务选择标准沿用冻结设计：确定性 oracle、契约稳定性、沙箱可行（无网络 / secret / live workspace，单次 ≤ 30 min）、可形成性、复用频率分层（F+/F0 设计 r ≥ 3，F− 设计 r ≈ 1）、每族 1 个 cross-family trap。

## 3. Per-Family Composition（FROZEN）

主实验（Main Study）每族：

| 每族任务 | 数量 | 约束 |
|---|---|---|
| formation tasks | 3 | 3 train → 1 formation episode → 1 artifact（B1/B2/B3） |
| in-family held-out | 3 | 绝不进入 formation |
| cross-family trap | 1 | 与另一族表面相似、契约不同；绝不进入 formation |

- 主实验唯一任务 = 21（3 families × 7）。
- Pilot 任务与主实验任务分离：Pilot 每族 2 个 calibration formation tasks + 1 个 trap probe；main-study 的 3 formation + 3 held-out + 1 trap 另行锁定。
- unique tasks ≠ observations：需要更多观测时只对已冻结任务做 independent repeated runs（§10），不新增/修改 task definition。

## 4. Pilot Calibration（FROZEN）

- Pilot 的 2 个 calibration formation tasks 只用于：oracle 稳定性、任务难度（B0 success ∈ [0.2, 0.8]）、B1 human cost 可记录、B2/B3 共享 generation input、Bundle 足够支撑 B3、NV 与 V/δ sensitivity 可运行。
- **calibration tasks 不进入主实验 effect estimate**；trap probes 也不进入（§1）。
- Pilot 成功率不得用于：主实验效应估计、主实验结果、第三个 formation task 的删除/替换、held-out / trap 的调参。
- 若 Pilot 发现 oracle 不确定 / task 无法执行 / 不满足预注册约束 → 记录 **Pilot Design Failure**，重新生成并重新 Pilot；测量/校准流程问题只修 Pilot 自身。

## 5. Model / Runtime Config（BLOCKED）

以下为协议要求与当前证据；带 `BLOCKED` 的字段**不得猜测取值**，须由 operator 提供后重新冻结。

| 字段 | 协议要求 | 状态 / 证据 |
|---|---|---|
| provider | 单一 provider，全 36 runs 相同 | **BLOCKED**；`pilot/config.json` 候选值 `deepseek`（rehearsal 用），需 operator 确认为正式端点 |
| model | 单一 model，全 runs 相同 | **BLOCKED**；候选值 `deepseek-v4-flash`，需 operator 确认 |
| reasoning_effort | 单一值，全 runs 相同 | **BLOCKED**；候选值 `max`，需 operator 确认 |
| temperature | 非 null 固定值 | **BLOCKED**；当前 `null`，不要猜 |
| seed policy | 固定、可记录 | 实验级 seed 已冻结 = `20260814`（§10）；模型采样 seed 策略 **BLOCKED**（provider 是否支持 seed、固定值多少由 operator 定） |
| timeout | 单 run 上限 | **FROZEN**：`timeout_seconds = 900`（≤30 min 设计约束；rehearsal 已用） |
| output limit | 单 run 输出上限 | **FROZEN**：`output_bytes = 1048576`（rehearsal 已用） |
| tool limits | 工具白名单 / 最大调用数 | **BLOCKED**；当前 config 无此字段，不要猜 |
| sandbox image | oracle / B3 invoke | **FROZEN**：`python:3.12-slim`（Docker，fail-closed） |
| sandbox image | agent run | **BLOCKED**；rehearsal 实际走 codex 原生 `workspace-write`（`sandbox_id=codex-workspace-write`），尚未作为正式 agent sandbox 策略钉死 |
| network policy | oracle / B3 invoke | **FROZEN**：`network = false`（fail-closed） |
| network policy | agent run | **BLOCKED**；codex 原生沙箱的网络行为未正式确认/钉死 |

## 6. Pricing（BLOCKED）

价格单位（USD，全部必须 pre-register）：

| 价格 | 字段 | 状态 |
|---|---|---|
| input token | `input_token_usd` | **BLOCKED**；当前 `0.0`（rehearsal 占位，无效） |
| output token | `output_token_usd` | **BLOCKED**；当前 `0.0`（rehearsal 占位，无效） |
| human minute | `human_minute_usd` | **BLOCKED**；当前 `0.0`（rehearsal 占位，无效） |
| sandbox minute | `sandbox_minute_usd` | **BLOCKED**；当前 `0.0`（rehearsal 占位，无效） |

- 正式值必须为显式 pre-registered 的有限非负数值，并附来源与日期；rehearsal 0 价不得用于 Formal Pilot 的 NV 计算。
- 任一价格缺失 / 为 null / 为负 / 仍是 rehearsal 0 占位 → `pricing missing` → 立即 STOP（§11）。

## 7. V（PARTIAL：F+ FROZEN；F− / F0 BLOCKED）

| 族 | V_low | V_mid | V_high | 状态 |
|---|---|---|---|---|
| F+ | 50 | 100 | 200 | **FROZEN**（来源 `pilot/manifest.json`） |
| F− | — | — | — | **BLOCKED**，须 operator 提供 |
| F0 | — | — | — | **BLOCKED**，须 operator 提供 |

- V 含义 = business value if success（`V(task) × 1[success]`），结论必须在 low / mid / high 三档分别报告；翻转或进入等价带 → `value-sensitive`，不得声称 "Forge 已被证明"。

## 8. delta（FROZEN）

`deltas = [0.05, 0.10, 0.20]`（5% / 10% / 20%），适用于全部三个族。

- 主阈值 `δ_NV = 10% × TCO_best`（aggregate）；5% / 20% 为 sensitivity 档。
- 三档结论一致才报告 robust；不一致 → `threshold-sensitive`，只报告各档结论与翻转点。

## 9. Main-study Manifest（schema / canonicalization / freeze point = FROZEN；content + digest = PENDING）

### 9.1 Schema（`task_manifest_v1`，main-study 内容）

```json
{
  "schema_version": "task_manifest_v1",
  "manifest_type": "main_study",
  "families": [
    {
      "family": "F+",
      "description": "CSV -> cleaning rules -> statistical report",
      "values": {"low": 50, "mid": 100, "high": 200},
      "deltas": [0.05, 0.10, 0.20],
      "oracle": {"kind": "check_command", "command": ["python", "/oracle/check.py"], "script": "oracles/check.py"},
      "formation_tasks": [
        {"task_id": "...", "prompt_ref": "...", "fixture_ref": "fixtures/<family>/<task_id>", "oracle": {...}, "limits": {"timeout_seconds": 900, "output_bytes": 1048576}}
      ],
      "future_tasks": [
        {"task_id": "...", "role": "in_family_held_out", "prompt_ref": "...", "fixture_ref": "...", "oracle": {...}, "limits": {...}}
      ]
    }
  ],
  "traps": [
    {"task_id": "...", "owner_family": "F+", "looks_like_family": "F0", "fixture_ref": "...", "oracle": {...}, "limits": {...}}
  ]
}
```

约束：
- 每族 `formation_tasks` 恰好 3；`future_tasks` 恰好 3（in-family held-out）；`traps` 共 3（每族 1 个，`owner_family` 为该族，`looks_like_family` 为另一族）。
- Pilot-scope manifest 用同一 schema、`manifest_type="pilot"`：每族 `formation_tasks` 恰好 2（calibration），`traps` 为 3 个 trap probes。
- 唯一任务数：Pilot 9（6 calibration + 3 trap probes）；Main Study 21。

### 9.2 Canonicalization

- 文件：UTF-8、无 BOM。
- Canonical bytes = `json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`，无尾随换行。

### 9.3 sha256 digest

- `digest = "sha256:" + sha256(canonical_bytes).hexdigest()`。
- 冻结时写入 `pilot/state/<manifest_type>_manifest_ref.json`：`{"manifest_type", "path", "sha256", "frozen_at", "git_commit"}`。
- 每次 run 启动前重算 digest，与 ref 不一致 = `manifest mutation` → 立即 STOP（§11）。

### 9.4 Freeze point

- Pilot manifest（9 fixtures + V + δ + oracle）：**Formal Pilot Spec 接受时冻结**，digest 入库。
- Main-study manifest（21 unique tasks）：**Pilot Gate PASS 时冻结**，digest 入库，此后不得修改；结构性错误走 `Pilot Design Failure`（重新生成 + 重新 Pilot）。

## 10. Randomization（FROZEN）

- **固定 seed**：`20260814`。任何随机决策（如 repeated-run 选择顺序、平局处理）使用 `random.Random(seed)`；seed 写入 run record 与 config。
- **Run order（冻结，全 36 runs 串行）**：
  1. 族顺序：F+ → F− → F0。
  2. 每族 formation：B0-t1, B0-t2, B1-t1, B1-t2, B2-t1, B2-t2, B3-t1, B3-t2（B2/B3 的 4 个 bundle 齐了再生成）。
  3. 每族 formation 与 artifact 阶段完成后：trap probes B0-trap, B1-trap, B2-trap, B3-trap。
  4. `order` 字段记录全局序号 1..36；同一 run 不并行执行。
- **Repeated-run policy**：若某个已冻结的 held-out / trap 任务在臂间首轮成功率波动 > 20pp，对该**同一任务**做 independent repeated runs，至多 3 次（`repeat_index` = 1..3）；每次 fresh sandbox、无状态继承；成功取多数，成本取均值；不新增/修改 task definition；main-study 总量上限 84 + 36 = 120 runs。

## 11. Stop Conditions（FROZEN）

| 条件 | 触发 | 动作 |
|---|---|---|
| INVALID_TREATMENT | `validate_treatment()` 返回非空（B0/B1/B2/B3 treatment 与证据不一致） | **立即 STOP**；该 run 不计入；调查后恢复 |
| oracle ambiguity | oracle 两次确定性复跑结果不一致，或输出非确定 | **立即 STOP**；记录 `ambiguous`；不可复现 → Pilot Design Failure |
| execution failure（任务级） | agent run 正常结束但 oracle FAIL / 输出不完整 / 非零退出 | **普通 failed run**：记录 `oracle=FAIL`，继续 |
| execution failure（基础设施级） | 沙箱无法启动、CLI 不可用、Docker 缺失、网络策略失效 | **立即 STOP**；修复后以 fresh sandbox 重跑该 run |
| pricing missing | 任一正式价格缺失 / null / 负 / rehearsal 0 占位 | **立即 STOP** |
| manifest mutation | manifest digest 重算 ≠ 冻结 ref | **立即 STOP** |
| attribution mismatch | B1/B2 skill 注入或 B3 invoke evidence 与 treatment 不一致 | **立即 STOP**（等价于 INVALID_TREATMENT 类） |

## 12. Final Status

**Formal Pilot Spec = BLOCKED**

协议定义（§1-§4、§8、§9 的 schema/canonicalization/freeze point、§10、§11）已冻结；以下依赖真实业务输入，不得由本 spec 编造：

### Operator Actions

1. 确认并锁定 Model / Runtime：正式 provider、model、reasoning_effort；提供 temperature 固定值、模型采样 seed 策略、tool limits；钉死 agent run 的 sandbox image/network 策略（或明确接受 codex 原生 `workspace-write` + network off）。
2. 提供正式 pre-registered 价格：`input_token_usd`、`output_token_usd`、`human_minute_usd`、`sandbox_minute_usd`（附来源与日期），替换 rehearsal 0 价。
3. 提供 F−、F0 的 `V_low` / `V_mid` / `V_high`（F+ 已冻结为 50/100/200）。
4. 提供并批准 F−、F0 的 2 个 calibration fixtures + 全部 3 个 trap probe fixtures（F+ 已有 calibration 资产；trap 全部缺失），随后计算并冻结 Pilot manifest digest；Main-study 21 个任务的实例化与冻结在 Pilot PASS 后执行。

以上 1-4 完成后，更新本文件相应字段并重新发布冻结状态。
