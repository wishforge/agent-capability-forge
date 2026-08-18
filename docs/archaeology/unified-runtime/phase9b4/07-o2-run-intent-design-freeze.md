# Phase 9-B.4.2 Design Freeze — O2 Run Intent Trust

- 日期：2026-08-18
- 基线：`ac0f0c0`（Phase 9-B.4.1 确认 O2 = REAL GAP）
- 模式：Design Freeze；未修改 production code、未增加 production tests、未 commit
- 输入：`phase9b4/01..06,99` + `phase9b2/11-phase9b2-design-freeze.md`
  + `pilot/harness.py` / `pilot/runtime_adoption_guard.py` /
  `pilot/adoption_authority_producer.py` / `pilot/adoption_authority.py` /
  `pilot/registry.py` / `src/forge/capabilityizer.py`
- 证据优先级：当前源码事实 > archaeology 报告；本文行号以基线代码为准

---

## 1. Scope

冻结 O2 的安全设计，回答唯一核心问题：

> 这一次 Runtime 到底被批准运行哪个 Candidate？

范围严格限定为：

```text
已授权 Candidate 之间的 Run Intent Drift
（b3_entry whole swap / registry + b3_entry 一致改写 / cache 删除 / stale）
```

本阶段只做设计冻结：

- 不实现、不修改生产代码
- 不新增数据库 / 服务 / 协议 / 外部依赖
- 不引入 Sigstore / OCI / Kubernetes Policy Controller / 完整 in-toto layout
- 不解决 O1（verify -> kernel bind mount 的 OS 级 TOCTOU）

## 2. Problem Statement

现状（probe 实测，见 03 号报告 P1 / P10b）：

```text
Authority = Candidate A
b3_entry  = Candidate B（name + 四元组一致替换）
        ↓
ALLOW B
        ↓
Runtime mounts B
```

根因不是单字段篡改（R1 已闭合），而是：

```text
b3_entry.name 决定 discover 目标（harness.py:698-699）
预期四元组与"它自己选中的 entry 的 adopt report"自指比对
  （runtime_adoption_guard.py:305-323, 448-473）
没有任何外部锚点记录"操作者/权威原本打算运行 A"
```

系统锚定了 `store_digest` / `authority_manifest_digest` /
`revocation_manifest_digest`（adoption_authority.py:166-170），
但 b3_entry 不在锚定范围（03 号报告 anchor 对照：改写 b3_entry -> `[]`）。
因此 b3_entry 被一致替换成另一个已授权候选时，整条链仍然自洽并 ALLOW。

最小不变量（06 号报告）：

```text
运行意图（run request）必须与它声明的四元组共享同一个 trust root；
任何把 run request 从 A 改成 B 的操作必须可检测（REJECT）或不可能（锚定/不可变）。
```

## 3. Current Trust Model

```text
Trust Root = 外部 integrity anchor（sealed digest 根）
  ↓ 仅覆盖 store_digest / authority_manifest_digest / revocation_manifest_digest
Anchored State = adoption_store.json + authorities/ ledger
  ↓ Authority（store 记录 == authorities/*.json 不可变记录，adopt 全链重验）
Registry entry（未锚定，但 adopt 重验 BINDING_KEYS + digest）
  ↓ entry.artifact_dir 决定 artifact 路径
Frozen Candidate（seal_digest 必须 == authority.seal_digest，字节重算）
  ↓
b3_entry.json（未锚定；name 决定 discover 目标；四元组自指比对）
  ↓
Runtime（phase_future("b3") -> docker_launch）
```

代码事实：

| 环节 | 文件:行 | 行为 |
|---|---|---|
| anchor 只覆盖 3 个 digest | adoption_authority.py:123-177 | `actual = {store_digest, authority_manifest_digest, revocation_manifest_digest}` |
| b3_entry 写入 | harness.py:636-644 | promotion 后写六字段 JSON（v2 格式） |
| b3_entry 读取 + discover | harness.py:698-699 | `json.loads` + `registry.discover(name)` |
| 四元组自指比对 | runtime_adoption_guard.py:305-323 | `identity_violations(expected_identity, report)` |
| adopt 全链重验 | runtime_adoption_guard.py:326-445 | store/ledger/frozen/eval/digest |
| verify_at_mount | runtime_adoption_guard.py:448-473 | 再 adopt + expected identity/digest + mount_source |
| mount 唯一来源 | harness.py:768-773 | `verified_artifact_dir` 后 docker_launch |

