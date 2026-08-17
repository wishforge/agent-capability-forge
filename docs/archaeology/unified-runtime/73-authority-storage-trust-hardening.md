# 73 — Authority Storage & Trust Hardening（Phase 8.3）

> 阶段：Phase 8.3（AdoptionAuthority 存储可信度 / write-once / revocation /
> issuer trust / TOCTOU；代码考古 + 最小 hardening design + offline proof）。
> 基线：72（Phase 8.2，RUNTIME_ADOPTION_GUARD_VALID_WITH_UNKNOWN）、71
> （Phase 8.1）、70（Phase 8）、69（Phase 7.6）、68 / 67 / 66（Phase 7.5 /
> 7.4.1 / 7.4）。
> 约束遵守：未修改 `pilot/` 生产代码；未接第二个 Runtime；未接 Cordis /
> Langfuse；未做 E.8；未做 production-wide rollout；未 commit / push；
> 只做 offline proof、storage semantics、trust boundary、TOCTOU proof。
> 本阶段只允许新增：本文件、`phase8.3/`（模型 + tests + current-gap repro）。

## 0. 执行摘要

Phase 8.2 结束时 Runtime 已 fail-closed，但剩余 UNKNOWN 全部集中在
“authority 这份凭证本身是否可信、是否可被改写、是否会在验证与执行之间被
替换”。本阶段回答这些问题，并给出最小 CAS / append-only / TrustedIssuer /
content-addressed artifact 设计（offline proof，不实现）。

代码考古结论（FACT）：

```text
adoption_store.json 是 flat JSON：
  - 任何对文件系统有写权限的进程都可以覆盖 / 删除 / 编辑它；
  - 两个写点（producer.issue_authority、guard.mark_promoted）都是
    读整文件 -> 内存改 -> os.replace 整文件，无锁、无 CAS、无 fsync；
  - 多进程并发 = last-writer-wins，后写者覆盖先写者；
  - Registry 接受“调用方构造的 authority”，不查 store["authorities"]；
  - Registry 不检查 authority.status == REVOKED/SUPERSEDED；
  - 删除 adoption_store.json 后重新 issue 会被当作全新 store；
  - Runtime digest 检查与 docker_launch 挂载之间仍有替换窗口。
```

最终判定：

```text
AUTHORITY_STORAGE_HARDENING_VALID_WITH_UNKNOWN
```

```text
production durability   FACT：flat JSON last-writer-wins / 无 CAS / 无 fsync
                         UNKNOWN：生产级持久化（JSONL/CAS 设计仅 offline
                         模型验证，未落地）。
issuer trust            FACT：authority_id 是确定性内容哈希，非密码学签名
                         INFERENCE：TrustedIssuer allowlist + issue 时注册
                         可关闭“任意调用方自己构造 authority”的应用层路径
                         （模型验证）；UNKNOWN：密码学信任锚。
TOCTOU protection       FACT：digest 检查与 mount 之间存在替换窗口（G4）
                         INFERENCE：content-addressed artifact + mount 前
                         recheck 关闭应用层窗口（模型验证）；UNKNOWN：
                         OS 级不可变性 / open-by-handle。
```

不是 `AUTHORITY_STORAGE_HARDENING_VALID`：设计只做了 offline proof，没有
落地到生产存储 / Runtime。
不是 `AUTHORITY_STORAGE_HARDENING_PARTIAL`：五个 UNKNOWN 都有完整、可机械
检查的最小设计，缺口是“落地层”，不是设计层（与 66/72 同一判据）。

---

## 1. Authority Store 可信度（考古）

### 1.1 谁可以写 authority？

```text
FACT  pilot/adoption_authority_producer.py:74,243-249
      issue_authority() 是 authorities 记录的唯一代码写点：
      内存合并 -> store["authorities"].append -> tmp + os.replace。
FACT  pilot/runtime_adoption_guard.py:290,329-332
      mark_promoted() 是 adoption_store.json 的第二个代码写点
      （lifecycle PROMOTABLE -> PROMOTED，原地改内存后整文件重写）。
FACT  pilot/harness.py:602,611
      pilot 唯一调用链：phase_b3_build -> issue_authority ->
      registry.promote -> mark_promoted。
FACT  任何对 registry_root 有写权限的进程 / 用户都可以直接写、删、改
      adoption_store.json；代码层没有任何权限检查。
```

