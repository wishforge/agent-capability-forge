# 74 — Authority & Artifact Integrity Hardening（Phase 8.4）

> 阶段：Phase 8.4（AdoptionAuthority 不可变 / TrustedIssuer 边界 / Artifact
> TOCTOU 最小真实改造）。
> 基线：73（Phase 8.3，AUTHORITY_STORAGE_HARDENING_VALID_WITH_UNKNOWN）、
> 72（Phase 8.2）、71（Phase 8.1）、70（Phase 8）。
> 与 73 的区别：73 只做 design + offline proof；本阶段把其中最小子集落地到
> `pilot/` 生产代码，并用真实代码测试证明非法路径 fail-closed。
> 约束遵守：未修改 Phase 7–8.3 历史 artifacts；未接第二个 Runtime /
> Cordis / Langfuse / E.8；未做 production-wide rollout / 大规模数据库迁移；
> 未 commit / push。

## 0. 执行摘要

本阶段先重新考古 `pilot/adoption_authority.py`、`adoption_authority_producer.py`、
`registry.py`、`runtime_adoption_guard.py`、`harness.py`，确认 Phase 8.3 的
G1–G4 全部仍然成立，然后落地三个最小真实改造：

```text
P0  Artifact TOCTOU：B3 激活路径在 docker_launch 前新增 verify_at_mount()
    二次全量校验（最新 store + 最新 digest + revocation），窗口从
    “校验后任意时长”压到“recheck 与 bind mount 解析之间”。
P1  Authority 不可变：签发时额外写 <root>/authorities/<id>.json，
    O_EXCL + os.link 原子 create-if-absent + fsync；禁止覆盖 / 改写 binding。
P1  Issuer 边界：authority 记录新增 issuer_id / issuer_type / decision_id；
    配置 PILOT_TRUSTED_ISSUERS 后，Registry / Runtime / producer / revoke
    全部对未知 issuer fail-closed。
P2  Revocation 持久性：revoke_authority() 只 append
    <root>/authorities/<id>.events.jsonl（REVOKED / SUPERSEDED），
    不重写已签发的 authority 记录；旧 flat store 的 revocations 同步为
    best-effort 派生副本。
```

最终判定：

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

```text
authority immutability   VALID：write-once ledger（O_EXCL CAS），
                         overwrite / mutation / delete-recreate /
                         deterministic-ID collision 全部 fail-closed。
issuer trust             PARTIAL：PILOT_TRUSTED_ISSUERS allowlist + 签发时
                         记录 issuer 身份；未配置时保持 legacy
                         deterministic-binding（UNKNOWN：密码学签名）。
TOCTOU                   VALID_WITH_UNKNOWN：mount 前完整 recheck +
                         read-only bind mount；OS 级
                         open-by-handle / WORM / 只读快照仍 UNKNOWN。
revocation durability    VALID：append-only 事件日志；事件与 record 分离。
```

不是 `INTEGRITY_HARDENING_VALID`：issuer 无密码学信任锚；legacy store（没有
`authorities/` 目录）仍保留 8.3 之前的语义；OS 级 TOCTOU 未闭合。
不是 `PARTIAL`：四个关键路径（producer / registry / runtime / revoke）都有
真实代码 enforcement，不是只有设计。

---

## 1. Current Security Facts（重新确认，不重复旧结论）

### G1 — flat JSON 无 CAS / 无 write-once / 无 fsync

```text
FACT  pilot/adoption_authority_producer.py:280-281
      issue_authority() 仍以 load -> merge -> tmp.write_text ->
      os.replace 写 adoption_store.json；无锁 / 无 CAS / 无 fsync。
FACT  pilot/runtime_adoption_guard.py:395-396（mark_promoted）
      仍是第二个整文件写点（lifecycle PROMOTABLE -> PROMOTED）。
FACT  8.4 新增 authorities/<id>.json 独立 ledger 后，store 降级为
      “派生快照 + legacy 兼容”，ledger 才是 write-once 权威记录。
```

### G2 — issuer trust 只有 deterministic identity

