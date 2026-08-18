# Managed Agent Runtime v1（Phase 10.1 Execution Contract Design Freeze）

- 阶段：Phase 10.1（Execution Contract Design Freeze）
- 日期：2026-08-19
- 基线：`main == origin/main`；HEAD `f8caaf1`；runtime integrity 基线 `de38f88`
- 产物：仅本设计冻结文档
- 执行原则：代码考古 + Domain Design + Contract Freeze；不写 production code、不加 production tests、不 commit、不 push

---

## 0. 代码考古结论

结论先行：**不新造第二套 identity**。现有代码已经具备稳定 Agent 身份
（`capability_id`）、Candidate 身份（`candidate_id`）、内容身份
（`artifact_digest` + `seal_digest`）和 Immutable Execution Snapshot
（Frozen Candidate 目录 `frozen/<candidate_id>/`）。本阶段只补上
AgentVersion、Deployment、RuntimeInstance 三个此前只有设计没有实现的对象，
并冻结它们的契约。

### 0.1 七个考古问题的答案

1. **当前稳定 Agent identity 是什么？**
   `capability_id`（Registry Entry 的稳定身份，`pilot/registry.py:promote()`；
   canonical 路径由 `capability_id_derivation(namespace, name)` 确定性派生，
   `src/forge/capabilityizer.py:203-206`）。当前 pilot 真实状态是 legacy
   `cap-d24c50c27fa8`（promote 时自造，`pilot/state/registry/F+/csv-clean-statistical-report.json`）。

2. **Version identity 是什么？**
   `manifest.capability.version`（int）；AdoptionAuthority 使用的
   `candidate_version = "v{N}"`（`pilot/adoption_authority_producer.py:160`）。
   没有独立的 `AgentVersion` / `CapabilityVersion` 持久对象（MVP spec §7.4 是 DESIGN，未实现）。

3. **Candidate 和 Agent 的关系是什么？**
   `CapabilityCandidate`（`candidate_id`）是 Intake / Governance 身份；
   `Capability` / Registry Entry（`capability_id`）是稳定业务身份。
   两者明确不同对象（`capability-candidate-contract-v1.md` §1.8、§23）。

4. **当前 Runtime instance 是否已经存在？**
   只有 DESIGN：`CapabilityInstance`（MVP spec §7.5，`activating/running/stopped/failed`）。
   Pilot B3 每次调用创建一次性 Docker 容器（`src/forge/sandbox.py:launch()`），
   但没有持久化 instance 对象、没有 deployment 绑定、没有 observed state 生命周期。

5. **`run_record` 能否作为 RuntimeInstance 的历史执行记录？**
   部分能。`run_record_v1`（`pilot/run_record.py`）是 append-only 实验执行记录，
   已记录 `run_id / sandbox_id / capability_used / artifact_digest / invoke_result`，
   可复用为 RuntimeInstance 的历史执行证据。它不是 live runtime state：
   没有 `deployment_id / desired_state / observed_state / start-stop 转换`，
   且每条记录是“一次实验调用”，不是“一个受管实例的生命周期”。

6. **Adoption Store 和 Run Intent 的关系是什么？**
   `adoption_store.json` 是 governance store（policies / candidates / runs /
   decisions / lifecycle / provenance / evidence / authorities / revocations）。
   `run_request` 是 canonical 条目 promoted 后写入的 **anchored Run Intent**
   （`pilot/runtime_adoption_guard.py:mark_promoted()`）；
   `load_trusted_run_request()` 是 runtime 唯一合法的 intent 来源。
   Deployment 只选择 Version；真正“允许跑什么”由 Run Intent 决定。

7. **哪些已有字段可以复用？**

