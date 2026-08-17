# 56 — Phase 6-E.7 Promotion Evidence Gate

> 阶段：Phase 6-E.7（Promotion Evidence Gate）。
> 基线：HEAD = `9f7c3a2`；本阶段 pre-registration 提交 = `ca06a9a`。
> E.5 / E.6 已封存于 `54-phase6e5-prompt-candidate-evaluation.md` /
> `55-phase6e6-regression-attribution.md`，本阶段不修改、不重新解释二者。
> 约束遵守：未修改 candidate prompt、parser / contract / retry / production
> runtime；未重新跑完整 44-case matrix；未执行生产 promotion；未继续 E.8。

## 0. 执行摘要

E.7 建立并执行了一个**先预注册、后实验**的 Promotion Evidence Gate。
Policy 在 live 调用前写入并冻结（commit `ca06a9a`，artifact
`artifacts/promotion-gate/promotion-policy.json`）；live runner 在 policy
缺失或与 frozen policy 不一致时拒绝运行。

Live 实验为 8 case × 2 arms 的 paired replay：CAL-26（target）与
TASK-JUDGE-01 / CAL-08 / CAL-18（suspicious）各 10 轮/arm，TASK-JUDGE-07 /
CAL-41（stable controls）与 TASK-JUDGE-03 / CAL-11（critical controls）各
5 轮/arm。合计 **120 rounds、142 attempts**（含 22 次同条件替换调用）。

```text
target effectiveness = 复现且更强
  CAL-26 B       = 9/9 INVALID_OUTPUT + 1 transport（样本因 transport 不完整）
  CAL-26 B-prime = 10/10 ACCEPT INCONCLUSIVE（Wilson 95% [0.7225, 1.0]）

rate-level stability = 未达标
  TASK-JUDGE-01 B-prime = PASS 1/10、INC 9/10（delta vs B = -0.8）
  CAL-08        B-prime = PASS 3/10、INC 7/10（delta = -0.7）
  CAL-18        B-prime = PASS 6/10、INC 4/10（delta = -0.4）

safety / contract = 干净
  candidate FAIL on stable-PASS = 0
  candidate PASS on critical-FAIL = 0
  candidate INVALID_OUTPUT = 0/120 rounds

E.6 pre-condition = REGRESSION_SAFETY_CONFIRMED（未重新解释）
```

```text
GATE = HOLD
```

结论：candidate 有明确 effectiveness 证据（CAL-26 修复 10/10）且没有
confirmed candidate regression，但三个 suspicious case 的 rate-level
behavior 与 baseline 存在系统性率差（candidate PASS 率 0.1 / 0.3 / 0.6 vs
baseline 0.9 / 1.0 / 1.0），未达到预注册的稳定性阈值。证据**不足以支持
Promotion**。

## 1. Promotion 的本质问题

E.7 不重新问 “candidate 有没有 regression”（E.6 已回答），而是问：

> candidate 的收益是否已经足够稳定、足够可信、足够可复现，可以支持上线？

六个维度显式区分：

| 维度 | E.7 结论 |
| --- | --- |
| 1. effectiveness | 有：CAL-26 修复 10/10 复现 |
| 2. regression safety | 有：E.6 = REGRESSION_SAFETY_CONFIRMED，本阶段未推翻 |
| 3. repeatability | 有（target）：CAL-26 candidate 10/10 同结果 |
| 4. repeatability（rate-level） | 无：suspicious cases 的 PASS/INC 率不稳定 |
| 5. sample sufficiency | 部分：suspicious/controls 完整；CAL-26 baseline 不足（transport） |
| 6. promotion confidence | 不足 → HOLD |

## 2. Pre-registered Promotion Policy

Policy 在 live 实验前写入并冻结：

```text
artifacts/promotion-gate/promotion-policy.json
  policy_id        = promotion-policy-e7-v1
  pre-registration = commit ca06a9a（live 前提交）
  decision evidence= E.7 fresh paired replay only
  E.6 pre-condition= REGRESSION_SAFETY_CONFIRMED（缺失或不同 => REJECT）
```

### 2.1 Fixed conditions（全部 attempt 一致）

| 字段 | 值 |
| --- | --- |
| dataset | `calibration:phase6d:procurement` @ v2 |
| provider | Model Studio（`model_studio`） |
| model | `qwen3.7-plus` |
| baseline prompt | `prompt:phase6b:judge:B:v1` |
| candidate prompt | `prompt:phase6b:judge:B-prime:v1` |
| temperature / seed | `0.0` / `42` |
| max_tokens / timeout | `8192` / `120.0` |
| response_format | `{"type": "json_object"}` |
| parser / contract | 既有 `judge_provider._parse` / `contract_guard`，未修改 |
| arm order | 奇数轮 B→B-prime；偶数轮 B-prime→B |