## 4. Run Intent Definition

### 4.1 定义

```text
Run Intent = 一条锚定在 adoption_store 内的记录：

{
  "name": "csv-clean-statistical-report",     # locator（不是安全身份）
  "capability_id": "cap-...",                  # 运行记录标签（inert）
  "candidate_id": "cand-...",                  # 身份分量
  "candidate_version": "v1",                   # 身份分量
  "artifact_digest": "sha256:...",             # 内容身份
  "seal_digest": "sha256:...",                 # 最强内容身份
  "promotion_decision_id": "dec-...",          # 绑定 authority/decision
  "created_at": "2026-08-18T..."
}
```

它回答：*此次运行经过批准，要运行哪个 Candidate*。

### 4.2 为什么只放这些字段

安全决策真正需要的字段只有四个身份分量 + promotion 绑定：

- `candidate_id` / `candidate_version`：身份连续性（R1 已用）
- `artifact_digest` / `seal_digest`：内容身份（R1 已用）
- `promotion_decision_id`：把 intent 绑到唯一 authority/decision，防止
  "同 decision 下 A->B 覆盖"

`name` / `capability_id` 是 locator / 记录标签，保留是为了兼容现有
run record 与 registry 索引；它们不参与信任决策（03 号报告 P4/P12：
capability_id 为 inert field，注入 verified_artifact_dir 被忽略）。

**不加入**：

```text
task / execution context     -> oracle 校验的是输出，不是 artifact；任务不改变"运行谁"
request identity / phase      -> 当前只有一个 B3 future-run 语义，无第二 selector
attempt / runtime target      -> 未来若出现多 intent 调度再立项；现在加入是猜测性字段
```

原则：Run Intent 中只放安全决策真正需要的字段。

## 5. Option A — Anchored Run Request in adoption_store

模型：

```text
Run Request
    ↓
adoption_store（锚定：store_digest）
    ↓
trusted Run Intent
    ↓
phase_future 解析 expected identity
    ↓
registry discover（locator）
    ↓
adopt / verify_at_mount
    ↓
Runtime
```

b3_entry 的角色：

```text
cache / locator / derived execution metadata
```

不再拥有独立安全决策权。

### 5.1 落点

`store["run_request"]` 单条 active 记录（当前 pilot 同一时刻只有一个 B3
capability，与 b3_entry.json 单文件语义一致）。写入发生在 canonical
promotion 路径：`phase_b3_build` 在 `mark_promoted` 之后（或作为
`mark_promoted` 的同一 store 事务的一部分）写入，并复用现有
`write_trust_anchor` 刷新 anchor。

代码事实支持：

- store 已是锚定对象：`store_digest = _sha256(_canonical(store))`
  （adoption_authority.py:217）；任何新字段自动进入 store_digest
- store 已承载 authority/decision/lifecycle/revocations
  （adoption_authority_producer.py:252-260）
- promotion 写 store 后刷新 anchor 的调用点已存在
  （runtime_adoption_guard.py:517-522；adoption_authority_producer.py:330-337）
- anchor schema 不需要变更（`integrity_anchor_v1`，adoption_authority.py:39）

### 5.2 phase_future 读取路径

```text
1. load_store + integrity_anchor_violations     （store 或 anchor 被改 -> 先失败）
2. 读 store["run_request"]                        （source of truth）
3. 读 b3_entry.json：
     missing       -> cache miss，从 run_request 重建（不阻断）
     equal         -> 继续
     differ        -> REJECT（RUN_REQUEST_CACHE_MISMATCH）
4. name = run_request.name（不来自 b3_entry 的安全决策）
5. entry = registry.discover(name)
6. adopt(entry, artifact_dir)
7. verify_at_mount(
       expected_identity=run_request 四元组,
       expected_digest=run_request.artifact_digest,
       mount_source=artifact_dir)
8. docker_launch(verified_artifact_dir)
```

## 6. Option B — Anchor b3_entry Digest

模型：

```text
Trust Root
   ↓ 新增 b3_entry_digest
b3_entry.json
    ↓ digest
anchor verification
    ↓
phase_future 继续以 b3_entry 为 run request
```

