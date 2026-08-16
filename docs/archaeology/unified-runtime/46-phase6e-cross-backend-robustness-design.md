# 46 — Phase 6-E Cross-Backend Robustness Design

> 阶段：Phase 6-E（代码考古 + 架构分析 + 实验设计，不实现）。
> 前置：Phase 6-D.3（`18642e6`，已 push）。
> 范围：`docs/archaeology/deepseek-harness/evaluation/**` 只读考古；
> 输出本设计文档。不修改 implementation、不 commit、不 push。

---

## 1. Problem

当前所有真实结果都来自同一个组合：

- Model：`deepseek-v4-flash`
- Prompt：A / C
- Backend：`DeepSeekJudgeProvider`（OpenAI-compatible SDK -> `api.deepseek.com`）

因此尚未证明以下问题：

> 更换 Prompt 或 Judge backend 后，Evidence Gate、Behavioral Gate、
> Condition Oracle、Aggregation 是否仍然稳定？

本阶段的核心研究问题是：**Agent Quality Gate 与 Judge backend / prompt
是否真正解耦**。需要区分三种不同的稳定性，不能混为一谈：

1. **status robustness**：最终 PASS / FAIL / INCONCLUSIVE 是否稳定；
2. **score robustness**：0.0–1.0 的数值是否稳定；
3. **confidence robustness**：HIGH / MEDIUM / LOW 是否稳定。

三者不必相同。Phase 6-D.3 的 A/C 证据只证明了 status robustness 在
DeepSeek + 44-case 上的表现，score / confidence 已经出现可见差异。

---

## 2. Current baseline

### Checkpoints

| Phase | Commit | 状态 |
| --- | --- | --- |
| 6-C | `45143c7` | 基线 |
| 6-D | `bf91ca6` | 基线 |
| 6-D.1 | `bdba660` | 分析 |
| 6-D.2 | `beaa3f5` | 复现 |
| 6-D.3 | `18642e6` | 完成并 push |

### 已验证证据（来源：44 号设计、45 号报告 + artifacts）

| 维度 | 值 |
| --- | --- |
| synthetic matrix | 19/19（`tests/test_phase6d3_condition_oracle.py`，19 个 offline test） |
| offline 44-case fake vs stub | 44/44 状态一致（`artifacts/phase6d3-offline-44.jsonl`） |
| real DeepSeek Prompt A | 44/44 命中 expected（`phase6d3-calibration-runs-A.jsonl`） |
| real DeepSeek Prompt C | 44/44 命中 expected（`phase6d3-calibration-runs-C.jsonl`） |
| A vs C status agreement | 1.000（44/44） |
| false pass / false fail | 0 / 0 |
| calibration error（HIGH 组） | 0.000 |
| CAL-09 | FAIL（deterministic condition VIOLATED） |
| CAL-17 | INCONCLUSIVE（deterministic condition UNKNOWN） |

### 本机 artifact 复核（2026-08-16，只读统计）

| 指标 | Prompt A | Prompt C |
| --- | --- | --- |
| final status 分布 | PASS 7 / FAIL 25 / INCONCLUSIVE 12 | 同 A |
| rules deterministic_status 分布 | PASS 29 / FAIL 14 / INCONCLUSIVE 1 | 同 A |
| condition verdict 分布 | PASS 25 / FAIL 14 / INCONCLUSIVE 5 | 同 A |
| condition status 分布 | SATISFIED 45 / VIOLATED 22 / UNKNOWN 6 | 同 A |
| aggregation_source | DETERMINISTIC 43 / LLM_FALLBACK 1 | 同 A |
| score 与 A 不同 | — | 17/44（其中 8 个两侧都有值但不相等，9 个一侧为 null） |
| confidence 与 A 不同 | — | 2/44（CAL-34：A LOW / C HIGH；CAL-44：A MEDIUM / C HIGH） |

重要语义提醒：artifacts 里的 `final_verdict` 是 **judge 层结果**
（`provider.judge()` 返回、经过 `_contract_guard` 的 `LLMJudgeResult.status`），
不是 `aggregate(deterministic_result, (judge,))` 的统一最终结果。
`calibration_run_record` 另外持久化了 rules 层的 `deterministic_status`，
但 artifacts 没有做两层合并。Phase 6-E 的指标必须同时跟踪：

- judge 层 final（guard 后）；
- unified 层 final（`aggregate()` 后，rules 层 FAIL/INCONCLUSIVE 优先）。

两者在 TASK-JUDGE-04 / CAL-36 / CAL-37 / CAL-38 等 case 上已知不同
（judge 层 INCONCLUSIVE、rules 层 FAIL -> unified 层 FAIL，见 45 号
§12.5）；TASK-JUDGE-03 是 aggregation_source 不同但两层 final 相同的
特例。不能混用。

---

## 3. Architecture boundary

### 真实调用链

