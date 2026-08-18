# Phase 9-D.4.05 — Live Runtime Validation

## 1. Positive Control — Same Owner

```text
Expected = REJECT
Observed = REJECT
```

`adopt` / `verify_at_mount`（runtime_uid=501）violations：

```text
EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED
EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE   # 临时 store 父目录为 owner 可写；部署路径需硬化
```

## 2. Positive Control — Different Owner（metadata 级）

`adopt` / `verify_at_mount`（runtime_uid=4294967294）：

```text
verdict = ALLOW
allowed = true
```

注意：这是 guard 逻辑 ALLOW；进程仍以 501 运行，不是 live B proof。

## 3. 真实 harness

canonical b3 路径（`de38f88` 后 harness.py）：

```text
run_request → E(D) = frozen_root/frozen/<candidate_id>/artifact
→ adopt → verify_at_mount(expected digest + identity, mount_source=E(D))
→ docker_launch 仅 mount E(D)
```

本机 harness 进程 uid = `os.getuid()` = 501 → guard REJECT：

```text
CANONICAL_RUNTIME = BLOCKED
```

这是正确的 fail-closed，不是 fake PASS。

## 4. Docker 容器观察

D.3 已证明 5/5 attack blocked、18/18 race 观察到 A、post-mount 观察到 A。
D.4 不重复该实验，且 container UID ≠ host UID，不能替代 host 多 UID 证明。

## 5. D.3 regression sanity

`phase9d3/test_runtime_object_integrity.py`：

```text
15 passed in 0.29s
```