即：把 b3_entry 的字节 digest 加入 trust anchor，seal 后任何改写触发
`INTEGRITY_STORE_CORRUPTED`。

### 6.1 代价

- anchor schema 必须从 `integrity_anchor_v1` 升级（新增字段 + 校验 + 写入 +
  seal/refresh 流程），存量 sealed store 需要重新 seal
- `integrity_anchor_violations(store, registry_root)` 只接收 registry_root
  （adoption_authority.py:123,129-130）；b3_entry 位于 harness state 目录，
  必须新增路径配置/参数
- harness 写入 b3_entry（harness.py:636-644）后必须追加调用
  `write_trust_anchor` —— harness 成为 anchor 写者，新增耦合
- b3_entry 每次 build 重写（harness.py:561-568,636-644），
  schema/内容变化会频繁造成 anchor churn
- b3_entry 携带 inert 字段（capability_id），锚定它们只会扩大 churn 面

### 6.2 语义问题

Option B 没有改变"谁拥有 Run Intent"：b3_entry 仍然是 run request 的来源，
只是变得可检测篡改。它把 Runtime cache 升级成了新的 security authority，
但 authority/decision/store 都不拥有 intent，provenance 被拆成两个锚定点。

## 7. A/B Code-Level Comparison

| 维度 | Option A | Option B |
|---|---|---|
| Trust owner | adoption_store（已锚定） | b3_entry.json（新增锚定） |
| Write authority | canonical promotion 路径（phase_b3_build -> mark_promoted 同一 store 写入 + write_trust_anchor，runtime_adoption_guard.py:517-522） | harness 写 b3_entry 后追加写 anchor（harness.py:636-644；新调用点） |
| Read authority | phase_future 读 anchored store；adopt 已先验 anchor（runtime_adoption_guard.py:333-345） | phase_future 继续读 b3_entry（harness.py:698）；读取点本身无 anchor 校验 |
| Mutability | 每个 promotion 一个不可变 record；新 promotion = 新 authority + anchor 刷新；同 decision 内 A->B 被 merge-conflict 拒绝 | b3_entry 每次 build 重写；本质是可变文件 + anchor churn |
| Runtime coupling | 低：runtime 已加载 store，只换 expected identity 来源 | 高：anchor 需要知道 harness state 路径，新参数/配置 |
| Existing code reuse | 复用 store_digest + write_trust_anchor + mark_promoted 写入点；anchor schema 不变 | 复用 anchor 机制但必须扩展 schema（adoption_authority.py:39,123-177,180-243） |
| Anchor surface | 不新增 digest 字段（run request 进 store_digest，adoption_authority.py:217） | 新增 b3_entry_digest 字段 + anchor v2 |
| Failure semantics | run request 被改 -> INTEGRITY_STORE_CORRUPTED（现有机制）；b3_entry 不一致 -> RUN_REQUEST_CACHE_MISMATCH | b3_entry 被改 -> INTEGRITY_STORE_CORRUPTED（仅 seal 后） |
| Recovery semantics | b3_entry 缺失 = cache miss，从 store 重建；store 是 source of truth | b3_entry 缺失 = intent 丢失（当前 FileNotFoundError），无重建来源 |
| Legacy compatibility | 只在 canonical 分支启用；legacy 分支已有 `expected_identity=None` 路径（harness.py:765-766，runtime_adoption_guard.py:428-430） | anchor v2 影响所有 sealed store；b3_entry 校验会波及 legacy，除非再加分支 |
| O1 interaction | 不改变 verify->mount 窗口；anchored expected identity 为未来不可变引用提供前置条件 | 同样不改变窗口；intent 绑定在可变 cache 上，对未来无帮助 |
| Future provenance | run request 与 authority/decision 同文件、同 anchor，单一 provenance 链 | intent 与 authority 分离，需要两处锚定 |
| Complexity | 最小：一个 store 字段 + phase_future 读路径 + cache 比对 | 中等：anchor v2 + 路径配置 + 写入点耦合 + churn 处理 |
| Attack surface | 改 b3_entry / registry 都不能改变执行候选；同写者改 store + refresh anchor 仍属既有边界（GAP-2/3） | seal 后改 b3_entry 被检测；但 harness 本身是写者，且 registry + b3_entry 一致改写仍无 store 对照 |