```text
FACT  8.4 之前 authority_id = sha256(candidate|version|decision)[:16]
      （adoption_authority.py:authority_id_for），无签名、无 issuer 记录。
FACT  producer.issue_authority() 无 issuer 参数；confirm.operator 只是
      字符串，不进入 authority 记录。
INFERENCE 8.4 落地后：authority 记录含 issuer_id / issuer_type /
      decision_id；配置 allowlist 后未知 issuer 一律 ADOPTION_BLOCKED。
UNKNOWN   密码学签名 / PKI / TPM / KMS（仓库无此类基础设施，不引入）。
```

### G3 — Runtime digest 校验与 mount 之间 TOCTOU

```text
FACT  8.4 之前 harness.py B3：
      runtime_guard.adopt(registry_root, entry, artifact_dir)  # digest check
      docker_launch(image, [(artifact_dir, "/artifact", True), ...])  # use
      两次调用之间 artifact_dir 可被替换；mount 使用替换后的字节。
FACT  docker bind mount 使用 `-v host:cont:ro`（src/forge/sandbox.py:27-29），
      container 侧只读，但 host 侧替换不受 `ro` 限制。
INFERENCE 8.4 落地后：docker_launch 前新增 verify_at_mount()，替换或
      revocation 都会被最新 digest / 最新 store 拦截。
UNKNOWN   verify 与 docker run 的 bind-mount 解析之间仍有微窗口；
      open-by-handle / 内容寻址不可变副本 / WORM 未实现。
```

---

## 2. Authority Integrity

### 2.1 不可变身份字段

已签发的 AuthorityRecord 中以下字段为 binding 字段，禁止修改：

```text
authority_id
candidate_id
candidate_version
promotion_decision_id
evaluation_run_id
policy_version
artifact_digest
provenance
issuer_id
issued_at
```

任何修改尝试（覆盖写、binding mutation、同 ID 不同内容）返回
`AUTHORITY_BINDING_MISMATCH` / `AUTHORITY_IMMUTABILITY_VIOLATION` 语义，
Registry / Runtime 消费时一律 `ADOPTION_BLOCKED`。

### 2.2 落地实现

```text
<registry_root>/authorities/<authority_id>.json   # write-once record
<registry_root>/authorities/<authority_id>.events.jsonl  # append-only 状态事件
```

`write_authority_record()`（adoption_authority.py:95）：

```text
1. 已存在同 ID 且内容相同 -> 幂等成功，不写盘。
2. 已存在同 ID 且内容不同 -> AUTHORITY_BINDING_MISMATCH，不改原文件。
3. 不存在 -> 写唯一 tmp -> fsync(file) -> os.link(tmp, path)
   （原子 create-if-absent，等价 O_EXCL CAS）-> fsync(dir)。
```

这保留了 `adoption_store.json` 的兼容形态（Phase 7–8.3 历史测试不破），
同时给每个 authority 一个不可覆盖的权威记录。flat store 被并发覆盖时，
ledger 不丢；Runtime 发现 ledger 与 store 不一致 -> fail-closed。

---

## 3. Persistence Options（比较）

| 方案 | 结论 |
| --- | --- |
| A. JSONL append-only 全量迁移 | 破坏所有旧 reader / 历史测试，改动大，不选 |
| B. SQLite | 仓库明确“experimental registry 无 SQLite”，引入新依赖，不选 |
| C. file-per-authority immutable record | **采用**：O_EXCL + os.link 原子 CAS，最小、与现有 `adoption_store.json` 共存 |
| D. existing storage | 保留：store 继续存 decisions/runs/policies/lifecycle，作为派生快照 |
| E. DB | 仓库无自然依赖，不选 |

选 C 的理由：`registry.promote` 已有 `os.link` 独占创建 entry 的先例
（registry.py:121-122），同一个模式扩展到 authority ledger，不需要新依赖、
不需要迁移旧 store。

---

## 4. Trusted Issuer

### 4.1 谁可以做什么（考古结论）

