# 75 — Phase 8.4.1 Integrity Closure（P1/P2 修复）

> 阶段：Phase 8.4.1（Phase 8.4 独立 Review 发现的完整性缺陷收口）。
> 基线：74（Phase 8.4，INTEGRITY_HARDENING_VALID_WITH_UNKNOWN）。
> 约束遵守：历史 Phase 7–8.3 artifacts 未修改；未启动 8.5；未接第二
> Runtime / Langfuse；未做 E.8 / production-wide rollout；未 commit / push。

## 0. 结论

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

两个真实缺陷已修复并有回归测试证明：

```text
FACT   write-once ledger（不变）
FACT   fail-closed registry（不变）
FACT   fail-closed runtime（修复后：hardened store 下 ledger 缺失 -> BLOCK）
FACT   load-bearing store revocation copy（修复后：events 缺失仍 BLOCK）
FACT   verify_at_mount()（继承 adopt() 同一 ledger 规则）

UNKNOWN（本次修复不改变）
  OS-level deletion resistance（删除整个 authorities/ 目录会降级 legacy 模式）
  cryptographic issuer trust（无签名 / PKI）
  full WORM
  distributed TOCTOU elimination（recheck 与 bind-mount 解析之间微窗口）
```

---

## 1. P1 Finding

`pilot/runtime_adoption_guard.py` `adopt()`：

```text
file_authority = load_authority_record(...)  # ledger 记录
authority = file_authority if file_authority is not None else store_authority
```

hardened store（`authorities/` 目录存在）下，ledger 记录缺失时
`file_authority is None`，代码错误 fallback 到 `store["authorities"]`
派生副本。删除 `authorities/<id>.json` 后 Runtime 仍可 ALLOW，
与 `registry.promote()` 的 UNISSUED_AUTHORITY 规则不一致
（Registry block 但 Runtime allow）。

## 2. P2 Finding

`pilot/adoption_authority.py` `revoke_authority()`：

```text
event = {... "promotion_decision_id": record["promotion_decision_id"], ...}
```

事件与 store["revocations"] 副本写入 `promotion_decision_id`，但
`violations_for_authority()` 与 `violations_for_runtime_activation()` 的
revocation 匹配只读 `decision_id`：

```text
r.get("decision_id") == decision.get("decision_id")
```

字段语义分裂：events 文件存在时靠事件阻断，events 文件被删除后
store revocation copy 因 `decision_id` 缺失永远不匹配 -> 不生效
（REVOKED 后删 events 文件可恢复 ALLOW）。

## 3. Fixes

### 3.1 P1 — Runtime ledger 缺失必须 BLOCK（runtime_adoption_guard.py）

`adopt()` 在 file/store 不一致检查之前新增 hardened-store ledger 规则：

```python
if (registry_root / "authorities").is_dir() and file_authority is None:
    raise AdoptionBlocked(
        [{"code": "UNISSUED_AUTHORITY",
          "message": f"no immutable ledger record for authority {aid}"}])
```

- hardened store 判定与 `registry.promote()` 使用同一个显式信号：
  `(registry_root / "authorities").is_dir()`；不是“文件不存在”推断。
- hardened 模式：ledger record 是唯一 authority anchor，缺失 -> BLOCK，
  禁止 fallback 到 `store["authorities"]`。
- legacy 模式（无 `authorities/` 目录）：保留 Phase 8.2 历史语义
  （store 派生副本兜底）。
- `verify_at_mount()` 直接调用 `adopt()`，自动继承同一规则。

### 3.2 P2 — revoke_authority() 写 canonical decision_id（adoption_authority.py）

```python
# canonical decision binding; validation matches on decision_id only
"decision_id": record["decision_id"],
# legacy mirror, same value; kept only for old readers
"promotion_decision_id": record["promotion_decision_id"],
```

- canonical 字段统一为 `decision_id`（与 authority record / store
  authorities / Phase 8.2 fixtures 一致）。
- `promotion_decision_id` 仅保留为同值 legacy mirror，二者不再有语义分歧。
- 写 store copy 前增加显式 normalization 层：旧副本只有
  `promotion_decision_id` 时补写 `decision_id`；校验路径不引入
  `OR promotion_decision_id / decision_id` 模糊匹配。

## 4. Before / After

### P1

| 场景 | Before | After |
| --- | --- | --- |
| hardened store，删除 `authorities/<id>.json` | Runtime ALLOW（store 副本兜底） | `UNISSUED_AUTHORITY` -> ADOPTION_BLOCKED |
| hardened store，删除 ledger + 改写 store authority | ALLOW（store 副本自洽） | `UNISSUED_AUTHORITY` -> ADOPTION_BLOCKED |
| legacy store（无 `authorities/`） | store 副本兜底 | 不变（历史兼容） |

### P2

