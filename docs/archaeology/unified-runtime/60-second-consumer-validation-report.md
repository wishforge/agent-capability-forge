# 60 — Phase 7 Second Consumer Validation Report

> 阶段：Phase 7（第二消费者验证）。基线：57（E.5–E.7.1 冻结，
> `ca06a9a` / `22890c1` / `f0ae41f`）。
> 本阶段没有修改 E.5 / E.6 / E.7 / E.7.1、`promotion-gate/*`、
> `candidate-eval/*`、`regression-attribution/*`；没有运行 live provider；
> 没有连接生产部署；没有 commit / push。

## 1. 执行摘要

Phase 6-E 抽象出的 Evaluation → Regression → Attribution → Promotion →
Provenance 控制协议，在第二个完全不同的 Agent Capability（swe-planner
plan-writer）上以**离线 replay** 走通了一遍。

```text
第二消费者 = swe-planner plan-writer（research/control-plane-loop S7.3）
  provider/model = DeepSeek / deepseek-v4-flash
  dataset       = gold-v2（33 条真实生产 trace）
  候选          = baseline-planwriter-v1 vs bad_v1 / bad_v2 / good_v1 / neutral_v1
  实验          = 5 候选 × 5 repeats × 33 samples = 25 个 append-only runs

最终判定：PARTIAL_REUSE
  核心协议（Candidate / Evaluation / Evidence / Outcome / Regression /
  Attribution 分类集 / 三态 Gate / Runtime-Control Plane 边界）可复用，
  语义无需修改；
  需要少量 consumer-specific extension（score-level 归因规则、target
  effectiveness 定义、预注册 + manifest 落地）。
```

回答业务问题：

> 这套控制协议不是第一消费者专属；第二消费者不需要复制 CAL-26 / B-prime /
> Wilson / 44-case / Model_Studio 等第一套专属逻辑就能复用其语义。

## 2. 执行内容（只读 + 离线）

新增最小验证工具：

```text
docs/archaeology/unified-runtime/phase7/validate_second_consumer.py
  python3 ... --self-check   # 断言式自检：OK
  python3 ...                # 生成 replay artifacts：OK
```

工具只读 `research/control-plane-loop/data/`，产出写入：

```text
docs/archaeology/deepseek-harness/evaluation/artifacts/phase7-second-consumer/
  protocol-objects.jsonl    # Candidate 5 + EvaluationRun 25 + Evidence 825
                            # + RegressionFinding 660 + Attribution 4
  replay-gate.json          # replay policy + per-pair gate + provenance
  binding-audit.json        # 第一消费者绑定审计（0 命中）
  summary.json              # 汇总
```

replay policy（`phase7-second-consumer-replay-v1`）明确标注
`REPLAY_ONLY`：只验证协议语义，不追溯认证原 S7.3 实验（原实验的 noise
阈值是事后校准的，见 §5）。

## 3. 验证结果

### A. Candidate effectiveness —— 可定义，但本数据集无可认证候选

replay policy 声明 target = “gold-v2 median 计划质量提升”，success =
median delta > baseline repeat noise（0.0447，只由 baseline 5 次 run 校准）。

结果（FACT，来自 replay-gate.json）：

| 候选 | 各 repeat median delta | effectiveness 证据 |
| --- | --- | --- |
| bad_v1 | +0.10 / +0.15 / +0.10 / 0.00 / +0.10 | 机械层 3/5 PASS，但这是 judge 盲区（s7/09），且 governance 缺失，不能成为协议级 effectiveness |
| bad_v2 | -0.10 / -0.15 / -0.20 / -0.20 / -0.20 | 无 |
| good_v1 | 0.00 / -0.05 / -0.10 / -0.10 / -0.075 | 无（judge 对 instruction 级改进无分辨率 + evidence 不足） |
| neutral_v1 | 0.00 ×5 | 无 |

结论（INFERENCE）：协议可以表达 effectiveness（policy 字段），第二消费者
只是还没有定义 target / success 并产生达标候选；这不是协议语义缺陷。

