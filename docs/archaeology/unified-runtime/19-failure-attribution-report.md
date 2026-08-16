# 19 — Failure Attribution Report（Phase 5-K）

> 阶段：Phase 5-K。产物：
> `16-failure-attribution-audit.md`、`17-failure-attribution-contract.md`、
> `evaluation/failure_attribution.py`（Attribution Layer）、
> `evaluation/tests/test_failure_attribution.py`（15 tests：14 个指定 +
> cross-backend shape）。
> 未实现 LLM RCA / 自动修复 / Improvement / Regression / Promotion；
> 未修改 Runtime / EventStore / Evaluator rules / Codex / AgentScope source。

## 1. Attribution Layer 是否成立？

**是。** `attribute(execution_record, evaluation_result)` 是纯函数：

```text
ExecutionRecord（5j.1）+ EvaluationResult（5-I）
    ↓
FailureAttribution（immutable dataclass）
```

- 只读 FAIL findings 的 rule_id + evidence_refs 与 record 字段；
- 不 import runtime / EventStore，不读 ContextVar；
- 同一输入 ⇒ 同一输出（replay 稳定测试通过）。

## 2. 十问是否全部有字段回答？

| 问 | 字段 | 状态 |
| --- | --- | --- |
| 哪个 execution | execution_id | VERIFIED |
| 哪个 turn | turn_id | VERIFIED |
| 哪个 step | step_id | VERIFIED |
| 哪次 attempt | attempt_id | VERIFIED |
| 哪个 tool / model request | evidence_refs.tool_call_id / backend refs | VERIFIED |
| 什么失败类型 | failure_kind | VERIFIED |
| 谁触发 | initiator_ref | VERIFIED（ADAPTER_DERIVED） |
| 谁拥有 | owner_ref / ownership | VERIFIED（缺失=INCONCLUSIVE） |
| context provenance | context_provenance_ref | VERIFIED（内容 PARTIAL） |
| backend evidence 在哪 | backend_event_refs[] | VERIFIED（result 自身 ref PARTIAL） |

## 3. Failure Kind 可用性（对照 16 审计）

| Kind | 审计 | 实现后 |
| --- | --- | --- |
| TOOL_FAILURE | AVAILABLE | VERIFIED（test_tool_failure_attribution） |
| MODEL_FAILURE | AVAILABLE | VERIFIED（cross-backend，attempt.error=MODEL_ERROR） |
| TIMEOUT | AVAILABLE | VERIFIED（test_timeout_attribution） |
| UNRESOLVED_TOOL | AVAILABLE | VERIFIED（test_unresolved_tool_attribution） |
| UNSAFE_RETRY | AVAILABLE | VERIFIED（test_unsafe_retry_attribution） |
| TURN_FAILURE | AVAILABLE | VERIFIED（test_turn_failure_attribution） |
| STEP_FAILURE | AVAILABLE（DERIVED） | VERIFIED（test_step_failure_attribution） |
| EXECUTION_ABORTED | AVAILABLE | VERIFIED（test_attempt_failure_attribution） |
| CONTEXT_FAILURE | PARTIAL | VERIFIED 映射（exact error code；无上下文质量判断） |
| COMPLETION_FAILURE | AVAILABLE（DERIVED） | VERIFIED 映射（RULE-01/04/09） |
| VERIFICATION_FAILURE | MISSING | 保留在集合，无证据时不产生（不猜） |
| UNKNOWN | 兜底 | VERIFIED（RULE-05 / 未映射 RULE） |

## 4. Hierarchy 是否不自动升级？

**是。**

- TOOL_FAILURE 存在时不附加 STEP/TURN 候选（候选只来自 FAIL findings，
  record 不反向补充）；
- STEP_FAILURE 与 TURN_FAILURE 同时存在时 primary=STEP_FAILURE（更深），
  TURN_FAILURE 只进 secondary；
- UNSAFE_RETRY 与 TURN_FAILURE 同时存在时 primary=UNSAFE_RETRY；
- 同 depth 多候选 ⇒ MULTIPLE_CANDIDATES，不猜 root cause。

## 5. MULTIPLE_CANDIDATES 是否正确表达？

**是。** `test_multiple_failure_candidates`：TOOL_FAILURE + UNRESOLVED_TOOL
同 depth ⇒ primary=None，secondary=全部候选，failure_kind=MULTIPLE_CANDIDATES。

## 6. Causality / Ownership / Context 是否 durable？

**是。**

- parent_ref 来自 attempt.parent_execution_id；
- initiator_ref / owner_ref 来自 record 持久化 refs；
- context_provenance_ref 来自 record.context_provenance[0]；
- 全部经 replay 测试验证语义不变；
- owner 缺失 ⇒ ownership=INCONCLUSIVE；owner ≠ initiator 有测试断言。

## 7. Cross Backend 是否同 shape？

**是。** `test_cross_backend_attribution_shape`：

- AgentScope（模型抛错）与 Codex（codex_error.jsonl 的失败 execution）
  都产生 `failure_kind=MODEL_FAILURE`；
- 两者都有 execution_id / turn_id / step_id / attempt_id /
  initiator_ref / mapping_quality；
- backend 差异只出现在 backend refs / lossiness / mapping_quality，
  不影响统一 shape。

## 8. 最大剩余 Gap

- VERIFICATION_FAILURE 无证据来源（保留在 kind 集合，不产生）；
- tool/result 自身 backend ref 仍 PARTIAL（Phase 5-J 冻结边界）；
- 完整 request-time context snapshot 仍 PARTIAL；
- attempt 层 timeout 细分与 TOOL_NOT_STARTED 细分仍缺失。

这些均属于已冻结的 extension 边界，本阶段按指令不补数据。

## 9. 最终判定

**PASS**

- 纯确定性、只读、可追溯的 Attribution Layer 成立；
- FailureAttribution 覆盖十问；最小 kind 集合 + MULTIPLE_CANDIDATES +
  primary/secondary 语义全部实现；
- 层级不自动升级；owner != initiator；context 只记录不判断；
- replay 稳定；AgentScope / Codex 同一 shape；
- 无 LLM RCA / 自动修复 / Improvement / Regression / Promotion；
- Runtime / EventStore / Evaluator rules 未修改。

## 10. 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | 未触碰（无变更） |
| Phase 2 kernel | 未触碰（无变更） |
| Phase 4/5 runtime suite（116 tests） | PASS |
| Phase 5-I / 5-J / 5-K evaluation suite（47 tests：17+15+15） | PASS |

```bash
PYTHONPYCACHEPREFIX=/private/tmp/phase5k-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
PYTHONPYCACHEPREFIX=/private/tmp/phase5k-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/evaluation/tests \
  -p 'test_*.py' -q
```

按阶段指令，完成后停止：不进入 Improvement / Regression / Promotion。