```text
CalibrationCase.jinput()                     calibration.py:78
  -> LLMJudgeInput(task, record,
                   evaluate(record, task),   evaluator.py:17 -> rules.py RULES
                   rubric, oracle)
  -> provider.judge(jinput, prompt_key)      judge_provider.py:626
       -> PROMPT_TEMPLATES[key]              judge_provider.py:278
       -> _render_prompt(...)                judge_provider.py:192
            -> assess_evidence(...)          llm_judge.py:374
            -> check_behavioral(...)         llm_judge.py:477
            -> assess_conditions(...)        llm_judge.py:818
            -> condition_verdict(...)        llm_judge.py:922
       -> _create(prompt)                    judge_provider.py:338   [DeepSeek 专用]
       -> _parse(...)                        judge_provider.py:378   [输出归一化]
       -> _contract_guard(...)               judge_provider.py:472   [deterministic 覆盖]
  -> calibration_run_record(...)             calibration.py:361
       -> _deterministic_verdict(...)        calibration.py:439
       -> aggregation_source 持久化
```

另有 `fake_judge`（`llm_judge.py:1060`）与
`aggregate()`（`llm_judge.py:1196`）两条路径：

- `fake_judge`：同一组纯函数 + 同样的 precedence，作为 offline 参照；
- `aggregate()`：把 rules 层 `EvaluationResult` 与多个 judge 结果合并，
  任何 judge 的 FAIL 优先于 PASS，conflict 默认 INCONCLUSIVE。

### 两层 deterministic

当前存在两层 deterministic 逻辑，Phase 6-E 必须分开测量：

1. **Rules 层**：`evaluate()` / RULE-01..13（`rules.py:79-508`），只读
   ExecutionRecord + TaskSpecification，判定完成度、未解析工具、必需/
   禁用工具、超时、上下文证据等。
2. **Oracle 层**：`assess_evidence` + `check_behavioral` +
   `assess_conditions` + `condition_verdict`，由 fake_judge 与
   `_contract_guard` 以相同 precedence 强制。

两层都完全不依赖 provider / prompt；但 guard 的“强制执行”目前只存在于
`fake_judge`（llm_judge.py）和 `DeepSeekJudgeProvider._contract_guard`
（judge_provider.py）两个位置。

### 代码考古回答

**Q1. 哪些步骤完全不依赖 provider？**

- `evaluate()` / rules（`evaluator.py:17`，`rules.py`）；
- `assess_evidence` / `check_behavioral` / `assess_conditions` /
  `condition_verdict`（`llm_judge.py:374/477/818/922`）；
- `_deterministic_verdict`（`calibration.py:439`）；
- `_render_prompt` 里的 deterministic 数据组装（`judge_provider.py:192-231`）；
- `fake_judge` 与 `aggregate()` 的 precedence 逻辑（`llm_judge.py:1060/1196`）；
- calibration 指标、prompt/backend comparison（`calibration.py:196/527/557`）。

**Q2. 哪些步骤依赖 prompt？**

只有 LLM 语义层：模型输出的 status / score / confidence / findings /
reasoning_summary 会随 prompt 指令变化。`_render_prompt` 的 JSON payload
对 A/B/C 完全相同，只有 instructions 段落不同。deterministic guard 会吸收
“LLM 想 PASS”的部分尝试，但无法吸收语义层主动追加的 FAIL/INCONCLUSIVE。

**Q3. 哪些步骤依赖 LLM？**

- 无 deterministic verdict 时的 rubric 语义判定（CRITERION-01..05）；
- score / confidence / reasoning_summary / findings 细节；
- 输出格式可靠性（非 JSON、字段缺失、`UNKNOWN` 回显等）；
- provider 可用性与延迟。

**Q4. provider 是否可能绕过 deterministic gates？**

当前真实路径不能：`DeepSeekJudgeProvider.judge()` 固定执行
`_parse` -> `_contract_guard`（`judge_provider.py:626-638`），guard 重新跑
evidence / behavioral / condition 并强制覆盖；`aggregate()` 还会再强制
rules 层 FAIL/INCONCLUSIVE。但边界是 **结构性的协议，不是机制**：

- `JudgeProvider` 只是 `Protocol`（`calibration.py:329`、
  `judge_provider.py:148`），没有任何强制手段阻止未来 provider 实现
  `judge()` 时跳过 guard；
- guard 代码没有抽成共享函数/基类，`fake_judge` 与 `_contract_guard`
  是两份并列的 precedence 实现（共享纯函数，但 enforcement 重复）。

结论：DeepSeek 路径不可绕过；未来 provider 是否绕过取决于实现纪律，
Phase 6-E 需要把“guard 必跑”变成可验证契约（见 §6）。

**Q5. parser / normalization 是否可能导致不同 backend 出现不同 verdict？**

会，但只影响语义层：

- 顶层 `UNKNOWN` 与 finding 级 `UNKNOWN` 都被归一化为 `INCONCLUSIVE`
  （`judge_provider.py:379/412`），A/B/C 相同；
