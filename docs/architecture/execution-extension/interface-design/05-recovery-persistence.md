# 05 — Recovery Persistence

## Durable recovery knowledge

以下 facts 必须 durable，且按 append-only history 保存：

- `UNKNOWN` 的原因、execution boundary、last-known fact 与对应 Attempt/epoch。
- receipt：operation identity、来源、原始内容引用、trust/verification 状态与 freshness。
- verification request/result：probe/audit source、查询时间、世界状态事实、结论与证据。
- compensation request/result：授权、undo operation、执行观察、验证结果与 policy outcome。
- reconciliation decision：decision id、policy version、fence、选择（new Attempt / verify / compensate / human gate / terminate）及其依据。

`SUCCESS`/`FAILURE` 只在所需事实达到 Runtime policy 后写入；receipt 不等于 result，`UNKNOWN` 不得被 crash cleanup 或 controller restart 默认改写为 `FAILURE`。

## Restart reconstruction

```text
process crash / runtime restart / controller restart / node restart / provider restart
        ↓
read Run + Attempt + Epoch + Recovery history
        ↓
rebuild semantic state; mark missing live handle stale
        ↓
Supervisor reconcile, verify before unsafe retry
```

Extension state 可以消失；Runtime semantic state 必须可重建。若 live handle 消失但副作用无法归因，旧 Attempt 保留 `UNKNOWN → RESOLVING`。若有可信 receipt/verification，可导出 terminal outcome；否则只能进入 safe retry、compensation、human gate 或 terminate。

Recovery history 不因新 Attempt 创建而删除；新 Attempt 通过 lineage/reference 连接旧 Attempt。重启时不得仅凭“进程已重新启动”宣称 Run/Attempt 已恢复。

## Retention boundary

语义上必须保留影响 outcome、trust、compensation、audit 的 evidence；纯 transport/event noise 可按 retention policy 丢弃，但丢弃造成的 evidence gap 必须转为 durable observation gap/UNKNOWN。receipt retention、probe freshness、verification timeout 与 compensation budget 是 open parameters。