### 1.2 谁可以覆盖 authority？是否 last-writer-wins？

```text
FACT  文件级：任何人可以覆盖整个 adoption_store.json（flat JSON 无 ACL）。
FACT  API 级：producer._merge_keyed / _merge_record（producer.py:55,64）
      只挡“同一 key 已有不同 record”的冲突；同 key 相同 record 幂等，
      同 key 不同 record 返回 AUTHORITY_BINDING_MISMATCH。
FACT  整个文件是 last-writer-wins：两个并发 producer 各自 load 同一旧
      快照 -> 各自 append -> 后一次 os.replace 覆盖前一次，
      先写者的新增记录丢失。
```

结论：**flat JSON 不是 write-once，也不是 append-only**。`os.replace`
只保证单文件替换原子，不保证“记录一旦写入不可变”。

### 1.3 是否 atomic？

```text
FACT  os.replace（producer.py:249；guard.py:332）对单个文件是原子替换，
      crash 时不会留下半截 JSON。
FACT  read -> validate -> merge -> write 整体不是事务：
      验证之后、写盘之前 store 可被其他进程修改。
FACT  没有 fsync / flock / fcntl / O_EXCL（全仓 rg 无命中）；
      os.replace 后未 fsync 文件与目录，断电持久性无保证。
FACT  registry.promote 的 entry 创建用 os.link 独占创建
      （registry.py:122），但那只保护 entry，不保护 adoption_store。
```

### 1.4 是否存在 delete / update / rollback？

```text
FACT  代码层没有 delete / update authority 的 API。
FACT  mark_promoted 是唯一的 in-place update（lifecycle 状态），
      只允许 PROMOTABLE -> PROMOTED，幂等。
FACT  文件层 delete/update 永远可能：直接 unlink / 编辑 JSON。
FACT  无 rollback；被覆盖 / 删除的 store 记录无法从当前代码恢复。
```

### 1.5 多进程并发怎么办？

```text
FACT  无锁。issue_authority / mark_promoted 都是 read-modify-write +
      os.replace，两个进程并发 = last-writer-wins / lost update。
FACT  os.link 独占创建只覆盖 registry entry（同一 name 并发 promote），
      不覆盖 store 记录（不同 name / 不同 decision 并发 issue 也会丢）。
FACT  G3（repro）证明：store 被删除后重新 issue 会被当作全新状态，
      删除行为不可审计、不可检测。
```

### 1.6 Registry / Runtime 读取的是不是同一份 authority？

```text
FACT  是同一个文件：registry.promote（registry.py:57）与
      runtime_guard.adopt（guard.py:264）都 load_store() 读
      <registry_root>/adoption_store.json（adoption_authority.py:52）。
FACT  不是同一份信任：Registry 验证的是“调用方传入的 authority dict”
      （registry.py:75 validate(adoption_authority, store, ...)），
      全程不查 store["authorities"]；Runtime 按
      entry.adoption.promotion_decision_id 从 store["authorities"] 加载
      （guard.py:54,257-267）。
FACT  G1（repro）证明：store 完全没有 authorities 记录时，调用方构造的
      合法 binding authority 仍能让 registry.promote() 写 state="promoted"。
```

> 这修正 71 §11 的表述：“绕过 producer 直接构造的 authority 在 Registry
> 重验时同样被挡”只对 id / binding 错误成立；如果调用方复制 store 里的
> decision/run/policy/candidate 字段并计算确定性 authority_id，Registry
> 无法区分“producer 签发过”和“调用方刚构造”。生产落地前必须让 Registry
> 也要求 `store["authorities"]` 存在且与传入 authority 完全一致。

### 1.7 当前行为总结

| 问题 | FACT |
| --- | --- |
| 谁可以写 authority | `issue_authority()`、`mark_promoted()`、任何有 FS 写权限者 |
| 谁可以覆盖 | 任何 FS 写者；os.replace 整文件覆盖 |
| last-writer-wins | 是（文件级） |
| atomic | 单文件 os.replace 原子；read-validate-write 非事务；无 fsync |
| delete / update | 代码无 API；FS 层永远可删可改；mark_promoted 是唯一 sanctioned update |
| rollback | 无 |
| 多进程并发 | 无锁，lost update / last-writer-wins |
| Registry / Runtime 同一份？ | 同一文件路径；不同信任模型（Registry 不查 authorities 记录） |

---

## 2. Issuer Trust

