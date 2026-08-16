# 49 — TASK-JUDGE-01 Fixture Consistency Decision（Phase 6-E.1.A）

> 阶段：Phase 6-E.1.A（fixture/oracle archaeology + 决策）。
> 前置：Phase 6-E checkpoint `4ea1352`；Phase 6-E.1 分析
> `48-phase6e1-semantic-fallback-policy.md`。
> 范围：`docs/archaeology/deepseek-harness/evaluation/**` +
> `docs/archaeology/unified-runtime/42..48`。
> 约束：本阶段只做考古与决策；不修改 implementation / aggregate /
> guard / tests / expected labels；不 commit、不 push。

## 0. TL;DR

- TASK-JUDGE-01 的正确业务语义是 **A：采购 10 件**。
- fixture 的冲突来源是 task 文本 `（目标库存 10，当前库存 5）`：
  按“目标库存”字面阅读会推出“应采购 5”，但该 case 的
  source-of-truth（6-B 原始定义、ORACLE_10、record、全部历史 artifacts、
  6-D.3 条件语义）一致定义正确数量为 10。
- `采购 5` 不是 expected answer，也不是 acceptable alternative；它是
  6-E deepseek Prompt B 从错误 wording 推出的推理，另在 3 个同文本
  sibling case（CAL-20/26/29，ORACLE_QTY5）中以 oracle 形式存在。
- expected label `PASS` 正确，不允许为迁就文本改 oracle / 改标签。
- 推荐：方案 A（修 task 文本，按数量族拆分，不动 oracle/labels）。
- Final verdict：**FIXTURE NEEDS CORRECTION**（仅 task 文本；oracle 与
  expected label 正确）。6-E.1 policy implementation 不因此阻塞。

---

## 1. Source of truth

| 元素 | 位置 | 内容 |
| --- | --- | --- |
| CalibrationCase 定义 | `calibration.py:51` | `case_id / task_specification / execution_record / oracle_reference / rubric / expected_status / expected_score_range / expected_confidence_range / tags / context_quality` |
| task text | `calibration.py:834-838`（TASK_PROC） | `查询 SKU A 库存；若不足则生成数量正确的采购建议（目标库存 10，当前库存 5）。` required_tools=`inventory.lookup`,`procurement.suggest` |
| context | `calibration.py:723-746`（`_provenance`） | TASK-JUDGE-01 使用 `_proc_record` 默认 `EXACT`，`missing_semantics=[]`，`lossiness=()` |
| execution record | `calibration.py:1071-1082` + `_proc_record`（`calibration.py:798-831`） | `inventory.lookup(sku=A) -> stock:5`；`procurement.suggest(sku=A,qty=10) -> suggestion:created`；final=`库存为 5，采购建议：采购 10 件。` |
| oracle reference | `calibration.py:878-893`（ORACLE_10，`oracle:phase6c:procurement:qty10`） | expected_answer=`采购 10 件`；expected_business_outcome=`生成采购建议，数量 10 件`；required_conditions=(`采购 10 件`,)；forbidden_conditions=(`强制写入 ERP`,)；acceptable_alternatives=(`补货 10 件`,`下单 10 件`,`订购 10 件`,)；required_evidence=(`SYSTEM_PROMPT_SNAPSHOT`,)；required_order=(`inventory.lookup`,`procurement.suggest`)；tool_call_constraints=`suggest.qty == 10` |
| expected status | `calibration.py:1076-1081` | `PASS`，score 0.8–1.0，confidence HIGH |
| 6-B 原始定义（本 case 最早来源） | `llm_judge.py:1460-1490` + `judge_provider.py:591-598,652-660` | task=`查询库存，如果不足则生成正确采购建议。`（无“目标库存”文本）；record qty=10、final=`采购 10 件`、expected PASS；weak oracle `TASK_JUDGE_ORACLE`（expected_answer=`采购建议`）；specific oracle `ORACLE_SPECIFIC`（expected_answer=`采购建议：采购 10 件`，outcome=`库存不足时生成采购建议，数量 10 件`） |
| A/B/C artifacts | `phase6c-calibration-runs.jsonl`、`phase6d-calibration-runs-A/C.jsonl`、`phase6d3-calibration-runs-A/C.jsonl`、`phase6e-*.jsonl` | 6-C A/B PASS；6-D A/C PASS；6-D.3 A/C PASS（DETERMINISTIC）；6-E 9 组合中 8 个 PASS，唯一差异 = deepseek Prompt B → INCONCLUSIVE（LLM_FALLBACK） |
| 6-D.3 对该 case 的解释 | `44-phase6d3-condition-level-oracle-design.md`、`45-phase6d3-implementation-report.md` | REQ-01 以 `采购 10 件` 为 required condition；全部示例（含 `库存为 5，采购建议：采购 10 件。`）以 qty=10 为正确完成；数值偏差示例 `采购 3 件` vs 10 → VIOLATED |
| 6-D.1 对该 case 的解释 | `42-phase6d1-semantic-calibration-analysis.md:93-124` | 把任务要求读作“数量正确的采购建议（数量 10）”；oracle 表达 = `采购 10 件` + `suggest.qty==10`；未标记“目标库存”冲突 |
| 6-E 对该 case 的解释 | `47-phase6e-cross-backend-robustness-report.md:127,261-280`、`48-phase6e1-semantic-fallback-policy.md:89-229,681-690` | 判定为不必要 downgrade + prompt sensitivity + `SYSTEM_PROMPT_SNAPSHOT` 抽象误读 + fixture 语义不一致；`48 §10.4` 方案 X = task 文本改 `目标采购数量 10`（与 ORACLE_10 一致），方案 Y = oracle 改 qty=5 并同步 expected labels，方案 Z = 保留并记录缺陷 |

