# 03 — Binding Runtime Contract

`ARCHAEOLOGY EVIDENCE`：已有材料显示 provider/model/package 会 mutation 或 reconstruction，但没有 durable epoch contract；以下 freeze/migration/ownership 是 `DESIGN DECISION`。

`Binding` 是逻辑绑定身份；`BindingEpoch` 是执行语义不变的一次冻结快照。两者均由 Managed Runtime 拥有。

## Responsibilities

- Runtime 创建 Binding，评估 compatibility，并在 admission 前创建/冻结 BindingEpoch。
- Epoch identity 一旦建立不可变；Attempt 创建时必须引用且只能引用一个 epoch。
- Extension 只能执行 epoch 中授权的 provider/agent/session/capability/isolation intent，并报告实际观察。

## Change rules

| Event | Runtime effect |
|---|---|
| same semantic binding, transport retry/reconnect/event replay | 保留 epoch 与 Attempt identity |
| provider/agent/session identity、capability、credential 或 isolation 语义变化 | 新 BindingEpoch；旧 active Attempt 不静默 mutation，通常新 Attempt |
| managed retry | 新 Attempt；可复用 Binding identity，是否复用 epoch 需重新 compatibility check |
| resume | 新 Attempt；可继承 input/history provenance；仅在 compatibility 仍成立时引用同一 epoch |
| fork | 新 Run + 新 Attempt；可复制 binding intent，不复制 epoch identity |
| stale detection | 冻结旧 epoch admission，记录 stale，Supervisor 终止/归因旧 Attempt 并建立新 epoch/new Attempt |

迁移顺序必须是：freeze old admission → create/verify new epoch → attribute old Attempt → schedule new Attempt。任何跨 epoch 执行都必须以新 Attempt 作为审计边界。

## Open parameters

`epoch_id`/numbering format、migration atomicity mechanism、stale evidence（配置版本、attestation 或 capability snapshot）、同一 Binding 下 epoch reuse policy 均开放；它们不得改变 Attempt→exactly-one immutable epoch。