### 2.2 Sample size & replacement

```text
core（CAL-26 + 3 suspicious）: N = 10 valid rounds / arm / case
controls（2 stable + 2 critical）: N = 5 valid rounds / arm / case
失败 attempt：同 arm 同 round 替换，最多 2 次；
替换后仍无 ACCEPT（或 transport 终局）=> 该 case-arm sample-insufficient
transport bound：core <= 2 / arm；control <= 1 / arm；超出 => HOLD
```

样本充分性按 `n_contract`（ACCEPT + INVALID_OUTPUT 的 round 数）判定：
INVALID_OUTPUT 是契约相关 outcome（CAL-26 baseline 的缺陷信号就是它），
transport 才是丢失样本。

### 2.3 Statistical method

```text
interval = Wilson score interval（two-sided 95%, z = 1.96）
rate     = success_count / n_contract（round-level）
delta    = candidate round_success_rate - baseline round_success_rate
公式     = (p + z^2/2n ± z*sqrt(p(1-p)/n + z^2/4n^2)) / (1 + z^2/n)
```

### 2.4 Pre-registered rate rules（阈值在 live 前固化，禁止事后调整）

| rule | case set | 要求 |
| --- | --- | --- |
| target_baseline_still_broken | CAL-26 | B INC <= 2/10 且 B INVALID_OUTPUT >= 5/10 |
| target_candidate_fixed | CAL-26 | B-prime INC >= 8/10、CI lower >= 0.5、INVALID_OUTPUT = 0 |
| target_delta | CAL-26 | candidate INC rate − baseline INC rate >= 0.5 |
| suspicious_baseline_stable | TJ-01, CAL-08, CAL-18 | B PASS >= 8/10 |
| suspicious_candidate_stable | 同上 | B-prime PASS >= 9/10、CI lower >= 0.5、INC <= 1/10、FAIL = 0 |
| suspicious_delta | 同上 | candidate PASS rate − baseline PASS rate >= -0.1 |
| stable_control_* | TJ-07, CAL-41 | B / B-prime PASS >= 4/5；B-prime FAIL = 0；delta >= -0.2 |
| critical_control_* | TJ-03, CAL-11 | B / B-prime FAIL >= 4/5；B-prime PASS = 0；delta >= -0.2 |

### 2.5 Gate semantics

```text
PROMOTE = E.6 confirmed + 全部 rate rules + sample sufficiency + transport
          bound + artifacts 完整 + 无 unresolved blocker
HOLD    = effectiveness 有证据、无 confirmed candidate regression，但
          sample / stability / provider variance / uncertainty 不足以支持上线
REJECT  = candidate-induced regression（stable-PASS FAIL 或 critical PASS）、
          target fix 不成立、candidate INVALID_OUTPUT、evidence integrity
          失败、或 policy 事后被修改
```

## 3. Experiment Matrix

```text
target            = CAL-26
suspicious        = TASK-JUDGE-01, CAL-08, CAL-18（E.5 Run 1 异常 case）
stable controls   = TASK-JUDGE-07, CAL-41
critical controls = TASK-JUDGE-03, CAL-11
```

每 case 每 arm 依次执行 N 轮；每轮首调失败按 policy 同条件替换（最多 2 次），
替换调用全部保留为独立 evidence。完整调度见
`artifacts/promotion-gate/promotion-manifest.json`。

## 4. Per-case Results（E.7 fresh）

| case | stratum | arm | n_contract | PASS | INC | FAIL | INVALID | transport | rate | Wilson 95% | sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAL-26 | target | B | 9 | 0 | 0 | 0 | 9 | 1 | 0.0 | [0.0, 0.2992] | NO |
| CAL-26 | target | B-prime | 10 | 0 | 10 | 0 | 0 | 0 | 1.0 | [0.7225, 1.0] | YES |
| TASK-JUDGE-01 | suspicious | B | 10 | 9 | 1 | 0 | 0 | 0 | 0.9 | [0.5958, 0.9821] | YES |
| TASK-JUDGE-01 | suspicious | B-prime | 10 | 1 | 9 | 0 | 0 | 0 | 0.1 | [0.0179, 0.4042] | YES |
| CAL-08 | suspicious | B | 10 | 10 | 0 | 0 | 0 | 0 | 1.0 | [0.7225, 1.0] | YES |
| CAL-08 | suspicious | B-prime | 10 | 3 | 7 | 0 | 0 | 0 | 0.3 | [0.1078, 0.6032] | YES |
| CAL-18 | suspicious | B | 10 | 10 | 0 | 0 | 0 | 0 | 1.0 | [0.7225, 1.0] | YES |
| CAL-18 | suspicious | B-prime | 10 | 6 | 4 | 0 | 0 | 0 | 0.6 | [0.3127, 0.8318] | YES |
| TASK-JUDGE-07 | stable control | B | 5 | 5 | 0 | 0 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| TASK-JUDGE-07 | stable control | B-prime | 5 | 5 | 0 | 0 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| CAL-41 | stable control | B | 5 | 5 | 0 | 0 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| CAL-41 | stable control | B-prime | 5 | 5 | 0 | 0 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| TASK-JUDGE-03 | critical control | B | 5 | 0 | 0 | 5 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| TASK-JUDGE-03 | critical control | B-prime | 5 | 0 | 0 | 5 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| CAL-11 | critical control | B | 5 | 0 | 0 | 5 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |
| CAL-11 | critical control | B-prime | 5 | 0 | 0 | 5 | 0 | 0 | 1.0 | [0.5655, 1.0] | YES |

