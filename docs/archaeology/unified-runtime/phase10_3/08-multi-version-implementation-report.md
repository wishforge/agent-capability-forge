# 08 — Phase 10.3 Stage 3 实现报告（Canonical Multi-Version）

- 阶段：Phase 10.3 Stage 3（Canonical Multi-Version Implementation）
- 日期：2026-08-19
- 基线：`0818a92`（Design Freeze）
- 方法：RED（14 个 Stage 3 测试）→ L1/L4 registry versionization → GREEN
  subset → L2 run intent versionization → GREEN subset → L3 consumer
  resolution → 全量 GREEN → Phase 9 regression → 全量 suite
- 结论：`PHASE_10_3_STAGE3 = PASS_WITH_FINDINGS`；
  Review Fix 后 `PHASE_10_3_STAGE3_REVIEW_FIX = PASS`

## 交付物

| 文件 | 角色 |
|---|---|
| `pilot/registry.py` | L1：canonical version entries `family/<name>/versions/<v>.json`（write-once）；L4：消费 frozen deterministic `capability_id`，已有 legacy anchor 复用它；`discover_version()` |
| `pilot/runtime_adoption_guard.py` | L2：`adoption_store["run_requests"][capability_id\|candidate_version]`；`load_trusted_run_request(version_key)`；legacy `run_request` 保留为 Phase 9 读者镜像 |
| `pilot/managed_runtime.py` | L3：`create_version` / `DockerRuntime.start` 按 version key 解析 Run Intent；`_version(agent_id, version_id)` agent 作用域；`create_deployment` 放开每 Agent 单 Deployment 限制；`revoke_version(agent_id=...)` |
| `pilot/harness.py` | L3：canonical 路径经 `discover_version` + version-scoped run intent；single-agent multi-version store 禁止全局 current intent |
| `docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage3.py` | Stage 3 验收：14 tests（生产发布链 / 共存 / upgrade / rollback / revoke / adversarial A-H / harness） |
| `docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage1.py` | 1 行：`test_legacy_registry_entry_requires_migration` 指向 canonical version entry |
| `docs/archaeology/unified-runtime/phase9b1/test_legacy_downgrade_closure.py` | 1 行：`entry_path()` 指向 canonical version entry（locator 迁移必需） |

## RED（修改 production 前）

```text
test_phase10_3_stage3.py: 13 failed, 1 passed
```

预期 RED 全部复现：

```text
promote(v2)             -> ENTRY_BINDING_CONFLICT（L1）
v2 覆盖 v1 run intent   -> store["run_request"] 单 key（L2）
Deployment(v2)          -> 无 version-specific resolution（L3）
capability_id(v1) != v2 -> registry mint（L4）
```

## Review Fix RED（修改 production 前）

```text
test_phase10_3_stage3.py: 7 failed, 16 passed
```

Review 新增 9 个测试（A-I），RED 对应三个真实 P2：

```text
A v1 + B v1                     -> VERSION_CONFLICT（跨 Agent 版本号冲突）
revoke(A, v1)                   -> A/B 两个 Deployment 都被 REVOKED
legacy anchor removed 后 promote v2 -> capability_id 漂移
```

## Review Fix — Multi-Agent Scoping

### Finding 1 — create_version version-idempotency is agent-scoped

`pilot/managed_runtime.py` 的 `create_version()` 幂等检查从
`_latest(versions.jsonl, "version_id", version_id)`（全局 version_id）
改为 `_latest_version(state_root, event["agent_id"], version_id)`。

- same agent + same version + same content → idempotent，不追加重复事件；
- same agent + same version + different content → `VERSION_CONFLICT`；
- different agent + same version number → ALLOW。

### Finding 2 — revoke propagation is agent-scoped

`revoke_version()` 的 deployment 传播循环从只按 `version_id` 过滤，改为按
`dep["agent_id"] == version["agent_id"]` 且 `dep["version_id"] == version_id`
过滤，并复用已经解析出的 agent-scoped version 记录。

- `revoke(A, v1)` → A/v1 deployment = REVOKED，B/v1 deployment 不变；
- B/v1 仍可 RUNNING（`revoke(A,v1) != revoke(B,v1)`）。

### Finding 3 — legacy-anchor removal no longer causes capability_id drift

`pilot/registry.py` 的 canonical `promote()` capability_id 解析顺序改为：

1. 已存在的 canonical `family/<name>/versions/<v>.json` entry（复用其中
   已确定的 capability_id）；
2. legacy anchor `family/<name>.json`；
3. deterministic derivation。

同一个 Agent 一旦已有 canonical version entry，后续版本（legacy anchor 被
删除后）仍复用同一 capability_id，不再 fallback 到 derivation；canonical v2
不会反向回退到 legacy。

## Review Fix Tests

