# Phase 9-D.4.03 — Filesystem Permission Probes

方法：在 `/private/tmp` 下创建一次性 canonical store（mkdtemp 后 chmod 0755），
使用生产代码 `freeze_candidate_dir` 发布 E(D)，与 D.3 live probe 相同的构造路径。

## 1. Store spine stat（发布后）

| path | uid | gid | mode |
|---|---|---|---|
| frozen_candidates | 501 | 0 | 0555 |
| frozen_candidates/frozen | 501 | 0 | 0555 |
| frozen/cand-A | 501 | 0 | 0555 |
| frozen/cand-A/artifact | 501 | 0 | 0555 |
| artifact/main.py | 501 | 0 | 0444 |
| frozen/cand-A.json | 501 | 0 | 0444 |

（gid=0 为 `/private/tmp` 临时目录继承；仓库内实际文件为 david:staff。
模式位与生产发布逻辑一致：目录 0555、文件 0444。）

## 2. POSIX 预测：runtime user = macOS nobody（uid/gid 4294967294）

| path | read | traverse | write | rename/unlink | chmod/chown |
|---|---|---|---|---|---|
| /private/tmp（1777） | YES | YES | YES（sticky 下不可删他人条目） | NO | NO |
| store spine（0555） | YES | YES | NO | NO | NO |
| main.py / record（0444） | YES | n/a | NO | NO | NO |

预测依据：B 非 owner、非 gid 0 组员、非 root，命中 other 位 r-x / r--。

## 3. 仓库路径预测：同一 runtime user B

| path | 结果 |
|---|---|
| /Users/david（0750） | READ/TRAVERSE = DENIED |
| 其余仓库目录（0755） | READ/TRAVERSE = ALLOW，WRITE = DENIED |

## 4. 0444/0555 不是唯一防线

- owner 可以 `chmod`（实测成功）→ 模式位对 owner 无效。
- owner 也不能 `chown`（macOS 非 root → EPERM）。
- 因此真正防线是 owner != runtime user + OS permission enforcement。
