# Managed Agent Multi-Version v1（Phase 10.3 Stage 3 Design Freeze）

- 阶段：Phase 10.3 Stage 3（Canonical Multi-Version Migration）
- 日期：2026-08-19
- 基线：`main == origin/main`，HEAD `4875b8d`
- 产物：仅本文档（Design Freeze）。不实现、不提交、不 push。
- 方法：代码考古 + 临时 probe 复现 + adversarial design。probe 在 `/private/tmp/mv-probe-*`，未进入仓库。

---

## 1. Business Problem

同一个 Agent（稳定身份 `capability_id`）必须能同时持有多个合法、可信、不可变版本：

```text
Agent A (capability_id)
 ├── AgentVersion v1  -> RunIntent(v1) -> E(D1)
 ├── AgentVersion v2  -> RunIntent(v2) -> E(D2)
 └── AgentVersion v3  -> RunIntent(v3) -> E(D3)
```

Deployment 只声明 `desired_version`，由该版本自己的信任链启动 Runtime：

```text
Deployment → desired_version = v2
    ↓
RunIntent(v2) → ExecutionSnapshot E(D2) → Runtime v2
```

禁止用全局 `run_request` 代表整个 Agent 的“当前版本”。

---

## 2. Current Single-Version Constraint

### 2.1 Trust Graph（现状）

```text
Candidate v1
   ↓ Evaluation
   ↓ issue_authority       -> authority(v1)（已按 candidate+version+decision 区分）
   ↓ promote               -> registry/F+/<name>.json（按 name 单入口）★ LOCK 1
   ↓ mark_promoted         -> adoption_store["run_request"]（单 key）★ LOCK 2
   ↓ load_trusted_run_request（无版本参数）★ LOCK 3
   ↓ frozen/<candidate_id>/artifact
   ↓ Runtime

Candidate v2
   ↓ Evaluation
   ↓ issue_authority       -> OK（store 已能容纳多 candidate）
   ↓ promote               -> ENTRY_BINDING_CONFLICT（LOCK 1 拦截）
```

### 2.2 精确锁点（代码事实）

| # | 锁点 | 代码 | 后果 |
|---|---|---|---|
| L1 | Registry entry 路径按 `(family, name)` 单入口 | `pilot/registry.py:73` `entry_path = registry_root / family / f"{name}.json"`；冲突 `:174`、`:223` | v2 不同 binding promote -> `ENTRY_BINDING_CONFLICT` |
| L2 | `adoption_store["run_request"]` 单 key，promote 后覆盖 | `pilot/runtime_adoption_guard.py:702` `store["run_request"] = run_request` | v2 写入会丢失 v1 的 RunIntent |
| L3 | 消费者全部读全局 run_request | `pilot/managed_runtime.py:184`、`:620`；`pilot/harness.py:698` | 即使入口放开，v2 也会被 v1 的 intent 校验拒绝 |
| L4 | `promote()` 每次 mint 新 `cap-<uuid>` | `pilot/registry.py:188` | 同一 Agent 的 v2 会得到不同 agent_id，变成“另一个 Agent” |
| L5 | `_version()` 只按 `version_id` 查 | `pilot/managed_runtime.py:113` | 单 Agent v1/v2 可区分，但多 Agent 的 `v1` 会互相冲突；VersionKey 未冻结 |

### 2.3 临时 probe 复现（2026-08-19）

在临时目录执行 canonical publish v1 -> v2：

```text
PROMOTE_V2=ENTRY_BINDING_CONFLICT
V1_RUN_INTENT_PRESERVED=False
V1_RUN_INTENT_REPLACED_BY_V2=True
V1_ENTRY_DISCOVERABLE=v1
AUTH_V1=auth-ddef07c922964a7f
AUTH_V2=auth-e7c4439df8038e7c
DIGEST_V1=sha256:10b6b8817...
DIGEST_V2=sha256:f7f335a96...
STORE_CANDIDATES=cand-v1,cand-v2
```

结论：

