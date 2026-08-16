# 44 — Phase 6-D.3 Condition-Level Oracle Semantics（设计）

> 阶段：Phase 6-D.3（实现前设计；不实现、不 commit、不 push）。
> 前置：Phase 6-C `45143c7`、Phase 6-D `bf91ca6`、Phase 6-D.1 `bdba660`、
> Phase 6-D.2 `beaa3f5`。
> 范围：`docs/archaeology/deepseek-harness/evaluation/**` 的只读考古 +
> 语义设计；不修改 evaluation implementation、production runtime、
> EventStore、control-plane-loop、calibration labels、CAL-09/CAL-17
> expected status；不引入 DSPy；不修改 Prompt 以追求分数。

---

## 1. Problem statement

两个已确认 calibration failures 仍未修复：

| case | expected | real 6-D A/C | fake judge（离线） |
| --- | --- | --- | --- |
| CAL-09（partial success / 缺数量） | FAIL | PASS 1.0 HIGH | FAIL |
| CAL-17（ambiguous final message） | INCONCLUSIVE | PASS 1.0 HIGH | FAIL |

两者共用同一 oracle（ORACLE_10）与几乎相同的 execution record，差异只有
final message 一句话：

- CAL-09：`库存不足，建议进行采购。`
- CAL-17：`建议进行采购。`

当前 evaluator 只有 case-level 三态 PASS / FAIL / INCONCLUSIVE，缺少
condition-level 语义状态 SATISFIED / VIOLATED / UNKNOWN。因此：

- “没有 FAIL 证据”被默认当作“成功”（CAL-09 / CAL-17 双双 PASS）；
- partial success（有可验证的部分 claim、但缺必需交付）与语义欠定
  （无任何可验证 claim）在同一个 bool 出口里被压扁；
- fake judge 与 real provider 走不同的 condition 逻辑，产生
  fake=FAIL、real=PASS 的 divergence。

本阶段目标：把

```text
Condition -> SATISFIED / VIOLATED / UNKNOWN -> aggregation
          -> PASS / FAIL / INCONCLUSIVE
```

设计为最小、可审计、fake/real 共享的 evaluation 语义层，并给出实验矩阵，
供后续实现阶段（Phase 6-E 之前）验证。

---

## 2. Current architecture

### 2.1 真实调用链（代码确认）

```text
CalibrationCase.jinput()                        calibration.py:47/82
  -> LLMJudgeInput(deterministic_evaluation=evaluate(...))
                                                  llm_judge.py:167
  -> evaluate(record, task)                      evaluator.py:17 / rules.py

run_calibration(provider, dataset)               calibration.py:416
  -> provider.judge(jinput, prompt_key=...)      judge_provider.py:559
       -> _render_prompt(...)                    judge_provider.py:187
            -> assess_evidence(...)              llm_judge.py:344
            -> check_behavioral(...)             llm_judge.py:447
       -> _create(...)                           judge_provider.py:319 (LLM call)
       -> _parse(...)                            judge_provider.py:359
       -> _contract_guard(...)                   judge_provider.py:451
  -> calibration_run_record(...)                 calibration.py:358
```

关键事实：calibration 的最终 status 是
`DeepSeekJudgeProvider.judge()` 返回的 `LLMJudgeResult.status`
（经 `_contract_guard` 覆盖后），**没有调用** `llm_judge.aggregate()`
（`llm_judge.py:956`）。`deterministic_status`（RULE-01..13）只进入
prompt 数据，guard 不消费它。

### 2.2 九个考古问题的答案

**Q1. Condition 当前在哪里表达？**

`OracleReference`（`llm_judge.py:72-99`）：

- `required_conditions` / `forbidden_conditions` / `acceptable_alternatives`
  （`llm_judge.py:80-84`）；
- `expected_answer` / `expected_business_outcome` / `tolerance`；
- 6-D 新增的行为事实字段（`required_tools`、`required_order`、
  `tool_call_constraints`、`required_evidence` 等，`llm_judge.py:86-97`）。

真实数据示例：`ORACLE_10`（`calibration.py:744`）声明
`required_conditions=("采购 10 件",)`、
`acceptable_alternatives=("补货 10 件","下单 10 件","订购 10 件")`、
`forbidden_conditions=("强制写入 ERP",)`、`tolerance=None`。

**Q2. condition 当前是否只有 bool-like semantics？**

是。fake judge 的 `_default_verdict`（`llm_judge.py:746`）对
CRITERION-02/03 只做 `condition in text` 子串匹配：

- `required and not all(condition in text)` → FAIL；
- `expected in text` / `alternative in text` → PASS；
- 无 final message → INCONCLUSIVE；
- **没有** UNKNOWN 状态：模糊 message 一律落到 FAIL（CAL-17 因此
  fake=FAIL，而不是 INCONCLUSIVE）。

