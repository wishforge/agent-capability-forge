# 42 — Phase 6-D.1 Semantic Calibration Analysis（CAL-09 / CAL-17）

> 阶段：Phase 6-D.1（仅考古 / 归因 / 方案设计，不实现）。
> 前置：Phase 6-C（`45143c7`）、Phase 6-D（`bf91ca6`）。
> 范围：`docs/archaeology/deepseek-harness/evaluation/**`、
> `docs/archaeology/unified-runtime/40` / `41` 报告，以及
> `phase6d-calibration-runs-{A,C}.jsonl` artifacts。
> 禁止：修改 production runtime / EventStore / control-plane-loop /
> evaluation implementation / OracleReference / judge_provider /
> calibration.py；不修改 CAL-09 / CAL-17 expected label；不删除失败 case。

---

## 1. Research question

验证 CAL-09（partial success / 缺数量 → PASS）与 CAL-17（ambiguous
final message → PASS）为什么能穿透 Phase 6-D 的 Evidence Gate 与
Behavioral Gate，并区分以下候选归因：

- A. Oracle 不足
- B. Evidence 不足
- C. Deterministic oracle 实现不足
- D. Judge criterion 设计不足
- E. LLM judge semantic interpretation 错误
- F. Calibration dataset 本身设计问题
- G. 多个因素共同造成

本阶段只回答“在哪一层、为什么、最小改哪一层”，不执行实现。

## 2. Current baseline

- Phase 6-C：`45143c7`
- Phase 6-D：`bf91ca6`（已 push，作为稳定 checkpoint）
- Real provider：DeepSeek `deepseek-v4-flash`，`temperature=0, seed=42`
- Artifacts：
  - `evaluation/artifacts/phase6d-calibration-runs-A.jsonl`（44 runs）
  - `evaluation/artifacts/phase6d-calibration-runs-C.jsonl`（44 runs）

| 指标 | 6-C A (N=30) | 6-D A (N=44) | 6-D C (N=44) |
| --- | --- | --- | --- |
| agreement | 0.833 | 0.955 | 0.955 |
| false pass | 0.067 | 0.023 | 0.023 |
| false fail | 0.000 | 0.000 | 0.000 |
| inconclusive | 0.133 | 0.250 | 0.250 |
| calibration error (HIGH) | 0.160 | 0.061 | 0.061 |
| mis_calibrated | CAL-09, CAL-14, CAL-17, CAL-25 | CAL-09, CAL-17 | CAL-09, CAL-17 |

6-D A vs C 的 44-case status agreement = 1.0；6-D 新 cases（CAL-31..44）
14/14 命中 expected status。遗留失败仅为 legacy 30 中的 CAL-09 / CAL-17。

### 调查文件

- `evaluation/models.py`（PASS / FAIL / INCONCLUSIVE 三态）
- `evaluation/evaluator.py`（deterministic 聚合）
- `evaluation/rules.py`（RULE-01..13）
- `evaluation/llm_judge.py`（OracleReference、EvidenceAssessment、
  check_behavioral、_default_verdict、fake_judge、aggregate）
- `evaluation/judge_provider.py`（_render_prompt、_parse、_contract_guard）
- `evaluation/calibration.py`（CalibrationCase、ORACLE_10、CAL-09/17/14/25/27、
  run_calibration、calibration_run_record）
- `evaluation/tests/test_phase6d.py`（6-D offline 断言）
- `unified-runtime/40-calibration-report.md`、`41-phase6d-report.md`

### 关键调用链（代码确认）

```text
CalibrationCase.jinput()                       calibration.py:47/902
  -> LLMJudgeInput(deterministic_evaluation=evaluate(...))  llm_judge.py:167
  -> evaluate(execution_record, task_spec)     evaluator.py:17 / rules.py:508
run_calibration(provider, dataset)             calibration.py:416
  -> DeepSeekJudgeProvider.judge(...)          judge_provider.py:559
       -> _render_prompt(...)                  judge_provider.py:187
            -> assess_evidence(...)            llm_judge.py:344
            -> check_behavioral(...)           llm_judge.py:447
       -> _create(...)                         judge_provider.py:319 (LLM call)
       -> _parse(...)                          judge_provider.py:359
       -> _contract_guard(...)                 judge_provider.py:451
  -> calibration_run_record(...)               calibration.py:358
  -> calibration_metrics(...)                  calibration.py:317
```

重要事实：calibration runner 的最终 status 是
`DeepSeekJudgeProvider.judge()` 返回的 `LLMJudgeResult.status`
（经 `_contract_guard` 覆盖后），**没有调用** `llm_judge.aggregate()`
（`llm_judge.py:956`）。因此 calibration 的 PASS 来自
“LLM judge 结果 + guard”，不是 deterministic evaluator 也不是
UnifiedEvaluationResult 聚合。

