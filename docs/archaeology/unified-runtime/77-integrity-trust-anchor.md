# 77 — Integrity Trust Anchor（Phase 8.4.3）

> 阶段：Phase 8.4.3（Adoption Authority “信任根”研究 + 最小落地）。
> 基线：76（Phase 8.4.2，INTEGRITY_HARDENING_VALID_WITH_UNKNOWN）。
> 约束遵守：未修改 E.5–E.7.1、Phase 7–8.4.2 历史 artifacts、
> 48/51/52/53、codex/、control-plane/、openhands/；未进入 Phase 8.5；
> 未接第二 Runtime / Langfuse / Cordis；未 commit / push。

## 0. 结论

```text
TRUST_ANCHOR_PARTIAL
```

仓库考古结论：`pilot/` 没有现成的第二信任域（无 SQLite 生产实现、无
HMAC / 签名 / KMS / secret store、无外部可信服务；Git 存在但
`pilot/state/` 被 gitignore，本地攻击者可重写历史，不能作为运行期锚）。
因此没有条件诚实地声明 `TRUST_ANCHOR_VALID`。

本阶段落地的是**最小外部完整性 manifest**（operator-sealed trust anchor）：

```text
FACT   外部 anchor 文件（代码强制在 registry_root 之外）
FACT   seal 是 create-only 的显式 operator 动作（不自动修复）
FACT   sealed store 下 14 项对抗攻击全部 INTEGRITY_STORE_CORRUPTED
FACT   删除 anchor 不会降级 legacy（store 内 trust_anchor_sealed 标记检测）
FACT   未 seal 的 store 保持 8.4.2 legacy 语义（历史测试不破）
UNKNOWN anchor 文件是否真的处于不同 trust domain
       （取决于部署：只读挂载 / 不同用户 / 外部服务，代码无法证明）
```

不是 `TRUST_ANCHOR_VALID`：同一 OS 用户仍可同时删除
`store_metadata.trust_anchor_sealed` 与 anchor 文件，代码内无法区分
“从未 seal”与“seal 后被整体删除”。这不是可以靠再加一个 hash 解决的问题，
必须由部署层提供真正的写保护。

---

## 1. Executive Summary

Phase 8.4.2 用 `store_metadata.integrity_mode = "hardened"` 修复了
“删除 authorities/ 目录后降级 legacy”的问题，但 marker 本身位于
attacker-writable 的 `adoption_store.json` 中：删除/篡改 marker 仍可让
hardened store 被解释为 legacy；`store["revocations"]` 与 events 同属
一个 trust domain，“副本一致”不等于“真实”。

本阶段先做 Trust Boundary 考古，再落地最小真实方案：

1. 新增外部 `integrity_anchor.json`（schema `integrity_anchor_v1`），
   代码强制 anchor 路径不在 `registry_root` 内。
2. anchor 绑定 `store_id`、`store_digest`、
   `authority_manifest_digest`、`revocation_manifest_digest`。
3. `seal_trust_anchor()` 是 create-only 显式 operator 动作；seal 时在
   store 记录 `trust_anchor_sealed = True`，因此**删除 anchor 会 fail
   closed**，而不是静默回到 legacy。
4. Registry / Runtime / revoke / mark_promoted 全部先做 anchor 校验；
   任何缺失/篡改 -> `INTEGRITY_STORE_CORRUPTED` -> `ADOPTION_BLOCKED`。
5. 未 seal 的 store 保留 8.4.2 legacy 语义（不强制引入 anchor），
   历史 Phase 8.1–8.4 测试全部保持通过。

最终判定为 `TRUST_ANCHOR_PARTIAL`：机制真实、可验证、fail-closed；
但“不同 trust domain”的物理保证属于部署层，不属于本仓库代码。

---

## 2. Current Trust Boundary

```text
Domain A（attacker-writable，同一目录）:
  <registry_root>/adoption_store.json
  <registry_root>/authorities/<authority_id>.json
  <registry_root>/authorities/<authority_id>.events.jsonl

Domain B（候选 trust anchor）:
  <registry_root>.integrity-anchor.json            # 默认 sibling
  ${PILOT_INTEGRITY_ANCHOR}                        # operator 覆盖
```

核心问题：

```text
如果 Domain A 被攻击者完全改写，
Domain B 还能否证明原始状态？
```

答案分两层：

