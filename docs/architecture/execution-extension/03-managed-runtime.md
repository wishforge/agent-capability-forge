# 03 — Managed Runtime

Managed Runtime 将 Extension 的局部执行事实组织成可恢复的 durable execution。

## Runtime guarantees

Runtime 必须拥有并保证：

- durable identity：Run、Attempt、Binding、Artifact/Provenance 可被稳定关联
- deterministic ownership：每项 durable 事实有唯一语义 owner
- attempt continuity：明确 retry、resume、fork、crash 后的 lineage 与新旧 Attempt 关系
- binding continuity：明确 Binding identity、epoch、迁移和 stale detection
- artifact provenance：记录 creator → execution → Attempt 的来源链
- capability compatibility：在启动和恢复时作出并记录兼容性决定
- recovery semantics：区分 result、side-effect fact 与 UNKNOWN
- isolation policy：选择所需隔离级别并要求可验证的执行约束

## Runtime does not become the executor

Runtime 可以发出 execution intent、接收事件、记录事实并作出策略决定，但不吸收 process、session、transport 或 tool 的实现。那些仍由 Extension/底层 provider 承担。

## Semantic authority

当 Extension 事实与 durable state 不一致时，Runtime 不应静默覆盖：它创建可审计的冲突/UNKNOWN 事实，并交给 Supervisor 按 recovery policy 处理。