```text
谁可以调用 issue_authority()   任何能运行 pilot 进程 / 导入 producer 的人；
                               8.4 起必须带受信任 issuer_id（配置 allowlist 时）。
谁可以伪造 authority_id        任何人（确定性哈希可重算），
                               但伪造 ID 过不了 authority_id 一致性检查；
                               且没有 ledger 记录的伪造 authority
                               在 hardened store 上被 UNISSUED_AUTHORITY 拦截。
谁可以写 adoption_store        任何有 FS 写权限者（flat JSON 无 ACL，UNKNOWN）。
谁可以修改 decision            任何有 FS 写权限者；decision recorded_hash/
                               current_hash 不一致会被 DECISION_TAMPERED 拦截。
谁可以修改 issuer metadata     authority 记录不可变（ledger）；
                               修改后与 ledger 不一致 -> AUTHORITY_BINDING_MISMATCH。
```

### 4.2 最小 TrustedIssuer

```text
issuer_id       签发者身份（显式参数或 confirm.operator / confirm.issuer_id）
issuer_type     签发者类型（默认 operator）
issued_at       签发时间（== decision.created_at，已有检查）
decision_id     被签发决策（必须 == promotion_decision_id）
authority_id    被签发凭证（确定性 id）
```

环境变量 `PILOT_TRUSTED_ISSUERS`（逗号分隔 allowlist）：

```text
未配置    -> legacy 模式：producer 仍记录 issuer_id，但不强制验证
            （FACT：确定性 binding；UNKNOWN：issuer 真实性）。
已配置    -> 严格模式：issue / revoke / Registry / Runtime 全部要求
            issuer_id ∈ allowlist，未知 issuer -> UNTRUSTED_ISSUER
            -> ADOPTION_BLOCKED / AUTHORITY_ISSUANCE_BLOCKED。
```

不引入 JWT / PKI / CA：仓库没有签名基础设施，符合约束。

---

## 5. Artifact TOCTOU

### 5.1 当前窗口（8.4 重新确认）

```text
harness.py:722   adopt() 计算 artifact_dir digest（check）
harness.py:729   docker_launch 挂载同一 artifact_dir（use）
```

窗口内替换文件 -> digest 变 -> 挂载的却是替换后的字节。

### 5.2 最小 CURRENT CODE COMPATIBLE 方案

在候选方案（content-addressed path / immutable dir / open fd / recheck /
atomic snapshot / permissions / ro mount / copy-to-dedicated-dir）中，
本阶段选择：

```text
1. mount 前 recheck：runtime_adoption_guard.verify_at_mount()
   - 重新 load 最新 adoption_store.json（revocation / stale 最新视图）
   - 重新计算 artifact_dir digest
   - 与首次 adopt() 返回的 digest 比对
   - 任一变化 -> ARTIFACT_DIGEST_MISMATCH / REVOKED_DECISION
     -> ADOPTION_BLOCKED，docker_launch 不被调用。
2. read-only bind mount（已有，src/forge/sandbox.py:27-29）：容器内不可写。
```

为什么不做 content-addressed copy：`promote()` 必须继续写到
`<root>/<family>/<name>/artifact`（Phase 8.1 测试断言），B3 必须继续挂载
`entry["artifact_dir"]`（Phase 8.2 测试断言）；改成挂载不可变副本会破坏
历史 artifacts。把 artifact 移到内容寻址不可变目录是下一步（见 §14）。

```text
UNKNOWN  recheck 与 docker bind-mount 解析之间仍有微窗口；
         同 host 有写权限者仍可改 ledger / artifact（OS 级不可变性）。
```

---

## 6. Digest Verified Execution

Runtime 可信对象链：

```text
PromotionDecision
  -> AdoptionAuthority（deterministic id + binding）
  -> Immutable Authority（<root>/authorities/<id>.json，write-once）
  -> Trusted Issuer（PILOT_TRUSTED_ISSUERS 配置时强制）
  -> Artifact Digest（authority / decision / run / candidate / entry /
                     实际目录六方一致）
  -> verify_at_mount()（最新 store + 最新 digest）
  -> docker_launch(ro bind mount)
  -> EXECUTE
```

任何一环失败 -> `ADOPTION_BLOCKED`。Runtime 不再只信 `path` / `version`：
每次激活都重新对实际字节计算 digest，并在 mount 前再算一次。

