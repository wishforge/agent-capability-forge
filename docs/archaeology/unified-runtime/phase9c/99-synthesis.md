# Phase 9-C Synthesis — End-to-End Agent Candidate Trust Boundary Audit

- 日期：2026-08-18
- 基线：`a70a433`
- 验证：`pytest -q` → `859 passed, 11 skipped, 19 subtests passed`；phase9b1+b3+b5
  定向 `81 passed, 6 subtests passed`；本轮 /tmp probes（probe1-4）
- 范围：只审计，未修改 production code / tests / schema，未 commit

## 1. 最终 Trust Graph（单 authority）

```text
Candidate（Mutable -> Verified after freeze）
    ↓ Identity + Digest
Evaluation（Derived/Verified）
    ↓ Digest + Provenance
Promotion（Derived/Verified）
    ↓ Digest + Provenance
Authority（Immutable + Trusted, anchored）
    ↓ Digest
Trust Root（Trusted, deployment contract）
    ↓ Digest
Run Intent（Trusted, anchored store["run_request"]）
    ↓ Identity + Digest + Reference
Registry（Locator/Mutable, re-verified）
    ↓ Reference
b3_entry（Cache/Locator/Mutable, compared）
    ↓ Reference
Adoption（Verified）
    ↓ Digest
Artifact Verification（Verified）
    ↓ Digest
Mount Verification（Verified）
    ↓ Reference
Runtime（唯一 Execution Decision）
```

## 2. Source of Truth Owners

| Owner | 内容 |
|---|---|
| Candidate Identity | Frozen Candidate + Authority（seal_digest 锚定） |
| Run Intent | adoption_store["run_request"] |
| Artifact Integrity | Frozen Candidate record + live digest 重算 |
| Runtime Execution Decision | harness.phase_future("b3") canonical 分支 |

无 competing owners；Registry / b3_entry / artifact_dir / frozen 全部是 locator /
verification，不能选择候选。

## 3. 十问十答

### Q1 Evaluation 批准 A 后，是否还能 Promotion B？

Canonical：**不能**（`EVALUATION_BINDING_MISMATCH`，issue/promote 同一 helper；
capabilityizer.py:405-419；adoption_authority_producer.py:98-180；registry.py:69-252）。
Legacy：可以（probe 实测），属历史兼容边界，非 canonical。

### Q2 Promotion A 后，是否还能 Authority B？

**不能**。authority 在 issue 时与 decision/run 绑定；promote 必须携带同一
authority，entry.adoption 与 authority 全等（BINDING_KEYS）；篡改 entry →
adopt 重验 REJECT。

### Q3 Authority A 后，是否还能 Run Intent B？

**不能**。run_request 由 mark_promoted 从 entry+authority 生成并写入锚定 store；
改写 run_request 而不刷新 anchor → `INTEGRITY_STORE_CORRUPTED`（phase9b5 test_d）。

### Q4 Run Intent A 后，是否还能通过 Registry / b3_entry 运行 B？

**不能**。b3_entry → `RUN_REQUEST_CACHE_MISMATCH`；registry 同名换 B →
`CANDIDATE_ID_MISMATCH`（probe3）；异名不被 discover（name 来自 run_request）。

### Q5 Run Intent A + artifact B，能否运行 B？

**不能**。frozen_artifact_violations 重算 live digest；B 字节 → `ARTIFACT_DIGEST_MISMATCH`。

### Q6 Run Intent A + mount source B，能否运行 B？

**不能（应用层）**。mount_source != verified_artifact_dir → `RUNTIME_BINDING_MISMATCH`；
verify 后目录内容被替换 = O1（OS 级），本阶段不修复。

### Q7 完整合法的 B 状态替换 A 后，系统是否仍能运行 B？

若替换不含 anchored run_request/anchor：**不能**（probe3：B 全部字段合法仍 REJECT）。
若同时改写 run_request + anchor：**能**，但该写者就是 trust root owner，属
same-writer/信任根边界（probe4），不是新的 application gap。

### Q8 是否存在任何 mutable state 仍拥有“选择 Candidate”的权限？

Canonical：**否**。Legacy：b3_entry + Registry 仍选择（历史兼容边界，Phase 9-B.2
O4 处置）。

### Q9 O1 是否仍然是唯一真实的 Runtime execution-level security gap？

**是**。应用层无新的 Approved A → Executed B 旁路；剩余为 O1（verify→bind-mount
OS 竞态）+ 既有部署边界（anchor 写保护 / issuer 密码学化）。

### Q10 是否需要 Phase 9-D，或者可以进入 O1？

Canonical trust closure 已成立，**不需要为“再找一个 gap”而开 Phase 9-D**。下一步
应进入 O1 Closure Design（digest 命名不可变快照 / 只读挂载 / open-by-handle），
并把 legacy 最终处置（O4）作为独立非阻断项。

## 4. Gap Classification

| 发现 | 分类 |
|---|---|
| whole b3_entry swap（9-B.4 O2） | CLOSED（9-B.5 anchored run_request） |
| single-field tampering | CLOSED（9-B.3 R1） |
| canonical → legacy downgrade | CLOSED（9-B.1.1） |
| registry/b3_entry/artifact/frozen 完整合法 B 替换（run_request=A） | CLOSED（probe1-3） |
| verify → bind mount | OS-LEVEL GAP（O1, OPEN） |
| store + anchor 可写时整体替换 | TRUST-ROOT / SAME-WRITER BOUNDARY（非应用 gap） |
| legacy evaluation→promotion 不绑定 | LEGACY COMPATIBILITY BOUNDARY（O4） |
| 当前 pilot/state 无 adoption_store | MIGRATION GAP（NON-BLOCKING） |
| issuer 无密码学签名 | NON-SECURITY DESIGN DEBT（GAP-3，已知） |
| anchor 默认 sibling 非物理写保护 | DEPLOYMENT CONTRACT（UNKNOWN，已知） |

## 5. Final Verdict

```text
PHASE_9C_VERDICT = PASS_WITH_FINDINGS

APPROVED_A_TO_EXECUTED_B = CLOSED
TRUST_CHAIN = CLOSED
CANDIDATE_SELECTION = SINGLE_AUTHORITY
RUN_INTENT = CLOSED
ARTIFACT_BINDING = CLOSED
RUNTIME_BINDING = CLOSED（应用层）/ O1_OPEN（OS 层）
O1 = OPEN
MIGRATION = NON-BLOCKING（legacy state 处置单独可选）
NEW_SECURITY_GAPS = NONE
```

## 6. 本阶段边界

- 未修改 production code、未新增 production tests、未改 schema、未 commit。
- probe 脚本在 `/tmp`，不进入仓库。
- 完整测试基线：`859 passed, 11 skipped, 19 subtests passed`。
