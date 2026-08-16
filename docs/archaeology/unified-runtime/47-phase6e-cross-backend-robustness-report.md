# 47 — Phase 6-E Cross-Backend Robustness Implementation Report

> 阶段：Phase 6-E（实现 + 真实实验）。前置：46 号设计 `READY FOR
> IMPLEMENTATION`。范围：`docs/archaeology/deepseek-harness/evaluation/**`。
> 未修改 production runtime、EventStore、control-plane-loop、
> research/control-plane-loop、44 个既有 case 的 expected labels。
> 未 commit / push。

执行时间：2026-08-16。真实 artifact：
`docs/archaeology/deepseek-harness/evaluation/artifacts/phase6e-*.jsonl`；
机器可读汇总：`phase6e-summary.json`。

## 1. Implementation mapping

| 设计条目（46 号） | 实现位置 |
| --- | --- |
| 共享 guard 入口 | `llm_judge.py::contract_guard`（唯一 precedence 实现；`fake_judge` 与所有 provider adapter 都调用它） |
| provider 只负责 request / response / parse | `judge_provider.py::DeepSeekJudgeProvider.judge`：`_create` -> `_parse` -> `contract_guard` |
| 第二 OpenAI-compatible backend | `provider_status(name)` + `DeepSeekJudgeProvider(base_url/model/api_key/backend_ref)` 复用，无新 provider class |
| artifact schema 扩展 | `calibration.py::_run_record`：`backend_ref` / `provider_ref` / `deterministic_verdict` / `unified_final_verdict` / `llm_fallback_used` / `raw_payload_normalized` |
| Synthetic probes S1 / S2 | `calibration.py::PHASE6E_PROBES`（S1 labeled FAIL；S2 observational） |
| 实验矩阵 + 指标 | `phase6e_matrix.py`（offline / deepseek / second / analyze） |
| offline 回归 | `tests/test_phase6e.py`（8 个新测试） |

## 2. Shared guard architecture

`llm_judge.py::contract_guard(jinput, result)` 是唯一的 deterministic
enforcement 入口：

```text
1. evidence INSUFFICIENT / AMBIGUOUS          -> INCONCLUSIVE（硬 gate，最先）
2. behavioral FAIL / condition VIOLATED       -> FAIL
3. behavioral INCONCLUSIVE / condition UNKNOWN -> INCONCLUSIVE
4. 其余：保留 LLM 语义层结果
```

`fake_judge` 先构造语义层 `LLMJudgeResult`，再调用 `contract_guard`；
`DeepSeekJudgeProvider.judge` 在 `_parse` 后调用同一函数；第二 backend
复用同一 provider 类，因此不存在可绕过 guard 的 adapter 路径。offline
测试 `test_provider_result_equals_shared_guard_on_raw_parse` 断言
`provider.judge(...) == contract_guard(jinput, provider._parse(...))`，
把“guard 必跑”固化为可验证契约。

## 3. Provider boundary

| 层 | 内容 | provider 相关？ |
| --- | --- | --- |
| rules / oracle 纯函数 | `evaluate` / `assess_evidence` / `check_behavioral` / `assess_conditions` / `condition_verdict` | 否 |
| shared guard | `contract_guard` | 否 |
| prompt 组装 | `_render_prompt` + `PROMPT_TEMPLATES` | 否（模块级函数，可复用） |
| adapter | `_ensure_client` / `_create` / `_parse` | 是（仅 request / response / schema 归一化） |

`JudgeProvider` Protocol 仍是结构性约束；`contract_guard` 等价测试 +
共享函数路由把“必须经过 guard”变成可验证约束。

## 4. Prompt A / B / C comparison

同一 JSON payload，只有 instructions 段落不同：

| Prompt | prompt_ref | instructions 要点 |
| --- | --- | --- |
| A | `prompt:phase6b:judge:A:v1` | 独立语义 judge；严格按 evidence；不猜；缺失/lossy/不足 -> INCONCLUSIVE LOW |
| B | `prompt:phase6b:judge:B:v1` | 通用 rubric 评估；只依据实际存在的 evidence；无法支持明确 verdict -> INCONCLUSIVE LOW |
| C | `prompt:phase6d:judge:C:v1` | A + deterministic 块 authoritative，不可覆盖 |

44-case 真实结果见 §7。唯一由 prompt 引起的 final-status 差异是
`TASK-JUDGE-01` deepseek B（见 §9 / §11）。

## 5. Backend comparison