- `issue_authority(v2)` 成功，adoption_store 已能同时保存 v1/v2 的 candidates / decisions / authorities / lifecycle。
- 第一道硬锁是 registry entry locator（L1）。
- 第二道是单 key run_request（L2，probe 用伪造 v2 entry 调用 `mark_promoted` 证明覆盖语义）。
- authority、digest、seal 天然按版本不同，不需要为共存修改。

---

## 3. 为什么 Registry 是 write-once

`promote()` 的 write-once 保护的是：

> **一个 registry locator 不能被不同的 adoption binding 覆盖。**

`ENTRY_BINDING_CONFLICT` 防的是同一路径 `family/<name>.json` 被第二次 promote 静默改写（防重放、防篡改、幂等）。

它**不是**：

- Candidate identity 约束（candidate_id 每次 intake 新生成，本身可多）。
- Authority 约束（authority_id 已按 candidate/version/decision 区分）。
- Adoption 约束（store 已能容纳多 candidate adoption）。
- 历史兼容约束（legacy 单 entry 可保留）。

它是 **Registry locator 约束**：路径把“Agent”和“Version”混成了一个 `name`。必须拆开：

```text
“一份 registry entry 不能被覆盖”   -> 保留（每个 Version entry 各自 write-once）
“同一个 Agent 不能存在多个 Version” -> 删除（Version entry 按版本分文件）
```

---

## 4. Agent vs AgentVersion

沿用 10.1 冻结模型：

```text
Agent        = 长期稳定业务身份（agent_id = capability_id）
AgentVersion = 不可变发布版本（version_id = v{N}）
```

禁止把 Agent 实现成“当前 mutable Candidate”。当前代码的 L4（每次 promote mint 新
capability_id）正是这个错误的残留：Phase 9-A.1.2 已记录该 production gap
（`capability-candidate-contract-v1-production-reconciliation.md` §4），Stage 3 必须
闭合它，否则 v2 天然属于另一个 Agent。

规则：

- `agent_id` 不随 version / candidate / snapshot 改变。
- 同一 `agent_id` 可拥有 1..* 个 `AgentVersion`。
- v1、v2 的 `capability_id` 必须相同。

---

## 5. Version Key

**不新增第二个 identity。** 复用现有字段：

```text
VersionKey = (agent_id, candidate_version)
agent_id          = capability_id（稳定）
candidate_version = "v{N}"（来自 manifest.capability.version，producer 已转换）
```

不需要 `(agent_id, candidate_id, candidate_version)`：`candidate_id` 每次 intake
都变，它是发布过程身份，不是版本身份。`(agent_id, candidate_version)` 已满足：

- 同一 agent 的 `v1 != v2`；
- 同一版本重复发布（新 candidate_id）-> `VERSION_CONFLICT`；
- 不同 agent 的 `v1` 互不冲突（要求 `_version()` 查询改为 agent 作用域）。

持久化 key 表示：

```text
registry version entry : <family>/<name>/versions/v1.json, v2.json
run_requests map key   : f"{agent_id}|{candidate_version}"
versions.jsonl 查找    : (agent_id, version_id)
```

---

## 6. Registry 角色

Registry 从“唯一 current mutable Agent”重新定位为 **AgentVersion catalog / locator**：

```text
registry/
  F+/
    <name>.json                 legacy 单 entry（保留，只读兼容）
    <name>/
      versions/
        v1.json                 AgentVersion v1 entry（write-once）
        v2.json                 AgentVersion v2 entry（write-once）
      artifact/                 legacy 复制目录（仅 legacy 路径使用）
```

设计原则：

- `registry/<family>/<name>.json` 若存在，作为 legacy/agent 锚点，不再被新 promote 覆盖；
- canonical promote 写 `versions/<candidate_version>.json`；
- `discover()` 保留 legacy 语义；新增 `discover_version(family, name, version)`；
- canonical 运行路径只消费 `discover_version`，不 fallback 到 legacy 单 entry；
- `promote()` 的 capability_id 改为消费 frozen record 的确定性 id
  （`capability_id_derivation(namespace, name)`）；已有 legacy entry 时复用其
  `capability_id` 作为该 Agent 的稳定 id（迁移映射见 Open Questions）。

