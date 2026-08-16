# 36 — Real Judge Report（Phase 6-B）

> 阶段：Phase 6-B。产物：
> `35-real-judge-provider-audit.md`、
> `evaluation/judge_provider.py`（JudgeProvider + DeepSeek adapter +
> calibration）、`evaluation/tests/test_real_judge.py`（23 tests）、
> `evaluation/artifacts/phase6b-judge-runs.jsonl`（14 runs）、
> `37-real-judge-assumptions.md`。
> 执行：2026-08-16，DeepSeek `deepseek-v4-flash`；默认
> `temperature=0.0, seed=42, max_tokens=8192, timeout=120s`；model variance
> 测试用 `temperature=0.7, seed=None`。

---

## 1. 十二问

### 1. 真实 provider 是否可用？

**是。** `provider_status()`：`provider=deepseek model=deepseek-v4-flash
models=['deepseek-v4-flash','deepseek-v4-pro']`；密钥来自既有
`~/.codex/config.toml`，未落盘。

### 2. Judge 是否能稳定输出结构化结果？

**是（达到本阶段标准）。** 14/14 次真实 run 全部解析为 `LLMJudgeResult`；
带网络运行 `test_real_judge.py`：23 passed。前提是 `max_tokens=8192`
（2048 会被 reasoning tokens 挤占导致 JSON 截断）和 `timeout=120s`。

### 3. Calibration agreement 是多少？

**7/7 = 1.0**，但 `N=7 < 30` →
`NOT_STATISTICALLY_MEANINGFUL`。

| Case | expected | actual | score | confidence |
| --- | --- | --- | --- | --- |
| TASK-JUDGE-01 | PASS | PASS | 1.0 | HIGH |
| TASK-JUDGE-02 | FAIL | FAIL | 0.22 | HIGH |
| TASK-JUDGE-03 | FAIL | FAIL | 0.78 | HIGH |
| TASK-JUDGE-04 | INCONCLUSIVE | INCONCLUSIVE | None | LOW |
| TASK-JUDGE-05 | FAIL | FAIL | 0.22 | HIGH |
| TASK-JUDGE-06 | FAIL | FAIL | 0.22 | HIGH |
| TASK-JUDGE-07 | PASS | PASS | 1.0 | HIGH |

### 4. False pass rate？

**0/7 = 0.0。**

### 5. False fail rate？

**0/7 = 0.0。**

### 6. Inconclusive rate？

**1/7 ≈ 0.143**（TASK-JUDGE-04，预期 INCONCLUSIVE）。

### 7. Prompt sensitivity？

**本样本无差异。** TASK-JUDGE-05 在 Prompt A / Prompt B 下均为
`FAIL 0.22 HIGH`；`prompt_ref` 不同、`judge_id` 不同。样本太小，不能外推。

### 8. Model variance？

**本样本为 0。** `temperature=0.7, seed=None` 对 TASK-JUDGE-01 跑 3 次：
全部 `PASS 1.0 HIGH`。`seed=42, temperature=0` probe 3/3 相同。早期一次
cross-backend 观察到 FAIL ↔ INCONCLUSIVE 翻转；加 final-message contract
guard 后稳定为双 INCONCLUSIVE。

### 9. Context sensitivity？

**成立。** 完整 context（EXACT）→ PASS；PARTIAL provenance（缺 system prompt
snapshot）→ 真实 judge 自行 INCONCLUSIVE（“无法验证库存阈值规则”）；provenance
缺失 → contract guard 强制 INCONCLUSIVE / LOW。

### 10. Lossiness handling？

**成立。** Prompt 显式包含 `has_lossy_evidence=true` 与 `lossiness[]`；adapter
contract guard 强制 INCONCLUSIVE / LOW，reasoning 含 `LOSSY`；禁止
LOSSY → EXACT。

### 11. Cross-backend consistency？

**成立（本样本）。** AgentScope 与 Codex 相同 TaskSpecification + Rubric：
两者均 INCONCLUSIVE / LOW（record 无 final message），status / score /
confidence / evidence 语义一致；`judge_id` 与 evidence refs 因 backend 不同。

### 12. 最大真实 Judge gap？

1. **Oracle / rubric 粒度不足**：oracle 只写“采购建议”时，数量错误的
   TASK-JUDGE-05 被判 `PASS 1.0`；换成具体 oracle（采购 10 件）后正确
   `FAIL 0.22`。Judge 无法自动补全任务阈值。
2. **完整 request-time context 未持久化**（quality=PARTIAL）：真实 judge 对
   无法验证的规则返回 INCONCLUSIVE，正确但保守。
3. **Reasoning tokens 与 max_tokens 共享**：budget 不足会截断 JSON。
4. **Calibration 样本只有 7 个**，不足以证明“模型已校准”。

---

## 2. 最终判定

**PARTIAL。**

| PASS 条件 | 结果 |
| --- | --- |
| 真实 provider 成功运行 | ✅ |
| Judge 输出稳定 | ✅（14/14 runs parsed） |
| Calibration 有证据 | ✅ 但 N=7 → NOT_STATISTICALLY_MEANINGFUL |
| Deterministic precedence 成立 | ✅（deterministic FAIL 覆盖 judge PASS） |
| Context / Lossiness handling 成立 | ✅ |
| Cross-backend evaluation semantics 成立 | ✅（本样本一致） |

由于 calibration sample too small，按阶段定义判 PARTIAL，不进入 Phase 6-C。

---

## 3. 回归

执行（2026-08-16）：

```text
python3 -m pytest docs/archaeology/deepseek-harness/evaluation/tests -q
141 passed, 10 skipped, 8 subtests passed   # 10 skipped = 无网络时真实 provider 测试 BLOCKED-skip

python3 -m pytest docs/archaeology/deepseek-harness/evaluation/tests/test_real_judge.py -q   # 带网络单独运行
23 passed, 8 subtests passed

python3 -m pytest docs/archaeology/deepseek-harness/runtime/tests -q
116 passed, 5 subtests passed

python3 -m pytest research/control-plane-loop -q
30 passed
```

Phase 1 / 2 / 4-A / 4-B / 4-C / 4-D / 5-B.1 / 5-C / 5-D / 5-F / 5-H / 5-I /
5-J / 5-K / 5-L / 5-M / 5-N / 5-O / 6-A 继续 PASS。Runtime / EventStore /
Capability Lifecycle 零修改。

## 4. Judge Result Persistence

`docs/archaeology/deepseek-harness/evaluation/artifacts/phase6b-judge-runs.jsonl`
（14 runs）：`judge_run_id` / `model_ref` / `model_version` / `prompt_ref` /
`prompt_version` / `rubric_ref` / `created_at` / `status` / `score` /
`confidence` / `usage`。只属于 Evaluation Layer，不写入 Agent Runtime events。