- findings 缺失时按顶层 status 补齐；required criterion 无证据时强制
  `INCONCLUSIVE UNSUPPORTED`（`judge_provider.py:423-443`）；
- `_overall_status` 以 findings 为准，顶层 status 不一致时 findings 赢；
- 非 JSON / schema 不合法 -> `INVALID_OUTPUT`，该 case 直接失败而不是
  产生 verdict（provider 可靠性问题）；
- score=null 与 score=数字 的混合输出已被 6-D.3 真实观察到（A/C 17 处
  score 不同），但不影响 status。

deterministic 层不受 parser 影响：guard 在 parser 之后重新计算，与原始
payload 无关。

**Q6. score / confidence 是否会影响最终 verdict？**

不会。当前代码中 verdict 只来自 status：

- `_parse`：`overall = _overall_status(findings)`；
- `_contract_guard`：仅用 status 覆盖；
- `aggregate()`：仅用 judge.status，score 只在“PASS 且无 conflict”时
  参与 `final_score` 平均，confidence 只在最后取 min。

score/confidence 只受合法性约束（范围、PASS+LOW 禁止、INCONCLUSIVE+HIGH
禁止），非法值会变成 `INVALID_OUTPUT`（运行失败），不会翻转 verdict。

**Q7. fake_judge、DeepSeek、future provider 的 shared boundary 是什么？**

- 数据契约：`LLMJudgeInput` / `LLMJudgeResult` / `JudgeRubric` /
  `JudgeFinding` / `OracleReference`（`llm_judge.py:82-241`）；
- 纯函数：evidence / behavioral / condition / verdict（`llm_judge.py`）；
- 调用契约：`JudgeProvider` Protocol（`calibration.py:329`，
  `judge_provider.py:148`，签名略有差异：后者多可选 `rubric`）；
- prompt 渲染：`_render_prompt` 是模块级函数（`judge_provider.py:192`），
  future provider 可 import 复用，但它物理上住在 DeepSeek 模块里；
- guard enforcement：目前不是共享代码，需要 future provider 自行调用
  或继承 `DeepSeekJudgeProvider`；
- offline 参照：`fake_judge`（函数）与 `OfflineJudge`
  （`tests/test_calibration.py:19`，测试用 adapter）。

---

## 4. Prompt boundary analysis

### A / B / C 共同字段

三者使用同一个 `_render_prompt` JSON payload 和同一个输出 schema
（`judge_provider.py:192-276`）：

| 输入字段 | A | B | C |
| --- | --- | --- | --- |
| task_specification | 相同 | 相同 | 相同 |
| execution_record（含 final_messages / provenance / lossiness） | 相同 | 相同 | 相同 |
| deterministic_evaluation（rules 层） | 相同 | 相同 | 相同 |
| rubric | 相同 | 相同 | 相同 |
| oracle_reference | 相同 | 相同 | 相同 |
| evidence_refs | 相同 | 相同 | 相同 |
| evidence_sufficiency | 相同 | 相同 | 相同 |
| behavioral_constraints | 相同 | 相同 | 相同 |
| condition_assessments + condition_verdict | 相同 | 相同 | 相同 |
| 输出 schema | 相同 | 相同 | 相同 |

### Wording 差异（唯一变量）

| Prompt | prompt_ref | instructions 要点 |
| --- | --- | --- |
| A | `prompt:phase6b:judge:A:v1` | 独立语义 judge；严格按 evidence；不猜；缺失/lossy/不足 -> INCONCLUSIVE LOW |
| B | `prompt:phase6b:judge:B:v1` | 通用版本：按 rubric 评估；只依据实际存在的 evidence；无法支持明确 verdict（含 lossy/missing）-> INCONCLUSIVE LOW |
| C | `prompt:phase6d:judge:C:v1` | A + 显式声明 deterministic 块 authoritative：evidence 非 SUFFICIENT -> INCONCLUSIVE LOW；behavioral FAIL -> FAIL；condition VIOLATED -> FAIL、UNKNOWN -> INCONCLUSIVE；均不可覆盖 |

### 哪些变化影响什么

| 变化 | 影响 score | 影响 status | 被 guard 吸收 |
| --- | --- | --- | --- |
| A -> B instructions | 是（语义层） | 仅 LLM-fallback case | 是（deterministic case） |
| A -> C deterministic 声明 | 是（语义层） | 仅 LLM-fallback case | 是（deterministic case） |
| payload 中嵌入 condition_assessments | 否（纯数据） | 否（guard 已重新计算） | — |
| prompt_ref / prompt_version | 否 | 否 | — |

### 为什么 6-D.3 中 A vs C status agreement = 1.0

不是“prompt 不影响 status”，而是：

1. 44 个 case 里 43 个的最终 status 由 deterministic gate 决定
   （`aggregation_source=DETERMINISTIC`），guard 无条件覆盖 LLM；
