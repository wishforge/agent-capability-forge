# 76 — Integrity Mode Marker & Revocation Read Normalization（Phase 8.4.2）

> 阶段：Phase 8.4.2（Phase 8.4 final review 发现的两个残余问题收口）。
> 基线：75（Phase 8.4.1，INTEGRITY_HARDENING_VALID_WITH_UNKNOWN）。
> 约束遵守：未进入 Phase 8.5；未接第二 Runtime / Langfuse / Cordis；未修改
> E.5–E.7.1 或历史 Phase 7–8.3 artifacts；未 commit / push。

## 0. 结论

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

```text
FACT   hardened marker 被真实校验
       （store_metadata.integrity_mode = "hardened"，不是目录存在性）
FACT   revocation legacy shape 可以 read-side normalize
       （仅 promotion_decision_id 的历史副本仍可识别 revoked）

UNKNOWN
  OS-level deletion protection（物理删除文件 / 目录仍可能）
  WORM / 只读挂载 / 目录级防删除
  cryptographic issuer（无签名 / PKI）
  distributed durability（单机 flat JSON + file-per-authority）
  final TOCTOU micro-window（verify_at_mount 与 bind-mount 解析之间）
```

## 1. P2 Finding

`pilot/registry.py promote()` 与 `pilot/runtime_adoption_guard.py adopt()`
此前用：

```python
(registry_root / "authorities").is_dir()
```

作为 hardened-mode 信号。攻击者 `rm -rf authorities/` 后：

```text
registry.promote()  目录不存在 -> 跳过 UNISSUED_AUTHORITY 检查 -> ALLOW
runtime.adopt()     目录不存在 -> 跳过 ledger 锚定规则 -> fallback 到
                    store["authorities"] -> ALLOW
```

安全模式因为安全基础设施本身被删除而自动降级为 legacy，store 派生副本被信任。

## 2. P3 Finding

`revoke_authority()` 对旧 store copy 做 write-side normalization（补写
`decision_id`），但 read-side validation 仍只匹配：

```python
r.get("decision_id") == decision.get("decision_id")
```

历史 foreign/legacy copy：

```json
{"promotion_decision_id": "...", ...}
```

在 events 文件删除后无法识别 revoked。write-side normalization 只在
revoke 时覆盖当时存在的副本；之前已存在的 / 外来的 legacy-only 副本仍漏检。

## 3. 设计：显式 hardened-mode marker

仓库此前没有自然的 store schema / mode 元数据，因此增加最小 marker：

```json
{
  "store_metadata": {
    "schema_version": "adoption_store_v2",
    "integrity_mode": "hardened"
  }
}
```

写入点：`adoption_authority_producer.issue_authority()` 签发成功、store 即将
持久化时调用 `mark_store_hardened(store)`。规则：

```text
hardened store 一旦被初始化 -> integrity_mode = "hardened"
authorities/ 不存在 + integrity_mode == "hardened"
  -> INTEGRITY_STORE_CORRUPTED -> ADOPTION_BLOCKED（state 不变，不 fallback）
```

分类函数 `store_integrity_mode(store)`：

```python
metadata = store.get("store_metadata") or {}
return HARDENED_MODE if metadata.get("integrity_mode") == HARDENED_MODE \
    else LEGACY_MODE
```

## 4. Hardened / Legacy 区分

```text
legacy store    integrity_mode absent -> 保留 Phase 8.2 历史语义
                （store 派生副本兜底）
                明确分类：PRODUCTION_HARDENING_NOT_ESTABLISHED，不能声称 hardened

hardened store  integrity_mode == "hardened" -> 唯一 authority anchor 是 ledger
                authorities/ 目录缺失 / ledger 记录缺失 -> ADOPTION_BLOCKED
```

不再使用“没有 authorities/ 目录 -> legacy”的推断。

## 5. Revocation Read-Side Normalization

新增 `normalize_revocation_record(record)`（adoption_authority.py）：

```python
if not isinstance(record, dict):
    return None, "INVALID_REVOCATION_RECORD"
decision_id = record.get("decision_id")
promotion_id = record.get("promotion_decision_id")
if decision_id is not None and promotion_id is not None \
        and decision_id != promotion_id:
    return None, "REVOCATION_RECORD_CONFLICT"
if decision_id is None and promotion_id is None:
    return None, "INVALID_REVOCATION_RECORD"
return (decision_id if decision_id is not None else promotion_id), None
```

规则：

```text
decision_id 存在               -> canonical = decision_id
decision_id 缺失、promotion_decision_id 存在
                              -> canonical = promotion_decision_id
两者都存在但不同               -> REVOCATION_RECORD_CONFLICT -> ADOPTION_BLOCKED
两者都不存在 / 非 dict          -> INVALID_REVOCATION_RECORD -> fail closed
```

校验层只匹配 canonical decision_id，不使用：

```python
r["decision_id"] == decision_id or r["promotion_decision_id"] == decision_id
```

`revocation_violations()` 供 `violations_for_authority()`（Registry /
producer）与 `violations_for_runtime_activation()`（Runtime）共享，两个
read-side 路径行为一致。`revoke_authority()` 的 write-side normalization
保留；文档表述为 read-side + write-side normalization。