real provider 路径完全不执行该逻辑：`required_conditions` 只是被
`_render_prompt` 序列化进 JSON 的提示数据。

**Q3. required_conditions 能否区分 satisfied / violated / unknown？**

不能：

- fake judge 只有“覆盖=过”与“未覆盖=FAIL”的二元出口（外加“无 message”
  的 INCONCLUSIVE）；
- real judge 没有任何 condition 判定，输出完全交给 LLM；
- `assess_evidence`（`llm_judge.py:344`）的
  SUFFICIENT / INSUFFICIENT / AMBIGUOUS 是**记录级**证据状态，不是
  condition 状态。

**Q4. expected_answer 是 condition、target、还是 free-form prompt data？**

它是 free-form reference answer 字符串，同时被当作：

- fake judge 的子串/数字匹配 target（`llm_judge.py:764-796`）；
- real provider 的 prompt 数据（`_render_prompt` 序列化）；
- 冲突检测的输入（`_conflicting_final_messages`，`llm_judge.py:323`）。

它不是结构化 condition：真正的 condition 语义由
`required_conditions` / `forbidden_conditions` / `acceptable_alternatives`
承载；`expected_answer` 在 `required_conditions` 为空时承担兜底 target。

**Q5. 当前 PASS 的 default path 是什么？**

```text
evaluate(): 无 RULE FAIL/INCONCLUSIVE -> PASS       evaluator.py:28-36
assess_evidence(): SUFFICIENT                       llm_judge.py:344
check_behavioral(): 无 ORACLE FAIL/INCONCLUSIVE     llm_judge.py:447
LLM findings: _overall_status 无 FAIL/INCONCLUSIVE  llm_judge.py:833
guard: 无覆盖原因 -> 原样返回 result               judge_provider.py:451
```

等价于：“record 完整 + 无确定性失败 + LLM 没有 FAIL finding → PASS”。
这正是不需要的语义：**absence of failure ≠ evidence of success**。

**Q6. 当前 FAIL 的 deterministic path 是什么？**

三个来源：

1. `evaluate()`：任一 RULE-* FAIL → `EvaluationResult.status=FAIL`
   （`evaluator.py:28`；只影响 `deterministic_status`，calibration 不消费）；
2. `check_behavioral()`：任一 ORACLE-* FAIL（tool/order/args/side effect）
   → fake judge 强制 FAIL（`llm_judge.py:871-881`）、real guard 强制 FAIL
   （`judge_provider.py:494-514`）；
3. fake judge `_default_verdict`：CRITERION-02/03 的 condition 子串 FAIL
   （`llm_judge.py:764-831`；**仅 fake 使用**）。

**Q7. 当前 INCONCLUSIVE 在哪一层产生？**

| 层 | 来源 | 位置 |
| --- | --- | --- |
| deterministic rules | RULE-* INCONCLUSIVE（如 tools 缺失、turn outcome 缺失） | rules.py / evaluator.py |
| evidence | INSUFFICIENT / AMBIGUOUS（MISSING/PARTIAL/LOSSY/conflict/truncated） | llm_judge.py:344 |
| behavioral | ORACLE-* INCONCLUSIVE（如 side_effects 缺失、tools 缺失） | llm_judge.py:447 |
| LLM | 模型输出 INCONCLUSIVE，或 required criterion 无 evidence | judge_provider.py:359 |
| guard | evidence/behavioral 强制覆盖 | judge_provider.py:451 |
| aggregation | 多 judge 冲突 / deterministic INCONCLUSIVE | llm_judge.py:956 |

没有任何一层处理“单条模糊 final message 的语义欠定”，所以 CAL-17 穿透。

**Q8. 当前 aggregation 到底发生在哪里？**

- `evaluate()`：RULE findings → deterministic status（`evaluator.py:28-36`）；
- `_overall_status()`：judge findings → judge status，FAIL > INCONCLUSIVE
  > PASS（`llm_judge.py:833-839`）；
- `aggregate()`：deterministic + judge results → `UnifiedEvaluationResult`
  （`llm_judge.py:956`；主评估路径使用，calibration 不使用）；
- `_contract_guard`：evidence → behavioral 的强制覆盖
  （`judge_provider.py:451-557`）。

不存在 condition-level aggregation：`required_conditions` 从不单独
聚合成 status。

**Q9. fake judge 与 real provider 是否仍然存在 semantic divergence？**

是。只读离线探针（现有代码，非新实验）确认：

```text
offline: fake_judge(CAL-09) = FAIL  (CRITERION-02/03: required condition 未覆盖)
         fake_judge(CAL-17) = FAIL  (同一路径；fake 无 UNKNOWN)
real:    CAL-09 / CAL-17 均为 PASS 1.0 HIGH（artifact A/C 第 9/17 行）
```

原因：`_default_verdict` 只在 fake_judge 内被调用；real provider 的
`_render_prompt` 只把 oracle 序列化给 LLM，`_contract_guard` 不执行
condition coverage。

