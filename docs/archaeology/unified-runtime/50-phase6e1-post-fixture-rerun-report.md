# 50 — Phase 6-E.1-B Post-Fixture Controlled Rerun Report（TASK-JUDGE-01）

> 阶段：Phase 6-E.1-B（fixture 修正后的受控重跑）。
> Checkpoint：Phase 6-E = `4ea1352`；Fixture correction = `d987ed6`（当前 HEAD）。
> 日期：2026-08-17。不 commit、不 push。
> 约束遵守：未修改 implementation / `aggregate()` / guard / expected labels；
> 历史 Phase 6-E artifacts（`dataset_version=1`）未被覆盖（`git diff` 对 tracked
> 文件为空，历史文件时间戳与内容未变）。

## 1. Experiment setup

- 数据集：修正后 `calibration:phase6d:procurement` version = **2**
  （qty=10 族 task 文本改为 `目标采购数量 10`；CAL-20/26/29 切到
  `TASK_PROC_GAP`，`采购缺口 5 件`；oracle / records / expected labels 不变）。
- Cases：44（`PHASE6D_DATASET`，与 Phase 6-E 相同集合）。
- Prompts：A / B / C（`prompt:phase6b:judge:{A,B,C}:v1`）。
- Backends：
  - fake（offline 参照）；
  - DeepSeek `deepseek-v4-flash`（`https://api.deepseek.com/`）；
  - Model Studio `qwen3.7-plus`
    （`https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`）。
- 采样：`temperature=0`、`seed=42`。
- Oracle / evaluation policy：与 Phase 6-E 相同，未改动。
- 新增 artifacts（均为 v2，未覆盖 v1）：
  `artifacts/phase6e-{offline,deepseek,second}-44-{A,B,C}-v2.jsonl`、
  `artifacts/phase6e-{offline,deepseek,second}-probes-{A,B,C}-v2.jsonl`、
  retry 文件 `*-v2-retry[-2].jsonl`（deepseek B：CAL-25/CAL-36；
  model_studio A：CAL-25/CAL-26；model_studio B：CAL-16/CAL-26/CAL-44）。
- 每条 record 保存：`dataset_version` / `case_id` / `prompt_ref` /
  `backend_ref` / `evidence_sufficiency` / `oracle_status`（behavioral status，
  沿用既有 schema 字段名）/ `condition_statuses` / `deterministic_verdict` /
  `aggregation_source` / `result`（LLM result，沿用既有 schema 字段名）/
  `final_verdict` / `score` / `confidence`。未记录 secrets。

## 2. Dataset version transition 1 → 2

| 维度 | v1 | v2 |
| --- | --- | --- |
| dataset version | `calibration:phase6d:procurement@1` | `calibration:phase6d:procurement@2` |
| task 文本变化 | — | 36/44（qty=10 族 33，qty=5 族 3） |
| oracle / records / expected labels | — | 0 变化（49a 审计 + 本次离线重算一致） |
| deterministic 层 | 44/44 | 44/44 与 v1 完全一致 |
| 历史 artifacts | 原样保留 | 新增 `*-v2*.jsonl`，未改写 v1 文件 |

本次 9 组合重跑全部写入 `dataset_version=2` 记录；probe 记录为
`calibration:phase6e:probes@2`。

## 3. 44-case results

有效 44-case 数与 judge 层分布（P / F / I），v2：

| backend | prompt | 有效 | judge 层 | unified 层 |
| --- | --- | --- | --- | --- |
| fake | A | 44 | 8 / 24 / 12 | 7 / 29 / 8 |
| fake | B | 44 | 8 / 24 / 12 | 7 / 29 / 8 |
| fake | C | 44 | 8 / 24 / 12 | 7 / 29 / 8 |
| deepseek | A | 44 | 7 / 25 / 12 | 7 / 29 / 8 |
| deepseek | B | 44 | 7 / 25 / 12 | 7 / 29 / 8 |
| deepseek | C | 44 | 7 / 25 / 12 | 7 / 29 / 8 |
| model_studio | A | 44 | 7 / 25 / 12 | 7 / 29 / 8 |
| model_studio | B | 42 | 7 / 25 / 10 | 7 / 29 / 6 |
| model_studio | C | 44 | 7 / 25 / 12 | 7 / 29 / 8 |

v1 对应基线（仅列出与 v2 不同的行）：

