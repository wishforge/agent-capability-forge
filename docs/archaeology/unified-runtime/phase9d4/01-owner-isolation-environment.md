# Phase 9-D.4.01 — Owner Isolation Environment

- 日期：2026-08-19
- 基线：`de38f88 fix(runtime): close verified artifact mount race`
- 分支：`main` 与 `origin/main` 同步（`git push origin main` → Everything up-to-date）
- 范围：只读系统调查 + 临时 `/private/tmp` probe；无生产代码改动、无 commit

## 1. Host identity

| 项 | 值 |
|---|---|
| uid | 501 (david) |
| gid | 20 (staff) |
| groups | 12,20,33,61,79,80,81,98,100,204,250,395,398,399,400,701 |
| whoami | david |
| uname | Darwin Mac 25.5.0 Darwin Kernel Version 25.5.0 arm64 (xnu-12377.121.6) |
| sw_vers | macOS 26.5.1 (Build 25F80) |

## 2. 本机用户（`dscl . -list /Users UniqueID`，节选）

| user | uid | 备注 |
|---|---|---|
| root | 0 | 特权身份 |
| daemon | 1 | 系统守护进程账号 |
| david | 501 | 当前开发/Store Owner |
| _www | 70 | 低权限系统账号 |
| _postgres | 216 | 低权限系统账号 |
| nobody | -2（unsigned uid_t = 4294967294） | macOS nobody，无 login shell |

完整列表还包括其余 `_` 系统账号，与本结论无关，不展开。

## 3. UID switch 可用性

| route | result |
|---|---|
| `sudo -n -u nobody id` | `sudo: a password is required` (exit 1) |
| `sudo -n -u _www id` | 同上 |
| `sudo -n -u daemon id` | 同上 |
| `launchctl asuser 65534 id` | `Failed to get user context: 1: Operation not permitted` |

结论：

```text
LIVE_UID_SWITCH = UNAVAILABLE
```

本机没有 passwordless sudo，不能切换到真实不同 OS user。以下文档不伪造结果。

## 4. Docker UID ≠ Host UID

Docker Desktop for macOS 的容器运行在 VM 中，container UID 与 host macOS UID
没有映射关系。本阶段验证 host filesystem permission，因此容器内 UID 不作为
owner-isolation 证据。