### 2.1 当前事实

```text
FACT  authority_id = sha256(candidate_id|version|decision_id)[:16]
      （adoption_authority.py:32-36）：确定性绑定投影，不是签名。
FACT  issue_authority() 没有 issuer / principal 参数；producer 不记录
      “谁批准、谁签发”。
FACT  pilot/confirm.json 只有 {"operator": "rehearsal-runner",
      "confirm": true, "note": ...}：operator 是字符串，没有持久化到
      decision / authority 记录，也没有密码学身份。
FACT  decision 记录（producer.py:131-132 构造）没有 approved_by / issued_by。
```

### 2.2 TrustedIssuer 最小设计

在 authority 记录（以及 revocation 事件）上新增 `issuer_id`，并让
issue / revoke 只接受显式 allowlist 内的 issuer：

```text
TrustedIssuer:
  issuer_id     签发者身份（进程 / 角色 / principal）
  issued_at     签发时间（已有：== decision.created_at）
  decision_id   被签发决策（已有：== promotion_decision_id）
  authority_id  被签发凭证（已有：确定性 id）
```

允许的 issuer 来自环境 / 配置的显式 allowlist
（12-Factor：配置来自环境，不是代码），不存在 allowlist -> 拒绝签发。
Registry / Runtime 验证时同样要求 `issuer_id in TRUSTED_ISSUERS`，未知
issuer -> `UNTRUSTED_ISSUER` -> `ADOPTION_BLOCKED`（模型已覆盖）。

### 2.3 密码学信任

```text
FACT  仓库没有 JWT / PKI / KMS / 签名基础设施（全仓无签名代码）。
INFERENCE TrustedIssuer allowlist 关闭“任意调用方构造 authority”的应用层
          路径：即使调用方知道确定性 id，没有受信任 issuer_id 也无法
          issue / 通过验证（模型验证）。
UNKNOWN  密码学信任：allowlist 无法防止“拿到 trusted issuer 身份的人伪造”；
          真信任锚（签名私钥 / TPM / 外部 KMS）不在本仓库范围。
```

本阶段不引入 JWT / PKI，符合“除非仓库已有基础设施”的约束。

---

## 3. Write-once / Append-only

### 3.1 AuthorityStatus

```text
ISSUED        issue 事件写入时的唯一初始状态
REVOKED       只能通过 append revocation 事件到达
SUPERSEDED    只能通过 append revocation 事件到达
```

禁止：

```text
update authority binding        AUTHORITY_BINDING_MUTATION
delete / recreate authority     AUTHORITY_DELETE_BLOCKED /
                                AUTHORITY_BINDING_MISMATCH（已有记录）
直接改写 status 字段            验证时 REVOKED_DECISION / INVALID_AUTHORITY_STATUS
```

### 3.2 最小 CAS / append-only boundary（设计，不实现）

最小改动形态：把 flat JSON 的单点覆盖写，换成一行一条不可变事件记录：

```text
adoption_store.jsonl（append-only）：
  {"event": "authority_issued", "authority_id": ..., "issuer_id": ...,
   "issued_at": ..., "decision_id": ..., "record": {...}}
  {"event": "authority_revoked", "revocation_id": ..., "authority_id": ...,
   "status": "REVOKED|SUPERSEDED", "issuer_id": ..., "reason": ...,
   "revoked_at": ...}
  {"event": "lifecycle_transition", "candidate_id": ...,
   "from": "PROMOTABLE", "to": "PROMOTED", ...}

adoption_store.json 降级为派生快照（由 replay 重建），不再作为权威写点。
```

语义：

```text
1. issue = create-if-absent：authority_id 唯一。并发两个 issue 同 id：
   - 相同 binding  -> replay 去重，幂等 ALLOW；
   - 不同 binding  -> 两条事件同时存在，replay 检测到
     AUTHORITY_BINDING_MISMATCH，任何消费者 -> ADOPTION_BLOCKED。
   这是 flat-file 下可实现的 CAS：冲突不静默覆盖，而是可见并 fail-closed。
2. revoke / lifecycle 只追加事件，不重写任何已写记录。
3. delete 不存在；删除文件本身需要文件系统层保护（WORM / 只读挂载，
   UNKNOWN）。
4. 写入用 O_APPEND 单行 JSON（一次 write），配合 replay 校验；
   os.replace 不再用于 store 主记录。
```