2. 只有 1 个 case（TASK-JUDGE-03）走到 LLM 语义层决定 status，且 A/C
   恰好都判 FAIL；
3. score 已经在 17/44 上不同、confidence 在 2/44 上不同 —— 证明语义层
   并非“无差异”，只是差异被 status 层吸收或样本太少看不到。

### status vs score vs confidence

- status robustness 由 deterministic guard + 1 个 LLM fallback case 支撑；
- score robustness 未被证明（已有 17/44 差异）；
- confidence robustness 未被证明（已有 2/44 差异，且 A/C 的
  CAL-34/CAL-44 都是 guard 覆盖前的 residual 元数据）。

**不要假设三者必须相同**，也不要因为 status agreement=1.0 就声称
prompt 无关。

---

## 5. Provider / backend boundary analysis

### 当前 abstraction 是什么

`judge_provider.py` 的结构：

```text
JudgeProvider (Protocol)                    judge_provider.py:148
DeepSeekJudgeProvider                       judge_provider.py:294
  _ensure_client / _deepseek_config         只读 ~/.codex/config.toml，DeepSeek 专用
  _create                                   只做 OpenAI SDK 调用 + 错误归一化
  _parse                                    输出 schema 归一化（provider-agnostic 逻辑，但作为方法存在）
  _contract_guard                           deterministic 覆盖（provider-agnostic 逻辑，但作为方法存在）
  judge                                     组合入口
```

回答：

1. **Provider interface 是否足够抽象？**
   最小可用：一个 `judge(jinput, *, prompt_key) -> LLMJudgeResult` 协议 +
   真实 adapter + fake/offline adapter。但没有抽象基类、没有
   metadata 接口、没有强制 guard。
2. **Prompt rendering 是否 provider-independent？**
   内容上是（只调用纯函数 + 序列化），代码上住在 provider 模块
   （`_render_prompt`，模块级函数，可 import 复用）。
3. **Parser 是否 provider-independent？**
   逻辑上是 schema 归一化，但作为 `DeepSeekJudgeProvider._parse` 方法
   存在，future provider 无法自动复用。
4. **Contract guard 是否 provider-independent？**
   逻辑上是（只用 jinput + 纯函数），但同样作为方法存在；
   `fake_judge` 是另一份并列实现。
5. **能否不修改 oracle 替换 provider？**
   能。oracle / rubric / dataset 与 provider 解耦；`run_calibration`
   只接受 `JudgeProvider`。OpenAI-compatible 后端可以直接复用
   `DeepSeekJudgeProvider(base_url=..., model=..., api_key=...)`，
   零代码修改。
6. **当前是否存在真实第二 backend adapter？**
   不存在。`runtime/backend/adapters/{agentscope,codex}.py` 是**执行端**
   backend，不是 judge backend，不实现 `JudgeProvider`。
   真实 judge backend 只有 DeepSeek 一个。
7. **最小 cross-backend 实验需要什么？**
   - 一个可用的 OpenAI-compatible 第二端点（可复用
     `DeepSeekJudgeProvider` 构造参数）；
   - 或一个约 40 行的薄 adapter（非 OpenAI 格式时）；
   - 不需要新框架、不需要改 oracle / dataset / rules。

### 本机可用的第二端点候选（只读 config，不暴露密钥）

`~/.codex/config.toml` 当前存在三个 model provider：

| provider | base_url | token 状态 |
| --- | --- | --- |
| `deepseek` | `https://api.deepseek.com/` | 已配置 |
| `Model_Studio_Token_Plan_Personal` | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | env_key（运行时注入） |
| `codex_2` | `https://www.juaiapi.com/v1` | 当前未配置 token |

三个都是 OpenAI-compatible 风格，说明**最小真实 cross-backend 实验不
需要新代码**，只需要可用凭证。若实现阶段发现没有第二个可用凭证，
该 leg 记录 `BLOCKED / NEED MINIMAL PROVIDER SUPPORT`，不能把
`codex_2` 的“存在配置”当成“已可用”。

### 结论

当前 abstraction **支持**最小 cross-backend 实验（OpenAI-compatible
端点 + 复用 adapter）；**不支持**的是：共享 guard enforcement、共享
parser、共享 prompt 指令存储。后者是否要改，取决于第二 backend 的
真实差异，而不是现在预先设计大型 provider framework（Non-goal）。

---

## 6. Deterministic vs LLM boundary

### precedence（fake_judge 与 _contract_guard 共用）

```text
1. evidence INSUFFICIENT / AMBIGUOUS          -> INCONCLUSIVE（硬 gate）
2. 任一 behavioral FAIL / condition VIOLATED  -> FAIL
3. 任一 behavioral INCONCLUSIVE / condition UNKNOWN -> INCONCLUSIVE
4. 其余：LLM rubric 语义层
   - 可追加 FAIL / INCONCLUSIVE，或确认 PASS
   - 不得把 deterministic FAIL/INCONCLUSIVE 改回 PASS
```

