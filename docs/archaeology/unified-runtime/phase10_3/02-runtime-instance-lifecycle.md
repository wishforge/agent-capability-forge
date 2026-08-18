# 02 — RuntimeInstance Lifecycle（含 10.1 Open Question 2 收口）

- 阶段：Phase 10.3 Stage 1
- 基线：`main == origin/main == 661d866`

## 对象与事件

`instances.jsonl` 每条事件携带完整 instance 视图；当前 observed state =
该 instance_id 最新事件。事件序列（Stage 1 只实现粗体状态）：

```text
instance_created    READY
    ↓
instance_starting   STARTING
    ↓
instance_running    RUNNING
    ↓
instance_stopping   STOPPING
    ↓
instance_stopped    STOPPED

STARTING / RUNNING / STOPPING → instance_failed → FAILED（带 failure_reason）
FAILED → instance_starting（bounded retry，attempt_count+1）
READY / STOPPED / RUNNING → instance_revoked → REVOKED（终态，不可再 start）
```

合同要求的 `DEPLOYING / PENDING / UNKNOWN` 本阶段只保留枚举（contract），
不实现状态机分支（10.3 §5：“其余先作为 contract”）。

## Q2 — Retry 最小契约

现有代码没有 retry model：`src/forge/sandbox.py:15-46` 对一次 `docker run`
只允许一个 timeout，超时即 kill 并返回失败；harness 不重试。

本阶段定义（`pilot/managed_runtime.py` 常量）：

```text
START_MAX_ATTEMPTS       = 3    # 同一 instance 最多尝试 start 3 次
START_RETRY_BACKOFF_S    = 0    # 无 scheduler；backoff 契约保留，值为 0
terminal failure         = attempt_count >= 3 时保持 FAILED，
                           reconcile 返回 RECONCILE_REQUIRED / ESCALATE
```

重试触发：`Desired=RUNNING` + `Observed=FAILED` + `attempt_count < 3`
→ 下一次 `reconcile()` 在**同一 instance** 上追加 `instance_starting` 并重新 start。
不建立 scheduler，不自动 sleep，不自动定时重试。

## RuntimeInstance 创建顺序（10.3 §8）

```text
1. Load Deployment
2. Resolve AgentVersion
3. Verify Version runnable（未 revoke、snapshot binding 一致）
4. Resolve Execution Snapshot（frozen/<candidate_id>/artifact）
5. Verify Snapshot identity/digest/seal（guard.verify_at_mount，启动前即时执行）
6. Start runtime
7. Observe result
8. Persist RuntimeInstance 事件
```

instance_id 在启动前生成：`READY → STARTING → start → RUNNING / FAILED`。
`RUNNING` 只在实际 runtime 启动确认成功之后写入（Docker adapter 用
`docker inspect` 确认 `State.Running == true`）。