### 7.1 Evidence Ledger

| # | Finding | Code fact / RED | Source | Principle | Candidates | Verdict |
|---|---|---|---|---|---|---|
| 1 | b3_entry whole swap -> ALLOW B | probe P1（03 号报告）；harness.py:698-699 以 b3_entry.name discover；762-767 四元组自指比对 | 本地 probe + 源码 | 运行意图必须与声明身份共享 trust root | A / B | A |
| 2 | b3_entry 不在 anchor 内 | adoption_authority.py:166-170 只算 3 个 digest；03 号报告 anchor 对照返回 `[]` | 本地 probe + 源码 | 安全决策状态必须可锚定或不可变 | A / B | A |
| 3 | store 已锚定且已有写入点 | adoption_authority.py:217；runtime_adoption_guard.py:517-522 | 源码 | 复用现有 trust root，零 schema 变更 | A | A |
| 4 | b3_entry 含 transient/inert 字段 | harness.py:638-643 写 capability_id；03 号报告 P4/P12 为 inert | 源码 + probe | 不锚定非安全状态，避免 churn | B 的否定理由 | B REJECT |

## 8. Decision

```text
OPTION_A = ADOPT
OPTION_B = REJECT
```

理由（代码级）：

1. Option A 零 anchor schema 变更：run request 进入已锚定的 `store_digest`
   （adoption_authority.py:217），现有 `write_trust_anchor` 原样复用。
2. Option A 让 Run Intent 与 authority/decision/lifecycle 同文件、同写者、
   同 anchor，单一 provenance 链；Option B 把 intent 留在 harness 缓存里，
   只是给缓存加锁。
3. Option A 的 recovery 语义完整：b3_entry 删除 = cache miss = 从 store 重建；
   Option B 的 b3_entry 删除 = intent 丢失。
4. Option A 保持 legacy 兼容分支天然隔离（canonical 才启用）；
   Option B 的 anchor v2 影响所有 sealed store。

## 9. Run Intent Owner

```text
RUN_INTENT_OWNER = Adoption Store（anchored）
```

回答"谁可以写 / 改 / 删 / 验 / Runtime 信谁"：

| 操作 | 允许者 | 代码事实 |
|---|---|---|
| 写 | 唯一安全写路径：canonical promotion（issue -> promote -> mark_promoted -> record run request） | runtime_adoption_guard.py:517-522；adoption_authority_producer.py:330-337 |
| 改 | 不允许原地改；只能由新 promotion（新 decision/authority）替换 active record | producer merge-conflict 模式 adoption_authority_producer.py:267-275 |
| 删 | 不允许（store 内记录）；b3_entry 缓存可删 = cache miss | 设计冻结 |
| 验 | Runtime 只信 anchored store 中的 run request | adopt 先验 anchor（runtime_adoption_guard.py:333-345） |
| Runtime 信谁 | 唯一：anchored Run Intent；registry 只是 locator，b3_entry 只是 cache | 见 §13 |

多头决策被消除：

```text
Authority says A  -> 与 run request 同在 anchored store，冲突 = INTEGRITY_STORE_CORRUPTED
b3_entry says B   -> cache 不一致 = REJECT；即使忽略，也不影响执行目标
Registry says A   -> 只决定 discover 目标；最终身份仍与 run request 比对
Runtime chooses   -> 只能是 run request 声明的 A
```

## 10. Single-Writer Rule

```text
Issue / Promote
    ↓
Create Run Intent（与 lifecycle PROMOTED 同一 store 事务）
    ↓
Anchor（write_trust_anchor）
    ↓
Runtime 只读
```

规则：

- Run Intent 只有一个写者：canonical promotion 路径（`phase_b3_build`）。
- Registry、guard、producer、b3_entry 都不是 run request 写者。
- 同 decision 内重复写入必须 idempotent；内容不同 -> conflict 错误
  （对齐 producer 的 `_merge_*` 模式，adoption_authority_producer.py:267-275），
  不存在 `last writer wins`。
- 不同 decision（新 promotion，`--force`）产生新 authority + 新 run request，
  是合法的 intent 版本替换，不是同一 run identity 的 A->B 覆盖。