Delta（candidate − baseline round success rate）：

| case | delta |
| --- | --- |
| CAL-26 | +1.0 |
| TASK-JUDGE-01 | -0.8 |
| CAL-08 | -0.7 |
| CAL-18 | -0.4 |
| TJ-07 / CAL-41 / TJ-03 / CAL-11 | 0.0 |

## 5. Statistical Summary

```text
rounds   = 120（core 4 cases x 10 x 2 arms + controls 4 x 5 x 2 arms）
attempts = 142（含 22 次同条件替换；TASK-JUDGE-01/CAL-26/TJ-03 各含
           TIMEOUT 替换，CAL-26 baseline 大量 INVALID_OUTPUT 替换）

target（CAL-26）:
  B       = INVALID_OUTPUT 9/10、transport 1/10 → INC rate 0.0
  B-prime = INC 10/10 → rate 1.0（95% CI [0.7225, 1.0]）

suspicious（B-prime PASS rate）:
  TASK-JUDGE-01 = 0.1（95% CI [0.0179, 0.4042]）
  CAL-08        = 0.3（95% CI [0.1078, 0.6032]）
  CAL-18        = 0.6（95% CI [0.3127, 0.8318]）
  threshold     = >= 0.9 且 CI lower >= 0.5 且 INC <= 0.1

controls:
  stable PASS = 5/5、5/5（B 与 B-prime 一致）
  critical FAIL = 5/5、5/5（B 与 B-prime 一致）

provider transport（round-final）:
  CAL-26 B r3（TIMEOUT）=> baseline target 样本 n_contract = 9 < 10
  其余 case-arm 无 round-final transport；全部 sample sufficient
```

Pre-registered rules 结果：

```text
PASS  target_baseline_still_broken（B INC 0 <= 2；INVALID 9 >= 5）
PASS  target_candidate_fixed（INC 10 >= 8；CI 0.7225 >= 0.5；INVALID 0）
PASS  target_delta（+1.0 >= 0.5）
PASS  suspicious_baseline_stable（TJ-01 9/10、CAL-08 10/10、CAL-18 10/10）
FAIL  suspicious_candidate_stable（TJ-01 1/10、CAL-08 3/10、CAL-18 6/10；
      均不满足 PASS >= 9/10、CI lower >= 0.5、INC <= 1/10）
FAIL  suspicious_delta（-0.8 / -0.7 / -0.4；均 < -0.1）
PASS  stable_control_*（4/4 case 全过）
PASS  critical_control_*（4/4 case 全过）
```

## 6. Final Gate

```text
GATE = HOLD
```

### 为什么不是 PROMOTE

1. **Rate-level stability 未达预注册阈值**：三个 suspicious case 的 candidate
   PASS 率（0.1 / 0.3 / 0.6）系统性低于 baseline（0.9 / 1.0 / 1.0），且
   Wilson 95% 下限全部 < 0.5；candidate INC 率 0.9 / 0.7 / 0.4 全部超过
   0.1 的预注册上限。
2. **Delta 未达阈值**：三个 suspicious case 的 PASS 率 delta 为 -0.8 / -0.7 /
   -0.4，全部低于 -0.1。
3. **Sample sufficiency 未完整达标**：CAL-26 baseline arm 因 1 次 round-final
   TIMEOUT，n_contract = 9 < 10。

E.5 的“过度弃权风险”在本轮以 rate-level 形式稳定出现：candidate 在
TASK-JUDGE-01 / CAL-08 / CAL-18 上以 0.9 / 0.7 / 0.4 的高 INC 率弃权，不是
单次抖动。这正是不允许把 “E.6 = REGRESSION_SAFETY_CONFIRMED” 直接当作
Promotion 的原因：E.6 证明“没有稳定因果 regression”，E.7 证明“rate-level
行为还没有稳定到可以上线”。

### 为什么不是 REJECT