| 已有字段 | 复用为 |
|---|---|
| `capability_id` | `agent_id`（稳定业务身份） |
| `candidate_id` | Candidate 治理身份 |
| `candidate_version`（`v{N}`） | AgentVersion 的版本绑定 |
| `artifact_digest` | 内容身份 D |
| `seal_digest` | Frozen Candidate 密封身份 |
| `frozen_root/frozen/<candidate_id>/` | Execution Snapshot E(D) 存储 |
| `run_request`（name/capability_id/candidate_id/candidate_version/artifact_digest/seal_digest） | Trusted Run Intent |
| `adoption_store.lifecycle`（PROMOTABLE/PROMOTED/REJECTED） | governance lifecycle |
| authority events（REVOKED/SUPERSEDED） | Version/Authority revoke 证据 |
| `run_record`（run_id/sandbox_id/capability_used/artifact_digest/invoke_result） | 历史执行记录 |

### 0.2 必须诚实记录的状态

- 当前 `pilot/state/registry/` 下没有 `adoption_store.json`，本地 F+ entry 是
  legacy Phase 8 形态（无 `adoption` 块、无 `frozen_root`）。canonical 路径已实现，
  但真实 pilot state 未迁移。Phase 10.1 冻结的是 canonical 契约；legacy 兼容只读不扩展。
- Phase 9 的 Owner Isolation 状态为 **OPEN / cross-environment validation pending**
  （`phase9d5/99-synthesis.md`），不因本契约关闭。

---

## 1. Business Problem

一个已经上线的 Agent，究竟以什么“执行契约”进入 Managed Agent Runtime？

现状是：Candidate 可以被 seal、评估、授权、promote，然后在 pilot B3 路径被
一次性挂载执行。但“这个 Agent 现在是什么版本、目标状态是什么、实际状态是什么、
谁在期望它运行、版本漂移和撤销由谁判断”都没有持久对象。生产化需要把：

```text
Agent Candidate
    ↓
Managed Agent
    ↓
Immutable Version
    ↓
Deployment
    ↓
Runtime Instance
```

冻结成一组可机器校验的对象，并保证核心目标：

```text
Desired Version
==
Deployed Version
==
Runtime Version
==
Execution Snapshot Identity
```

---

## 2. Managed Agent Model

```text
Agent（稳定业务身份，agent_id = capability_id）
  └── AgentVersion（不可变发布版本，1..*）
        └── ExecutionSnapshot E(D)（1..1，Frozen Candidate 快照）

Deployment（期望状态指针，MVP 每 Agent 1 个）
  └── version_id -> AgentVersion

RuntimeInstance（实际运行记录，MVP 每 Deployment 最多 1 个 running）
  └── deployment_id + version_id + execution_snapshot_identity
```

身份关系必须严格区分：

```text
Agent ID（capability_id）
    ≠ Candidate ID（candidate_id）
    ≠ Version（version_id = v{N}）
    ≠ Execution Snapshot（E(D)）
    ≠ Artifact Digest（D）
```

---

## 3. Agent

**定义**：Agent 代表长期稳定的业务 Agent 身份（例如 `sales-agent`、
当前 pilot 的 `csv-clean-statistical-report`）。Agent identity 不随版本改变。

**最小字段**：

```text
agent_id      = capability_id（稳定业务身份；legacy 保留 cap-<uuid>，
                canonical 新路径 = capability_id_derivation(namespace, name)）
name          = registry entry name
namespace     = family（当前 F+）
created_at
```

**规则**：

- `agent_id` 不随 Candidate / Version / Snapshot 改变。
- 同 `agent_id` 允许 1..* 个 `AgentVersion`。
- `register_agent()` 是幂等创建；同名不同 `agent_id` 或同 `agent_id` 不同 name 冲突。

---

## 4. AgentVersion

**定义**：AgentVersion 代表一个不可变、可以发布的 Agent 软件版本。
对应 MVP spec 的 `CapabilityVersion`（此前 DESIGN，未实现）。

**最小安全绑定**：