---

## 7. Version-scoped Authority

现状已经满足，**不需要修改**：

```text
authority_id_for(candidate_id, candidate_version, promotion_decision_id)
```

（`pilot/adoption_authority.py:45`）

probe 证实：

```text
AUTH_V1=auth-ddef07c922964a7f
AUTH_V2=auth-e7c4439df8038e7c
```

因此：

```text
Authority(v1) != Authority(v2)
Agent ID（capability_id）≠ Authority ID（auth-...）
```

revoke 天然按 authority 生效：`revoke(v2)` 只追加 v2 authority 的
`REVOKED` event，v1 authority 不受影响。

---

## 8. Version-scoped Run Intent

当前 `_run_request(entry, authority)`（`runtime_adoption_guard.py:409`）字段已经足够：

```text
name / capability_id / candidate_id / candidate_version /
artifact_digest / seal_digest / promotion_decision_id / created_at
```

缺少的是“存储 key”和“解析参数”。Stage 3 冻结：

```text
adoption_store["run_requests"] = {
  "cap-...|v1": { ...RunIntent(v1), "version_key": "cap-...|v1" },
  "cap-...|v2": { ...RunIntent(v2), "version_key": "cap-...|v2" },
}
```

解析：

```text
load_trusted_run_request(registry_root, version_key)
```

- 传入 `version_key`：只读 map 中对应记录，缺失 -> `MISSING_RUN_REQUEST`；
- 不传（legacy fixture）：只允许读旧 `run_request` 字段，canonical 路径禁止；
- 旧 `run_request` 字段保留为 legacy 别名，canonical 新路径永不写入。

Deployment 目标链变为：

```text
Deployment desired_version = v2
    ↓ version_id -> AgentVersion v2
    ↓ version_key -> RunIntent(v2)
    ↓ frozen/<candidate_id> -> E(D2)
```

---

## 9. Run Intent 的 Ownership

```text
Who creates RunIntent(v)?  mark_promoted()，在 promote(v) 成功后写入
When?                      promotion finalize 时
Can v1 be replaced by v2?  不能；run_requests 是 map 中的独立不可变记录
Can v1 remain valid after v2? 可以；只有 revoke(v1) 会使其失效
Can deployment choose either?  可以；通过 version_key 解析
```

核心原则：

> 一个 Version 的 Run Intent 必须是独立、可验证、不可被另一个 Version 覆盖的安全记录。

`mark_promoted` 从覆盖式写 `store["run_request"]` 改为按 `version_key` 写
`store["run_requests"][version_key]`；写入后照常刷新 trust anchor。

---

## 10. Adoption Store

考古结论（probe 证实）：`adoption_store.json` 的 candidates / lifecycle /
provenance 已经按 `candidate_id` 分 key，decisions / runs / evidence /
authorities 是 append 列表，**结构上已支持多版本**。唯一单点就是
`run_request`。

演进：

```text
adoption_store["run_request"]    -> legacy 别名（只读）
adoption_store["run_requests"]   -> {version_key: RunIntent}（canonical）
```

问题逐项回答：

- store digest 是否覆盖全部 version-specific records？是；store 整体 JSON 进
  `store_digest`，`run_requests` 一旦加入即被 trust anchor 覆盖。
- authority manifest 是否可以记录多个 version？是；`authorities/*.json` 已按
  authority_id 分文件，manifest digest 覆盖全部。
- active deployment 如何引用特定 version？`deployment.version_id`。
- revoke 如何影响 version record？revoke 只影响该 version 的 authority event /
  lifecycle / deployment desired；run intent 记录本身保留但校验失败。
- 旧 version 是否仍 verifiable？是；其 frozen record、authority、run intent、
  entry 均独立保留。

---

## 11. Trust Anchor

不重新发明 root：

