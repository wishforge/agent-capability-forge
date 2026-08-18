# Phase 9-D.2.05 — Docker Desktop / macOS Object Binding Analysis

- 日期：2026-08-18
- 基线：`ee1c639`
- 方法：只读 docker inspect / version / info + 一次性 /tmp 容器 probe（已清理）

## 1. 实测环境

| 项 | 值 |
|---|---|
| macOS | 26.5.1 (25F80)，arm64，APFS（/System/Volumes/Data） |
| Docker Desktop | 4.57.0 (215387)，context `desktop-linux` |
| Engine | 29.1.3，linux/arm64，driver=overlayfs |
| containerd / runc | v2.2.1 / 1.3.4 |
| API | 1.52（minimum 1.44） |
| 测试 image | python:3.12-slim（与 harness 相同） |

## 2. 谁解析 mount source（实测证据）

| 组件 | 行为 |
|---|---|
| Python | `Path.resolve()` 一次，生成字符串（runtime_adoption_guard.py:534） |
| Docker CLI | 透传字符串（sandbox.py:28,32） |
| Docker daemon | 容器创建时按 `Mounts[].Source` 字符串解析（`docker inspect` 实测）；VM 内 mount line `/run/host_mark/private /artifact fakeowner ro,nosuid,nodev,relatime,fakeowner` |

结论：**Docker daemon 是最终解析者**，且解析发生在容器创建时；Python 的
verify 与 daemon 的解析是两次独立按名字解析，中间隔一个 VM 共享层。

## 3. 共享层行为（fakeowner）

Docker Desktop 的 host 共享文件系统（VirtioFS / gRPC-FUSE 家族，mount type
`fakeowner`）行为：

| 事件 | 容器观察 |
|---|---|
| 容器创建前 host 替换目录/文件 | B（9-D.1：5/5 确定性，9/18 自然） |
| 容器创建后 host 替换**目录**（rename swap） | A（9-D.1 post-mount probe；目录对象被 pin） |
| 容器创建后 host in-place 改写**文件** | 新字节（本轮 obs1 = A2） |
| 容器创建后 host 原子替换**文件** | 新字节（本轮 obs2 = A3） |

## 4. 什么能跨 VM，什么不能

```text
能跨   ：path string、bytes（通过共享 FS 实时读写）
不能跨 ：Darwin fd、host APFS inode、目录句柄、mount object handle
```

## 5. 冻结推论

```text
1. :ro = 容器侧只读；≠ host artifact immutable
2. mount 之后 O1 并未完全关闭：文件级 mutation 仍进入运行中容器
3. 唯一可行边界 = 让 mount source 的对象在 host 写域内不可变
   （写域隔离），而不是依赖 ro / digest 名 / fd
```