## 3. CAL-09 forensic analysis

### 3.1 数据（calibration.py:1032；artifact A/C 第 9/17 行）

```text
task        : 查询 SKU A 库存；若不足则生成数量正确的采购建议
              （目标库存 10，当前库存 5）。
final       : 库存不足，建议进行采购。
tools       : inventory.lookup(sku=A) -> stock:5
              procurement.suggest(sku=A, qty=10) -> suggestion:created
context     : EXACT，missing_semantics=[]
oracle      : oracle:phase6c:procurement:qty10
              expected_answer="采购 10 件"
              expected_business_outcome="生成采购建议，数量 10 件"
              required_conditions=("采购 10 件",)
              acceptable_alternatives=("补货 10 件","下单 10 件","订购 10 件")
              required_order=("inventory.lookup","procurement.suggest")
              tool_call_constraints=(suggest.qty == 10)
              required_evidence=("SYSTEM_PROMPT_SNAPSHOT",)
expected    : FAIL（score 0.4–0.6，MEDIUM；tag C partial success）
observed    : PASS 1.0 HIGH（Prompt A 与 C 一致）
```

### 3.2 十二问

1. **Oracle 的真实要求是什么？** 任务要求“数量正确的采购建议（数量
   10）”。Oracle 用 `expected_answer="采购 10 件"` +
   `required_conditions=("采购 10 件",)` + `tool_call_constraints`
   `suggest.qty==10` 表达。工具参数层已确定性验证通过
   （ORACLE-06 PASS）；final answer 层的要求没有确定性执行。
2. **required condition 是否包含数量要求？** 是：
   `required_conditions=("采购 10 件",)` 本身含数量；且
   `expected_business_outcome="生成采购建议，数量 10 件"`。
3. **quantity 是否是可 deterministic verification 的字段？** 是。
   两个位置可验证：`procurement.suggest.arguments.qty == 10`
   （已实现，ORACLE-06）；final message 文本是否包含 “采购 10 件” /
   “10” 或 acceptable alternative（未实现为真实 provider 的强制 gate；
   只存在于 fake judge 的 `_default_verdict`，`llm_judge.py:746`）。
4. **当前 oracle 是否知道“数量缺失”？** 在数据层知道（条件已声明），
   在执行层不知道：`check_behavioral`（`llm_judge.py:447`）只检查
   tools / order / call counts / arguments / side effects，不检查 final
   message 对 `expected_answer / required_conditions /
   acceptable_alternatives` 的覆盖。`_default_verdict` 会执行该覆盖，
   但它只被 `fake_judge` 使用，真实 provider 路径不调用。
5. **数量未知时是 UNKNOWN 还是隐式 satisfied？** 当前模型没有
   UNKNOWN 条件状态。final message 缺数量既不被标 UNKNOWN，也不被
   确定性判 FAIL；它被交给 LLM，LLM 输出 PASS，等于被隐式当作 satisfied。
6. **EvidenceAssessment 是否把“缺数量”视为 evidence insufficiency？**
   否。`assess_evidence`（`llm_judge.py:344`）只检查记录级存在性：
   final message 存在、context provenance 存在、tools/results 存在、
   required_evidence 不在 `missing_semantics` 中。它不检查 final message
   是否覆盖 oracle 条件，因此 verdict=SUFFICIENT。
7. **为什么最终可以进入 PASS？** deterministic= PASS，
   evidence= SUFFICIENT，behavioral= PASS（ORACLE-03/06），guard 没有
   任何可覆盖的 FAIL/INCONCLUSIVE；LLM 对五个通用 criterion 输出 PASS，
   `_parse` 汇总为 PASS，`_contract_guard` 原样返回。
8. **是 Oracle 没有表达“必须证明 quantity >= N”还是 judge 没执行？**
   两者都有，但主因是实现未执行：Oracle 已表达“采购 10 件”
   （`calibration.py:744`），却没有与 fake judge 等价的确定性覆盖
   gate；真实 judge 只把 oracle 当 JSON 数据阅读，可执行也可忽略。
9. **acceptable_alternatives 是否导致语义放宽？** 没有直接导致。
   final message “库存不足，建议进行采购”不含
   “补货 10 件 / 下单 10 件 / 订购 10 件”任何一项；若 LLM 把它当作
   “采购 10 件”的泛化表达，那是 judge 推断，不是 alternatives 放宽。
   但由于 alternatives 只存在于 prompt 数据、无强制覆盖检查，
   judge 是否真按 alternatives 判定不可从 artifact 验证。