- 并发 harness 进程：与现有 flat JSON store 相同边界，无 CAS
  （registry.py:214-215 已声明的 ponytail 上限）；本阶段不解决，
  不宣称并发安全。

Race semantics（Run Intent 层面）：

```text
同一 decision 内：create-if-absent；冲突即失败，绝不覆盖
跨 decision：新的完整 promotion 才可替换 active record；替换与 anchor
             refresh 在同一次 store 写入中完成
```

## 11. Immutability Model

```text
RUN_INTENT_IMMUTABILITY = per-record immutable；active record 仅由新 promotion 替换
```

- 每个 `promotion_decision_id` 对应一条不可变 run request 记录。
- 同 decision 内 overwrite A -> B：REJECT（merge-conflict）。
- 新 intent = 新 decision + 新 authority + 新 run request + anchor refresh；
  旧 authority/decision 仍在 store 中，provenance 可追溯。
- anchor sealed 后任何 store 内 run request 改写（未同步刷新 anchor）
  -> `INTEGRITY_STORE_CORRUPTED`。
- 未 seal 的 store：与现有 store 同一 trust boundary（GAP-2/3 范围），
  本设计不新增承诺。

## 12. b3_entry Role

```text
B3_ENTRY_ROLE = DERIVED_EXECUTION_METADATA（cache / locator，无安全权威）
```

角色拆分：

| 主角色 | 说明 |
|---|---|
| CACHE | 从 anchored run request 派生；缺失可重建 |
| LOCATOR（派生） | 与 run request 一致时，其 `name` 是 anchored name 的副本，供工具/日志读取；运行时 discover 的 name 来自 anchored record |
| DERIVED_EXECUTION_STATE | 记录最近一次 promotion 的快照，供工具/日志读取 |

不是：

```text
SECURITY_AUTHORITY   （authority 在 store + ledger）
SIGNED_ATTESTATION   （无签名；以后也不应签名它）
RUN_INTENT           （run intent 在 anchored store）
```

强制回答：

> b3_entry 被替换成 B 后，为什么 Runtime 不应该相信它？

因为 Runtime 的 expected identity 来自 anchored `store["run_request"]`，
不是来自 b3_entry。b3_entry 只是派生表示：

```text
Trusted Run Intent = source of truth
b3_entry           = derived cache
```

删除 b3_entry 不等于 Run Intent 丢失，而是 cache miss -> rebuild。

## 13. Resolution Algorithm

### 13.1 Canonical 路径（冻结）

```text
Run Request（operator/pipeline）
    ↓
1. load_store + integrity_anchor_violations          # 失败 -> INTEGRITY_STORE_CORRUPTED
    ↓
2. 读 anchored run_request（source of truth）
    ↓
3. b3_entry cache：
      missing -> 重建（cache miss）
      equal   -> 继续
      differ  -> REJECT RUN_REQUEST_CACHE_MISMATCH
    ↓
4. name = run_request.name（不是 b3_entry 的安全决策）
    ↓
5. entry = registry.discover(name)                    # locator only
    ↓
6. adopt(entry, artifact_dir)                         # authority/store/frozen/eval/digest 全链
    ↓
7. verify_at_mount(
       expected_identity = run_request 四元组,
       expected_digest   = run_request.artifact_digest,
       mount_source      = artifact_dir)
    ↓
8. docker_launch(verified_artifact_dir)               # 唯一 mount 来源
```

b3_entry 参与位置：**只在步骤 3 作为 cache 一致性检查**；
执行目标的来源永远是步骤 2 的 anchored record。

### 13.2 Legacy 路径（保持现状）

```text
b3_entry（v1/v2）读 name
    ↓
registry.discover(name)
    ↓
adopt（legacy dir digest 路径，runtime_adoption_guard.py:428-430）
    ↓
verify_at_mount(expected_identity=None,
                expected_digest=b3_entry 有则传)
    ↓
docker_launch
```

## 14. Adversarial Cases

