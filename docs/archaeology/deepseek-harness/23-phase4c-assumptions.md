# 23 — Phase 4-C Implementation Assumptions

> 阶段：Phase 4-C（Context Projection + Compaction 最小实现）
> 引用：21 Context Compaction Contract / 22 Context Compaction Requirements /
> 19 Phase 4-B Assumptions
> 状态词：DSH VERIFIED / DSH PARTIAL / DSH UNKNOWN / PHASE-4C DESIGN

以下每一项都是 Phase 4-C implementation contract，不是 DSH facts。
PASS 只代表 Phase 4-C 最小 scope 完成；不声明 provider tokenizer 精确计费、
生产 LLM summarizer、跨进程并发、多事件原子性、完整 agent-loop retry 接线。

## 必需 Assumptions（A1–A8）

| # | Assumption | 状态 | 说明 |
| --- | --- | --- | --- |
| A1 | deterministic test summarizer：`deterministic_summarizer()` 是 PHASE-4C TEST SUMMARIZER，text-only、确定性、无 LLM；engine 强制 summary heuristic tokens < shadowed tokens，否则按 `summary` 失败。 | DSH summarizer VERIFIED（LLM + size check）；PHASE-4C DESIGN | 不伪装成生产 summarizer。 |
| A2 | token estimator：固定 `ceil(chars/4)+4`（message/system/tools）+ total；threshold/retain 由 context_window 派生；只用于 pressure 决策，不是 provider 精确 token usage。 | DSH 固定启发式 VERIFIED；provider 精确对齐 DSH UNKNOWN（CTX-06）；PHASE-4C DESIGN | `TokenMeter` 明确标注 PHASE-4C ESTIMATION。 |
| A3 | summary schema：替换事件是 `user/message`，payload 含 `content=summary` 与 `source={kind:plugin, plugin:compact, compaction_id}`；`surface_op={op:replace,start,end}`；`source_event_seqs=(start.seq, summary.seq, *shadowed)`；配套 `compaction/start|summary|end` log-only 事件。 | DSH checkpoint/summary/replace/end schema VERIFIED；Python 字段名 PHASE-4C DESIGN | `CompactionPlan` 是 runtime planning object，不写入 log。 |
| A4 | replacement generation：`replace_generation` 是 engine 单调计数；只经事件 payload 持久化，restart 后从事件重新得到同一 generation，不依赖内存状态。 | DSH replaceGeneration VERIFIED；Python 表示 PHASE-4C DESIGN | 生成号用于 retry 决策与 lineage。 |
| A5 | compaction concurrency：单进程 per-session busy registry；第二个并发 compact 返回 `busy`（CompactionError），不等待、无分布式锁；unmatched `compaction/start` 同样阻止后续 compaction。 | DSH compaction lock VERIFIED；分布式并发 DSH UNKNOWN；PHASE-4C DESIGN | `ponytail:` 单进程 busy 集合；多进程/多线程需要真实 lock/lease。 |
| A6 | atomicity boundary：无多事件事务；顺序 append。summary 失败发生在任何 append 之前（log 不变）；commit 失败留下 `compaction/start + compaction/summary + compaction/end{error}`，绝无 replacement → surface 不进入半提交状态；persistence 失败在四事件全部提交后仍抛 `persistence`（surface 已一致）；最坏情况 unmatched start 阻塞后续 compaction。 | DSH 跨事件原子性 DSH UNKNOWN（13 §12-5 / COMP-03）；PHASE-4C DESIGN | 不做 fsync/事务承诺。 |
| A7 | request overflow retry：`handle_request_error()` 是 decision-level 实现，未接入真实 agent loop；仅在 `CONTEXT_WINDOW_EXCEEDED`、`retry_safe()` 通过、replacement 已追加时返回 RETRY；`max_overflow_retries=1`；`overflow_retries` 不在 agent idle 时清零（无 agent loop）。 | DSH overflow retry 机制 VERIFIED；Python loop 接线 NOT IMPLEMENTED；PHASE-4C DESIGN | 不伪装成完整 agent-loop 行为。 |
| A8 | tool-result pruning representation：`prune_tool_result()` 独立于 full compaction；先 append `compaction/prune`（shadow price），再 append 替换 `tool/result`（`surface_op replace [seq,seq]`、`source_event_seqs=(seq,)`、仅 content 变化）；短结果 no-op。 | DSH ToolResultPruner VERIFIED；PHASE-4C DESIGN | 原 tool/result 永在 log。 |

## 附加实现记录（同样不是 DSH facts）

| # | Assumption | 状态 |
| --- | --- | --- |
| A9 | implicit append marker：`surface_op=None` 与 `'append'` 都表示追加；Phase 4-A/4-B 既有 message 事件保持 `None` 不变，只有 replacement 显式携带 `surface_op`。22 §2.1 的 “每个 surface 事件都写 append” 未采用，避免改写已冻结事件。 | PHASE-4C DESIGN |
| A10 | event order：事务顺序是 `compaction/start → compaction/summary → replacement user/message → compaction/end`（DSH VERIFIED），而非任务枚举的 start → replacement → summary → end；这样 replacement 的 lineage 可包含 summary seq。 | PHASE-4C DESIGN |
| A11 | balanced cut：assistant tool-call 与紧随其后的 tool/result 组成不可分割 unit；保留尾部 = 达到 retain_tokens 的最小 unit 后缀（`retain_tokens=0` 时保留最后一个 unit）；cut 永不拆开 call/result 对。 | DSH toolPairingBalancedBefore VERIFIED；Python 简化 PHASE-4C DESIGN |
| A12 | failure classification：`busy / cancelled / changed / summary / commit / persistence` 六类均可达；`changed` 通过 append 前 active range 复查；`persistence` 通过提交后 `store.flush()` 失败；manual flush 路径未实现。 | DSH 六类 VERIFIED；PHASE-4C DESIGN |
| A13 | model context builder：`build_model_context()` 是 request-time 组装（system/tools/runtime-context/derive_messages/current input），使用 deterministic test values；不是完整 DSH prompt system；capability state 永不进入。 | DSH buildRequest VERIFIED；PHASE-4C DESIGN |

## 结论

Phase 4-C PASS 只覆盖最小 scope：surface replace projection、token estimate、
pressure/overflow 双触发、replacement event、tool-result pruning、retry
safety、restart 后 compacted surface 重建、capability/model-context 分离、
失败保留 source history。A1–A13 覆盖的边界（provider tokenizer、生产
summarizer、分布式并发、多事件原子性、完整 retry 接线、schema 迁移）全部保留为
PHASE-4C IMPLEMENTATION ASSUMPTION，不进入下一阶段作为已证明事实。
