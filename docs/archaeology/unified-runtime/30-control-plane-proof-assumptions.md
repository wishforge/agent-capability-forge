# 30 — Control Plane Proof Assumptions（Phase 5-O）

> 阶段：Phase 5-O。以下假设支撑
> `evaluation/tests/test_control_plane_e2e.py` 的端到端证明；
> 每一项都可在测试或本文档中找到固定输入，不依赖 random / wall-clock /
> 网络 / LLM。

| # | 假设 | 固定输入 / 证据 |
| --- | --- | --- |
| A1 | deterministic task fixture：采购/库存场景，无外部系统 | `TaskSet(phase5o-procurement, v1, 4 tasks)`；tool 输出固定为 `stock:5` / `suggestion:created` / `ok`；`TaskSpecification` 固定 required / forbidden tools |
| A2 | version identity：V1/V2/V3 只是稳定字符串，不做真实版本注册 | `agents:inventory:v1/v2/v3`；所有 version 引用都通过 Regression / Promotion 的稳定 token 校验 |
| A3 | baseline identity：V1 是稳定 baseline | `baseline_ref=agents:inventory:v1` 同时进入 Candidate 与 RegressionRun |
| A4 | candidate identity：同一 failure 派生 V2/V3 proposal | `propose()` 从 V1 attribution 生成 `PROPOSED` candidate；`candidate_id` 确定性派生 |
| A5 | regression comparability：同一 TaskSet 比较 baseline 与 candidate | `compare()` 强制 candidate.baseline_ref == run.baseline_ref；缺失/多余 task 全部 BLOCKED；lossiness 保持可见（AgentScope = PARTIAL，Codex = LOSSY） |
| A6 | promotion eligibility：PROMOTED 是契约层资格，不是真实部署 | `decide()` 只做 Evaluation / Regression / Safety / Policy gate；测试断言 `decision=PROMOTED` 且文档明确「未部署」 |
| A7 | rollback reference：RollbackDecision 只验证语义 | `request_rollback(from=v2, to=v1)` 返回 `REQUESTED`；不执行 rollback |
| A8 | replay stability：reopen 后语义等价 | `EventStore(path)` 持久化 → `replay()` → 重建 record → evaluate + attribute；断言 status / findings / attribution 语义等价 |
| A9 | evidence chain completeness：每层有稳定 reference | 测试从 PromotionDecision 反查 regression → candidate → attribution → evaluation → record → replay_ref → backend refs；AgentScope adapter 每次运行生成随机 backend event/reply ID，因此只保证语义稳定，不做字节级相等（PARTIAL） |
| A10 | cross-backend equivalence：同一 Control Plane contract 作用于 AgentScope 与 Codex | `test_cross_backend_shape` 对两个 backend 各跑完整 V1→V2 链；decision / gates / aggregate / critical 全部相等 |

## 边界

- AgentScope 使用真实 adapter 路径 + scripted deterministic model（无网络）。
- Codex 使用 pinned RolloutItem schema 的确定性 fixture
  （V1/V3 为本测试内联生成，V2 为单步双 tool 的等效 fixture），
  不调用真实网络模型；已有 real Codex golden record 由 Phase 5-C/5-D
  测试另行覆盖。
- 版本注册表、真实部署、canary traffic、rollback execution 均不在本阶段
  假设内。