```text
version_id                 = "v" + str(manifest.capability.version)
agent_id                   = capability_id
candidate_id               = 被采纳的 Frozen Candidate
candidate_version          = "v{N}"（与 candidate 绑定）
artifact_digest            = D
seal_digest                = Frozen Candidate 密封身份
execution_snapshot_identity = E(D)
evaluation_id
promotion_decision_id
authority_id
frozen_root                = 存储定位符（实现细节，不是安全身份）
created_at
```

**Execution Snapshot Identity 定义**：

```text
execution_snapshot_identity = "snap-" + sha256(canonical({
  candidate_id, artifact_digest, seal_digest
}))[:16]

解析：E(D) -> frozen_root/frozen/<candidate_id>/
验证：verify_frozen(frozen_root, candidate_id) 必须 FROZEN_CANDIDATE_UNCHANGED；
      artifact_digest 必须与 frozen record 一致。
```

**不可变规则**：

```text
AgentVersion 创建后任何字段不可原地修改。
升级 v16 → v17 = 创建新的 AgentVersion，禁止把 v16 原地改成 v17。
同一 version_id 只能用同一组 candidate/artifact/seal 创建一次；
不同内容复用 version_id -> VERSION_CONFLICT。
```

---

## 5. Candidate 与 AgentVersion 的关系

**冻结结论**：

```text
Candidate    -> AgentVersion
```

Candidate 是**发布过程 / Governance 身份**；AgentVersion 是**正式 Managed
Agent Version 身份**。两者不是同一个对象：

- 一个 Candidate 可以先被评估 / 拒绝 / HOLD，不产生 Version。
- 只有 Evaluation PASS + Authority ISSUED + Registry PROMOTED 的 Candidate
  才能创建一个 AgentVersion。
- 一个 Candidate 最多产生一个 AgentVersion；一个 AgentVersion 只绑定一个
  Candidate（`candidate_id + candidate_version + artifact_digest + seal_digest`）。
- 语义升级 = 新 Candidate + 新 Version，原 Version 保留用于 rollback。

不采用 `Candidate == AgentVersion`：Candidate 的评估 / 拒绝 / 生命周期是
governance 状态，Version 的发布 / 部署 / 回滚是发布层状态，强行合并会让
“评估失败”和“版本不可部署”混在一起。

---

## 6. Deployment

**定义**：Deployment 代表“我要让哪个 Agent Version 以什么期望状态运行”。

**最小字段**：

```text
deployment_id
agent_id
version_id
desired_state    # RUNNING | STOPPED | REVOKED
created_at
updated_at
```

**规则**：

- `artifact_path` / `registry_path` / `b3_entry` **不是** Deployment 的安全身份；
  它们最多是 observability 定位符。安全身份只能通过 `version_id` 解析。
- Deployment 只指向 AgentVersion，再由 AgentVersion 找到 ExecutionSnapshot。
- 禁止 Deployment 直接指向 Registry live artifact 路径。
- MVP：一个 Agent 一个 Deployment；一个 Deployment 最多一个 running
  RuntimeInstance（无 scaling）。

---

## 7. RuntimeInstance

**定义**：RuntimeInstance 代表一个实际运行中的 Agent 实例。
对应 MVP spec 的 `CapabilityInstance`（此前 DESIGN，未实现）。

**最小字段**：

```text
instance_id
deployment_id
agent_id
version_id
execution_snapshot_identity
observed_state
started_at
stopped_at
failure_reason
```

**关键 invariant**：

```text
RuntimeInstance.version_id == Deployment.version_id
RuntimeInstance.agent_id == Deployment.agent_id
RuntimeInstance.execution_snapshot_identity == AgentVersion.execution_snapshot_identity
```

RuntimeInstance 是 live runtime state；`run_record` 是它的历史执行证据
（通过 sandbox_id / artifact_digest / capability_id 关联）。

---

## 8. DesiredState / ObservedState

**DesiredState**（Deployment 持有）：

```text
RUNNING
STOPPED
REVOKED
```

**ObservedState**（RuntimeInstance 持有）：

