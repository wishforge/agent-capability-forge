# Phase 9-C.06 — Adversarial: Approved A → Executed B

基线：`a70a433`。攻击模型：Evaluation=PASS → Promotion=A → Authority=A →
Run Intent=A，然后逐点篡改为 B，全部走 canonical path。

## 1. 攻击矩阵

| 篡改点 | 构造 | Expected | Observed / Error | Final Runtime Candidate |
|---|---|---|---|---|
| Registry → B | entry 换成 B（同名/异名） | REJECT | `CANDIDATE_ID_MISMATCH`（同 store 完整 B）或 `UNISSUED_AUTHORITY`（跨 store）；cache 存在时先行 `RUN_REQUEST_CACHE_MISMATCH` | 无执行 |
| b3_entry → B | whole swap（name+四元组） | REJECT | `RUN_REQUEST_CACHE_MISMATCH` | 无执行 |
| artifact_dir → B | entry.artifact_dir 指向 B artifact | REJECT | `ARTIFACT_DIGEST_MISMATCH`（digest 重算） | 无执行 |
| runtime path → B | docker 前替换路径/内容 | REJECT（应用层）/ O1 | verify_at_mount 后替换 = O1 窗口；替换后内容不同 → digest mismatch | 无执行（应用层）；O1 OPEN |
| candidate name → B | b3_entry.name 或 run_request.name 改 B | REJECT | b3_entry：`RUN_REQUEST_CACHE_MISMATCH`；run_request：sealed → `INTEGRITY_STORE_CORRUPTED` | 无执行 |
| candidate version → B | 单字段 vA→vB | REJECT | `CANDIDATE_VERSION_MISMATCH` | 无执行 |
| artifact digest → B | 单字段 | REJECT | `ARTIFACT_DIGEST_MISMATCH` | 无执行 |
| seal digest → B | 单字段 | REJECT | `SEAL_DIGEST_MISMATCH` | 无执行 |

## 2. 完整合法替换（最高价值 probe）

同 store 内把 B 构造为完全合法状态（B authority/decision/frozen/artifact 全部存在、
lifecycle PROMOTED、registry 同名 entry 换成 B、b3 cache 删除、store 未 seal 允许
攻击者改写 lifecycle），但 run_request 保持 A：

```text
Probe3（本轮实测）：
  registry=B（valid, same store）
  lifecycle[B]=PROMOTED
  b3_entry missing
  run_request=A
  -> REJECT：CANDIDATE_ID_MISMATCH + ARTIFACT_DIGEST_MISMATCH + SEAL_DIGEST_MISMATCH
  -> docker calls = 0
```

结论：即使“B 状态全部字段合法”，只要 anchored Run Intent 仍是 A，任何 mutable
state（registry / b3_entry / artifact / frozen / 未 seal 的 store 副作用字段）都
不能把执行对象变成 B。

## 3. 边界条件（非 application gap）

```text
Probe4（本轮实测）：
  run_request 本身被改写成 B（store 未 seal 或攻击者同时写 anchor）
  registry=B，b3_entry missing
  -> ALLOW B（docker calls = 1）
```

这属于 trust-root / same-writer 边界：能改写 adoption_store 并刷新（或绕过）
anchor 的攻击者就是信任根写者，等价于能重新批准 B。Phase 8.4.3/9-B.2 GAP-2/3 已
显式声明；不是新的 application-level “Approved A → Executed B” 旁路。

## 4. 结论

```text
APPROVED_A_TO_EXECUTED_B = CLOSED
（残余：O1 OS-level verify→bind-mount；Trust Root 写者边界）
```
