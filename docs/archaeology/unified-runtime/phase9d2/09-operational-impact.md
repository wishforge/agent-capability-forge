# Phase 9-D.2.09 — Operational Impact

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：design freeze；未实现

## 1. Snapshot creation cost

- 复制发生在 freeze（capabilityizer.py:213 的 `shutil.copytree`），不是每次 run。
- 当前 canonical 路径实际有两份 artifact 副本：frozen snapshot + registry copy
  （registry.py:183）。改用 frozen snapshot 作为 mount source 后，canonical
  可去掉 registry copy -> 每 candidate 从 2 份降到 1 份。
- 未来大包（Python packages / Node deps / MCP bundles）可考虑 APFS clonefile
  COW 复制提速，但 clone 不改变不可变语义，仍需写域隔离。

## 2. Disk usage

```text
每 candidate 1 份 immutable snapshot（被 authority/run_request 引用期间保留）
无 per-run 副本
```

## 3. Concurrent runs

- 多 run 共享同一只读 snapshot；无 per-run copy、无锁。
- 读并发安全的前提是写域隔离（无写者）。

## 4. GC

- 冻结：不做基于时间的 GC；引用期间禁止删除（referenced guard fail-closed）。
- 显式生命周期处置（未来若需要）必须与“删除即 fail-closed”一致，且不能
  与运行中 verify 竞争。

## 5. Crash recovery

- 沿用 freeze 事务：record `os.link` 先、snapshot `os.replace` 后。
- 中间态 -> `FROZEN_CANDIDATE_INCOMPLETE`，fail-closed，不自动修复。

## 6. Long-running containers

- 写域隔离下：整个容器生命周期内 bytes 稳定。
- 没有写域隔离时：本轮已实测 host 文件级 mutation 会实时进入运行中容器；
  “mount 完成即安全”不成立。

## 7. Nested / large artifacts

- canonical 当前 allowlist 是 `["main.py"]`（capabilityizer.py:547 附近）；
  设计按全量 digest + 精确布局扩展（artifact_layout 已支持多文件）。
- verify 每 run O(total bytes)（read_bytes + sha256）。小 artifact 实测
  verify ~1.0-1.4ms；docker run 全程 277-2281ms，verify 不是瓶颈。
- 大 artifact：copy 成本在 freeze（一次性），verify 成本每 run 线性；
  未来可加 digest cache 或容器内流式验证，但本期不设计。

## 8. 安全/性能取舍

```text
用每 run 一次 digest 重算（现状已有）+ 写域隔离，换取：
  - 无 per-run copy
  - 无锁共享
  - 单一不可变执行对象
```