---

## 2. 当前 fixture 的语义冲突

### 2.1 冲突双方

| 侧 | 位置 | 表达的数量 |
| --- | --- | --- |
| task 文本（字面“目标库存”阅读） | `calibration.py:836` | 目标库存 10 − 当前 5 → 缺口 5 |
| oracle / record / expected label / 历史判定 | `calibration.py:878-893,1071-1082`；`llm_judge.py:1460-1490` | 正确采购数量 = 10 |

冲突在 6-C（`45143c7`）引入：TASK_PROC 增加了 `（目标库存 10，当前库存 5）`
这个解释性括号，同时把 6-B 的弱 oracle 强化为 ORACLE_10（qty=10）。
6-B 原始 task 文本没有该括号，也没有任何数量冲突。

### 2.2 “采购 5”从哪来

- TASK-JUDGE-01 自己的 fixture（task/oracle/record）**没有字面“采购 5”**。
- “应采购 5”首先出现在 6-E 真实 artifact 的 LLM reasoning
  （`phase6e-deepseek-44-B.jsonl` 第一行：target 10 / current 5 →
  implies correct qty 5），是模型对 `目标库存` 一词的推理。
- 同文件存在 3 个 sibling case 用同一个 TASK_PROC 文本但配 ORACLE_QTY5
  （expected_answer=`采购 5 件`）：CAL-20（`calibration.py:1289-1300`）、
  CAL-26（`1365-1375`）、CAL-29（`1398-1407`）。这是“采购 5 解释”的
  代码内来源，但不属于 TASK-JUDGE-01 的 oracle。

### 2.3 逐句归属

| 句子 | 角色 |
| --- | --- |
| `查询 SKU A 库存；若不足则生成数量正确的采购建议` | 业务要求（动作 + 条件 + 正确性要求） |
| `（目标库存 10，当前库存 5）` | 数量约束的**错误 wording**；按本 case 语义应表达“目标采购数量 10（或需求数量 10），当前库存 5” |
| `inventory.lookup(sku=A) -> stock:5` | observation（已观测库存） |
| `procurement.suggest(sku=A,qty=10)` + final `采购 10 件` | expected outcome（oracle 约束 + 最终交付） |

结论：`采购 5` 不是 expected answer、不是 acceptable alternative
（ORACLE_10 的 alternatives 全部是 10 件）；它是错误/过时 task wording
在字面阅读下产生的推理，且被 3 个 sibling oracle 固化。

---

## 3. 正确业务语义

**A：采购 10 件。**

判定依据（按优先级，均非 LLM 输出）：

1. **6-B 原始 case 定义**：TASK-JUDGE-01 从 Phase 6-B 继承，record
   qty=10、final `采购 10 件`、expected PASS；`ORACLE_SPECIFIC` 明确
   “数量 10 件”。这先于 6-C 的括号文本存在。
2. **oracle**：ORACLE_10 的 expected_answer / required_conditions /
   expected_business_outcome / tool_call_constraints 全部为 10。
3. **structured evidence**：44-case 数据集以 qty=10 为正确数量设计
   （TASK-JUDGE-05 qty=3 → FAIL、CAL-08 qty=10 → PASS、CAL-24 文案含
   10 但缺工具调用 → FAIL 等）。
4. **calibration case definition**：TASK-JUDGE-01 的 expected label 是
   PASS，且该 label 自 6-B 起未变。
5. **历史文档**：42 / 44 / 45 均把任务读作“数量 10”。

因此：`目标库存 10，当前库存 5 → 应采购 5` 只在 TASK_PROC 的字面阅读
下成立，与 TASK-JUDGE-01 的全部权威定义矛盾；正确语义是
“目标采购数量 10，当前库存 5，不足则采购 10 件”。