---

## 3. Current semantic gap

```text
record 完整 + 行为正确 + LLM 无 FAIL finding
    -> PASS
```

缺少：

```text
required condition SATISFIED（positive evidence of success）
required condition VIOLATED（observable violation / 明确违反）
required condition UNKNOWN（语义欠定，不能 PASS 也不能 FAIL）
```

三个已存在的三态（deterministic status、evidence verdict、behavioral
finding）都不是 condition 语义状态：

- deterministic status：RULE 聚合，与 oracle condition 无关；
- evidence verdict：记录是否存在/可信（SUFFICIENT/INSUFFICIENT/AMBIGUOUS）；
- behavioral finding：可观察行为事实（PASS/FAIL/INCONCLUSIVE）。

CAL-09 需要 condition VIOLATED；CAL-17 需要 condition UNKNOWN。二者在
现有模型中都没有表达位置。

---

## 4. ConditionStatus proposal

### 4.1 最小模型

```text
ConditionStatus = SATISFIED | VIOLATED | UNKNOWN
```

仅三个状态，不新增：

- `NOT_APPLICABLE`：不需要。当前 oracle 声明的 condition 对该 case 全部
  适用；条件分支（“若库存不足则采购，否则无需采购”）通过数据集显式选择
  对应 oracle 表达，不需要 condition 自报 N/A。
- `CONFLICTING`：不需要。多 message 正反冲突已经由
  `_conflicting_final_messages`（`llm_judge.py:323`）在 evidence 层判定
  AMBIGUOUS → INCONCLUSIVE；单 message 内部矛盾（claim 与 evidence 矛盾）
  是 deterministic VIOLATED，不需要第四态。
- `UNOBSERVABLE`：不需要。行为/证据缺失由 evidence gate
  （INSUFFICIENT/AMBIGUOUS）与 behavioral INCONCLUSIVE 表达；condition
  层对应地标 UNKNOWN 即可。增加状态只会让聚合更复杂。

### 4.2 数据形状（实现阶段的最小新增）

```text
ConditionAssessment:
  condition_id: str          # 如 "REQ-01" / "FORB-01"
  polarity: "required" | "forbidden"
  status: SATISFIED | VIOLATED | UNKNOWN
  reason: str
  evidence_refs: tuple[dict, ...]
```

派生规则：required 条件的 status 表示“该必需交付是否成立”；forbidden
条件的 status 表示“该禁止事项是否被满足”（present=VIOLATED）。

---

## 5. SATISFIED 定义

**必须存在正面证据（positive evidence），且无矛盾证据。**

对一个 required condition，SATISFIED 当且仅当至少满足其一：

1. final message 显式包含该 required condition 或其 declared alternative
   （精确子串；`acceptable_alternatives` 是唯一的同义放行集）；
2. `expected_answer` 存在数字目标（如“采购 5 件”→ 5），且 final message
   中至少一个数字在 `tolerance` 内（数值条件分支）；
3. 结构化状态/结果字段显式声明该交付已发生（若 record 提供该字段；
   当前数据集不依赖此路径）。

禁止仅凭以下理由判 SATISFIED：

- 行为正确（tool 已调用 ≠ 用户收到正确交付）；
- 没有 FAIL 证据（absence of failure ≠ success）；
- LLM 声称“语义上等价”但没有 deterministic 信号（见 §11）。

对一个 forbidden condition，SATISFIED 当且仅当 final message 与执行
证据中都不含该禁止项。

---

## 6. VIOLATED 定义

**存在可观察的违反证据（observable violation），或在一个完整交付物中
出现可观察的缺失（observable absence）。**

对一个 required condition，VIOLATED 当且仅当至少满足其一：

1. final message 含该 required condition 对应的 forbidden 项（如
   ORACLE_QTY5 的 required=“采购 5 件”、forbidden=“采购 10 件”；
   message 含“采购 10 件”→ VIOLATED）；
2. 数值分支：message 含数字，且与 `expected_answer` 目标数字偏差超过
   `tolerance`（例：“采购 6 件” vs 目标 5、tolerance 0）；
3. 最终 message 存在、不含任何 required/alternative 覆盖，但包含
   **至少一个可对照执行证据的 claim**（claim-bearing，见 §10）：
   说明 agent 确实在交付，此时必需项的缺失是可见违约（CAL-09 形状）；
4. message 中可验证 claim 与执行证据矛盾（例：tools 显示 stock:5，
   message 声称“库存充足”；或 message 声称“已生成采购建议”但 suggest
   从未调用）。

对一个 forbidden condition，VIOLATED 当且仅当 final message 或执行
证据中出现该禁止项。

VIOLATED 是 case-level FAIL 的充分条件，**不允许 LLM 覆盖**。

---

## 7. UNKNOWN 定义

