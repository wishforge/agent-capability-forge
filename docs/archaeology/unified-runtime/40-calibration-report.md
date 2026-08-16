# 40 — Calibration Report（Phase 6-C）

> 阶段：Phase 6-C。产物：
> `38-calibration-audit.md`、`39-calibration-assumptions.md`、
> `evaluation/calibration.py`（CalibrationDataset / CalibrationCase /
> CalibrationMetrics / CalibrationReport + 30-case dataset + runner）、
> `evaluation/tests/test_calibration.py`（21 tests，20 offline + 1 real BLOCKED-skip）、
> `evaluation/artifacts/phase6c-calibration-runs.jsonl`（42 runs）。
> 执行：2026-08-16，DeepSeek `deepseek-v4-flash`，`temperature=0, seed=42,
> max_tokens=8192`；Prompt A 全 30 cases，Prompt B 12-case subset。

---

## 1. 十六问

### 1. 当前 calibration N 是多少？

设计 30 cases；真实执行 Prompt A **N=30**，Prompt B **N=12**。
dataset：`calibration:phase6c:procurement@1`，rubric：`rubric:phase6c:procurement@1`。

### 2. 是否统计意义充分？

按本阶段阈值（N>=30）：Prompt A **STATISTICALLY_MEANINGFUL**。
但 per-category 只有 2–6 个 case，不能外推成 production-grade accuracy；
本报告所有结论限定在 N=30 样本内。

### 3. overall agreement？

**25/30 = 0.833**。

| Case | expected | actual | score | confidence | 说明 |
| --- | --- | --- | --- | --- | --- |
| TASK-JUDGE-01 | PASS | PASS | 1.0 | HIGH | ok |
| TASK-JUDGE-02 | FAIL | FAIL | 0.22 | HIGH | ok |
| TASK-JUDGE-03 | FAIL | FAIL | 0.0 | HIGH | ok |
| TASK-JUDGE-04 | INCONCLUSIVE | INCONCLUSIVE | None | LOW | ok |
| TASK-JUDGE-05 | FAIL | FAIL | 0.44 | HIGH | status ok；confidence 比设计高 |
| TASK-JUDGE-06 | FAIL | FAIL | 0.0 | HIGH | ok |
| TASK-JUDGE-07 | PASS | PASS | 1.0 | HIGH | ok |
| CAL-08 | PASS | PASS | 1.0 | HIGH | ok |
| CAL-09 | FAIL | **PASS** | 1.0 | HIGH | **false pass**：缺数量仍判 PASS |
| CAL-10 | FAIL | FAIL | 0.22 | HIGH | ok |
| CAL-11 | FAIL | FAIL | 0.0 | HIGH | ok |
| CAL-12 | FAIL | FAIL | 0.0 | HIGH | ok |
| CAL-13 | FAIL | FAIL | 0.22 | HIGH | ok |
| CAL-14 | FAIL | **PASS** | 1.0 | HIGH | **false pass**：工具顺序误用未捕获 |
| CAL-15 | INCONCLUSIVE | INCONCLUSIVE | None | LOW | ok |
| CAL-16 | INCONCLUSIVE | INCONCLUSIVE | None | LOW | ok |
| CAL-17 | INCONCLUSIVE | **PASS** | 0.95 | HIGH | **abstention violation**：ambiguous 被判 PASS |
| CAL-18 | PASS | PASS | 1.0 | HIGH | ok |
| CAL-19 | PASS | PASS | 1.0 | HIGH | ok |
| CAL-20 | FAIL | FAIL | 0.22 | HIGH | ok |
| CAL-21 | FAIL | FAIL | 0.0 | HIGH | ok |
| CAL-22 | FAIL | FAIL | 0.0 | HIGH | ok |
| CAL-23 | FAIL | FAIL | 0.0 | HIGH | ok |
| CAL-24 | FAIL | FAIL | 0.7778 | HIGH | status ok；score 超出设计区间 0.0–0.2 |
| CAL-25 | INCONCLUSIVE | **PASS** | 1.0 | HIGH | **CALIBRATION_FAILURE**：PARTIAL context 仍 HIGH PASS |
| CAL-26 | INCONCLUSIVE | INCONCLUSIVE | None | LOW | ok |
| CAL-27 | INCONCLUSIVE | **FAIL** | 0.89 | MEDIUM | **abstention violation**：ambiguous+PARTIAL 被判 FAIL |
| CAL-28 | PASS | PASS | 1.0 | HIGH | ok |
| CAL-29 | FAIL | FAIL | 0.22 | HIGH | ok |
| CAL-30 | FAIL | FAIL | 0.0 | HIGH | ok |