10. **criterion aggregation 是否把 partial success 压成 PASS？**
    是间接结构问题：rubric（`calibration.py:902` 附近）只有五个通用
    criterion，没有“partial success”或“condition coverage”判据；
    `_overall_status`（`llm_judge.py:833`）只有在出现 FAIL/INCONCLUSIVE
    finding 时才降级。LLM 全部给 PASS 时，partial 无位置表达。
11. **confidence 对 verdict 是否有错误影响？** 无。代码中 confidence
    不改变 status；`_contract_guard` 明确在 guard 后覆盖。HIGH 是结果
    症状（模型对错误 PASS 给出 HIGH），不是 PASS 的原因。

### 3.3 五层对照（CAL-09）

| 层 | 内容 | 结论 |
| --- | --- | --- |
| expected semantics | final answer 必须给出数量 10 | FAIL（partial） |
| encoded oracle semantics | required_conditions / expected_answer 含数量；tool qty=10 | 已表达，但 final-answer 层未强制 |
| available evidence | final message 缺数量；tool 参数有 qty=10 | 可确定判“缺数量” |
| judge interpretation | 把“建议进行采购”+ 正确 tool 行为判为 PASS | 语义放宽 / 未执行 oracle |
| final verdict | PASS 1.0 HIGH | LLM 层产生 |

## 4. CAL-17 forensic analysis

### 4.1 数据（calibration.py:1125；artifact A/C 第 17/17 行）

```text
task        : 同上（数量 10）
final       : 建议进行采购。
tools       : 与 CAL-09 完全相同（lookup + suggest qty=10，顺序正确）
context     : EXACT
oracle      : 与 CAL-09 相同（ORACLE_10）
expected    : INCONCLUSIVE（LOW/MEDIUM；tag K ambiguous）
observed    : PASS 1.0 HIGH（Prompt A 与 C 一致）
```

### 4.2 十问

1. **CAL-17 的 ambiguity 到底是什么？** final message 只有一句
   “建议进行采购。”，既不陈述库存结果，也不陈述采购数量，无法从
   final message 判断是否完成了“数量 10 的采购建议”这一交付。
   tool 记录显示系统执行了 `suggest(qty=10)`，但 final answer 是否
   把该结果正确交付给用户不可判定。
2. **为什么系统认为 evidence sufficient？** `assess_evidence` 只看
   record 级存在性：final message 存在、context EXACT、tools/results
   存在、无 LOSSY、无 multi-message 冲突
   （`_conflicting_final_messages` 要求 >=2 条且正反条件同时出现，
   `llm_judge.py:323`）→ SUFFICIENT。
3. **Oracle 是否有明确 success condition？** 有（expected_answer /
   required_conditions / business outcome），但同样只在 fake judge
   的 `_default_verdict` 中执行；真实 provider 路径无强制检查。
4. **final message 为什么具有歧义？** 它没有包含任何可验证的
   oracle 条件；它既不含“采购 10 件”，也不含“库存为 5”，也不含
   “无需采购”。它属于“动作方向提及但交付内容未定”。
5. **是否缺少 state evidence？** 是：缺少 final message 层面的
   quantity claim；tool 层面的 state（suggestion:created）存在，但
   它证明“系统调用了工具”，不证明“用户收到了数量正确的建议”。
6. **是否缺少 explicit completion evidence？** 是。CAL-17 没有
   “建议：采购 10 件”这样的 completion claim；仅有模糊动作短语。
7. **Judge criterion 是否允许推断？** 通用 rubric 的 criterion 描述
   不区分“可验证条件覆盖”与“语义推断”；prompt C 虽然写了
   “never infer missing facts”，但没有对应的确定性 gate。LLM 仍
   输出 PASS，说明 prompt 措辞本身不足以阻止推断。
8. **judge 是否把“没有明确失败”理解为“成功”？** 从结果看是：
   behavioral 全 PASS + 无明确 FAIL 证据 → LLM 输出 PASS。当前
   “pass 所需证据 = record 完整 + 无 FAIL 行为”的默认，确实把
   “No evidence of failure”和“Evidence of success”混为一谈。
9. **为什么没有产生 INCONCLUSIVE？** abstention policy
   （`41-phase6d-report.md` §6）覆盖：truncated、MISSING context、
   LOSSY、required evidence 缺失、final messages 冲突、无 final
   message。这些都不命中 CAL-17；单条模糊 final message 不在覆盖集内。
10. **当前 abstention policy 是否覆盖这种 ambiguity？** 否。覆盖的是
    “证据记录缺失/冲突”类 ambiguity，不是“语义欠定”类 ambiguity。

### 4.3 关键语义区分

当前实现把“没有 FAIL evidence”当作可 PASS：

