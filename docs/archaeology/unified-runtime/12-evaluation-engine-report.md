# 12 — Evaluation Engine Report（Phase 5-I）

> 阶段：Phase 5-I。产物：
> `10-evaluation-engine-audit.md`、`11-evaluation-engine-assumptions.md`、
> `deepseek-harness/evaluation/{models,rules,evaluator,golden}.py`、
> `deepseek-harness/evaluation/tests/test_evaluator.py`（17 tests）。
> 未实现 LLM Judge / RCA / Regression / Promotion；未修改 Runtime /
> EventStore / Semantic Core / Codex / AgentScope。

## 1. Evaluator 是否完全 Runtime-independent？

**是。** `evaluator.py` / `rules.py` / `models.py` / `golden.py` 零 runtime
import；Evaluator 通过 duck typing 读取 ExecutionRecord 字段，只接受
ExecutionRecord + TaskSpecification。runtime 只出现在测试侧，用于从既有
fixture 投影 record。

## 2. ExecutionRecord 是否足够？

**否（PARTIAL）。** 5h.1 record 提供 attempt outcomes、tool calls、
initiator/owner/context provenance、backend refs；但缺少 tool results、
turn outcome、step outcome、replay_ref。Evaluator 对缺失项降级为
INCONCLUSIVE，未为 Evaluation 修改 Runtime。

## 3. 哪些 deterministic rules 可以成立？

在完整 synthetic record 上 RULE-01..13 全部可判定（PASS/FAIL）。
在当前真实 5h.1 record 上可成立（可给 PASS/FAIL）：

- RULE-03 No unsafe retry（attempt reason）
- RULE-04 All required tools called（tools[]）
- RULE-05 No forbidden tool called（tools[]）
- RULE-08 No internal runtime failure（attempts / turn reason）
- RULE-09 Terminal condition（spec 提供谓词时）
- RULE-11/12/13 Evidence availability（refs / provenance）

## 4. 哪些只能 INCONCLUSIVE？

当前 5h.1 record 上：

- RULE-01 Turn completed（无 turn outcome）
- RULE-02 No unresolved tool（无 tool results）
- RULE-06 Required tool calls succeeded（无 tool results；或 result LOSSY）
- RULE-07 No timeout（无 tool results；或 result LOSSY）
- RULE-10 Execution is replayable（无 replay_ref）

这不是 FAIL：证据不足，禁止假设。

## 5. Evidence 是否可追溯？

**是。** 每条 Finding 至少携带 `evidence_refs`：execution_id 必在；
工具规则附 tool_call_id / backend_event_ref / event_ref；attempt 规则附
attempt_id / step_id。`test_agent_scope_fixture` / `test_codex_fixture`
断言所有 finding 的 evidence_refs 非空且可定位。

## 6. Lossiness 是否显式？

**是（Evaluator 侧）**。record 内嵌 backend_metadata（Codex 六项 /
AgentScope 三项）保留；`rule_06` / `rule_07` 检测 `mapping_quality=LOSSY`
并把结果降为 INCONCLUSIVE，message 显式写 LOSSY，绝不当作 EXACT。

## 7. Replay 后 Evaluation 是否一致？

**是。** `test_replay_semantic_result_stable`：同一 execution 的 record A
（运行后）与 record B（close → reopen → replay 后）evaluate 得到相同
status 与相同 (rule_id, status, message) findings；对象身份不同，语义相同。

## 8. AgentScope/Codex 是否共享同一 Evaluation semantics？

**是。** `test_same_task_cross_backend`：同一 TaskSpecification 分别评估
AgentScope record 与 Codex record，finding 的 rule_id + status 序列完全一致；
evidence refs 各自可定位到本 backend raw ref；差异显式（backend 标识 /
missing_semantics 清单），未产生假精度。

## 9. 最大 Evaluation Data Gap 是什么？

**tool results + turn/step outcome 未投影进 ExecutionRecord**：导致
RULE-01/02/06/07 与 RULE-10（replay_ref）在真实 record 上只能
INCONCLUSIVE。次大缺口是完整 request-time context snapshot（provenance
quality 仍为 PARTIAL）与统一层 usage/cost。这些缺口属于 5-G/5-H 已冻结的
extension 边界；本阶段按指令不补数据。

## 10. Golden Tasks

`golden.py` 建立 4 个 deterministic task（TaskSpecification + record
fixture，不依赖真实网络模型）：

- TASK-01 simple tool success → PASS
- TASK-02 required tool failure → FAIL（RULE-06）
- TASK-03 unsafe retry blocked → FAIL（RULE-03）
- TASK-04 missing final terminal condition → FAIL（RULE-09）

## 11. 最终判定

**PASS**

- Evaluator 只依赖 ExecutionRecord + TaskSpecification；
- RULE-01..10 + 三条证据规则 deterministic 成立，缺失证据显式
  INCONCLUSIVE；
- evidence refs 可追溯；LOSSY 可见且不冒充 EXACT；
- replay 前后 Evaluation 语义一致；
- AgentScope / Codex 共享同一 Evaluation semantics；
- Runtime / EventStore / Semantic Core / Codex / AgentScope 未修改。

**PARTIAL 项（诚实降级，不阻塞 PASS）**：当前 5h.1 ExecutionRecord 缺
tool results / turn / step outcome / replay_ref，相关规则在真实 record 上
为 INCONCLUSIVE；完整 request-time context snapshot 仍 PARTIAL。

## 12. 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | PASS（14/14 invariants） |
| Phase 2 kernel | PASS（40/40） |
| Phase 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H | PASS（116/116 runtime suite） |
| Phase 5-I（新增） | PASS（17/17） |

```bash
PYTHONPYCACHEPREFIX=/private/tmp/eval-pyc python3 \
  docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
PYTHONPYCACHEPREFIX=/private/tmp/eval-pyc python3 -m unittest \
  docs/archaeology/python-cordis/kernel/tests/test_invariants.py \
  docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -q
PYTHONPYCACHEPREFIX=/private/tmp/eval-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
PYTHONPYCACHEPREFIX=/private/tmp/eval-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/evaluation/tests \
  -p 'test_*.py' -q
```

按阶段指令，完成后停止：不进入 LLM Judge / RCA。