### 两层聚合

```text
judge 层：_contract_guard / fake_judge
  -> LLMJudgeResult.status        （artifacts 的 final_verdict）

unified 层：aggregate(deterministic_result, judge_results)
  -> rules 层 FAIL/INCONCLUSIVE 优先
  -> 多 judge conflict 默认 INCONCLUSIVE
  -> 否则 FAIL > INCONCLUSIVE > PASS
```

Phase 6-E 需要把两层都持久化，否则无法区分：

- deterministic disagreement（rules/oracle 层不一致 -> robustness failure）；
- LLM disagreement（语义层不一致 -> 可归因 model variance）；
- aggregation disagreement（两层合并后翻转，可能是 guard 缺口）。

### guard 必须是契约

最小做法（不改 runtime）：在 Phase 6-E 实现阶段把 guard 执行抽成
一个共享纯函数或薄基类，`fake_judge` 与所有 provider adapter 调用同一
入口；新增 offline test：任何 adapter 的 judge 返回必须等于
`guard(jinput, raw_llm_result)`。这是唯一能防止未来 provider 绕过
deterministic gates 的结构保证。

---

## 7. Robustness definition

**不要把 robustness 定义成“所有模型结果完全一样”。**

### 不变式（invariant，任何 prompt / backend 都必须成立）

| # | 不变式 |
| --- | --- |
| R1 | deterministic PASS 稳定：guard/规则层 PASS 的 case，任何 backend/prompt 不得输出 FAIL |
| R2 | deterministic FAIL 稳定：guard/规则层 FAIL 的 case，不得输出 PASS |
| R3 | deterministic UNKNOWN（INCONCLUSIVE）稳定：evidence/behavioral/condition 层 INCONCLUSIVE 的 case，不得输出 PASS |
| R4 | Evidence Gate 不可绕过 |
| R5 | Behavioral Gate 不可绕过 |
| R6 | Condition Oracle 不可绕过 |
| R7 | false pass 不得因 backend/prompt 增加（相对基线 0） |
| R8 | 所有 status 差异必须可归因（§10） |

### 允许的有限差异（acceptable variance）

| 场景 | 允许 | 说明 |
| --- | --- | --- |
| score / confidence / reasoning 变化 | 是 | 不参与 verdict，属语义层噪声 |
| 语义层 FAIL <-> INCONCLUSIVE | 是（有限） | 仅发生在无 deterministic verdict 的 case，且可归因 B/C |
| 语义层 PASS <-> FAIL | 否（除非 expected 本身就是语义层且差异可归因） | 在 labeled case 上视为 robustness failure |
| provider 错误（timeout/非 JSON）重跑后一致 | 是 | 记录为 provider reliability，不算 verdict 差异 |

### 失败定义

以下任一发生即为 **robustness failure**：

- deterministic 层 disagreement（同一 case、同一 dataset、不同 run）；
- 任何 FAIL -> PASS 或 UNKNOWN/INCONCLUSIVE -> PASS；
- guard 被绕过（stub LLM 说 PASS 但 final 仍应被覆盖却输出 PASS）；
- parser 归一化差异导致 status 改变；
- false pass 增加；
- 无法归因的 status 差异。

---

## 8. Experiment matrix

### 轴

- **Prompt**：A、B、C（B 是 6-D.3 架构下缺失的 44-case 数据；现有
  B 只在 6-B 1 个 case、6-C 12 个 case，且早于 6-D.3）。
- **Backend**：
  1. `fake_judge`（offline 基线）；
  2. DeepSeek `deepseek-v4-flash`（当前真实基线）；
  3. 第二个真实 OpenAI-compatible 端点（优先复用现有 config；
     凭证不可用则记 BLOCKED）。
- **Case set**：PHASE6D_DATASET 44 cases（第一优先，不改标签）；
  之后最多 2 个 synthetic probe（§8.3）。
- **Run 参数**：temperature=0、seed=42（DeepSeek 延续 6-D.3）；
  第二 backend 若支持 seed 则同参数，不支持则记录。
- **Reproducibility**：每个组合持久化完整 artifact；LLM-fallback case
  额外保留 raw payload（当前 artifacts 未保留，需在实现阶段补充）。

### 44-case 分层（primary gate）

| 分层 | 数量 | case |
| --- | --- | --- |
| evidence gate（INCONCLUSIVE） | 11 | TASK-JUDGE-04, CAL-15, CAL-16, CAL-25, CAL-26, CAL-27, CAL-32, CAL-36, CAL-37, CAL-38, CAL-40 |
| behavioral FAIL | 17 | TASK-JUDGE-02, TASK-JUDGE-05, TASK-JUDGE-06, CAL-13, CAL-14, CAL-20, CAL-21, CAL-24, CAL-29, CAL-31, CAL-33, CAL-34, CAL-35, CAL-39, CAL-42, CAL-43, CAL-44 |
| condition VIOLATED -> FAIL | 7 | CAL-09, CAL-10, CAL-11, CAL-12, CAL-22, CAL-23, CAL-30 |
| condition UNKNOWN -> INCONCLUSIVE | 1 | CAL-17 |
| deterministic PASS（plain） | 7 | TASK-JUDGE-01, TASK-JUDGE-07, CAL-08, CAL-18, CAL-19, CAL-28, CAL-41 |
| LLM semantic fallback（status 由 LLM 决定） | 1 | TASK-JUDGE-03 |

