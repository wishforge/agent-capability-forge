# 45 — Phase 6-D.3 Condition-Level Oracle Implementation Report

> 阶段：Phase 6-D.3（实现）。前置：44 号设计 `READY FOR IMPLEMENTATION`。
> 范围：`docs/archaeology/deepseek-harness/evaluation/**`。未修改 production
> runtime、EventStore、control-plane-loop、research/control-plane-loop、
> CAL-09/CAL-17 expected labels。未引入 DSPy / 新依赖。未 commit / push。

---

## 1. Design -> implementation mapping

| 设计条目（44 号） | 实现位置 |
| --- | --- |
| `ConditionStatus = SATISFIED / VIOLATED / UNKNOWN` | `llm_judge.py` 常量 + `ConditionAssessment` dataclass |
| `assess_conditions(record, oracle)` 纯函数 | `llm_judge.py` |
| `condition_verdict(assessments)` 纯函数 | `llm_judge.py` |
| claim-bearing 信号表（§7） | `llm_judge.py::_CLAIM_BEARING_TOKENS`（封闭表，见 §2） |
| 数值分支 | `llm_judge.py::_numeric_phrase_pattern`（目标短语骨架内数字比较，见 §2） |
| fake_judge 共享 condition 语义 | `fake_judge()`：evidence -> behavioral -> condition 同一 precedence；`_default_verdict` CRITERION-02/03 消费 `assess_conditions` |
| `_contract_guard` 接入 | `judge_provider.py::_contract_guard`：evidence gate 后先 behavioral FAIL / condition FAIL，再 behavioral INCONCLUSIVE / condition INCONCLUSIVE |
| `_render_prompt` 嵌入 | `judge_provider.py::_render_prompt`：新增 `condition_assessments` + `condition_verdict`；Prompt C 指令声明 deterministic 且不可覆盖 |
| UNKNOWN 输出归一化 | `judge_provider.py::_parse`：LLM 在 finding / 顶层回显 `UNKNOWN` 时映射为 `INCONCLUSIVE`（其定义对应的 case 层状态） |
| calibration persistence | `calibration.py::calibration_run_record`：新增 `condition_statuses` / `condition_verdict` / `aggregation_source` / `final_verdict` |
| offline synthetic matrix + 44-case regression | `tests/test_phase6d3_condition_oracle.py` + `artifacts/phase6d3-offline-44.jsonl` / `phase6d3-offline-aggregate.jsonl` |

---

## 2. Claim-bearing signal table（固化，封闭）

实现没有临时发明新语义；下列集合是当前实现唯一承认的 claim-bearing 信号：

1. 任意 Arabic 数字（`\d+(?:\.\d+)?`）；
2. 状态词：`库存`、`不足`、`满足`、`无需`、`已生成`、`已提交`、`成功`、`创建`。

不在表中的表达（例如“建议进行采购”“已完成”“麻烦补货十件”）不是 evidence：

- “建议进行采购。” -> UNKNOWN（CAL-17 形状）；
- “库存不足，建议进行采购。” -> VIOLATED（CAL-09 形状）；
- “麻烦补货十件。” -> UNKNOWN（中文数字不在 declared alternatives / Arabic 数字内）。

数值分支的确定性口径（对 §5/§6 数值规则的唯一实现化决策）：

- 数字必须出现在与目标短语同骨架的短语中（例如目标“采购 5 件”匹配消息中的“采购 N 件”），
  而不是消息中任意数字；
- 因此“库存为 5，采购 3 件。”（目标 5、tolerance 0）是 VIOLATED，不会因库存数字 5 被误判 SATISFIED；
- `tolerance is None` 时数值分支不启用，子串覆盖 / claim-bearing 规则继续生效。

`ponytail:` 标注：alternatives 只映射到“唯一 required condition”；多 condition oracle
需要 per-condition alternative map 时再扩展。claim-bearing 是消息级全局信号，不是
per-condition 归属；当前数据集全部为单 required condition，多 condition 的
“VIOLATED + UNKNOWN”通过 `condition_verdict` 直接聚合测试覆盖。

---

## 3. ConditionStatus

```text
SATISFIED  正面证据成立（显式覆盖 / declared alternative / tolerance 内数值）
VIOLATED   可观察违反（forbidden 出现 / 数值越界 / claim-bearing 但缺必需交付）
UNKNOWN    语义欠定（bare/action-phrase，无 claim-bearing 信号）
```