```text
single trusted store（adoption_store.json）
    ↓ trust anchor（store_digest + authority_manifest_digest + revocation_manifest_digest）
    ↓ 多个 immutable Version records（run_requests map 内）
```

`run_requests` 进入 store 后自动被 `store_digest` 覆盖；`mark_promoted` /
`revoke_authority` 的 anchor refresh 逻辑不变。不需要每个 Version 一个新 root。

---

## 12. Frozen Snapshot

现状已满足共存：

```text
E(D1) = frozen/<candidate_id_v1>/artifact
E(D2) = frozen/<candidate_id_v2>/artifact
```

`candidate_id` 每次 intake 唯一，因此 v1/v2 snapshot 天然不互相覆盖。
`execution_snapshot_identity` 已绑定 `candidate_id + artifact_digest +
seal_digest`（`managed_runtime.py`），D1/D2 不同 -> E(D1) != E(D2)。

Stage 3 只补一条验收链（Chain C）证明 rollback 用 E(D1)、upgrade 用 E(D2)，
不改实现。

---

## 13. Candidate ID / Version ID 生命周期

| 字段 | 生产者 | 消费者 | 持久化 | 唯一性 | 稳定性 |
|---|---|---|---|---|---|
| `candidate_id` | `capabilityize()`，`cand-<uuid12>`（`capabilityizer.py`） | freeze / authority / registry / guard | frozen record + adoption_store | 每次 intake 唯一 | 不稳定，每次发布都变 |
| `candidate_version` | producer 从 `manifest.capability.version` 转 `"v{N}"` | authority / registry / guard / managed runtime | adoption_store + version entry | 同一 agent 内版本唯一 | 稳定（同一语义版本复用） |
| `capability_id` | 设计：freeze 时 `capability_id_derivation(namespace, name)`；当前生产仍是 registry mint（gap） | registry / deployment / run intent | frozen record + registry entry | agent 级唯一 | 跨版本稳定（必须修复 L4 后才成立） |

结论：

- `candidate_id` 每次发布变化：正确，它就是 Candidate 身份。
- `candidate_version` 稳定：正确，它就是 Version 身份的一部分。
- `capability_id` 是 Agent ID：正确，但当前 registry mint 行为违反它，Stage 3 必须修。

---

## 14. Promotion Contract

```text
Promotion Identity = Version Identity = (agent_id, candidate_version)
```

规则：

- `promote(v1)`、`promote(v2)` 都是合法新记录；
- `promote(v2)` 不得覆盖 `authority(v1)` 或 `run_intent(v1)`；
- 同一 version entry 重复 promote 且 binding 相同 -> 幂等返回；
- 同一 version 不同 binding（新 candidate_id / digest）-> `VERSION_CONFLICT`；
- capability_id 消费 frozen record / 既有 agent entry，不再 mint；
- 写版本 entry 前完成全部现有 trust 校验（authority / digest / frozen / anchor），
  不弱化任何检查。

---

## 15. Version Coexistence

冻结：

```text
v1 = VALID
v2 = VALID
```

同时成立。Deployment 层：

```text
Deployment A → v1
Deployment B → v2
```

在 domain 层合法。为此放开 `create_deployment` 的“每 Agent 一个 Deployment”
限制（当前 `managed_runtime.py` 的 `DEPLOYMENT_CONFLICT`），改为按
`deployment_id` 幂等；每个 Deployment 仍保持“at-most-one-running instance”。

注意：这是对 10.1 §6“MVP 每 Agent 1 个 Deployment”的显式修订。本阶段只保证
domain 创建合法；两个 Deployment 同时 RUNNING 的多实例执行不做（Non-Goal）。

---

## 16. Deployment Selection

沿用 Stage 2 已有字段 `deployment.version_id`，补齐解析链：

```text
deployment.version_id = "v2"
    ↓ _version(state_root, agent_id, "v2")     -> AgentVersion v2
    ↓ version_key                               -> RunIntent(v2)
    ↓ frozen/<candidate_id>                     -> ExecutionSnapshot E(D2)
    ↓ verify_at_mount(expected_identity=RunIntent(v2))
    ↓ Runtime v2
```

