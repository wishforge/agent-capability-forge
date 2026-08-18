# Phase 9-D.4 Synthesis — Execution Snapshot Owner Isolation Validation

- 日期：2026-08-19
- 基线：`de38f88` 已确认在 `origin/main`（push → Everything up-to-date）
- 方法：真实 host 环境调查 + 一次性 `/private/tmp` canonical store + guard/OS
  两层验证；D.3 套件复跑 15 passed
- 产物：仅 validation / archaeology 文档；无生产代码、无生产测试改动、无 commit

## Verdict

```text
PHASE_9D4_VERDICT = PASS_WITH_FINDINGS

OWNER_ISOLATION = OPEN
STORE_OWNER_UID = 501 (david)
RUNTIME_UID = 501 (david)     # 部署目标：4294967294 (macOS nobody) / 65534 (Linux nobody)
LIVE_MULTI_UID_PROOF = NO

READ_ACCESS = PASS（store spine 预测可读可 traverse；repo 内 /Users/david 0750 会阻断
             无关用户 → 部署需移出 store 或开放祖先 traverse）
WRITE_ACCESS = BLOCKED（模式位 + guard；owner 可 chmod，真实防线是身份不同）
RENAME_ACCESS = BLOCKED（OS 层预测；未以真实 B live 验证）
DELETE_ACCESS = BLOCKED（OS 层预测；未以真实 B live 验证）
CHMOD_CHOWN_ACCESS = BLOCKED（chown 非 root 一律 EPERM；chmod 仅 owner 有效）
CANONICAL_RUNTIME = BLOCKED（本机 same-owner fail-closed；runtime_uid=B 时 guard 级
                   ALLOW，但不是 live proof）

O1 = CLOSED（object-level：E(D) 不可变 + digest 绑定 + 仅 snapshot mount）
MIGRATION = NON-BLOCKING
NEXT_PHASE = 部署级 owner isolation：真实第二 OS user / 专用 service account
             + store 置于 B 可 traverse 路径 + 以 B 重跑 mutation matrix
             + canonical runtime 以 B 身份 ALLOW；之后可增加长期 regression test
```

## Closing 条件（未满足）

```text
1. Store Owner != Runtime User 真实成立        # 当前 501 == 501
2. Runtime User B 真实 OS 身份：
   read / traverse / execute = ALLOW
   write / rename / replace / delete / chmod / chown = OS DENIED
3. Canonical runtime 以 B 身份 ALLOW 且观察到 A
```

## 本阶段确认的代码事实

- guard 从 `frozen_root.stat().st_uid` 读 owner，从 `os.getuid()` /
  `runtime_uid` 读 runtime；same-owner 一定 REJECT（fail-closed）。
- guard 是 stat 级判断；OS 层不可写仍需真实第二身份验证。
- `freeze_candidate_dir` 发布顺序为 tmp → verify → fsync → chmod → atomic
  rename → 硬化；runtime user 只能看到 absent 或 complete snapshot。
- harness canonical b3 只 mount `E(D)`，digest/identity 在 mount 前重验。
- 本地无 passwordless sudo、`launchctl asuser` 不可用 → 真实多 UID 证明
  在本机不可执行；结论保持 `OWNER_ISOLATION = OPEN`，不降低安全标准。

## 业务不变量

> 上线版本生成的不可变执行快照，只能被 Runtime 使用，不能被 Runtime 自己修改；
> 因此上线版本和实际运行版本始终一致。

当前：代码层已 fail-closed（本机 same-owner 部署被 guard 拒绝）；部署层
owner-isolation 未在本机闭环，关闭它需要真实不同 OS identity 的 live 验证。