## 6. Adversarial Tests

新增于 `phase8.4/test_authority_artifact_integrity_hardening.py`：

```text
P2
  test_hardened_store_marker_written_and_preserved
    marker 写入并在 revoke_authority 整文件重写后保留
  test_delete_entire_authorities_dir_blocks_registry
    issue -> promote -> rm -rf authorities/ -> promote
    -> INTEGRITY_STORE_CORRUPTED（store["authorities"] 仍在，不 fallback）
  test_delete_entire_authorities_dir_blocks_runtime_and_mount
    同一快照 -> adopt() / verify_at_mount() -> INTEGRITY_STORE_CORRUPTED
  test_legacy_store_without_marker_keeps_legacy_semantics
    无 marker -> LEGACY_MODE / PRODUCTION_HARDENING_NOT_ESTABLISHED，
    promote + adopt 保持 legacy ALLOW

P3
  test_legacy_revocation_copy_only_promotion_decision_id_blocks_runtime
    revoke -> store copy 去掉 decision_id -> 删除 events
    -> adopt / verify_at_mount REVOKED_DECISION
  test_legacy_revocation_copy_only_promotion_decision_id_blocks_registry
    同一形状 -> Registry.promote() REVOKED_DECISION
  test_revocation_both_ids_equal_normalizes
    两者相等 -> canonical = decision_id，无错误 -> REVOKED_DECISION
  test_revocation_conflicting_ids_fail_closed
    decision_id != promotion_decision_id -> REVOCATION_RECORD_CONFLICT
    （Runtime + Registry）
  test_revocation_missing_ids_fail_closed
    双缺失 -> INVALID_REVOCATION_RECORD（Runtime + Registry）
```

## 7. Before / After

### P2

| 场景 | Before | After |
| --- | --- | --- |
| hardened store，删除整个 `authorities/` | 降级 legacy；Registry ALLOW、Runtime fallback store ALLOW | `INTEGRITY_STORE_CORRUPTED` -> ADOPTION_BLOCKED |
| hardened store，删除单个 ledger 文件 | Registry UNISSUED_AUTHORITY；Runtime 8.4.1 后 UNISSUED_AUTHORITY | 不变 |
| legacy store（无 marker） | store 副本兜底 | 不变（PRODUCTION_HARDENING_NOT_ESTABLISHED） |

### P3

| 场景 | Before | After |
| --- | --- | --- |
| revoke 后删除 events，store copy 只含 `promotion_decision_id` | 不匹配 -> ALLOW | read-side normalize -> `REVOKED_DECISION` |
| store copy 两个 ID 相等 | 匹配 decision_id | canonical 匹配，不变 |
| 两个 ID 不同 | 匹配失败可能 ALLOW | `REVOCATION_RECORD_CONFLICT` -> BLOCK |
| 两个 ID 都缺失 | 不匹配可能 ALLOW | `INVALID_REVOCATION_RECORD` -> BLOCK |

## 8. Remaining UNKNOWN

```text
OS-level deletion protection
  应用层用显式 marker 阻断目录删除后的降级；但拥有 FS 写权限者仍可物理
  删除 ledger / events / artifact 文件（WORM / 只读挂载未实现）。
WORM
  仍是应用层 write-once，非介质级。
cryptographic issuer
  deterministic binding + 可选 allowlist，无签名 / PKI / KMS。
distributed durability
  单机 flat JSON + file-per-authority；无复制 / 分布式一致性。
final TOCTOU micro-window
  verify_at_mount() 与 docker bind-mount 解析之间仍有 OS 级微窗口。
```

## 9. Verification

```text
python3 -m compileall -q pilot docs/archaeology/unified-runtime/phase8.3 \
  docs/archaeology/unified-runtime/phase8.4
  -> COMPILEALL_OK

python3 -m pytest docs/archaeology/unified-runtime/phase8.3 -q
  -> 12 passed
python3 -m pytest docs/archaeology/unified-runtime/phase8.4 -q
  -> 41 passed
python3 -m pytest phase7.2..phase8.4 全量回归 -q
  -> 224 passed
```

adversarial probes（全部 ADOPTION_BLOCKED）：

```text
authorities/ directory deletion     -> INTEGRITY_STORE_CORRUPTED
ledger record deletion              -> UNISSUED_AUTHORITY
store authority rewrite             -> AUTHORITY_BINDING_MISMATCH
legacy revocation copy              -> REVOKED_DECISION
conflicting revocation IDs          -> REVOCATION_RECORD_CONFLICT
missing revocation IDs              -> INVALID_REVOCATION_RECORD
```

## 10. Final Verdict

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

```text
write-once ledger                    FACT（不变）
fail-closed registry                 FACT（marker 修复）
fail-closed runtime                  FACT（marker 修复）
load-bearing store revocation        FACT（read-side + write-side normalization）
verify_at_mount()                    FACT（继承 adopt() 同一 marker 规则）
explicit hardened marker             FACT（本次新增，真实校验）
```

未 commit / push。历史 artifacts（E.5–E.7.1、Phase 7–8.3、48/51/52/53、
codex/control-plane/openhands）未修改。

STOP。
