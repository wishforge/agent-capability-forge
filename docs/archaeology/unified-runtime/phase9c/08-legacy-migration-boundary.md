# Phase 9-C.08 — Legacy / Migration Boundary

基线：`a70a433`。legacy 与 canonical 分开审计，不混为一谈。

## 1. Legacy Chain（历史语义，保持 ALLOW）

```text
Legacy Candidate（无 source_bundle_ids 或历史 Phase 8 状态）
    ↓ legacy issue（frozen_root=None, dir_digest）
Legacy Authority
    ↓ legacy promote（无 frozen_root）
Legacy Registry Entry（无 artifact_identity marker）
    ↓ b3_entry locator
Legacy Adoption（legacy_dir_digest 分支）
    ↓
Runtime
```

代码事实：

- issue_authority frozen_root=None 分支：adoption_authority_producer.py:158-164
- promote legacy 分支：registry.py:136-138
- adopt legacy 分支：runtime_adoption_guard.py:518-520
- harness legacy 运行路径：harness.py:706-718（run_request 不存在时）
- 回归：phase9b1 test_h/test_i + phase9b5 test_i 全部 ALLOW

## 2. Canonical 不能 downgrade to legacy

已由 9-B.1.1 关闭，本轮复核不重复修改：

| 攻击 | 结果 |
|---|---|
| canonical authority + 缺 frozen_root at issue/promote | `CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT` |
| entry 剥 artifact_identity marker | `ARTIFACT_IDENTITY_MISMATCH` |
| entry 剥 frozen_root | `MISSING_FROZEN_CANDIDATE` |
| canonical entry + run_request 缺失 | `MISSING_RUN_REQUEST`（harness.py:713-717） |
| frozen record 删除 | `MISSING_FROZEN_CANDIDATE` / `FROZEN_CANDIDATE_DELETED` |

## 3. 当前 pilot/state 状态

实测：

```text
pilot/state/b3_entry.json            = v1 旧格式（仅 name + capability_id）
pilot/state/registry/F+/<name>.json  = promoted，但无 adoption / artifact_identity /
                                       frozen_root 段
pilot/state 无 adoption_store.json
```

对当前 state 直接 `phase_future("b3")` 会因 adopt 要求 adoption_store 而
`MISSING_ADOPTION_STORE`（9-B.5 报告已记录）。该 state 是 9-B.1 之前的 historical
fixture，不是 canonical 状态。

## 4. 分类

```text
pre-existing legacy pilot/state
  = B. migration gap（历史状态，非 canonical 信任链）
    + C. test fixture gap（用于回归 legacy 语义）
    + D. expected historical state（Phase 9-B.2 O4 处置对象）
  ≠ A. security gap

MISSING_ADOPTION_STORE
  = migration gap / expected historical state
```

## 5. 本轮新记录的 legacy 事实

Legacy 路径不校验 evaluation binding：probe 实测
`Evaluation(cand-LA) → issue/promote(cand-LB)` 得 `AUTHORITY_ISSUED`。这是历史
语义（9-B.1.1 冻结“legacy 保持 ALLOW”），不影响 canonical 信任；若未来要收紧
legacy 入口，属于 Phase 9-B.2 O4 范围，不在 Phase 9-C。

## 6. 结论

```text
Legacy = compatibility boundary
Canonical = trusted boundary
MIGRATION = NON-BLOCKING（不阻塞 canonical trust closure；单独阶段可选）
```
