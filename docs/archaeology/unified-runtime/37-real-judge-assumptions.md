# 37 — Real Judge Assumptions（Phase 6-B）

> 阶段：Phase 6-B。真实 provider 集成的显式假设；每条都是审计 / 报告 /
> 未来 Phase 6-C 的边界，静默改变这些语义即视为 contract gap。

---

- **A1 provider availability**：真实 provider 是 DeepSeek
  （`https://api.deepseek.com/`，OpenAI 兼容），配置来自既有
  `~/.codex/config.toml`；provider 不可达时真实 E2E 测试
  `BLOCKED`（skip），不使用 fake provider 冒充。env 中的 key 只作 fallback
  来源，任何 secret 不落盘。
- **A2 provider determinism**：DeepSeek 接受 `seed` + `temperature`；probe
  显示 `seed=42, temperature=0` 3/3 相同，因此不标记
  `NON_DETERMINISTIC_PROVIDER`，但 provider 不承诺跨版本 / 复杂 prompt 的
  确定性；model variance 仍需实测。
- **A3 schema reliability**：`response_format={"type":"json_object"}` 可用；
  `json_schema` 不支持。输出可能因 reasoning tokens 挤占 `max_tokens` 而
  截断（默认 8192），或出现空 content；一律归为 `INVALID_OUTPUT`，不猜测。
- **A4 prompt sensitivity**：Prompt A / B 只改 wording、不改 rubric
  semantics；本次 TASK-JUDGE-05 未观察到差异，但样本太小，不能外推。
- **A5 calibration size**：`N=7 < 30` → metrics 标
  `NOT_STATISTICALLY_MEANINGFUL`；不把当前 agreement 1.0 宣传成“已校准”。
- **A6 score semantics**：0.0 = 完全错误，0.5 = 部分正确，1.0 = 满足 rubric；
  rubric `pass_threshold=0.8 / fail_threshold=0.4`；INCONCLUSIVE → score None。
  模型分数按原样记录，不做黑箱映射。
- **A7 confidence semantics**：HIGH / MEDIUM / LOW 表示判断确定性；
  PASS + LOW 与 INCONCLUSIVE + HIGH 被 adapter 拒绝为 `INVALID_OUTPUT`；
  contract guard 强制 INCONCLUSIVE → LOW。
- **A8 context availability**：Judge 只能使用 model-visible context /
  provenance，不能默认拥有完整 runtime state；PARTIAL provenance 允许真实
  judge 返回 INCONCLUSIVE；provenance 缺失由 adapter 强制 INCONCLUSIVE；
  需要 PASS 的 calibration case 使用 EXACT context。
- **A9 lossiness**：LOSSY 证据在 prompt 中显式可见；任何 LOSSY 记录由 adapter
  强制 INCONCLUSIVE / LOW，LOSSY 永不升级为 EXACT。
- **A10 cross-backend consistency**：同一 TaskSpecification + Rubric 对
  AgentScope / Codex 产生相同核心 semantics（status / score / confidence）；
  backend-specific wording 与 evidence refs 允许不同；record 缺 final
  message 时两端均 INCONCLUSIVE。