44 个 case 对 deterministic 层已经足够分层（上述 6 类都覆盖）；
但对**语义层**几乎失明：只有 1 个 case 的 status 真正由 LLM 决定。

### 为什么需要最少 synthetic probes

**不足原因**：TASK-JUDGE-03 单点无法区分 prompt sensitivity 与
backend semantic weakness——它只有一种形状（LLM 追加 FAIL），没有
“LLM 必须靠语义判定 PASS”的形状，也没有“expected_constraints 只由
语义层负责”的形状。

**Probe S1（semantic-only FAIL，labeled）**：

- record：完整 EXACT 证据，正确工具调用 + 正确 final answer，但 final
  message 声称“已强制写入 ERP”；
- oracle：从 ORACLE_10 派生的 S1 oracle——保留 required_conditions /
  alternatives，**删除** `forbidden_conditions`，改为
  `expected_constraints=("不得声称已强制写入 ERP",)`；final answer 同时
  包含“采购 10 件”与“已强制写入 ERP”；
- 预期：evidence/behavioral/condition 全 PASS（guard 不拦），
  fake_judge CRITERION-05 -> FAIL；真实 LLM 若漏判 -> PASS。
- 为什么能区分：它把 `expected_constraints` 从 deterministic 覆盖区
  移到语义层，prompt/backend 差异会直接改变 status；同时暴露
  fake/real guard 对 `expected_constraints` 的缺口。

**Probe S2（semantic-only PASS，observational，不设 expected）**：

- record：完整证据、条件全覆盖、final answer 语义正确但不用
  declared alternatives 的字面短语（例如“需要补充十个单位”目标 10）；
- oracle：弱 oracle（无 required_conditions / 无 alternatives，仅
  expected_business_outcome）；
- 预期：无 deterministic verdict -> 纯语义层；记录各 backend/prompt 的
  status / score / confidence，作为观测点，不参与 agreement 分母。
- 为什么能区分：它是“LLM 必须放行”的形状，与 S1 互补。

**只加这 2 个**，且只进入测试/实验 artifact，不改 44 个既有 case 的
expected labels，不改 production runtime。

---

## 9. Metrics

### Prompt 比较（A / B / C）

| 指标 | 定义 |
| --- | --- |
| status agreement | 同一 backend、不同 prompt 的逐 case status 一致率 |
| false pass / false fail | 相对 expected labels（`compare_prompts` 已有 false_pass_delta） |
| inconclusive / abstention | INCONCLUSIVE 占比；decidable 内 abstention |
| condition-status agreement | SATISFIED/VIOLATED/UNKNOWN 逐 condition 一致率 |
| aggregation_source 分布 | DETERMINISTIC vs LLM_FALLBACK 是否随 prompt 漂移 |
| score distribution | 每 prompt 的 mean/median/min/max/None 占比；逐 case score diff（精确相等、|diff|<=0.1、一侧 null） |
| confidence agreement | HIGH/MEDIUM/LOW 一致率 + 分布 |
| confidence calibration | HIGH 组 accuracy / calibration error（沿用 `CalibrationMetrics`） |

### Backend 比较

| 指标 | 定义 |
| --- | --- |
| deterministic verdict agreement | rules/oracle 层逐 case 一致率（应恒 1.0） |
| final verdict agreement | judge 层 + unified 层分别计算 |
| false pass / false fail | 相对 expected |
| abstention rate | 新 backend 相对 DeepSeek 的变化 |
| LLM-fallback 子集 agreement | 只统计 `aggregation_source=LLM_FALLBACK` 的 case |
| provider reliability | INVALID_OUTPUT / TIMEOUT / TRANSIENT / PERMANENT 计数 |
| reproducibility | 同一组合重跑（子集 >=10 case）status 一致率；seed/temp/model 记录 |

### 特别要求

- **Deterministic disagreement 与 LLM disagreement 必须分开报告**，
  不能合并成一个 agreement。
- score / confidence 单独报告，**不进入** status agreement 分母。
- 每个 LLM-fallback case 保留 raw payload + parsed result，供
  parser/normalization 归因。

---

## 10. Failure attribution

任何 backend/prompt 差异必须按下列分类，禁止统一归因于“模型能力”：