```text
READY         # 实例记录已创建，尚未开始部署
DEPLOYING     # 信任校验 + snapshot 挂载中
PENDING       # 等待启动资源
STARTING      # 进程启动中
RUNNING       # 进程运行
STOPPING      # 停止中
STOPPED       # 已停止
FAILED        # 失败（含被 guard 拒绝）
REVOKED       # 已撤销，终态
UNKNOWN       # 无法观察（心跳丢失 / 进程不可达）
```

Desired 与 Observed 必须分开，因为：

```text
Desired = RUNNING
Observed = STOPPED
```

不是“系统正常停止”，而是 `RECONCILE_REQUIRED`。

---

## 9. Reconciliation

核心机制：

```text
Desired State
      ↓
Observed State
      ↓
Diff
      ↓
Reconcile
```

**至少冻结以下 diff → action**：

| Desired | Observed | Action |
|---|---|---|
| RUNNING | STOPPED | START |
| STOPPED | RUNNING | STOP |
| version v17 | version v16（RUNNING） | UPGRADE / RECONCILE（STOP v16 → START v17） |
| REVOKED | RUNNING | STOP + BLOCK FUTURE START |
| RUNNING | FAILED | bounded retry START；超过上限保持 FAILED + escalate |
| RUNNING | UNKNOWN | probe；无进程则安全恢复 START；无法确认则保持 UNKNOWN |

本阶段不做 auto scaling；reconcile 只处理单个 Deployment 的
start / stop / upgrade / rollback / revoke。

---

## 10. Lifecycle State Machine

**RuntimeInstance 状态机**（过渡必须显式）：

```text
READY
  ↓
DEPLOYING
  ↓
STARTING
  ↓
RUNNING
  ↓
STOPPING
  ↓
STOPPED
```

失败：

```text
DEPLOYING → FAILED
STARTING  → FAILED
RUNNING   → FAILED
STOPPING  → FAILED
PENDING   → FAILED
```

撤销：

```text
READY / STOPPED → REVOKED（终态）
RUNNING → STOPPING → STOPPED → REVOKED（立即停止后进入终态）
```

重启（仅当 Desired=RUNNING 且未 REVOKED）：

```text
STOPPED → DEPLOYING
FAILED  → DEPLOYING（bounded retry）
```

任意状态 → `UNKNOWN`（liveness 丢失）；`UNKNOWN` 必须 probe 后映射回真实状态，
不得直接把 UNKNOWN 当 RUNNING 或 STOPPED。

**REVOKED = no new start**（终态，不可从 REVOKED 启动）。

---

## 11. Upgrade Contract

升级 v16 → v17：

```text
Create AgentVersion v17（新 Candidate + 新 ExecutionSnapshot E(D17)）
    ↓
Update Deployment desired version = v17
    ↓
Reconcile
    ↓
RuntimeInstance v17（snapshot = E(D17)）
```

- v16 必须完整保留，用于 rollback。
- 禁止修改 v17 变成 v16，或把 v16 原地改成 v17。
- 升级过程中 Desired v17 + Observed v16 = `VERSION_DRIFT`，不显示 HEALTHY。

---

## 12. Rollback Contract

```text
Deployment v17
    ↓
DesiredVersion = v16
    ↓
Reconcile
    ↓
Run immutable v16 snapshot
```

- 禁止 `modify v17 → become v16`。
- rollback 就是一次指向旧 Version 的 desired-state 更新，与 upgrade 共用
  reconcile 机制；API 提供语义包装。

---

## 13. Revoke Contract

`revoke_version(version_id)` 的冻结语义：

```text
new RuntimeInstance from this Version = REJECT
existing instance                     = stop immediately（控制面发起 STOP）
```

执行顺序：

```text
append authority event（REVOKED / SUPERSEDED，write-once ledger）
    ↓
lifecycle → REVOKED
    ↓
Deployment desired_state → REVOKED
    ↓
Reconcile：RUNNING → STOPPING → STOPPED → REVOKED
    ↓
trust guard 在启动链路上永久 BLOCK 该 Version
```

