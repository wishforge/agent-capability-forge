# Phase 9-D.4.02 — Store Owner vs Runtime User

## 1. Guard 读取来源（`pilot/runtime_adoption_guard.py`）

- Owner UID：`frozen_root.stat().st_uid`
- Runtime UID：`runtime_uid` 参数；未传时 `os.getuid()`
- Groups：`set(os.getgroups())`（guard 进程自己的 groups，不是目标 runtime user 的 groups）
- 显式 `runtime_uid`：允许（`execution_snapshot_isolation_violations(frozen_root, candidate_id, runtime_uid=...)`）

## 2. Guard 语义

- Store Owner == Runtime User → `EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED`（REJECT）
- Owner 不同且祖先/子树对 runtime user 无写位 → 无 violations（ALLOW）
- 判断是 metadata / stat 比较，不是以 runtime user 身份发起的真实进程 probe

因此 guard ALLOW 不等于 OS 层真实不可写；必须另行验证。

## 3. 当前环境

```text
Store Owner UID  = 501 (david)
Runtime User UID = 501 (david)   # 真实 harness 进程 os.getuid()
```

Owner == Runtime → 当前系统正确 fail-closed。

## 4. 部署候选 Runtime UID

| UID | 含义 | guard（metadata 级） | 备注 |
|---|---|---|---|
| 501 | david | REJECT | 本机 harness 身份 |
| 4294967294 | macOS nobody（-2） | ALLOW | 真实 macOS 系统账号 |
| 65534 | Linux nobody | ALLOW | 跨平台参考，非本机 |
| 0 | root | ALLOW（见 06 限制） | OS 权限无法阻止 root；部署必须禁止 runtime 以 root 运行 |

## 5. 祖先 traverse 检查缺口

guard 只检查祖先是否可被 runtime user replace / write，不检查 runtime user
是否能 read / traverse 到 store。当前仓库路径：

| path | mode | owner:group |
|---|---|---|
| /Users | 0755 | root:admin |
| /Users/david | 0750 + ACL `deny delete` | david:staff |
| agent-capability-forge 及子目录 | 0755 | david:staff |

与 david 无关的 OS user B 无法 traverse `/Users/david`（0750 other 无权限）。
因此若 store 放在仓库内，即使 owner isolation 成立，B 也读不到 snapshot。
部署时必须把 store 放在 B 可 traverse 的路径，或显式验证祖先 read + execute。