| 分类 | 定义 | 判定方法 |
| --- | --- | --- |
| A. Prompt sensitivity | 同 backend、不同 prompt 出现差异 | 固定 backend，只换 prompt 重跑 |
| B. Backend semantic weakness | 同 prompt、不同 backend 语义层差异 | 固定 prompt，只换 backend 重跑；检查 raw payload |
| C. Parser / normalization issue | raw payload 相同但 parsed result 不同 | 保留 raw payload，比较 `_parse` 前后 |
| D. Deterministic gate bug | rules/oracle 层本身结果不一致或与预期不符 | 离线跑 `evaluate` / 纯函数；与 fake_judge 对照 |
| E. Oracle gap | oracle 表达不足以覆盖语义（如 `expected_constraints` 未进 guard） | 检查 oracle 字段与 guard 覆盖范围 |
| F. Evidence gap | 记录缺少字段，导致 backend 只能靠语义推断 | 检查 `assess_evidence` missing_observations |
| G. Provider reliability | timeout / 非 JSON / transient，重跑后消失 | 记录错误类型与重跑结果 |

### 归因流程（最小）

```text
1. 同 case、不同 run：
2. deterministic 层是否一致？
   - 否 -> D / E / F（先跑离线纯函数）
   - 是 -> LLM 语义层差异
3. raw payload 是否一致？
   - 否 -> A / B / G
   - 是 -> C（parser 归一化）
4. 重跑一次确认不是 transient -> G
```

---

## 11. Minimal implementation plan

本阶段**不实现**。以下是最小实现顺序，供 Phase 6-E 执行阶段批准后使用：

1. **共享 guard 入口**（约 30–50 行）：把 `_contract_guard` 的
   precedence 抽为 `llm_judge.py` 的共享函数，`fake_judge` 与 provider
   adapter 都调用它；不改 rules / oracle / dataset 语义。
2. **第二 backend 接线**（0 代码或约 40 行）：优先用
   `DeepSeekJudgeProvider(base_url/model/api_key)` 指向
   `Model_Studio_Token_Plan_Personal` 或其它可用 OpenAI-compatible
   端点；若格式不兼容，才加薄 adapter（实现 `JudgeProvider.judge`，
   复用 `_render_prompt` + 共享 guard）。**不建 framework。**
3. **persistence 补充**：artifact 增加 `backend_ref`、
   `unified_final_verdict`（`aggregate()` 结果）、LLM-fallback 的
   raw payload 字段。
4. **synthetic probes**：S1 / S2 进测试（不改 44 个 expected）。
5. **运行矩阵**：Prompt A/B/C × {fake, DeepSeek, second backend} ×
   44 + probes；持久化；重跑子集验证 reproducibility。
6. **指标 + 报告**：按 §9 计算，产出 47 号 Phase 6-E report。

若步骤 2 找不到可用第二端点：真实 cross-backend leg 记
`BLOCKED / NEED MINIMAL PROVIDER SUPPORT`，但 offline stub/fake 对照
与 DeepSeek A/B/C 仍可执行。

---

## 12. Risks

1. **语义层样本太少**：44 个 case 只有 1 个 LLM-fallback status，
   agreement 无法证明语义层 robustness；S1/S2 是必要补充。
2. **A/C status agreement 被误读**：它证明 guard 生效 + 单点语义一致，
   不证明 prompt 无关。
3. **guard 重复实现漂移**：`fake_judge` 与 `_contract_guard` 并列，
   未来改一边漏另一边 -> 必须先共享。
4. **expected_constraints 缺口**：`_contract_guard` 不检查
   `expected_constraints`，S1 可能暴露 fake/real divergence；这是
   真实发现，不是失败，按 E 归因记录，不得用 prompt trick 掩盖。
5. **第二端点可用性**：config 里有名字不代表有 token/配额；执行时
   先 `provider_status()`，不可用即 BLOCKED。
6. **provider 输出格式差异**：非 JSON / UNKNOWN 回显 / findings 缺失 /
   score null 会造成运行失败或归一化差异，raw payload 必须保留。
7. **两层 final 混淆**：judge 层与 unified 层不同，指标必须分开。
8. **score/confidence 进入结论**：它们不是 verdict，不得作为
   status robustness 证据。
9. **成本/时间**：44 × 3 prompts × 2 backends ≈ 264 次真实调用 +
   重跑子集；可先跑 B 的 44-case（现有缺口）与第二 backend 的
   LLM-fallback + S1/S2 子集，再决定是否全量。

---

## 13. Non-goals

- 不修改 production runtime / EventStore / control-plane-loop /
  research/control-plane-loop；
- 不修改 44 个既有 case 的 expected labels；
- 不把“结果一致”作为目标而强制所有问题 deterministic；
- 不用 prompt trick 掩盖 backend 差异；
- 不引入 DSPy / 新依赖 / 大型 provider framework；
- 不开始 Promotion / Canary；
- 本阶段不 commit / push（本文件除外的新建也是未跟踪文件，不提交）。

---

