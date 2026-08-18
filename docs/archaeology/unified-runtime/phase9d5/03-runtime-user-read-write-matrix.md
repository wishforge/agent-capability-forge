# Phase 9-D.5.03 — Runtime User Read/Write Matrix

## 1. 矩阵

| Check | A = Store Owner (501) | B = Runtime User（无真实身份） |
|---|---|---|
| Publish | ALLOW（live：freeze→authority→promote 成功） | DENY（POSIX 预测；未 live） |
| Traverse | ALLOW | ALLOW（POSIX 预测；未 live） |
| Read | ALLOW | ALLOW（POSIX 预测；未 live） |
| Write | publish 前 ALLOW / publish 后 DENY（live：PermissionError） | DENY（POSIX 预测；未 live） |
| Rename | publish 后 DENY（live：PermissionError） | DENY（POSIX 预测；未 live） |
| Replace | publish 后 DENY（live：D.4 原子替换 PermissionError） | DENY（POSIX 预测；未 live） |
| Delete | publish 后 DENY（live：unlink/rmtree PermissionError） | DENY（POSIX 预测；未 live） |
| Chmod | 仅 owner 有效（D.4 live；本阶段未重复） | DENY（POSIX 预测；未 live） |
| Chown | 非 root EPERM（D.4 live） | DENY（POSIX 预测；未 live） |
| Canonical runtime | N/A（same-owner 被 guard REJECT） | 未验证（无 B） |

## 2. 结论

- A 行是 live 证据（本阶段或 D.4）。
- B 行全部是 POSIX 预测；B 不存在，`LIVE_MULTI_UID_PROOF = NO`。
- guard 元数据级对 B 返回 ALLOW，但不等于 OS 层 live 证明（见 05/06）。