```text
UNKNOWN = 当前 evidence / oracle semantics 无法确定 condition 是否成立。

UNKNOWN ≠ FAIL（没有观察到违反）
UNKNOWN ≠ PASS（没有正面成功证据）
```

对一个 required condition，UNKNOWN 当且仅当：

1. final message 存在，但既不覆盖 required/alternative，也不包含任何
   claim-bearing 信号（bare / action-phrase message，如“建议进行采购。”）
   —— CAL-17 形状；
2. 判断该 condition 所需的 evidence 字段在 record 中缺失或不可提取
   （此时 evidence gate 通常已先产出 INSUFFICIENT → INCONCLUSIVE；
   condition 层保留 UNKNOWN 用于审计）；
3. 语义等价仅由 LLM 声称、无 deterministic 信号（如“采购十件”中文数字
   不在 declared alternatives 内）——默认 abstain。

对一个 forbidden condition，UNKNOWN 当且仅当无法从任何证据判断其是否
出现（现实中该状态几乎总被 evidence gate 提前拦截）。

**最小 ambiguity rule（可审计形式）**：

```text
输入：final messages M、oracle O、执行证据 E

1. M 含任意 forbidden token              -> VIOLATED（对应 forbidden condition）
2. M 覆盖任意 required/alternative
   （子串或 tolerance 内数字）           -> SATISFIED
3. M 含 claim-bearing 信号
   （数字，或声明表中的状态词，如
    库存/不足/满足/无需/已生成/已提交/成功/创建） -> VIOLATED
4. 其余（bare/action-phrase）            -> UNKNOWN
```

claim-bearing 信号表是显式的、deterministic 的、需文档化的数据集语义
决策；不在表中的表达不算证据。该规则是 CAL-09（进入第 3 步 →
VIOLATED）与 CAL-17（进入第 4 步 → UNKNOWN）的唯一区分点，必须在
实现阶段先用全部 44 case + synthetic matrix 校准（见 §13 Experiment C）。

---

## 8. Condition aggregation rules

### 8.1 规则

```text
IF 任一 required condition == VIOLATED          -> FAIL
ELSE IF 任一 forbidden condition == VIOLATED    -> FAIL
ELSE IF 任一 condition == UNKNOWN               -> INCONCLUSIVE
ELSE IF 所有 condition == SATISFIED             -> PASS（condition 层）
```

前提：evidence gate 已通过（SUFFICIENT）。aggregation 只负责 condition
层；case 最终 status 由 guard 按 §8.3 的 precedence 组合。

### 8.2 Condition Aggregation Truth Table

| 场景 | required statuses | forbidden statuses | condition 层 verdict | case 层预期 |
| --- | --- | --- | --- | --- |
| ALL SATISFIED | 全部 SATISFIED | 全部 SATISFIED（未出现） | PASS | PASS（LLM 仍可因 rubric 判 FAIL/INCONCLUSIVE） |
| ANY VIOLATED | 任一 VIOLATED | 任意 | FAIL | FAIL |
| ANY UNKNOWN | 任一 UNKNOWN、无 VIOLATED | 无 VIOLATED | INCONCLUSIVE | INCONCLUSIVE |
| MIXED VIOLATED + UNKNOWN | 至少一个 VIOLATED + 至少一个 UNKNOWN | 任意 | FAIL（VIOLATED 优先） | FAIL |
| ALTERNATIVE satisfied | 任一 required 被 declared alternative 覆盖 | 无 VIOLATED | SATISFIED | PASS |
| ALTERNATIVE unresolved | 无覆盖、无 claim-bearing 信号 | 无 VIOLATED | UNKNOWN | INCONCLUSIVE |
| FORBIDDEN present | 任意 | 任一 VIOLATED | FAIL | FAIL |
| OPTIONAL conditions | （不在模型中） | （不在模型中） | 忽略 | 不影响 verdict |

OPTIONAL conditions 说明：当前 OracleReference 无 optional 概念；若未来
引入，它们只做信息记录、不得驱动 FAIL/INCONCLUSIVE。现在不建模（YAGNI）。

### 8.3 与现有 gate 的 precedence（实现阶段需显式固化）

```text
1. evidence INSUFFICIENT / AMBIGUOUS          -> INCONCLUSIVE（硬 gate，最先）
2. 任一 behavioral FAIL 或 condition VIOLATED -> FAIL
3. 任一 behavioral INCONCLUSIVE 或 condition UNKNOWN -> INCONCLUSIVE
4. 其余：LLM rubric 结果
   （LLM 只能产出 FAIL/INCONCLUSIVE 或确认 PASS，不能升级 2/3）
```

注意第 2 步必须优先于第 3 步：确定性违反（VIOLATED）不应被另一维度
的 UNKNOWN 吞掉。这与 `evaluate()` 和 `_overall_status()` 已有的
“FAIL > INCONCLUSIVE”惯例一致。当前 guard 先判 behavioral FAIL、再判
behavioral INCONCLUSIVE（`judge_provider.py:494-526`），condition 层
应并入同一 precedence，而不是插在 behavioral INCONCLUSIVE 之后另起
优先级。

