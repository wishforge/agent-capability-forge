# Phase 9-D.1.08 — O1 Gap Analysis

## Q1. Verify 的准确 check point

`verify_at_mount`（`pilot/runtime_adoption_guard.py:549` 调用 `adopt`）内，
`frozen_artifact_violations` 对 **live mount source 目录** 重算 canonical digest，
最后一次字节读取在 `src/forge/capabilityizer.py:49`
（`path.read_bytes()`，经 `capabilityizer.py:431`）。

## Q2. 实际 mount / use point

`pilot/harness.py:786` 调用 `docker_launch`；`src/forge/sandbox.py:28` 构造
`-v <verified_artifact_dir>:/artifact:ro`；`sandbox.py:32` 发起 docker。
真正的内核 bind mount 在 Docker Desktop VM 内、容器创建时完成
（实测 mount line：`/run/host_mark/private ... fakeowner`）。

## Q3. 是否存在可攻击窗口

**存在，且实测可赢**。window = verify 最后一次 read_bytes 完成
（capabilityizer.py:49）→ daemon 容器创建时解析 mount source。
自然竞态实测：18 次 ALLOW 中 9 次容器观察到 B。

## Q4. A→B directory replacement 是否真实可行

**可行**（P1：rm + mkdir + copy 后容器观察到 B，exit 0）。

## Q5. Atomic rename 是否真实可行

**可行**（P2：os.replace 三连，路径不变、inode 变化、容器观察到 B）。

## Q6. Symlink replacement 是否适用

**适用**（P3：verify 后 A 换成指向 B 的 symlink，docker 跟随，容器观察到 B）。
另外 checker 本身接受 artifact path 为 symlink（symlink-at-check probe ALLOW）。

## Q7. Same path / different inode 是否可导致 B 被执行

**可以**（P2：path 不变、inode 36525652→36525660、容器观察到 B）。
系统信任 path，不是被验证的 object。

## Q8. Docker Desktop/macOS 实际行为

- Docker Desktop 29.1.3 / macOS 26.5.1 / Linux VM aarch64 / overlayfs。
- host path 在容器创建时由 daemon 解析并 bind mount；
  verify 与容器创建之间的 host 替换被容器看到；
  容器创建之后的 host 替换不被看到。
- Python check 与内核 mount 是两次独立按名字解析，中间隔 VM 共享层。

## Q9. 系统信任的是

```text
path   : runtime mount reference（verified_artifact_dir path string）
digest : application identity（check 时刻，不持续 pin）
inode  : 不信任/不记录
fd     : 无
snapshot: 仅作验证参考，不是 mount source
```

## Q10. O1 分类

```text
O1 = CONFIRMED SECURITY GAP
```

依据：当前边界（canonical runtime + macOS + Docker Desktop 29.1.3）下，
`verify(A) -> mount(B)` 已通过 production 函数实测成功（5/5 确定性攻击；
9/18 自然竞态）。这不是纯理论模型。

## 威胁模型边界（如实说明）

- 攻击者需要与 harness 相同的 filesystem 写权限（能写
  `pilot/state/registry/F+/<name>/artifact`）。
- 该权限下攻击者本可篡改其他未锚定输入；但本阶段问题是“验证通过的 A 是否
  可能变成执行的 B”，答案是 **能**，且发生在 application 验证闭合之后。
- 未修改 production code；未修 O1；未 commit。