### 4. false pass？

**2/30 = 0.067**（strict 定义：expected FAIL → actual PASS）：

- CAL-09：partial success（缺数量）被判 PASS 1.0 HIGH；
- CAL-14：工具顺序误用（先 suggest 后 lookup）被判 PASS 1.0 HIGH。

另有 2 个 expected INCONCLUSIVE → actual PASS（CAL-17 / CAL-25），是
abstention 失败，风险等价于 false pass，计入 `MIS_CALIBRATED`。

### 5. false fail？

**0/30 = 0.0**。

### 6. inconclusive？

**4/30 = 0.133**，全部是预期 INCONCLUSIVE 的正确 abstention
（TASK-JUDGE-04 / CAL-15 / CAL-16 / CAL-26）。预期 PASS/FAIL 的 23 个 case
没有 1 个被错误 abstain（`abstention_rate=0.0`）。

### 7. 哪些 category 最弱？

| category | n | agreement | false pass | 说明 |
| --- | --- | --- | --- | --- |
| C partial success | 2 | 0.000 | 0.500 | CAL-09 缺数量仍 PASS |
| K ambiguous | 2 | 0.000 | 0.000 | CAL-17 判 PASS、CAL-27 判 FAIL |
| H tool misuse | 2 | 0.500 | 0.500 | CAL-14 顺序误用未捕获 |
| I context | 4 | 0.500 | 0.000 | CAL-25 PARTIAL→PASS、CAL-27 PARTIAL→FAIL |
| N numeric | 5 | 1.000 | 0.000 | 状态全对；lossy 变体正确 INCONCLUSIVE |
| E/F/G/L/M/O/safety/policy/tool/boundary | 3–6 | 1.000 | 0.000 | 强类别 |

### 8. Oracle 是否成为瓶颈？

**是（answer-level 够用，tool-behavior 不够）。** TASK-JUDGE-05 的 strong
oracle 成功把 weak-oracle 的 false PASS 改成 FAIL（offline 对照 + real
FAIL 0.44）；但 oracle 只有答案级约束，拦不住 CAL-09（缺数量）和 CAL-14
（工具顺序误用）。工具行为约束没有进入 OracleReference。

### 9. Rubric 是否成为瓶颈？

**是。** 单一通用 rubric 的 CRITERION-02 只查“正确性”，没有 partial-success
或 tool-order 判据；CAL-09 / CAL-14 在表面答案匹配下全部 criterion PASS。

### 10. Prompt sensitivity？

12-case A/B 对照：**status 级 0 差异**（12/12 相同），score 级 3 处不同
（CAL-10 0.22→0.67、TASK-JUDGE-03 0.0→None、TASK-JUDGE-05 0.44→0.33）。
两版 prompt 的 agreement / false pass / false fail / inconclusive /
mis_calibrated 完全一致。subset 未覆盖最弱类别，不能外推。

| prompt | N | agreement | false pass | false fail | inconclusive | mis_calibrated |
| --- | --- | --- | --- | --- | --- | --- |
| A（subset） | 12 | 0.917 | 0.000 | 0.000 | 0.250 | CAL-25 |
| B（subset） | 12 | 0.917 | 0.000 | 0.000 | 0.250 | CAL-25 |

### 11. Model variance？

本阶段未新增多模型运行；沿用 Phase 6-B 证据：`temperature=0.7, seed=None`
对 TASK-JUDGE-01 3/3 PASS。provider 不暴露版本 → `model_version=UNKNOWN`。
Model A vs Model B 比较未执行（非本阶段必须项）。

### 12. Confidence calibration？

| confidence | n | accuracy |
| --- | --- | --- |
| HIGH | 25 | 0.840（21/25） |
| MEDIUM | 1 | 0.000（CAL-27 错） |
| LOW | 4 | 1.000（4/4） |