| 场景 | Before | After |
| --- | --- | --- |
| revoke 后 events 文件存在 | `REVOKED_DECISION`（事件路径） | 不变 |
| revoke 后删除 events 文件 | store copy 无 `decision_id`，不匹配 -> ALLOW | store copy 带 `decision_id` -> `REVOKED_DECISION` |
| store copy 只含 `decision_id`（无 legacy mirror） | 匹配 | 匹配（canonical 字段） |
| 篡改事件或副本之一 | 另一路径仍阻断（偶然） | 任一显示撤销 / 事件损坏 -> FAIL CLOSED |

## 5. New Invariants G8–G10

```text
G8   Hardened store + missing ledger -> ADOPTION_BLOCKED
     （Registry UNISSUED_AUTHORITY 已有；Runtime adopt() /
     verify_at_mount() 本次补上）
G9   Hardened store + revoked store record -> ADOPTION_BLOCKED
     （events 文件缺失时 store copy 仍 load-bearing）
G10  Revocation event / store copy schema 共享 canonical decision_id
     （校验只匹配 decision_id；promotion_decision_id 仅为同值 legacy mirror）
```

三个 invariant 均有 machine-checkable 测试（见 §6）。

## 6. Tests

新增于 `phase8.4/test_authority_artifact_integrity_hardening.py`：

```text
G8  test_invariant_g8_missing_ledger_blocks_runtime
    删除 ledger，store/candidate/artifact 全不变 -> adopt 与
    verify_at_mount 均 UNISSUED_AUTHORITY，且不是 ARTIFACT_DIGEST_MISMATCH
G8  test_invariant_g8_ledger_deleted_store_rewritten_still_blocks
    adversarial：ledger 删除 + store authority 改写仍 BLOCK
G9  test_invariant_g9_store_revocation_copy_is_load_bearing
    revoke -> store copy 有 decision_id -> 删除 events -> adopt /
    verify_at_mount 均 REVOKED_DECISION
G9  test_invariant_g9_registry_does_not_allow_without_events_file
    revoke -> 删除 events -> registry.promote() 仍 REVOKED_DECISION
G10 test_invariant_g10_revocation_schema_uses_canonical_decision_id
    event 与 store copy 均写 decision_id == promotion_decision_id；
    删除 events + 删除 legacy mirror 后 store copy 仍阻断
其它 test_rewritten_store_authority_blocks_runtime
    改写 store["authorities"] -> AUTHORITY_BINDING_MISMATCH
其它 test_mutated_entry_binding_blocks_runtime
    改写 entry adoption binding -> ENTRY_BINDING_MISMATCH
其它 test_incomplete_adoption_on_hardened_store_blocks
    adoption 字段缺失 -> 仍 BLOCK（不崩溃、不 fallback）
其它 test_mutated_revocation_artifacts_still_block（3 参数）
    event status 改 ISSUED / store copy decision_id 改写 /
    events 文件损坏 -> 全部 FAIL CLOSED
```

## 7. Adversarial Verification

```text
delete authority ledger                  -> UNISSUED_AUTHORITY   BLOCK
delete ledger + rewrite store authority  -> UNISSUED_AUTHORITY   BLOCK
delete events file                       -> REVOKED_DECISION     BLOCK
mutate revocation event                  -> REVOKED_DECISION     BLOCK
mutate store revocation record           -> REVOKED_DECISION     BLOCK
mutate candidate binding (entry)         -> ENTRY_BINDING_MISMATCH BLOCK
mutate artifact digest                   -> ARTIFACT_DIGEST_MISMATCH BLOCK
合法路径（同 authority 重复 adopt / mount）-> ALLOW（回归不变）
```

实际运行：

```text
pytest docs/archaeology/unified-runtime/phase8.4 -q
  -> 32 passed
pytest docs/archaeology/unified-runtime/phase8.3 \
       docs/archaeology/unified-runtime/phase8.4 -q
  -> 44 passed
pytest phase7.2..phase8.4 全量回归
  -> 233 passed
compileall
  -> COMPILEALL_OK
```

未运行 live LLM / provider。

## 8. Remaining UNKNOWN

本次修复不改变以下 UNKNOWN：

```text
OS-level deletion resistance
  - 删除 authorities/<id>.json 被应用层阻断；
  - 删除整个 authorities/ 目录会把 hardened 模式降级为 legacy
    （未实现 WORM / 只读挂载 / 目录级防删除）。
cryptographic issuer trust
  - 仍为 deterministic binding + 可选 allowlist，无签名 / PKI / KMS。
full WORM
  - 应用层 write-once，非介质级。
distributed TOCTOU elimination
  - verify_at_mount() 与 docker bind-mount 解析之间仍有 OS 级微窗口。
```

## 9. Final Verdict

```text
INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
```

```text
写一次 ledger                    FACT
fail-closed registry             FACT
fail-closed runtime              FACT（本次修复）
load-bearing store revocation    FACT（本次修复）
verify_at_mount()                FACT（与 adopt() 同一 ledger 规则）
```

未 commit / push。历史 artifacts（E.5–E.7.1、Phase 7–8.3、48/51/52/53、
codex/control-plane/openhands）未修改。
