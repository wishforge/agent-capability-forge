# 28 — Promotion Report（Phase 5-N）

> 阶段：Phase 5-N。产物：
> `26-promotion-audit.md`、`27-promotion-assumptions.md`、
> `evaluation/promotion.py`（Promotion / Rollback contract）、
> `evaluation/tests/test_promotion_contract.py`（20 tests）。
> 未实现真实生产发布、真实 Canary 流量路由、Kubernetes / CI/CD / Cloud
> deployment、真实 rollback execution、auto promotion、LLM Judge；
> 未修改 Runtime / EventStore / Evaluator rules / models / Capability ownership。

## 1. 十三问

### 1. Promotion 是否独立于 Runtime？

**是。** `decide()` / `request_rollback()` 只消费 `ImprovementCandidate` +
`RegressionRun`；不 import runtime / EventStore / ContextVar，无写回，
不产生 Session / Turn / Step / Execution / ExecutionAttempt / EventStore 修改。

### 2. Promotion 是否消费 Candidate + Regression？

**是。** 只接受 `status=VALIDATED` 的 Candidate，且强制 candidate 与
Regression 的 `candidate_ref` / `baseline_ref` 一致；
`RegressionRun.evidence_refs` 为空时 BLOCKED，不允许 `decision=PROMOTED`
而无证据。

### 3. INCONCLUSIVE 是否阻止默认 Promotion？

**是。** Evaluation gate：任一 candidate evaluation INCONCLUSIVE ⇒ gate
INCONCLUSIVE ⇒ REJECTED；Regression gate：decision INCONCLUSIVE ⇒ REJECTED。
只有显式 exception / lossy policy 引用可放行，且 evidence quality 不升级。

### 4. REGRESSED 是否阻止 Promotion？

**是。** `regression.decision=REGRESSED` ⇒ Regression gate FAIL ⇒ REJECTED。

### 5. Critical Regression 是否能阻断 Promotion？

**是。** gate 直接检查 `RegressionRun.critical_regressions`，即使 decision
被错误构造为 IMPROVED 也会 REJECTED；Safety gate 再按声明类别单独阻断。

### 6. Version identity 是否稳定？

**契约层是。** `target_version` / `rollback_to_version` 必须通过
`UNSTABLE_VERSION_REFS` 阻断；版本注册表解析是外部职责（A1，PARTIAL）。

### 7. Rollback target 是否明确？

**是。** 每个 PromotionDecision 都必须携带稳定 `rollback_to_version`；
RollbackDecision 的 from / to 都必须稳定且不同。

### 8. Canary semantics 是否清晰？

**是。** CANARY 需要 `canary_observations` + `observation_window` +
`rollback_to_version`；缺观察 ⇒ PENDING，不伪造 CANARY PASS。流量路由未实现。

### 9. Audit trail 是否完整？

**是（契约层）。** Decision 不可变、`decision_id` 确定性派生；记录
candidate_ref / regression_ref / target_version / rollback_to_version /
gate_results / evidence_refs / reason / created_at / initiator_ref /
owner_ref / authorized_principal。没有 durable principal 时
`authorization=PARTIAL`，不伪造。

### 10. Ownership / Initiator / Authorization 是否分离？

**是。** `owner_ref`（Candidate）与 `initiator_ref`（调用方）只作为审计
字段记录；只有 `authorized_principal` 才产生 AUTHORIZED，缺失即 PARTIAL。

### 11. Lossiness 是否透明？

**是。** `promotion_evidence_quality` 继承 Regression comparison quality；
LOSSY 默认阻断，policy 例外放行时仍保持 LOSSY / PARTIAL，绝不升级 EXACT。

### 12. AgentScope / Codex 是否共享 Promotion semantics？

**是。** `decide()` / `request_rollback()` 无 backend 分支；backend 差异只
出现在 evidence refs / backend refs，不进入 decision
（`test_cross_backend_shape`）。

### 13. 最大 Promotion Data Gap 是什么？

1. **稳定版本注册表未实现**：契约能阻断不稳定 token，但任意引用的版本解析
   依赖外部 registry（A1，PARTIAL）。
2. **durable authorization / approval 未实现**：无 principal 时显式
   PARTIAL，不伪造（A5，PARTIAL）。
3. **canary observation 未实现**：无真实观察即 PENDING，观察/监控属外部
   职责（A6，PARTIAL）。
4. **Deployment Layer 未实现**：Decision / Version Reference 已冻结，
   真正应用版本在外部 Deployment Layer（A11，DESIGN PROPOSAL）。

## 2. 最终判定

**PASS**

- Candidate → Regression → Promotion boundary 成立；
- Gate model 成立（Evaluation / Regression / Safety / Policy）；
- INCONCLUSIVE / REGRESSED / critical regression 能阻断默认 Promotion；
- Stable version identity 与 rollback target 有明确语义并强制；
- Canary semantics 成立（无观察 ⇒ PENDING）；
- Decision audit trail 成立（immutable + deterministic id + 完整 refs）；
- Ownership / Initiator / Authorization 分离；
- Lossiness transparent；
- Cross-backend neutral；
- Runtime / EventStore / Evaluator / Capability ownership 零修改。

version registry、authorization、canary observation、deployment layer 仍为
外部系统职责（PARTIAL），允许。

## 3. 回归

| Suite | 结果 |
| --- | --- |
| Phase 1 probe | ALL INVARIANTS PASS（14/14） |
| Phase 2-A semantic tests | 12/12 ok |
| Phase 2-B AgentScope bridge tests | 7/7 ok |
| Phase 2-C capability lifecycle tests | 9/9 ok |
| Phase 2-D capability manager tests | 12/12 ok |
| Phase 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H runtime suite | 116 tests PASS |
| Phase 5-I / 5-J / 5-K / 5-L / 5-M / 5-N evaluation suite（17+15+15+15+15+20） | 97 tests PASS |

```bash
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/evaluation/tests -p 'test_*.py' -q
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest discover \
  -s docs/archaeology/deepseek-harness/runtime/tests -p 'test_phase*.py' -q
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest \
  docs/archaeology/python-cordis/kernel/tests/test_invariants.py -v
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest \
  docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py -v
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest \
  docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py -v
PYTHONPYCACHEPREFIX=/private/tmp/phase5n-pyc python3 -m unittest \
  docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -v
```

按阶段指令，完成后停止：不进入 Phase 6 / 真实部署 / Canary / Rollback
execution / auto promotion。
