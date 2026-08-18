# Phase 9-B.1 Production Report

- 日期：2026-08-18
- 基线 commit：`1f6ee1c`（docs(architecture): close capability candidate contract）
- 范围：Canonical Artifact Identity V1 + Candidate Seal / Frozen Candidate 作为生产信任源
- 判定：**PHASE_9B1_CLOSED_WITH_UNKNOWN**

## 0. Phase 9-B.1.1 Legacy Downgrade Closure

- 判定：**PASS**（9-B.1.1 adversarial closure）
- 核心修改：canonical identity 从 caller-writable registry entry
  （`artifact_identity` / `frozen_root`）迁移到 **trust-anchored authority record**：

```text
issue_authority(frozen_root=...)
  -> authority.artifact_identity = CANONICAL_ARTIFACT_IDENTITY_V1
  -> authority.seal_digest = frozen record seal_digest
promote()
  -> canonical authority + frozen_root omitted      => REJECT
  -> legacy authority + frozen_root supplied        => REJECT
adopt()
  -> routing 只看 authority.artifact_identity
  -> canonical authority 缺少 entry marker / frozen_root / seal / frozen
     record => REJECT，绝不 fallback legacy
```

### Invariants

```text
CANONICAL_IDENTITY    = PASS  authority.artifact_identity + seal_digest（anchored）
FROZEN_TRUST_ROOT     = PASS  frozen record + verify_frozen + seal cross-check
CANONICAL_DIGEST      = PASS  canonical digest 全链一致，digest equality 不决定身份
LEGACY_COMPATIBILITY  = PASS  legacy issue/promote/adopt 保持 ALLOW
LEGACY_DOWNGRADE      = PASS  canonical -> legacy 关闭（promote/adopt 均 REJECT）
UNDECLARED_ARTIFACT   = PASS  exact layout 在 issue/promote/adopt 均 REJECT
FAIL_CLOSED           = PASS  canonical proof 缺失/篡改一律 REJECT，无 legacy fallback
```

### Exploit results

```text
Fresh candidate + frozen_root=None (issue / promote)
  Before: issue 或 promote 写入无 marker authority/entry -> adopt legacy ALLOW
  After:  CANONICAL_CANDIDATE_REQUIRES_FROZEN_ROOT -> REJECT
  Expected / Observed: REJECT, no store write / no registry entry written

Frozen record deletion
  Before: canonical lookup failure -> legacy branch ALLOW
  After:  MISSING_FROZEN_CANDIDATE -> REJECT
  Expected / Observed: REJECT

artifact_identity stripping
  Before: entry loses marker -> legacy branch ALLOW
  After:  authority still canonical; ARTIFACT_IDENTITY_MISMATCH -> REJECT
  Expected / Observed: REJECT

frozen_root stripping
  Before: entry loses frozen_root -> legacy branch ALLOW
  After:  MISSING_FROZEN_CANDIDATE -> REJECT
  Expected / Observed: REJECT

Undeclared artifact (declared A, actual A+B)
  Before: new candidate can enter legacy path; B silently included
  After:  canonical path UNDECLARED_ARTIFACT_FILE -> REJECT；
          legacy omission also REJECT（never legacy ALLOW）
  Expected / Observed: REJECT

Digest ambiguity
  Before: digest equality alone could be read as legacy-compatible
  After:  canonical identity（authority marker + seal_digest）独立成立；
          同 digest 的 legacy entry 仍 ALLOW，canonical entry 不降级
  Expected / Observed: canonical stays canonical, legacy stays legacy
```

### Tests

```text
Phase 9-B.1.1 targeted tests    PASS  （11 passed:
  test_legacy_downgrade_closure.py A-J）
Phase 9-B.1 suite               PASS  （53 passed + 6 subtests）
Full test suite                 PASS  （831 passed, 11 skipped,
                                       19 subtests passed）
Production harness              PASS  （live phase_future("b3") with real
                                       Docker in temp state:
                                       HARNESS_LIVE_B3_PASS）
```

### Changed files (9-B.1.1)

```text
pilot/adoption_authority_producer.py
pilot/registry.py
pilot/runtime_adoption_guard.py
docs/archaeology/unified-runtime/phase9b1/test_legacy_downgrade_closure.py
docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py
  （legacy fixture 移除 source_bundle_ids，使其成为真正的 historical legacy
     candidate）
docs/archaeology/unified-runtime/phase9b1/phase9b1-production-report.md
```

### Known boundary

```text
canonical 身份锚定在 trust-anchored authority record。若攻击者能同时改写
adoption_store.json + authorities/ + trust anchor（OS-level / 未 seal 的
store），不在本应用层防御范围；sealed store 下由 integrity anchor 拦截。
issue 边界用 candidate.json.source_bundle_ids（capabilityize 新候选标记）
拒绝 new candidate 以 legacy 身份签发；该字段在 capabilityize 产出后写入，
若攻击者在 issue 前篡改 candidate 目录本身，属于 intake 信任边界之外。
```

## 1. 本轮修复的 P1/P2/P3

