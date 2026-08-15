# 22 — Phase 4-C Python 最小实现要求（Context Projection + Compaction）

> 前置：21-context-compaction-contract.md（契约冻结，本文件只提取 Python 下一阶段需求）
> 本阶段禁止：实现生产 Compaction、实现 TokenMeter、接真实 LLM / AgentScope / SQLite / UI、修改 Phase 4-A runtime 与 Phase 4-B persistence/recovery。
> 本文件产物是 REQUIREMENTS + DESIGN PROPOSAL + UNKNOWN 清单，不是实现。

---

## 1. 对象映射与状态

| Python 对象 | 角色 | DSH 对应 | 状态 |
| --- | --- | --- | --- |
| `EventStore` | append-only 事件权威 | `Session.log` + persistence 插件 | REQUIRED（Phase 4-B 已有；需要 schema 扩展，见 §2） |
| `SessionEvent` + `surface_op` / `source_event_seqs` | 事件可携带投影意图与血缘 | `types.ts SurfaceIntent` | REQUIRED（Phase 4-B 只有 `source_event_seqs`，无 `surface_op`） |
| `SurfaceProjection.derive_messages()` | log → 当前 surface → model messages | `Session.deriveMessages`（`core/session/src/index.ts:726-749`） | REQUIRED（Phase 4-A 已有；需支持 replace 后才是 compacted projection） |
| `CompactionEngine`（抽象接口） | 定义 `compactIfNeeded(trigger)` / `compactNow()` / `compactRegion()` | `CompactionEngine`（`compaction/src/index.ts:70-134`） | REQUIRED（接口契约）；实现 = DESIGN PROPOSAL（本阶段不做） |
| `CompactionPlan` | 区间选择结果：start/end/shadowedSeqs + retain 尾部 | `selectCompactableRange` 的返回值（`compaction-basic/src/region.ts:98-148`） | DESIGN PROPOSAL（DSH 无独立对象，只有函数；Python 需要时再定 shape） |
| `ReplacementEvent` | `compaction/start` / `compaction/summary` / 替换 `user/message` / `compaction/end` / `compaction/prune` | `compaction/src/types.ts:26-109` | REQUIRED（schema）；summary 生成逻辑 = DESIGN PROPOSAL |
| `TokenMeter` | pressure + surface token estimate | `ctx.tokenMeter.measure()` | REQUIRED（接口契约）；固定 4 字符/token 估算 = DESIGN PROPOSAL；provider 精确对齐 = UNKNOWN |
| `ContextBuilder` | 组装单次 model request（system/tools/messages/runtime-context/input） | DSH 无独立对象；组合在 `agent-loop/buildRequest`（`agent.ts:407-467`） | DESIGN PROPOSAL（若 Python 实现 agent loop 需要；不得当作 DSH 既有事实） |
| `RetryDecision` | `{kind:'retry'}` 或保留原错误 | `agent/request-error` action（`index.ts:179-228`；`agent.ts:356-367`） | REQUIRED（契约）；接线 = DESIGN PROPOSAL |
| `ToolResultPruner` | 独立可选、model-free 剪枝服务 | `ToolResultPruner`（`compaction-tool-result-pruner/src/index.ts:136-166`） | DESIGN PROPOSAL（独立于 full compaction） |
| 失败分类 | `busy / cancelled / changed / summary / commit / persistence` | `ManualCompactionError`（`compaction/src/index.ts:28-49`） | REQUIRED（词汇冻结） |
| Runtime State / Capability | 资源生命周期，不落 SessionEvent，不进 model context | Phase 2 Capability Runtime；17 §2/§7 | REQUIRED（保持分离）；事件 schema = UNKNOWN/OPEN |

---

## 2. 实现 Compaction 前必须补齐的 Event Schema（REQUIRED）

1. message-producing 事件（`user/message`、`assistant/message`、`tool/result`）增加 `surface_op`：`'append' | {op:'replace', start, end}`；非 surface 事件禁止携带。
2. replace 校验：
   - start/end 必须存在于当前 surface；
   - `source_event_seqs` 必须包含全部被替换节点；
   - `tool/result` 替换只允许改 content，其余字段深比较不变（DSH `surface.ts:259-290`）。
3. 新增 log-only 事件：`compaction/start`（compaction_id、turn）、`compaction/summary`（summary、shadowed_range、shadowed_seqs、shadowed_token_count、provider/model）、`compaction/end`（error 可选）、`compaction/prune`（shadow price）。
4. 替换 summary 是 `user/message`，带 `source: {kind:'plugin', plugin:'compact', compaction_id}` 标记。
5. `EventStore` JSONL 编解码必须持久化 `surface_op`；schema 演进/迁移策略保持 Phase 4-B 现状（无版本号）→ 标 UNKNOWN，不得伪装。

---

## 3. 行为要求（REQUIRED 契约）

- `derive_messages()` 只投影当前 surface；replace 后旧节点不再出现，但 log 不删除。
- Pressure trigger 在 buildRequest 之前（DSH `agent/pre-step` 等价点）；无 routed request header 时不触发。
- `CONTEXT_WINDOW_EXCEEDED` 失败时：prune → compact → `replace_generation` 前进且未取消 → retry；否则保留原错误。
- retry 用新 `derive_messages()` 重建请求，同 turn/step，不重跑工具；受 `max_overflow_retries` 限制。
- summary 必须 text-only、必须比 shadowed 区间小（heuristic estimate），否则算 `summary` 失败。
- 压缩失败必须显式表示（事件 error 或分类异常），禁止吞成成功；pressure 失败允许继续 turn。
- token meter 只用于决策，不得声明为 provider 精确计费。
- Capability state 不写入 model context；工具执行输出只经 `tool/result` 进入 surface。

---

## 4. 下一阶段验收条件（contract-level）

1. same log + same projection rules ⇒ same messages（本实现确定性）。
2. 仅凭持久化事件可重建 compacted surface（start/summary/replace/end 足够）。
3. prune replay 后 `derive_messages()` 等于压缩后 surface；原始 tool/result 仍可从 lineage 恢复。
4. 任意 compaction/prune 前后 log 事件数只增不减。
5. CTX-01..08 全部成立。
6. 失败分类六类可被测试区分。
7. retry 只在 overflow 且 surface 有 durable progress 时发生。

---

## 5. 非目标（本阶段不进入）

- 生产 CompactionEngine / TokenMeter / ToolResultPruner 实现；
- 真实 LLM、AgentScope、SQLite、UI；
- Capability 事件 schema 决策（保持 OPEN QUESTION）；
- summary 信息质量评估（NOT FOUND，不设计）；
- 跨 backend 原子性、fsync 承诺。

---

## 6. 结论

**PARTIAL** —— Python 最小对象边界已冻结：EventStore / Surface / ReplacementEvent / CompactionEngine 接口 / RetryDecision / 失败分类为 REQUIRED；CompactionPlan / TokenMeter 估算 / ContextBuilder / ToolResultPruner 为 DESIGN PROPOSAL；provider 精确计费、Python compacted replay、schema 迁移为 UNKNOWN。实现 Compaction 前先补 §2 的 schema 与 §3 的行为契约。
