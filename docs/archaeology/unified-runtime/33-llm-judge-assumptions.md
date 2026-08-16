# 33 — LLM Judge Assumptions（Phase 6-A）

> 阶段：Phase 6-A。冻结 Judge 层的显式假设；每条假设都是 contract 的一部分，
> 后续真实 Judge / provider 集成不得静默改变这些语义。

---

- **A1 judge model nondeterminism**：LLM Judge 输出允许 non-deterministic；
  `judge_id` 是 run identity，同一输入多次运行结果不要求 byte-identical，
  也禁止假设 deterministic。
- **A2 rubric semantics**：Rubric 是 judge 的唯一质量标准，版本化
  （rubric_id + version）；criteria / weight / required /
  pass_threshold / fail_threshold 由调用方提供，不写死在 evaluator。
- **A3 score semantics**：score 是 0.0~1.0 的语义质量分，不是 deterministic
  evaluation score，也不与 pass/fail 自动等价；缺失时允许 None。
- **A4 confidence semantics**：HIGH / MEDIUM / LOW 表示判断确定性；明确不
  确定必须 INCONCLUSIVE；LOW confidence 不得包装成 PASS；INCONCLUSIVE 不得
  标 HIGH。
- **A5 evidence requirement**：每个 finding 必须引用 evaluation-facing
  evidence（execution_id / step_id / tool_call_id / tool_result_id /
  context_provenance_ref / backend_event_ref 中适用项）；required criterion
  无证据时 finding 标 UNSUPPORTED，不得 PASS。
- **A6 lossiness**：LOSSY backend evidence 对 Judge 可见；关键判断依赖
  LOSSY 时必须降低 confidence 或 INCONCLUSIVE；LOSSY 永远不升级为 EXACT。
- **A7 context availability**：Judge 只能使用 model-visible context 或
  context provenance，不能默认拥有完整内部 runtime state；区分
  “Agent saw” 与 “runtime knew”；context 不完整时允许 INCONCLUSIVE。
- **A8 prompt version reference**：Judge 每次运行记录 prompt_ref +
  prompt_version；不实现 Prompt Registry，只做 reference。
- **A9 model version reference**：Judge 每次运行记录 model_ref +
  model_version；provider 无明确版本时记 UNKNOWN，不伪造。
- **A10 multi-judge conflict**：多个 Judge 冲突（PASS 与 FAIL 并存）→
  JUDGE_CONFLICT → 最终 INCONCLUSIVE；除非 policy 显式指定某个 judge_id
  优先。
- **A11 replay vs judge rerun**：ExecutionRecord replay 只重建 record，
  不重新运行 Judge；重新运行 Judge 产生新 judge_id，旧结果不可变、不覆盖。