```text
FACT  挂载参数仍是 path（PATH_ONLY 语义在 docker 层面保留）。
FACT  挂载前最后一次 digest 校验通过 -> 该路径字节 == 已验证字节
      （应用层）。
UNKNOWN  OS 层保证“挂载解析到的 inode == 校验过的 inode”
      （需要 O_PATH fd / /proc/self/fd 挂载或 WORM，未实现）。
```

---

## 7. Revocation / Supersession

### 7.1 状态模型

```text
ISSUED      -> 初始状态（ledger record 唯一初始状态）
REVOKED     -> 只通过 append 事件到达
SUPERSEDED  -> 只通过 append 事件到达
```

`revoke_authority(registry_root, authority_id, status=..., issuer_id=...,
reason=...)`：

```text
1. 必须存在 ledger record，否则 MISSING_AUTHORITY。
2. status ∈ {REVOKED, SUPERSEDED}，否则 INVALID_AUTHORITY_STATUS。
3. issuer 必须受信任（allowlist 配置时），否则 UNTRUSTED_ISSUER。
4. append <root>/authorities/<id>.events.jsonl（O_APPEND + fsync）。
5. best-effort 同步 store["revocations"]（legacy 派生副本）。
```

Registry（`validate()`）与 Runtime（`violations_for_runtime_activation()`）
都会验证 revocation；REVOKED / SUPERSEDED -> `REVOKED_DECISION`
-> `ADOPTION_BLOCKED`。已撤销 authority 不能被重新 promote /
重新 adopt / 重新 issue（producer 的 validate 同样检查 revocation）。

### 7.2 与 flat store 的关系

```text
events 文件是持久真相：即使后续 mark_promoted / issue_authority
整文件重写 store，revocation 事件不会被覆盖。

hardened store 下 store["revocations"] 不是普通派生副本，而是
load-bearing 的 revocation 副本：
  - revoke_authority() 写事件时同步写入 store copy；
  - 事件与副本统一使用 canonical 字段 decision_id
    （promotion_decision_id 只保留为同值 legacy mirror）；
  - events 文件缺失 -> 副本仍阻断（不会自动恢复 ALLOW）；
  - events 与副本任一显示 REVOKED/SUPERSEDED，或 events 文件损坏
    -> FAIL CLOSED（REVOKED_DECISION / AUTHORITY_BINDING_MISMATCH）。
```

---

## 8. Replay / Double Spend

以代码 / 业务语义为依据，不做猜测：

```text
FACT  8.2 测试 test_repeat_valid_activation_is_idempotent：
      同一 authority 重复 adopt -> 幂等 ALLOW。
FACT  8 测试 test_same_valid_adoption_twice_is_idempotent：
      同一 authority 重复 promote -> 幂等 ALLOW（不重复写 entry）。
FACT  registry.promote 对已存在 entry 的不同 binding
      -> ENTRY_BINDING_CONFLICT（8 测试覆盖）。
FACT  runtime 每次激活都重新全量验证，不消耗 / 不销毁 authority。
```

结论：当前语义是 **reusable adoption credential**，不是 single-use。
一个 version 可以长期运行；安全性由“authority 不可变 + 绑定不可变 +
每次激活重验 + revocation 事件”保证，而不是一次性消费。

8.4 不引入 consumption state：如果未来需要 single-use，应增加
`authorities/<id>.consumed.jsonl` 事件并在 `verify_at_mount` 中拒绝
已消费 authority（本阶段不做，YAGNI）。

---

## 9. Minimal Hardening Plan（落地清单）

```text
P0  artifact TOCTOU hardening
    - runtime_adoption_guard.verify_at_mount()（新）
    - harness.py B3：docker_launch 前调用（新）
P1  authority immutable persistence
    - adoption_authority.write_authority_record()（新）
    - producer.issue_authority() 签发时写 ledger（新）
    - registry.promote() 校验 ledger / UNISSUED_AUTHORITY（新）
    - runtime.adopt() 以 ledger 为权威、与 store 比对（新）
P1  issuer trust boundary
    - authority 记录 + issuer_id / issuer_type / decision_id（新）
    - PILOT_TRUSTED_ISSUERS allowlist（新，opt-in）
P2  revocation durability
    - revoke_authority() + append-only events 文件（新）
    - Registry / Runtime 读取 events（新）
```

未做（不在本阶段）：