- `REVOKED` 是终态：不允许 new start，不允许 un-revoke。
- 如果 instance 不可达：Observed = UNKNOWN，reconcile 继续尝试 STOP，
  但任何时候都不得从该 Version 启动新实例。
- 选择 stop-immediately 而非 graceful drain：与 MVP spec §6.7 / §12
  （revoke 时若 instance running 先 stop）一致，且符合本阶段安全优先。

---

## 14. Trust Integration

Phase 9 Trust Contract 是底层不可破坏约束。Runtime 启动必须遵循：

```text
Deployment
   ↓
AgentVersion
   ↓
Trusted Run Intent（adoption_store.run_request + authority）
   ↓
ExecutionSnapshot E(D)
   ↓
verify identity（candidate_id / candidate_version / artifact_digest / seal_digest）
   ↓
verify digest（frozen_checks + verify_at_mount）
   ↓
Runtime
```

禁止：

```text
Deployment
   ↓
Registry live path
   ↓
Runtime
```

现有实现已经符合该链：`runtime_adoption_guard.adopt()` +
`verify_at_mount()` 返回的唯一 mount source 就是已验证的
`frozen/<candidate_id>/artifact`（`pilot/harness.py:phase_future("b3")`）。
Owner isolation（store owner != runtime user，runtime user 对 E(D) 无写/替换路径）
继续作为部署前置条件，不因本阶段关闭。

---

## 15. Version Drift

必须冻结：

```text
DesiredVersion == ObservedVersion
```

如果：

```text
Desired = v17
Observed = v16
```

则状态为 `VERSION_DRIFT`：

- 不能显示 `RUNNING / HEALTHY`。
- 控制面必须知道“当前实际运行的 Agent 版本不是目标版本”。
- `get_runtime_status()` 必须暴露 `version_drift: true` 和两端的 version。

---

## 16. RuntimeInstance 与 Snapshot Binding

Phase 9 的 Snapshot Binding 必须保留：

```text
AgentVersion:
  version_id      = v17
  artifact_digest = D17
  execution_snapshot_identity = E(D17)

RuntimeInstance:
  instance_id = ...
  version_id  = v17
  execution_snapshot_identity = E(D17)
```

禁止：

```text
instance.version = v17
snapshot = E(D16)
```

任何 `version_id ↔ snapshot` 不一致 -> 启动 BLOCK / 已运行实例标记
`VERSION_DRIFT` + `SNAPSHOT_BINDING_MISMATCH`。

---

## 17. Desired vs Observed Examples

### 正常

```text
Desired:  v17 / RUNNING
Observed: v17 / RUNNING
→ HEALTHY
```

### 版本漂移

```text
Desired:  v17 / RUNNING
Observed: v16 / RUNNING
→ VERSION_DRIFT
```

### 进程挂掉

```text
Desired:  v17 / RUNNING
Observed: v17 / STOPPED
→ RECONCILE_REQUIRED（next action = START）
```

### 被撤销

```text
Desired:  v17 / RUNNING
Version:  REVOKED
→ REJECT（new start blocked；existing instance → STOP）
```

### Snapshot 不一致

```text
Desired:  v17 / RUNNING
Observed: v17 / RUNNING
Snapshot: E(D16)
→ SNAPSHOT_BINDING_MISMATCH（必须立即 STOP，不能视为 HEALTHY）
```

---

## 18. Idempotency

以下操作必须有明确幂等语义：

| 操作 | 重复调用行为 |
|---|---|
| `start` | 已 RUNNING 且同 version/snapshot -> NO-OP；STARTING/PENDING -> NO-OP |
| `stop` | 已 STOPPED -> NO-OP；STOPPING -> NO-OP |
| `upgrade` | desired 已是 v17 -> NO-OP |
| `rollback` | desired 已是 v16 -> NO-OP |
| `revoke` | 已 REVOKED -> 返回既有 revocation，不重复写事件 |
| `reconcile` | diff 为空 -> NO-OP，不产生新 instance / 新事件 |
| `create_version` | 同 version_id + 同 binding -> 返回既有 Version；不同 binding -> VERSION_CONFLICT |
| `create_deployment` | 同 deployment_id + 同内容 -> 返回既有；不同内容 -> DEPLOYMENT_CONFLICT |
| `register_agent` | 同 agent_id + 同 name -> 返回既有；不同 name -> AGENT_ID_CONFLICT |