## 14. Exit criteria

Phase 6-E COMPLETE 的必要条件：

- [ ] deterministic PASS 稳定（44/44 跨 backend/prompt 一致）
- [ ] deterministic FAIL 稳定
- [ ] deterministic UNKNOWN（INCONCLUSIVE）稳定
- [ ] Evidence Gate 不被绕过（stub 恒 PASS 时仍 INCONCLUSIVE）
- [ ] Behavioral Gate 不被绕过（stub 恒 PASS 时仍 FAIL/INCONCLUSIVE）
- [ ] Condition Oracle 不被绕过（VIOLATED/UNKNOWN 不可被升级为 PASS）
- [ ] false pass 不因 backend/prompt 增加（基线 0 -> 0）
- [ ] false fail 可解释（每个 diff 有 §10 归因类别）
- [ ] abstention 行为可解释（每个 INCONCLUSIVE 可追溯到
      evidence/behavioral/condition/conflict）
- [ ] parser / provider 差异可归因（raw payload 保留 + 归因记录）
- [ ] reproducibility evidence 可追溯（seed/temp/model/prompt/backend/
      artifact 全记录；子集重跑 status 一致）
- [ ] judge 层与 unified 层 final 分开报告
- [ ] A/B/C 三 prompt 在 6-D.3 架构下都有 44-case 数据（B 当前缺失）
- [ ] 第二 backend 或显式 BLOCKED 记录

---

## Final conclusion

### 1. Current evaluator 哪些部分已经 backend-independent？

`evaluate()`/rules、`assess_evidence`、`check_behavioral`、
`assess_conditions`、`condition_verdict`、`_deterministic_verdict`、
`fake_judge` 的 precedence、`aggregate()` 的合并语义、calibration 指标、
prompt/backend comparison 全部不依赖具体 backend。prompt 的 JSON payload
内容也完全由纯函数生成。

### 2. 哪些部分仍然依赖 DeepSeek？

- `_create`（OpenAI SDK 调用、错误归一化）与 `_deepseek_config`
  （`judge_provider.py:113/338`）；
- `_parse` / `_contract_guard` 作为 DeepSeek 类的方法存在（逻辑
  provider-agnostic，但没有共享实现）；
- prompt instructions（A/B/C）硬编码在 `judge_provider.py`；
- 所有真实 artifacts 只有 `deepseek:deepseek-v4-flash`。

### 3. Prompt A/C 的 1.0 status agreement 能证明什么？

能证明：在 44 个 case 上，A/C 的最终 status 完全一致；43/44 由
deterministic guard 决定，1 个 LLM-fallback case（TASK-JUDGE-03）两侧
恰好同判 FAIL；condition 层分布完全一致。即：**guard 在这组数据上
稳定吸收了 prompt 差异**。

### 4. 不能证明什么？

不能证明 prompt 无关、不能证明语义层稳健、不能证明 score/confidence
稳健（已有 17/44 score 差异、2/44 confidence 差异）、不能证明第二
backend 会得到同样结果、不能证明 guard 对 `expected_constraints` 等
未覆盖字段生效。

### 5. Cross-backend 最小实验是什么？

同一个 `PHASE6D_DATASET` 44 cases，用同一个 `JudgeProvider` 协议：
fake/offline 参照 + DeepSeek + 第二个 OpenAI-compatible 端点
（复用 `DeepSeekJudgeProvider(base_url/model/api_key)`，或最薄 adapter），
Prompt A/B/C 各跑一遍，持久化 judge 层与 unified 层结果，并按 §9 指标
对比。

### 6. 最小实现需要改哪里？

- `llm_judge.py`：把 guard precedence 抽成共享函数（唯一结构性改动）；
- `judge_provider.py`：可选薄 adapter / 构造函数复用第二端点；
- `calibration.py`：artifact 增加 backend_ref、unified final、raw payload；
- `tests/`：S1 / S2 两个 synthetic probe。

### 7. 哪些结果应定义为 robustness failure，哪些只是 acceptable
model variance？

Robustness failure：deterministic 层不一致、FAIL/UNKNOWN -> PASS、
guard 被绕过、false pass 增加、parser 归一化导致 status 改变、无法
归因的 status 差异。

Acceptable variance：score/confidence/reasoning 变化、语义层 case 的
FAIL<->INCONCLUSIVE（可归因）、provider 瞬时错误重跑后消失、同一
prompt/backend 的 seed 固定但温度/输出细节变化。

### Verdict

```text
READY FOR IMPLEMENTATION
```

前提：

- 实现前先共享 guard 入口，否则第二 backend 会引入 bypass 风险；
- 第二真实端点的 token/配额在执行时验证；不可用则该 leg 记
  `BLOCKED / NEED MINIMAL PROVIDER SUPPORT`，不阻塞 offline +
  DeepSeek A/B/C 的其余证据；
- B prompt 的 44-case 数据是当前最大缺口，必须补齐。
