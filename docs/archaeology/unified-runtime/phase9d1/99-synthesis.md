# Phase 9-D.1 Synthesis — Runtime Verify-to-Bind-Mount TOCTOU

- 日期：2026-08-18
- 基线：`a70a433`
- 范围：CODE ARCHAEOLOGY + RUNTIME PATH ANALYSIS + ADVERSARIAL TOCTOU PROBES
  + OS/CONTAINER BEHAVIOR VERIFICATION；未修改 production code、未修 O1、
  未 commit。
- 方法：production 函数（`verify_at_mount` / `docker_launch`）+ 一次性
  canonical registry（/tmp）+ Docker Desktop 29.1.3 实测。

## 关键证据

1. Check = `verify_at_mount` 内 `frozen_artifact_violations` 对 live
   mount source 重算 canonical digest（capabilityizer.py:49,431；
   runtime_adoption_guard.py:513,549）。
2. Use = `-v <verified_artifact_dir>:/artifact:ro`（sandbox.py:28,32），
   daemon 在容器创建时按 path string 二次解析并 bind mount。
3. Check 与 Use 之间只有 path string；无 fd / inode / snapshot pin。
4. 确定性攻击 5/5 成功：directory replacement、atomic rename、symlink、
   in-place mutation、atomic file replace —— verify ALLOW(A) 后容器全部观察到 B。
5. 自然竞态（无 barrier，攻击线程每 ~2ms 交换）：18 次 ALLOW → 9 次观察到 B。
6. 容器创建后替换 host 目录不再被观察（window 结束点）。
7. mount line：`/run/host_mark/private ... fakeowner` —— host path 经 VM
   共享层解析，Python check 与内核 mount 不是同一次解析。

## Final Verdict

```text
PHASE_9D1_VERDICT = PASS_WITH_FINDINGS

O1 = CONFIRMED SECURITY GAP

CHECK_USE_WINDOW = OPEN（verify 最后一次 read_bytes 之后、容器创建 bind mount 之前；
                   实测可赢）
FILESYSTEM_OBJECT_BINDING = PATH-ONLY（不 pin inode/fd/snapshot；
                                   same-path different-inode 实测运行 B）
CONTAINER_OBSERVATION = B OBSERVED（5/5 确定性攻击；9/18 自然竞态）
DOCKER_LIVE_VERIFIED = YES（Docker Desktop 29.1.3, macOS 26.5.1, aarch64,
                           overlayfs, API 1.52）
MIGRATION = NON-BLOCKING

NEXT_PHASE = O1 Closure Design（候选机制不做预设；候选包括 digest 命名不可变
             snapshot 作为 mount source、mount frozen snapshot、
             open-by-handle / O_PATH、镜像化不可变对象；本阶段不选择、不实现）
```

## 本阶段输出

- 01-runtime-mount-lifecycle.md
- 02-check-use-boundary.md
- 03-toctou-window.md
- 04-adversarial-probes.md
- 05-filesystem-object-analysis.md
- 06-docker-macos-analysis.md
- 07-industry-comparison.md
- 08-o1-gap-analysis.md
- 99-synthesis.md

## 边界声明

- 未修改 production code、legacy、trust anchor、Run Intent、b3_entry。
- 未引入新依赖，未 commit。
- 临时 probe 位于 `/tmp`，运行后已清理，不进入 Git。
- 威胁模型：same-user / same-filesystem-writer 并发攻击者。此权限下
  O1 真实存在；不是“只能写在理论模型上”。

