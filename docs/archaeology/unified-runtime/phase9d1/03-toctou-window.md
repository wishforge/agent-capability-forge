# Phase 9-D.1.03 — TOCTOU Window

## 1. Window 定义

```text
CHECK_POINT
  （adopt 内最后一次 read_bytes 完成，capabilityizer.py:49）
    ↓
[ attack window ]
    ↓
USE_POINT
  （Docker daemon 在容器创建时解析 host path 并 bind mount）
```

## 2. 精确位置

Window begins：`verify_at_mount` → `adopt` → `frozen_artifact_violations`
→ `frozen_artifact_report` → `artifact_layout` → `file_digest` 的最后一次
`path.read_bytes()`：

```text
src/forge/capabilityizer.py:49
（经由 capabilityizer.py:431, runtime_adoption_guard.py:513,549）
```

Window ends：Docker daemon 在容器创建时完成 host path 解析和 bind mount。
该点不在 Python 可观察代码内；实测在 verify 返回后约 277-2281 ms
（`docker run` 全程，含 CLI/daemon/挂载）。

Python 侧 use point：

```text
src/forge/sandbox.py:28   （-v 参数构造）
src/forge/sandbox.py:32   （subprocess.run 发起 docker）
```

## 3. 实测时序（本轮 probe，production 函数 + 临时 registry）

| 事件 | 实测 |
|---|---|
| verify_at_mount 执行 | ~1.0-1.4 ms |
| 攻击替换（rename/copy/symlink/write） | 0.13-0.41 ms |
| docker run 到容器内看到结果 | 277-2281 ms |

替换严格发生在 verify 返回之后、docker 发起之前。所有 5 个确定性攻击
（P1/P2/P3/P4/P4b）都让容器观察到 B。

## 4. 自然竞态（无人工 barrier）

攻击线程每 ~2 ms 在 A/B 之间原子 rename 交换；主线程反复执行
`verify_at_mount`（成功 = ALLOW）+ `docker_launch`：

```text
40 次尝试 -> 18 次 verify ALLOW
  -> 9 次容器观察到 B
  -> 8 次容器观察到 A
  -> 1 次无法判定
```

结论：窗口不仅存在，且在 same-user 并发写者下自然可赢（本轮约 50%）。

## 5. Window 的结束点（mount 之后）

容器启动后替换 host 目录（rename swap），运行中容器仍看到 A：

```text
POST_MOUNT_REPLACEMENT = container_saw = A
```

即 window 在容器创建时关闭；此后不再受影响。这同时证明问题不在
“docker 永远解析最新 path”，而在“verify 与容器创建之间没有对象 pin”。

