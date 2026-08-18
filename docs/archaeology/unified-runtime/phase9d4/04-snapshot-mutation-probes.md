# Phase 9-D.4.04 — Snapshot Mutation Probes

Probe 身份：store owner 501（当前唯一可用的真实身份）。这不是 runtime user B
的 live 证据，只能证明模式位和 OS 行为；B 的真实结果见 06。

## 1. Attack matrix（owner 进程执行）

| attack | result |
|---|---|
| write `attack.txt` | PermissionError |
| append `main.py` | PermissionError |
| atomic file replace（evil.py → main.py） | PermissionError |
| atomic dir replace（evil_dir → artifact） | PermissionError |
| rename artifact → artifact.old | PermissionError |
| unlink main.py | PermissionError |
| rmtree artifact | PermissionError |
| symlink evil.py 到 artifact 内 | PermissionError |
| chmod main.py 0644（owner） | SUCCESS（随后恢复 0444） |
| chown main.py → nobody（owner） | EPERM Operation not permitted |
| chown artifact → nobody（owner） | EPERM Operation not permitted |

## 2. Digest 状态

全部 probe 后 `verify_frozen`：

```text
ok = true
violations = []
```

digest 未变。

## 3. 结论

- 模式位足以阻止 owner 进程的普通 write / rename / delete / symlink。
- `chmod` 对 owner 有效 → 只有 owner != runtime user 才能阻止 runtime user chmod。
- `chown` 即使 owner 也不能执行 → owner 变更需要特权。
- 每一行 "Runtime User B 尝试" 的预期结果都来自 POSIX 预测（03），不是 live B 证明。

## 4. Atomic publish boundary（代码考古）

`freeze_candidate_dir` 的发布顺序：

```text
materialize tmp snapshot → recompute digest → fsync → chmod tree（0555/0444）
→ os.link(record) 原子创建 → os.replace(tmp_snap, snap_dir) → 硬化 store root
```

publish 前 runtime user 只能看到 absent 或 complete snapshot；publish 后
store spine 0555 / record 0444，无 post-publish 写路径。owner 下一次 freeze
会临时恢复 0755 并再次硬化（单写者 pilot 语义，D.3 已记录）。
