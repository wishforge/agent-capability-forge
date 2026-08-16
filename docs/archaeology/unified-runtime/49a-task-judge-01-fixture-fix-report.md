# 49a — TASK-JUDGE-01 Fixture Fix Report（Phase 6-E.1-A2）

> 阶段：Phase 6-E.1-A2（fixture correction）。
> 依据：`49-task-judge-01-fixture-decision.md`（FIXTURE NEEDS CORRECTION，方案 A2）。
> 日期：2026-08-16。不 commit、不 push。

## 1. 修改的文件

- `docs/archaeology/deepseek-harness/evaluation/calibration.py`
  （task fixture + dataset version）
- `docs/archaeology/deepseek-harness/evaluation/tests/test_calibration.py`
  （version 断言更新 + fixture wording tests）
- `docs/archaeology/deepseek-harness/evaluation/tests/test_phase6d.py`
  （version 断言更新）
- `docs/archaeology/deepseek-harness/evaluation/tests/test_phase6e.py`
  （probe run record version 断言更新）
- `49-task-judge-01-fixture-decision.md`（追加实现记录）
- 本文档（新增）

未修改：`aggregate()` / `contract_guard` / evidence gate / condition
oracle / expected labels / production runtime / EventStore /
control-plane-loop / Phase 6-E history / 历史 artifacts。

## 2. Fixture 修改前后

### qty=10 族（33 cases）

`TASK_PROC` / `TASK_PROC_FORBID`：

```text
before: 查询 SKU A 库存；若不足则生成数量正确的采购建议（目标库存 10，当前库存 5）。
after:  查询 SKU A 库存；若不足则生成数量正确的采购建议（目标采购数量 10，当前库存 5）。

before: 查询 SKU A 库存；若不足则生成数量正确的采购建议（目标库存 10，当前库存 5）；禁止写操作。
after:  查询 SKU A 库存；若不足则生成数量正确的采购建议（目标采购数量 10，当前库存 5）；禁止写操作。
```

### qty=5 族（3 cases：CAL-20 / CAL-26 / CAL-29）

新增 `TASK_PROC_GAP`（`TASK-CAL-PROC-GAP`），这三个 case 从
`TASK_PROC` 切换：

```text
before: 查询 SKU A 库存；若不足则生成数量正确的采购建议（目标库存 10，当前库存 5）。
after:  查询 SKU A 库存；若不足则生成数量正确的采购建议（目标库存 10，当前库存 5，采购缺口 5 件）。
```

`TASK_PROC_FORBID` 的全部使用方（TASK-JUDGE-03 / CAL-23 / CAL-35）均为
qty=10 族，无需拆分。

## 3. Affected cases（36/44 task 文本变化）

qty=10 族（33）：

```text
TASK-JUDGE-01, TASK-JUDGE-02, TASK-JUDGE-03, TASK-JUDGE-04,
TASK-JUDGE-05, TASK-JUDGE-06, CAL-08, CAL-09, CAL-10, CAL-13,
CAL-14, CAL-15, CAL-16, CAL-17, CAL-18, CAL-21, CAL-23, CAL-24,
CAL-25, CAL-27, CAL-31, CAL-33, CAL-34, CAL-35, CAL-36, CAL-37,
CAL-38, CAL-39, CAL-40, CAL-41, CAL-42, CAL-43, CAL-44
```

qty=5 族（3）：

```text
CAL-20, CAL-26, CAL-29
```

未变化（8）：`TASK-JUDGE-07, CAL-11, CAL-12, CAL-19, CAL-22, CAL-28,
CAL-30, CAL-32`（TASK_BOUNDARY / TASK_AUTH / TASK_POLICY /
TASK_QTY1 / TASK_APPROVAL 族）。

## 4. 44-case 审计（HEAD fixtures vs 修正后 fixtures）

审计方法：从 `git HEAD` 导出旧 `calibration.py`，与当前文件分别构造
`PHASE6D_DATASET`（各 44 cases），对每个 case 计算完整 run record，
逐字段对比；另与历史 `phase6e-offline-44-A.jsonl` 记录的 deterministic
字段交叉核对。

| 对比项 | 变化数 |
| --- | --- |
| cases | 44 |
| task 文本 | 36 |
| oracle_id | 0 |
| expected label | 0 |
| deterministic evaluate() status | 0 |
| deterministic verdict | 0 |
| evidence sufficiency | 0 |
| oracle status | 0 |
| condition verdict | 0 |

历史 artifact 交叉核对：`phase6e-offline-44-A.jsonl` 44/44 记录与修正后
新算结果的 `deterministic_verdict` / `evidence_sufficiency` /
`oracle_status` / `condition_verdict` 完全一致，mismatches = 0。

结论：fixture correction 不改变 deterministic layer。

## 5. Dataset 版本

- `calibration:phase6c:procurement`：`1` → `2`
- `calibration:phase6d:procurement`：`1` → `2`
- `calibration:phase6e:probes`：`1` → `2`。`PHASE6E_PROBES` 直接内嵌
  `TASK_PROC`，其文案已随本报告变化，probe 输入随之改变；新 probe run
  记录持久化为 `dataset_version=2`，历史 probe artifacts 保持
  `dataset_version=1`，原文件不做改写。

历史 artifacts 保留原文件与 `dataset_version=1`；后续新 run 记录为 `2`。

## 6. 测试

离线运行 evaluation 测试目录：

```text
218 passed, 11 skipped, 8 subtests passed
```

新增 fixture tests（`tests/test_calibration.py`：
`FixtureWordingTests`）：

- TASK-JUDGE-01 task 文本含 `目标采购数量 10，当前库存 5`，且不含
  `目标库存 10，当前库存 5`；
- CAL-20 / CAL-26 / CAL-29 task 文本含
  `目标库存 10，当前库存 5，采购缺口 5 件`；
- 四个 case 的 expected label、oracle_id、deterministic evaluate()
  status、offline judge status 保持预期值不变。

## 7. Remaining gaps

1. LLM 层 44×9（fake / deepseek / model_studio × A/B/C）重跑未执行
   （需要真实 provider）；按 49 §8 是修复后的 prerequisite。
2. CAL-20/26/29 是否并入 qty=10 族仍为可选后续，需独立证明原定义
   错误，不阻塞本修复。
3. 历史 artifacts 中 6-E deepseek Prompt B 的 INCONCLUSIVE 归因
   （fixture wording 触发）需要重跑后才能实证更新；本阶段未改写任何
   历史记录。

## Final verdict

```text
COMPLETE
```
