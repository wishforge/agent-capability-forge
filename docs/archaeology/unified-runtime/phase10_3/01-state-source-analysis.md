# 01 — 真实状态源分析（10.1 Open Question 1/3/4 收口）

- 阶段：Phase 10.3 Stage 1
- 日期：2026-08-19
- 基线：`main == origin/main == 661d866`（managed-agent-runtime-v1.md 已 commit/push）
- 方法：代码考古，无生产代码改动

## 结论：唯一状态源

| 状态 | 唯一 source of truth | 位置 |
|---|---|---|
| Deployment desired state | `managed_runtime/deployments.jsonl` 每 deployment_id 最新一条事件 | `pilot/state/managed_runtime/` |
| RuntimeInstance observed state | `managed_runtime/instances.jsonl` 每 instance_id 最新一条事件 | `pilot/state/managed_runtime/` |
| AgentVersion | `managed_runtime/versions.jsonl`（write-once；revoke 追加终态事件） | `pilot/state/managed_runtime/` |
| Governance（authority/lifecycle/revocation） | `adoption_store.json` + `authorities/*.json|*.events.jsonl`（Phase 8 既有，只读消费） | `pilot/state/registry/` |
| ExecutionSnapshot E(D) | `frozen/<candidate_id>/`（Frozen Candidate，0555/0444） | `pilot/state/frozen_candidates/` |
| run_record | 历史执行证据（append-only），不拥有生命周期 | `pilot/state/run_records.jsonl` |

本阶段明确**不出现**“run_record + state.json + runtime instance + deployment 四处写状态”。
`b3_entry.json` 维持既有定位符角色（`pilot/runtime_adoption_guard.py:455-493`），不参与
Deployment/RuntimeInstance 状态判定。

## Q1 — Deployment desired state / RuntimeInstance observed state 存哪里

10.1 已冻结逻辑存储契约（`docs/architecture/managed-agent-runtime-v1.md` §20）：

```text
managed_runtime/deployments.jsonl   Deployment create/update 事件，
                                    当前状态 = 每 deployment_id 最新一条
managed_runtime/instances.jsonl     RuntimeInstance lifecycle 事件，
                                    当前 observed state = 每 instance_id 最新一条
```

实现遵循该契约：`deployments.jsonl` 最新事件是 **desired state 唯一状态源**；
`instances.jsonl` 每 instance 最新事件是 **observed state 唯一状态源**。

为什么不复用现有文件：

- `run_record`（`pilot/run_record.py:8-18`）字段固定、按“一次实验调用”建模，
  没有 `deployment_id / desired_state / observed_state`，且会随 oracle/cost
  追加语义（10.1 §0.1 考古结论 5）。
- `adoption_store.json` 是 governance store，不是运行状态 store；
  `run_request` 是 Run Intent（`pilot/runtime_adoption_guard.py:423-453`），
  表达“允许跑什么”，不表达“现在跑没跑”。
- Registry entry（`pilot/registry.py:186-202`）是 Agent 身份 + 发布绑定，
  不表达目标/实际运行状态。

## Q3 — legacy id migration（只回答，不实施）

代码事实：

- Legacy `capability_id`：`pilot/registry.py:188`（`promote()`）与 `:242`
  （`reject()`）生成 `cap-<uuid>`；真实 pilot entry 为
  `cap-d24c50c27fa8`（`pilot/state/registry/F+/csv-clean-statistical-report.json`，
  无 `adoption` 块，Phase 8 legacy 形态）。
- Canonical 确定性 id：`src/forge/capabilityizer.py:206`
  `capability_id_derivation(namespace, name)`。

映射结论：

```text
legacy capability_id  -> Agent.agent_id（保留既有 id，不改写）
legacy candidate_id   -> Candidate 治理身份（registry adoption 块缺失时无绑定）
legacy version        -> AgentVersion.version_id = "v{N}"（manifest.capability.version）
```

判定：

- 已有 registry entry 保留既有 `capability_id` 作为 `agent_id`：**安全**，
  因为 `agent_id` 只要求稳定、不要求确定性。
- Legacy entry 缺少 `adoption` 块 / `artifact_identity == CANONICAL_ARTIFACT_IDENTITY_V1`：
  `create_version` 显式返回 `LEGACY_MIGRATION_REQUIRED`，不推断、不降级。
- 记录：`MIGRATION_REQUIRED`，本阶段不实施迁移。

## Q4 — run_record ↔ instance_id

结论：`run_record = historical execution evidence`（10.1 冻结语义）。

实现决定：

- 不把 `instance_id` 加入 `pilot/run_record.py:FIELDS`（:8-18）——那会让全部历史
  run record 变成“缺字段”，破坏 append-only 兼容。
- 反向关联：RuntimeInstance 事件可选记录 `run_id`；当 runtime start 产生真实
  执行记录时，instance 持有 `run_id` 引用，run_record 本身不被 instance 生命周期写回。
- 满足：“历史 evidence 可以关联 instance，不拥有 instance 生命周期”。

