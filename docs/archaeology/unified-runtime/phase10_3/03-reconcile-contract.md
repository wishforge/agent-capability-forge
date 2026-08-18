# 03 — Reconcile Contract（Stage 1）

- 阶段：Phase 10.3 Stage 1
- 基线：`main == origin/main == 661d866`

## Diff → Action（Stage 1 实现范围）

| Desired | Observed（最新 active instance） | Action | Verdict |
|---|---|---|---|
| RUNNING | 无 / STOPPED | START（新 instance） | HEALTHY（成功后） |
| RUNNING | RUNNING（同 version） | NO-OP | HEALTHY |
| RUNNING | RUNNING（不同 version） | NO-OP（不自动升级） | VERSION_DRIFT / RECONCILE_REQUIRED |
| RUNNING | STARTING / STOPPING | NO-OP | RECONCILE_REQUIRED（in transition） |
| RUNNING | FAILED | START retry（attempt<3）；超限 NO-OP | RECONCILE_REQUIRED / ESCALATE |
| RUNNING | 任意 | REJECT（version revoked / snapshot mismatch） | REJECT |
| STOPPED | RUNNING / STARTING / READY | STOP | HEALTHY（成功后） |
| STOPPED | STOPPING | NO-OP | RECONCILE_REQUIRED |
| STOPPED | STOPPED / FAILED / 无 | NO-OP | HEALTHY |
| REVOKED | RUNNING / STARTING / READY | STOP → REVOKED | REVOKED |
| REVOKED | STOPPED | REVOKED（终态事件） | REVOKED |
| REVOKED | 无 / REVOKED | NO-OP | REVOKED |

Stage 1 **不实现**自动 UPGRADE：`Desired v17 + Observed v16 RUNNING` 只报告
`VERSION_DRIFT`，不执行 STOP→START v17（10.3 §1 明确 Upgrade 是下一阶段）。

## Idempotency

- `reconcile(RUNNING) × N`：第一个 reconcile 产生 1 个 instance；后续
  `RUNNING + RUNNING → NO-OP`，不产生第二个 instance（Test C）。
- `reconcile(STOPPED) × N`：第一个执行 stop；后续 `STOPPED → NO-OP`，
  不重复 stop（Test B 断言 stop 调用次数 = 1）。
- `set_desired_state(同值)`：NO-OP，不追加事件。

## Revoke（最小实现，Test F）

```text
revoke_version(version_id)
    ↓
adoption_authority.revoke_authority()（authority events.jsonl append-only）
    ↓
versions.jsonl 追加 state=REVOKED（终态）
    ↓
deployments.jsonl 追加 desired_state=REVOKED
    ↓
reconcile：RUNNING → STOPPING → STOPPED → REVOKED；无实例 → NO-OP
```

启动链路双保险：

1. `create_version()` 检查 authority events，已 REVOKED/SUPERSEDED 直接拒绝；
2. `reconcile()` start 前再次检查 authority events + version state，任一 REVOKED
   → 不创建/不启动新 instance（REJECT）。

