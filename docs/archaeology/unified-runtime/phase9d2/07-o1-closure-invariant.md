# Phase 9-D.2.07 — O1 Closure Invariant（Design Freeze）

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：design freeze；未实现

## 1. 冻结不变式

```text
Verified Artifact Identity
        ==
Execution Snapshot Identity
        ==
Mounted Object Identity

且：
runtime observed bytes == verified bytes
```

具体链：

```text
Run Intent A（anchored store["run_request"]）
  -> Artifact Digest D（run_request.artifact_digest == authority/frozen/seal）
  -> Execution Snapshot E(D)
       = frozen_root/frozen/<candidate_id>/artifact
  -> E(D) immutable（写域隔离：store owner != runtime user；
      目录 0555、文件 0444；原子发布；发布后无写路径）
  -> verify(E(D))：canonical digest 重算 == D
  -> mount E(D) :ro
  -> container 执行 /artifact/main.py，观察到的 bytes == D
```

## 2. 三个必须冻结的原则

```text
1. digest verification ≠ immutability
   digest 只证明验证时刻的 bytes；不保证未来执行时不可变。

2. container read-only ≠ host artifact immutable
   :ro 只挡容器侧写；host 侧文件级写实时进入容器（05-§3 新证据）。

3. path equality ≠ object equality
   verified_path == mount_source 由 RUNTIME_BINDING_MISMATCH 强制（应用层，
   已闭合）；它不 pin 对象。对象同一性只能由“对象不可变”保证。
```

## 3. 对称性要求（目录 / 多文件 / symlink / metadata）

```text
目录       ：E(D) 是目录；mount 后目录对象被 pin（9-D.1），但目录内文件实时
多文件     ：allowlist 精确布局 + 全量 canonical digest（capabilityizer.py:56-88）
symlink    ：canonical snapshot 构造上无 symlink（copytree symlinks=False 解析）
metadata   ：canonical 只验证 bytes + layout；权限/ownership 由写域隔离统一保证
嵌套 artifact：按 allowlist 展开验证；snapshot 复制保持相对路径
```

## 4. Symlink 政策（冻结）

```text
方案一（禁止 symlink）＝ SECURITY INVARIANT（canonical）
  - 不是靠扫描器“拒绝”，而是构造保证：copytree(symlinks=False) 已解析，
    写域隔离后无人能再插入 symlink
  - 现有 canonical artifact 只含 main.py，无 symlink；无兼容负担

方案二（允许 symlink 并解析固定）＝ 同一机制的实现细节（freeze 时解析），
  不是与方案一竞争的策略

Legacy 路径     ＝ COMPATIBILITY BEHAVIOR（保持历史语义；不修改）
```

## 5. 闭合所需部署契约（必要条件）

```text
EXECUTION_SNAPSHOT_STORE_OWNER != RUNTIME_USER
  - snapshot store（frozen_root）由可信写者创建/拥有
  - runtime user 对 store 只有读/执行（目录 0555、文件 0444）
  - parent 层级同样只读，防止 rename 替换
```

诚实声明：

```text
若不满足该部署契约（当前单用户 pilot 即如此），A/B 只是把 O1 的攻击面
从 registry 目录移到 snapshot 目录，验证与 mount 之间仍可被同 uid 攻击者
赢下 -> 不能声称已闭合。
```

## 6. Acceptance Criteria（冻结）

```text
A approved
  -> A verified
  -> A snapshot E(D) created
  -> E(D) immutable（写域隔离；替换/改写不可能，或修改后 verify 必 REJECT）
  -> E(D) mounted :ro
  -> container observed bytes == D

replace original registry A -> B  ：不影响 runtime（mount source 是 E(D)，不是 registry）
replace verified snapshot A -> B   ：REJECT（verify 重算失败）或不可能（写域隔离）
```