```text
record 完整 + behavioral 全 PASS + LLM 无 FAIL finding
    -> PASS
```

缺少的语义是：

```text
required condition SATISFIED（evidence of success）
required condition UNKNOWN（语义欠定 -> INCONCLUSIVE）
required condition VIOLATED（evidence of failure -> FAIL）
```

CAL-17 需要的是中间态 UNKNOWN，而当前三态 PASS/FAIL/INCONCLUSIVE
的 INCONCLUSIVE 只在“记录 / 行为层”出现：evidence INSUFFICIENT
（记录缺失 / required evidence 缺失）、evidence AMBIGUOUS（LOSSY
backend evidence、final messages 冲突）、behavioral INCONCLUSIVE
（行为不可验证）。这些都不是“条件语义欠定”，因此 CAL-17 的模糊
final message 走不到 INCONCLUSIVE。

## 5. CAL-14 / CAL-25 comparison

### 5.1 为什么 6-D 修复了 CAL-14 / CAL-25

- CAL-14：`ORACLE_10` 在 6-D 新增 `required_order`
  （`calibration.py:744`），`check_behavioral` 产出 ORACLE-03 FAIL，
  `_contract_guard`（`judge_provider.py:451`）强制覆盖 LLM 的 PASS。
- CAL-25：`ORACLE_10` 新增 `required_evidence=("SYSTEM_PROMPT_SNAPSHOT",)`，
  record 的 PARTIAL context 在 `missing_semantics` 中列出该 token，
  `assess_evidence` 返回 INSUFFICIENT，guard 强制 INCONCLUSIVE/LOW。

两者的共同模式：**新增的 oracle 字段被一个确定性函数消费，且该函数
的结果被 guard 强制执行。**

### 5.2 为什么 CAL-09 / CAL-17 仍然穿透

| 维度 | CAL-14（已修） | CAL-25（已修） | CAL-09 / CAL-17（未修） |
| --- | --- | --- | --- |
| oracle 字段 | required_order | required_evidence | expected_answer / required_conditions / acceptable_alternatives（6-C 已有） |
| 确定性消费 | check_behavioral ORACLE-03 | assess_evidence | 仅 fake judge `_default_verdict`；真实 provider 不消费 |
| guard 覆盖 | 有（FAIL） | 有（INCONCLUSIVE） | 无 |
| 失败类型 | tool-order misuse | PARTIAL + missing required evidence | final-answer condition coverage / 语义欠定 |

结构差异：6-D 把“可验证的行为事实”和“证据种类”接到
deterministic gate；而 final-answer 的语义条件
（`expected_answer / required_conditions / acceptable_alternatives`）
在 6-C 就已存在于 OracleReference，却始终没有对应的确定性执行路径，
只作为 LLM prompt 数据存在。

### 5.3 fake vs real 的 divergence（代码确认）

离线执行同一 CAL-09 / CAL-17：

```text
fake_judge -> FAIL（_default_verdict：required condition 不在 final text）
real judge -> PASS（LLM 输出；guard 不覆盖）
```

这直接证明：问题不是“oracle 没表达”，而是“表达没有被真实路径执行”。

## 6. Failure Attribution Matrix

| Case | Expected | Observed (6-D A/C) | Evidence | Oracle | Deterministic Gate | Judge | Confidence | Root Cause | Fix Type |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAL-09 | FAIL | PASS 1.0 HIGH | final 缺数量；tool qty=10；EXACT | required_conditions 含数量，但仅 advisory | PASS（RULE + ORACLE-03/06 全 PASS） | PASS | HIGH | final-answer condition coverage 未确定性执行；LLM 把缺数量推断为满足 | Oracle 实现 + guard（deterministic） |
| CAL-17 | INCONCLUSIVE | PASS 1.0 HIGH | 单条模糊 final；tool 行为正确；EXACT | 同上 + 无 ambiguity 表达 | PASS | PASS | HIGH | 单条语义欠定无 UNKNOWN 模型；abstention policy 不覆盖；LLM 把无失败当成功 | Condition status（UNKNOWN）+ abstention 规则 |
| CAL-14 | FAIL | FAIL（6-C 为 PASS） | tools 逆序；final 正确 | required_order 已声明 | ORACLE-03 FAIL（guard 强制） | PASS（被覆盖） | HIGH | 6-C：oracle 无 tool order 表达 | 6-D 已修（behavioral gate） |
| CAL-25 | INCONCLUSIVE | INCONCLUSIVE LOW（6-C 为 PASS） | PARTIAL + missing SYSTEM_PROMPT_SNAPSHOT | required_evidence 已声明 | assess_evidence INSUFFICIENT（guard 强制） | PASS（被覆盖） | LOW | 6-C：evidence sufficiency 无声明 | 6-D 已修（evidence gate） |
| CAL-27 | INCONCLUSIVE | INCONCLUSIVE LOW（6-C 为 FAIL） | PARTIAL + 模糊 final | 同 CAL-25 | 同 CAL-25 | FAIL（被覆盖） | LOW | 6-C：同 CAL-25 | 6-D 已修（evidence gate） |

