# Phase 9-D.2.02 — Option A: Digest-Named Immutable Snapshot

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：option archaeology；未实现

## 1. 模型

```text
artifact A
  -> digest D
  -> snapshot path derived from D
  -> snapshot immutable
  -> verify snapshot
  -> mount snapshot
```

## 2. 十个必须回答的问题

### Q1. snapshot 的真正 immutable 机制是什么？

不是“目录名 = digest”。名字只提供 content-addressed locator。真正机制必须是：

```text
1. 写域隔离：snapshot store 的 owner 与 runtime user 分离
   （目录 0555、文件 0444；runtime user 只读）
2. 原子发布：tmp 完整构建 -> os.replace 到最终位置；发布后 parent 也不可写
   （否则整个 snapshot 目录可被 rename 掉）
3. 发布后无写路径：freeze/promote 之后没有任何代码再写 snapshot
4. 检测兜底：verify_frozen 全量重算 digest（检测已发生的篡改，不是不可变机制）
```

### Q2. snapshot 是复制、硬链接、目录 clone、CAS、其他？

当前 `freeze_candidate` 用 `shutil.copytree`（capabilityizer.py:213），普通复制；
macOS Python 实测无 `os.clonefile`。未来可选 APFS clonefile 提速（copy-on-write），
但同一不可变语义仍必须靠写域隔离，clone 本身不防写。

### Q3. verify 后路径是否仍可被替换？

可以，只要 snapshot store 对攻击者可写。当前 pilot 状态全部是
`david:staff`、目录 0755、文件 0644、无 flags（本轮 `ls -lO` 实测），
同 uid 攻击者可替换/改写。写域隔离后才不可。

### Q4. 谁拥有 snapshot？

创建者 = freeze / promote 写者；安全要求 = **store owner != runtime user**。
如果 owner 与 runtime user 相同，chmod 可被同一 uid 改回，不构成隔离。

### Q5. snapshot 生命周期？

与 frozen record 相同：write-once；被 authority / run_request 引用期间不可删除
（`referenced_candidate_ids` fail-closed，capabilityizer.py:503）。

### Q6. 多次 run 是否共享 snapshot？

是。共享只读对象，无 per-run copy，无并发写。

### Q7. snapshot GC 如何处理？

冻结：**不做基于时间的 GC**。只有显式生命周期处置 + referenced guard 保护；
运行时 GC 与读取竞争会产生新的 TOCTOU，本设计禁止。

### Q8. Crash recovery？

沿用 freeze 事务：record 先 `os.link`、snapshot 后 `os.replace`
（capabilityizer.py:213 附近）。中间态（有 record 无 snapshot）被
`verify_frozen` 判 `FROZEN_CANDIDATE_INCOMPLETE`，fail-closed，不自动修复。

### Q9. Docker mount 是否仍然 path-based？

是。Docker API/CLI 的 bind mount `Source` 是字符串（本轮
`docker inspect` 实测 `Source: "/tmp/o1_d2_probe/artifact"`），daemon 在容器
创建时解析。Option A 不能改变这一点。

### Q10. 为什么攻击者不能替换 snapshot？

唯一答案：**snapshot store 不在攻击者写域内**。名字 = digest 不提供任何保护。

## 3. digest ≠ snapshot（冻结）

```text
digest  回答：“当前 bytes 是不是预期 bytes？”（capabilityizer.py:49 验证时刻）
snapshot回答：“未来执行时还能不能被改变？”（写域隔离）
```

两个问题独立。把目录命名为 digest 只解决定位与审计，不解决不可变。

## 4. copy race / freeze race / GC race

| race | 分析 | 处置 |
|---|---|---|
| copy race | copytree 期间源变化 -> 快照是混合内容 | freeze 后 record 记录 digest；runtime `verify_frozen` 重算检测 -> REJECT，不静默执行 |
| freeze race | record `os.link` 先于 snapshot `os.replace`；窗口内有 record 无 snapshot | `FROZEN_CANDIDATE_INCOMPLETE` fail-closed |
| GC race | 删除被引用 snapshot 与 runtime 读取竞争 | 引用期间禁止删除；不做 GC |
| 发布 race | 发布后 parent 可写 -> 整目录 rename 替换 | parent 层级写域隔离（0555 + owner 隔离） |

## 5. 判定

```text
OPTION_A = 可作为 digest-binding / locator 层（名字=digest，便于审计与共享同字节对象）
OPTION_A 单独 = 不闭合 O1（digest 命名不是不可变机制）
OPTION_A 闭合条件 = 写域隔离（见 07 号文件部署契约）
```
