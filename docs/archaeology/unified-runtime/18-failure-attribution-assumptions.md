# 18 — Failure Attribution Assumptions（Phase 5-K）

> 依据：`16-failure-attribution-audit.md`（实现前审计）+ Phase 5-G/5-H/5-I/5-J
> 契约（04/05/06/07/08/09/13/14/15）+ `17-failure-attribution-contract.md`
> + 本次实现的 `evaluation/failure_attribution.py` 与
> `evaluation/tests/test_failure_attribution.py`。
> 状态词：VERIFIED（有实现/测试证据）/ PARTIAL（source fact 不足）/
> DESIGN PROPOSAL。

| # | Assumption | 状态 | 证据 / 说明 |
| --- | --- | --- | --- |
| A1 | deterministic mapping：同一 ExecutionRecord + 同一 EvaluationResult ⇒ 同一 FailureAttribution；映射只读 finding.rule_id + record 字段，无模型/随机/ContextVar | VERIFIED | `attribute()` 纯函数；`test_replay_stable_attribution` 断言 replay 前后完整 attribution 语义相等 |
| A2 | rule → kind 映射冻结：RULE-01（max-tokens→COMPLETION_FAILURE，其余非 completed→TURN_FAILURE）、RULE-02→UNRESOLVED_TOOL、RULE-03→UNSAFE_RETRY、RULE-04/09→COMPLETION_FAILURE、RULE-06→TOOL_FAILURE、RULE-07→TIMEOUT、RULE-08 按 record 证据、RULE-05→UNKNOWN | VERIFIED | `_classify()`；对应 14 个测试 |
| A3 | RULE-08 的 kind 由 record 证据决定：ABORTED attempt→EXECUTION_ABORTED；attempt.error=CONTEXT_WINDOW_EXCEEDED→CONTEXT_FAILURE；attempt.error=MODEL_ERROR→MODEL_FAILURE；failed step→STEP_FAILURE；turn/end error→TURN_FAILURE；其余 UNKNOWN | VERIFIED | `_runtime_kind()`；`test_attempt/step/turn_failure_attribution` + cross-backend 测试 |
| A4 | MODEL/CONTEXT 归因只用 exact error code，不解析自由文本 | VERIFIED | `_runtime_kind()` 只比较两个常量；审计 16 §2 |
| A5 | 去重规则：相同 (failure_kind, turn_id, step_id, attempt_id) 的候选是同一个失败，只保留一个；MULTIPLE_CANDIDATES 只表达“多个不同失败无法排序” | VERIFIED | `_dedupe()`；Codex error record 的 RULE-01+RULE-08 双 TURN_FAILURE 不误报 MULTIPLE |
| A6 | primary 选择 = 最深候选（最小 depth）；同 depth 多候选 ⇒ MULTIPLE_CANDIDATES，primary=None，全部进 secondary | VERIFIED | `_select()`；`test_multiple_failure_candidates` |
| A7 | owner != initiator；owner_ref 缺失 ⇒ ownership=INCONCLUSIVE，不推断 | VERIFIED | `test_initiator_attribution` / `test_owner_attribution` |
| A8 | context_provenance_ref 只标识“failure 发生在该 provenance 下”，不判断质量；provenance 内容 PARTIAL 保持 | VERIFIED（ref）/ PARTIAL（内容） | `test_context_provenance`；DEFAULT_PROVENANCE quality=PARTIAL |
| A9 | mapping_quality 从 record.lossiness 聚合：LOSSY > BACKEND_SPECIFIC > EXACT > UNKNOWN；LOSSY 不得因归因层变 EXACT | VERIFIED | `_mapping_quality()`；`test_lossy_mapping` |
| A10 | cross-backend 同 shape：AgentScope / Codex 经同一 `attribute()`，backend 差异只允许在 backend refs / mapping_quality / lossiness | VERIFIED | `test_cross_backend_attribution_shape`：两 backend 均 MODEL_FAILURE + 同一字段结构 |
| A11 | replay 表示漂移：Event Log 重建后 tuple/list 等 raw representation 允许不同，semantic 内容必须相等 | VERIFIED | 测试用 `_plain()` 规范化后比较完整 attribution |
| A12 | 最小 kind 集合不扩展：VERIFICATION_FAILURE 当前无证据来源，保留在集合内但不会由确定性映射产生 | VERIFIED（集合）/ MISSING（证据） | 审计 16 §2；`_classify()` 无 VERIFICATION_FAILURE 分支 |

## 显式保留的 gap（不伪造）

- VERIFICATION_FAILURE：无 execution-time verification 事件 / 无 RULE。
- attempt 层 timeout 细分、TOOL_NOT_STARTED 细分：当前 evidence 不足。
- tool/result 自身 backend ref：Phase 5-J 已显式 PARTIAL，归因层不借用
  call 的 ref 冒充 result 的 ref。
- 完整 request-time context snapshot（system / runtime_context）：
  provenance quality=PARTIAL 保持。
- 模型层细分（HTTP / stream / retry delay 等）：不在本阶段 kind 集合。

## 禁止事项

- 不调用 LLM / 不做根因文字结论；
- 不自动修复 / 不改 Prompt / 不改 Evaluation rules；
- 不读 ContextVar / runtime mutable state；
- 不把 tool failure 自动升级为 step/turn failure；
- 不把 LOSSY 当 EXACT；
- 不复制 Event Log / backend raw event。
