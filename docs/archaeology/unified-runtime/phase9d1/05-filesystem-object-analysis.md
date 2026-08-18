# Phase 9-D.1.05 — Filesystem Object Analysis

## 1. 系统信任什么

```text
Application-level identity  : canonical digest（check 时刻的 bytes）
Runtime mount reference     : path string（verified_artifact_dir）
Filesystem object identity  : 无（不记录/不比较 inode、无 fd）
Snapshot                    : frozen snapshot 仅作验证参考，不作 mount source
```

## 2. Same path / different inode（Q7）

Probe P2：

```text
path = <registry>/F+/foo/artifact      不变
inode = 36525652 -> 36525660          变化
容器观察到 B
```

结论：Runtime 接受同一 path 上的新 inode；系统信任 path，不信任被验证的
filesystem object。

## 3. Content mutation without rename（Q15）

Probe P4：目录 inode 不变、文件字节改写 → 容器观察到 B。

Probe P4b：目录 inode 不变、文件通过 `os.replace` 原子替换 → 容器观察到 B。

`CONTENT_MUTATION` 未被现有 freeze 阻止：freeze 锁的是 frozen snapshot 记录，
live registry artifact 目录在 promote 后没有被 chmod/chflags 只读。

旁证：真实 `pilot/state/registry/F+/csv-clean-statistical-report/artifact/`
中存在 promote 后生成的 `__pycache__/`（目录 mtime 2026-08-18 vs
promotion 2026-08-14）。该目录是可写的（该脏文件本身会使 canonical 验证
REJECT，不是攻击路径，但证明“artifact 目录 promote 后可被写入”）。

## 4. Atomic rename（Q5）

Probe P2：`rename(A, A_old); rename(B, A)`（os.replace 三连）成功，路径不变、
对象替换，容器观察到 B。Atomic rename 真实可行。

## 5. Symlink（Q6）

- 布局检查允许 symlink（04 文件 symlink-at-check 实测 ALLOW）。
- verify 后把 A 换成指向 B 的 symlink，docker 跟随 host symlink，容器观察到 B
  （P3）。
- 结论：`SYMLINK_ATTACK = APPLICABLE`（且 checker 本身也接受 symlink）。

## 6. FD / handle semantics（Q10 小节）

`rg` 结果：runtime 无 `O_PATH` / `openat` / `fstat` / `st_ino` / memfd。
Check 与 Use 之间只有 `str(Path)`。不存在 fd-based binding，因此不存在
“descriptor 消除 TOCTOU”的现状。

## 7. Level 2 判定

```text
Level 1 (verified_path == mount_source)     : CLOSED
Level 2 (verified object == mounted object) : OPEN / CONFIRMED（path 只 pin 名字）
Level 3 (container observes verified bytes) : CONFIRMED GAP（实测观察到 B）
```

