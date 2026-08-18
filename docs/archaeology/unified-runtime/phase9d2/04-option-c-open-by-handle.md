# Phase 9-D.2.04 — Option C: Open-by-Handle / Filesystem Object Pinning

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：option archaeology；未实现

## 1. 机制清单与平台事实（本轮实测）

| 机制 | 平台 | 本机（macOS 26.5.1 / Python 3.13.9） |
|---|---|---|
| `O_PATH` | Linux-only | `hasattr(os, "O_PATH") == False` |
| `openat` | Linux；Darwin C 有但 Python 未封装 | `hasattr(os, "openat") == False` |
| `open_tree` / `move_mount` | Linux-only，需 CAP_SYS_ADMIN | 无 |
| `memfd_create` / `O_TMPFILE` | Linux-only | `hasattr(os, "memfd_create") == False` |
| `chflags` | macOS 有 | `hasattr(os, "chflags") == True`；`uchg` 可由 owner 清除，`schg` 需 root，均不构成同 uid 隔离 |
| bubblewrap `--ro-bind-fd` / `--bind-fd` | Linux 原生运行时，按 O_PATH fd 做 race-free bind mount | 不适用（非本项目运行时） |

## 2. 当前架构边界

```text
Python (macOS APFS)
  -> Docker CLI
  -> Docker Desktop VM (Linux)
  -> daemon 容器创建时解析 host path
  -> shared FS (/run/host_mark/private, fakeowner)
  -> bind mount
```

实测证据：

1. Docker API / CLI 的 bind mount `Source` 是 path string：
   `docker inspect` -> `{"Type":"bind","Source":"/tmp/o1_d2_probe/artifact",...}`。
2. Python 持有的 Darwin fd 不能跨进 Linux VM；Docker 不接受 fd/handle 作为
   mount source。
3. host inode 与容器 inode 不在同一 namespace：本轮 host `main.py`
   inode `34691380`，容器内 `stat -c %i` = `1392`。

## 3. 即使 host 内 pin 也不够

```text
目录 fd / O_PATH  : pin 目录对象，不 pin 目录内文件内容；
                   host 对文件 in-place 写仍可见（01 号文件 post-mount probe）
文件 fd           : pin inode，但同 inode 的 in-place 写仍可见；
                   只有 memfd / 不可变 tmpfs / 快照对象才能 pin bytes
```

所以 C 即便在 Linux host 内也只解决 rename / replace，不解决 in-place
mutation，除非同时引入不可变对象。

## 4. 判定

```text
NOT SUFFICIENT FOR CURRENT ARCHITECTURE

原因：
1. 不能跨 Python -> Docker Desktop VM 边界（Docker API 只接受 path string）
2. macOS 无 O_PATH / memfd / open_tree 等价物（实测）
3. 不能防 in-place mutation（fd 不 pin bytes）
4. bubblewrap --ro-bind-fd 是 Linux 原生运行时的反例，不是本项目架构
```

若未来迁移到 native Linux sandbox runtime（bubblewrap 类）并放弃 Docker
Desktop，可重新评估；本阶段冻结为 NOT SUFFICIENT，不采用。