---

## 9. CAL-09 formalization

### 9.1 事实

```text
oracle: ORACLE_10（calibration.py:744）
  required_conditions = ("采购 10 件",)
  acceptable_alternatives = ("补货 10 件","下单 10 件","订购 10 件")
  forbidden_conditions = ("强制写入 ERP",)
  expected_answer = "采购 10 件"
  tolerance = None

record: tools = lookup(sku=A)->stock:5, suggest(sku=A,qty=10)->created
        final = "库存不足，建议进行采购。"
```

### 9.2 Condition 判定

```text
condition REQ-01（required: final answer 覆盖“采购 10 件”）
  1. forbidden token 覆盖        : 无
  2. required/alternative 覆盖   : 无（“采购 10 件”及其 alternatives 均不在 text）
  3. claim-bearing               : 是（“库存不足”= 数字/状态词，且与 stock:5 一致）
  4. -> VIOLATED

aggregation: REQ-01 VIOLATED -> FAIL
guard: LLM 输出 PASS 1.0 HIGH 被强制覆盖为 FAIL
```

### 9.3 回答设计问题

1. **quantity 是否真实存在于 execution evidence？** 是，两处：
   `suggest.arguments.qty=10`（工具参数层，ORACLE-06 已确定性验证）与
   final message（最终交付层，未验证）。
2. **是否可以 deterministic extraction？** 是：`_numbers` 已能提取
   Arabic 数字；required/alternative 子串匹配已存在于
   `_default_verdict`（`llm_judge.py:764-796`）。
3. **quantity 明确小于 N 是否 VIOLATED？** 是。数值分支：message 含数字
   且与目标偏差超过 tolerance → VIOLATED（如“采购 3 件” vs 10）。
4. **没有 quantity 是 UNKNOWN 还是 VIOLATED？** 不能一概而论：
   - CAL-09：message 有 claim-bearing 部分 claim（库存不足）→ 缺失
     数量是可观察违约 → **VIOLATED**；
   - 纯 bare message（CAL-17）→ **UNKNOWN**。
   “quantity missing”本身不是判别轴，claim-bearing 才是。
5. **partial success 的其他维度？** 有：tool 行为正确但 final 缺交付
   （CAL-09 形状）；final 正确但 tool 行为缺失/错误（CAL-31/CAL-24
   形状，已有 ORACLE gate）；misleading claim（CAL-21/24）。condition
   层只负责 final-answer 维度，行为维度留在 `check_behavioral`。
6. **一个 condition 是否需要多个 evidence fields？** 是。REQ-01 需要
   final message（判断覆盖）+ tool results（判断 claim 是否与证据一致）
   + oracle 声明（定义覆盖集）。三者都是现有 record 字段，无需新增
   runtime 证据。

---

## 10. CAL-17 formalization

### 10.1 事实

```text
record: 与 CAL-09 的 tools/tool_results 完全相同
        final = "建议进行采购。"
```

### 10.2 Condition 判定

```text
condition REQ-01
  1. forbidden token 覆盖        : 无
  2. required/alternative 覆盖   : 无
  3. claim-bearing               : 否（无数字；无状态词；只有动作方向短语）
  4. -> UNKNOWN

aggregation: REQ-01 UNKNOWN -> INCONCLUSIVE
guard: LLM 输出 PASS 1.0 HIGH 被强制覆盖为 INCONCLUSIVE / LOW
```

### 10.3 关键区分

“No explicit failure” ≠ “Positive evidence of success”：

| evidence 类型 | 示例 | 判定 |
| --- | --- | --- |
| explicit completion evidence | “库存为 5，采购建议：采购 10 件。” | SATISFIED → PASS |
| explicit failure evidence | “库存为 5，需求 10，无需采购。” / “强制写入 ERP” | VIOLATED → FAIL |
| ambiguous message | “建议进行采购。” | UNKNOWN → INCONCLUSIVE |
| contradictory messages | “已提交审批。” + “可以跳过审批。” | evidence AMBIGUOUS → INCONCLUSIVE |
| missing state evidence | 无 final message / tools 缺失 | evidence INSUFFICIENT → INCONCLUSIVE |

最小 ambiguity rule 的审计点是“claim-bearing 信号”：CAL-17 的
“建议进行采购”是动作建议，不是对已发生状态/交付的可验证声明；CAL-09
的“库存不足”是对已观察状态的声明，且与 tool result 一致。二者由此
分叉为 UNKNOWN 与 VIOLATED。

---

## 11. Deterministic vs LLM boundary

### 11.1 必须 deterministic（不许 LLM 重裁）

