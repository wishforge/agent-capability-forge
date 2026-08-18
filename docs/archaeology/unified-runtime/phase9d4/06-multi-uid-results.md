# Phase 9-D.4.06 — Multi-UID Results

## 1. Guard-level（metadata）结果

| scenario | runtime_uid | violations |
|---|---|---|
| same owner | 501 | `EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED` + `EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE` |
| macOS nobody | 4294967294 | [] |
| Linux nobody | 65534 | [] |
| root | 0 | `EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE`（仅祖先；root 可写一切，见 §3） |
| store missing | 4294967294 | `EXECUTION_SNAPSHOT_STORE_MISSING` |
| artifact dir 0777 | 4294967294 | `EXECUTION_SNAPSHOT_WRITABLE` x2 |
| main.py 0666 | 4294967294 | `EXECUTION_SNAPSHOT_WRITABLE` |

## 2. Failure mode 对照

| Case | 语义 | 结果 |
|---|---|---|
| A | Owner == Runtime User | REJECT（live 确认） |
| B | Owner unknown / store missing | REJECT（live 确认：`EXECUTION_SNAPSHOT_STORE_MISSING`） |
| C | Snapshot ownership changed unexpectedly | 逻辑覆盖：store owner == runtime 或任一文件可写给 runtime → REJECT；无法 live chown（需 root） |
| D | Runtime user can write snapshot | REJECT（live 确认：chmod 0777 / 0666 后 guard 报 `EXECUTION_SNAPSHOT_WRITABLE`） |

## 3. 已知限制（本阶段不修改 guard）

1. `gids = os.getgroups()` 是 guard 进程的 groups，不是 runtime user B 的
   groups；hardened store 0444/0555 组位无写，当前安全。若部署使用组写位，
   必须显式传入/验证 runtime gids。
2. `runtime_uid=0` 不特殊处理：OS 权限无法阻止 root。部署契约必须禁止
   runtime 以 root 运行。
3. guard 不检查祖先 read/traverse（见 02.5）；部署时必须保证 B 能到达 store。

## 4. 最终状态

```text
LIVE_MULTI_UID_PROOF = NO
OWNER_ISOLATION     = OPEN
```

guard 逻辑测试通过不构成 owner isolation 证明。
