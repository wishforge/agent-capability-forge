# Phase 9-D.5.06 — Owner Isolation Analysis

## 1. 身份状态

```text
STORE_OWNER_UID = 501 (david)
RUNTIME_UID = 无真实 B（候选 nobody=4294967294 / _www=70 / daemon=1）
A != B = NO（没有第二个真实 OS 用户可运行）
```

## 2. Guard 未修改

本阶段没有修改 capabilityizer / runtime_adoption_guard / harness / sandbox /
Run Intent / Authority / O1 snapshot / Legacy / trust anchor schema，也没有为测试
放宽 owner isolation。

## 3. Negative control（same-owner，live）

runtime_uid=501 → `EXECUTION_SNAPSHOT_OWNER_ISOLATION_REQUIRED` +
`EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE` → REJECT。Guard 未因 D.5 被弱化。

## 4. Fail-closed 对照（复用 D.4 §6 + guard 代码）

| 场景 | 结果 |
|---|---|
| store owner == runtime user | REJECT |
| store missing | EXECUTION_SNAPSHOT_STORE_MISSING |
| store/artifact writable | EXECUTION_SNAPSHOT_WRITABLE |
| 祖先可被 runtime replace | EXECUTION_SNAPSHOT_STORE_PATH_WRITABLE |
| 未知 owner / stat 失败 | 按缺失/不可读 fail-closed（guard 代码路径） |

## 5. 已知限制（D.4 保持，未消除）

1. guard 的 gids 来自 guard 进程，不是 runtime user B 的 groups；部署须避免组写位。
2. runtime_uid=0 不特殊处理；部署契约禁止 root 运行 runtime。
3. guard 不检查祖先 read/traverse；由部署路径保证（02 已给出模型）。
4. guard ALLOW 是 stat 级判断，不等于 OS 层 live 不可写证明。

## 6. 结论

```text
OWNER_ISOLATION = OPEN
LIVE_MULTI_UID_PROOF = NO
```

关闭条件：在具备真实第二 OS user（或 Linux CI service account）的部署主机上，
以 B 完成 read/traverse ALLOW、write/rename/replace/delete/chmod/chown DENY、
canonical runtime ALLOW 的 live 验证。