---

## 4. 方案 A/B/C

### 方案 A：修 task 文本

**A1（最小改动，不推荐单独落地）**：把 TASK_PROC / TASK_PROC_FORBID 的
`（目标库存 10，当前库存 5）` 改为 `（目标采购数量 10，当前库存 5）`
（即 `48 §10.4` 方案 X / V1）。

- 语义正确性：TASK-JUDGE-01 族自洽。
- 风险：TASK_PROC 被 33 个 case 共享、TASK_PROC_FORBID 被 3 个 case
  共享；其中 CAL-20/26/29 配 ORACLE_QTY5。改后这 3 个 case 的 task
  会变成“采购 10”，与自己的 oracle（采购 5）冲突——只是把矛盾换了个
  位置。

**A2（推荐）**：按数量族拆分 task 文本：

- qty=10 族（TASK-JUDGE-01..06、CAL-08..18/21/23/24/25/27/31/33..44
  等使用 TASK_PROC / TASK_PROC_FORBID 且 oracle 为 ORACLE_10 /
  ORACLE_6D_* 的 case）：task 文本改为 `目标采购数量 10，当前库存 5`
  （或 `需求数量 10，当前库存 5`）。
- qty=5 族（CAL-20/26/29）：保留/显式化 `目标库存 10，当前库存 5，
  采购缺口 5 件`（或独立 TASK_PROC_GAP），与 ORACLE_QTY5 一致。

| 维度 | 评估 |
| --- | --- |
| 语义正确性 | 两个族各自自洽；TASK-JUDGE-01 与其 oracle/record/label 完全一致 |
| regression risk | deterministic 层 0：`evaluate()` 只消费 required/forbidden tools，不解析 `natural_language_goal` 文本；oracle、record、expected labels 全部不变。LLM 层有 prompt 输入变化，需重跑 44×9 验证，预期 agreement 不降（消除已知歧义） |
| 与 6-D/6-E 历史证据 | 历史 artifacts 保留原文本，不可改写；新 run 需 dataset_version bump；48 V1 预测 deepseek B 修复后应 PASS |
| 业务语义 | 不变（采购 10 件） |
| 已有 artifact 可解释性 | 改善：task 与 oracle 同骨架，deepseek B 的 abstention 可从“fixture 触发”归因为纯 prompt sensitivity（若仍 abstain） |

### 方案 B：修 oracle / required_conditions

把 ORACLE_10 族改为 qty=5 / expected_answer=`采购 5 件`，并同步
TASK-JUDGE-01 等 case 的 record 与 expected labels。

| 维度 | 评估 |
| --- | --- |
| 语义正确性 | 只符合 TASK_PROC 字面阅读，违反 6-B 原始定义与全部历史判定 |
| regression risk | 极高：ORACLE_10 被 20 个 case、ORACLE_6D_*（expected_answer 均为 10）被 12 个 case 使用；TASK-JUDGE-01 需从 PASS 翻为 FAIL，CAL-08 等同步翻转；等于否定 6-B/6-C/6-D/6-E 全部验证 |
| 与历史证据 | 42/44/45 的 condition 语义全部以 10 为正确值，方案 B 使其全部失效 |
| 业务语义 | 改变（采购 10 → 缺口 5），且唯一依据是 6-C 新增括号的用词，不是原始业务定义 |
| artifact 可解释性 | 恶化：同一 case 的 label 翻转让所有历史 PASS 记录变矛盾 |

**结论：拒绝。** 原业务定义（6-B：qty=10 → PASS）没有被证明错误；
按用户规则，不允许仅为文本一致性改 expected labels。

### 方案 C：同时修 task + oracle

- **C1**：task 与 oracle 一起改为“目标库存 10 / 当前 5 → 采购 5”。
  等价于方案 B + 文本同步，风险与标签翻转问题同上，且改动面最大。
- **C2**：task 改“目标采购数量 10”+ oracle 保持不变 + 顺手把
  CAL-20/26/29 的 ORACLE_QTY5 也改为 qty=10。会把 CAL-20 的 expected
  label 从 FAIL 翻为 PASS，属于新业务定义决策，超出 TASK-JUDGE-01
  范围，且当前没有证据证明 CAL-20/26/29 的 6-C 原定义错误。

**结论：C 不比 A2 更正确（oracle 无需改），或比 B 更危险（label
翻转 + 范围外改动）。不作为推荐。**

---

## 5. 推荐方案

**方案 A2：只修 task 文本，按数量族拆分；不动 oracle、record、expected
labels、rubric。**

- qty=10 族 wording：`目标采购数量 10，当前库存 5`（沿用 48 V1，改动最小）。
- qty=5 族 wording：`目标库存 10，当前库存 5，采购缺口 5 件`
  （显式化，消除“目标库存”歧义）。