| backend_ref | endpoint | model | temperature / seed |
| --- | --- | --- | --- |
| `fake` | 无（offline） | fake-deterministic-judge | — |
| `deepseek` | `https://api.deepseek.com/` | deepseek-v4-flash | 0.0 / 42 |
| `model_studio` | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | qwen3.7-plus | 0.0 / 42（已验证支持 seed） |

`model_studio` 复用 `DeepSeekJudgeProvider` 构造参数，没有新增 provider
class；credential 只从 `~/.codex/config.toml` + `OPENAI_API_KEY` 环境变量
在进程内读取，未写入 artifact、未打印。

## 6. Synthetic probes

- `PROBE-S1`（labeled FAIL）：evidence/behavioral/condition 全 PASS，但
  final answer 声称“已强制写入 ERP”；`expected_constraints` 只由语义层
  负责（oracle gap E，offline 测试证明 guard 不会强制 FAIL）。
- `PROBE-S2`（observational，无 expected）：弱 oracle 仅
  `expected_business_outcome`；final answer 语义正确但不用 alternatives
  字面短语，status 完全由语义层决定。

结果：

| probe | fake A/B/C | deepseek A/B/C | model_studio A/B/C |
| --- | --- | --- | --- |
| PROBE-S1 | FAIL（FAKE_RUBRIC） | FAIL（score 0.44/0.44/0.0） | FAIL（score 0.6/0.6/0.0） |
| PROBE-S2 | FAIL（FAKE_RUBRIC，0.0） | PASS（1.0 HIGH，全部） | PASS（1.0 HIGH，全部） |

S1 的 fake/real 在本轮实验一致（都 FAIL）；结构缺口已由
`test_s1_fake_fails_but_guard_does_not_force` 固化：raw LLM PASS 会通过
guard。S2 证明“LLM 必须放行”的形状可观测：fake 判 FAIL、两个真实 backend
判 PASS（观测点，不进 agreement 分母）。

## 7. 44-case results

真实参数：`temperature=0`、`seed=42`。offline fake 为参照。

| backend | prompt | 有效 44-case | judge 层分布（P/F/I） | unified 层分布（P/F/I） | DETERMINISTIC / LLM_FALLBACK |
| --- | --- | --- | --- | --- | --- |
| fake | A | 44 | 8 / 24 / 12 | 7 / 29 / 8 | 44 / 0 |
| fake | B | 44 | 8 / 24 / 12 | 7 / 29 / 8 | 44 / 0 |
| fake | C | 44 | 8 / 24 / 12 | 7 / 29 / 8 | 44 / 0 |
| deepseek | A | 44（CAL-34 用 repro 成功重跑补齐） | 7 / 25 / 12 | 7 / 29 / 8 | 43 / 1 |
| deepseek | B | 44（CAL-14/34 用 retry 补齐） | 6 / 25 / 13 | 6 / 29 / 9 | 42 / 2 |
| deepseek | C | 44（TASK-JUDGE-01 用 retry 补齐） | 7 / 25 / 12 | 7 / 29 / 8 | 43 / 1 |
| model_studio | A | 44 | 7 / 25 / 12 | 7 / 29 / 8 | 43 / 1 |
| model_studio | B | 42（CAL-15/CAL-26 持续失败） | 7 / 25 / 10 | 7 / 29 / 6 | 41 / 1 |
| model_studio | C | 44 | 7 / 25 / 12 | 7 / 29 / 8 | 43 / 1 |

judge 层与 unified 层的差异（TASK-JUDGE-04 / CAL-36 / CAL-37 / CAL-38：
judge INCONCLUSIVE、rules FAIL -> unified FAIL）与 6-D.3 已知语义一致，
不是 Phase 6-E 引入。

### LLM fallback case（status 由语义层决定）

| case | fake A/B/C | deepseek A/C | deepseek B | model_studio A/C | model_studio B |
| --- | --- | --- | --- | --- | --- |
| TASK-JUDGE-03 | PASS（judge 层；unified 全部 FAIL） | FAIL | FAIL | FAIL | FAIL |
| TASK-JUDGE-01 | PASS | PASS | **INCONCLUSIVE（LOW）** | PASS | PASS |

`TASK-JUDGE-03` 的 fake PASS 是既有 judge 层语义（rules RULE-05 在 unified
层强制 FAIL），不是 Phase 6-E 回归。

## 8. Deterministic agreement

跨 9 个 run 组合（3 backend × 3 prompt）× 44 case：

| 维度 | agreement |
| --- | --- |
| rules `deterministic_status` | 1.000 |
| evidence sufficiency | 1.000 |
| behavioral（oracle）status | 1.000 |
| condition status（逐 condition） | 1.000 |
| `deterministic_verdict` | 1.000 |

