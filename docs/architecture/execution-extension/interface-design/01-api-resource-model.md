# 01 — API Resource Model

## Resource shape

| Logical resource | Exposure | Identity | Owner |
|---|---|---|---|
| Run | top-level resource；Attempt/Recovery/Artifact 为关联或 subresource | `run_id`，稳定跨 retry/resume | Managed Runtime |
| Attempt | Run 的 collection/subresource；可单独读取 | `attempt_id`，恰属一个 Run | Managed Runtime |
| Binding | top-level 或 Runtime-internal resource | `binding_id` | Managed Runtime |
| BindingEpoch | Binding 的 immutable child/reference；不单独开放 mutation | `epoch_id` | Managed Runtime |
| Artifact | top-level reference resource，或 Run/Attempt 关联 subresource | `artifact_id` | Managed Runtime |
| Recovery | Run/Attempt 的 append-only subresource | `recovery_id` | Runtime durable journal；Supervisor 提交事实 |

Execution Extension handle 不是 API resource identity，只作为 Attempt 的 ephemeral observation/reference。

## Logical operations

操作先定义为 domain command，不直接等同 HTTP method：

| Command | 语义 |
|---|---|
| create Run | 创建 `OPEN` Run；不启动 execution |
| start Run | admission、选定 immutable epoch，并创建首个 `PENDING` Attempt；重复调用返回同一 operation result |
| retry Run | 仅在旧 Attempt terminal，或 UNKNOWN 已按 policy 解析/隔离后，创建新的 Attempt；永远不重用旧 Attempt identity |
| resume Run | 用 session/history/checkpoint 作为输入创建新的 Attempt；可继承 provenance，不能继承旧 Attempt identity；transport reconnect 若语义未变则仍是同一 Attempt 内部操作 |
| cancel Run | 写入取消 intent，终止相关 live primitives；只有终止归因完成后 Run/Attempt 才为 `CANCELLED` |
| verify Attempt | 对 UNKNOWN 或 artifact/side-effect fact 发起 observation/probe；不创建 Attempt、不直接改写 terminal state |
| reconcile Run | 让 Supervisor 读取 durable state 并追加 decision；可安排 verify、compensation、新 epoch/new Attempt 或 terminate |

Read 返回 durable semantic state 与必要的 latest observations。Update 仅允许修改由 Runtime owning policy 声明的 desired fields；状态转移必须走 command。Recovery 与 audit history append-only，不能用普通 update 覆盖。

## Idempotency contract

`create Run`、`start`、`retry`、`resume`、`cancel`、`verify`、`reconcile` 都是 command，必须支持 caller-supplied `idempotency_key`。key 的去重范围为 `(tenant, logical resource, command kind)`；同一 key 必须绑定 canonical request fingerprint，fingerprint 不同则拒绝冲突。

服务端产生 `operation_id`，保存 request identity、结果引用与状态（accepted/running/succeeded/failed）。客户端重试同一 request identity 返回原 operation/result；未知响应时先查询 operation，不猜测是否已执行。

`retry` 的 dedupe 结果是已创建的 `attempt_id`；`resume` 的 dedupe 结果是已创建的新 `attempt_id`；`cancel`/`verify`/`reconcile` 的重复请求不能重复执行副作用，只能复用或追加同一 operation 的观察。

## Identity separation

```text
run_id != attempt_id != binding_id != epoch_id != execution_handle
```

Run identity stable；Attempt identity stable；一个 Attempt 恰好引用一个 immutable BindingEpoch；Extension handle 可丢失、重建或 stale。