## 7. Oracle vs Evidence vs Judge vs Prompt taxonomy

### 7.1 Oracle problem

- OracleReference 有 final-answer 语义字段，但没有“final-answer 条件
  覆盖”的确定性检查（`llm_judge.py:447` 只查行为事实）。
- 没有 SATISFIED / VIOLATED / UNKNOWN 条件状态。
- 没有“final answer 必须包含数量”这类可验证交付条件的声明字段。

### 7.2 Evidence problem

- `required_evidence=("SYSTEM_PROMPT_SNAPSHOT",)` 在 EXACT context
  下被视为满足，即使 record 实际上不包含 snapshot 字段；检查逻辑是
  “不在 missing_semantics 中”而不是“字段真实存在”
  （`llm_judge.py:344` 的 `elif kind in _missing_semantics(record)`）。
- evidence sufficiency 只覆盖记录完整性，不覆盖 final-answer 语义覆盖。

### 7.3 Judge problem（criterion + semantic interpretation）

- Rubric 是五个通用 criterion，无 condition coverage / partial-success
  判据。
- LLM 在 oracle 明确声明 required_conditions 的情况下仍输出 PASS
  （A、C 一致），是真实的 judge semantic interpretation 错误；
  但它被结构允许，因为没有任何 gate 会拒绝该结果。

### 7.4 Prompt problem

- Prompt A/C 措辞不同但 status 完全一致（44/44），说明 prompt 措辞
  不是主导因素。Prompt C 已要求 “never infer missing facts”，仍被
  穿透，进一步说明单靠 prompt 无法解决。

### 7.5 归因结论（对 A–G 选项）

```text
A. Oracle 不足        : 部分（final-answer 条件无执行；无 UNKNOWN）
B. Evidence 不足      : 部分（sufficiency 不覆盖语义覆盖）
C. Deterministic 实现不足 : 主因（fake 有、real 无；guard 无对应 gate）
D. Judge criterion 不足 : 次要（无 condition coverage criterion）
E. LLM semantic 错误   : 真实存在，但它是被 C 允许的结果
F. Dataset 设计问题    : 部分（CAL-09/17 标签语义未被模型表达，
                          且二者证据差异仅一句话）
G. 多因素             : 是（C 为主，A/B/D/E/F 共谋）
```

## 8. PASS / FAIL / INCONCLUSIVE semantics analysis

### 8.1 当前判定链

```text
deterministic rules（evaluator.py）:
  any FAIL -> FAIL；any INCONCLUSIVE -> INCONCLUSIVE；否则 PASS

LLM rubric（_overall_status, llm_judge.py:833）:
  同上，基于 criterion findings

guard（judge_provider.py:451）:
  evidence != SUFFICIENT -> INCONCLUSIVE
  behavioral FAIL -> FAIL；behavioral INCONCLUSIVE -> INCONCLUSIVE
```

### 8.2 “No evidence of failure” vs “Evidence of success”

当前实现中，PASS 的真实含义是：

```text
record 完整 + 无确定性 FAIL/INCONCLUSIVE + LLM 没有 FAIL finding
```

这不是“所有 oracle 条件都被验证为 SATISFIED”。CAL-09 / CAL-17 的
final message 都没有满足 required_conditions，但也没有任何机制要求
“未覆盖 = 不 PASS”。因此：

- “No evidence of failure”被当作“Evidence of success”使用；
- INCONCLUSIVE 只在记录缺失 / 冲突 / 行为不可验证时出现，
  不在“条件语义欠定”时出现。

## 9. UNKNOWN semantics analysis

### 9.1 当前数据模型

`models.py` 只有 PASS / FAIL / INCONCLUSIVE。OracleReference 的条件是
字符串 tuple，没有条件状态。`EvidenceAssessment` 有
SUFFICIENT / INSUFFICIENT / AMBIGUOUS，但那是“证据记录”状态，不是
“oracle 条件”状态。

### 9.2 是否应该改为分层模型

研究问题：“Evidence → Condition Status（SATISFIED / VIOLATED /
UNKNOWN）→ Aggregation → PASS / FAIL / INCONCLUSIVE” 是否比
“Evidence → Judge → PASS / FAIL / INCONCLUSIVE” 更正确？

答案是：**是，尤其对 CAL-17**。原因：

