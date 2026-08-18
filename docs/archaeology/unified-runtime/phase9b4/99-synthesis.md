# 99 Phase 9-B.4.1 Synthesis — b3_entry Trust-Anchor Closure

日期：2026-08-18 ｜ 基线：`85f8328` ｜ 阶段规则：只考古 + 探针，不修改 production code，不 commit

## Verdict

```text
O2 = REAL GAP（已授权候选之间的运行意图漂移）
```

## Current Trust Chain

```text
Trust Root      = 外部 integrity anchor（sealed digest 根，adoption_authority.py:123-177）
  ↓ 覆盖 store_digest / authority_manifest_digest / revocation_manifest_digest
Authority       = anchored store + authorities/ immutable ledger；adopt 全链重验
  ↓ BINDING_KEYS 全等 + artifact/seal digest 重算
Registry entry  = 未锚定，但每次 adopt 重验 -> 单独篡改 REJECT
  ↓ entry.artifact_dir + frozen digest 重算
b3_entry        = 未锚定；四元组仅与自身选中的 entry 的 report 自指比对
  ↓ name 决定 discover
Adoption        = adopt/verify_at_mount 全绿才 ALLOW
  ↓ 同一 verified 路径
Runtime         = docker_launch mount verified_artifact_dir（harness.py:768-777）
```

## Q&A

**Q1 b3_entry 的真实语义？**
Runtime Intent（D）+ Locator（E）的混合体：name/capability_id 是 locator，
四元组是 expected identity；两者共同构成 "这次运行谁" 的 run request。

**Q2 是否属于 security-sensitive state？**
是。Runtime 用它决定执行对象；一致替换可把运行意图从 A 改成 B。

**Q3 是否在 trust anchor 内？**
否。anchor 只覆盖 store + authorities + revocation events；probe 实测 seal 后改写
b3_entry 不触发任何 violation。

**Q4 b3_entry 替换成 Candidate B，Runtime 最终运行什么？**
一致替换（name+四元组=B）→ **ALLOW，运行 B**（probe P1，`verified_artifact_dir=.../beta/artifact`）。
单字段替换 → REJECT。

**Q5 artifact locator 被替换？**
registry entry.artifact_dir → B 时 REJECT（digest 重算）；b3_entry 内注入
verified_artifact_dir 字段被忽略（P11/P12）。identity→artifact 绑定闭合。

**Q6 b3_entry 删除？**
`FileNotFoundError`，无重建 / 无 fallback（P7）。

**Q7 version 被修改？**
REJECT `CANDIDATE_VERSION_MISMATCH`（P3/P8）。

**Q8 Authority / Registry / b3_entry 冲突谁赢？**
**Authority 赢**（adopt 以 anchored authority 为真）；Registry 与 b3_entry 必须一致，
任何不一致 REJECT。但一致替换时 b3_entry 的 name 重新选择 discover 目标，无仲裁者。

**Q9 当前 O2 是？为什么？**
REAL GAP：一致替换 b3_entry → Runtime B → ALLOW，且 b3_entry 不在 anchor 内。
范围限定：只能切换到另一个 authority-approved 候选，不能运行未授权代码。

**Q10 最小修复？**
Option A：把 run request 写进 anchored adoption_store（mark_promoted 后现有 anchor
自动覆盖），phase_future 以 anchored record 为唯一意图来源，b3_entry 降级为 cache。
Option B：给 anchor 增加 b3_entry digest 字段。详见 06 号报告。

## Adversarial Results（摘要）

| 场景 | Manipulation | Observed | Security Impact |
|---|---|---|---|
| whole swap | b3_entry → B（一致） | ALLOW B | **REAL GAP** |
| candidate_id swap | 仅 id → B | REJECT CANDIDATE_ID_MISMATCH | 无 |
| candidate_version swap | 仅 version → v99 | REJECT CANDIDATE_VERSION_MISMATCH | 无 |
| artifact_digest swap | 仅 digest → B | REJECT ARTIFACT_DIGEST_MISMATCH | 无 |
| seal_digest swap | 仅 seal → B | REJECT SEAL_DIGEST_MISMATCH | 无 |
| artifact locator swap | entry.artifact_dir → B | REJECT ARTIFACT_DIGEST_MISMATCH | 无 |
| deletion | 文件删除 | FileNotFoundError | 无 |
| stale version | v0 vs v1 | REJECT CANDIDATE_VERSION_MISMATCH | 无 |
| Authority vs b3_entry | authority A，b3_entry 指向 B | REJECT | 无（Authority 赢） |
| Registry vs b3_entry | registry→B，b3_entry 仍 A | REJECT | 无 |
| 一致改写 | registry→B 且 b3_entry→B | ALLOW B | **REAL GAP（同写者）** |

完整表见 03 号报告，probe 原始输出在 `/tmp/o2_probe_results.json`。

## Code Evidence（关键结论）

| 结论 | 文件 / 函数 / 行 | 行为 |
|---|---|---|
| b3_entry 由 harness 写入 | pilot/harness.py `phase_b3_build` :636-641 | promotion 后写六字段 JSON |
| name 是唯一 discover 键 | pilot/harness.py `phase_future` :698-699 | `json.loads` + `registry.discover(name)` |
| artifact 路径来自 entry | pilot/harness.py `phase_future` :750 | `artifact_dir = Path(entry["artifact_dir"])` |
| 四元组只与 adopt report 比对 | pilot/runtime_adoption_guard.py `verify_at_mount` :460-466 | `identity_violations(expected_identity, report)` |
| adopt 以 anchored authority 为真 | pilot/runtime_adoption_guard.py `adopt` :326-446 | store/ledger/frozen/digest 全链重验 |
| mount 唯一来源 | pilot/harness.py `phase_future` :768-777 | `artifact_dir = mount["verified_artifact_dir"]` 后 docker_launch |
| anchor 不覆盖 b3_entry | pilot/adoption_authority.py `integrity_anchor_violations` :123-177 | 只算 store / authorities / revocation 三个 digest |
| registry entry 未锚定但重验 | pilot/registry.py `discover` :254-260 + guard `adopt` | state==promoted + BINDING_KEYS 全等 |
| 单字段篡改错误码 | pilot/runtime_adoption_guard.py `identity_violations` :305-324 | CANDIDATE_ID / VERSION / ARTIFACT_DIGEST / SEAL_DIGEST / MISSING |
| frozen 绑定 artifact 字节 | src/forge/capabilityizer.py `frozen_artifact_violations` :421-439 | live digest vs frozen digest |
| probe 实测 | /tmp/o2_probe.py | 见 03 号报告 |

## O2 Decision

```text
O2 = REAL GAP

Minimal Invariant
  运行意图与它声明的四元组必须共享同一 trust root；A→B 的意图改写必须可检测或不可能。

Minimal Change Boundary
  Option A（推荐）：adoption_store 增加 anchored run-request 记录，
  复用现有 write_trust_anchor；phase_future 以它为唯一意图来源。
  Option B：anchor 增加 b3_entry digest 字段。

Required Regression Tests
  whole swap REJECT / 单字段 REJECT（保持）/ deletion REJECT /
  stale version REJECT（保持）/ sealed 后意图改写 INTEGRITY_STORE_CORRUPTED /
  合法 run ALLOW。
```

## O1

```text
O1 remains OPEN and is NOT addressed in this phase.
（verify_at_mount 返回与内核 bind mount 之间的 OS-level 竞态，
  本阶段未处理；Phase 9-B.3 的 R8 应用层单一路径约束保持有效。）
```

