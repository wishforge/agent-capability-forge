# Phase 9-D.3 Implementation Report — O1 Runtime Object Integrity Closure

- 日期：2026-08-19
- 基线：`6db07ce`（9-D.2 Design Freeze）
- 范围：Hybrid 方案实现（B = frozen execution snapshot；A = digest binding）
- 改动：`src/forge/capabilityizer.py`、`pilot/runtime_adoption_guard.py`、
  `pilot/harness.py` + Phase 9-D.3 targeted tests / live Docker probe；
  `sandbox.py`、`registry.py`、legacy、Run Intent、Authority schema 未改

## Verdict

```text
PASS_WITH_FINDINGS
```

O1 的 verify → mount TOCTOU 在 canonical 路径上已被闭合（E(D) 不可变 +
digest 绑定 + 仅 snapshot mount source）。但**部署级 owner isolation 在本机
未真实验证**：snapshot store owner = uid 501，本地 harness 用户 = uid 501
（same-writer boundary）。guard 对该配置 fail-closed
（`EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED`），因此不能判 PASS。

## O1 Closure

```text
CHECK_USE_WINDOW = CLOSED（canonical：verify E(D) -> mount E(D)；E(D) 不可变，
                   同 uid 也无法在 mode 下写入/rename/replace）
FILESYSTEM_OBJECT_BINDING = E(D) path + full digest + owner-isolation
                           （不再是 PATH-ONLY）
SNAPSHOT_IMMUTABILITY = ENFORCED
    atomic publish（tmp -> verify digest -> fsync -> chmod -> os.replace）
    目录 0555 / 文件 0444
    post-publish 无写路径
    verify_frozen full digest recompute 作为检测兜底
OWNER_ISOLATION = CODE-LEVEL ENFORCED / LOCAL DEPLOYMENT NOT PROVEN
    store owner != runtime user 是 guard 的强制前置条件
    本地 uid 501 == 501 -> guard REJECT（诚实 fail-closed）
    部署身份 65534 -> isolation check 通过（POSIX mode/owner 语义）
MOUNT_BINDING = E(D) only
    harness 只 mount frozen_root/frozen/<candidate_id>/artifact
    path mismatch -> RUNTIME_BINDING_MISMATCH REJECT
CONTAINER_OBSERVATION = A OBSERVED（5/5 攻击 blocked；18/18 race A；post-mount A）
```

## 实现摘要

### capabilityizer.py（freeze 发布）

1. 以 anchored `run_request.artifact_digest` 为最终预期 digest（记录侧不变）。
2. tmp snapshot 完整 materialize 后，对 materialized bytes 重新计算
   artifact/tests digest；不匹配则 BLOCK，不 publish。
3. `fsync` 文件后递归 chmod（目录 0555 / 文件 0444），再 `os.replace`
   原子发布；最终路径在 publish 前不存在（absent or complete）。
4. publish 后 record 0444、`frozen/` 与 store root 0555；owner 下一次 freeze
   会临时恢复 0755 写域并再次硬化（单写者 pilot 可接受；
   `ponytail:` 并发 freeze 未加锁，多写者时需 per-store 写锁）。

### runtime_adoption_guard.py（执行绑定）

1. canonical `adopt()` 的验证对象从 registry live copy 改为
   `E(D) = frozen_root/frozen/<candidate_id>/artifact`；
   `verified_artifact_dir` 只返回 E(D)。
2. 新增 `execution_snapshot_isolation_violations()`：要求 store owner !=
   runtime user、snapshot 子树无 runtime-user 写位、祖先链不可被
   runtime user rename/replace（sticky-bit 已考虑）。
3. `adopt()`/`verify_at_mount()` 默认 `runtime_uid=os.getuid()`；
   same-owner 部署 fail-closed，不 fake PASS。
4. `verify_at_mount()` 保持 `RUNTIME_BINDING_MISMATCH`：mount source 必须
   等于 verified E(D)。

### harness.py（mount source）

canonical b3 分支由 `run_request` 派生 E(D) 并作为唯一 mount source；
registry live path 不再进入 `docker_launch`。legacy 分支不变。

## Attack Matrix

