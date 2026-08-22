# 02 — Attempt State Machine

## Meaning

**DESIGN DECISION**：Attempt 是 Run 下的一次实际 execution boundary，由 Runtime 归因。transport retry 可留在 Attempt 内；新的 managed retry、resume、fork 或 binding migration 不留在旧 Attempt 内。

## States

```text
PENDING -> STARTING -> RUNNING <-> WAITING
   |          |          |  \       |
 CANCELLED  FAILED     UNKNOWN  SUCCEEDED
                \         |
                 \        +--> RESOLVING --+--> SUCCEEDED
                                           +--> FAILED
                                           +--> CANCELLED
                                           +--> new Attempt / terminal old Attempt
```

- `PENDING`：已创建并等待 admission、capability、binding、isolation 与 dispatch 条件。
- `STARTING`：dispatch 已获准，Extension 正建立 process/session/tool boundary；尚未证明可执行。
- `RUNNING`：执行边界已观察到并可归因于该 Attempt。
- `WAITING`：执行仍由 Runtime 负责，但等待外部事件、tool completion、provider response、scheduler/admission 或人工 gate；不是隐含成功。
- `SUCCEEDED`：Attempt 的执行结果及其要求的 side-effect/artifact facts 已足够可信。
- `FAILED`：Attempt 已确定不能完成其 execution boundary，且不是证据不足；仍不自动推导无副作用。
- `UNKNOWN`：边界失联、结果丢失或事实冲突，无法安全判断 outcome/side effect。
- `RESOLVING`：Supervisor 正对 UNKNOWN 做 observation/verification/compensation；它不是新的执行 Attempt。
- `CANCELLED`：Runtime 接受取消并完成该 Attempt 的终止归因。

`RESOLVING` 是 durable recovery state，避免把 UNKNOWN 直接改写为 FAILED。

## Creation and transitions

1. Runtime 创建 Attempt 为 `PENDING`，绑定一个 immutable Binding Epoch。
2. admission 条件满足后进入 `STARTING`；Extension 报告可归因的 live execution 后进入 `RUNNING`。
3. 等待可观察外部条件进入 `WAITING`，条件满足回到 `RUNNING`。
4. 明确成功进入 `SUCCEEDED`；明确不可继续且证据充分进入 `FAILED`；接受取消进入 `CANCELLED`。
5. process crash、session disconnect、event loss、timeout 或 stale handle 只有在无法证明边界与副作用时进入 `UNKNOWN`，不能自动等同 `FAILED`。
6. `UNKNOWN -> RESOLVING`；验证后可进入 terminal，或旧 Attempt terminal 后由 Supervisor 安排新 Attempt。

## Crash continuation, retry

**DESIGN DECISION**：crash 后默认不继续同一 Attempt。若 Runtime 能证明原 execution boundary、binding epoch、operation identity 与 side-effect facts 仍连续，才可把失联视为 live observation gap 并恢复到 `RUNNING/WAITING`；否则旧 Attempt 保持 `UNKNOWN` 并终止归因，后续为新 Attempt。

Retry 不是 UNKNOWN 的快捷键。未解决 UNKNOWN 时禁止假设 effect 未发生；只有 verification、deduplication、明确 idempotency 或人工 policy 允许时才能新建 Attempt。

## Invariants

- **I1（DESIGN）**：每个 Attempt 恰好属于一个 Run。
- **I2（DESIGN）**：Attempt identity 永不改变。
- **I3（DESIGN）**：terminal Attempt 不回到 active execution。
- **I4（DESIGN）**：每个 Attempt 恰好执行于一个 immutable Binding Epoch。
- **I5（DESIGN）**：新 Attempt 不能覆盖旧 Attempt 的结果、UNKNOWN 或 receipt 历史。

**OPEN PARAMETER**：lease/heartbeat/timeout 数值与人工 gate 细节不在本阶段决定。