```text
FACT     代码强制 anchor 文件不在 Domain A 目录内；
         anchor 内容与 Domain A 独立计算，A 被部分改写 -> anchor mismatch
INFERENCE anchor 若放在只读挂载 / 不同用户目录 / 外部服务，
          则 Domain B 是真正不同的 trust domain，可以证明原始状态
UNKNOWN  同一 OS 用户可同时写 Domain A 和 Domain B；
         代码无法证明部署层写保护存在
```

因此：

```text
默认 sibling 文件           -> NOT_A_TRUST_ANCHOR（仅测试/迁移便利）
外部路径 + 部署写保护        -> 真正 trust anchor（INFERENCE，非代码保证）
```

---

## 3. Why Current Marker Is Not a Trust Anchor

```text
store_metadata.integrity_mode = "hardened"
```

问题：

```text
1. 与 adoption_store.json 其余内容同文件、同目录、同写权限。
2. 删除 marker -> store_integrity_mode() 返回 legacy -> hardened 语义丢失。
3. 在同一 JSON 里再放 hash 字段不改变 trust domain：
   攻击者可以同时改 hash 与内容。
```

8.4.2 的 marker 是**状态标记**，不是**证明**。它只能让“目录删除”不再
降级；不能证明“这份 store 曾经被可信流程硬化、之后没有被改写”。

---

## 4. Trust Anchor Options

| 方案 | 安全强度 | 兼容性 | 改造成本 | 恢复能力 | 攻击面 | 是否不同 trust domain |
| --- | --- | --- | --- | --- | --- | --- |
| A. External integrity manifest | 取决于部署（同用户可写则低） | 高（并存，不迁移） | 低（一个文件 + 校验函数） | 显式 operator re-seal / 快照恢复 | anchor 路径配置错误、anchor 被同用户删除 | 仅当部署写保护成立 |
| B. Separate protected marker | 与 A 相同，但无独立证明 | 高 | 低 | 无 | 同 A | 否 |
| C. Git-backed provenance | 低-中（本地仓库可重写，无远程验证） | 低（`pilot/state/` 被 gitignore） | 中 | 依赖远端 | git 历史 / 身份 | 否（无远端可信锚） |
| D. SQLite / transactional store | 中（事务、WAL，但同文件系统） | 低（仓库明确 EXPERIMENT_ONLY 无 SQLite） | 高（大迁移） | 中 | DB 文件同用户可写 | 否（除非 DB 在独立服务） |
| E. HMAC / signature | 高（密钥保护时） | 低（仓库无密钥/secret store/KMS） | 高（需新基础设施） | 密钥丢失则不可恢复 | 密钥管理 | 是（密钥域）但仓库不存在 |
| F. Existing external trusted storage | 高 | 低 | 高 | 取决于服务 | 服务凭据 | 是，但仓库中不存在 |

结论：仓库现成能力只支持 A（外部独立 manifest），且必须诚实标注其物理
trust domain 是部署属性。

---

## 5. Recommended MVP

采用 **A. External integrity manifest**，落地为：

```text
<external>/integrity-anchor.json
```

anchor 内容：

```json
{
  "schema": "integrity_anchor_v1",
  "store_id": "store-<uuid>",
  "integrity_mode": "hardened",
  "schema_version": "adoption_store_v2",
  "store_digest": "sha256:...",
  "authority_manifest_digest": "sha256:...",
  "revocation_manifest_digest": "sha256:...",
  "anchor_created_at": "...",
  "anchor_revision": 1
}
```

物理位置规则：

```text
PILOT_INTEGRITY_ANCHOR 设置时 -> 使用该路径（必须不在 registry_root 内）
未设置时 -> <registry_root.parent>/<registry_root.name>.integrity-anchor.json
           （sibling；代码视为部署前测试/迁移形态，不是真 trust anchor）
```

代码强制：

```text
anchor 路径在 registry_root 内 -> TRUST_ANCHOR_CONFIG_INVALID
seal 已存在 -> TRUST_ANCHOR_ALREADY_EXISTS（不覆盖，不修复）
seal 非 hardened store -> INTEGRITY_STORE_CORRUPTED
```

seal 副作用：

```text
store_metadata.trust_anchor_sealed = true
```

该字段**不是 trust anchor**（它和 store 同文件可写）；它的唯一作用是让
“anchor 被删除”变成 `INTEGRITY_STORE_CORRUPTED` 而不是静默 legacy。
“seal 标记 + anchor 都被同一攻击者删除”在进程内不可检测，属于 residual
risk（见 §13）。

---

## 6. Authority Manifest

对每个 `authorities/<authority_id>.json`：

```text
digest(record) = sha256(canonical_json(record))
authority_manifest = {
  "<authority_id>": digest(record),
  ...
}
authority_manifest_digest = sha256(canonical_json(authority_manifest))
```