### B. Regression safety —— 配对重放走通

按协议规则顺序（dataset 一致 → evidence 完整 → L0/agent failure 不升 →
delta 超噪声）对 5 对 repeat 逐对判定：

| 候选 | 机械 gate（PASS/FAIL/INCONCLUSIVE） | 协议 decision |
| --- | --- | --- |
| bad_v1 | 3 PASS / 0 FAIL / 2 INC（r4 variance、r5 evidence） | HOLD |
| bad_v2 | 0 PASS / 4 FAIL / 1 INC（r5 evidence） | REJECT |
| good_v1 | 0 / 0 / 5（全部 evidence 不足） | HOLD |
| neutral_v1 | 0 / 0 / 5（4 variance + 1 evidence） | HOLD |

全部 4 个候选都在不修改核心语义的前提下产生了配对回归判定（FACT）。
bad_v2 的 4/4 可比 repeat 稳定负 delta（-0.10 ~ -0.20）被判定为
rate-level candidate regression → REJECT。

### C. Attribution —— 四类：三类可直接区分，一类需 score-level 扩展

| 类别 | 第二消费者可区分？ | 证据 |
| --- | --- | --- |
| BASELINE_INSTABILITY | 是 | baseline 5 次 run median = 0.10/0.15/0.20/0.20/0.20，std 0.0447（FACT） |
| PROVIDER_NONDETERMINISM | 是 | 同候选 5 次 run median 波动；S7.1 固定输入 judge 重测波动 0.2–0.6（FACT） |
| INSUFFICIENT_EVIDENCE | 是 | good_v1 每 run 2–4 个样本、baseline r5 1 个样本进入 error statuses（FACT） |
| CANDIDATE_REGRESSION | score-level 是；verdict-level 否 | bad_v2 5/5 median=0.0 vs baseline 0.10–0.20（score-level，FACT）；第二消费者没有 per-case 二值 verdict，第一消费者的“100% verdict 翻转”规则不可套用（UNKNOWN / not applicable） |

工具产出的 Attribution 对象如实标记：bad_v2 =
`CANDIDATE_REGRESSION (score-level strict) + INSUFFICIENT_EVIDENCE`；
其余候选 primary = `INSUFFICIENT_EVIDENCE`，同时保留
BASELINE_INSTABILITY / PROVIDER_NONDETERMINISM 的 expressible 标记。
没有为套模型而强行归因（FACT）。

### D. Promotion —— 三态全部可达，本数据集只落 HOLD / REJECT

机械层三态映射 1:1 走通（FACT，s73 matrix 与 replay 均产出三种值）：

```text
PASS        -> PROMOTE   （bad_v1 3 个 repeat 机械 PASS）
FAIL        -> REJECT    （bad_v2 4 个 repeat）
INCONCLUSIVE-> HOLD      （good / neutral / 其余 repeat）
```

协议级最终 decision：

```text
bad_v2      -> REJECT（confirmed score-level regression）
bad_v1      -> HOLD  （机械 PASS 被 governance_missing 拦截；且是 judge 盲区 false confidence）
good_v1     -> HOLD  （evidence 不足）
neutral_v1  -> HOLD  （variance / evidence）
PROMOTE     -> 本数据集不可达：要求全部 repeat 通过 + effectiveness +
               governance，第二消费者原实验缺 governance
```

这是协议更严格的正确表现（FACT/INFERENCE），不是协议无法表达 PROMOTE。

## 4. Provenance 与第一消费者绑定审计

### Provenance（第二消费者现状）

```text
evidence 层：run 目录 append-only + 唯一 run_id           FACT
dataset：gold-v2 冻结 + sha256 + 拒绝覆盖                  FACT
candidate：candidates/*.jsonl + plan_sha256               PARTIAL
registered policy bytes == git show                       MISSING（原实验无 policy 文件）
manifest / audit revision                                 MISSING
recompute 等价性                                          replay 工具可重算（本次执行）
```