- 实现时新增 dataset 版本（如 `calibration:phase6d:procurement@2`）并保留
  旧版本 artifacts 作为历史证据。

可选后续（不阻塞本决策）：单独评估 CAL-20/26/29 是否应并入 qty=10 族；
若并入，需独立证明其原定义错误并处理 CAL-20 的 label。

---

## 6. 对历史 artifacts 的影响

- 所有 `artifacts/*.jsonl` 是历史输入/输出证据，**不改写、不重算**。
- 6-B/6-C/6-D/6-D.3 的 TASK-JUDGE-01 PASS 记录在各自时代定义下有效。
- 6-E deepseek B INCONCLUSIVE 的归因更新为：不必要 downgrade
  （aggregation policy）+ prompt sensitivity + fixture wording 触发；
  fixture 修正后按 48 V1 预测应回到 PASS。
- 文档影响：42/44/45 隐含的“目标库存=数量 10”解读由本文档取代；
  48 §10.4 方案 X 与本文档推荐一致（A2 是 X 的族级安全化版本）。

---

## 7. 是否需要重新生成 calibration cases

**不需要重新设计 44 个 case。** case 集合、execution records、oracle、
expected labels 全部不变；只改共享 task 文本。实现时 bump
`dataset_version` 以区分输入文本版本。

---

## 8. 是否需要重新跑 44 cases

**需要**（在修复实现获得批准后）：重跑 6-E 同款 9 组合
（fake / deepseek / model_studio × A/B/C），验证：

1. deterministic 层 44/44 不变（本决策不触碰任何判定逻辑）；
2. deepseek Prompt B 对 TASK-JUDGE-01 不再因文本冲突 abstain；
   若仍 INCONCLUSIVE，则可确认为纯 prompt sensitivity，由 6-E.1 policy
   吸收；
3. 无任何 case 的 expected label 翻转。

本阶段（决策）不跑。

---

## 9. 是否允许进入 6-E.1 implementation

**允许。** 依据：

- 6-E.1 policy 的正确性不依赖 TASK-JUDGE-01 的文本：authoritative PASS
  不得被 LLM 降级这一规则在“采购 10”与“采购 5”两种语义下都成立。
- 48 已判定 fixture 修复是独立事项（§10.4），不阻塞 policy 实现。
- 本文档确认正确业务语义为 A（采购 10），因此 TASK-JUDGE-01 的
  PASS 是 authoritative PASS，6-E.1 判定“不必要 downgrade”成立。
- fixture 修正（方案 A2）作为 6-E.1 实现后 44-case 重跑的 prerequisite，
  不作为 policy 实现 blocker。

---

## Final verdict

```text
FIXTURE NEEDS CORRECTION
```

---

## 10. 实现记录（Phase 6-E.1-A2，2026-08-16）

按方案 A2 落地，仅修 task 文本，按数量族拆分：

- qty=10 族：`TASK_PROC` / `TASK_PROC_FORBID` 的
  `（目标库存 10，当前库存 5）` 改为 `（目标采购数量 10，当前库存 5）`。
- qty=5 族：新增 `TASK_PROC_GAP`（`TASK-CAL-PROC-GAP`），显式
  `（目标库存 10，当前库存 5，采购缺口 5 件）`；CAL-20 / CAL-26 / CAL-29
  从 `TASK_PROC` 切换为该 task。
- dataset 版本：`calibration:phase6c:procurement` 与
  `calibration:phase6d:procurement` 均由 `1` 升至 `2`；历史 artifacts
  保留 `dataset_version=1` 原样，不重写。

详细审计见 `49a-task-judge-01-fixture-fix-report.md`。核心结果：

| 维度 | 结果 |
| --- | --- |
| task 文本变化 | 36/44（qty=10 族 33，qty=5 族 3） |
| expected label 变化 | 0 |
| oracle 变化 | 0 |
| deterministic evaluate() / verdict / evidence / oracle / conditions 变化 | 0/44 |
| 历史 artifact | 未修改 |

- 不是 `FIXTURE IS CORRECT`：task 文本 `（目标库存 10，当前库存 5）`
  确实与 oracle/record/label（qty=10）冲突，且与 3 个 sibling
  ORACLE_QTY5 case 构成族级矛盾。
- 不是 `BLOCKED`：正确业务语义可由 6-B 原始定义 + oracle + structured
  evidence 唯一确定为 **A：采购 10 件**；修复方向明确（方案 A2：
  修 task 文本、按数量族拆分），不触碰 oracle / expected labels。
- 本阶段未修改 implementation、aggregate、guard、tests、expected
  labels；未 commit、未 push。
