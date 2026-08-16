# 41 — Phase 6-D Report: Behavioral Oracle & Evidence Sufficiency

> 阶段：Phase 6-D。前置：Phase 6-C（commit `45143c7`，
> `40-calibration-report.md`）。
> 范围：仅 evaluation / archaeology 代码、测试、文档与实验 artifact；
> 不修改 production runtime、EventStore、control-plane loop、agent 执行路径。
> 执行：2026-08-16，DeepSeek `deepseek-v4-flash`（`temperature=0, seed=42,
> max_tokens=8192`）。

## 1. Phase 6-D hypothesis

6-C 的 calibration failures 主要不是“LLM judge 不够聪明”，而是 judge 之前缺两层
结构性保护：

1. **Oracle 表达能力不足**：tool 行为（顺序、参数、调用次数、副作用、禁用工具）
   无法进入正式 oracle，导致正确 final answer 掩盖错误工具行为（CAL-14）。
2. **Evidence sufficiency 缺失**：judge 的 confidence 可以直接覆盖证据缺口，
   导致 PARTIAL context + 缺失关键证据仍输出 HIGH-confidence PASS（CAL-25）。

假设：在 judge 之前显式加入 Evidence Sufficiency 门控 + 确定性 Behavioral
Oracle 约束后，false pass 与 abstention violation 会下降，且不会把所有
PARTIAL 一律判成 INCONCLUSIVE（仅当 oracle 所需证据缺失时 abstain）。

## 2. Phase 6-C failure taxonomy

6-C（Prompt A, N=30）：

| 类别 | 数量 | 代表 case |
| --- | --- | --- |
| false pass（expected FAIL → PASS） | 2 | CAL-09（partial success）、CAL-14（tool order misuse） |
| abstention violation（expected INCONCLUSIVE → PASS/FAIL） | 3 | CAL-17（ambiguous → PASS）、CAL-25（PARTIAL+missing evidence → PASS）、CAL-27（ambiguous+PARTIAL → FAIL） |
| score calibration 偏差 | 2 | CAL-24、CAL-27 score 超出设计区间 |
| 其他 status 正确但 confidence 偏高 | 若干 | TASK-JUDGE-05 等 |

根因归因（不再笼统归因于 LLM judge）：

| Failure | Oracle incomplete | Evidence insufficient | Judge incorrect | Calibration incorrect |
| --- | --- | --- | --- | --- |
| CAL-09 | ✓（缺数量的正确性无法被 oracle 拒绝） | | ✓ | |
| CAL-14 | ✓（tool order 无 oracle 表达） | | ✓ | |
| CAL-17 | | | ✓（ambiguous 未 abstain） | |
| CAL-25 | | ✓（required evidence 无声明） | ✓ | |
| CAL-27 | | ✓ | ✓ | |
| CAL-24 score | | | ✓ | ✓ |

## 3. Oracle gap

6-C `OracleReference` 只能表达 final-answer 层面的
`expected_answer / required_conditions / forbidden_conditions /
acceptable_alternatives / tolerance / expected_constraints`，无法表达：

- required / forbidden tools（TaskSpecification 有，但 oracle 没有）；
- required / forbidden tool order；
- max calls；
- tool call 参数约束（例如 suggest qty 必须等于目标值）；
- side-effect 约束；
- oracle 需要的证据种类（required_evidence）。

因此 judge 只能从自然语言描述里“猜”工具行为是否正确，prompt 再聪明也无法
把缺失的表达变成确定性结论。

## 4. Judge gap

- judge 的 confidence 可以直接覆盖证据缺口：`_contract_guard` 只拦截
  MISSING context 与 LOSSY，不拦截 PARTIAL + 缺失 oracle-required evidence；
- judge reasoning 可以“脑补”未观察事实（CAL-25 输出 1.0 PASS）；
- judge 没有权威来源区分“行为 FAIL”与“语义 FAIL”。

## 5. Evidence gap

6-C 只有二元/三态：context provenance 存在与否 + LOSSY。没有显式的
SUFFICIENT / INSUFFICIENT / AMBIGUOUS 概念，也没有“oracle 需要哪些证据”
的声明，因此 PARTIAL 只能一刀切（全部 abstain）或完全忽略（6-C 的
`context_policy` 属于测试内 fake，未进入真实 provider guard）。

## 6. Abstention policy（6-D 固化）

1. evidence verdict 不是 `SUFFICIENT` → INCONCLUSIVE + LOW；
2. ambiguous evidence（LOSSY / final messages 与 oracle 条件冲突）→
   INCONCLUSIVE + LOW；
3. oracle 声明的 required evidence 缺失 → INCONCLUSIVE + LOW；
4. confidence 不能覆盖 evidence insufficiency：guard 在 judge 之后强制覆盖；
5. judge reasoning 不能把缺失证据当作已观察事实（prompt 显式声明 + guard）；
6. PARTIAL context 本身不 abstain：仅当 oracle 所需证据确实缺失时
   INSUFFICIENT。

