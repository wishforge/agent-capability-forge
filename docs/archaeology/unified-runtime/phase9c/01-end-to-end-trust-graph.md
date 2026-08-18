# Phase 9-C.01 — End-to-End Trust Graph

- 日期：2026-08-18
- 基线：`a70a433`（fix(runtime): anchor canonical run intent）
- 范围：Candidate → Evaluation → Promotion → Authority → Trust Root → Run Intent → Registry → b3_entry → Adoption → Artifact Verification → Mount Verification → Runtime
- 方法：源码事实 + 既有 9-B.1/9-B.3/9-B.5 回归 + 本轮 /tmp probe
- 验证：`pytest -q` 当前基线 `859 passed, 11 skipped, 19 subtests passed`

## 1. Trust Graph

```text
Candidate
    ↓ Identity (candidate_id / name / version / bytes)
Evaluation
    ↓ Digest + Provenance (artifact_digest, seal_digest, evaluation_id)
Promotion
    ↓ Digest + Provenance (decision_id, authority)
Authority
    ↓ Digest + Provenance (seal_digest, decision/run, issuer)
Trust Root (external integrity anchor)
    ↓ Digest (store_digest + authority/revocation manifests)
Run Intent (adoption_store["run_request"])
    ↓ Identity + Digest (四元组 + promotion_decision_id)
Registry (F+/<name>.json entry)
    ↓ Reference (artifact_dir, frozen_root)
b3_entry.json (derived cache / locator)
    ↓ Reference (name 副本, 仅 cache 一致性)
Adoption (adopt())
    ↓ Verified (authority/ledger/frozen/eval/layout/digest)
Artifact Verification (frozen_artifact_violations)
    ↓ Digest (live bytes == frozen artifact_digest)
Mount Verification (verify_at_mount)
    ↓ Verified (expected identity == adopt report; mount_source == verified path)
Runtime (docker_launch)
```

## 2. Node Classification

| 节点 | 分类 | 依据 |
|---|---|---|
| Candidate（freeze 前目录） | Mutable | capabilityize 产出普通目录，尚无信任属性（capabilityizer.py:609-674） |
| Frozen Candidate | Verified + Immutable（应用层） | write-once record + snapshot；verify_frozen 全量重算（capabilityizer.py:213-320, 323-379）；OS 级删除/重写不在应用层范围 |
| Evaluation | Derived / Verified | evaluate 产出（evaluator.py:24-68），bind_evaluation 绑定三字段（capabilityizer.py:478-498） |
| Promotion | Derived / Verified | registry.promote 重跑 frozen/eval/layout 校验后写 entry（registry.py:69-252） |
| Authority | Immutable + Trusted | write-once ledger（adoption_authority.py:307-339）+ store 内 authority 记录，二者必须相等；sealed store 下被 anchor 覆盖 |
| Trust Root | Trusted（部署契约） | 外部 integrity anchor 文件；默认 sibling 不是真锚，受保护路径由部署提供（adoption_authority.py:90-99, 123-178；77 号报告 UNKNOWN） |
| Run Intent | Trusted（anchored） | `store["run_request"]` 进入 store_digest，由 write_trust_anchor 覆盖（runtime_adoption_guard.py:329-341, 566-625） |
| Registry entry | Locator / Mutable | 未锚定；adopt 每次重验 BINDING_KEYS + digest，单独篡改无法改变执行对象 |
| b3_entry.json | Locator / Cache / Mutable | 未锚定；canonical 路径只做 cache 一致性比对，无安全决策权（runtime_adoption_guard.py:380-413） |
| Adoption | Verified | adopt() 全链重验（runtime_adoption_guard.py:416-535） |
| Artifact Verification | Verified | frozen_artifact_violations 重算 live digest + exact layout（capabilityizer.py:421-439） |
| Mount Verification | Verified | verify_at_mount 再 adopt + expected identity/digest + mount_source（runtime_adoption_guard.py:538-564） |
| Runtime | Execution Decision（唯一入口） | harness phase_future("b3")；docker_launch 只接收 verified_artifact_dir（harness.py:683-810, 786-791） |

## 3. Edge Types

| 边 | 类型 | 证据 |
|---|---|---|
| Candidate → Evaluation | Identity + Digest | evaluate 运行 candidate 目录字节；bind_evaluation 写入 candidate_id/artifact_digest/seal_digest（capabilityizer.py:478-498） |
| Evaluation → Promotion | Identity + Digest + Provenance | issue_authority 先 frozen_checks + evaluation_binding_violations + live_candidate_violations（adoption_authority_producer.py:98-180） |
| Promotion → Authority | Identity + Digest + Provenance | decision/run/authority 同 digest；authority_id 确定性绑定（adoption_authority_producer.py:98-344） |
| Authority → Trust Root | Digest | integrity_anchor_violations 覆盖 store/authority/revocation manifests（adoption_authority.py:123-178） |
| Trust Root → Run Intent | Digest | run_request 在 store 内，进入 store_digest；sealed 后改写 → INTEGRITY_STORE_CORRUPTED（runtime_adoption_guard.py:343-377） |
| Run Intent → Registry | Reference | phase_future 用 run_request.name discover（harness.py:702）；name 是 locator 不是身份 |
| Registry → b3_entry | Reference | b3_entry 的 name 是 run_request.name 的派生副本；canonical 路径不以其为来源（runtime_adoption_guard.py:380-413） |
| b3_entry → Adoption | Reference（仅一致性） | resolve_b3_cache 只验证 cache == run_request；执行目标仍来自 run_request（runtime_adoption_guard.py:394-413） |
| Adoption → Artifact Verification | Digest | adopt 对 entry.artifact_dir 重算 canonical digest（runtime_adoption_guard.py:499-520） |
| Artifact Verification → Mount Verification | Digest | verify_at_mount 再 adopt + expected_digest 比对（runtime_adoption_guard.py:538-564） |
| Mount Verification → Runtime | Reference | harness 只把 mount["verified_artifact_dir"] 传给 docker_launch（harness.py:785-791） |

## 4. Source of Truth（单一 owner）

| 信任问题 | Owner | 位置 | 竞争者 |
|---|---|---|---|
| Candidate Identity | Frozen Candidate + Authority（seal_digest 锚定） | frozen record/snapshot（capabilityizer.py）+ authority（store/ledger） | 无：candidate.json / manifest 单独不能决定身份 |
| Run Intent | adoption_store["run_request"]（anchored） | runtime_adoption_guard.py:329-341, 566-625 | 无：registry / b3_entry 均不能选择候选 |
| Artifact Integrity | Frozen Candidate record + live 重算 | frozen_artifact_violations（capabilityizer.py:421-439） | 无：digest 只从字节重算 |
| Runtime Execution Decision | harness.phase_future("b3") canonical 分支 | harness.py:683-810 | 无：docker_launch 无第二条选择路径 |

结论：canonical 路径上不存在多个 competing owners。legacy 路径的 b3_entry/registry 仍承担选择职责，属于历史兼容边界（见 08 号报告）。