| backend | prompt | 有效 | judge 层 | unified 层 |
| --- | --- | --- | --- | --- |
| deepseek | B | 44 | 6 / 25 / 13 | 6 / 29 / 9 |
| model_studio | B | 42 | 7 / 25 / 10 | 7 / 29 / 6 |

其余 7 个组合 v1 = v2。在 v1/v2 双方都有 final verdict 的 case 中，唯一
final-verdict 变化是 `deepseek B TASK-JUDGE-01: INCONCLUSIVE → PASS`；
另外存在 model_studio B 的 CAL-15/CAL-16 provider-availability transitions
（v1 TIMEOUT 缺记录 → v2 INCONCLUSIVE；v1 INCONCLUSIVE → v2 INVALID_OUTPUT
缺记录），见 §6。无 expected-label 翻转。

Deterministic 层跨 9 组合 agreement：`deterministic_status` /
`evidence_sufficiency` / `oracle_status` / `condition_verdict` /
`deterministic_verdict` 全部 = 1.000。

## 4. TASK-JUDGE-01 before / after

| 维度 | v1（fixture 冲突） | v2（修正后） |
| --- | --- | --- |
| task 文本 | `（目标库存 10，当前库存 5）` | `（目标采购数量 10，当前库存 5）` |
| deterministic_verdict | PASS | PASS |
| evidence / behavioral / conditions | SUFFICIENT / PASS / PASS | SUFFICIENT / PASS / PASS |
| DeepSeek B LLM raw status | INCONCLUSIVE | PASS |
| DeepSeek B final | INCONCLUSIVE（LLM_FALLBACK，score None，LOW） | **PASS（DETERMINISTIC，score 1.0，HIGH）** |
| DeepSeek B reasoning | “task states target stock 10, current stock 5, which implies correct procurement quantity should be 5, creating a direct [conflict]” | “procurement.suggest called with qty 10 … final message states 采购 10 件 … satisfies oracle expected answer … all rubric criteria pass” |
| 其余 8 组合 | 全部 PASS | 全部 PASS（不变） |

结论：修正后 DeepSeek B 不再产生数量冲突推理；raw PASS 与 deterministic PASS
一致，aggregation 回到 DETERMINISTIC。

## 5. CAL-20 / CAL-26 / CAL-29 before / after

| case | v1 各组合 | v2 各组合 | 说明 |
| --- | --- | --- | --- |
| CAL-20 | FAIL（DETERMINISTIC） | FAIL（DETERMINISTIC） | 不变；deepseek B score 0.22 两版一致 |
| CAL-26 | INCONCLUSIVE（DETERMINISTIC） | INCONCLUSIVE（DETERMINISTIC） | 不变；deterministic gate 语义，非 LLM 引入；model_studio B 两版均因 provider 失败缺该 case |
| CAL-29 | FAIL（DETERMINISTIC） | FAIL（DETERMINISTIC） | verdict 不变；deepseek B score 0.2222 → 0.22（LLM score 微差，不影响 verdict） |

这三个 case 的 task 文本在 v2 切换为 `TASK_PROC_GAP`
（`采购缺口 5 件`），与各自 `ORACLE_QTY5` 自洽；判定无变化，证明族级拆分
未引入回归。

## 6. Backend comparison

- v2 跨 backend 的 final-verdict pairwise agreement：prompt A = 0.9848
  （44 case），B = 0.9841（42 case），C = 0.9848（44 case）。
- 全部 mismatch 唯一来自 `TASK-JUDGE-03`：fake judge 层 PASS vs 真实
  backend FAIL——既有语义（RULE-05 在 unified 层强制 FAIL，fake 的
  judge-layer PASS 不是 Phase 6-E.1 回归）。
- v2 不存在“deterministic FAIL/INCONCLUSIVE 被 LLM 提升为 PASS”的 bypass；
  raw-vs-final 差异 13 条，全部为 DETERMINISTIC guard 纠正
  （evidence/behavioral gate 覆盖 LLM raw status），v1 为 15 条。
- LLM fallback 使用：v2 每个真实 backend×prompt 仅 1 case（TASK-JUDGE-03），
  fake 0；除 v1 DeepSeek B 的 TASK-JUDGE-01 外，其余真实 backend×prompt
  组合与 v1 真实行为一致（v1 DeepSeek B：42 DETERMINISTIC / 2
  LLM_FALLBACK，即 TASK-JUDGE-01、TASK-JUDGE-03）。