canonical JSON：`sort_keys=True, separators=(",", ":"), ensure_ascii=False`。

因此修改：

```text
candidate_id
candidate_version
policy_version
evaluation_run_id
artifact_digest
provenance
issuer_id / issued_at / decision_id
```

都会改变 record digest -> 改变 manifest root -> anchor mismatch ->
`INTEGRITY_STORE_CORRUPTED`。新增/删除/替换 authority 文件同样被捕获。

未实现 Merkle tree：当前单 authority / 小规模文件场景下，整表 manifest
root 已足够，不需要增量证明。

---

## 7. Revocation Manifest

对每个 `authorities/<authority_id>.events.jsonl`：

```text
digest(events) = sha256(raw event file bytes)   # 保留顺序与原始字节
revocation_manifest = {
  "<authority_id>": digest(events),
  ...
}
revocation_manifest_digest = sha256(canonical_json(revocation_manifest))
```

攻击者：

```text
删除 events 文件              -> manifest 变化 -> BLOCK
修改 event 内容               -> raw bytes 变化 -> BLOCK
同时修改 event 与 store copy  -> manifest 变化 -> BLOCK
删除整条 revocation           -> manifest 变化 -> BLOCK
只改 store["revocations"]     -> store_digest 变化 -> BLOCK
```

这解决了 8.4.2 的“副本一致 ≠ 真实”问题：可信事实来自
`revocation_manifest_digest` 与外部 anchor 的绑定，而不是 store 副本自洽。

---

## 8. Issuer Trust

```text
FACT   authority_id = sha256(candidate_id|candidate_version|decision_id)
FACT   PILOT_TRUSTED_ISSUERS allowlist 校验 issuer_id
INFERENCE 以上只证明“内容格式正确、身份绑定一致”
UNKNOWN   密码学真实性：无签名 / PKI / CA / HMAC / KMS
```

仓库考古未发现现成 trusted issuer infrastructure（无 signing key、
secret store、KMS、外部身份服务），因此不自行引入 JWT/PKI/HMAC。
anchor 不伪造 issuer 真实性；issuer 真实性保持 `UNKNOWN`，与 74/76 一致。

---

## 9. Corruption vs Legacy

```text
未 seal（无 anchor、无 trust_anchor_sealed）:
  -> LEGACY 语义（8.4.2 行为不变）
  -> PRODUCTION_HARDENING_NOT_ESTABLISHED

已 seal（anchor 存在 + trust_anchor_sealed = true）:
  -> 所有校验通过         VALID
  -> 任一条件不满足        INTEGRITY_STORE_CORRUPTED -> ADOPTION_BLOCKED
```

以下情况在 sealed store 下**禁止** LEGACY fallback：

```text
store_metadata 缺失 / malformed
integrity_mode 被篡改
trust_anchor_sealed 被篡改（anchor 仍存在 -> 不一致 -> BLOCK）
authorities/ 缺失
ledger manifest 缺失
trust anchor 缺失
trust anchor mismatch
store_digest / authority_manifest / revocation_manifest mismatch
```

只有“从未 seal 的 store”允许 legacy semantics；一旦 seal，
“从未 hardened”这个声明必须由外部 anchor 的存在性来支持。

---

## 10. Recovery

```text
禁止：自动 fallback 到 legacy
禁止：自动重建 authority
禁止：自动“修复” trust anchor（seal 是 create-only）
```

恢复路径（全部显式 operator 动作）：

```text
1. 从 trusted snapshot 恢复 adoption_store.json + authorities/ + events。
2. 确认 anchor 不存在或来自 trusted backup。
3. 显式 seal_trust_anchor() 重新 seal（已存在则拒绝）。
4. 在 operator audit record 中记录动作（仓库当前无自动 audit 通道，
   由部署/人工记录）。
```

anchor 损坏时不允许 seal 覆盖（`TRUST_ANCHOR_ALREADY_EXISTS` /
`TRUST_ANCHOR_CORRUPTED`），必须显式移除/替换后由 operator 重新 seal。

---

## 11. Adversarial Tests

新增 `phase8.4.3/test_integrity_trust_anchor.py`（20 tests）与
`validate_integrity_trust_anchor.py`（standalone matrix）。

