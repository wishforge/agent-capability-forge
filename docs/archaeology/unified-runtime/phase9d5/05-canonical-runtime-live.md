# Phase 9-D.5.05 — Canonical Runtime Live

## 1. 代码路径（本阶段复核 `pilot/harness.py`）

`phase_future("b3")`：

```text
adopt → verify_at_mount(expected_digest + identity, mount_source=E(D))
→ docker_launch 仅 mount E(D) = frozen_root/frozen/<candidate_id>/artifact
```

## 2. 结果

| 场景 | 结果 |
|---|---|
| 真实 B 启动 canonical runtime | 未执行（无真实 B） |
| guard 级 verify_at_mount（runtime_uid=4294967294，进程仍为 501） | ALLOW（metadata 级） |
| same-owner（501） | REJECT（fail-closed，正确） |

## 3. 边界

- Docker 容器 UID ≠ Host macOS UID；container 内 nobody 不构成 host
  owner-isolation 证明。
- 本阶段没有“Runtime 以 B 身份观察到 Candidate A”的 live 证据。
- `CANONICAL_RUNTIME = BLOCKED`（未证明），不能写 ALLOW。

## 4. Docker

Docker version 29.1.3 build f52814d（本机）。容器级验证 D.3 已完成（5/5 attack
blocked、18/18 race 观察到 A），但那是 host 501 启动的容器，不是 B。