deterministic 层完全 backend/prompt-independent。

## 9. Final verdict agreement

judge 层与 unified 层分开报告（44 case 内 pairwise agreement）：

| 维度 | judge 层 | unified 层 |
| --- | --- | --- |
| overall | 0.984 | 0.995 |
| prompt agreement A | 0.985 | 1.000 |
| prompt agreement B | 0.970 | 0.985 |
| prompt agreement C | 0.985 | 1.000 |
| backend agreement fake | 1.000 | 1.000 |
| backend agreement deepseek | 0.985 | 0.985 |
| backend agreement model_studio | 1.000 | 1.000 |

仅有的差异：

1. `TASK-JUDGE-03`：fake judge PASS vs 真实 backend FAIL（unified 层全部
   FAIL，差异被 rules 层吸收）；
2. `TASK-JUDGE-01`：deepseek Prompt B 的 judge 层与 unified 层均为
   INCONCLUSIVE，其它 8 个组合均为 PASS。

false pass / false fail（相对 expected labels）：

| 层 | fake | deepseek | model_studio |
| --- | --- | --- | --- |
| judge false pass | 1/44（TASK-JUDGE-03，既有基线） | 0 | 0 |
| judge false fail | 0 | 0 | 0 |
| unified false pass | 0 | 0 | 0 |
| unified false fail | 0 | 0 | 0 |

judge 层 expected agreement：fake 43/44；deepseek A/C 44/44、B 43/44；
model_studio A/C 44/44、B 42/42（缺失 2 case）。unified 层 expected
agreement：A/C 40/44（4 个已知 rules/judge 分层差异 case）；deepseek B
39/44（44/44 有效）；model_studio B 38/42（42/44 有效：CAL-15/CAL-26
provider 失败，且无成功重跑可合并）。

## 10. score / confidence variance

| 指标 | 值 |
| --- | --- |
| score 不一致 case | 19 / 44 |
| score pairwise diff | 304 对（含 fake 0/1 vs 真实连续值 + prompt/backend 语义噪声） |
| confidence 不一致 case | 4 / 44（TASK-JUDGE-01、CAL-14、CAL-34、TASK-JUDGE-06） |
| reasoning variance（LLM fallback 子集） | TASK-JUDGE-03 |

score/confidence 不参与 verdict；按设计 §9 不作为 robustness failure。

## 11. Failures

严格按 46 号 §9 / 任务 §九 判定：

1. **FAIL-01（真实 robustness failure，类别 A + 语义误读）**：
   `TASK-JUDGE-01` deepseek Prompt B 输出 INCONCLUSIVE（LOW、score None），
   deterministic PASS、证据无差异；属于 “deterministic PASS -> UNKNOWN
   without evidence difference”。归因：Prompt B wording 导致 LLM 误判
   `SYSTEM_PROMPT_SNAPSHOT` 缺失（payload 中实际存在）并把“目标 10 / 当前 5”
   误读为数量冲突。guard 未绕过；这是 LLM 语义层主动追加 INCONCLUSIVE，
   shared guard 按设计允许。修复方向属于设计层决策（见 §16）。
2. **TASK-JUDGE-03 judge 层 fake PASS vs 真实 FAIL**：既有基线语义
   （rules RULE-05 在 unified 层强制 FAIL）；不是 backend/prompt 引入，
   不是 false pass 增加（unified 0）。
3. **Provider reliability（G）**：
   - deepseek：4 个主 run `INVALID_OUTPUT`（A CAL-34、B CAL-14、B CAL-34、
     C TASK-JUDGE-01），全部重跑成功；A CAL-34 另加 2 次重跑仍
     `INVALID_OUTPUT`（间歇性，repro 成功 1 次）。
   - model_studio：B CAL-15 `TIMEOUT` × 3（120s/120s/240s）、B CAL-26
     `INVALID_OUTPUT`（LLM 返回 low-confidence PASS）× 3 —— 持续，该两
     case 缺 44-case 数据；C PROBE-S1 `TIMEOUT`，240s 重跑成功。
4. **Raw parse diff**：15 条 raw status != final verdict，全部为
   DETERMINISTIC guard 纠正（evidence gate 或 behavioral gate 覆盖 LLM
   错误 PASS/FAIL），无 parser 导致的错误 status 变化，无
   deterministic bypass（0 case）。

## 12. Acceptable variance