`start(RUNNING)` 永远不允许创建第二个 running instance。

---

## 19. Failure Semantics

| Failure | Observed State | Desired State | Next Reconcile Action |
|---|---|---|---|
| Snapshot Missing | FAILED / UNKNOWN | RUNNING | BLOCK START（SNAPSHOT_MISSING），escalate |
| Snapshot Digest Mismatch | FAILED / UNKNOWN | RUNNING | BLOCK START（SNAPSHOT_DIGEST_MISMATCH），escalate |
| Snapshot Owner Isolation Violation | FAILED / UNKNOWN | RUNNING | BLOCK START（EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED），escalate |
| Version Revoked | STOPPING / STOPPED / REVOKED | REVOKED | STOP + BLOCK FUTURE START |
| Runtime Start Failure | FAILED | RUNNING | bounded retry START；超限保持 FAILED + escalate |
| Runtime Crash | FAILED | RUNNING | 同 Start Failure（bounded retry） |
| Version Drift | RUNNING（v16） | RUNNING（v17） | UPGRADE：STOP v16 → START v17 |
| Deployment Not Found | UNKNOWN（无 instance） | RUNNING | DEPLOYMENT_NOT_FOUND，不自动创建 |
| Runtime Instance Missing | UNKNOWN | RUNNING | probe；无进程且未 REVOKED -> START |

所有 guard 拒绝都保持 fail-closed：Observed 进入 FAILED / UNKNOWN，
Desired 不变，reconcile 不得绕过 guard 强行启动。

---

## 20. Persistence

**不引入数据库**。逻辑存储契约：

复用：

```text
pilot/state/registry/adoption_store.json      governance（lifecycle/decisions/
                                               authorities/revocations/run_request）
frozen_root/frozen/<candidate_id>/            ExecutionSnapshot E(D)
pilot/state/registry/<family>/<name>.json     Agent 稳定身份（capability_id/name）
pilot/state/run_records.jsonl                 RuntimeInstance 历史执行证据
```

新增（Phase 10.3 才实现；本阶段只冻结逻辑 contract）：

```text
managed_runtime/versions.jsonl      AgentVersion，append-only，write-once
managed_runtime/deployments.jsonl   Deployment create/update events，
                                    当前状态 = 每 deployment_id 最新一条
managed_runtime/instances.jsonl     RuntimeInstance lifecycle events，
                                    当前 observed state = 每 instance_id 最新一条
```

不设计分布式数据库、不设计 SQL schema；文件布局由 Phase 10.3 决定。

---

## 21. Domain API

只冻结 domain/API contract，不要求 HTTP。每个函数必须定义
input / output / idempotency / error semantics。

```text
register_agent(agent_id, name, namespace) -> Agent
create_version(agent_id, candidate_id, frozen_root) -> AgentVersion
create_deployment(agent_id, version_id, desired_state) -> Deployment
get_deployment(deployment_id) -> Deployment
start_deployment(deployment_id) -> Deployment
stop_deployment(deployment_id) -> Deployment
upgrade_deployment(deployment_id, version_id) -> Deployment
rollback_deployment(deployment_id, version_id) -> Deployment
revoke_version(version_id) -> Revocation
list_runtime_instances(agent_id=None) -> list[RuntimeInstance]
get_runtime_status(instance_id) -> RuntimeStatus
reconcile(deployment_id) -> ReconcileReport
```

**关键语义**：