- Provider reliability：
  - deepseek B main：CAL-25 `ValueError`、CAL-36 `INVALID_OUTPUT` →
    `-v2-retry` 均恢复（INCONCLUSIVE/DETERMINISTIC）。
  - model_studio A main：CAL-25/CAL-26 `INVALID_OUTPUT` → `-v2-retry` 恢复。
  - model_studio B：CAL-16/CAL-26 `INVALID_OUTPUT`、CAL-44 `TIMEOUT`；
    retry 后 CAL-44 恢复（FAIL），CAL-16/CAL-26 持续失败 → 42/44，
    与 v1 的 model_studio B 持久失败模式（v1 缺 CAL-15/CAL-26）同级。
  - Probes：v1 model_studio C PROBE-S1 已有恢复后的最终 FAIL（score 0.0，
    见 `phase6e-second-probes-C-retry.jsonl`），v2 同样为 FAIL；其余 probe
    的 FINAL VERDICT v1 = v2——该相等仅指 FINAL VERDICT，LLM
    score/confidence/residual 元数据可能跨版本不同（与 §11.2 的
    score-variance caveat 一致）。

## 7. Prompt comparison

- v2 每个 backend 内 A/B/C 的 final-verdict pairwise agreement：
  fake = 1.000（44），deepseek = 1.000（44），model_studio = 1.000（42）。
- 跨 9 组合 overall pairwise agreement = 0.9881（42 个完整 case；
  mismatch 均为 TASK-JUDGE-03 fake-vs-real）。
- 不再存在 deepseek Prompt B 独有的 INCONCLUSIVE；Prompt B 敏感性在 v2
  下未复现。

## 8. Root-cause conclusion

**fixture ambiguity was the primary cause.**

依据：TASK-JUDGE-01 deterministic PASS + fixture version 2 + DeepSeek B
final PASS（DETERMINISTIC，raw PASS）。v1 的 INCONCLUSIVE 直接来自 LLM 对
`目标库存 10，当前库存 5` 推导出“应采购 5”的冲突推理；v2 文本改为
`目标采购数量 10` 后，同一 backend/prompt/temperature/seed 下推理不再冲突，
raw status 为 PASS，且与 deterministic PASS 一致。

## 9. Is Authoritative PASS policy still needed?

**不需要（不进入 Phase 6-E.1 Authoritative PASS Policy Implementation）。**

按判别规则：deterministic PASS + fixture version 2 + DeepSeek B final PASS
→ 记录“fixture ambiguity was the primary cause”，不实现 Authoritative PASS
policy。残余说明：单个 rerun 不能排除极端偶然的 prompt sensitivity，但当前
9 组合矩阵已无 deterministic-PASS→INCONCLUSIVE downgrade；若未来再次出现
同类 downgrade，再单独评估 policy。

## 10. Regression

| 套件 | 命令 | 结果（新 baseline） |
| --- | --- | --- |
| evaluation | `pytest docs/archaeology/deepseek-harness/evaluation/tests -q` | 218 passed, 11 skipped, 8 subtests（= 49a 修正后 baseline） |
| runtime | `pytest docs/archaeology/deepseek-harness/runtime/tests -q` | 116 passed, 5 subtests（不变） |
| control-plane-loop | `pytest research/control-plane-loop -q` | 30 passed（不变） |
| compileall | `python3 -m compileall -q docs/archaeology/deepseek-harness/evaluation docs/archaeology/deepseek-harness/runtime research/control-plane-loop` | pass |

工作区：tracked 文件 `git diff` 为空；未 commit、未 push；历史 v1 artifacts
未修改。

## 11. Remaining gaps

1. model_studio B 仍缺 CAL-16/CAL-26（`INVALID_OUTPUT`，low-confidence PASS
   forbidden），与 v1 的 CAL-26 持久失败同类；该组合无法给出 44/44。
2. score / confidence 在真实 LLM rerun 间存在少量非 verdict 差异
   （deepseek/model_studio 若干 case score 变化；7 条 confidence 变化，
   含 TASK-JUDGE-01 LOW→HIGH 随 verdict 翻转）；不进入判定层。
3. 每组合单次 rerun；`temperature=0/seed=42` 已记录，但真实 provider 的
   重复性未做多轮统计。
4. CAL-20/26/29 是否并入 qty=10 族仍是 49 §10 的可选后续，不阻塞。
5. TASK-JUDGE-03 judge-layer fake PASS vs 真实 FAIL 保持既有语义
   （unified FAIL），非本阶段回归。

## Final verdict

```text
FIXTURE ISSUE RESOLVED
```
