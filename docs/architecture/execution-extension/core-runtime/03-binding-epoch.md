# 03 — Binding Epoch

## Definitions

- **Binding**：Managed Runtime 对 agent、provider、session、capability set 及其 compatibility decision 的逻辑绑定身份。
- **Binding Epoch**：Binding 在一组执行语义不变条件下的不可变版本边界。
- **Attempt**：引用一个且仅一个 Binding Epoch 的 execution boundary。

**ARCHAEOLOGY EVIDENCE**：OSS 展示了 provider/model/package 的 mutation 或 reconstruction，但没有 durable Binding/epoch contract。

**DESIGN DECISION**：影响执行语义的 provider、agent、session identity、capability、credential 或 isolation 变化必须产生新 epoch；active Attempt 内不得静默 mutation。

```text
Binding B
  ├── Epoch 1  <- Attempt 1
  ├── Epoch 2  <- Attempt 2
  └── Epoch 3  <- Attempt 3
```

## Epoch rules

- Epoch 在 Attempt admission 前创建并冻结；Attempt 只读它。
- transport retry、同一 operation 的 reconnect、无语义变化的 event replay 继承 epoch。
- managed retry 默认新 Attempt；可继承同一 Binding identity，但必须重新确认兼容性。是否复用 epoch 取决于 runtime policy，不能改变旧 Attempt 的引用。
- resume 创建新 Attempt；默认继承输入/history provenance，但只有在 binding compatibility 仍成立时才可引用相同 epoch。
- fork 创建新 Run/Attempt；可复制 binding intent，不复制 epoch identity。
- provider/model/package/capability/credential/isolation 迁移产生新 epoch，并默认产生新 Attempt。

## Migration and stale detection

迁移顺序是：冻结旧 epoch 的新 admission → 建立并验证新 epoch → 旧 active Attempt 进入 `UNKNOWN` 或 terminal → Supervisor 安排新 Attempt。不得先 mutation 再补记录。

active Attempt 能否观察不同 epoch？**NO（DESIGN DECISION）**。否则同一 Attempt 的 artifact provenance、capability decision、side-effect attribution 与 replay 语义会随时间改变，无法判定事实属于哪个 execution boundary。跨 epoch 必须用新 Attempt 作为可审计边界。

**OPEN PARAMETER**：epoch 编号格式、迁移原子性实现、stale detection 的具体证据（配置版本、attestation 或 capability snapshot）留给 implementation design。