| Attack | Before | Attack | Expected | Observed | Result |
|---|---|---|---|---|---|
| directory replacement | verify E(D)=A | `os.replace(B_dir, E(D))` | blocked or REJECT | PermissionError；container A | PASS |
| atomic rename | verify E(D)=A | rename E(D) → B at same path | blocked or REJECT | PermissionError；container A | PASS |
| symlink | verify E(D)=A | create symlink in E(D) → B | blocked or REJECT | PermissionError；container A | PASS |
| in-place mutation | verify E(D)=A | write B into E(D)/main.py | blocked or REJECT | PermissionError；container A | PASS |
| atomic file replacement | verify E(D)=A | `os.replace(B_file, main.py)` | blocked or REJECT | PermissionError；container A | PASS |
| same-path/different-inode | verify E(D)=A | replace E(D) with new inode B | never ALLOW B | denied；owner-simulated replace → `ARTIFACT_DIGEST_MISMATCH` REJECT | PASS |
| registry A→B | registry=A, E(D)=A | replace registry live artifact with B | runtime still A | container observed A（digest 匹配 E(D)） | PASS |
| snapshot A→B | E(D)=A | owner-simulated snapshot replace/tamper | REJECT | `ARTIFACT_DIGEST_MISMATCH` REJECT | PASS |

## Tests

| Suite | Result |
|---|---|
| Phase 9-D.3 targeted（`phase9d3/test_runtime_object_integrity.py`） | RED 15 failed（实现前）→ GREEN 15 passed |
| Phase 9-B.1 regression | 53 passed, 6 subtests passed |
| Phase 9-B.3 regression | 16 passed |
| Phase 9-B.5 regression | 12 passed |
| Phase 8.2 / 8.3 / 8.4 / 8.4.3 / 8.5 / tests/test_minimal.py | 129 passed |
| Full suite（`pytest -q`） | 874 passed, 11 skipped, 19 subtests passed |
| Live Docker（`phase9d3/live_docker_probe.py`，Docker 29.1.3 / macOS / aarch64） | 5/5 attacks blocked；0/5 B execution；registry A→B 仍观察 A |
| Natural race | 18/18 containers observed A；攻击线程 154,096 次尝试，0 次成功（由 mode/ownership 拒绝，非 race luck） |
| Post-mount mutation | 运行中容器 + host 5/5 mutation blocked；container digest == A |

## Deployment Contract

```text
EXECUTION_SNAPSHOT_STORE_OWNER = uid 501 (david, 本地 store owner)
RUNTIME_USER                  = 本地 harness 同一 uid 501
                               （deployment identity 65534 仅测试身份）
filesystem permissions        = store root 0555; frozen/ 0555;
                                frozen/<candidate_id>/ 0555;
                                artifact dir 0555; files 0444
ownership                     = owner != runtime user 由 guard 强制；
                                本机未以真实第二 OS 用户验证
```

诚实声明：

```text
本地无 passwordless sudo，无法创建/切换到真实 runtime 用户；
因此 owner isolation 的“真实第二身份”部署契约 remains unenforced。
chmod 0555/0444 单独不构成 proof：owner 仍可 chmod，guard 因此显式
reject same-owner（EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED）。
```

## Remaining Open

```text
Legacy O1 = SECURITY DEBT / NON-BLOCKING（legacy 路径语义未改）
Migration = NON-BLOCKING
Local owner isolation = NOT PROVEN（PASS_WITH_FINDINGS；部署时需真实
  独立账号/特权 freeze 步骤，guard 会自动放行）
Commit    = 未执行（§36 要求 owner isolation proven 才 commit；
           当前为 PASS_WITH_FINDINGS，工作区保持未提交）
```

## Scope Audit

`git diff --name-only`：

```text
src/forge/capabilityizer.py
pilot/runtime_adoption_guard.py
pilot/harness.py
docs/archaeology/unified-runtime/phase9b1/test_candidate_seal.py
docs/archaeology/unified-runtime/phase9b1/test_legacy_downgrade_closure.py
docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py
docs/archaeology/unified-runtime/phase9b3/test_candidate_identity_fail_closed.py
docs/archaeology/unified-runtime/phase9b5/test_anchored_run_intent.py
```

新增（未跟踪）：`docs/archaeology/unified-runtime/phase9d3/`（tests +
live probe + 本报告）。`docs/archaeology/codex/`、`deepseek-harness/`、
`control-plane/`、`openhands/` 等未跟踪文件为既有内容，本阶段未触碰。