实现位置：`evaluate/evidence` 逻辑在 `llm_judge.py` 的
`assess_evidence()` / `check_behavioral()`，fake judge 与
`DeepSeekJudgeProvider._contract_guard` 都强制执行。

## 7. Behavioral oracle design

`OracleReference` 增量新增（全部 optional，backward compatible）：

| Field | 语义 | 判定 |
| --- | --- | --- |
| `required_tools` | 必须调用 | 未调用 = FAIL；tools 缺失 = INCONCLUSIVE |
| `forbidden_tools` | 禁止调用 | 调用 = FAIL |
| `required_order` | 必须按序出现 | 逆序 = FAIL |
| `forbidden_order` | 禁止该先后关系 | 出现 = FAIL |
| `max_calls` | 总调用次数上限 | 超限 = FAIL |
| `tool_call_constraints` | 每工具 min/max calls + 参数约束 | 违反 = FAIL |
| `side_effect_constraints` | 禁止的副作用 | 出现 = FAIL；无副作用证据 = INCONCLUSIVE |
| `required_evidence` | oracle 需要的证据种类 | 缺失 = INSUFFICIENT |

设计原则：

- oracle 只描述“可验证的行为事实”，不硬编码 execution implementation
  details；judge 只消费最终 Finding，不自己解析工具语义；
- acceptable alternatives 继续由 oracle 表达（answer / 参数层面）；
- 可表达“A、B 两条工具路径都可以，但不能出现 C”：用 required_tools /
  tool_call_constraints 的 min_calls + 允许路径，forbidden_tools 排除 C；
- 可表达“最终答案正确，但 tool order 错误仍 FAIL”：oracle required_order
  是确定性 FAIL，guard 强制覆盖 judge 的 PASS。

## 8. 6-C vs 6-D 实验结果

real-provider：DeepSeek `deepseek-v4-flash`，`temperature=0, seed=42`。

| 指标 | 6-C A (N=30) | 6-D A (N=44) | 6-D C (N=44) |
| --- | --- | --- | --- |
| agreement | 0.833 | 0.955 | 0.955 |
| false pass | 0.067 | 0.023 | 0.023 |
| false fail | 0.000 | 0.000 | 0.000 |
| inconclusive | 0.133 | 0.250 | 0.250 |
| abstention（expected decidable 中被误 abstain） | 0.000 | 0.000 | 0.000 |
| confidence accuracy (HIGH) | 0.840 | 0.939 | 0.939 |
| calibration error (HIGH) | 0.160 | 0.061 | 0.061 |
| mis_calibrated | CAL-09, CAL-14, CAL-17, CAL-25 | CAL-09, CAL-17 | CAL-09, CAL-17 |

按 generation 拆分（6-D A）：

| generation | N | agreement | false pass | inconclusive | calibration error | mis_calibrated |
| --- | --- | --- | --- | --- | --- | --- |
| 6C（legacy 30） | 30 | 0.933 | 0.033 | 0.200 | 0.083 | CAL-09, CAL-17 |
| 6D（new 14） | 14 | 1.000 | 0.000 | 0.357 | 0.000 | 无 |

by context（6-D A）：EXACT 39 / PARTIAL 3 / MISSING 2 全部命中；
PARTIAL 与 MISSING 的 inconclusive rate 均为 1.0，EXACT 为 0.154。

Prompt sensitivity：6-D A vs 6-D C 在 44 个 case 上 status agreement = 1.0，
进一步支持“修复来自结构性 guard（evidence sufficiency + behavioral
oracle），而不是 prompt 措辞”。

### CAL-25 / CAL-14 verdict

| case | 6-C | 6-D |
| --- | --- | --- |
| CAL-25（PARTIAL + missing required evidence） | PASS 1.0 HIGH（CALIBRATION_FAILURE） | INCONCLUSIVE LOW（evidence gate） |
| CAL-14（tool order misuse） | PASS 1.0 HIGH（false pass） | FAIL（ORACLE-03 behavioral guard） |

### 6-D 新 cases（CAL-31..44，Prompt A）

14/14 全部符合 expected status：

- FAIL：CAL-31（partial success）、CAL-33（tool misuse）、CAL-34（order）、
  CAL-35（forbidden tool）、CAL-39（correct answer + invalid behavior）、
  CAL-42（side effect）、CAL-43（max_calls）、CAL-44（forbidden order）；
- INCONCLUSIVE：CAL-32（ambiguous）、CAL-36（missing tool result）、
  CAL-37（truncated）、CAL-38（incomplete state）、CAL-40（tempting answer +
  insufficient evidence）；
- PASS：CAL-41（acceptable alternative）。

## 9. 已修复问题