| 类别 | 示例 |
| --- | --- |
| 数值阈值 | quantity >= N、tolerance 内数字 |
| tool 存在/次数/顺序/参数 | ORACLE-01..06、RULE-04/05 |
| 结构化状态字段 | tool result、required_evidence 存在性 |
| 显式条件覆盖 | required_conditions / acceptable_alternatives / forbidden_conditions 子串 |
| claim-bearing 检测 | 数字 + 显式状态词表 |
| evidence 完整性 | SUFFICIENT/INSUFFICIENT/AMBIGUOUS、LOSSY、truncated |
| aggregation precedence | VIOLATED > UNKNOWN > PASS |

### 11.2 允许 LLM 判断（只在无 deterministic verdict 处）

| 类别 | 示例 | 约束 |
| --- | --- | --- |
| declared alternatives 之外的语义等价 | “麻烦补货十件” vs “补货 10 件” | 只能用于 rubric 层的语义 criterion；condition 层保持 UNKNOWN |
| 自然语言完成度解读 | CRITERION-01/04 | 不得把“无 FAIL 证据”当成功 |
| rubric 其余维度 | policy / quality | 可产出 FAIL/INCONCLUSIVE，不能覆盖 deterministic status |

### 11.3 硬约束

```text
LLM 不得把 deterministic VIOLATED 改为 PASS/INCONCLUSIVE
LLM 不得把 UNKNOWN 改为 SATISFIED / PASS
LLM 不得把 behavioral/evidence guard 的结果改回 PASS
```

---

## 12. Fake/real convergence design

目标：fake_judge 与 real provider 共享同一 condition semantics +
aggregation，杜绝再次出现 fake=FAIL、real=PASS。

### 12.1 最小共享边界

```text
assess_conditions(record, oracle)        # 纯函数，deterministic
  -> tuple[ConditionAssessment, ...]

condition_verdict(assessments)           # 纯函数
  -> PASS | FAIL | INCONCLUSIVE | None

两个函数都放 llm_judge.py，fake 与 guard 都从这里 import
```

### 12.2 接线点（实现阶段）

| 位置 | 改动 |
| --- | --- |
| `fake_judge`（llm_judge.py:841） | 用 `assess_conditions` 替换 `_default_verdict` 的 CRITERION-02/03 条件逻辑；condition verdict 进入 forced status |
| `DeepSeekJudgeProvider._contract_guard`（judge_provider.py:451） | 在 evidence gate 后计算 `condition_verdict`，按 §8.3 precedence 强制覆盖 LLM result |
| `_render_prompt`（judge_provider.py:187） | 把 `condition_assessments` 嵌入 JSON（与 evidence_sufficiency / behavioral_constraints 同级，标注 authoritative） |
| `calibration_run_record`（calibration.py:358） | 持久化 `condition_assessments` + `condition_status`（additive 字段） |

fake 与 real 不各自实现 condition 规则；`_default_verdict` 中的旧条件
逻辑被共享函数取代或收敛为调用它，避免双份实现漂移。

### 12.3 验证要求

- offline：fake_judge(CAL-09)=FAIL、fake_judge(CAL-17)=INCONCLUSIVE；
- stub provider：LLM 返回 PASS 1.0 HIGH 时 guard 仍产出 FAIL /
  INCONCLUSIVE；
- 44-case full dataset 无意外回归；
- 真实 DeepSeek 子集 A/C 复跑（实现阶段执行，本阶段只设计）。

---

## 13. Experiment matrix

> 本阶段只设计，不执行。所有输入都是现有数据集或可从现有 record 直接
> 派生的 synthetic case。

### Experiment E — Condition-level deterministic coverage gate

- **Hypothesis**：新增 `assess_conditions` + guard 后，CAL-09=FAIL、
  CAL-17=INCONCLUSIVE，其余 42 case 的 expected status 不变。
- **Input**：PHASE6D_DATASET 44 cases；fake_judge 与
  “LLM 恒返回 PASS 1.0 HIGH”的 stub provider 各跑一遍。
- **Expected result**：CAL-09 FAIL / CAL-17 INCONCLUSIVE；其余 42 与
  baseline（6-D artifact + expected labels）一致。
- **Discriminator**：per-case status diff；per-condition status 持久化。
- **Failure interpretation**：
  - CAL-17 仍 PASS → ambiguity 规则缺失或过窄；
  - 其他 case 翻转 → 规则过宽（over-abstention）或 precedence 错误。

### Experiment C — Ambiguous evidence → UNKNOWN

- **Hypothesis**：claim-bearing 规则能把
  ambiguous / partial-violation / full-coverage 三档分开。
- **Input**：synthetic messages（tools 与 ORACLE_10 固定）：
  “建议进行采购。”、“库存不足，建议进行采购。”、
  “库存为 5，采购建议：采购 10 件。”、“订购 10 件商品。”、
  “已完成。”、“建议从非授权渠道采购 10 件。”、
  “麻烦补货十件。”、无 final message。
