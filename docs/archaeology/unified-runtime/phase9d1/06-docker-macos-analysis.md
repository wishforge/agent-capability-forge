# Phase 9-D.1.06 — Docker / macOS Analysis

## 1. 环境

```text
Host OS        : macOS 26.5.1 (Darwin 25.5.0 arm64)
Host FS        : APFS（root 为 sealed/read-only system volume；workspace 在 data volume）
Docker         : Docker Desktop 29.1.3
Docker daemon  : linux, aarch64, driver=overlayfs, cgroupfs
API            : 1.52
Image          : python:3.12-slim（与 harness 相同）
```

## 2. Path 解析链（实测）

```text
Python: str(Path(artifact_dir).resolve())
  -> /private/var/folders/bg/.../artifact        （macOS /var -> /private/var）
    ↓
docker CLI argv: -v /private/var/folders/.../artifact:/artifact:ro
    ↓
Docker Desktop VM: /run/host_mark/private/var/folders/.../artifact
    ↓
容器内 /proc/mounts:
  /run/host_mark/private /artifact fakeowner ro,nosuid,nodev,relatime,fakeowner 0 0
```

`docker inspect` 记录的 Source 为 `/var/folders/.../artifact`（daemon 侧规范化）。

## 3. 谁解析 mount source

- Python：只解析一次（`Path.resolve()`），生成字符串。
- Docker CLI：透传字符串，不解析。
- Docker daemon（VM 内）：容器创建时解析 host path 并 bind mount
  （`/run/host_mark/private` 共享层）。

因此：

```text
Python check 的路径解析  !=  Docker 内核 mount 的路径解析
两者之间隔一个 VM 文件共享层，且各自独立按名字解析。
```

## 4. 实测行为

| 时间点 | host 替换 | 容器观察 |
|---|---|---|
| verify 之后、容器创建之前 | A → B | **B**（P1-P4b） |
| 容器创建之后 | A → B | A（post-mount probe） |

结论：

- Docker Desktop/macOS 在容器创建时解析 mount source；verify 与容器创建之间
  的 host 替换会被容器看到。
- mount 完成后对象被 pin，运行中容器不受后续 host 替换影响。
- macOS host 与 Linux VM 之间的 `host_mark` 共享层没有消除 TOCTOU；
  它只是把“按名字解析”的时点推迟到容器创建。

## 5. 与 Linux 语义的差异说明

本结论基于当前 macOS + Docker Desktop 29.1.3 实测。Linux 原生 Docker 上
bind mount 同样在容器创建时按名字解析，预期同类 window 存在，但本阶段
不把 Linux 行为当作已验证事实。

