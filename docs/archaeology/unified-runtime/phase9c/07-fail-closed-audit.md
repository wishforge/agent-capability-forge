# Phase 9-C.07 — Fail-Closed Audit

基线：`a70a433`。逐项检查 `fallback / legacy / default / infer / guess / else: /
except`，只判定“该路径是否改变 Candidate selection”。

## 1. 判定表（pilot + src/forge，排除 state/历史产物）

| 位置 | 行为 | 是否改变候选选择 | 判定 |
|---|---|---|---|
| runtime_adoption_guard.py:352 `return None`（无 adoption store） | legacy fixture 语义；canonical entry 随后 MISSING_RUN_REQUEST | 否（canonical 禁止推断） | CLOSED |
| runtime_adoption_guard.py:394-413 cache missing → rebuild | 从 anchored run_request 重建；重读比对 | 否（目标不变） | CLOSED（明确允许 rebuild，非 infer） |
| runtime_adoption_guard.py:518-520 legacy digest 分支 | 仅 entry 无 canonical marker 时使用 | 否（canonical 先拒绝） | CLOSED（兼容边界） |
| adoption_authority.py:124 unsealed store → 不校验 anchor | 未 seal 的 store 保持 legacy 语义；sealed 后任何不一致 REJECT | 否 | CLOSED（文档化部署契约） |
| adoption_authority.py:281 issuer allowlist 未设置 → 放行 | deterministic-binding 模式，issuer UNKNOWN | 否（不影响候选身份） | CLOSED（GAP-3 边界） |
| adoption_authority_producer.py:183 `except Exception` | 任意坏 candidate → `CANDIDATE_METADATA_MISSING` BLOCK | 否 | CLOSED |
| registry.py:112 / 136 legacy branch | frozen_root 未提供时 legacy 校验 | 否（canonical authority 缺 frozen_root 先 REJECT） | CLOSED（兼容边界） |
| harness.py:706-718 run_request=None → b3_entry 路径 | 仅 legacy entry；canonical entry 直接 `MISSING_RUN_REQUEST` | 否（canonical 拒绝） | CLOSED |
| sandbox.py:34 TimeoutExpired → kill | 超时 fail；不执行代码 | 否 | CLOSED |
| capabilityizer.py:287/294 freeze 文件冲突 | `FROZEN_CANDIDATE_CONFLICT` / `FROZEN_CANDIDATE_INCOMPLETE` | 否 | CLOSED |
| capabilityizer.py:395/453/464/512/532 读取异常 | BLOCK（MISSING_FROZEN_CANDIDATE / FROZEN_CANDIDATE_INCOMPLETE） | 否 | CLOSED |

## 2. Canonical 关键失败路径

| 失败 | 语义 |
|---|---|
| identity verification failure | `CANDIDATE_ID/VERSION/ARTIFACT_DIGEST/SEAL_DIGEST_MISMATCH` / `MISSING_IDENTITY` → REJECT |
| run intent verification failure | `MISSING_RUN_REQUEST` / `INTEGRITY_STORE_CORRUPTED` → REJECT |
| registry mismatch | cache mismatch 或 identity mismatch → REJECT |
| cache mismatch | `RUN_REQUEST_CACHE_MISMATCH` → REJECT |
| artifact mismatch | `ARTIFACT_DIGEST_MISMATCH` / `UNDECLARED_ARTIFACT_FILE` / allowlist 错误 → REJECT |
| frozen 缺失/篡改 | `MISSING_FROZEN_CANDIDATE` / `FROZEN_CANDIDATE_INCOMPLETE` / `NEW_CANDIDATE_REQUIRED` → REJECT |
| mount source 不一致 | `RUNTIME_BINDING_MISMATCH` → REJECT |

无任何 fallback / infer / guess 路径改变候选选择。`except` 全部 fail-closed
（BLOCK 或 REJECT），不降级到另一候选。

## 3. 结论

```text
FAIL_CLOSED = PASS（canonical）
```
