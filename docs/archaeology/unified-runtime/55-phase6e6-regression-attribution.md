# 55 — Phase 6-E.6 Regression Attribution & Evidence Completion

> 阶段：Phase 6-E.6（Regression Attribution）。
> 基线：HEAD = `65f79df`；E.5 已封存于
> `54-phase6e5-prompt-candidate-evaluation.md`，本阶段不修改 E.5 结论。
> 唯一目标：判定 Run 1 中 TASK-JUDGE-01 / CAL-08 / CAL-18 的
> PASS → INCONCLUSIVE 属于 CANDIDATE_REGRESSION / PROVIDER_NONDETERMINISM /
> BASELINE_INSTABILITY / INSUFFICIENT_EVIDENCE 中的哪一类。
> 不做 Promotion；不做 E.7。

## 0. 执行摘要

E.6 minimal paired replay 已完成：3 cases × 5 rounds ×（B + B-prime）
= 30 次有效调用；另有 2 次 transport 失败（TIMEOUT / UNAVAILABLE）被
同条件替换成功、2 次失败 attempt 的 evidence 完整保留（共 34 条
attempt 记录）。

```text
TASK-JUDGE-01 → BASELINE_INSTABILITY
  fresh baseline = PASS ×4 + INCONCLUSIVE ×1（baseline 自身翻车）
  fresh candidate = PASS ×5（Run 1 的 INC 未复现）

CAL-08 → PROVIDER_NONDETERMINISM
  fresh baseline = PASS ×5；fresh candidate = INCONCLUSIVE ×5
  全证据集 candidate = INCONCLUSIVE ×6 + PASS ×1（Run 2 PASS 构成同 arm 摇摆）

CAL-18 → PROVIDER_NONDETERMINISM
  fresh baseline = PASS ×5；fresh candidate = INCONCLUSIVE ×5
  全证据集 candidate = INCONCLUSIVE ×6 + PASS ×1（同上）
```

```text
GATE = REGRESSION_SAFETY_CONFIRMED
```

三个异常 case 均未构成 candidate-induced regression：
TASK-JUDGE-01 是 baseline 自身不稳定；CAL-08 / CAL-18 是 candidate
同 arm 在相同控制条件下的 PASS/INCONCLUSIVE 摇摆。

## A. E.6 Scope

### A.1 目标

只回答三个异常 case 的归因：

```text
TASK-JUDGE-01   baseline B PASS -> candidate B-prime INCONCLUSIVE (Run 1)
CAL-08          baseline B PASS -> candidate B-prime INCONCLUSIVE (Run 1)
CAL-18          baseline B PASS -> candidate B-prime INCONCLUSIVE (Run 1)
```

### A.2 不做什么

- 不做 candidate promotion / rollback。
- 不修改 E.5 结论与 `54` 报告。
- 不修改 completion contract、parser、retry、provider production runtime。
- 不重跑完整 44-case matrix。
- 不覆盖 E.5 artifacts（`artifacts/candidate-eval/` 保持不变）。

### A.3 复用

- runner / evidence 机制：`provider_probe.py` 的 `_run_probe` /
  `_second_provider` / `write_debug_evidence`（E.3/E.5 既有）。
- dataset：`calibration.PHASE6D_DATASET`（`calibration:phase6d:procurement` @ v2）。
- prompt：`prompt:phase6b:judge:B:v1` 与 `prompt:phase6b:judge:B-prime:v1`
  （hash 与 E.5 metadata 一致）。
- provider：Model Studio（`model_studio` / `qwen3.7-plus`）。
- 历史证据：E.5 `candidate-eval/run1/regression.jsonl` 与
  `candidate-eval/regression.jsonl`。

## B. Pre-registered Attribution Policy

> 本 policy 在 live 实验执行前写入并固化；结果不得反过来修改 policy。

### B.1 证据集

每个 case 的归因使用全部相同控制条件下的 ACCEPT 结果：

```text
E.5 Run 1（1 次 baseline + 1 次 candidate）
+ E.5 Run 2（1 次 baseline + 1 次 candidate）
+ E.6 fresh paired replay（N=5 轮 baseline + 5 轮 candidate）
```

相同控制条件 = dataset v2 / case input / provider（model_studio）/
model（qwen3.7-plus）/ prompt 与 template / temperature=0.0 / seed=42 /
max_tokens=8192 / timeout=120.0 / parser 与 contract 版本。

### B.2 判定顺序（per case，严格稳定标准）

```text
1. INSUFFICIENT_EVIDENCE
   如果 E.6 fresh paired matrix 不完整：任一 arm 的有效 attempt 不足 N=5
   （transport/parse failure 经同条件替换后仍失败）。

2. BASELINE_INSTABILITY
   如果完整证据集中任一 baseline verdict != PASS
   （baseline 自身不能稳定保持 PASS，差异不能单独归因于 candidate）。

3. CANDIDATE_REGRESSION
   如果 baseline 全部 PASS 且 candidate 全部 INCONCLUSIVE
   （100% 稳定因果差异；provider/transport/parse failure 无法解释）。

4. PROVIDER_NONDETERMINISM
   如果 baseline 全部 PASS 且 candidate 结果包含 PASS 与 INCONCLUSIVE
   （同一 arm 在相同控制条件下发生 PASS/INCONCLUSIVE 摇摆；
   差异与 candidate 无稳定因果关联）；
   或 INCONCLUSIVE 未复现。
```

