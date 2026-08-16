# 39 — Calibration Assumptions（Phase 6-C）

> 阶段：Phase 6-C。Calibration 的显式假设；每条都是 audit / report / 后续
> 阶段的边界，静默改变这些语义即视为 calibration contract gap。

---

- **A1 calibration dataset size**：设计 30 cases（dataset `calibration:phase6c:procurement@1`），
  真实执行可以跑子集；`N >= 30` 才标记 `STATISTICALLY_MEANINGFUL`，
  `N < 30` 一律 `NOT_STATISTICALLY_MEANINGFUL / INSUFFICIENT_SAMPLE`。
  不把 designed N 宣称成 executed N。
- **A2 class balance**：expected 分布 6 PASS / 17 FAIL / 7 INCONCLUSIVE；
  PASS 占比 < 50%。只按真实 executed 样本计算 metrics；空类别不假装平衡。
- **A3 oracle correctness**：oracle 由本阶段人工设计，代表任务期望事实/约束；
  不是外部 ground truth。oracle 写错会导致 calibration label 错，
  因此 TASK-JUDGE-05 保留 weak→strong 对照以暴露 weak oracle 的 false PASS。
- **A4 rubric correctness**：单一版本化 rubric（`rubric:phase6c:procurement@1`，
  5 criteria，均带 `oracle_ref`）；假设 rubric 覆盖任务完成、正确性、业务相关、
  输出质量、安全/策略五个判定维度；不同 domain 需要新 rubric 版本而不是改写旧版本。
- **A5 score calibration**：score ∈ 0.0–1.0；区间 0.0–0.2 strong fail、
  0.2–0.4 fail、0.4–0.6 partial/uncertain、0.6–0.8 mostly correct、
  0.8–1.0 strong pass；最终 status 不只由 score 决定——critical rule failure
  直接 FAIL，INCONCLUSIVE 时 score=None。
- **A6 confidence calibration**：HIGH/MEDIUM/LOW 表示判断确定性；
  HIGH + wrong 计入 `MIS_CALIBRATED`；PASS + LOW 构造时拒绝；
  INCONCLUSIVE + HIGH 构造时拒绝。
- **A7 prompt sensitivity**：Prompt A/B 只改 wording、不改 rubric/oracle 语义；
  用同一 dataset 比较 agreement / false pass / false fail / inconclusive /
  confidence。目标是“最稳定、最安全、最少 false pass”，不是“最高分”。
- **A8 model variance**：真实 provider 为 DeepSeek `deepseek-v4-flash`，
  `model_version=UNKNOWN` 不伪造；variance 通过 temperature/seed 多次运行实测。
- **A9 context availability**：Judge 只能使用 record 中的 context /
  provenance，不能默认拥有完整 runtime state；EXACT 正常判断，PARTIAL 可能
  INCONCLUSIVE/LOW，MISSING 必须 INCONCLUSIVE；MISSING 上出现 HIGH-confidence
  PASS 记为 `CALIBRATION_FAILURE`。
- **A10 lossiness**：LOSSY critical evidence 对 Judge 可见；任何 LOSSY 记录
  不得产生 HIGH-confidence PASS；fake judge 与 provider contract guard 强制
  INCONCLUSIVE/LOW，LOSSY 永不升级为 EXACT。
- **A11 cross-backend comparability**：同一 TaskSpecification + Oracle +
  Rubric 下比较 AgentScope / Codex；允许 backend-specific metadata 与
  evidence refs 不同，不允许核心 status/score/confidence 语义不一致而无人发现。