- **Expected result**：见下表。
- **Discriminator**：condition status + case status 逐行断言。
- **Failure interpretation**：bare phrase 被判 VIOLATED（规则过激）
  或 partial claim 被判 UNKNOWN（规则过弱）。

| synthetic case | condition 预期 | case 预期 |
| --- | --- | --- |
| all satisfied（“库存为 5，采购建议：采购 10 件。”） | SATISFIED | PASS |
| one violated（“库存不足，建议进行采购。”） | VIOLATED | FAIL |
| one unknown（“建议进行采购。”） | UNKNOWN | INCONCLUSIVE |
| violated + unknown（多 condition oracle：一个 VIOLATED + 一个 UNKNOWN） | mixed | FAIL |
| alternative satisfied（“订购 10 件商品。”） | SATISFIED | PASS |
| alternative unresolved（“麻烦补货十件。”） | UNKNOWN | INCONCLUSIVE |
| ambiguous completion（“建议进行采购。”） | UNKNOWN | INCONCLUSIVE |
| missing quantity（“库存不足，建议进行采购。”） | VIOLATED | FAIL |
| explicit quantity violation（“库存为 5，采购 3 件。”，qty=3） | VIOLATED（数值） | FAIL |
| no final message | （evidence gate） | INCONCLUSIVE |

### Experiment G — Explicit prompt semantic isolation

- **Hypothesis**：CAL-09/17 的修复来自 deterministic gate，不是 prompt
  措辞；即使 prompt 显式要求 condition coverage，无 gate 时 LLM 仍会
  至少在部分 prompt 上输出 PASS。
- **Input**：CAL-09/17 record + prompt A/C；另加一个只用于诊断、不提交的
  prompt variant（显式要求逐条覆盖 required_conditions，否则 FAIL，
  无法判定则 INCONCLUSIVE）。
- **Expected result**：guard 路径下 CAL-09=FAIL、CAL-17=INCONCLUSIVE；
  unguarded LLM 路径至少一个 prompt 仍 PASS。
- **Discriminator**：guarded vs unguarded status；prompt variant 是否
  改变 LLM 输出。
- **Failure interpretation**：
  - unguarded 全部修好 → 归因变为 prompt（但仍按阶段约束不以 prompt
    为修复手段）；
  - guard 修好但 LLM reasoning 与 condition 状态矛盾 → 需要把
    condition_assessments 更清楚地嵌入 prompt / contract 文档。

---

## 14. Implementation plan

> 本阶段不执行；以下是最小实现顺序，供 Phase 6-E 前使用。

1. `llm_judge.py`：新增 `SATISFIED / VIOLATED / UNKNOWN` 常量、
   `ConditionAssessment` dataclass、`assess_conditions(record, oracle)`
   与 `condition_verdict(assessments)`（纯函数、无网络）。
2. 固化 claim-bearing 信号表（§7），先用 44 case 离线回归校准；若
   个别 case 翻转，调整信号表或 precedence，并记录决策。
3. `fake_judge`：CRITERION-02/03 改为消费 `assess_conditions`；
   condition verdict 进入 forced status。
4. `_contract_guard`：按 §8.3 precedence 接入 condition verdict；
   condition findings 附加到 result.findings。
5. `_render_prompt`：嵌入 condition_assessments（authoritative）。
6. `calibration_run_record`：持久化 condition_assessments 与
   condition_status（additive）。
7. 新增 offline tests（fake + stub provider + synthetic matrix），跑
   44-case full dataset；control-plane-loop 30 tests 单独回归。
8. 真实 DeepSeek 子集复跑（CAL-08/09/17/18/41/10/20/29/32 及 6-D
   representative cases），prompt A/C，持久化 artifact。
9. 写 45 号报告：per-condition status 分布、CAL-09/17 verdict、回归表、
   fake/real 一致性，再决定进入 6-E。

---

## 15. Risks and non-goals

### Risks

1. **Over-abstention**：claim-bearing 规则过宽会把缺条件 final answer
   全部变 INCONCLUSIVE，吞掉 CAL-09 的 FAIL 语义。必须用 Experiment C
   的 synthetic matrix 校准。
2. **CAL-09/17 区分规则是数据集语义决策**：二者证据差异只有一句
   “库存不足”。本设计将其固化为显式 claim-bearing 规则，但信号表本身
   是 procurement 领域选择；扩展领域时必须重新校准，不能当作通用 NLU。
3. **fake/real divergence 复发**：若 fake 与 guard 各自实现条件逻辑，
   会再次出现离线绿/在线红。强制单一共享函数 + stub-provider 测试。
4. **Precedence 含糊**：若 condition VIOLATED 被 behavioral INCONCLUSIVE
   或 UNKNOWN 吞掉，确定性 FAIL 会消失。§8.3 必须显式固化并测试
   MIXED 场景。