`ponytail: 单写者串行化最简；多写者时依赖 append 行原子性 + replay 冲突
检测，不引入分布式锁。真 CAS（数据库 / object store）在吞吐需要时再说。`

---

## 4. Revocation

### 4.1 当前事实

```text
FACT  store["revocations"] 由 producer 初始化（producer.py:190）。
FACT  Registry 检查 revocations 列表（adoption_authority.py:214-221）。
FACT  Runtime 检查 revocations 列表 + authority.status
      （guard.py:213-218）。
FACT  没有 revoke() 写路径：revocations 只能手工编辑 JSON；无 issuer /
      reason / revoked_at 的强制审计字段。
FACT  G2（repro）证明：Registry 对 authority.status == "REVOKED" 且
      revocations 列表为空的 authority 放行（promote -> promoted）。
      即 Registry 只认 revocations 事件，不认 status 字段；Runtime 两者
      都认。两层语义不一致。
```

### 4.2 最小设计

```text
revocation 事件（append-only，可审计）：
  revocation_id / authority_id / candidate_id / candidate_version /
  promotion_decision_id / status: REVOKED | SUPERSEDED / issuer_id /
  reason / revoked_at

Registry + Runtime 都必须检查：
  authority record status in (REVOKED, SUPERSEDED)
  OR 存在匹配的 revocation 事件
  -> REVOKED_DECISION -> ADOPTION_BLOCKED
```

撤销只能由 trusted issuer 追加事件；不能改已签发记录。当前 Registry 的
status 检查缺口（G2）在硬化落地时必须闭合。

---

## 5. TOCTOU

### 5.1 当前窗口（FACT）

```text
Registry 路径：
  registry.py:71   validate() 对 candidate artifact 计算 digest（check）
  registry.py:91   shutil.copytree 拷贝同一 artifact（use）
  验证与拷贝之间源目录可被替换；Runtime 事后会发现 digest 不匹配，
  但 registry entry 已写（不一致状态）。

Runtime 路径：
  harness.py:721   guard.adopt() 计算 artifact_dir digest（check）
  harness.py:725   docker_launch 挂载同一 artifact_dir（use）
  G4（repro）证明：adopt() 返回 ALLOW 后替换 main.py，digest 变化；
  如果此时 docker_launch，挂载的是替换后的字节。
```

### 5.2 最小防护（只选当前代码最小可行项）

```text
1. content-addressed artifact copy（推荐）：
   promote 时把 artifact 复制到
   <registry_root>/artifacts/<artifact_digest>/（目录名 = digest），
   entry.artifact_dir 指向该副本；Runtime 挂载副本而非源 candidate 目录。
   digest 检查与 mount 的路径从此是同一份复制内容，应用层窗口关闭。
2. mount 前 recheck（推荐，与 1 配套）：
   adopt() 通过后、docker_launch 前，对同一 artifact_dir 再算一次 digest
   并以最新 store 复查 revocation / stale（= 模型的 verify_at_mount）。
   任一变化 -> ADOPTION_BLOCKED。
```

不选择：大规模 CAS storage redesign（object store / 分布式快照），超出
“最小可行”边界。

```text
UNKNOWN  OS 级不可变性：content-addressed 目录仍可被同 host 有写权限者
         修改；真闭合需要只读挂载 / WORM / open-by-handle
         （O_PATH fd -> /proc/self/fd 挂载）。生产落地前保持 UNKNOWN。
```

---

## 6. Offline Proof（本阶段新增）

新增文件：

```text
docs/archaeology/unified-runtime/73-authority-storage-trust-hardening.md
docs/archaeology/unified-runtime/phase8.3/validate_authority_storage_hardening.py
docs/archaeology/unified-runtime/phase8.3/test_authority_storage_hardening.py
docs/archaeology/unified-runtime/phase8.3/repro_current_code_gaps.py
```

模型语义（`validate_authority_storage_hardening.py`）：

```text
write-once issue（create-if-absent + expected_version CAS）
append-only revocation 事件（REVOKED / SUPERSEDED）
TrustedIssuer allowlist（issuer_id + issued_at + decision_id + authority_id）
激活前验证 + mount 前 recheck（最新 store + 精确 digest）
```

测试覆盖（`test_authority_storage_hardening.py`，12 项，全部
`ADOPTION_BLOCKED` 或合法 ALLOW）：