```text
P1-1  Evaluation Binding 从"只写入"变为"验证"：
       issue_authority / promote / runtime 全部调用同一
       capabilityizer.evaluation_binding_violations()；
       candidate_id / artifact_digest / seal_digest 任一不一致即 BLOCK。

P1-2  B3 生产路径真正消费 Frozen Candidate：
       phase_b3_build 在 validate/evaluate 前 freeze；
       phase_future(b3) 经 registry entry.frozen_root 解析 frozen record，
       verify_frozen -> evaluation binding -> canonical digest ->
       exact layout -> 既有 runtime guard -> verify_at_mount -> docker_launch。

P2    Canonical digest 收敛：新 Candidate 全链只使用
       CANONICAL_ARTIFACT_IDENTITY_V1；
       legacy helper 改名为 legacy_dir_digest，不参与新路径绑定。

P3    bind_evaluation 三字段冲突 -> EVALUATION_BINDING_CONFLICT，
       不再 silent overwrite。
```

## 2. RED -> GREEN

```text
RED tests  docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py
          （18 failed at RED，覆盖 14 个要求场景 + harness 实路径）

1  evaluation A + artifact B   -> EVALUATION_BINDING_MISMATCH (issue/promote/runtime)
2  evaluation A + manifest B   -> live manifest swap -> FROZEN_CANDIDATE_MISMATCH
3  evaluation A + tests B      -> live tests swap -> TESTS_CHANGED_AFTER_SEAL
4  evaluation A + seal B       -> EVALUATION_BINDING_MISMATCH
5  frozen candidate mutation   -> NEW_CANDIDATE_REQUIRED (runtime BLOCK)
6  undeclared file before issue   -> UNDECLARED_ARTIFACT_FILE
7  undeclared file before promote -> UNDECLARED_ARTIFACT_FILE
8  undeclared file before runtime -> UNDECLARED_ARTIFACT_FILE
9  B3 reads frozen candidate   -> 删除 frozen record 后 phase_future 必须 BLOCK；
                                  未删除时正常 activate
10 delete frozen record + re-seal -> FROZEN_CANDIDATE_INCOMPLETE /
                                     FROZEN_CANDIDATE_DELETED
11 bind_evaluation conflict    -> EVALUATION_BINDING_CONFLICT
12 canonical vs legacy mismatch-> runtime ARTIFACT_DIGEST_MISMATCH
13 new Candidate no legacy fallback -> UNDECLARED_ARTIFACT_FILE 且无
                                       ARTIFACT_DIGEST_MISMATCH
14 historical legacy candidate -> legacy issue/promote/adopt 仍 ALLOW
```

## 3. 生产变更

```text
src/forge/capabilityizer.py
  freeze_candidate：write-once + 引用感知 delete/recreate 防护
  frozen_checks / verify_frozen / load_frozen_candidate_snapshot
  evaluation_binding_violations（唯一 binding semantics）
  frozen_artifact_violations / live_candidate_violations（exact layout + canonical digest）
  bind_evaluation 三字段 conflict fail-closed
  referenced_candidate_ids / freeze_candidate_dir(registry_root=...)

pilot/adoption_authority_producer.py
  issue_authority(frozen_root=...)：
    新路径 = frozen record + evaluation binding + live candidate 校验，
    decision/run/authority 全用 frozen canonical artifact_digest；
    frozen_root=None = legacy Phase 8 路径不变。

pilot/registry.py
  promote(frozen_root=...)：新路径先 frozen/eval/layout 校验，再 validate；
    entry 写入 artifact_identity=CANONICAL_ARTIFACT_IDENTITY_V1 + frozen_root。

pilot/runtime_adoption_guard.py
  adopt / verify_at_mount：entry marker 为 canonical 时强制
    frozen record -> evaluation binding -> canonical digest + exact layout
    -> 既有 runtime guard；legacy entry 无 marker 走 legacy。

pilot/harness.py
  phase_b3_build：capabilityize -> freeze -> validate -> evaluate ->
    bind_evaluation -> issue_authority(frozen_root) -> promote(frozen_root)
  phase_future(b3)：registry.discover -> adopt -> verify_at_mount -> docker_launch
  legacy harness digest 改名 _legacy_dir_digest
```

## 4. 真实调用链证明（exact function / file / call site）