| 函数 | 输出 / 错误 / 幂等 |
|---|---|
| `register_agent` | Agent；AGENT_ID_CONFLICT；幂等返回既有 |
| `create_version` | AgentVersion；CANDIDATE_NOT_FROZEN / AUTHORITY_MISSING / VERSION_CONFLICT / REVOKED_AGENT；幂等返回既有 |
| `create_deployment` | Deployment；AGENT_NOT_FOUND / VERSION_NOT_FOUND / DEPLOYMENT_CONFLICT；幂等返回既有 |
| `get_deployment` | Deployment；DEPLOYMENT_NOT_FOUND |
| `start_deployment` | 设置 desired=RUNNING 并 reconcile；已 RUNNING -> NO-OP |
| `stop_deployment` | 设置 desired=STOPPED 并 reconcile；已 STOPPED -> NO-OP |
| `upgrade_deployment` | 更新 version_id + desired=RUNNING 并 reconcile；同版本 -> NO-OP |
| `rollback_deployment` | 与 upgrade 同一机制；同版本 -> NO-OP |
| `revoke_version` | Revocation；先 authority event + lifecycle + desired REVOKED + STOP；已 REVOKED -> 返回既有 |
| `list_runtime_instances` | 空列表合法；不抛错 |
| `get_runtime_status` | 返回 observed_state / version / snapshot / version_drift / failure_reason |
| `reconcile` | ReconcileReport{diff, actions, instances, verdict}；无 diff -> NO-OP |

所有返回结构为确定性 JSON 对象，错误为 `{code, message}`，缺字段视为 BLOCK。

---

## 22. Security Boundaries

Agent / AgentVersion / Deployment / RuntimeInstance 不是同一个安全身份：

```text
Agent            身份持有者（agent_id）
AgentVersion     发布对象（不可变；绑定 candidate + snapshot）
Deployment       期望状态指针（只引用 Version）
RuntimeInstance  执行对象（只消费已批准的 ExecutionSnapshot）
```

安全身份仍来自：

```text
Candidate Identity（candidate_id）
Authority（authority_id + 事件）
Run Intent（adoption_store.run_request）
Execution Snapshot（E(D)）
```

约束：

- Deployment 只能引用 AgentVersion，不能引用 artifact_path / registry_path / b3_entry。
- RuntimeInstance 只能从 `verify_at_mount()` 返回的 verified_artifact_dir 挂载。
- revoke 在 authority event 层生效；RuntimeInstance 不能覆盖 revoke。
- runtime user 对 governance store / frozen store 无写或替换路径
  （Owner Isolation，部署前置条件）。

---

## 23. Non-Goals

本阶段明确不做：

```text
Sandbox integration
Seatbelt
Landlock
nono
agt-sandbox
Kubernetes
CRD
Operator
Multi-cluster
Scheduling
GPU allocation
Auto scaling
Network policy
Secrets management
```

这些以后单独处理，不进入 10.1 契约。

---

## 24. Acceptance Criteria

Phase 10.1 完成条件：

1. 身份链 `Agent ≠ Candidate ≠ Version ≠ ExecutionSnapshot` 定义明确，
   且复用 `capability_id / candidate_id / artifact_digest / seal_digest`。
2. AgentVersion 不可变；upgrade / rollback 只创建新 Version，禁止原地改写。
3. invariant 明确：`instance.version_id == deployment.version_id`，
   `instance.execution_snapshot_identity == version.execution_snapshot_identity`。
4. Desired/Observed 分离；`Desired v17 + Observed v16 -> VERSION_DRIFT`，
   不显示 HEALTHY。
5. Revoke：new start REJECT；existing instance stop immediately；REVOKED 终态。
6. Trust chain：Deployment -> AgentVersion -> Run Intent -> ExecutionSnapshot
   -> verify identity/digest -> Runtime；禁止 Registry live path。
7. Failure semantics 每种都有 Observed / Desired / Next Reconcile Action。
8. 全部 API 有 input / output / idempotency / error semantics。
9. Persistence 复用 adoption_store + frozen store + registry + run_record；
   新 JSONL 只冻结逻辑 contract。