| 场景 | 结果 |
| --- | --- |
| valid issue + verify + mount | ALLOW |
| authority overwrite attempt | AUTHORITY_BINDING_MISMATCH |
| authority delete / recreate | AUTHORITY_DELETE_BLOCKED / BINDING_MISMATCH |
| revoked authority | REVOKED_DECISION |
| superseded authority | REVOKED_DECISION |
| authority status = REVOKED | REVOKED_DECISION |
| unknown issuer | UNTRUSTED_ISSUER |
| forged authority id | AUTHORITY_ID_MISMATCH |
| authority binding mutation | AUTHORITY_BINDING_MUTATION |
| concurrent issue（CAS） | STALE_WRITE / AUTHORITY_BINDING_MISMATCH |
| stale read（mount 前 recheck） | REVOKED_DECISION |
| artifact replacement after validation | ARTIFACT_DIGEST_MISMATCH |

current-code gap repro（`repro_current_code_gaps.py`，4 项 FACT）：

```text
G1  store 无 authorities 记录，registry.promote 仍 ALLOW（unissued authority）
G2  authority.status=REVOKED 且 revocations 为空，registry.promote 仍 ALLOW
G3  删除 adoption_store.json 后重新 issue = AUTHORITY_ISSUED（delete/recreate 未检测）
G4  adopt() ALLOW 后 artifact 替换，digest 变化（mount 前窗口存在）
```

验证命令（实际运行）：

```text
python3 -m pytest docs/archaeology/unified-runtime/phase8.3 -q
  -> 12 passed
python3 docs/archaeology/unified-runtime/phase8.3/repro_current_code_gaps.py
  -> CURRENT_GAPS_REPRODUCED
python3 -m compileall -q docs/archaeology/unified-runtime/phase8.3
  -> COMPILEALL_OK
python3 -m pytest docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 \
  docs/archaeology/unified-runtime/phase8.2 -q
  -> 82 passed（回归未破坏）
```

注意：offline proof 证明“设计语义自洽、可机械检查”，不证明生产存储已
加固。G1-G4 是当前代码缺口，不是新测试通过项。

---

## 7. FACT / INFERENCE / UNKNOWN

### production durability

```text
FACT      当前 adoption_store.json：flat JSON，无 CAS / 无锁 / 无 fsync /
          last-writer-wins / delete-recreate 不可检测（§1，G3）。
INFERENCE 最小 JSONL append-only + replay 冲突检测可消除 lost update 与
          覆盖写（模型验证）。
UNKNOWN   生产级持久化：未落地；断电持久性（fsync / 目录 fsync）与
          文件系统层 WORM / 权限未实现。
```

### issuer trust

```text
FACT      当前 authority_id 是确定性内容哈希，无签名；producer 无
          issuer 身份记录（§2.1）。
INFERENCE TrustedIssuer allowlist + issue 时注册可关闭“任意调用方构造
          authority”的应用层路径（模型验证：UNTRUSTED_ISSUER）。
UNKNOWN   密码学信任锚（签名 / TPM / KMS）不存在。
```

### TOCTOU protection

```text
FACT      当前 digest 检查与 mount / copytree 之间存在替换窗口
          （§5.1，G4）。
INFERENCE content-addressed artifact copy + mount 前 recheck 关闭应用层
          窗口（模型验证：ARTIFACT_DIGEST_MISMATCH / REVOKED_DECISION）。
UNKNOWN   OS 级不可变性（只读挂载 / WORM / open-by-handle）。
```

---

## 8. 最终判定

```text
AUTHORITY_STORAGE_HARDENING_VALID_WITH_UNKNOWN
```

```text
FACT      当前 flat JSON 的写入 / 覆盖 / 并发 / 删除行为全部考古完成，
          四个缺口（unissued authority、Registry status 检查、store
          delete/recreate、mount 前窗口）都有可运行 repro（G1-G4）。
FACT      最小 hardening 设计完整：TrustedIssuer / AuthorityStatus /
          append-only + CAS 边界 / content-addressed artifact +
          mount recheck，12 项 offline tests 全部通过。
UNKNOWN   production durability、密码学 issuer trust、OS 级 TOCTOU 闭合
          均未落地，不能宣称生产安全。
```

STOP：

```text
未接第二个 Runtime / Cordis / Langfuse / E.8 / production rollout。
未修改 pilot/ 生产代码（本次只做 design + offline proof）。
未 commit / push。
```