```text
phase_b3_build：
  Coding Agent -> capabilityize
    src/forge/capabilityizer.py:596 def capabilityize
  -> Frozen Candidate
    pilot/harness.py:589 freeze_candidate_dir(cand, self.state/"frozen_candidates",
                                              registry_root=self.registry_root)
    src/forge/capabilityizer.py:534 def freeze_candidate_dir
    src/forge/capabilityizer.py:205 def freeze_candidate
  -> Evaluation + Binding
    pilot/harness.py:608 bind_evaluation(evaluation, frozen["record"]["candidate_id"],
                                         artifact_digest, seal_digest)
    src/forge/capabilityizer.py:465 def bind_evaluation
  -> Authority
    pilot/harness.py:621 producer.issue_authority(..., frozen_root=...)
    pilot/adoption_authority_producer.py:97 def issue_authority
    新路径校验：:162 frozen_checks / :165 evaluation_binding_violations /
               :166 live_candidate_violations
  -> Registry
    pilot/harness.py:628 registry.promote(..., frozen_root=...)
    pilot/registry.py:69 def promote
    新路径校验：:99 frozen_checks / :102 evaluation_binding_violations /
               :103 live_candidate_violations

phase_future(b3)：
  Registry Entry
    pilot/harness.py:689 entry = registry.discover(...)
  -> Frozen Candidate resolve + verify_frozen
    pilot/harness.py:742 runtime_guard.adopt(self.registry_root, entry, artifact_dir)
    pilot/runtime_adoption_guard.py:297 def adopt
    :367 frozen_checks -> src/forge/capabilityizer.py:367
      （内部 verify_frozen :315）
  -> Evaluation Binding
    pilot/runtime_adoption_guard.py:370 evaluation_binding_violations
  -> Canonical Artifact + Exact Layout
    pilot/runtime_adoption_guard.py:374 frozen_artifact_violations
    src/forge/capabilityizer.py:408
  -> 既有 Runtime Guard
    pilot/runtime_adoption_guard.py:380 violations_for_runtime_activation(...)
  -> verify_at_mount
    pilot/harness.py:748 runtime_guard.verify_at_mount(...)
    pilot/runtime_adoption_guard.py:395 def verify_at_mount（fresh adopt + digest compare）
  -> docker_launch
    pilot/harness.py:750 invoke = docker_launch(...)
    mounts 使用同一 artifact_dir：(artifact_dir, "/artifact", True)
```

## 5. 生产状态矩阵

| Property | Status |
|---|---|
| Canonical artifact digest | FACT：capabilityize / freeze / decision / authority / registry / runtime 新路径全用 CANONICAL_ARTIFACT_IDENTITY_V1 |
| Exact layout at issue | FACT：live_candidate_violations 在 issuance 前执行 |
| Exact layout at promote | FACT：promote 写入前重新执行 |
| Exact layout at runtime | FACT：adopt + verify_at_mount 在 docker_launch 前重新执行 |
| Candidate seal | FACT：write-once freeze + verify_frozen；mutation -> NEW_CANDIDATE_REQUIRED |
| Evaluation binding | FACT：三字段一致才 ALLOW，issue/promote/runtime 同一 helper |
| Authority binding | FACT：authority/decision/run/candidate/entry 全链同 canonical digest，validate 交叉校验 |
| Frozen Candidate consumption | FACT：producer/registry/runtime/harness 均读取 frozen record |
| B3 frozen source of truth | FACT：phase_future(b3) 经 entry.frozen_root 强制消费，缺失即 BLOCK |
| Legacy compatibility | FACT：267 个 phase7.2-8.5 测试全绿；无 marker entry 走 legacy 路径 |
| Delete/recreate resistance | FACT（应用层）：引用存在时 re-seal -> FROZEN_CANDIDATE_DELETED；部分删除 -> FROZEN_CANDIDATE_INCOMPLETE；OS-level delete resistance = UNKNOWN |
| TOCTOU | PARTIAL：verify_at_mount 关闭 mount 前替换窗口；多进程 freeze 的 record/snapshot 非单一原子操作（fail-closed 检测已实现）；OS bind-mount race = UNKNOWN |

## 6. UNKNOWN（明确不声称）

```text
- WORM / DB / transactional storage：未实现；当前是 O_EXCL/hard-link 文件存储。
- external storage durability：无完整 fsync 链、无备份/恢复测试。
- OS-level adversary（root / bind mount / 介质替换）：不在防御范围。
- 多进程 freeze TOCTOU：record 与 snapshot 非单一原子操作，
  但 FROZEN_CANDIDATE_INCOMPLETE fail-closed 检测存在。
- Phase 8 legacy dir_digest（pilot/adoption_authority.py）保留字节不变，
  仅在无 canonical marker 的历史 entry 使用。
- 9-B.2 capability_id migration / Governance / OCI / Marketplace 未做。
```

## 7. 回归

```text
pytest phase9b1 -q                         42 passed + 6 subtests
pytest phase9a1 -q                         53 passed
pytest phase7.2 phase7.3 phase7.4 phase7.5
       phase7.6 phase8 phase8.1 phase8.2
       phase8.3 phase8.4 phase8.4.3 phase8.5  267 passed
pytest tests/test_minimal.py               11 passed
compileall src/ pilot/ phase9a1/ phase9b1/   clean
```

## 8. Git 边界

```text
修改：src/forge/capabilityizer.py、pilot/harness.py、
      pilot/adoption_authority_producer.py、pilot/registry.py、
      pilot/runtime_adoption_guard.py
新增：phase9b1/test_production_trust_chain.py + 既有 phase9b1 tests/docs
未触碰：Phase 7-8.5 historical artifacts、codex/、control-plane/、
       deepseek-harness/、openhands/、48*、51*、52*、53*
```

未 commit / 未 push。