- CAL-09 的缺数量 = 条件 VIOLATED（或至少是确定的部分失败）；
- CAL-17 的模糊 message = 条件 UNKNOWN（无法判定交付）；
- 当前并非缺少 case-level INCONCLUSIVE（evidence INSUFFICIENT /
  AMBIGUOUS、behavioral INCONCLUSIVE 都会产出它）；真正的缺口是
  condition-level 语义欠定没有 UNKNOWN -> INCONCLUSIVE 路径，
  CAL-17 因此被默认判为 PASS 而静默穿透；
- 分层后，aggregation 规则可以显式区分：

```text
any VIOLATED                    -> FAIL
required condition UNKNOWN      -> INCONCLUSIVE
all conditions SATISFIED        -> PASS
```

注意：不要用 UNKNOWN 当万能出口。CAL-09 需要 VIOLATED（partial
failure），CAL-17 才需要 UNKNOWN；分层模型的意义是让二者各有位置，
而不是把所有语义失败都变 INCONCLUSIVE。

## 10. Deterministic verification opportunities

| 属性 | 数据源 | 当前处理 | 缺口 |
| --- | --- | --- | --- |
| quantity：actual >= required | `procurement.suggest.arguments.qty` | ORACLE-06 已确定性验证 | 无（工具参数层已覆盖） |
| quantity：final message 包含数量 | `steps[].assistant_messages` | 仅 fake judge `_default_verdict` 子串检查 | 真实 provider 无 gate |
| required condition 覆盖 | final messages + oracle.required_conditions / acceptable_alternatives | 仅 fake judge | 真实 provider 无 gate |
| 单条 message 语义欠定 | final messages 是否含任何可验证条件 claim | 无 | 无 UNKNOWN / ambiguity 规则 |
| tool order | tools 序列 | ORACLE-03/04 已覆盖 | 无（6-D 已修） |
| completion / state | final message 存在性 | assess_evidence 已覆盖 | 覆盖存在性，不覆盖内容 |

CAL-09 / CAL-17 都属于“可以从 trajectory / structured tool result /
final message 直接计算”的属性：

- CAL-09：`final_message 不含 required_conditions/alternatives` 是
  确定性可判的；
- CAL-17：`final_message 不含任何可验证条件 claim` 需要一条显式
  ambiguity 规则（见 §12），规则本身可以 deterministic；
- 不需要新增 runtime 证据字段：现有 `steps` / `tools` / `tool_results`
  足够。

## 11. Minimal discriminating experiments（只设计，不执行）

### Experiment A — 强化 oracle wording，不改变 evidence

改 oracle 文案（例如 `expected_answer="采购建议：采购 10 件"`、
`required_conditions=("数量 10",)`），保持 record 不变，跑 real judge。

- 若 CAL-09/17 变 FAIL/INCONCLUSIVE → oracle 表达/prompt 读取问题；
- 若仍 PASS → 与当前 A/C 一致，说明不是 wording。

### Experiment B — 缺失 quantity 显式建模为 UNKNOWN

给 oracle 增加“final-answer 必须覆盖 condition”声明；缺失时
`assess_evidence` 返回 INSUFFICIENT 或新增 UNKNOWN 状态，guard 强制
INCONCLUSIVE。

- 预期：CAL-09 可能变 INCONCLUSIVE（不匹配 expected FAIL）→ 暴露
  “UNKNOWN 不能替代 VIOLATED”。

### Experiment C — ambiguous final message 显式建模为 UNKNOWN

增加“单条 final message 不含任何可验证条件 claim → UNKNOWN”的规则，
guard 强制 INCONCLUSIVE。

- 预期：CAL-17 INCONCLUSIVE；CAL-09 不受影响（含“库存不足”claim）。

### Experiment D — 去掉 confidence 对 verdict 的任何影响

confidence 目前本就不改 status；用 stub provider 对同一 evidence 输出
HIGH/MEDIUM/LOW，断言 status 不变。

- 预期：验证 confidence 不是根因。

### Experiment E — CAL-09 / CAL-17 转为 deterministic oracle candidate

把 `_default_verdict` 的 final-answer condition coverage 提为
deterministic oracle 检查（fake judge 与 real guard 共用）。

- 预期：CAL-09 FAIL（命中 expected）；
- 预期：CAL-17 也 FAIL，除非同时加 ambiguity 规则（命中 expected 需要
  Experiment C 的规则）。

### Experiment F — 相同 evidence，不同 oracle

对同一 record 用 weak oracle（只有 `expected_answer="采购建议"`）与
strong oracle（含数量条件）对比。

- 若 strong oracle 修好 → oracle 表达是关键；
- 若两者都 PASS → judge 语义是关键。