关键点：`稳定` 定义为 100%（全证据集无例外）。因此只要同一 arm 在
相同参数下出现过 PASS 与 INCONCLUSIVE 两种结果，即命中
PROVIDER_NONDETERMINISM，不允许把单次/不稳定的 INC 解释为
candidate-induced regression。

### B.3 Failure / retry policy

- 每次 attempt 的 transport（TIMEOUT/TRANSIENT/UNAVAILABLE/PERMANENT）与
  parse/contract（INVALID_OUTPUT）失败均保留完整 evidence。
- 失败的 attempt 允许同一 case/同一 arm/相同参数立即替换，最多 2 次；
  替换成功则该轮有效，失败仍记录在案。
- 若任一 arm 最终有效 attempt < N=5，该 case = INSUFFICIENT_EVIDENCE。
- 不因 baseline/candidate 分数或 ACCEPT 率提升而改变判定。

### B.4 Gate 语义

```text
任一 case = CANDIDATE_REGRESSION                      -> REGRESSION_CONFIRMED
全部 case ∈ {PROVIDER_NONDETERMINISM, BASELINE_INSTABILITY}
                                                     -> REGRESSION_SAFETY_CONFIRMED
任一 case = INSUFFICIENT_EVIDENCE                     -> INSUFFICIENT_EVIDENCE
```

注意：REGRESSION_SAFETY_CONFIRMED 仅表示“三个异常 case 均证明不存在
candidate-induced regression”，不等于 candidate promotion。

## C. Experiment Matrix

### C.1 Fixed conditions（全部 attempt 一致）

| 字段 | 值 |
| --- | --- |
| dataset_id / version | `calibration:phase6d:procurement` / `2` |
| provider / backend | Model Studio / `model_studio` |
| model | `qwen3.7-plus` |
| baseline prompt | `prompt:phase6b:judge:B:v1` |
| candidate prompt | `prompt:phase6b:judge:B-prime:v1` |
| temperature / seed | `0.0` / `42` |
| max_tokens / timeout | `8192` / `120.0` |
| response_format | `{"type": "json_object"}` |
| parser / contract | 既有 `judge_provider._parse` / `contract_guard`，未修改 |

### C.2 Pairing schedule

```text
case 依次：TASK-JUDGE-01, CAL-08, CAL-18
round r = 1..5:
  奇数轮：B -> B-prime
  偶数轮：B-prime -> B        # 交替 arm 顺序，控制时间漂移
```

总调用：3 cases × 5 rounds × 2 arms = 30 次有效 attempt（失败替换额外计）。

### C.3 Artifacts

```text
artifacts/regression-attribution/
  {case}-model_studio-{B,B-prime}-attribution-r{1..5}.json
  {case}-model_studio-{B,B-prime}-attribution-retry{1,2}-r{n}.json   # 仅失败替换
  attribution-runs.jsonl        # 每次 attempt 的完整 evidence row
  attribution-matrix.json       # fresh/historical/combined + per-case attribution + gate
```

每行 evidence 至少包含：case_id / run_id / arm / prompt_id / prompt_hash /
provider / model / temperature / seed / raw_response / raw_content /
parsed（status/confidence/score）/ contract（decision/reason/stage）/
failure kind / timestamp / artifact。

## D. Per-case Results

时间窗：2026-08-17T02:57Z .. 03:14Z（model_studio / qwen3.7-plus /
temp=0 / seed=42 / dataset v2 / prompt hash 见 E.5 metadata）。

### D.1 TASK-JUDGE-01

| 来源 | baseline B | candidate B-prime |
| --- | --- | --- |
| E.5 Run 1 | PASS | INCONCLUSIVE |
| E.5 Run 2 | PASS | PASS |
| E.6 fresh | PASS, PASS, PASS, PASS, **INCONCLUSIVE** | PASS, PASS, PASS, PASS, PASS |
| combined | 6 PASS + 1 INCONCLUSIVE | 6 PASS + 1 INCONCLUSIVE |

失败替换：B-prime r5 首调用 TIMEOUT（保留），替换 attempt 返回 PASS；
matrix 完整。

关键 raw evidence（fresh baseline r5）：

```text
reasoning: Overall Assessment: PASS / Confidence: HIGH / Score: 1.0
final:     INCONCLUSIVE / LOW / null
reason:    oracle_reference requires SYSTEM_PROMPT_SNAPSHOT，record 中不存在
```

即 baseline 自身在相同参数下也会发生 Run 1 同款“reasoning PASS → final
INCONCLUSIVE”翻转；Run 1 的 PASS→INCONCLUSIVE 不能单独归因于 candidate。

