# 04 — Idempotency and Concurrency

## Command idempotency

| Command | Required key | Deduplicated effect |
|---|---|---|
| create Run | yes | one Run identity |
| start Run | yes | one admitted first Attempt |
| retry Run | yes | one new Attempt for that operation |
| resume Run | yes | one new Attempt for that operation |
| cancel Run | yes | one cancellation intent/termination operation |
| verify Attempt | yes | one verification operation and its observations |
| reconcile Run | yes or deterministic controller operation id | one decision per observed version/fence |

同一 resource、command kind、tenant 范围内，key 必须绑定 request fingerprint；重复请求返回既有 operation。不同 key 不保证业务动作安全，仍受 semantic guards 和 recovery policy 限制。

## Optimistic concurrency and fencing

每个 mutable resource 暴露 `generation`（desired changes）与 `resource_version`/semantic version（observed durable changes）。写入必须携带读取版本；版本不匹配返回 conflict，调用者重新读取后再作决定。

每次 reconciliation/side-effect operation 产生单调 `operation_id` 与 fencing token。Supervisor、Attempt writer、controller 的写入必须带当前 token；旧 token 只能追加 stale observation，不能改变 state。BindingEpoch 以 immutable identity/version 作为执行 fence；旧 epoch 不得 admission。

## Race handling

- **Duplicate create/retry/resume**：operation journal 先 dedupe，再创建 identity；唯一业务结果可被重试读取。
- **Concurrent reconciliation**：以 Run semantic version + per-Run reconcile fence 竞争；输者重新读取，不重复执行 primitive。
- **Stale Supervisor**：fence 校验失败，记录 stale decision，禁止 terminate/retry/compensate 旧事实。
- **Stale Attempt writer**：transition version 或 epoch fence 失败；不得覆盖 UNKNOWN、terminal 或新 Attempt history。
- **Cancel vs retry**：由 Runtime transition guard 排序；已接受 cancel 后不得由旧 retry operation 重新 admission。

不把数据库锁、HTTP retry 或 controller queue 本身当作语义保证；实现可选择锁/队列，但必须满足上述 version/fence contract。