### Experiment G — 相同 oracle，不同 prompt

在 A/C 之外增加显式指令：“final answer 必须逐条覆盖
required_conditions / acceptable_alternatives，否则 FAIL；无法判定则
INCONCLUSIVE”，不改代码。

- 若修好 → prompt 层问题；
- 若修不好 → 必须上确定性 gate。

### 区分矩阵

| 结果模式 | 归因 |
| --- | --- |
| A/G 修好 | Oracle/prompt 表达 |
| B 修好但 CAL-09 变 INCONCLUSIVE | 需要 VIOLATED，不能只加 UNKNOWN |
| C 修好 CAL-17 | ambiguity 规则可行 |
| E 完全命中（CAL-09 FAIL + CAL-17 INCONCLUSIVE） | 确定性实现 + 明确规则 |
| 全部修不好 | judge semantic / dataset semantics |

## 12. Proposed 6-D.1 design（最小方案，不实现）

原则：在现有 `OracleReference` / `EvidenceAssessment` / guard 形状内
扩展，不引入新框架（无 DSPy、无 runtime 改动、无 EventStore 改动）。

1. **Condition status 层（最小）**
   - 新增轻量状态：`SATISFIED / VIOLATED / UNKNOWN`（evaluation 内部，
     不是 runtime 概念）。
   - OracleReference 新增可选声明，例如
     `final_answer_conditions`（或复用 `required_conditions` +
     `acceptable_alternatives`），语义为“final message 必须显式覆盖
     其中之一”。
2. **Deterministic final-answer coverage check**
   - 在 `check_behavioral`（或一个平行的 `check_final_answer`）中实现
     `_default_verdict` 已有的子串/数值覆盖逻辑。
   - 结果进入 guard：VIOLATED → FAIL；UNKNOWN → INCONCLUSIVE/LOW。
3. **Ambiguity 规则（CAL-17 专用，必须显式）**
   - 单条 final message 不覆盖任何 required condition / alternative，
     且不包含任何可对照 evidence 验证的 claim（如“库存不足”）
     → UNKNOWN → INCONCLUSIVE。
   - 包含部分可验证 claim 但缺数量（CAL-09 形状）→ VIOLATED → FAIL。
   - 该规则是 dataset 语义决策，不是 label 修改；实现前先确认
     CAL-09/17 的区分是否就是“是否有可验证的部分 claim”。
4. **Guard 接线**
   - `DeepSeekJudgeProvider._contract_guard` 增加对 final-answer
     coverage 的强制覆盖（与 ORACLE-03/06 同级）。
   - `fake_judge` 保持同一逻辑（它已经接近，需补 UNKNOWN）。
5. **保持 LLM 只做真正语义的事**
   - 数字/字符串/存在性 → deterministic；
   - 模糊意图、同义表达（如“补货 10 件”之外的 paraphrase）→ LLM；
   - 不允许 LLM 把“没有明确失败”输出为 PASS，除非 coverage 已
     SATISFIED。

### 预期效果

```text
CAL-09 -> FAIL（coverage VIOLATED）
CAL-17 -> INCONCLUSIVE（coverage UNKNOWN / ambiguity 规则）
CAL-08 / CAL-18 / CAL-41 -> PASS（coverage SATISFIED，regression 保护）
CAL-10 / CAL-20 / CAL-29 -> FAIL（禁止条件 / 数量不符，仍 FAIL）
CAL-32 -> INCONCLUSIVE（multi-message 冲突，仍 AMBIGUOUS）
```

## 13. Risks

1. **过度 abstention**：若 UNKNOWN 规则过宽，会把所有缺条件 final
   answer 都变 INCONCLUSIVE，CAL-09 的 FAIL 语义会丢。必须保留
   VIOLATED（partial/contradictory claim）路径。
2. **CAL-17 标签语义未固化**：CAL-09 与 CAL-17 的证据差异只有
   “库存不足”一句，当前没有任何文档化规则解释为什么一个是 FAIL、
   一个是 INCONCLUSIVE。实现前必须先固化为显式规则，否则任何确定性
   gate 都是猜。
3. **fake/real divergence 再次出现**：新增确定性逻辑必须同时接入
   fake judge 与 real guard，否则又会出现离线绿、在线红的假象。
4. **required_evidence 语义弱**：当前 `SYSTEM_PROMPT_SNAPSHOT` 在
   EXACT 下“默认存在”，实际 record 无该字段。若下一步要严格化，
   会影响全部 EXACT case，需单独评估，不能与 CAL-09/17 混修。
5. **回归面**：CAL-08/18/41 等 PASS case、CAL-10/20 等 FAIL case、
   CAL-32 冲突 case 都可能受 coverage gate 影响；需要 full offline
   dataset 回归。