禁止：

```text
Deployment v2 -> global run_request -> v1
```

---

## 17. Upgrade / Rollback 真实可达

Stage 2 的 `seed_version()` 只是测试助手。Stage 3 生产路径：

```text
create_version(v2)  真实发布：
  capabilityize -> freeze -> evaluation -> issue_authority(v2)
    -> promote(version entry v2)
    -> mark_promoted -> RunIntent(v2)
    -> create_version -> versions.jsonl v2
    -> deployment.version_id = v2
    -> reconcile -> Runtime v2
```

Rollback：

```text
deployment.version_id = v1
    -> RunIntent(v1) -> E(D1) -> Runtime v1
```

Stage 2 冻结语义不变：

```text
stop old -> confirm STOPPED -> start new
```

---

## 18. Revoke（version-specific）

```text
revoke(v2)
    ↓ revoke_authority(authority_id(v2), REVOKED)
    ↓ v2 versions.jsonl state = REVOKED
    ↓ 引用 v2 的 deployment desired = REVOKED
    ↓ v1 保持 VALID
```

- `Deployment → v1` 仍可启动；
- `Deployment → v2` -> `VERSION_REVOKED` / `REJECT`；
- `revoke_version` 现有实现已按 version 迭代 deployment，无需改语义，只改
  version 查询为 agent 作用域。

---

## 19. Rollback 后的 Trust Chain

```text
v2 current
    ↓ rollback
Deployment desired_version = v1
    ↓ RunIntent(v1)
    ↓ Authority(v1)
    ↓ Snapshot E(D1)
    ↓ Runtime v1
```

不会经过 global run_request，也不会解析到 v2。

---

## 20. Legacy Compatibility

- `registry/<family>/<name>.json`（无 adoption 的 legacy entry）继续被
  `discover()` 读取；
- 旧 `adoption_store["run_request"]` 作为 legacy fixture 别名继续可读；
- canonical v1/v2 一律走 `versions/` + `run_requests`；
- **禁止** canonical v2 缺失记录时 fallback 到 legacy 单 entry / legacy
  run_request（保持 Phase 9-B.1.1 closure）；
- legacy 迁移（cap-uuid ↔ deterministic capability_id 映射）见 Open Questions。

---

## 21. Error Semantics

复用已有错误码，不重复创建：

| 需求错误语义 | 复用/等价现有码 | 位置 |
|---|---|---|
| `VERSION_ALREADY_EXISTS` | `VERSION_CONFLICT` | `managed_runtime.py` |
| `VERSION_NOT_FOUND` | `VERSION_NOT_FOUND` | `managed_runtime.py` |
| `VERSION_REVOKED` | `VERSION_REVOKED` | `managed_runtime.py` |
| `VERSION_TRUST_RECORD_MISSING` | `AUTHORITY_MISSING` / `UNISSUED_AUTHORITY` / `MISSING_DECISION` | guard / producer |
| `VERSION_RUN_INTENT_MISSING` | `MISSING_RUN_REQUEST` | `runtime_adoption_guard.py` |
| `VERSION_SNAPSHOT_MISSING` | `SNAPSHOT_INVALID` / `MISSING_FROZEN_CANDIDATE` | `managed_runtime.py` |
| `VERSION_BINDING_MISMATCH` | `RUN_REQUEST_MISMATCH` / `ENTRY_BINDING_MISMATCH` / `SNAPSHOT_BINDING_MISMATCH` / `AUTHORITY_BINDING_MISMATCH` | guard / managed runtime |

---

## 22. 三条端到端逻辑链

### Chain A

```text
Agent v1 -> publish -> trusted -> Deployment → v1
```

成功条件：`RunIntent(v1)`、`E(D1)`、Runtime v1。

### Chain B

```text
Agent v2 -> publish -> trusted -> Deployment → v2
```

成功条件：`RunIntent(v2)`、`E(D2)`、Runtime v2，且 v1 记录仍存在。

