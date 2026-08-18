# Phase 9-D.2 Synthesis — O1 Runtime TOCTOU Closure Design Freeze

- 日期：2026-08-18
- 基线：`ee1c639`（9-D.1 实证 O1）
- 范围：DESIGN ARCHAEOLOGY + OPTION COMPARISON + DESIGN FREEZE
- 未修改 production code、未新增 production tests、未修改 Run Intent /
  Authority / b3_entry / Legacy、未引入外部安全基础设施、未 commit
- 临时 probe（/tmp）已清理，不进入 Git

## 1. 关键实证

### 9-D.1（基线，复述）

```text
O1 = CONFIRMED SECURITY GAP
verify(A) -> replace A→B -> docker mount -> container observes B
5/5 确定性攻击；9/18 自然竞态
FILESYSTEM_OBJECT_BINDING = PATH-ONLY
```

### 9-D.2 新增证据

```text
1. Docker Desktop 4.57.0 / Engine 29.1.3 / linux aarch64 / overlayfs / API 1.52 确认
2. docker inspect：bind mount Source 是 path string；daemon 容器创建时解析
3. container inode（1392）≠ host inode（34691380）——对象身份不可跨 VM
4. POST_MOUNT_FILE_MUTATION = VISIBLE：
   - 运行中容器内 cat 看到 host in-place 改写（A2）
   - 运行中容器内 cat 看到 host 原子文件替换（A3）
   - 目录级 rename swap 仍不可见（9-D.1）
   -> “window 在容器创建时关闭”只对目录对象成立，不对文件内容成立
5. macOS 无 O_PATH / openat(Python) / memfd / clonefile；chflags 不构成同 uid 隔离
6. 当前 frozen snapshot 权限普通（0755/0644，david:staff），无写域隔离；
   frozen 目前只是逻辑/元数据语义
```

## 2. 对象模型结论

```text
Path              = locator（可替换，不是身份）
Digest            = 验证时刻的内容身份（≠ immutability）
FD / inode        = 不能跨 Python -> Docker Desktop VM（C 不可行）
Snapshot（frozen） = 唯一接近“不可变执行对象”的现成载体；
                     真正不可变 = 写域隔离，不是 digest 名
```

## 3. 方案判定

```text
OPTION_A（digest 命名 snapshot） = digest-binding / locator 层；单独不闭合 O1
OPTION_B（mount frozen snapshot） = object 层；复用现成 frozen snapshot，最小新增
OPTION_C（open-by-handle）       = REJECT / NOT SUFFICIENT FOR CURRENT ARCHITECTURE

RECOMMEND = HYBRID
  B：mount source = frozen_root/frozen/<candidate_id>/artifact
  A：digest 身份绑定（verify E(D) digest == anchored run_request.artifact_digest）
  C：不使用；若未来迁移 native Linux runtime 再评估
```

## 4. 不可变机制

```text
IMMUTABILITY_MECHANISM = 写域隔离（snapshot store owner != runtime user；
  目录 0555 / 文件 0444；原子发布；发布后无写路径）+ verify_frozen 检测兜底
```

诚实声明：

```text
digest 命名本身不是 immutable；:ro 挂载本身不是 immutable；
path equality 本身不是 object equality。
没有写域隔离时，A/B 都只是把攻击面从 registry 目录移到 snapshot 目录，
O1 仍然可赢（包括 mount 后的文件级 mutation，本轮新证据）。
因此“真正闭合”以 07-§5 部署契约为必要条件；
契约不满足时，诚实判定为 NO SAFE MINIMAL OPTION（same-writer boundary）。
```

## 5. Final Design Verdict

```text
PHASE_9D2_VERDICT = READY
O1_SOLUTION = HYBRID（B base + A digest binding；C REJECT）

VERIFIED_OBJECT_MODEL =
  E(D) = frozen_root/frozen/<candidate_id>/artifact
  D = anchored run_request.artifact_digest == authority/frozen/seal digest

IMMUTABILITY_MECHANISM =
  write-domain isolation of E(D) store
  （owner != runtime user；0555/0444；atomic publish；no post-publish writes）
  + verify_frozen full digest recompute as detection backstop

MOUNT_BINDING_MODEL =
  Docker bind mount E(D) -> /artifact:ro
  path equality enforced by RUNTIME_BINDING_MISMATCH；
  object equality enforced by store immutability（不是 ro，不是 digest 名）

DOCKER_DESKTOP_COMPATIBILITY =
  YES（普通 host 目录；4.57.0/29.1.3/aarch64 实测）
  注意：文件级 host 写实时进入运行中容器 -> 必须写域隔离

MACOS_COMPATIBILITY =
  YES（APFS；无 O_PATH/memfd，不需要）

PERFORMANCE_IMPACT =
  0 per-run copy；verify 每 run O(bytes)（现状已有）；
  canonical 可去掉 registry copy -> 每 candidate 1 份（现状 2 份）

LEGACY_IMPACT =
  无（canonical-only）；legacy O1 保留 = LEGACY SECURITY DEBT

IMPLEMENTATION_BOUNDARY =
  capabilityizer.py（freeze 发布前 chmod / 无 post-publish 写）
  + runtime_adoption_guard.py（canonical 只接受 frozen snapshot mount source）
  + harness.py（b3 canonical 分支 mount snapshot）
  registry.py 可选（canonical 停止复制到 registry）；
  sandbox.py / adoption_authority.py / Run Intent / b3_entry / Legacy 不改

O1_CLOSURE_INVARIANT =
  Verified Artifact Identity
    == Execution Snapshot Identity
    == Mounted Object Identity
  且 runtime observed bytes == verified bytes

  verify digest D
    -> E(D)（写域隔离不可变）
    -> mount E(D) :ro
    -> container observes D

  replace registry A->B ：不影响 runtime
  replace snapshot A->B ：REJECT 或不可能（写域隔离）

OPEN_QUESTIONS =
  1. 写域隔离的部署形态：root-owned store + 特权 freeze 步骤 /
     独立账号 / 只读卷；pilot 单用户环境如何落地
  2. 是否保留 registry live copy（工具兼容）还是 canonical 彻底移除
  3. 大 artifact（多文件/Node deps/MCP bundles）的 verify 成本与
     可选容器内 digest gate（copy-to-tmpfs 再执行）何时需要
  4. Legacy O1 的最终处置（保留 / 弃用 / 迁移）
  5. 未来 native Linux sandbox runtime（bubblewrap --ro-bind-fd）时
     是否重开 Option C
```

## 6. 为什么最终 mount 的对象一定是 verify 时的对象

```text
1. mount source 固定为 E(D)：由 anchored run_request 派生，唯一对象
2. E(D) 在 host 写域内不可变：verify 后到 mount 之间、mount 之后
   （容器整个生命周期）都无法被替换或改写
3. verify 的对象就是 E(D)（对 snapshot 重算 digest，而不是对 registry live dir）
4. Docker 按 path 二次解析的对象只能是 E(D)；E(D) 不可变
   -> VERIFIED_OBJECT == MOUNTED_OBJECT == CONTAINER_OBSERVED
```

## 7. 本阶段输出

```text
01-current-runtime-object-model.md
02-option-a-digest-snapshot.md
03-option-b-frozen-snapshot.md
04-option-c-open-by-handle.md
05-docker-macos-object-binding-analysis.md
06-option-comparison.md
07-o1-closure-invariant.md
08-adversarial-coverage.md
09-operational-impact.md
10-minimal-implementation-boundary.md
99-synthesis.md
```

边界确认：未修改 production code、未新增 production tests、未实现 O1、
未 commit。临时 probe 位于 `/tmp`，运行后已清理。