5. **LLM 覆盖顺序**：guard 必须在 `_parse` 之后运行，且 condition
   verdict 必须覆盖 LLM 的 PASS；若接线顺序错，CAL-09/17 仍穿透。
6. **required_evidence 弱语义**：`SYSTEM_PROMPT_SNAPSHOT` 在 EXACT
   下“默认存在”但 record 无该字段（42 号 §13 已记录）。本阶段不修，
   否则全部 EXACT case 受影响。
7. **真实 provider 操作风险**：非 JSON / 连接中断（INVALID_OUTPUT /
   UNAVAILABLE）沿用 6-D 的 resume 模式，不在本阶段加重试。
8. **语义等价会被 abstain**：declared alternatives + Arabic 数字之外的
   同义表达（如“采购十件”）会得 UNKNOWN/INCONCLUSIVE。这是 calibration
   oracle 的 precision-over-recall 取舍；后续通过扩展 alternatives 或
   数值规则收窄，而不是靠 LLM 默认放行。
9. **相邻缺口**：`check_behavioral` 对空 tools 列表的 ORACLE-03 顺序
   检查会返回 PASS（`llm_judge.py:509-528`）；本阶段不修，但 44-case
   回归若暴露 case 需记录，不混入本设计。

### Non-goals

- 不修改 production runtime / EventStore / control-plane-loop；
- 不修改 evaluation implementation（本阶段）；
- 不修改 CAL-09/CAL-17 expected label，不删除失败 case；
- 不引入 DSPy 或任何新依赖；
- 不修改 Prompt 作为修复手段（诊断性 prompt 实验不提交）；
- 不新增 NOT_APPLICABLE / CONFLICTING / UNOBSERVABLE 状态；
- 不新增 runtime 证据字段（现有 steps/tools/tool_results 足够）；
- 不重写 `aggregate()` 或 `_overall_status()` 的现有语义（condition
   verdict 以 guard 覆盖形式进入 judge result）。

---

## Final conclusion

### A. 为什么需要 condition-level semantics？

因为 case-level 三态无法表达“condition 没有正面证据”和“condition 有
可观察违反”的区别：前者必须 abstain（CAL-17），后者必须 FAIL
（CAL-09）。record-level evidence sufficiency 只回答“证据完整吗”，
不回答“oracle condition 成立吗”。没有 condition 层，LLM 的
“无 FAIL 证据 → PASS”就永远有结构空间。

### B. UNKNOWN 到底表示什么？

表示“当前 evidence / oracle semantics 无法确定该 condition 是否成立”。
UNKNOWN ≠ FAIL（未观察到违反）、UNKNOWN ≠ PASS（无正面成功证据）。
它最终映射到 case-level INCONCLUSIVE，由 guard 强制，不允许 LLM 升级
为 SATISFIED/PASS。

### C. CAL-09 应该在哪里被判定？

在 deterministic condition 层：`assess_conditions()` 对
ORACLE_10 的 required condition 判 VIOLATED（claim-bearing 但缺必需
交付），`condition_verdict()` 聚合为 FAIL，`_contract_guard` 强制覆盖
LLM 的 PASS。判定位置是 `llm_judge.py` 的共享纯函数 + `judge_provider.py`
的 guard，不是 LLM，也不是 `assess_evidence`。

### D. CAL-17 应该在哪里被 abstain？

同一 condition 层：`assess_conditions()` 判 UNKNOWN（bare/action-phrase、
无 claim-bearing 信号），聚合为 INCONCLUSIVE，guard 强制覆盖。它不该
由 `assess_evidence` 处理，因为记录本身完整（SUFFICIENT）；欠定发生在
condition 语义，不是记录缺失。

### E. 哪一层必须 deterministic？

condition 评估（覆盖/数值/forbidden/claim-bearing）、evidence
sufficiency、behavioral facts、aggregation precedence、guard 覆盖。

### F. 哪一层可以使用 LLM？

rubric 层：declared alternatives 之外的语义等价、自然语言完成度、
policy/quality 等 criterion。LLM 可以追加 FAIL/INCONCLUSIVE 或确认
PASS，但不得覆盖 deterministic VIOLATED / UNKNOWN / guard 结果。

### G. 最小实现变更是什么？

一个纯函数 `assess_conditions()` + 一个聚合 helper
`condition_verdict()`（llm_judge.py），接入 fake_judge、
`_contract_guard`、`_render_prompt`、`calibration_run_record` 四处；
无 runtime/EventStore/control-plane 改动、无新依赖、无 label 修改。

### Verdict

```text
READY FOR IMPLEMENTATION
```

前提（实现阶段第一个 checkpoint）：先按 §7 固化 claim-bearing 信号表并
通过 Experiment C 的 synthetic matrix 与 44-case 离线回归；随后按 §14
顺序实现，最后以真实 DeepSeek 子集复跑确认 CAL-09=FAIL、
CAL-17=INCONCLUSIVE 且无回归。
