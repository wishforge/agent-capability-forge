# Phase 9-D.5.01 — Real Multi-UID Environment

- 日期：2026-08-19
- 实现基线：`de38f88 fix(runtime): close verified artifact mount race`
- 文档基线：`2536d13 docs(archaeology): validate execution snapshot owner isolation`
  （HEAD == origin/main，已推送）
- 范围：只读环境调查 + `/private/tmp` 一次性 probe；无生产代码改动、无 guard 改动

## 1. Host identity

| 项 | 值 |
|---|---|
| uid | 501 (david) |
| gid | 20 (staff) |
| whoami | david |
| uname | Darwin Mac 25.5.0 arm64 (xnu-12377.121.6) |
| sw_vers | macOS 26.5.1 (Build 25F80) |
| Docker | 29.1.3 build f52814d |

## 2. 本机真实用户（`dscl . -list /Users UniqueID`，本阶段复核）

- 唯一真实开发者/人类用户：david (501)
- 其余非 `_` 账号：root (0)、daemon (1)、nobody (-2)
- 低权限系统账号可作为 B 候选：nobody (4294967294)、_www (70)、daemon (1)
- 不存在已创建的非管理员低权限人类账号

## 3. UID switch 可用性

| route | result（本阶段复核） |
|---|---|
| `sudo -n -u nobody id` | `sudo: a password is required`（exit 1） |
| `launchctl asuser` | D.4 已记录 `Operation not permitted`，本阶段不重复 |

sudo 需要密码；当前没有 passwordless sudo。创建临时测试账号同样需要管理员密码
（sysadminctl / dscl），不满足 D.5 第 4 节“安全创建临时用户”的前提，且不得绕过
macOS 安全策略。

## 4. 结论

```text
LIVE_MULTI_UID_ENVIRONMENT = UNAVAILABLE
A (Store Owner) = 501 (david)
B (Runtime User) = 无真实可切换身份
```

按 D.5 第 4 节：不伪造 PASS，停止 live B 矩阵与 live canonical runtime 验证。
本阶段只做 store path 权限模型 + guard 级/owner 级复核；以下文档明确标注哪些是
POSIX 预测、哪些是 live 证据。
