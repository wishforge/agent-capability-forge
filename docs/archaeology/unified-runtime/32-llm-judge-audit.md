# 32 — LLM Judge Audit（Phase 6-A）

> 阶段：Phase 6-A。实现前审计：在既有 Deterministic Evaluation（RULE-01..13）
> 之上增加 LLM Judge 的边界与数据需求。
> 输入：04 / 05 / 06 / 13 / 15 / 17 / 22 / 25 / 28 / 31、
> `evaluation/evaluator.py` / `models.py` / `rules.py` /
> `failure_attribution.py` / `improvement_candidate.py` / `regression.py` /
> `promotion.py`、Codex 07-10、DSH 07-11。
> 状态词：AVAILABLE / PARTIAL / MISSING。

---

## 1. Evaluation dimension 覆盖审计

### 1.1 已被 deterministic rules 覆盖（runtime-verifiable facts）

| Dimension | Rule | 状态 |
| --- | --- | --- |
| Turn 是否完成 | RULE-01（turn/end.reason） | AVAILABLE |
| Tool 是否有未解析结果 | RULE-02（tool call ↔ result 配对） | AVAILABLE |
| 是否 unsafe retry | RULE-03（attempt.reason=UNSAFE_RETRY_BLOCKED） | AVAILABLE |
| 必选工具是否调用 | RULE-04（tools[].name） | AVAILABLE |
| 禁止工具是否被调用 | RULE-05（tools[].name） | AVAILABLE |
| 必选工具是否成功 | RULE-06（tool_result.is_error；LOSSY 降级） | AVAILABLE |
| 是否 timeout | RULE-07（error_code / attempt.error） | AVAILABLE |
| 是否存在内部 runtime 失败 | RULE-08（attempt status / turn reason） | AVAILABLE |
| Terminal condition 是否满足 | RULE-09（TaskSpecification.terminal_condition） | AVAILABLE |
| 是否可 replay | RULE-10（replay_ref + record identity） | AVAILABLE |
| Initiator / Owner / Context 证据是否存在 | RULE-11 / 12 / 13 | AVAILABLE |

### 1.2 只能通过 semantic judgment 覆盖（Judge 的职责）

| Dimension | 为什么 deterministic 不够 | 6-A 前状态 |
| --- | --- | --- |
| 最终答案质量（清晰、完整、可执行） | runtime event 不包含“答案好不好” | MISSING |
| 任务完成程度（业务意义，不只是 tool 序列） | 完成事件 ≠ 业务目标达成（05 §2） | MISSING |
| 推理/解释是否合理 | 无结构化 reasoning 证据 | MISSING |
| 输出是否符合业务目标 | 需要 Task / Oracle 层语义 | MISSING |
| 隐藏语义错误（数量错、方向反、看似正确实际错误） | 事件层无法证明语义正确性 | MISSING |
| 答案层面的安全/策略符合性 | RULE-05 只证明 tool 调用，不证明输出合规 | MISSING |

结论：Deterministic 覆盖“执行事实”，Judge 覆盖“语义质量”；二者互不替代。

---

## 2. 十项审计

### 1. 哪些 dimension 已被 deterministic rules 覆盖？

**AVAILABLE**。RULE-01..13 覆盖 turn/tool/attempt/execution 层可验证事实，
全部以 ExecutionRecord（5j.1）为输入；规则未改，LOSSY 降级语义保留。

### 2. 哪些 dimension 只能通过 semantic judgment？

**MISSING（6-A 前）**。最终答案质量、业务完成度、推理合理性、业务目标匹配、
隐藏语义错误、答案级安全/策略。这些没有 runtime event 可以证明，必须由
Judge 承担；第一版只实现 contract + fake judge（PARTIAL）。

### 3. 哪些数据应该提供给 Judge？

**AVAILABLE**。`LLMJudgeInput` 只包含 evaluation-facing 数据：

```text
task_specification
execution_record（不可变投影）
deterministic_evaluation
rubric（版本化）
oracle_reference（optional，Task/Evaluation 层）
evidence_refs
```

不允许：Runtime / EventStore / Capability Manager / ContextVar / ambient
状态。

### 4. 哪些数据禁止提供？

**AVAILABLE（契约 + 模块边界）**。禁止提供 runtime mutable state、EventStore
写路径、Capability registry、ContextVar、backend 内部状态、prompt 模板执行
态。`llm_judge.py` 不 import runtime 任何模块；测试
`test_judge_input_is_runtime_independent` 检查源码 import 面。

### 5. 哪些 metadata 需要暴露？

**AVAILABLE**。Judge 每次运行必须携带：

```text
judge_id（run identity）
status / score / confidence
model_ref / model_version（无版本 = UNKNOWN）
prompt_ref / prompt_version
rubric_ref（rubric_id + version）
evidence_refs（execution / step / tool / context / backend refs）
```

### 6. Lossiness 如何影响 Judge？

**PARTIAL（记录层 AVAILABLE，真实 Judge 验证 PARTIAL）**。ExecutionRecord 的
`lossiness[]` / `mapping_quality` 可读；fake judge 对任何 LOSSY 证据返回
INCONCLUSIVE + LOW confidence，禁止 LOSSY → EXACT。真实 LLM Judge 需要在
prompt 中显式传递 lossiness 语义，本轮未验证。

### 7. Context provenance 是否足够？

**PARTIAL**。record 携带 `context_provenance`（quality=PARTIAL，完整
request-time 快照未持久化，04 §7 / 06 §2）。Judge 只能使用 model-visible
context 或 provenance；上下文缺失时允许 INCONCLUSIVE（fake judge 强制）。

### 8. 是否需要 oracle / rubric？

**AVAILABLE**。Rubric 必填且版本化（rubric_id + version + criteria +
thresholds），不写死在 evaluator 中；Oracle 可选，来自 Task / Evaluation
层，不属于 Runtime。

### 9. 如何定义 Judge uncertainty？

**AVAILABLE**。confidence ∈ {HIGH, MEDIUM, LOW}；明确不确定 → INCONCLUSIVE；
LOW + PASS 被禁止（构造时 ValueError）；无证据的 required criterion →
UNSUPPORTED → INCONCLUSIVE。

### 10. 如何保证 Judge 不直接修改 runtime？

**AVAILABLE**。Judge 只产生 immutable `LLMJudgeResult`；无写回路径、不 import
runtime、不调用 improvement / regression / promotion。Failure Attribution /
Improvement / Regression / Promotion 保持独立，不消费 Judge 的副作用（因为
不存在副作用）。

---

## 3. 审计结论

```text
Deterministic facts   -> AVAILABLE（RULE-01..13，0 修改）
Semantic dimensions   -> MISSING -> 6-A 增加 Judge contract + fake judge
Judge input boundary  -> AVAILABLE（evaluation-facing only）
Lossiness 可见性       -> AVAILABLE（记录层）；真实 Judge 消费 PARTIAL
Context provenance    -> PARTIAL（允许 INCONCLUSIVE 兜底）
Oracle / Rubric       -> AVAILABLE（contract 层）
Uncertainty 语义      -> AVAILABLE（confidence + INCONCLUSIVE + UNSUPPORTED）
Runtime 零修改         -> AVAILABLE（模块边界 + 测试）
```