| Test | 场景 | 结果 |
|---|---|---|
| A | A v1 + B v1 同时发布 | ALLOW |
| B | A v1 + A v1 same content | idempotent，无重复语义版本 |
| C | A v1 + A v1 different content | `VERSION_CONFLICT` |
| D | `F+/cap-x/versions/v1.json` + `F+/cap-b/versions/v1.json` 共存 | PASS |
| E | revoke(A, v1)，A/v1 + B/v1 两个 Deployment | A=REVOKED，B 不变 |
| F | revoke(A, v1) 后 B/v1 reconcile | RUNNING（HEALTHY） |
| G | legacy anchor 删除后 promote(A v2) | capability_id 稳定 |
| H | legacy anchor 删除后 upgrade(A v1 -> A v2) | 无 `AGENT_VERSION_MISMATCH` |
| I | A v1 / A v2 / B v1 最终身份 | X, X, Y，X != Y |

## L1 — Registry Version Locator

```text
registry/<family>/<name>.json           legacy 单 entry（保留，只读兼容）
registry/<family>/<name>/versions/v1.json
registry/<family>/<name>/versions/v2.json
```

- canonical `promote()` 按 `candidate_version` 写独立 write-once entry；
- 同一 version 不同 binding 仍 `ENTRY_BINDING_CONFLICT`；
- `discover()` 保留 legacy 语义；新增 `discover_version()`；
- canonical 路径只消费 `discover_version()`，不 fallback legacy 单 entry。

## L4 — Stable Capability ID

```text
capability_id(v1) == capability_id(v2)
```

- canonical `promote()` 不再 mint `cap-<uuid>`，改用
  `frozen.record.capability_id`（`capability_id_derivation(namespace, name)`）；
- 若 `family/<name>.json` legacy anchor 已存在，复用其 `capability_id`
  （既有 Agent 身份迁移规则）；
- `candidate_id` 仍是每次发布不同的 Candidate 身份，不再承担 Agent 身份。

## L2 — Run Intent Map

```text
adoption_store["run_requests"] = {
  "<capability_id>|v1": RunIntent(v1),
  "<capability_id>|v2": RunIntent(v2),
}
```

- `mark_promoted()` 按 version key 写入独立记录；同 key 不同 binding →
  `RUN_REQUEST_MISMATCH`；
- `load_trusted_run_request(version_key)` 只读对应记录，缺失 →
  `MISSING_RUN_REQUEST`；
- `run_requests` 在 `adoption_store.json` 内，自动被同一个 trust anchor 的
  `store_digest` 覆盖；未新增 trust root。

## L3 — Consumer Version Resolution

```text
Deployment -> version_id -> AgentVersion -> RunIntent(version) -> E(D)
    -> verify_frozen -> verify_at_mount -> Runtime
```

- `managed_runtime._version(agent_id, version_id)`：`v1` 不再跨 Agent 混淆；
- `create_version`：用 entry 的 version key 解析 Run Intent；
- `DockerRuntime.start`：按 instance 对应 Version 的
  `(agent_id, candidate_version)` 解析 Run Intent，`expected_identity` 绑定
  该版本，mount source 固定为该版本 E(D)；
- `harness.phase_future("b3")`：single-agent multi-version store 必须由
  b3_entry 的 `capability_id + candidate_version` 显式选择版本；缺失或
  无 cache 时 `MISSING_RUN_REQUEST` fail-closed；
- multi-agent rehearsal store 保留 legacy alias 语义（Phase 9-B.5 回归）。

## Version Coexistence

```text
v1 authority != v2 authority       PASS
v1 run intent  != v2 run intent    PASS
v1 snapshot    != v2 snapshot      PASS
v1 entry 不被 v2 覆盖              PASS
v2 entry 不被 v1 覆盖              PASS
```

## Production-Reachable Proof

```text
seed_version()
    = state-machine fixture only
create_version() -> promote() -> authority -> version-scoped run intent
    -> snapshot E(D) -> deployment -> reconcile
    = production proof
```

Stage 3 测试全部走真实 publish 链：

```text
v1 publish = ALLOW
v2 publish = ALLOW
v1 + v2 coexist = YES
```

## Upgrade / Rollback / Revoke

- `upgrade(v1 -> v2)`：STOP v1（docker kill 经 fake proc）→ START v2，
  新 instance 绑定 `RunIntent(v2)` + `E(D2)`，mount source 为 v2 snapshot；
- `rollback(v2 -> v1)`：STOP v2 → START v1，mount source 为 v1 snapshot；
- `revoke(v2)`：v2 authority REVOKED + versions.jsonl REVOKED + 引用
  deployment REVOKED；v1 保持 ACTIVE，新 Deployment(v1) reconcile ALLOW，
  v2 start REJECT / upgrade to v2 `VERSION_REVOKED`；
- 两个 Deployment 可 domain 共存（设计 §15）；多实例同时 RUNNING 仍为
  Non-Goal，测试只验证 STOPPED 共存。

## Adversarial Tests