```text
candidate-induced regression  = 无（stable-PASS FAIL = 0，critical PASS = 0）
target fix 不成立              = 无（CAL-26 candidate INC 10/10）
candidate INVALID_OUTPUT       = 0/120 rounds
evidence integrity             = OK（policy frozen、artifacts 完整、secret scan clean）
E.6 gate                       = REGRESSION_SAFETY_CONFIRMED
```

## 7. E.5 / E.6 关系

- E.5 = INSUFFICIENT_EVIDENCE：既不能确认 no deterministic regression，也
  不能 REJECT。
- E.6 = REGRESSION_SAFETY_CONFIRMED：三个异常 case 无 candidate-induced
  regression；E.6 明确说明“不等于 promotion”。
- E.7 在 E.6 之上补上了 rate-level / sample / uncertainty 证据层，结论
  HOLD 与 E.6 的自我限制完全一致：**没有抓到 candidate 把东西搞坏，不等于
  有足够把握说这个新版本值得上线**。

## 8. Artifacts

```text
artifacts/promotion-gate/
  promotion-policy.json                        # mutable live copy（E.7 = registered bytes）
  promotion-policy-e7-v1-registered.json       # immutable registered policy（ca06a9a）
  promotion-policy-e7-v1-final.json            # audited final policy（E.7.1）
  promotion-manifest.json      # fixed conditions + schedule + policy provenance
  promotion-runs.jsonl         # 142 attempt rows（raw evidence 索引）
  promotion-matrix.json        # per-case / per-arm summary + delta
  promotion-stats.json         # statistical summary + rules
  promotion-gate.json          # final gate + blockers
  {case}-model_studio-{B,B-prime}-gate[-retryN]-rN.json   # 142 个 raw evidence
```

未覆盖 `candidate-eval/` 与 `regression-attribution/`。

## Policy lifecycle

E.7 registration:
- v1-registered（`promotion-policy-e7-v1-registered.json`）
- commit `ca06a9a`
- used for live experiment
- immutable historical evidence（E.7 matrix/stats/gate/runs 只引用 registered policy）

E.7.1 audit:
- final/audited revision（`promotion-policy-e7-v1-final.json`）
- declaration/provenance corrections only（rate documentation =
  `success_count / n_contract`；`target_fix_absent` explicitly declared）
- no threshold changes
- no live rerun
- Gate remains HOLD

## 9. Validation

```text
promotion gate offline tests  = 19 passed（tests/test_promotion_gate.py）
全量 evaluation tests         = 255 passed, 11 skipped, 8 subtests passed
py_compile                    = provider_probe / judge_provider /
                                phase6e_matrix / calibration / tests 全部通过
secret scan                   = rg -l -i "api_key|authorization|bearer |sk-[a-z0-9]{24,}"
                                artifacts/promotion-gate/ -> 0 命中
offline recompute             = temp-dir --summarize-promotion-gate：
                                GATE=HOLD, policy_frozen=True,
                                e6=REGRESSION_SAFETY_CONFIRMED；
                                gate.json byte-identical to 22890c1
                                （matrix/stats 仅 run_git_commit 为当前 HEAD，预期）
provenance                    = registered bytes == git show ca06a9a；
                                registered/final SHA256 == manifest；
                                final 仅声明/来源差异；mutable
                                promotion-policy.json 未归属 ca06a9a
```

## 10. Limitations

1. 单 provider / 单 model（model_studio / qwen3.7-plus）；结论不外推到其他
   backend。
2. Wilson CI 假设每轮独立二项 outcome；实际同 arm 连续调用存在时间相关
   风险，CI 仅作不确定性表达，不是因果检验。
3. CAL-26 baseline arm 样本不完整（1/10 transport），baseline 缺陷率
   的估计精度略降；不影响 HOLD 判定（suspicious rate rules 已独立失败）。
4. Controls n=5，作为环境漂移 sanity check 足够，不作为 rate 估计主体。
5. 只覆盖 target + 3 suspicious + 4 controls（8 case），不覆盖完整 44-case
   matrix；结论只回答这些 case 上的 promotion 证据强度。
6. E.6 的 strict-stable attribution policy（100% 稳定才算 CANDIDATE_REGRESSION）
   与 E.7 的 rate-level policy 是两层不同问题；本报告不把它们混用。

## 11. 停止条件

```text
GATE = HOLD
```

本阶段结束。不执行生产 promotion，不继续 E.8。若后续要解锁 Promotion，
方向是解决 candidate 在 stable-PASS case 上的过度弃权（CAL-08/18 的
SYSTEM_PROMPT_SNAPSHOT 误弃权机制，见 E.6 D.4），然后以同一 policy 重新
收集证据；而不是在本阶段补实验、改阈值。