```text
第二个 Runtime / Cordis / Langfuse / E.8 / production rollout
数据库迁移 / JSONL 全量迁移
content-addressed immutable artifact copy
密码学签名 / PKI / TPM / KMS
single-use consumption state
```

---

## 10. Production Code Changes

### 修改

```text
pilot/adoption_authority.py
  + trusted_issuers / issuer_allowed / PILOT_TRUSTED_ISSUERS
  + authority_record_path / authority_events_path / write_authority_record
  + load_authority_record / load_authority_events / append_authority_event
  + revoke_authority
  + violations_for_authority：issuer / decision_id / ledger / events 检查
  + validate：透传 registry_root
pilot/adoption_authority_producer.py
  + issuer_id / issuer_type / decision_id 写入 authority 记录
  + issuer allowlist 检查
  + 签发时写不可变 ledger（冲突 -> AUTHORITY_ISSUANCE_BLOCKED）
pilot/registry.py
  + promote 校验 ledger record；hardened store 无记录 -> UNISSUED_AUTHORITY
pilot/runtime_adoption_guard.py
  + violations_for_runtime_activation：issuer / decision_id / events / store
    revocation 检查
  + adopt：ledger 为权威记录，与 store 比对；hardened store 下
    authorities/ 目录存在时 ledger 记录必须存在，缺失 -> UNISSUED_AUTHORITY
    （禁止 fallback 到 store["authorities"]）；verify_at_mount() 继承同一规则
  + verify_at_mount()：mount 前完整 recheck
pilot/harness.py
  + B3：docker_launch 前调用 verify_at_mount()
```

### 兼容性

```text
旧 store 没有 authorities/ 目录 -> 走 legacy 路径（8.3 语义保留，UNKNOWN）。
新 producer 签发的 store 必有 ledger -> Registry / Runtime 强制校验；
ledger 记录缺失时 Runtime 与 Registry 同样 fail-closed，不再依赖
store["authorities"] 派生副本。
Phase 7–8.3 历史 artifacts 未修改；94 个历史测试全部保持通过。
```

---

## 11. FACT / INFERENCE / UNKNOWN

### authority immutability

```text
FACT      write_authority_record：O_EXCL 等价 CAS（tmp + fsync + os.link +
          dir fsync），已存在不同记录 -> AUTHORITY_BINDING_MISMATCH；
          21 个 8.4 测试覆盖 overwrite / mutation / delete-recreate /
          stale write / concurrent writer / deterministic-ID collision。
INFERENCE 即使 flat store 被并发覆盖，ledger 仍保留原始 binding；
          Runtime 发现不一致 -> fail-closed。
UNKNOWN   OS 级：有 FS 写权限者可删除 ledger 文件本身
          （WORM / 只读挂载未实现）。
```

### issuer trust

```text
FACT      authority 记录现在包含 issuer_id / issuer_type / decision_id。
FACT      PILOT_TRUSTED_ISSUERS 配置后，未知 issuer 在 issue / revoke /
          Registry / Runtime 全部被拒（测试覆盖）。
UNKNOWN   未配置 allowlist 时仍只有 deterministic binding；
          密码学签名不存在。
```

### TOCTOU

```text
FACT      B3 在 docker_launch 前执行 verify_at_mount()：
          最新 store + 最新 digest + revocation；替换 / 换路径 /
          字节变化 -> ARTIFACT_DIGEST_MISMATCH -> ADOPTION_BLOCKED。
FACT      artifact bind mount 为 ro（容器内只读）。
UNKNOWN   recheck 与 bind-mount 解析之间微窗口；
          open-by-handle / WORM / 内容寻址不可变副本未实现。
```

### revocation durability

```text
FACT      revoke / supersede 只 append events JSONL（O_APPEND + fsync），
         不重写 authority record；事件与 store copy 统一 canonical
         decision_id；events 缺失时 store copy 仍 load-bearing 阻断，
         events 与副本任一显示撤销或事件文件损坏 -> FAIL CLOSED。
UNKNOWN   events / store / ledger 文件本身可被 OS 级删除；
         删除整个 authorities/ 目录会把 store 从 hardened 模式
         降级为 legacy 模式（OS 级删除抵抗未实现）。
```

---

