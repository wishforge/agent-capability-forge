# Phase 9-C.05 — Registry / Cache / Runtime Audit

基线：`a70a433`。验证三项原则：`Registry = Locator`、`b3_entry = Cache/Locator`、
Runtime 无第二条 candidate selection path。

## 1. Registry = Locator

测试构造与结果（canonical 路径）：

| # | 构造 | 期望 | 实测 | 证据 |
|---|---|---|---|---|
| R1 | Run Intent=A, Registry=B, b3_entry=B | REJECT | `RUN_REQUEST_CACHE_MISMATCH`，docker 未调用 | phase9b5 test_a / test_f |
| R2 | Run Intent=A, Registry=B, b3_entry missing | REJECT | 同 store 完整合法 B：`CANDIDATE_ID_MISMATCH + ARTIFACT_DIGEST_MISMATCH + SEAL_DIGEST_MISMATCH`；跨 store：`UNISSUED_AUTHORITY` | 本轮 probe3 / probe1 |
| R3 | Runtime 直接找到 B artifact（entry.artifact_dir=B） | REJECT | `ARTIFACT_DIGEST_MISMATCH`（frozen digest 重算） | phase9b3 Case E；probe P11（9-B.4.1） |

不存在 direct path bypass：`adopt()` 对 entry.artifact_dir 重算 live digest 且
`verify_at_mount` 再把 expected identity 与 report 比对（runtime_adoption_guard.py:
416-535, 538-564）。

## 2. b3_entry = Cache / Locator

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| C1 | b3_entry → B（whole swap），Run Intent=A | REJECT | `RUN_REQUEST_CACHE_MISMATCH`（phase9b5 test_a） |
| C2 | b3_entry missing，Run Intent=A | REBUILD A → ALLOW A | 重建文件与 run_request 一致（phase9b5 test_b/test_g） |
| C3 | b3_entry stale（单字段 B），Run Intent=A | REJECT | `RUN_REQUEST_CACHE_MISMATCH`（phase9b5 test_c） |
| C4 | rebuild 结果被篡改为 B 后使用 | REJECT | 重读比对 `RUN_REQUEST_CACHE_MISMATCH`（phase9b5 test_h） |

b3_entry 没有 security authority：`run_request_cache_violations` 只校验与
run_request 的一致性（runtime_adoption_guard.py:380-392）；capability_id 不在
比较字段（inert，9-B.4.1 P12 已证明）。

## 3. Artifact Binding

```text
verified identity (run_request)
        ↓ identity_violations
adopt report (authority)
        ↓ frozen_artifact_violations
artifact directory (entry.artifact_dir)
        ↓ RUNTIME_BINDING_MISMATCH 反例
mount source (verify_at_mount 传回的 verified_artifact_dir)
        ↓ 唯一
docker_launch mount
```

- `identity=A, digest=A, mount_source=B` → `RUNTIME_BINDING_MISMATCH`（phase9b3
  test_r8_mount_source_must_equal_verified_artifact_dir）。
- `identity=A, verified_artifact_dir=A` 但 mount 前路径被替换为 B：属于 O1
  OS-level verify→bind-mount 窗口，只记录不修复（见 09 号报告）。

## 4. Runtime Boundary

`docker_launch` 唯一调用点（harness.py:786-791）：

```text
mounts = [(artifact_dir, "/artifact", True),
          (fixture/input, "/input", True),
          (out, "/output", False)]
```

`artifact_dir = Path(mount["verified_artifact_dir"])`（harness.py:785），来自
`verify_at_mount` report；docker 命令不含 candidate name / candidate_id / version。
不存在 `docker_launch receives name=B` 形态的旁路。

## 5. 结论

```text
REGISTRY   = LOCATOR ONLY（canonical）
B3_ENTRY   = CACHE ONLY（canonical）
RUNTIME    = SINGLE PATH（verified_artifact_dir）
ARTIFACT_BINDING = CLOSED（O1 单独开放）
```