### Chain C

```text
v1 + v2 coexist
Deployment → v2（upgrade）  -> v2 Runtime
rollback → v1               -> v1 Runtime
```

必须使用不同 RunIntent / Snapshot / Digest；Stage 2 stop-before-start 语义不变。

---

## 23. Adversarial Cases

| 场景 | Expected |
|---|---|
| v2 run intent missing | `REJECT`：`MISSING_RUN_REQUEST` |
| v2 authority missing | `REJECT`：`AUTHORITY_MISSING` / `UNISSUED_AUTHORITY` |
| v2 snapshot missing | `REJECT`：`SNAPSHOT_INVALID` |
| v2 snapshot digest mismatch | `REJECT`：`SNAPSHOT_INVALID` / `ARTIFACT_DIGEST_MISMATCH` |
| v1 deployment points to v2 run intent | `REJECT`：`RUN_REQUEST_MISMATCH` |
| v2 deployment points to v1 run intent | `REJECT`：`RUN_REQUEST_MISMATCH` |
| revoke v2 then deployment v2 | `REJECT`：`VERSION_REVOKED`（new start；existing stop） |
| rollback v2 → v1 | 合法：Runtime v1 + RunIntent(v1) + E(D1) |
| registry v2 entry replaced by v1 | `REJECT`：`ENTRY_BINDING_CONFLICT`（version entry write-once） |

---

## 24. Stage 2 Lifecycle Semantics（不变）

不改：

```text
stop old -> confirm STOPPED -> start new
at-most-one-running per deployment
FAILED -> bounded retry
REVOKED -> terminal
```

Stage 3 只改变“target v2 从哪来”：从 synthetic seed 换成真实 canonical
publish / trust chain。

---

## 25. Minimal Implementation Boundary

| 文件 | CURRENT | REQUIRED | WHY |
|---|---|---|---|
| `pilot/registry.py` | 单 entry `family/<name>.json`，write-once；每次 mint `cap-<uuid>` | version-scoped entries（`family/<name>/versions/<v>.json`）；消费 frozen `capability_id` / 既有 agent id；`discover_version()` | L1 + L4：v2 共存 + agent_id 稳定 |
| `pilot/runtime_adoption_guard.py` | `run_request` 单 key 覆盖；`load_trusted_run_request()` 无版本参数 | `run_requests` map（key=`agent_id\|candidate_version`）；`mark_promoted` 按 version 写；`load_trusted_run_request(version_key)`；legacy `run_request` 只读别名 | L2 + L3：v1 intent 不丢、按版本解析 |
| `pilot/managed_runtime.py` | `create_version` / `DockerRuntime.start` 用全局 run_request + name-only discover；`_version()` 无 agent 作用域 | `discover_version` + version-scoped run intent；`_version(agent_id, version_id)`；`create_deployment` 放开 per-agent 单 Deployment 限制 | 生产 v2 可达、rollback 解析 v1、domain 双 Deployment |
| `pilot/harness.py` | canonical B3 读全局 run_request + `b3_entry.json` | canonical 路径从 b3_entry 的 `candidate_version` 解析 version-scoped run intent；legacy 路径不变 | 消除 canonical 路径的全局 current intent |
| `pilot/adoption_authority.py` | — | 不改 | authority 已按 candidate/version/decision 区分；store 已多 candidate |
| `pilot/adoption_authority_producer.py` | — | 不改 | issuance 已支持多 candidate 合并 |
| `src/forge/capabilityizer.py` | — | 不改 | frozen snapshot 已按 candidate_id 共存；确定性 capability_id 已在 frozen record |
| tests | Stage 2 用 `seed_version()` | Stage 3 新增：`create_version(v2)` 真实发布链 + Chain A/B/C + adversarial | 证明生产路径，不以 synthetic seed 作为最终证明 |

---

## 26. Design Freeze（本文档）

本文档即 Phase 10.3 Stage 3 Design Freeze。批准后方进入 implementation。

---

## 27. Acceptance Criteria

