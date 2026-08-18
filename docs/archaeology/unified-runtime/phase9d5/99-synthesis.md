# Phase 9-D.5 Synthesis — Real Multi-UID Deployment Validation

- 日期：2026-08-19
- 实现基线：`de38f88`；HEAD `2536d13`（D.4 已推送）
- 方法：真实环境复核（dscl 全量用户、sudo -n、逐级 stat）+ `/private/tmp` 一次性
  canonical store probe（publish/guard/mutation/verify）+ D.4 证据引用
- 产物：仅 archaeology 文档；无生产代码改动、无 guard 改动、无测试改动

## Verdict

```text
PHASE_9D5_VERDICT = PASS_WITH_FINDINGS

LIVE_MULTI_UID_ENVIRONMENT = UNAVAILABLE
STORE_OWNER_UID = 501 (david)
RUNTIME_UID = 无真实 B（候选：nobody=4294967294 / _www=70 / daemon=1）
A != B = NO

ANCESTOR_TRAVERSE = CLOSED（stat/POSIX 模型 + guard；B live 复核留待真实部署）
READ_ACCESS = PASS（POSIX 预测；未以 B live）
WRITE_ACCESS = BLOCKED（POSIX 预测；未以 B live）
RENAME_ACCESS = BLOCKED（POSIX 预测；未以 B live）
DELETE_ACCESS = BLOCKED（POSIX 预测；未以 B live）
CHMOD_CHOWN = BLOCKED（POSIX 预测；未以 B live）
CANONICAL_RUNTIME = BLOCKED（无 B，未 live 验证）

O1 = CLOSED（object-level 不变）
OWNER_ISOLATION = OPEN
MIGRATION = NON-BLOCKING
```

## 为什么不是 PASS

完成条件要求 `A != B` 并且以真实 B 完成 live 矩阵。本机唯一真实用户是 david(501)，
`sudo -n` 需要密码、`launchctl asuser` 不可用，无法切换到 nobody/_www/daemon，
也不能安全创建临时账号。按 D.5 第 4 节，记录 UNAVAILABLE 并停止，不伪造 PASS。

## 本阶段确认

1. D.4 的第二个问题已给出可落地路径：store 移到 `/Users/Shared/...` 或等价
   B 可 traverse 的独立根下；逐级 stat 已证明 `/Users/david` 之外的候选祖先
   对 B 开放 traverse。
2. 真实 store（A 发布）spine 为 0555/0444，owner 级 mutation 全部 PermissionError，
   digest 不变；guard 对 nobody 元数据级 ALLOW，对 same-owner REJECT。
3. Canonical runtime 的 b3 路径仍只 mount E(D)，与 D.3/D.4 一致。

## 下一步（关闭 OWNER_ISOLATION 所需）

1. 在具备真实多 UID 的主机（Linux CI service account 或 macOS 管理员创建临时账号）
   部署 store 到 `/Users/Shared` 风格根路径。
2. 以 B 重跑：read/traverse matrix、mutation matrix（含 same-path different-object）、
   post-mount mutation、canonical runtime ALLOW。
3. 全部通过后再把 `OWNER_ISOLATION = CLOSED` 写回。
