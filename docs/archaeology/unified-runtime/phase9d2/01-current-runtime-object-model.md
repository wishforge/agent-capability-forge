# Phase 9-D.2.01 — O1 Current Runtime Object Model

- 日期：2026-08-18
- 基线：`ee1c639`（9-D.1 实证 O1）
- 范围：design archaeology；未修改 production code、未新增 production tests、未 commit
- 输入：`pilot/runtime_adoption_guard.py` / `pilot/harness.py` /
  `src/forge/sandbox.py` / `src/forge/capabilityizer.py` + phase9d1 全套
  + 本轮只读 Docker / filesystem 实验（/tmp，已清理）

## 1. 精确调用链

```text
harness.phase_future("b3")                       harness.py:767
  artifact_dir = Path(entry["artifact_dir"])     # live registry artifact dir
  -> adopt()                                     harness.py:768
       -> frozen_checks(frozen_root, candidate_id)     runtime_adoption_guard.py:502
       -> frozen_artifact_violations(record, candidate, artifact_dir)
                                                     runtime_adoption_guard.py:513
         -> frozen_artifact_report(directory, allowlist)   capabilityizer.py:91
           -> artifact_layout(directory, allowlist)        capabilityizer.py:56
             -> file_digest -> path.read_bytes()          capabilityizer.py:47-49
  -> verify_at_mount(...)                          harness.py:778
       -> adopt() 再次全链                           runtime_adoption_guard.py:549
       -> report["verified_artifact_dir"]
          = str(Path(artifact_dir).resolve())     runtime_adoption_guard.py:534
  -> artifact_dir = Path(mount["verified_artifact_dir"])  harness.py:785
  -> docker_launch([(artifact_dir, "/artifact", True), ...]) harness.py:786
       -> sandbox.launch: -v <path>:/artifact:ro   sandbox.py:28
       -> subprocess.run(["docker", "run", ...])   sandbox.py:32
       -> Docker Desktop VM daemon 容器创建时解析 host path
       -> kernel bind mount /run/host_mark/private/... -> /artifact
       -> container 执行 python /artifact/main.py
```

## 2. 三个“对象”目前各是什么

| 问题 | 现状 |
|---|---|
| 哪一个对象被 verify？ | live registry artifact 目录 `pilot/state/registry/F+/<name>/artifact` 的当前 bytes（最后一次 `read_bytes()` 在 capabilityizer.py:49） |
| 哪一个对象被传给 Docker？ | 只有 path string `verified_artifact_dir`（runtime_adoption_guard.py:534）；无 fd / inode / snapshot handle |
| 哪一个对象实际被 mount？ | Docker daemon 在容器创建时按同一 path string 在 VM 共享层二次解析出的对象（docker inspect Source；实测 mount line `/run/host_mark/private /artifact fakeowner ro`） |

结论：三者目前是**同一个 path**，但不是**同一个 filesystem object**。
Phase 9-D.1 已实证：path 相同、object 不同 -> B 被执行（5/5 确定性攻击；
9/18 自然竞态）。

## 3. 对象概念表

| 概念 | stable identity？ | 可被替换？ | 跨 Python→Docker→VM？ | 防 same-path replacement？ | 适用目录型 artifact？ |
|---|---|---|---|---|---|
| Path string | 否（只 pin 名字） | 是 | 是（字符串透传） | 否 | 是 |
| Directory | 否（mount 前）；mount 后 VM 侧 pin 目录对象 | 是（mount 前）；目录级替换 mount 后不可见 | 对象本身不跨，只有名字跨 | 否（mount 前） | 是 |
| Inode（host APFS） | 是（host 内） | 可被 rename 替换 | 否（不同 namespace；容器内 inode 不同） | 否（跨边界） | 否 |
| File descriptor | 是（进程内 pin 对象） | 否（fd 持有对象） | 否（Darwin fd 不能进 Linux VM；Docker API 只收 path string） | 进程内是；跨边界否 | 目录 fd 可 openat，但 Docker 不接受 |
| Snapshot（当前 frozen） | 逻辑上（candidate_id + record） | 是（目录/文件权限普通、无写域隔离） | 仅以 path string | 否（除非写域隔离） | 是 |
| Digest | 内容身份（验证时刻） | n/a（是字节的函数） | 是（作为数据/字符串） | 否（只是验证，不是 pin） | 是 |
| Digest-addressed artifact | 内容身份 + locator | 取决于 store 是否受保护 | 以 path string | 否（名字本身不是不可变机制） | 是 |
| Container mount source | daemon 侧 path string；创建时解析 | 创建前可被替换；创建后目录对象 pin、文件内容仍实时 | 是（path） | 否 | 是 |

## 4. 本轮新增证据：mount 只 pin 目录对象，不 pin 文件内容

新临时 probe（Docker Desktop 4.57.0 / macOS 26.5.1 / aarch64，`/tmp`，已清理）：

| 时间点 | host 操作 | 运行中容器 `cat /artifact/main.py` |
|---|---|---|
| 容器启动后 ~1s | 对已挂载目录内 `main.py` in-place 改写（同 inode） | `A2`（看到新字节） |
| 容器启动后 ~5s | `mv` 原子替换 `main.py`（新 inode） | `A3`（看到新文件） |
| 9-D.1 post-mount probe | host 对已挂载目录做 rename swap（目录级） | `A`（仍看到旧目录对象） |

因此修正 9-D.1 的“window 在容器创建时关闭”：

```text
目录对象      ：mount 时被 VM 侧 pin 住（目录级 rename/replace 不再进入容器）
目录内文件    ：容器每次 open 仍实时解析共享层；host 侧 in-place 写与原子文件替换
               都会进入运行中容器的视野
:ro          ：只挡容器侧写，不挡 host 侧写
```

推论：O1 的窗口不止存在于 verify→mount 之间；**mount 之后文件级 mutation
仍然能改变容器观察到的内容**。因此任何设计若只“验证一次再挂载”，而没有让
mount source 对象在 host 写域内不可变，都无法闭合 O1。

## 5. 冻结结论

```text
PATH_BASED_RUNTIME = YES（维持 9-D.1）
FILESYSTEM_OBJECT_BINDING = PATH-ONLY（维持 9-D.1）
POST_MOUNT_DIRECTORY_REPLACEMENT = NOT OBSERVED（mount pin 目录对象）
POST_MOUNT_FILE_MUTATION = VISIBLE（本轮新增；in-place 与 atomic file replace 都可见）
O1_CLOSURE_REQUIREMENT = mount source 对象必须在 host 写域内不可变
```