协议要求的 Provenance 链结构通用，第二消费者尚未实现后三件。

### 绑定审计（重点检查项全部通过）

`binding-audit.json` 对全部协议对象与 replay gate 做了 token 扫描：

```text
CAL-26 / task-judge / b-prime / prompt-b-v2 / wilson /
model_studio / qwen3.7-plus / promotion-policy-e7 /
system_prompt_snapshot  → 0 命中（pass=true）
```

57 §4.5 把 `Outcome.confidence` 列为最小字段，但第二消费者 judge 只有
score + reasoning（s7/03，FACT），没有 confidence；因此该字段应降级为
consumer-specific / optional，不能写死进通用协议（UNKNOWN 通用性）。

## 5. 关键审计发现

1. **原 S7.3 实验没有预注册 policy（FACT）**：gate 规则只存在于
   `gate_calibration.py` 的 `GATE_CONFIG_VERSION` 字符串；repeat noise
   由同一实验数据事后校准（s7/09 §1）。按 57 号协议，这属于 governance
   证据缺失，原实验的任何“PASS”都不能升级为 PROMOTE。这是消费者侧缺口，
   不是协议语义需要修改。
2. **score-level strict-stability 是必要 extension（INFERENCE）**：
   第二消费者事实是连续分数而非二值 verdict，第一消费者的 verdict-level
   100% 翻转规则不可套用；需要 policy 预注册 score-level 规则
   （bad_v2 已用它正确给出 REJECT）。
3. **`finalize-candidates --force` 存在候选改写入口（FACT/UNKNOWN）**：
   run 层 evidence 不可覆盖（FACT），但 candidate 文件可被 --force 重建；
   无 manifest 无法证明历史上未发生（UNKNOWN）。
4. **arm-order 交替未记录（FACT）**：第二消费者 5 对 repeat 未交替 arm
   顺序；协议把 arm order 视为 EvaluationRun 固定条件，不改变核心语义。

## 6. 最终判定：PARTIAL_REUSE

### Core（REUSE_CONFIRMED —— 第二消费者验证通过）

```text
Candidate（身份 + hash）
EvaluationRun（固定条件 + append-only 唯一 run）
Attempt / Evidence（失败保留，raw 落盘）
三层 outcome 语义（verdict / contract / transport）
Paired replay（同 dataset 按 repeat 配对）
Regression（paired delta + 显式不可比）
Attribution 分类集（四类语义可表达）
三态 Gate（PROMOTE / HOLD / REJECT）
Runtime / Control Plane 边界
```

### Extension（consumer-specific，不属于核心语义）

```text
E1. score-level strict-stability 归因规则（连续分数事实下的稳定负 delta）
E2. target effectiveness 定义（协议字段，consumer 提供值）
E3. 预注册 policy 文件 + manifest + commit 锚点（协议已要求，第二消费者未落地）
E4. outcome 标签映射（INVALID_OUTPUT ↔ JUDGE_*）
```

### UNKNOWN（未验证，禁止升级）

```text
Outcome.confidence 的通用性
Registered/Final PolicyVersion 与 Manifest 在第二消费者的实现形态
arm-order 交替的必要性
Wilson / 8-of-10 / -0.1 / CI 0.5 在第二消费者任务域的可迁移性
```

## 7. 停止条件

Consumer Selection（58 §2）→ Generic vs Consumer-specific analysis（59）
→ Minimal validation design（58 §5）→ Minimal second-consumer validation
（本文档 §3-4）→ Reuse assessment（本文档 §6）全部完成。

STOP：不建 schema / database / service / API / CRD / controller；不做 E.8；
不继续优化 B-prime 或 S7.3 候选；不 commit / push。

> 最终答案：这套 Evaluation / Regression / Attribution / Promotion /
> Provenance 控制协议是跨 Agent Capability 通用的（核心语义），
> 但需要为连续分数型 consumer 补充 score-level 归因扩展与 governance
> 落地，判定为 PARTIAL_REUSE。