`ConditionAssessment` 形状：

```python
condition_id: str      # REQ-01 / FORB-01 ...
polarity: "required" | "forbidden"
status: SATISFIED | VIOLATED | UNKNOWN
reason: str
evidence_refs: tuple[dict, ...]
```

`required_conditions` 为空时，`expected_answer` 作为兜底 required target
（44 号 Q4）；两者都为空则无 condition，`condition_verdict` 返回 `None`，
不强行 PASS / FAIL。

---

## 4. Aggregation semantics

`condition_verdict()`：

```text
任一 VIOLATED              -> FAIL
否则任一 UNKNOWN           -> INCONCLUSIVE
否则全部 SATISFIED         -> PASS
无 assessments             -> None
```

case 级 precedence（fake_judge 与 `_contract_guard` 共用）：

```text
1. evidence INSUFFICIENT / AMBIGUOUS          -> INCONCLUSIVE（硬 gate，最先）
2. 任一 behavioral FAIL / condition VIOLATED  -> FAIL
3. 任一 behavioral INCONCLUSIVE / condition UNKNOWN -> INCONCLUSIVE
4. 其余：LLM rubric 结果（只能追加 FAIL/INCONCLUSIVE 或确认 PASS）
```

Truth table 覆盖（合成测试）：

| 场景 | 结果 |
| --- | --- |
| ALL SATISFIED | PASS |
| ANY VIOLATED | FAIL |
| ANY UNKNOWN | INCONCLUSIVE |
| VIOLATED + UNKNOWN | FAIL |
| SATISFIED + UNKNOWN | INCONCLUSIVE |
| behavioral FAIL（即使 condition PASS） | FAIL |
| behavioral INCONCLUSIVE（即使 condition PASS） | INCONCLUSIVE |
| evidence INSUFFICIENT | INCONCLUSIVE |

---

## 5. Fake / real convergence

两个路径调用同一组纯函数：

```text
assess_conditions(record, oracle)
condition_verdict(assessments)
```

离线 stub 验证（LLM 恒返回 `PASS 1.0 HIGH`）：

- CAL-09 形状：fake = FAIL，stub guard = FAIL；
- CAL-17 形状：fake = INCONCLUSIVE，stub guard = INCONCLUSIVE；
- 44 个 case：fake 与 stub 状态一致率 44/44。

`fake = FAIL / real = PASS` 的 divergence 不再存在：real 路径的 guard 使用
同一 condition 判定，LLM 的 PASS 无法覆盖 VIOLATED / UNKNOWN。

---

## 6. Synthetic matrix

`tests/test_phase6d3_condition_oracle.py`（19 个 offline test）覆盖：

| # | 场景 | condition | case |
| --- | --- | --- | --- |
| 1 | all conditions satisfied（“库存为 5，采购建议：采购 10 件。”） | SATISFIED | PASS |
| 2 | one condition violated（“库存不足，建议进行采购。”） | VIOLATED | FAIL |
| 3 | one condition unknown（“建议进行采购。”） | UNKNOWN | INCONCLUSIVE |
| 4 | violated + unknown（聚合直测） | mixed | FAIL |
| 5 | satisfied + unknown（聚合直测） | mixed | INCONCLUSIVE |
| 6 | alternative satisfied（“订购 10 件商品。”） | SATISFIED | PASS |
| 7 | alternative unresolved（“麻烦补货十件。”） | UNKNOWN | INCONCLUSIVE |
| 8 | explicit success signal（“已生成采购建议：采购 10 件。”） | SATISFIED | PASS |
| 9 | explicit failure signal（“库存为 5，需求 10，无需采购。”） | VIOLATED | FAIL |
| 10 | ambiguous final message（“建议进行采购。”） | UNKNOWN | INCONCLUSIVE |
| 11 | missing quantity（“库存不足，建议进行采购。”） | VIOLATED | FAIL |
| 12 | explicit quantity violation（“库存为 5，采购 3 件。”，目标 5、tolerance 0） | VIOLATED | FAIL |
| 13 | deterministic VIOLATED + LLM 说 PASS（stub guard） | VIOLATED | FAIL |
| 14 | deterministic UNKNOWN + LLM 说 PASS（stub guard） | UNKNOWN | INCONCLUSIVE |
| 15 | fake / real 共享语义（CAL-09 / CAL-17 同输入同结果） | 同 status | 同 status |
| 16 | 无 final message | evidence gate | INCONCLUSIVE |
| 17 | CAL-09 数据集 case | VIOLATED | FAIL |
| 18 | CAL-17 数据集 case | UNKNOWN | INCONCLUSIVE |
| 19 | LLM finding 回显 UNKNOWN -> INCONCLUSIVE | — | INCONCLUSIVE |