| # | 场景 | 判定 | 机制 |
|---|---|---|---|
| A | whole b3_entry swap：intent=A，b3_entry=B | **REJECT** | b3_entry != anchored run_request -> `RUN_REQUEST_CACHE_MISMATCH`；即使删除 cache，name 也来自 anchored record，B 不会被 discover |
| B | Registry -> B 且 b3_entry -> B | **REJECT** | cache mismatch 先拒绝；即使绕过，adopt(B) report 的 identity != run_request A -> `CANDIDATE_ID_MISMATCH` / `ARTIFACT_DIGEST_MISMATCH` |
| C | b3_entry deleted | **REBUILD** | cache miss，从 anchored run_request 重建；执行目标不变（ALLOW A） |
| D | b3_entry stale：intent=A v2，b3=A v1 | **REJECT** | 与 run_request 不一致 -> `RUN_REQUEST_CACHE_MISMATCH`；operator 删除 cache 或重新 build 后重建 |
| E | Registry=A，b3_entry=B，intent=A | **REJECT** | cache mismatch（E 与 A 同机制） |
| F | b3_entry 在 anchor sealed 后改变 | **REJECT** | cache mismatch；run_request 不变，B 不可能执行 |

选择说明：

- **missing -> rebuild**：缺失是 cache miss，不是篡改证据，重建不改变执行目标。
- **present-but-different -> REJECT**：存在的缓存与 source of truth 不一致
  是篡改/漂移证据；静默重写会隐藏证据并制造第二个写者语义。
  恢复方式：删除缓存（-> rebuild）或重新运行 phase_b3_build。

## 15. Legacy Compatibility

```text
canonical 路径（entry.artifact_identity == CANONICAL_ARTIFACT_IDENTITY_V1）
  -> Option A：anchored Run Intent + b3_entry cache
legacy 路径（历史 Phase 8 entry，如当前 pilot/state 的 adoption=null 形态）
  -> 保持现状：b3_entry locator + legacy digest + expected_identity=None
```

代码事实：

- canonical 判别符：capabilityizer.py:35；
- legacy/canonical 分支已存在于 adopt（runtime_adoption_guard.py:408-430）
  与 harness 的 expected_identity 选择（harness.py:765-766）。
- 现场 `pilot/state` 目前是 legacy 形态（b3_entry v1、entry.adoption=null、
  无 adoption_store.json）；本设计不要求迁移它。

信任模型差异：

| | canonical | legacy |
|---|---|---|
| Run Intent | anchored store record | 无（b3_entry 即运行请求，维持历史语义） |
| 校验 | 四元组强制 | digest 重算 + 既有 binding |
| 变更 | 本设计冻结 | 不动（Phase 9-B.2 边界） |

## 16. O1 Boundary

```text
O1 = OPEN（verify_at_mount 返回与内核 bind mount 之间的 OS 级竞态）
```

- 本设计不改变 verify -> docker_launch 的调用形态
  （runtime_adoption_guard.py:448-473；harness.py:768-773）。
- Option A 对未来 O1 的影响是**正向前置条件**：Runtime 已经拥有
  anchored expected identity（含 artifact_digest），未来 O1 方案（如 R4
  digest 命名不可变快照）可以直接以 run_request.artifact_digest 为
  "不可变 artifact reference"，无需再引入新的意图来源。
- Option B 对未来 O1 没有额外帮助：intent 仍绑定在可变 cache 上。

## 17. Minimal Implementation Boundary

下一阶段（Phase 9-B.5）最小实现只允许：

```text
pilot/adoption_authority.py         （可选：record_run_request 小 helper；
                                      核心逻辑是 setdefault + write_trust_anchor 复用）
pilot/runtime_adoption_guard.py     （mark_promoted 或相邻 helper 写 run_request；
                                     仅在 canonical entry 分支）
pilot/harness.py                    （phase_b3_build 写 run_request；
                                     phase_future 读 anchored run_request +
                                     b3_entry cache 比对/重建）
```

约束：

```text
不新增数据库 / 服务 / 协议 / 外部依赖
不改 anchor schema（integrity_anchor_v1 保持）
不改 registry.promote / issue_authority 的既有写路径
不改 legacy 路径
capability_id 继续作为 inert field
```

Blast radius（实现时须 grep 全部调用点）：

```text
store["run_request"] 的写：phase_b3_build（唯一）
store["run_request"] 的读：phase_future("b3")（唯一）
受影响测试：phase9b3/test_candidate_identity_fail_closed.py、
           phase9b1/test_production_trust_chain.py（b3_entry 相关用例）
```

Rollback：删除 store 字段 + 恢复 phase_future 读取 b3_entry；无数据迁移、
无 anchor schema 变更，回滚面最小。

