# Phase 9-D.2.08 — Adversarial Coverage

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：design freeze；未实现

设计模型（07 号文件）下逐攻击验证：

```text
Mount Source = E(D) = frozen_root/frozen/<candidate_id>/artifact
E(D) immutable = 写域隔离（owner != runtime user；0555/0444；原子发布）
Verify = verify_at_mount 对 E(D) 重算 canonical digest == run_request.artifact_digest
```

| # | 攻击 | Why blocked | Boundary | Invariant |
|---|---|---|---|---|
| 1 | directory replacement（registry A→B） | registry 不再是 canonical mount source；替换它不影响 E(D)；adopt 若仍查 registry 则 REJECT | promote/registry 写域 | mount source 来自 frozen snapshot |
| 2 | atomic rename（registry 或 snapshot） | snapshot store 不可写 -> rename 不可能；若 verify 前发生 -> digest mismatch REJECT | snapshot store 写域 | E(D) immutable + verify |
| 3 | symlink replacement | freeze 时 copytree 已解析；store 不可写 -> 无法插入 symlink；checker 侧无需再拒绝 | snapshot store 写域 | canonical snapshot 无 symlink |
| 4 | in-place content mutation | store 不可写 -> 不可能；若 verify 前发生 -> digest mismatch REJECT | snapshot store 写域 | E(D) immutable + verify |
| 5 | atomic file replacement | 同 #4 | snapshot store 写域 | E(D) immutable + verify |
| 6 | same path / different inode | inode 无关：路径对象不可变，任何对象替换要么不可能、要么 digest mismatch | snapshot store 写域 | VERIFIED_OBJECT == MOUNTED_OBJECT |
| 7 | registry path replacement | 同 #1 | registry 写域（不再进入 mount） | mount source 是 E(D) |
| 8 | runtime locator replacement（b3_entry / run_request） | 已由 9-B.5 闭合：anchored run_request + RUN_REQUEST_CACHE_MISMATCH / INTEGRITY_STORE_CORRUPTED | trust store 写域 | Run Intent 锚定 |
| 9 | post-mount 目录 rename swap | 目录对象在容器创建时被 VM 侧 pin（9-D.1） | mount 时点 | mount pins 目录对象 |
| 10 | post-mount 文件 mutation（本轮新确认） | snapshot store 不可写 -> host 侧无写权限，运行中容器不可能看到新字节 | snapshot store 写域（全程，不只 mount 前） | E(D) immutable 覆盖整个容器生命周期 |

## 残余（如实声明）

```text
1. 若部署契约（07-§5）不满足：
   #2/#4/#5/#10 全部仍可被同 uid 攻击者赢下
   -> 判定降级为 NO SAFE MINIMAL OPTION（same-writer boundary）

2. Legacy 路径（非 canonical）不采用本设计：
   verify(live registry dir) -> mount(live dir) 的 O1 原样保留
   -> 记录为 LEGACY SECURITY DEBT（本阶段不扩大 scope）

3. 攻击者若拥有 snapshot store owner 或 trust root 写权限：
   属既有的同写者 / trust-root 边界（9-C Q7），本设计不新增承诺
```

