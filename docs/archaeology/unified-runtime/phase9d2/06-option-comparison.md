# Phase 9-D.2.06 — Option Comparison

- 日期：2026-08-18
- 基线：`ee1c639`
- 依据：02/03/04/05 号文件；每格附依据

## 1. 矩阵

| 维度 | A: Digest Snapshot | B: Frozen Snapshot | C: Handle/Object Pinning |
|---|---|---|---|
| 真正防 same-path replacement | 条件性 YES：仅当 store 写域隔离（02-Q1/Q10）；名字=digest 本身不防 | 条件性 YES：同一写域隔离要求（03-§2） | NO：跨 Docker Desktop VM 边界不可用（04-§2）；host 内 fd 可防 |
| 防 atomic rename | 条件性 YES（store 隔离后 rename 不可能） | 条件性 YES（同左） | host 内 YES（fd pin inode）；跨边界 NO |
| 防 symlink replacement | YES：copytree symlinks=False 解析 + store 隔离（02-Q2, 03-§3） | YES（同左） | host 内 YES；跨边界 NO |
| 防 in-place mutation | 条件性 YES：store 隔离后 host 无写权限（05-§5）；否则 NO（连 mount 后都实时可见） | 条件性 YES（同左） | NO：fd 不 pin bytes（04-§3） |
| 防 file replacement | 条件性 YES（store 隔离后）；否则 NO | 条件性 YES（同左） | host 内 YES；跨边界 NO |
| Docker Desktop 兼容性 | YES（普通 host 目录；05-§3） | YES（同左） | NO（Docker API 只收 path string） |
| macOS 兼容性 | YES（APFS 普通目录） | YES（同左） | NO（无 O_PATH/memfd；uchg 可被 owner 清除） |
| Host → VM 可传递性 | path string YES；object 本身 NO | 同左 | NO |
| Runtime complexity | 中（新 store + 发布 + GC 纪律） | 低（复用现有 frozen + 写域隔离） | 极高 / 架构级重写 |
| Storage overhead | 每 candidate 1 份快照（若保留 registry copy 则 2） | 0 新增（复用 frozen snapshot；canonical 可去掉 registry copy） | n/a |
| GC complexity | 中（新 store 需定义生命周期） | 低（现有 write-once + referenced guard；冻结不做 GC） | n/a |
| Crash recovery | 新 freeze 事务（可沿用现有模式） | 现有 freeze 事务（record 先、snapshot 后，fail-closed） | n/a |
| Existing artifact contract compatibility | 中（entry.artifact_dir 语义改变） | 高（frozen record/snapshot 契约已存在） | 中（需要新 runtime） |
| Legacy compatibility impact | 无（canonical-only） | 无（canonical-only） | 无（不采用） |
| O1 closure strength | 条件性 FULL（写域隔离后） | 条件性 FULL（写域隔离后） | 跨边界 0；host 内部分 |
| Implementation scope | 中 | 小 | 架构级 |

## 2. 判定

```text
OPTION_A = digest-binding / locator 层（名字=digest 便于审计）
OPTION_B = object 层（复用 frozen snapshot 作为 mount source）
OPTION_C = REJECT（NOT SUFFICIENT FOR CURRENT ARCHITECTURE）

RECOMMEND = HYBRID（B + A 的 digest 身份绑定）
```

最小组合：

```text
B 提供：不可变 execution snapshot 对象（现有 frozen snapshot + 写域隔离）
A 提供：digest 身份绑定（verify snapshot digest == anchored run_request
        artifact_digest；路径是否叫 digest 不改变安全性）
```

两者共用同一不可变机制：**写域隔离**。没有它，A/B 都只是把 O1 的攻击面
从 registry 目录挪到 snapshot 目录。

