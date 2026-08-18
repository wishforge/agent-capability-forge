# 05 — Failure Semantics（Stage 1）

- 阶段：Phase 10.3 Stage 1
- 基线：`main == origin/main == 661d866`

## 状态与动作

| Failure | Observed | Desired | Reconcile Action（Stage 1） |
|---|---|---|---|
| Snapshot missing / digest mismatch / owner isolation | FAILED | RUNNING | BLOCK START（guard 拒绝，fail-closed） |
| Version revoked | REVOKED / 无 instance | REVOKED | new start REJECT；existing → STOP → REVOKED |
| Runtime start failure | FAILED（failure_reason） | RUNNING | bounded retry（attempt<3）；超限 ESCALATE |
| Runtime stop failure | FAILED（failure_reason） | STOPPED | 保持 FAILED，manual reconcile |
| Runtime crash（外部进程消失） | FAILED | RUNNING | 同 start failure（bounded retry） |
| Version drift | RUNNING（v16） | RUNNING（v17） | VERSION_DRIFT，不自动升级 |
| Deployment / Version missing | 无 instance | RUNNING | VERSION_NOT_FOUND / DEPLOYMENT_NOT_FOUND，不自动创建 |

所有 guard 拒绝保持 fail-closed：Observed 进入 FAILED（或拒绝创建 instance），
Desired 不变，reconcile 不得绕过 guard 强行启动。

## Test G 覆盖

`FakeRuntime.start` 返回 FAILED → reconcile 后 instance 最新事件为
`instance_failed`，`observed_state=FAILED`，`failure_reason` 有值；
再次 reconcile（runtime 恢复成功）→ 同一 instance 追加 STARTING（attempt=2）
→ RUNNING。第 3 次失败后 attempt_count=3 → reconcile 返回
`RECONCILE_REQUIRED / ESCALATE`，不再调用 runtime.start。

## run_record 边界

RuntimeInstance 失败/停止不写 run_record；run_record 只在真实执行产生
执行证据时追加，并通过 instance 上的可选 `run_id` 反向关联
（见 `01-state-source-analysis.md` Q4）。
