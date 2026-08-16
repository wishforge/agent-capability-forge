# 17 — Failure Attribution Contract（Phase 5-K）

> 阶段：Phase 5-K。冻结 `FailureAttribution` 语义；实现为
> `deepseek-harness/evaluation/failure_attribution.py`（纯确定性、只读）。
> 输入：`ExecutionRecord`（5j.1）+ `EvaluationResult`（5-I）。
> 禁止：LLM RCA / 自动修复 / Improvement / Regression / Promotion /
> Runtime semantic change / Prompt 修改 / Evaluation rule redesign。

## 1. 定位

```text
ExecutionRecord
    ↓
EvaluationResult（deterministic findings）
    ↓
FailureAttribution（deterministic, read-only, traceable）
```

FailureAttribution 是 EvaluationResult 的**归因投影**：

- 不修改输入；
- 不调用模型、不读 ContextVar / runtime mutable state；
- 只消费 durable evidence（record 字段 + finding evidence_refs）；
- 同一 record + 同一 EvaluationResult ⇒ 同一 FailureAttribution（replay
  稳定）。

## 2. 最小字段

| 字段 | 语义 | 来源 |
| --- | --- | --- |
| `failure_id` | 确定性标识：execution_id + 候选 (kind, rule_id) 排序拼接 | 派生 |
| `execution_id` | 哪个 execution | record.execution_id |
| `turn_id` | 哪个 turn（无证据时 None） | record.turns[] |
| `step_id` | 哪个 step（无证据时 None） | finding evidence / record.steps / record.tools |
| `attempt_id` | 哪次 execution attempt（无证据时 None） | finding evidence / record.attempts / record.tools |
| `failure_kind` | 最小确定性集合；多个不可排序候选时 MULTIPLE_CANDIDATES；无失败时 None | 派生（见 §4/§7） |
| `evidence_refs[]` | 该 attribution 引用的全部 finding evidence | EvaluationResult.findings[].evidence_refs + 解析出的 ids |
| `initiator_ref` | 谁触发（durable ref；缺失为 None） | record.initiator_ref / tool/attempt initiator_ref |
| `owner_ref` | 谁拥有（durable ref；缺失为 None） | 失败 tool 的 owner_ref / record.owner_refs |
| `context_provenance_ref` | failure 发生时 context 的 provenance（不判断好坏） | record.context_provenance[0] |
| `backend_event_refs[]` | 原始 backend evidence 在哪里 | finding evidence / record.backend_refs / attempt / tool refs |
| `mapping_quality` | EXACT / LOSSY / BACKEND_SPECIFIC / UNKNOWN | record.lossiness 聚合 |
| `parent_ref` | attempt.parent_execution_id（causality durable ref） | record.attempts |
| `ownership` | ATTRIBUTED（有 owner_ref）/ INCONCLUSIVE（缺失） | 派生 |
| `primary_failure` | 唯一最深候选；多候选不可排序时为 None | 派生（见 §7） |
| `secondary_failures[]` | primary 之外的候选；MULTIPLE_CANDIDATES 时=全部候选 | 派生 |

每条 `Failure` 候选：

```text
failure_kind
rule_id（None = record 级派生，本阶段不产生）
turn_id / step_id / attempt_id
evidence_refs[]
```

## 3. 能回答的十问

1. 哪个 execution 失败 → `execution_id`
2. 哪个 turn → `turn_id`
3. 哪个 step → `step_id`
4. 哪次 execution attempt → `attempt_id`
5. 哪个 tool / model request → evidence_refs（tool_call_id / backend_event_ref）
   + backend_event_refs
6. 什么类型的失败 → `failure_kind`
7. 谁触发 → `initiator_ref`
8. 谁拥有 → `owner_ref` / `ownership`
9. context provenance → `context_provenance_ref`
10. backend evidence 在哪里 → `backend_event_refs[]` + `evidence_refs[]`

## 4. Failure Kind（最小确定性集合）

```text
TOOL_FAILURE
MODEL_FAILURE
TIMEOUT
UNRESOLVED_TOOL
UNSAFE_RETRY
TURN_FAILURE
STEP_FAILURE
EXECUTION_ABORTED
CONTEXT_FAILURE
COMPLETION_FAILURE
VERIFICATION_FAILURE
UNKNOWN
```

确定性映射（只从已冻结的 RULE + record 字段取，不解析自由文本）：

