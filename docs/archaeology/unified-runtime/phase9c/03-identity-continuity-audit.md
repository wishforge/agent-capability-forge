# Phase 9-C.03 — Candidate Identity Continuity Audit

基线：`a70a433`。追踪 `candidate_id` / `candidate_version` / `artifact_digest` /
`seal_digest` 在 Evaluation → Promotion → Authority → Run Intent → Adoption →
Runtime 的 producer / consumer / verification。

## 1. 全链追踪

| 阶段 | file | function | line range | producer | consumer | verification |
|---|---|---|---|---|---|---|
| 生成 | src/forge/capabilityizer.py | capabilityize | 609-674 | candidate_id（uuid）+ manifest + artifact bytes | freeze_candidate_dir | — |
| Freeze | src/forge/capabilityizer.py | freeze_candidate | 213-320 | frozen record：candidate_id/capability_id/name/version/artifact_digest/manifest_digest/tests_digest/seal_digest | issue/promote/adopt | seal_violations + artifact_layout + digest 重算 |
| Frozen verify | src/forge/capabilityizer.py | verify_frozen | 323-379 | — | frozen_checks | 字节全量重算：artifact/manifest/tests/seal |
| Evaluation | src/forge/evaluator.py | evaluate | 24-68 | evaluation 初始（含 candidate_id） | bind_evaluation | oracle 验证 |
| Evaluation bind | src/forge/capabilityizer.py | bind_evaluation | 478-498 | 三字段写入 evaluation | issue/promote/adopt | 冲突即 EVALUATION_BINDING_CONFLICT |
| Authority | pilot/adoption_authority_producer.py | issue_authority | 98-180 | decision/run/authority 四元组 | registry.promote / adopt | frozen_checks + evaluation_binding_violations + live_candidate_violations |
| Promotion | pilot/registry.py | promote | 69-252 | entry.adoption 透传 BINDING_KEYS | adopt | 重跑同一组校验；entry/adoption 全等 authority |
| Run Intent | pilot/runtime_adoption_guard.py | mark_promoted / _run_request | 566-625 / 329-341 | store["run_request"] 四元组 + promotion_decision_id | phase_future | 与 entry+authority 同源；store_digest 锚定 |
| Registry resolve | pilot/harness.py | phase_future | 698-705 | — | adopt | discover(run_request.name) |
| Adoption | pilot/runtime_adoption_guard.py | adopt | 416-535 | report 四元组 + verified_artifact_dir | verify_at_mount | authority/ledger/store/frozen/eval/layout/digest 全链 |
| Mount verify | pilot/runtime_adoption_guard.py | verify_at_mount | 538-564 | — | harness | identity_violations(expected=run_request, report) + expected_digest + mount_source |
| Runtime | pilot/harness.py | phase_future | 766-791 | — | docker_launch | 只使用 mount["verified_artifact_dir"] |

## 2. 是否丢失 identity component

Canonical 路径：**没有丢失**。四元组在每一阶段都存在：

```text
Evaluation:  (candidate_id=A, version=v1, digest=D, seal=S)   bind_evaluation 强制
Promotion:   (A, v1, D) + authority.seal_digest=S              entry.adoption 全等 authority
Authority:   (A, v1, D, S)                                     store + ledger 双份必须相等
Run Intent:  (A, v1, D, S)                                     store["run_request"]
Adoption:    (A, v1, D, S)                                     adopt report
Runtime:     D（+ expected identity 比对）                      verify_at_mount
```

关键点：Runtime 阶段看起来“只剩 digest=D”，但执行前 `verify_at_mount(
expected_identity=run_request)` 把四元组完整比对 adopt report，因此不会因“digest D
相同”就默认 identity A（phase9b3 Case D 实测：同 digest 不同 identity → REJECT）。

## 3. Legacy 路径差异（有意边界）

Legacy（frozen_root=None）不执行 evaluation_binding_violations：本轮 probe 实测
`Evaluation(cand-LA) -> issue/promote(cand-LB)` 得 `AUTHORITY_ISSUED`（candidate B）。
这是历史兼容语义（9-B.1.1 冻结），不是 canonical 信任链的一部分。新 candidate 有
`source_bundle_ids` 标记，legacy 签发被 `CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT`
拒绝。是否需要收紧 legacy 路径留给 Phase 9-B.2 O4 决策。

## 4. 结论

```text
IDENTITY_CONTINUITY = CLOSED（canonical）
LEGACY_BINDING = compatibility boundary（记录，不视为 canonical gap）
```