| # | 场景 | 结果 |
|---|---|---|
| A | Deployment=v2，RunIntent=v1 | REJECT（`CANDIDATE_VERSION_MISMATCH`） |
| B | Deployment=v1，RunIntent=v2 | REJECT（`CANDIDATE_VERSION_MISMATCH`） |
| C | v2 RunIntent missing | REJECT（`MISSING_RUN_REQUEST`） |
| D | v2 Authority missing | REJECT（`UNISSUED_AUTHORITY`） |
| E | v2 Snapshot missing | REJECT（`FROZEN_CANDIDATE_INCOMPLETE`） |
| F | v2 Snapshot digest mismatch | REJECT（`ARTIFACT_DIGEST_MISMATCH`） |
| G | revoke(v2)，Deployment=v1 | ALLOW |
| H | revoke(v2)，Deployment=v2 | REJECT（`VERSION_REVOKED` / REJECT） |

## Phase 9 Regression

```text
phase9b1 / phase9b3 / phase9b5 / phase9d3: 96 passed, 6 subtests passed
```

Phase 9-B.5 的 legacy `run_request` 单 key 语义被保留为只读镜像：
`mark_promoted` 仍同步最新 intent 到 `store["run_request"]`，供旧读者与
Phase 9 测试使用；canonical version-scoped 消费者从不读取该字段。

## Full Suite

```text
pytest -q: 920 passed, 11 skipped, 19 subtests passed
```

```text
passed   = 920
skipped  = 11
subtests = 19
```

## Live Runtime

```text
LIVE_RUNTIME = UNAVAILABLE
```

`docker info` 实测：

```text
permission denied while trying to connect to the docker API at
unix:///Users/david/.docker/run/docker.sock
```

未伪造 Docker live PASS。`DockerRuntime.start` 的完整信任解析链
（discover_version → version-scoped run intent → verify_at_mount →
mount source）通过 fake `subprocess.run` 在 domain 层真实执行。

## Findings

1. **legacy alias 保留为最新 intent 镜像**：Design Freeze §20 写“canonical
   新路径永不写入 `run_request`”，但 Phase 9-B.5 的既有 adversarial 测试
   依赖旧单 key 覆盖语义。为保持 Phase 9 回归字节级 PASS，`mark_promoted`
   继续镜像最新 intent 到 `store["run_request"]`；canonical v1/v2 的全部
   消费路径只读 `run_requests[version_key]`，镜像字段不可达。若后续产品
   删除旧读者，可移除该镜像。
2. **harness 多版本解析边界**：`phase_future("b3")` 是单参数 B3 rehearsal
   路径，没有 deployment/version 参数。single-agent multi-version store
   由 b3_entry 显式指定版本；multi-agent rehearsal store（Phase 9-B.5
   夹具）继续走 legacy alias 语义。
3. **Phase 9-B.1 测试 locator 适配**：`entry_path()` 从
   `family/<name>.json` 改为 `family/<name>/versions/v1.json`（1 行），
   是 canonical locator 迁移的必要测试更新，未改变任何断言语义。
4. **`create_deployment` 放开每 Agent 单 Deployment**：按 Design Freeze
   §15 显式修订 10.1 §6；multi-instance 调度仍 Non-Goal。

## Scope Audit

```text
git diff --name-only:
  pilot/registry.py
  pilot/runtime_adoption_guard.py
  pilot/managed_runtime.py
  pilot/harness.py
  docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage3.py (new)
  docs/archaeology/unified-runtime/phase10_3/test_phase10_3_stage1.py
  docs/archaeology/unified-runtime/phase9b1/test_legacy_downgrade_closure.py
  docs/archaeology/unified-runtime/phase10_3/08-multi-version-implementation-report.md (new)
```

```text
git diff --check: 空
```

未修改 Trust Root schema、未新增数据库、未改 Sandbox / Kubernetes /
Process Supervisor。

## Final Verdict

```text
PHASE_10_3_STAGE3 = PASS_WITH_FINDINGS
PHASE_10_3_STAGE3_REVIEW_FIX = PASS

MULTI_VERSION_PUBLISH = CLOSED
REGISTRY_VERSIONING = CLOSED
VERSION_IDENTITY = CLOSED
RUN_INTENT_VERSIONING = CLOSED
CONSUMER_VERSION_RESOLUTION = CLOSED
STABLE_CAPABILITY_ID = CLOSED
MULTI_AGENT_VERSION_SCOPING = CLOSED
CROSS_AGENT_REVOKE_ISOLATION = CLOSED
CAPABILITY_ID_STABILITY = CLOSED

V1_V2_COEXIST = PASS
UPGRADE_PRODUCTION_REACHABLE = PASS
ROLLBACK_PRODUCTION_REACHABLE = PASS
REVOKE_VERSION_SCOPED = PASS
A_V1_A_V2_IDENTITY_STABLE = PASS
A_V1_B_V1_ISOLATED = PASS

PHASE_9_REGRESSION = PASS
FULL_SUITE = 929 passed, 11 skipped, 19 subtests passed
LIVE_RUNTIME = UNAVAILABLE

LEGACY_COMPATIBILITY = PASS
```