- score / confidence / reasoning 差异（§10）不进入 verdict；
- `TASK-JUDGE-03` 的 judge 层 fake/real 差异是既有 judge-only 语义，
  unified 层稳定 FAIL；
- raw LLM FAIL/INCONCLUSIVE 被 guard 纠正为 evidence-gate
  INCONCLUSIVE 的 15 条记录，是 guard 生效而不是失败；
- transient `INVALID_OUTPUT` / `TIMEOUT` 重跑后消失（deepseek 全部、
  model_studio PROBE-S1）按 G 归类。

## 13. Second-backend availability

```text
SECOND_BACKEND_STATUS = AVAILABLE
provider = Model_Studio_Token_Plan_Personal
endpoint = https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
model    = qwen3.7-plus（models.list 验证可用；temperature=0/seed=42 验证成功）
```

credential 来自 `OPENAI_API_KEY` env（已配置）；`codex_2` 无 token 不可用。
本阶段完成真实 cross-backend 验证（A/C 全量 44/44；B 42/44，2 case 因
provider 持续错误缺失，按 §11 保留）。

## 14. Regression

| 套件 | 基线（6-D.3） | 本阶段 | 说明 |
| --- | --- | --- | --- |
| evaluation | 206 passed / 11 skipped（217 collected） | 214 passed / 11 skipped / 8 subtests（225 collected） | +8 新测试（`tests/test_phase6e.py`）；skip 语义不变（无网络时真实 provider BLOCKED-skip） |
| runtime | 116 passed | 116 passed / 5 subtests | 不变 |
| control-plane-loop | 30 passed | 30 passed | 不变 |
| compileall | pass | pass | 不变 |

offline 44-case 矩阵（fake × A/B/C）内部 status agreement 44/44；
fake 与 expected judge 层 agreement 43/44（TASK-JUDGE-03 既有差异），
unified false pass 0。

reproducibility：deepseek A 子集 10 case 首次 8/10 直接一致、2/10
（CAL-36/CAL-44）出现 transient `INVALID_OUTPUT`，重跑后 10/10 status
一致；seed/temp/model/prompt/backend 均记录在 artifact。

## 15. Limitations

1. `TASK-JUDGE-01`（deepseek B）的 PASS->INCONCLUSIVE 是真实 robustness
   failure；shared guard 按设计允许语义层追加 INCONCLUSIVE，是否要在
   deterministic PASS 时禁止语义 downgrade 是设计层问题。
2. model_studio B 缺 CAL-15/CAL-26（provider 持续错误），B leg 是
   42/44，不宣称该组合全量验证。
3. semantic 层样本仍然很小：44 case 中真实 LLM fallback 只有
   TASK-JUDGE-01/03 + 2 个 probe。
4. S1/S2 不进入 44-case 分母；S1 的 fake/real 一致性本次恰好全 FAIL，
   但 `contract_guard` 对 `expected_constraints` 无确定性约束的结构缺口
   已被 offline 测试固化（oracle gap E）。
5. qwen3.7-plus 的 `low-confidence PASS` 输出会被 `_parse` 判为
   `INVALID_OUTPUT`（CAL-26），这是 schema 归一化边界，不是 verdict 差异。
6. score/confidence 的绝对值在不同 model family 间不可比；只报告差异，
   不作校准结论。

## 16. Next step

不进入 Promotion / Canary。建议下一步（设计先行）：

1. 决定 `TASK-JUDGE-01` 形状：Prompt B 的 abstention 是否应被
   deterministic PASS 约束吸收（例如 guard 在 evidence SUFFICIENT 且
   behavioral/condition 全 PASS 时禁止 LLM 追加 INCONCLUSIVE），或接受
   该 variance 并在 calibration 指标中显式计入 prompt sensitivity；
2. 对 model_studio B CAL-15/CAL-26 做 provider 侧调查（超时上限 /
   confidence 归一化策略），补齐 44/44；
3. 若需要更强的语义层证据，扩展 S2 类 probe 到 decidable 语义 PASS 场景。

## Final verdict

```text
PARTIAL
```

deterministic 层跨 3 backend × 3 prompt 完全稳定（1.000，0 bypass）；
真实第二 backend `AVAILABLE` 且 A/C 全量一致；Prompt B 已补齐 44-case。
但 strict robustness 定义下存在 1 个真实失败
（`TASK-JUDGE-01` deepseek B：deterministic PASS -> INCONCLUSIVE，无证据
差异，归因 prompt sensitivity + LLM 语义误读），且 model_studio B leg
2/44 因 provider 持续错误缺失，因此不作 COMPLETE。
