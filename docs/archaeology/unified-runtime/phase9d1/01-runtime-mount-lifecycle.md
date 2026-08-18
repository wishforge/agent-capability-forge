# Phase 9-D.1.01 — Runtime Mount Lifecycle

- 基线：`a70a433`
- 范围：canonical B3 runtime 的 `adopt -> verify_at_mount -> docker_launch -> container`
- 方法：源码考古 + 临时 canonical registry 上真实调用 production 函数
- 日期：2026-08-18

## 1. 真实执行路径

```text
harness.phase_future(arm="b3")
  -> adopt()                       # 第一次完整验证（激活前）
  -> verify_at_mount()             # 第二次完整验证（mount 前，最终 Check）
  -> docker_launch()               # Use：-v <verified_artifact_dir>:/artifact:ro
  -> docker CLI                    # 传递 host path string
  -> Docker Desktop VM daemon      # 在 VM 内解析 host path
  -> kernel bind mount             # /run/host_mark/private/... -> /artifact
  -> container 执行 /artifact/main.py
```

## 2. 每一步的 file / function / line / input / output / side effect

| 步骤 | 位置 | 输入 | 输出 | 副作用 |
|---|---|---|---|---|
| 1. 解析 registry 路径 | `pilot/harness.py:767` `artifact_dir = Path(entry["artifact_dir"])` | registry entry locator | Path | 无 |
| 2. 第一次 adopt | `pilot/harness.py:768` → `pilot/runtime_adoption_guard.py:416` | registry_root, entry, artifact_dir | ALLOW report | 读 store/authority/frozen/live artifact |
| 3. 最终 Check（第二次 adopt） | `pilot/harness.py:778-784` → `runtime_adoption_guard.py:538-563` | registry_root, entry, artifact_dir, expected digest + identity, mount_source | ALLOW report `verified_artifact_dir` | 重算 live artifact canonical digest；无对象句柄返回 |
| 4. 接受 verified path | `pilot/harness.py:785` `artifact_dir = Path(mount["verified_artifact_dir"])` | report | Path | 无（字符串到 Path，无 stat） |
| 5. 构造 mount | `src/forge/sandbox.py:27-29` `args += ["-v", f"{Path(host)}:{cont}:{'ro' if ro else 'rw'}"]` | verified_artifact_dir | argv string | 无 |
| 6. 发起 docker | `src/forge/sandbox.py:32` `subprocess.run(["docker","run",...,"-v",...])` | argv | 子进程 | docker CLI 连接 daemon |
| 7. daemon 解析 host path | Docker Desktop VM（Linux, aarch64） | `/private/var/folders/.../artifact` | VM 路径 `/run/host_mark/private/...` | 容器创建时绑定 |
| 8. kernel bind mount | VM 内核 | mount source path | `/artifact` (ro) | 容器挂载 |
| 9. 容器观察 | 容器内 `sha256(/artifact/main.py)` | - | digest | 执行 |

## 3. Mount source 的确定

`verify_at_mount` 返回 `report["verified_artifact_dir"]`，即
`str(Path(artifact_dir).resolve())`（`runtime_adoption_guard.py:534`）。
`mount_source` 与它不一致时抛 `RUNTIME_BINDING_MISMATCH`
（`runtime_adoption_guard.py:558-562`）。

Mount source 是 **live registry 目录**：

```text
pilot/state/registry/F+/<name>/artifact
```

该目录在 `registry.promote` 时由 `shutil.copytree` 从 candidate 复制
（`pilot/registry.py:190-192`），之后没有任何 chmod / chflags / 不可变锁。
冻结快照（`frozen_candidates/frozen/<candidate_id>/artifact`）只作为验证参考，
从不作为 mount source。

## 4. 关键事实

1. Check 与 Use 之间只有 path string 传递；没有 fd / O_PATH / openat / inode 记录。
2. `Path.resolve()` 只规范化字符串，不 pin 任何 filesystem object。
3. Python 进程与 Docker daemon 之间隔着一个 VM 文件共享层
   （`/run/host_mark/private`），host path 在容器创建时才被 daemon 解析。