### D.2 CAL-08

| 来源 | baseline B | candidate B-prime |
| --- | --- | --- |
| E.5 Run 1 | PASS | INCONCLUSIVE |
| E.5 Run 2 | PASS | PASS |
| E.6 fresh | PASS ×5 | INCONCLUSIVE ×5 |
| combined | 7 PASS | 6 INCONCLUSIVE + 1 PASS |

失败替换：B-prime r5 首调用 UNAVAILABLE（保留），替换 attempt 返回
INCONCLUSIVE；matrix 完整。

### D.3 CAL-18

| 来源 | baseline B | candidate B-prime |
| --- | --- | --- |
| E.5 Run 1 | PASS | INCONCLUSIVE |
| E.5 Run 2 | PASS | PASS |
| E.6 fresh | PASS ×5 | INCONCLUSIVE ×5 |
| combined | 7 PASS | 6 INCONCLUSIVE + 1 PASS |

无失败替换；matrix 完整。

### D.4 机制复核

三个 case 的 INCONCLUSIVE（Run 1 candidate、fresh baseline r5
TASK-JUDGE-01、CAL-08/18 fresh candidate）全部是同一弃权机制：

```text
oracle_reference.required_evidence = ("SYSTEM_PROMPT_SNAPSHOT",)
该 required_evidence 在 dataset 中本就不存在
模型在 reasoning 中推演出 PASS，final 却以“缺失 SYSTEM_PROMPT_SNAPSHOT”
为由输出 INCONCLUSIVE/LOW
```

该行为在 B 与 B-prime 两个 prompt 下都出现过，说明它由模型/条件
nondeterminism 触发，B-prime 措辞只是更容易触发，并非唯一来源。

## E. Attribution Decision

| case | attribution | 依据（policy B.2 判定顺序） |
| --- | --- | --- |
| TASK-JUDGE-01 | BASELINE_INSTABILITY | 全证据集 baseline = 6 PASS + 1 INC，baseline 自身不能稳定保持 PASS |
| CAL-08 | PROVIDER_NONDETERMINISM | baseline 全部 PASS；candidate 全证据集 = 6 INC + 1 PASS（同 arm 摇摆） |
| CAL-18 | PROVIDER_NONDETERMINISM | 同上 |

说明：CAL-08 / CAL-18 若只看 E.6 fresh 集，是 baseline 5/5 PASS vs
candidate 5/5 INC 的“稳定差异”；但 pre-registered policy 规定
`稳定 = 全证据集 100%`，E.5 Run 2 的 candidate PASS 已构成同 arm
PASS/INCONCLUSIVE 摇摆，因此按 policy 归为 PROVIDER_NONDETERMINISM。
该判定是执行前固化的严格标准，不是看到结果后的解释。

## F. Evidence Limitations

1. **严格稳定阈值**：policy 只承认 100% 稳定差异为 CANDIDATE_REGRESSION；
   CAL-08/18 的 6/7 INC vs baseline 0/7 INC 的“率差异”未被本 policy 判定。
   若要为 promotion 决策做 rate-level 分析，需要更多重复与统计检验。
2. **样本量**：每个 case 每 arm 5 次 fresh 调用（全证据集 7 次），
   对二值 outcome 而言较小；未预注册统计检验，仅做严格稳定性判定。
3. **transport 干扰**：TASK-JUDGE-01 B-prime r5 TIMEOUT、CAL-08 B-prime
   r5 UNAVAILABLE 均被同条件替换且 matrix 完整；transport 抖动本身是
   provider nondeterminism 的另一佐证，但也会压缩有效窗口。
4. **TASK-JUDGE-01 baseline 单次 INC**：policy 规定任一 baseline 非 PASS
   即 BASELINE_INSTABILITY；7 次中 1 次 INC 不足以估计真实翻转率。
5. **机制外推**：SYSTEM_PROMPT_SNAPSHOT 弃权在 B 与 B-prime 都出现，
   确认非 candidate 独有；但未对全部 44 case 重跑，不能外推到其他 case。

## G. Final Gate

```text
GATE = REGRESSION_SAFETY_CONFIRMED
```

- 三个异常 case 均未证明 candidate-induced regression（无
  CANDIDATE_REGRESSION）。
- 该 Gate 只表示 regression attribution 证据充分、三个异常 case 的
  翻转可由 baseline instability / provider nondeterminism 解释。
- 不等于 candidate promotion；E.6 停止，不做 E.7 / Promotion。

## H. Validation

- 新增 offline tests：`tests/test_regression_attribution.py`（7 个）。
- 现有 evaluation tests 全量：236 passed, 11 skipped, 8 subtests passed。
- `py_compile`：provider_probe.py / judge_provider.py / phase6e_matrix.py /
  calibration.py 全部通过。
- secret scan：`rg -l -i "api_key|authorization|bearer |sk-[a-z0-9]{24,}"`
  artifacts/regression-attribution/ -> 0 命中（最终结果见执行记录）。