| # | 攻击 | sealed store 结果 |
| --- | --- | --- |
| 1 | delete store_metadata | INTEGRITY_STORE_CORRUPTED |
| 2 | mutate integrity_mode | INTEGRITY_STORE_CORRUPTED |
| 3 | delete authorities/ | INTEGRITY_STORE_CORRUPTED |
| 4 | mutate authority record | INTEGRITY_STORE_CORRUPTED |
| 5 | replace authority record entirely | INTEGRITY_STORE_CORRUPTED |
| 6 | delete revocation event | INTEGRITY_STORE_CORRUPTED |
| 7 | mutate revocation copy | INTEGRITY_STORE_CORRUPTED |
| 8 | mutate both revocation IDs | INTEGRITY_STORE_CORRUPTED |
| 9 | delete revocation | INTEGRITY_STORE_CORRUPTED |
| 10 | delete trust anchor | INTEGRITY_STORE_CORRUPTED |
| 11 | mutate trust anchor | INTEGRITY_STORE_CORRUPTED |
| 12 | store hash mismatch | INTEGRITY_STORE_CORRUPTED |
| 13 | authority manifest mismatch | INTEGRITY_STORE_CORRUPTED |
| 14 | revocation manifest mismatch | INTEGRITY_STORE_CORRUPTED |

每个攻击同时验证 Registry `promote()` 与 Runtime `adopt()`，全部
`ADOPTION_BLOCKED`，无 LEGACY fallback。

实际运行：

```text
python3 -m pytest docs/archaeology/unified-runtime/phase8.4.3 -q
  -> 20 passed
python3 -m pytest docs/archaeology/unified-runtime/phase8.1 \
       docs/archaeology/unified-runtime/phase8.2 \
       docs/archaeology/unified-runtime/phase8.3 \
       docs/archaeology/unified-runtime/phase8.4 -q
  -> 117 passed（历史回归不变）
python3 docs/archaeology/unified-runtime/phase8.4.3/validate_integrity_trust_anchor.py
  -> 28/28 PASS
python3 -m compileall -q pilot docs/archaeology/unified-runtime/phase8.4.3
  -> COMPILEALL_OK
```

---

## 12. FACT / INFERENCE / UNKNOWN

```text
FACT      代码强制 anchor 路径在 registry_root 之外
FACT      seal 是 create-only；已存在/损坏的 anchor 不被自动覆盖
FACT      sealed store 下 14 项攻击全部 fail closed（INTEGRITY_STORE_CORRUPTED）
FACT      删除 anchor 不降级 legacy（trust_anchor_sealed 检测）
FACT      未 seal 的 store 保持 8.4.2 legacy 语义
FACT      store_digest 绑定整个 store；authority/revocation manifest
          绑定 ledger 与事件日志

INFERENCE anchor 放在只读挂载 / 不同用户目录 / 外部服务时，
          构成真正的不同 trust domain，可证明原始状态

UNKNOWN   anchor 的物理写保护是否由部署提供
UNKNOWN   同一 OS 用户同时删除 seal 标记 + anchor（进程内不可检测）
UNKNOWN   密码学 issuer 真实性（无签名 / PKI / KMS）
UNKNOWN   OS 级 deletion resistance / WORM / 只读挂载
UNKNOWN   verify_at_mount() 与 bind-mount 解析之间的 OS 级微窗口
```

---

## 13. Residual Risks

```text
1. 同一 OS 用户可同时删除 trust_anchor_sealed 与 anchor 文件
   -> 进程内被解释为“从未 seal”的 legacy store。
   这是 TRUST_ANCHOR_PARTIAL 的核心原因；只有部署层写保护能闭合。
2. 默认 sibling anchor 与 store 同级可写，不是真 trust anchor；
   生产必须设置 PILOT_INTEGRITY_ANCHOR 到受保护路径。
3. 无密码学 issuer 签名，authority 真实性仍是 deterministic binding。
4. flat JSON 无事务/锁；多写者并发仍存在竞态（8.4 已标注 UNKNOWN）。
5. 无自动 recovery；anchor 损坏需要显式 operator 介入。
```

---

## 14. Next Step

如果后续要求 `TRUST_ANCHOR_VALID`：

```text
1. 部署 anchor 到只读挂载 / 不同 OS 用户目录 / 外部可信服务。
2. 重新运行 validate_integrity_trust_anchor.py 证明部署后攻击矩阵。
3. 若需要密码学 issuer：先引入真实 secret store / KMS，再在 anchor
   或 authority 上加签名；仓库当前没有自然落点，不在本阶段自造。
4. 若需要分布式一致性：仓库现有 SQLite 只有文档/设计，没有生产实现；
   属于大规模存储重构，超出本阶段边界。
```

然后 STOP；不进入 Phase 8.5，不接第二 Runtime / Langfuse / Cordis，
不执行 E.8。