| 来源 | Kind |
| --- | --- |
| RULE-01，turn_end_reason=max-tokens | COMPLETION_FAILURE |
| RULE-01，其他非 completed reason | TURN_FAILURE |
| RULE-02 | UNRESOLVED_TOOL |
| RULE-03 | UNSAFE_RETRY |
| RULE-04 | COMPLETION_FAILURE |
| RULE-05 | UNKNOWN（最小集合无 policy kind；不猜） |
| RULE-06 | TOOL_FAILURE |
| RULE-07 | TIMEOUT |
| RULE-08 + attempt.status=ABORTED | EXECUTION_ABORTED |
| RULE-08 + attempt.error=CONTEXT_WINDOW_EXCEEDED | CONTEXT_FAILURE |
| RULE-08 + attempt.error=MODEL_ERROR | MODEL_FAILURE |
| RULE-08 + steps[].outcome FAILED/ABORTED | STEP_FAILURE |
| RULE-08 + turn_end_reason=error（无更深证据） | TURN_FAILURE |
| RULE-08 其余 | UNKNOWN |
| RULE-09 | COMPLETION_FAILURE |
| 其他 RULE / 无匹配 | UNKNOWN |

证据不足时返回 UNKNOWN / INCONCLUSIVE，不猜。VERIFICATION_FAILURE 当前
无证据来源（16 §2），保留在集合内但本阶段不会由确定性映射产生。

## 5. Attribution Hierarchy

```text
Execution
  ↓
Attempt
  ↓
Step
  ↓
Tool / Model Event
  ↓
Failure Evidence
```

确定性深度（仅用于 primary 选择，不是根因声明）：

```text
tool/model event   = 1
step               = 2
attempt            = 3
turn               = 4
execution / completion / unknown = 5
```

规则：

- tool failure 不自动升级为 step failure；
- step failure 不自动升级为 turn failure；
- 只有 record 中已有 step / turn / execution outcome 证据时才产生对应
  候选；
- RULE-06 已产生 TOOL_FAILURE 时，不再从 record 附加 step/turn 候选
  （避免自动升级）。

## 6. Root Failure Candidate

```text
primary_failure       # 唯一最深候选（最小深度值）
secondary_failures[]  # 其余候选
```

- primary_failure 必须有 deterministic evidence（来自 FAIL finding 或
  record 的 outcome 证据）；
- 多个候选深度相同且无法排序 → `failure_kind = MULTIPLE_CANDIDATES`，
  `primary_failure = None`，全部候选进入 secondary_failures；
- 不输出“根因”文字结论，不猜。

## 7. Causality

FailureAttribution 只读取：

```text
initiator_ref
parent_ref（attempt.parent_execution_id）
backend_event_ref
evidence_refs
```

禁止读取 ContextVar / runtime mutable state。ambient initiator 未持久化时
`initiator_ref=None`，不重建。

## 8. Ownership

```text
owner_ref != initiator_ref
owner_ref != authorized principal
```

- owner_ref 来自失败 tool 的持久化 owner_ref，否则 record.owner_refs；
- owner_ref 缺失时 `ownership=INCONCLUSIVE`，不推断；
- 本阶段不持久化 authorized principal（保持 5-H OPEN）。

## 9. Context

`context_provenance_ref` 只回答：

```text
failure 发生在 context provenance X 下
```

不判断“context 好不好”，不把 provenance quality=PARTIAL 当 EXACT。

## 10. Evidence Graph

```text
Failure
 ├── execution_id
 ├── attempt_id
 ├── step_id
 ├── turn_id
 ├── tool/model event（evidence_refs.tool_call_id / backend_event_ref）
 ├── initiator_ref
 ├── owner_ref
 ├── context_provenance_ref
 └── backend_event_refs[]
```

所有节点通过 refs 连接；不复制整份历史，不复制 backend raw event。

## 11. 确定性 / Replay

```text
same record + same EvaluationResult ⇒ same FailureAttribution
```

- 所有字段从 immutable 输入派生；
- replay 后 record 语义相等 ⇒ attribution 相等；
- mapping_quality 随 lossiness 保留（LOSSY 不因归因层变 EXACT）。

## 12. Cross Backend

- AgentScope / Codex 走同一 `attribute(record, result)`；
- 相同 Evaluation failure ⇒ 相同 FailureAttribution shape；
- backend 差异只允许出现在 backend_event_refs / mapping_quality /
  lossiness（LOSSY / BACKEND_SPECIFIC），不允许出现在 kind / ids /
  refs 结构。

## 13. 验收

| # | 标准 | 结果（实现后） |
| --- | --- | --- |
| 1 | 只读、纯确定性、无 LLM | 见 19-report |
| 2 | 十问全部有字段回答 | 见 19-report |
| 3 | 最小 kind 集合不扩展 | 见 19-report |
| 4 | 层级不自动升级 | 见 19-report |
| 5 | MULTIPLE_CANDIDATES 可表达 | 见 19-report |
| 6 | initiator / owner / context / backend refs 可追溯 | 见 19-report |
| 7 | replay 稳定 | 见 19-report |
| 8 | AgentScope / Codex 同 shape | 见 19-report |
