# Phase 9-D.5.02 — Store Path Permission Model

## 1. D.4 问题复述

`/Users/david = 0750`（other 无 r-x）→ 与 david 无关的 B 无法 traverse 到仓库内
store。frozen store 不能继续依赖 `/Users/david` 作为 B 的祖先路径。

## 2. 候选祖先逐级 stat（本阶段复核）

| path | owner:group | mode |
|---|---|---|
| / | root:wheel | 0755 |
| /Users | root:admin | 0755 |
| /Users/Shared | root:wheel | 1777（sticky，world rwx） |
| /private | root:wheel | 0755 |
| /private/tmp | root:wheel | 1777（sticky） |
| /private/var | root:wheel | 0755 |

对 B（nobody，other 位）：

- 0755 → traverse/read ALLOW，write DENY
- 1777 → traverse/read ALLOW，目录自身 write ALLOW，但 sticky 阻止删除/替换他人条目；
  store root 条目由 A 创建并硬化 0555 后，B 对 store 内容 write/rename/delete 均 DENY

## 3. 实际 probe store（`/private/tmp`，一次性，已清理）

canonical publish（A=501 执行 freeze → authority → promote）：

| path | uid:gid | mode |
|---|---|---|
| /private/tmp/phase9d5-*/ | 501:0 | 0755（probe 显式设置） |
| .../state | 501:0 | 0755 |
| .../frozen_candidates | 501:0 | 0555 |
| frozen | 501:0 | 0555 |
| cand-d5-a | 501:0 | 0555 |
| artifact | 501:0 | 0555 |
| main.py / cand-d5-a.json | 501:0 | 0444 |

## 4. B 对 probe store 的 POSIX 预测

| 能力 | 结果 |
|---|---|
| traverse /private → /private/tmp → probe 祖先 → store spine | ALLOW（逐级 other r-x） |
| read artifact 文件 | ALLOW（0444） |
| write / rename / replace / delete store 内容 | DENY（0555/0444，非 owner） |
| chmod / chown | DENY（chmod 仅 owner/root；chown 非 root EPERM） |

## 5. Guard 级结果（非 live）

- runtime_uid=4294967294（nobody）：`execution_snapshot_isolation_violations = []`；
  `verify_at_mount → ALLOW`
- runtime_uid=501（same owner）：`EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED` +
  `EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE` → REJECT

## 6. 部署建议（D.4 deployment issue 的解决路径）

1. store root 放在 B 可 traverse 的独立路径，例如
   `/Users/Shared/<namespace>/frozen_candidates`（祖先 0755 + 1777；sticky 阻止 B
   替换 store root 条目）。
2. store root / frozen / candidate / artifact 全部 A 所有，发布后目录 0555、文件
   0444（现有 `freeze_candidate_dir` 已自动硬化）。
3. 不使用 `/Users/david` 作为祖先；若必须使用，需显式 ACL/组权限并逐级验证。
4. 真实部署到目标主机后，以真实 B 逐级 `ls -lde` / `stat` 复核。

注意：本阶段只做 stat/POSIX + guard 级验证；B 不存在，所以“B 实际能 traverse/读”
仍是部署清单项，不是 live 证明。