- CAL-25：PARTIAL context + required evidence 缺失不再产生 HIGH PASS；
- CAL-14：tool-order misuse 从 false PASS 变为 FAIL；
- CAL-27：ambiguous + PARTIAL 由 evidence gate（required evidence 缺失）覆盖；
- 6-D A：mis_calibrated 从 4 个降到 2 个（CAL-09、CAL-17），两者都是
  judge 语义/校准问题，不再是 evidence/behavioral 层问题；
- oracle 现在可以表达 tool 行为约束与所需证据；
- calibration run 持久化新增 `evidence_sufficiency / oracle_status /
  deterministic_status / generation` 等字段。

## 10. 仍然存在的 gap / 限制

- 6-D 的 N=44 仍以 procurement 单领域为主，per-category 样本不足以外推；
- CAL-17（ambiguous final answer → PASS 1.0 HIGH）在 6-D A 仍未被修复：
  evidence 充分（required evidence 都在），ambiguous 检测目前只覆盖
  LOSSY 与 final messages 冲突；CAL-17 是单条模糊 final message，
  属于 judge 语义 abstention gap；
- CAL-09（partial success 缺数量 → PASS）仍存在：oracle 已声明
  required_conditions，模型仍给出 PASS，属于 judge/calibration gap；
- 真实 provider 偶发非 JSON / 连接中断（`INVALID_OUTPUT` /
  `UNAVAILABLE`），6-D 通过分批 resume 完成；`judge_provider` 未为此
  增加重试逻辑（属已知操作限制）；
- fake judge 无法替代真实 judge 的语义 abstention（CAL-17 类 ambiguous
  在 offline 只能由 real provider 验证）；
- `required_order` 目前按工具名首次出现位置检查
  （`ponytail:` 注释：重复调用同一工具的顺序语义未建模）；
- side-effect 约束依赖 record 显式携带 `side_effects` 字段，真实 runtime
  是否产出该字段未在本阶段验证（若没有，则记录为 runtime gap）；
- runtime / EventStore / control-plane-loop 未修改；任何需要 runtime 提供
  新证据字段的需求都记录为 gap，不在本阶段越界实现。

## 11. 结论

**最终 verdict：COMPLETE。**

验收核对：

- [x] 所有现有 evaluation tests 通过（188 passed / 3 real-provider
  BLOCKED-skip，离线环境）
- [x] 所有新增 offline tests 通过（26 个 6-D tests）
- [x] runtime regression 不受影响（116 passed）
- [x] control-plane-loop regression 不受影响（30 passed）
- [x] EventStore 未修改
- [x] control-plane-loop 未修改
- [x] behavioral/tool constraints 可表达（required/forbidden tools、
  order、max_calls、tool call arguments、side effects）
- [x] evidence sufficiency 成为显式概念（SUFFICIENT / INSUFFICIENT /
  AMBIGUOUS）
- [x] insufficient evidence 不能仅靠 confidence 产生 PASS（fake judge +
  real provider guard 双保险）
- [x] PARTIAL context 的误判规则正式固化（required evidence 缺失才
  INCONCLUSIVE；CAL-25/27 修复，其余 PARTIAL 正常判断）
- [x] CAL-25 真实修复验证（real DeepSeek A/C 均 INCONCLUSIVE/LOW）
- [x] CAL-14 tool-order misuse 明确 verdict（real A/C 均 FAIL）
- [x] 6-C / 6-D metrics 可直接比较（同一 metrics 计算器 + 同一 30 legacy
  cases；artifact 已持久化）
- [x] real-provider artifacts 持久化
  （`phase6d-calibration-runs-A.jsonl` / `-C.jsonl`，各 44 runs）
- [x] 文档完整记录失败与限制（本报告 §2/§9/§10）
- [x] negative evidence 未隐藏（CAL-09 / CAL-17 仍失败，如实记录）

剩余 gap 不属于本阶段验收项：CAL-09 / CAL-17 是 judge 语义与校准问题；
side-effects 字段是否由真实 runtime 产出未验证（若缺失，记 runtime gap）。

## 12. Reproduce

```text
# offline
python3 -m unittest discover -s docs/archaeology/deepseek-harness/evaluation/tests -p 'test_phase6d.py'

# real provider（DeepSeek deepseek-v4-flash；需网络 + ~/.codex/config.toml 中 deepseek provider）
python3 docs/archaeology/deepseek-harness/evaluation/calibration.py \
  --dataset 6d --prompt A \
  --persist docs/archaeology/deepseek-harness/evaluation/artifacts/phase6d-calibration-runs-A.jsonl
python3 docs/archaeology/deepseek-harness/evaluation/calibration.py \
  --dataset 6d --prompt C \
  --persist docs/archaeology/deepseek-harness/evaluation/artifacts/phase6d-calibration-runs-C.jsonl
```