## 12. Residual Risks

```text
1. OS 级文件不可变性缺失：同 host 有写权限者可删除 ledger / events /
   artifact 文件；需要 WORM / 只读挂载 / open-by-handle。
2. issuer 无密码学签名：allowlist 只挡“未授权身份”，不挡
   “拿到受信任身份的人”或“配置泄露”。
3. legacy store 兼容路径：没有 authorities/ 目录的旧 store 仍是 8.3 语义
   （UNISSUED_AUTHORITY / store-revocation 强校验只在 hardened store 上
   生效）；删除 authorities/ 目录本身即触发该降级（OS 级，UNKNOWN）。
4. flat adoption_store.json 仍是 last-writer-wins：decision / run /
   policy / lifecycle 的并发写可能丢，但丢失会 fail-closed，
   不会静默放行（ledger 与 store 不一致 -> blocked）。
5. recheck 与 mount 之间的微窗口无法在应用层完全消除。
```

---

## 13. MVP Boundary

本阶段 = 最小生产硬化 MVP：

```text
一个 ledger 文件格式（file-per-authority，无迁移）
一个环境变量开关（PILOT_TRUSTED_ISSUERS，缺省兼容）
一个 mount 前 recheck（verify_at_mount）
一个 revoke API（append-only events）
```

不做全量 JSONL / SQLite / 密码学 / 内容寻址副本。每个都是独立后续阶段。

---

## 14. Next Step

```text
1. content-addressed immutable artifact：
   promote 时复制到 <root>/artifacts/<digest>/ 并 chmod 只读，
   B3 挂载该副本；需要同步更新 Phase 8.1 / 8.2 测试中的路径断言
   （本阶段因“不改历史 artifacts”约束未做）。
2. OS 级闭合：O_PATH fd -> /proc/self/fd 挂载，或 artifact/ledger 目录
   只读挂载 / WORM。
3. 密码学 issuer：HMAC / 签名私钥 + 公钥验证，或外部 KMS。
4. single-use consumption state（若业务语义变化）。
```

---

## 15. 验证（实际运行）

```text
python3 -m pytest docs/archaeology/unified-runtime/phase8.4 -q
  -> 21 passed
python3 -m pytest docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 \
  docs/archaeology/unified-runtime/phase8.2 \
  docs/archaeology/unified-runtime/phase8.3 \
  docs/archaeology/unified-runtime/phase8.4 -q
  -> 115 passed
python3 -m compileall -q pilot docs/archaeology/unified-runtime/phase8.4
  -> COMPILEALL_OK
```

---

## 16. 最终判定

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

回答四个核心问题：

```text
“这张 AI 上岗许可证现在能不能被偷偷改？”
  不能通过应用层改：每个 authority 有 write-once ledger，
  overwrite / binding mutation / delete-recreate / ID collision
  全部 fail-closed；hardened store 下 Registry 与 Runtime 都以 ledger
  record 为 authority anchor，ledger 缺失 -> UNISSUED_AUTHORITY，
  Runtime 不再 fallback 到 store；OS 级删除 ledger 文件本身仍 UNKNOWN。

“谁能签发？Registry / Runtime 为什么信它？”
  签发 = producer.issue_authority() + 受信任 issuer_id
  （PILOT_TRUSTED_ISSUERS 配置后强制）+ write-once ledger。
  Registry / Runtime 信的是 ledger 记录与 presented authority 完全一致，
  而不是只信确定性哈希或调用方自述。

“验过的 AI 产物在真正执行时还能不能被偷偷换掉？”
  应用层窗口已关闭到 mount 前最后一次 recheck：替换 / 换路径 /
  字节变化会在 docker_launch 前触发 ADOPTION_BLOCKED；
  recheck 与 bind-mount 解析之间的 OS 级微窗口仍 UNKNOWN。

“撤销后 events 文件被删，Runtime 会复活吗？”
  不会：hardened store 下 store["revocations"] 是 load-bearing 副本
  （canonical decision_id），events 缺失仍 REVOKED_DECISION -> BLOCK；
  events 与副本不一致同样 FAIL CLOSED。
```

STOP：未 commit / push；未改历史 artifacts；未引入任何平台级重构。
