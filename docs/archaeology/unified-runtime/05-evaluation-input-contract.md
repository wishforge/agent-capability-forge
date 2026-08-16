# 05 — Evaluation Input Contract（Phase 5-G）

> 阶段：Phase 5-G。冻结 EvaluationInput 语义；不实现 Evaluation Engine /
> Judge / Scoring；不修改 Runtime semantics。
> 输入证据：04-execution-record-contract.md、Phase 5-E Contract v1、
> Phase 5-F 01-03、Codex 07-10/27、DSH 07/08/10/11/17。

---

## 1. 定义

```text
EvaluationInput =
    ExecutionRecord        # Runtime 生成（04）
  + Task Specification     # Evaluation / Task Definition 提供
  + Expected Outcome       # Oracle reference；存在时由 Task Definition 提供
```

边界：

- Runtime 只负责产生 ExecutionRecord；
- **Expected Outcome 不由 Runtime 生成**，也不由 Runtime 推断；它属于
  Evaluation / Task Definition 域；
- Task Specification（任务描述、约束、验收上下文）不属于 Execution Record；
  缺失时 EvaluationInput 只含 ExecutionRecord，评价能力相应受限。

---

## 2. Evaluation 与 Verification 区分

```text
Verification = execution-time gate / correctness signal
Evaluation   = post-execution quality judgment
```

冻结：

1. Runtime 不能把“任务结束”自动解释成“任务成功”；
2. `turn/end{completed}` / attempt SUCCEEDED 只是执行终止证据，不是质量
   结论（Codex 07：completion = end_turn + 无后续工作；DSH 07：
   structured_output 校验 = 协议一致性，非正确性）；
3. EvaluationInput 保留 ExecutionRecord 的 UNKNOWN 语义，由 Evaluation
   决定如何解释，不由 Runtime 预先评分。

---

## 3. Evaluation 只读边界

Evaluation 可以：

- 读取 ExecutionRecord；
- 读取 raw event reference（经 `event_refs` / `backend_refs` 回源）；
- 读取 backend metadata；
- 读取 lossiness；
- 读取 tool outputs；
- 读取 context provenance；
- 请求 Replay（只读重建）。

Evaluation 不能：

- 修改 EventStore / Session / Step；
- 修改 Capability / Tool ownership / Causality / attempt identity；
- 修改 ExecutionRecord（immutable）；
- 读取 ambient runtime ContextVar；
- 把 LOSSY 字段当作 EXACT 参与比较而不带质量标记。

---

## 4. Failure Attribution 边界

Evaluation 应能读取：

```text
failure events
attempts
tool errors
backend metadata
lossiness
causality
context provenance
```

但：

```text
Root Cause Analysis 不是 Runtime Core；Runtime 只提供证据。
```

- Runtime 不生成“根因结论”；
- Evaluation（或上层归因系统）从证据派生归因；
- ExecutionRecord 中证据不足的归因字段必须标 PARTIAL / UNKNOWN，禁止
  Runtime 或 Adapter 静默补全（Phase 5-E §15；CORE-08）。

---

## 5. Cross-Backend 消费

同一个 EvaluationInput 形状分别消费：

```text
AgentScope ExecutionRecord
Codex ExecutionRecord
```

必须比较：

1. 字段语义是否一致（04 §13 表）；
2. 哪些字段 LOSSY（Codex 六项 / AgentScope 三项）；
3. 哪些 backend-specific（ownership、initiator、approval/sandbox 机制）；
4. 哪些 evaluation 逻辑可跨 backend 复用（仅语义层：attempt 树、tool
   lineage、outcome 派生、lossiness 消费）。

Evaluation 逻辑不得假设 backend 特定字段在另一 backend 存在；缺字段时按
该字段的契约状态（EXACT / ADAPTER / LOSSY / BACKEND_SPECIFIC / PARTIAL /
UNKNOWN）降级，不报假精度。

---

## 6. 验收（05 部分）

| # | 标准 | 结果 |
| --- | --- | --- |
| 1 | Expected Outcome 与 Runtime 解耦 | PASS（Oracle 属 Task Definition） |
| 2 | Verification / Evaluation 语义分离 | PASS（结束 ≠ 成功） |
| 3 | Evaluation READ ONLY | PASS（边界冻结） |
| 4 | Failure Attribution 只读证据 | PASS（RCA 非 Runtime Core） |
| 5 | AgentScope/Codex 同一输入形状 | PASS（语义层复用 + 显式降级） |
| 6 | 不实现 evaluator / judge / scoring | PASS（本文件只定义契约） |