10. 本阶段只产出本文档：无 production code、无 production tests、
    无 commit、无 push；既有 untracked 文件未触碰。

---

## 25. Final Verdict

```text
PHASE_10_1_VERDICT = READY

AGENT_MODEL = reuse capability_id as agent_id; stable business identity;
              distinct from candidate_id / version / snapshot
AGENT_VERSION_MODEL = new immutable release object; binds agent_id +
              candidate_id + candidate_version + artifact_digest +
              seal_digest + execution_snapshot_identity
DEPLOYMENT_MODEL = new desired-state pointer; deployment_id / agent_id /
              version_id / desired_state / created_at / updated_at
RUNTIME_INSTANCE_MODEL = new observed-state record; instance_id /
              deployment_id / agent_id / version_id /
              execution_snapshot_identity / observed_state / started_at /
              stopped_at / failure_reason

DESIRED_STATE = RUNNING | STOPPED | REVOKED
OBSERVED_STATE = READY | DEPLOYING | PENDING | STARTING | RUNNING |
              STOPPING | STOPPED | FAILED | REVOKED | UNKNOWN

LIFECYCLE = READY -> DEPLOYING -> STARTING -> RUNNING -> STOPPING ->
              STOPPED; DEPLOYING/STARTING/RUNNING/STOPPING/PENDING -> FAILED;
              READY/STOPPED -> REVOKED; STOPPED/FAILED -> DEPLOYING (retry)
RECONCILIATION = Desired vs Observed diff -> START / STOP / UPGRADE /
              STOP+BLOCK / bounded retry / probe

UPGRADE = create v17 + update Deployment desired version + reconcile +
              RuntimeInstance v17; v16 retained for rollback
ROLLBACK = DesiredVersion = v16 + reconcile + run immutable v16 snapshot;
              never modify v17
REVOKE = new start REJECT; existing instance stop immediately;
              REVOKED is terminal

VERSION_DRIFT = DesiredVersion != ObservedVersion -> VERSION_DRIFT,
              never RUNNING/HEALTHY

SNAPSHOT_BINDING = instance.version_id == deployment.version_id and
              instance.execution_snapshot_identity ==
              AgentVersion.execution_snapshot_identity == E(artifact_digest)

TRUST_INTEGRATION = Deployment -> AgentVersion -> Trusted Run Intent ->
              ExecutionSnapshot -> verify identity -> verify digest ->
              Runtime; Registry live path prohibited

PERSISTENCE = reuse adoption_store + frozen store + registry + run_record;
              new JSONL contracts for versions / deployments / instances
              (logic contract only, no DB)

DOMAIN_API = register_agent / create_version / create_deployment /
              get_deployment / start_deployment / stop_deployment /
              upgrade_deployment / rollback_deployment / revoke_version /
              list_runtime_instances / get_runtime_status / reconcile

NEXT_PHASE = Phase 10.3
```

## 26. Open Questions（Phase 10.3 前解决，不阻塞 Freeze）

1. **legacy registry 迁移**：现有 `cap-<uuid>` 与 deterministic
   `capability_id_derivation()` 的映射规则（Phase 9 closure 已定“已有 entry 保留
   既有 id”，真实迁移脚本待 10.3）。
2. **ObservedState 来源**：process supervisor / docker inspect / heartbeat，
   由 Phase 10.3 的 runtime adapter 决定。
3. **retry 上限与 backoff**：Runtime Start Failure / Crash 的
   `max_retries` / `backoff` 常量，由 Phase 10.3 配置。
4. **run_record 关联**：是否在 `run_record_v1` 增加可选 `instance_id`，
   由 Phase 10.3 决定（向后兼容 append-only）。
5. **多实例 / scaling**：明确 Non-Goal，未来单独阶段。
6. **graceful drain vs stop-immediate**：本阶段冻结 stop-immediate；
   若产品需要 drain 语义，单独变更契约。