1. Agent A 同时存在 v1、v2，且：

```text
v1 authority != v2 authority
v1 run_intent != v2 run_intent
v1 snapshot != v2 snapshot
```

2. `Deployment → v1` 与 `Deployment → v2` 都合法；Runtime 分别得到
   RunIntent(v1)/E(D1) 与 RunIntent(v2)/E(D2)。
3. `create_version(v2)` 走真实 publish：freeze -> authority -> promote(version
   entry) -> run_intent(v2) -> versions.jsonl。
4. rollback：`Deployment → v1` -> RunIntent(v1) -> E(D1) -> Runtime v1，不被
   全局 run_request 阻塞。
5. revoke(v2) 后 v1 仍可启动，v2 启动 REJECT。
6. adversarial 表（§23）全部 fail-closed。
7. Stage 2 lifecycle 语义测试保持 PASS（不修改 stop-before-start）。
8. legacy fixture 仍可读；canonical 路径不 fallback legacy。

---

## 28. Final Verdict

```text
PHASE_10_3_STAGE3_DESIGN = READY

MULTI_VERSION = required; blocked at registry locator (L1) + single run_request (L2) +
                global intent consumers (L3) + minted capability_id (L4)
VERSION_IDENTITY = (agent_id=capability_id, candidate_version="v{N}"); no new id
VERSION_SCOPED_AUTHORITY = already satisfied (authority_id_for candidate/version/decision)
VERSION_SCOPED_RUN_INTENT = adoption_store.run_requests[agent_id|candidate_version],
                written by mark_promoted per version
ADOPTION_STORE = already multi-candidate; only run_request must become a version map
TRUST_ANCHOR = unchanged single anchor; store_digest covers run_requests automatically
SNAPSHOT_COEXISTENCE = already satisfied (frozen/<candidate_id>/)
PROMOTION = version-scoped entries; consume frozen capability_id; never overwrite v1
DEPLOYMENT_SELECTION = deployment.version_id -> AgentVersion -> RunIntent(version) -> E(D)
UPGRADE_REACHABILITY = create_version(v2) real publish chain (no seed_version)
ROLLBACK_REACHABILITY = deployment.version_id=v1 -> RunIntent(v1) -> E(D1)
REVOKE = per-authority REVOKED; v1 remains VALID; v2 start REJECT
LEGACY_COMPATIBILITY = legacy entry + legacy run_request read-only aliases;
                canonical never falls back
IMPLEMENTATION_BOUNDARY = pilot/registry.py, pilot/runtime_adoption_guard.py,
                pilot/managed_runtime.py, pilot/harness.py (minimal),
                + Stage 3 acceptance tests
OPEN_QUESTIONS = legacy capability_id migration mapping; deployment multiplicity
                vs 10.1 contract; version uniqueness scope; run_requests migration

NEXT_PHASE = implementation
```

---

## 29. Non-Goals / Open Questions

### Non-Goals（本阶段不实现）

```text
Process Supervisor
Sandbox
Kubernetes
Multi-cluster
Autoscaling
两个 Deployment 同时 RUNNING 的多实例调度
修改 Stage 2 stop-before-start 语义
以 seed_version() 作为最终 production solution
弱化 trust checks
本阶段提交代码
```

### Open Questions

1. legacy `cap-<uuid>` 与 deterministic `capability_id_derivation()` 的迁移映射
   （Phase 9 已定“已有 entry 保留既有 id”，执行细节待实现阶段）。
2. 10.1 §6“每 Agent 一个 Deployment”在本阶段显式放开为多 Deployment；若产品
   仍要求单 Deployment，则 §15 的 Deployment A/B 需回退为“同一 Deployment 的
   desired version 切换”。
3. `version_id = v{N}` 保持全局唯一，还是仅 `(agent_id, version_id)` 组合唯一；
   设计采用组合唯一，`_version()` 需带 agent 作用域。
4. 既有 `adoption_store["run_request"]` 数据迁移到 `run_requests` map 的
   一次性脚本/幂等规则。