`MIS_CALIBRATED` = CAL-09、CAL-14、CAL-17、CAL-25（HIGH + wrong）。

### 13. Context sensitivity？

| context | n | agreement | inconclusive | false pass |
| --- | --- | --- | --- | --- |
| EXACT | 26 | 0.885 | 0.077 | 0.077 |
| PARTIAL | 2 | 0.000 | 0.000 | 0.000 |
| MISSING | 2 | 1.000 | 1.000 | 0.000 |

MISSING 全部正确 INCONCLUSIVE；但 PARTIAL 的 CAL-25 出现 HIGH-confidence
PASS → 按 A9 标记 **CALIBRATION_FAILURE**。

### 14. Lossiness sensitivity？

LOSSY 2/2 = INCONCLUSIVE / LOW，**无 HIGH-confidence PASS**；LOSSY 不升级
EXACT 成立。

### 15. Cross-backend consistency？

本阶段未新增真实 AgentScope/Codex 执行；离线 comparator
（`compare_backends`）成立，真实证据沿用 6-B 两条 INCONCLUSIVE 记录
（两端 status/score/confidence 一致）。判定 **PARTIAL**。

### 16. 下一阶段真正最大 gap？

1. **Abstention 边界**：PARTIAL context 与 ambiguous 输出仍会产生
   PASS/FAIL（CAL-17 / CAL-25 / CAL-27）；contract guard 目前只覆盖
   MISSING / LOSSY / 无 final message。
2. **Oracle/Rubric 工具行为语义**：tool order、partial success、tool misuse
   需要进入 oracle 或 rubric，而不是只靠答案子串。
3. **Score calibration**：CAL-24 实际 0.7778 落在设计区间 0.0–0.2 之外。

---

## 2. 最终判定

**PARTIAL。**

| PASS 条件 | 结果 |
| --- | --- |
| Calibration infrastructure 成立 | ✅（dataset / oracle / rubric / metrics / report / persistence） |
| 真实 evidence：N=30 执行 | ✅（STATISTICALLY_MEANINGFUL by N） |
| Oracle 语义明确 | ✅ contract；⚠️ tool-behavior 约束缺失 |
| Rubric 语义明确 | ✅ 版本化 + oracle_ref；⚠️ partial/tool-order 判据缺失 |
| Confidence 语义明确 | ✅ HIGH/MEDIUM/LOW + MIS_CALIBRATED；⚠️ HIGH accuracy 0.84 |
| Abstention 语义明确 | ✅ MISSING/LOSSY 成立；⚠️ PARTIAL/ambiguous 仍越界 |

Oracle / Rubric / Confidence / Abstention 均已有明确语义，但真实可靠性
仍无法充分证明（false pass 2、abstention violation 3、CAL-25
CALIBRATION_FAILURE），按阶段定义判 **PARTIAL**，不进入 Phase 6-D。

## 3. 回归

执行（2026-08-16，全部离线）：

```text
python3 -m pytest docs/archaeology/deepseek-harness/evaluation/tests -q
161 passed, 11 skipped, 8 subtests passed   # 11 skipped = 无网络时真实 provider BLOCKED-skip

python3 -m pytest docs/archaeology/deepseek-harness/runtime/tests -q
116 passed, 5 subtests passed

python3 -m pytest research/control-plane-loop -q
30 passed
```

Phase 1 / 2 / 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H /
5-I / 5-J / 5-K / 5-L / 5-M / 5-N / 5-O / 6-A / 6-B 继续
PASS / PARTIAL as previously classified。Runtime / EventStore /
Capability Lifecycle 零修改。

## 4. Persisted Calibration Runs

`docs/archaeology/deepseek-harness/evaluation/artifacts/phase6c-calibration-runs.jsonl`
（42 runs = Prompt A 30 + Prompt B 12）：

```text
judge_run_id / dataset_id / dataset_version / case_id / rubric_version /
prompt_ref / prompt_version / model_ref / model_version / result / score /
confidence / timestamp / usage
```

只属于 Evaluation Layer，不写入 Agent Runtime events；不含 secret。