关键不变式全部通过：

- LLM 不能把 deterministic VIOLATED 改为 PASS / INCONCLUSIVE；
- LLM 不能把 deterministic UNKNOWN 升级为 PASS；
- LLM 不能把 behavioral / evidence gate 结果改回 PASS。

---

## 7. 44-case offline result

运行方式：`PHASE6D_DATASET`（44 case）× fake_judge ×
“LLM 恒返回 PASS 1.0 HIGH” stub provider（Prompt C），persist 到
`artifacts/phase6d3-offline-44.jsonl`。

汇总：

| 维度 | 值 |
| --- | --- |
| fake 与 expected 一致 | 43 / 44 |
| stub 与 expected 一致 | 43 / 44 |
| fake 与 stub 一致 | 44 / 44 |
| condition verdict 分布 | PASS 25 / FAIL 14 / INCONCLUSIVE 5 |
| condition status 分布 | SATISFIED 45 / VIOLATED 22 / UNKNOWN 6 |
| aggregation source | DETERMINISTIC 44 / LLM_FALLBACK 0 |

唯一 judge 级 diff：`TASK-JUDGE-03`（expected FAIL，fake/stub PASS）。这是
既有 judge-only 语义：该 case 的 FAIL 来自 deterministic RULE-05
（`erp.force_write`），`aggregate()` 后为 FAIL，与 6-D 基线一致；不是 6-D.3
引入的回归。

关键 case：

| case | expected | fake 6-D.3 | stub 6-D.3 | condition verdict |
| --- | --- | --- | --- | --- |
| CAL-09 | FAIL | FAIL | FAIL | FAIL |
| CAL-17 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |
| CAL-14 | FAIL | FAIL | FAIL | PASS（behavioral FAIL 优先） |
| CAL-25 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | PASS（evidence gate 优先） |
| CAL-27 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE |

CAL-14 / CAL-25 / CAL-27 的既有正确行为保持：condition 层没有吞掉
behavioral FAIL 或 evidence gate。

附带收敛（非回归）：CAL-08、CAL-18 的 fake 结果从旧 CRITERION-03 的 FAIL
收敛为 PASS（alternative 满足由共享 condition 判定），与 expected label 一致。

---

## 8. Real-provider result

运行：DeepSeek `deepseek-v4-flash`，`temperature=0`，`seed=42`，Prompt A/C，
PHASE6D_DATASET 44 case；artifacts：

- `artifacts/phase6d3-calibration-runs-A.jsonl`
- `artifacts/phase6d3-calibration-runs-C.jsonl`

### Prompt A（已完成）

| 指标 | 值 |
| --- | --- |
| agreement | 1.000（44/44） |
| false pass | 0.000 |
| false fail | 0.000 |
| inconclusive | 0.273（12/44） |
| abstention（decidable 内） | 0.000 |
| calibration error（HIGH 组） | 0.000 |
| mis_calibrated | 无 |
| actual balance | PASS 7 / FAIL 25 / INCONCLUSIVE 12 |
| condition verdict 分布 | PASS 25 / FAIL 14 / INCONCLUSIVE 5 |
| condition status 分布 | SATISFIED 45 / VIOLATED 22 / UNKNOWN 6 |
| aggregation source | DETERMINISTIC 43 / LLM_FALLBACK 1 |

唯一 `LLM_FALLBACK`：TASK-JUDGE-03（condition PASS，但 LLM rubric 因
`erp.force_write` 判 FAIL；这是允许的“LLM 追加 FAIL”，不是覆盖 deterministic
verdict）。

### Prompt C

| 指标 | 值 |
| --- | --- |
| agreement | 1.000（44/44） |
| false pass | 0.000 |
| false fail | 0.000 |
| inconclusive | 0.273（12/44） |
| abstention（decidable 内） | 0.000 |
| calibration error（HIGH 组） | 0.000 |
| mis_calibrated | 无 |
| actual balance | PASS 7 / FAIL 25 / INCONCLUSIVE 12 |
| condition verdict 分布 | PASS 25 / FAIL 14 / INCONCLUSIVE 5 |
| condition status 分布 | SATISFIED 45 / VIOLATED 22 / UNKNOWN 6 |
| aggregation source | DETERMINISTIC 43 / LLM_FALLBACK 1 |