Confidence：

```text
O2 gap            = HIGH（probe P1/P10b 稳定复现）
Option A 可行性    = HIGH（结构性复用：store_digest 已锚定、
                          write_trust_anchor 调用点已存在、legacy 分支已隔离）
```

## 18. Acceptance Criteria

| # | 条件 | 失败码 / 证据 |
|---|---|---|
| AC1 | Trusted Run Intent = A，b3_entry = B -> MUST NOT run B | `RUN_REQUEST_CACHE_MISMATCH` |
| AC2 | b3_entry deleted -> Run Intent 不静默改变 | cache miss -> rebuild，runtime A |
| AC3 | Registry -> B + b3_entry -> B -> REJECT | cache mismatch / `CANDIDATE_ID_MISMATCH` |
| AC4 | anchor sealed 后改写 run request -> REJECT | `INTEGRITY_STORE_CORRUPTED` |
| AC5 | 合法 promotion 后 phase_future("b3") ALLOW A | 正向回归 |
| AC6 | 单字段篡改仍 REJECT | 既有 R1 四码保持 |
| AC7 | legacy 路径行为不变 | legacy 回归保持 |
| AC8 | capability_id 不参与决策 | inert 断言 |
| AC9 | 无新依赖 / 新服务 / anchor schema 不变 | 代码审查 |

证明链：

```text
Run Intent(A) == Adoption(A)
  <=> run_request 四元组 == adopt report 四元组（identity_violations）

Adoption(A) == Runtime(A)
  <=> verify_at_mount(mount_source=verified_artifact_dir) -> docker_launch
      （harness.py:768-773）

Run Intent 被改成 B
  => b3_entry cache mismatch REJECT，或 adopt identity mismatch REJECT
  => Runtime 不可能 mount B
```

## 19. Open Questions

```text
O1   verify_at_mount 与内核 bind mount 的 OS 竞态：仍 OPEN；
     Option A 提供 anchored expected identity 作为未来前置条件。

Q2   是否允许多个 active run requests（多 capability 并行 future）？
     当前冻结为单 active record；harness 支持多 promoted name 时再扩展。

Q3   task/phase/attempt 何时进入 Run Intent？
     当前无安全决策需要；出现多 intent 调度时重新评估。

Q4   anchor 未 seal 时 run request 的保护？
     与 store 相同：降级为同写者边界（GAP-2/3），本设计不新增承诺。

Q5   canonical 路径是否彻底删除 b3_entry？
     当前保留为 cache/legacy 兼容；若工具链不再需要，可在后续阶段移除。

Q6   legacy 路径最终处置（Phase 9-B.2 O4）：保留 / 弃用 / 迁移。
```

## 20. Final Verdict

```text
O2_DESIGN = READY

RUN_INTENT_OWNER = Adoption Store（anchored store["run_request"]）
RUN_INTENT_IMMUTABILITY = per-promotion immutable；
                         active record 仅由新 promotion（新 authority/anchor）替换
B3_ENTRY_ROLE = DERIVED_EXECUTION_METADATA（cache / locator，无安全权威）

OPTION_A = ADOPT
OPTION_B = REJECT

TRUST_CHAIN =
  Trust Root（外部 anchor）
    -> adoption_store（run_request + authority + decision + lifecycle，同一 store_digest）
    -> registry（locator，adopt 重验）
    -> frozen candidate（seal_digest 全等 + 字节重算）
    -> adopt / verify_at_mount（expected identity == run_request）
    -> Runtime（唯一 verified_artifact_dir mount）

IMPLEMENTATION_BOUNDARY =
  canonical 路径 only：
  harness.py（写/读 run_request + cache 比对重建）
  + runtime_adoption_guard.py / adoption_authority.py（record_run_request helper）
  不新增存储/服务/依赖；anchor schema 不变；legacy 路径不动。

O1 = OPEN

NEXT_PHASE = Phase 9-B.5：实现 Option A 最小集 + RED 回归测试
  （whole swap REJECT / deletion rebuild / cache mismatch REJECT /
   sealed 后 run request 改写 INTEGRITY_STORE_CORRUPTED / 正向 ALLOW）
```

本阶段结束条件确认：只新增本文件；未修改 production code、未增加
production tests、未 commit。
