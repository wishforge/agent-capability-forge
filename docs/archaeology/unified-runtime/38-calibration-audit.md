# 38 — Calibration Audit（Phase 6-C）

> 阶段：Phase 6-C。实现前/并行审计：把 Phase 6-B 的 7-case probe 升级为可
> 测量、可校准、可版本化的 calibration infrastructure。
> 输入：32 / 33 / 34 / 35 / 36 / 37、
> `evaluation/llm_judge.py` / `judge_provider.py` / `calibration.py` /
> `tests/test_calibration.py`、`artifacts/phase6b-judge-runs.jsonl`。
> 状态词：AVAILABLE / PARTIAL / MISSING。

---

## 1. Calibration Audit

| 审计项 | 状态 | 证据 / 缺口 |
| --- | --- | --- |
| calibration cases | AVAILABLE（设计 30；真实执行见 40） | `CalibrationDataset` 30 cases，含 6-B 的 TASK-JUDGE-01..07；A–O 全类别覆盖 |
| oracle quality | AVAILABLE（contract）/ PARTIAL（真实消费） | `OracleReference` 支持 expected_answer / required_conditions / forbidden_conditions / tolerance / acceptable_alternatives / expected_constraints；真实 judge 对新字段的消费待 6-C 实测 |
| rubric quality | AVAILABLE | `JudgeRubric` 版本化；每个 `JudgeCriterion` 带 `oracle_ref`；pass/fail threshold 与 required/weight 语义保留 |
| expected labels | AVAILABLE | 每个 case 有 expected_status ∈ {PASS, FAIL, INCONCLUSIVE} |
| expected score range | AVAILABLE | 每个可判定 case 有 expected_score_range（如 0.8–1.0、0.0–0.2） |
| confidence | AVAILABLE | expected_confidence_range ∈ HIGH/MEDIUM/LOW；PASS+LOW 与 INCONCLUSIVE+HIGH 构造时拒绝 |
| sample size | PARTIAL | 30 designed；真实执行 N 见 40；N<30 一律 `INSUFFICIENT_SAMPLE` |
| class balance | AVAILABLE（设计） | expected 6 PASS / 17 FAIL / 7 INCONCLUSIVE；PASS 占比 < 50%，避免 100% PASS 数据集 |
| edge cases | AVAILABLE | boundary（M）、ambiguous（K）、multiple valid（L）、numeric（N）、misleading fluent（O）均有 fixture |
| context completeness | AVAILABLE | EXACT / PARTIAL / MISSING 三组；PARTIAL 允许 INCONCLUSIVE/LOW，MISSING 强制 INCONCLUSIVE |
| lossiness | AVAILABLE | LOSSY critical evidence 由 fake judge 与 provider contract guard 强制 INCONCLUSIVE/LOW |
| cross-backend coverage | PARTIAL | 离线 comparator + 6-B 的 AgentScope/Codex 各 1 条 INCONCLUSIVE 证据；本阶段未新增真实 cross-backend 执行 |

## 2. 结论

```text
Dataset / Oracle / Rubric / Metrics / Abstention / Persistence -> AVAILABLE
Real executed sample                           -> PARTIAL（N 见 40）
Cross-backend real evidence                    -> PARTIAL（沿用 6-B 2 runs）
```

Calibration infrastructure 成立；是否 statistically meaningful 取决于真实执行 N。