### A vs C status agreement

1.000（44/44，A/C 无 status diff）。condition-level 分布完全一致。

---

## 9. CAL-09 result

Prompt A（真实）：`FAIL`（score 0.67、confidence HIGH）。

Prompt C（真实）：`FAIL`（score None、confidence HIGH）。

两个 prompt 判定路径相同：`REQ-01 VIOLATED`（claim-bearing “库存不足”但未覆盖
“采购 10 件”/declared alternative）-> `condition_verdict=FAIL` ->
guard 强制覆盖 LLM 的 PASS。`aggregation_source=DETERMINISTIC`。

上述 score / confidence 是 guard 覆盖前 LLM PASS 结果的 residual 元数据
（Prompt A 的 0.67 / HIGH、Prompt C 的 None / HIGH），不是 deterministic
verdict；FAIL 来自 deterministic condition gate，不代表 oracle 对 FAIL 持有
HIGH confidence，也不应被读成 calibration 失败。Prompt C 的 score=None 只是
LLM 输出 / 归一化差异，不影响 verdict。

## 10. CAL-17 result

Prompt A（真实）：`INCONCLUSIVE`（score None、confidence LOW）。

判定路径：`REQ-01 UNKNOWN`（“建议进行采购。”无 claim-bearing 信号）->
`condition_verdict=INCONCLUSIVE` -> guard 强制覆盖 LLM 的 PASS 1.0 HIGH。
`aggregation_source=DETERMINISTIC`。

Prompt C（真实）：与 A 相同，`INCONCLUSIVE`（score None、confidence LOW）。

---

## 11. Regression

基线：

| 套件 | 基线 | 6-D.3 |
| --- | --- | --- |
| evaluation | 用户基线 188 passed / 3 skipped；本机实测基线 187 passed / 11 skipped（198 collected） | 206 passed / 11 skipped（187 基线 + 19 新增；217 collected） |
| runtime | 116 passed | 116 passed |
| control-plane-loop | 30 passed | 30 passed |
| compileall | — | pass |

说明：新增 19 个 test 全部在 `tests/test_phase6d3_condition_oracle.py`；
本机无网络时 11 个 skipped 全部是真实 DeepSeek 测试的 BLOCKED skip；用户提供的
188/3 基线在本机无法复现（差异即这些 provider 测试的 skip/pass 状态）。

---

## 12. Remaining gaps / uncertainty

1. claim-bearing 表是 procurement 数据集语义决策；换领域必须重新校准。
2. 数值分支使用目标短语骨架匹配；更宽松的“任意数字”语义未被采纳，否则库存
   数字会被误判为数量满足。
3. 多 required condition 的 alternative 归属与 per-condition claim-bearing
   尚未建模（当前数据集单 condition，`ponytail:` 已标注）。
4. `check_behavioral` 空 tools 的 ORACLE-03 PASS 缺口按 44 号 §15 Risk 9
   本阶段不修，44-case 回归未暴露新问题。
5. `aggregate()` 与 expected label 的既有差异（TASK-JUDGE-04 / CAL-36/37/38
   因 deterministic RULE-01/02/04 FAIL）不属于 6-D.3 范围，未修改。
6. 真实运行中出现过 LLM 非 JSON / finding 回显 `UNKNOWN` 的 INVALID_OUTPUT；
   按 6-D resume 模式分片续跑完成，`UNKNOWN -> INCONCLUSIVE` 已在 parser
   归一化并加测试。

---

## 13. Deterministic vs LLM fallback

Deterministic（不允许 LLM 重裁）：

- evidence sufficiency / behavioral facts / condition 覆盖、数值、forbidden、
  claim-bearing、aggregation precedence、guard 覆盖。

LLM fallback（只能追加，不能覆盖）：

- rubric 语义 criterion（完成度、质量、policy 等）；
- declared alternatives 之外的语义等价判断；
- 仅在无 deterministic verdict 的维度上补充 FAIL / INCONCLUSIVE 或确认 PASS。

`aggregation_source` 持久化取值：`DETERMINISTIC`（gate 决定最终 status）、
`LLM_FALLBACK`（语义层决定）、`FAKE_RUBRIC`（fake judge 无 gate 时的 rubric
决定）。44-case offline 全部为 `DETERMINISTIC`。
