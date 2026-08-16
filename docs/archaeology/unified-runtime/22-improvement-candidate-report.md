# 22 — Improvement Candidate Report（Phase 5-L）

> 阶段：Phase 5-L。产物：
> `20-improvement-audit.md`、`21-improvement-candidate-assumptions.md`、
> `evaluation/improvement_candidate.py`（Candidate layer）、
> `evaluation/tests/test_improvement_candidate.py`（15 tests）。
> 未实现 LLM improvement generator / prompt rewrite / skill rewrite / code
> mutation / auto apply / Regression engine / promotion / canary / rollback；
> 未修改 Runtime / EventStore / Evaluator rules / models。

## 1. Candidate 是否严格来源于 FailureAttribution？

**是。** `propose()` 只接受 `FailureAttribution`，且强制：

- `failure_id` 存在且不是 `NO_FAILURE`；
- `evidence_refs` 非空；
- `source_execution_ids` 与 `source_evaluation_ids` 存在。

无失败证据直接 `ValueError`；`source_failure_ids` / `source_execution_ids` /
`evidence_refs` 全部由 attribution 派生，不另造来源。

## 2. 是否必须有 baseline？

**是。** `baseline_ref` 必填；空值 `ValueError`；`baseline_ref="UNKNOWN"` ⇒
`status=INVALID_FOR_REGRESSION`。没有 baseline 的 candidate 不能进入
Regression，不猜。

## 3. Candidate 与 Applied Change 是否分离？

**是。** `ImprovementCandidate` 只有不可变 metadata：无 `apply` /
`promote` / `rollback` 方法，不写文件、不 import runtime。候选永远是
proposal，只有未来的 Regression / Promotion 才能让它变成 applied change。

## 4. Candidate 是否可跨 Backend？

**是。** AgentScope / Codex 走同一个 `propose()` 与同一 dataclass shape；
backend 差异只出现在 `evidence_refs` / backend refs / `source_mapping_quality`
（EXACT vs LOSSY），不影响字段结构。

## 5. Lossiness 是否透明？

**是。** `source_mapping_quality` 继承 `attribution.mapping_quality`；LOSSY
不因 Candidate 层变 EXACT；`test_lossy_candidate_visible` 覆盖。

## 6. Missing owner/initiator 如何处理？

允许生成，但 `attribution_status=ATTRIBUTION_INCOMPLETE`；不伪造、不阻断
proposal。`test_missing_owner_allowed_but_incomplete` /
`test_missing_initiator_allowed_but_incomplete` 分别覆盖。

## 7. Multiple failure 如何避免错误归因？

`failure_kind=MULTIPLE_CANDIDATES` ⇒ `status=REQUIRES_DISAMBIGUATION`；不
自动选 primary、不猜 root cause、不强行合并成单一 candidate；`source_failure_ids`
保留 attribution 的 composite failure_id。

## 8. 是否完全不修改 Runtime？

**是。** 只新增 `evaluation/improvement_candidate.py` +
`evaluation/tests/test_improvement_candidate.py` + 3 份 unified-runtime 文档；
Runtime / EventStore / recovery / Evaluator rules / models 一行未改。

## 9. 是否已经可以被 Regression 消费？

**可以（contract 层面）。** Candidate 已携带 Regression 所需字段：
`baseline_ref` / `target_type` / `target_ref` / `change_type` / `change_ref` /
evidence refs / `status`。`REQUIRES_DISAMBIGUATION` 与
`INVALID_FOR_REGRESSION` 必须被排除；Regression engine 本身未实现
（Phase 6 边界）。

## 10. 最大剩余 Improvement Gap 是什么？

1. 状态转换引擎：VALIDATED / PROMOTED / ROLLED_BACK 只定义不实现。
2. Evaluation identity：`EvaluationResult` 无 `evaluation_id`，
   `source_evaluation_ids` 需显式传入（Evaluation 身份仍 PARTIAL）。
3. Change artifact registry：`change_ref` 只是引用，无具体版本对象。
4. 完整 request-time context snapshot 仍 PARTIAL（显式标记）。
5. 无存储格式、无 Regression engine、无 promotion / canary / rollback。

## 最终判定

**PASS**

- Candidate contract 完整（最小字段 + 状态集合 + change type 白名单）；
- 来源可追溯（failure / evaluation / execution refs 全必填）；
- baseline 明确（UNKNOWN ⇒ INVALID_FOR_REGRESSION）；
- target 明确（target_type / target_ref 必填）；
- hypothesis 与 fact 分离（字段语义 + "VERIFIED" 拒绝）；
- expected effect 明确（QUALITATIVE_ONLY / METRIC_DRIVEN，禁止伪造数值）；
- lossiness 可见；attribution 不完整时不伪造（ATTRIBUTION_INCOMPLETE）；
- candidate 不自动应用（无 apply / promote / rollback）；
- Regression 可直接消费（字段齐备；engine 未实现）；
- Core Runtime 不变。

## 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | PASS（未触碰） |
| Phase 2 kernel | PASS（未触碰） |
| Phase 4-A / 4-B / 4-C / 4-D runtime suite | PASS |
| Phase 5-B.1 / 5-C / 5-D / 5-F / 5-H runtime suite（116 tests） | PASS |
| Phase 5-I / 5-J / 5-K / 5-L evaluation suite（62 tests：17+15+15+15） | PASS |

```bash
PYTHONPYCACHEPREFIX=/private/tmp/phase5l-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
PYTHONPYCACHEPREFIX=/private/tmp/phase5l-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/evaluation/tests \
  -p 'test_*.py' -q
```

按阶段指令，完成后停止：不进入 Phase 5-M / LLM improvement generator /
Regression engine / Promotion。
