# 05 — Recovery Semantics

## Vocabulary

```text
execution state   = Extension/Runtime 对执行边界的观察
side-effect state = 外部 world state 是否实际提交
SUCCESS           = 结果与所需事实足够可信
FAILURE           = 明确不能完成，不等于无副作用
UNKNOWN           = 事实不足，不能判定 SUCCESS 或 FAILURE
VERIFIED          = 通过 observation/probe 得到的 world-state fact
COMPENSATED       = 已执行并验证 recovery compensation
```

## UNKNOWN contract

典型情况是 request 已发送、tool 可能已执行、response 丢失。`UNKNOWN != FAILURE`，也 `UNKNOWN != SUCCESS`。Runtime 必须保留 UNKNOWN 原因与边界，Supervisor 先验证，再决定新 Attempt、compensation、人工 gate 或终止。

## Receipt

Receipt 是由 Extension/tool/provider 生成的、与 operation identity 关联的 durable observation 或提交证明。它可以证明“某个系统报告了某事实”，但只有在其 trust/verification policy 满足时，才可证明 side effect definitely happened。receipt 丢失不等于 effect 未发生；需 probe、外部查询、审计源或人工决策。

## Idempotency and effect classes

- **idempotent**：重复操作的最终语义安全。
- **deduplicatable**：可按 operation id/key 抑制重复提交。
- **verifiable**：可查询 world state 以判断提交事实。
- **compensatable**：存在有意义且可验证的反向动作。
- **non-compensatable**：不能可靠撤销；可能仍可 verify 或人工处理。

这些属性可同时成立，也可全部不成立；并非所有 side effect 天然幂等。operation id/idempotency key 是 policy/tool contract，不是 Runtime 自动推导的保证。

## Verification and compensation

```text
UNKNOWN
  -> observe / verify world state
  -> VERIFIED fact
  -> derive SUCCESS / FAILURE / safe retry / human gate
```

Compensation 是 recovery mechanism，不是 failure detection。只有明确 compensation contract、权限与验证方式时才可执行；不能用“执行了 undo hook”伪造恢复成功。`COMPENSATED` 只表示 compensation 本身完成且达到 policy 目标，不表示原 side effect 从未发生。

**DESIGN DECISION**：blind retry 在 unresolved UNKNOWN 上默认禁止。Runtime 决定 admission 与 durable outcome；Supervisor 编排 verification/compensation；Extension 只提供可用 primitive、receipt、probe 或 undo hook。

**OPEN PARAMETER**：各 tool class 的 receipt schema、operation journal、probe freshness、人工 gate 与 compensation budget 留给 implementation design。

