# 20 — Improvement Audit（Phase 5-L）

> 阶段：Phase 5-L。本文件在 Candidate 实现前完成，只审计当前
> `ExecutionRecord`（5j.1）、`EvaluationResult`（5-I）、
> `FailureAttribution`（5-K）以及 Codex / DSH archaeology（09/10/11）
> 已经能为 `ImprovementCandidate` 提供什么。
> 状态词：AVAILABLE / PARTIAL / MISSING。
> 判定原则：只依据 durable evidence 与已冻结契约；evidence 不足时不猜。

审计对象：

```text
Execution
  ↓
ExecutionRecord（5j.1，immutable 投影）
  ↓
EvaluationResult（RULE-01..13 findings）
  ↓
FailureAttribution（5-K，failure_id + evidence refs）
  ↓
ImprovementCandidate（本阶段）
```

## 1. 逐项审计

| # | 需要的事实 | 现状证据 | 判定 |
| --- | --- | --- | --- |
| 1 | failure → change mapping | FailureAttribution 只到 failure（17 §2/§6），不产生“改什么”；Evaluator / Attribution 无 change 概念；Codex 09：无 eval 驱动 improvement；DSH 09：NOT FOUND | MISSING |
| 2 | baseline identity | ExecutionRecord 有 `replay_ref` / `record_version` / `projection_rule_version`（04 §2/§12）；Codex 10 §1.3 的 baseline 是 context / memory git baseline，不是 capability/eval baseline；DSH 10 §3 无产品层 baseline | PARTIAL（只有 record/evidence 版本，无候选 baseline） |
| 3 | candidate identity | `failure_id` 已冻结（17 §2）；improvement candidate 对象不存在；Codex 10 §1.5 只有运行时候选（tool suggest / skill selector shadow）；DSH 11 §1 无 candidate 对象 | PARTIAL（failure 有 id；candidate 无） |
| 4 | expected effect | EvaluationResult.finding 只有 status / severity / message（models.py），不表达“预期改善”；两 archaeology 均无 effect 语义 | MISSING |
| 5 | evidence references | FailureAttribution 有 `failure_id` / `evidence_refs` / `backend_event_refs` / `initiator_ref` / `owner_ref` / `context_provenance_ref` / `mapping_quality`（17 §2），全部 durable | AVAILABLE |
| 6 | version reference | record / projection 版本已冻结（04 §2）；skill 无 version（Codex 10 §1.5）；agent/skill/prompt 版本无（DSH 10 §3） | PARTIAL（只覆盖 record 版本） |
| 7 | validation state | candidate 不存在，无 UNDER_VALIDATION / VALIDATED 等状态；Codex / DSH 无 eval gate（09/10/11） | MISSING |
| 8 | rejection reason | 无 candidate lifecycle，无 rejection 字段；两 archaeology 无拒绝语义 | MISSING |
| 9 | promotion state | Codex 10 §1.6：capability promotion NOT FOUND；DSH 11：candidate / staging / canary / promote / rollback 全 NOT FOUND | MISSING |

## 2. 结论

- 唯一 **AVAILABLE**：evidence references（5-K 已把失败证据链完整冻结）。
- **PARTIAL**：baseline identity（只有 record 版本）、candidate identity
  （只有 failure_id）、version reference（只有 record 版本）。
- **MISSING**：failure → change mapping、expected effect、validation state、
  rejection reason、promotion state。

Phase 5-L 只补 Candidate **contract / proposal metadata**：让 Candidate 能
表达 baseline / target / change / hypothesis / expected effect / evidence /
lossiness / attribution completeness / status，并强制要求 failure evidence。
不实现 change 生成、Regression、Promotion、存储格式；不修改 Runtime。