6. **Artifact 证据缺口**：当前 artifact 不持久化
   `reasoning_summary / findings`（`calibration.py:358` 的 record 无
   这两项），无法复核 LLM 当时的判据。若后续要区分 judge semantic
   错误与 prompt 错误，建议在 6-D.1 实验阶段把 findings/reasoning
   持久化（评估侧，不改 runtime）。

## 14. What must NOT change

- production runtime / EventStore / control-plane-loop
- `OracleReference` 已有字段的语义（只允许新增 optional 字段）
- `judge_provider` 的 provider 适配边界（可加 guard，不改 provider 抽象）
- CAL-09 / CAL-17 / CAL-25 / CAL-27 的 expected label
- 删除失败 case / 隐藏 negative evidence
- 不得为“让分数变好”修改 dataset
- 不得引入 DSPy 或新依赖

## 15. Recommended implementation order

1. 固化 CAL-09 / CAL-17 区分规则（先写进 43 号设计文档，再动代码）。
2. 实现 condition status（SATISFIED / VIOLATED / UNKNOWN）与
   final-answer coverage check（fake judge 与 guard 共用）。
3. 跑 full offline dataset：验证 CAL-09=FAIL、CAL-17=INCONCLUSIVE、
   其余 42 case 无回归。
4. 用 stub provider 验证 guard 强制覆盖（HIGH PASS 被覆盖）。
5. 真实 DeepSeek 子集复跑 CAL-09/17/08/18/41/10/20/32
   （A 与 C 各一次），并持久化 reasoning_summary/findings。
6. 根据真实结果写 43 号报告，再决定是否进入 6-E。

---

## Final conclusion

```text
Root cause:
  CAL-09 / CAL-17 的 required_conditions / expected_answer 只作为
  prompt 数据传给 LLM；真实 provider 路径缺少与 fake judge
  (_default_verdict) 等价的 final-answer condition coverage gate。
  同时，数据模型没有 condition-level UNKNOWN，单条语义欠定的
  final message 无法进入 INCONCLUSIVE；LLM 把“无 FAIL 证据”当成功。

Primary layer:
  Deterministic oracle implementation（C）：
  final-answer 语义条件已编码但未被强制执行；fake/real divergence
  是直接证据。

Secondary layer:
  A（oracle 无 UNKNOWN/ambiguity 表达）、D（rubric 无 condition
  coverage criterion）、E（LLM 语义放宽，但被 C 允许）、
  F（CAL-09/17 标签语义未文档化）。

Evidence:
  calibration.py:744（ORACLE_10 已声明数量条件）
  llm_judge.py:344（assess_evidence 只查记录完整性）
  llm_judge.py:447（check_behavioral 不查 final-answer 覆盖）
  llm_judge.py:746（_default_verdict 有覆盖逻辑，仅 fake 使用）
  judge_provider.py:187/359/451（prompt 含 oracle，但 guard 不执行
  condition coverage）
  artifacts/phase6d-*.jsonl（CAL-09/17：deterministic=PASS、
  evidence=SUFFICIENT、oracle_status=PASS、result=PASS 1.0 HIGH）
  离线复现：fake_judge(CAL-09/17)=FAIL，real=PASS

Confidence:
  HIGH —— CAL-09（代码路径 + fake/real divergence 直接证明）；
  MEDIUM —— CAL-17 的“expected INCONCLUSIVE”需要一条当前代码中不
  存在的 ambiguity 规则，该规则的正确阈值是 dataset 语义决策，
  现有 artifact 未持久化 reasoning_summary，无法进一步复核。

Recommended next change:
  在 evaluation 内新增 condition status（SATISFIED/VIOLATED/UNKNOWN）
  与 final-answer coverage check，并接入 real guard；不碰 runtime。
  CAL-09 -> FAIL（coverage VIOLATED）；
  CAL-17 -> INCONCLUSIVE（coverage UNKNOWN，需显式 ambiguity 规则）。

Recommended experiment:
  Experiment E（deterministic coverage gate，offline full dataset）
  先行，再跑 Experiment C（ambiguity -> UNKNOWN）；
  若二者命中 expected，则无需依赖 prompt/LLM 修复；
  若 CAL-17 仍不命中，补跑 Experiment G（显式 prompt）以隔离
  judge semantic 与规则设计问题。

Implementation:
  NOT YET

Verdict:
  READY FOR IMPLEMENTATION
  —— 前提：先以文档固化 CAL-09/17 的区分规则；核心确定性 gate 的
  结构已由现有代码（fake judge 的覆盖逻辑 + guard 机制）证实可行。
```
