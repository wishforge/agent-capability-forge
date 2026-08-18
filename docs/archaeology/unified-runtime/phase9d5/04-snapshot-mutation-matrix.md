# Phase 9-D.5.04 — Snapshot Mutation Matrix

## 1. 本阶段 probe（身份 = owner 501，`/private/tmp` store）

| attack | result |
|---|---|
| write snap/main.py | PermissionError |
| rename snap/main.py → evil.py | PermissionError |
| unlink snap/main.py | PermissionError |
| rmtree snap | PermissionError |

probe 后 `verify_frozen`：ok=true，violations=[]，digest 未变。

## 2. D.4 已完成的 owner 级矩阵（引用）

append / atomic file replace / atomic dir replace / symlink / chmod / chown 结果见
`phase9d4/04-snapshot-mutation-probes.md`；chmod 对 owner 有效，chown EPERM。

## 3. 关键结论

- publish 后 owner 进程的普通 mutation 也被 OS 阻止（0555/0444）。
- 真正的防线仍是 owner != runtime user：owner 可以 chmod，B 不能。
- B 的 live mutation matrix（写/追加/截断/改名/替换/删目录/同路径换对象/chmod/
  chown/post-mount mutation）本阶段未执行（无 B），不得视为通过。
