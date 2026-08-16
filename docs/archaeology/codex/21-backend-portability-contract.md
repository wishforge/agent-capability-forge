# 21 — Backend Portability Contract（Codex as Second Agent Backend，Phase 5-A）

> 对象：Unified Semantic Runtime（`docs/archaeology/deepseek-harness/13-17/21`）+ Phase 4 实现（`docs/archaeology/deepseek-harness/runtime/`）+ Codex baseline `279b93242cfef379e65da97e87e44b83c5934fd7`。
> 本文件只定义契约，不实现 Adapter，不修改任何 runtime / contract / business source。
> 状态词：VERIFIED / PARTIAL / UNKNOWN / INFERENCE / DESIGN PROPOSAL。

---

## 1. Purpose

固定“Semantic Runtime Core 保持 backend-neutral”的可验证边界，并给出 Codex Adapter 必须满足的最小能力契约。任何后续 Phase 5-B 实现必须在此契约内进行；本文件本身不批准实现。

---

## 2. Backend Independence Audit（现状）

审计范围：`docs/archaeology/deepseek-harness/runtime/` 全部 `.py` + `docs/archaeology/python-cordis/kernel/` semantic core / capability / manager。

### 2.1 结果

| 检查项 | 结果 | Status |
| --- | --- | --- |
| Semantic core 文件是否直接 import agentscope / codex | `events.py`、`event_store.py`、`surface.py`、`compaction.py`、`tool_runtime.py`、`runtime.py`、`turn_step.py`、`initiator.py`、`recovery.py`：直接字符串 **0 命中** | VERIFIED（直接层） |
| `runtime.py` 是否传递依赖 AgentScope | **是**：`runtime.py` 直接 `from model_adapter import ...`，而 `model_adapter.py` 顶层 import agentscope；因此 AgentRuntime 当前编译/运行依赖具体 AgentScope adapter | PARTIAL（seam 级潜在 PORTABILITY LEAK） |
| 是否存在 `if codex:` / `if agentscope:` 分支 | 无 | VERIFIED |
| AgentScope 引用位置 | `model_adapter.py`（adapter 层）与 `runtime/tests/*`；经 runtime.py 传递进入 core 依赖图 | PARTIAL |
| Codex 引用位置 | runtime 目录内无；Codex 只在本文档与 `src/forge/codex_adapter`（独立、且与 pinned main 冲突，见 20 §13.2） | VERIFIED |
| Semantic Layer（`kernel/semantic_layer/`、`kernel/capability.py`、`kernel/manager.py`） | 无 agentscope import；AgentScope 只在 `kernel/adapters/agentscope.py` | VERIFIED |

结论：

- **语义对象层无 PORTABILITY LEAK**：无 backend import、无 backend 分支。
- **运行时装配层有一个 seam 级 PARTIAL 风险**：`runtime.py` 直接 import 具体 `model_adapter`（AgentScope-specific），不是抽象 adapter interface。未来加入 Codex Adapter 时，若继续沿用该模式，`runtime.py` 需要第二个 backend import 或分支——这正是契约要禁止的形态。**本阶段不修复**，仅在契约中要求抽象 adapter seam（见 BP-01 / §4.10）。
- `model_adapter.py` 本身是合法 adapter 实现；Codex Adapter 应以同层 sibling 加入，禁止把 backend import 上移到 core 对象。

---

## 3. Portability Contracts

### BP-01 — Semantic core does not depend on Codex or AgentScope.

Status: **PARTIAL**

证据：§2 审计；`kernel/adapters/agentscope.py:1-11` 明确 adapter 只走 public API。PARTIAL 原因：`runtime.py` 直接 import AgentScope-specific `model_adapter`，当前依赖图传递包含 agentscope；语义对象本身无 backend 依赖，但运行时装配 seam 尚未抽象。

契约：`docs/archaeology/deepseek-harness/runtime/` 的 core 对象文件（events/event_store/surface/compaction/tool_runtime/turn_step/initiator/recovery）禁止出现 `codex` / `agentscope` import 与 backend 分支；`runtime.py` 必须改为依赖 adapter interface（或显式 adapter registry），具体 backend 实现只允许存在于 adapter 文件。新增 Codex 能力时只允许新增 adapter 文件、接口与测试，不得在 core 增加 backend import。

### BP-02 — Adapters may translate backend-native execution into unified semantic events.

Status: **VERIFIED**（seam 存在）/ DESIGN PROPOSAL（Codex 翻译未实现）

证据：`model_adapter.py` 已证明 “semantic core → adapter → backend public API” 的翻译 seam；20 §2/§4 给出 Codex → Unified 的翻译点。

契约：Codex Adapter 负责把 rollout JSONL / 运行时事件翻译为 Unified `SessionEvent`；翻译规则属于 adapter，不改变 core。

### BP-03 — Backend-specific metadata may be preserved without changing unified semantics.

Status: **DESIGN PROPOSAL**

契约：每个 Unified event 可携带 `raw_event_ref`（rollout 路径 + 行号 + `RolloutItem` 类型）与 backend metadata；`raw_event_ref` 不是统一语义的一部分。当前 EventStore schema 无该字段，实现前需要扩展（不得在 Phase 5-A 做）。

### BP-04 — Ownership is runtime-owned semantics.

Status: **VERIFIED**（契约层）；Codex 侧 BACKEND-SPECIFIC（20 §5）

证据：17 §5；python-cordis CAP-03；Codex owner = session-scoped services（`state/service.rs:46-70`）。

契约：Unified Capability/Scope/Effect 由 Runtime 管理；Codex Adapter 不得从 rollout 推导“谁拥有工具”，也不得把 Codex session 服务当成 Capability。

### BP-05 — Causality is explicitly modeled and is independent from ownership.

Status: **VERIFIED**（契约层 / Phase 4 `initiator.py`）；Codex 侧 **MISSING**（ambient initiator）

证据：17 §5；`initiator.py:1-48`；20 §6（Codex 无 current initiator；有 durable thread lineage）。

契约：`initiator` 与 `owner` 分离；Codex Adapter 只能使用 session/thread lineage 建立因果链，不发明 `initiator_id`；若无法归因，标 UNKNOWN。

### BP-06 — Backend lossiness must be observable.

Status: **DESIGN PROPOSAL**

契约：Adapter 必须输出一个可枚举的 lossiness 清单（至少包含：Step 边界为构造值、exec failure 无结构化 success、chunk lineage 缺失、crash unknown outcome 缺失、compaction retry 跨 Step）。当前 Runtime 无 lossiness 字段；实现 Codex Adapter 时随事件或元数据暴露，禁止静默吞掉。

### BP-07 — Replay semantics must not be falsely equated.

Status: **VERIFIED**（契约层）

证据：13 REPLAY-04（replay ≠ evaluation）；20 §8（Codex resume/fork/rollback 与 Unified replay 有差异：marker、copy/reference、无 seed 边界）。

契约：Codex Adapter 的 replay/resume/fork/rollback 输出必须带 backend-specific 语义标记；Unified 侧不得声称与 Codex resume 等价。

### BP-08 — Context differences must be explicit.

Status: **PARTIAL**（契约层）；Codex 差异 VERIFIED

证据：21 CTX-01..08；20 §7（Codex compaction 为 CompactedItem 新事实、retry 跨 Step、TokenMeter 不能表达全部 budget）。

契约：Adapter 翻译 compaction 时，必须区分“Unified replacement 事件语义”与“Codex CompactedItem 事实”；context budget 差异必须在文档/元数据中显式声明。

### BP-09 — Capability lifecycle semantics must remain backend-neutral.

Status: **VERIFIED**（契约层）

证据：python-cordis 12/13；20 §10（Codex 无 Capability，MISSING）。

契约：Capability/Scope/Effect 契约不因 Codex 而改变；Codex 工具可见性只作为 backend 快照翻译，不进入 capability lifecycle。

### BP-10 — Session/Turn/Step contract must not change merely to accommodate Codex.

Status: **DESIGN PROPOSAL**

契约：Unified Session/Turn/Step 定义（13/14）不变；Codex 的 Step 缺失由 Adapter 构造，Codex Task/run_turn 的差异由 backend metadata 表达（20 §2），禁止为了 Codex 给 Unified 增加 Task/run_turn 概念。

---

## 4. 最小 Codex Adapter 能力契约

以下为 Phase 5-B 实现前必须满足的接口能力（本阶段不实现）：

1. **读取**：读 Rollout JSONL（`RolloutItem`），识别 SessionMeta / ResponseItem / EventMsg / Compacted / WorldState / TurnContext / InterAgentCommunication；对 `EventMsg::RawResponseItem` 去重（20 §3）。
2. **构造 Session/Turn/Step**：Session = thread；Turn = `TurnStarted`…`TurnComplete/TurnAborted/Error` 分段；Step = 一次 sampling request（Adapter 构造，含 model stream + tool activity），并标记 `step_id` 为构造值。
3. **翻译 Tool Call/Result**：call_id 配对；exec 失败按 lossiness 标记；timeout/cancel/approval-reject 映射为 tool-result 层失败；fatal 错误单独标记（可能终止 turn）。
4. **翻译事件**：`EventMsg::ExecCommandBegin/End`、`McpToolCallBegin/End`、approval/guardian 事件 → Unified trace/log-only 事件或 backend metadata。
5. **翻译 Compaction**：`CompactedItem` → Unified replacement 语义 + backend metadata（replacement_history/window ids）；保留 raw ref。
6. **翻译 Replay/Recovery**：resume = 历史重建；fork = copied/referenced 前缀；rollback = `ThreadRolledBack` marker + 重建；crash unknown outcome = MISSING 标记（不伪造）。
7. **翻译 lineage**：SessionMeta parent/forked lineage + InterAgentCommunication → Unified parent-session / initiator 可推导部分；无 ambient initiator 时标 UNKNOWN。
8. **保留 raw_event_ref**：每个 Unified event 携带 rollout 路径 + 行号 + 原生类型，保证可审计回源。
9. **暴露 lossiness**：BP-06 清单必须由 Adapter 输出，至少包含 20 §12 的五项。
10. **禁止**：修改 Codex / AgentScope / Semantic Core / Capability / 既有 contracts；禁止在 core 对象中出现 backend import 或分支；`runtime.py` 不得直接 import Codex adapter（必须先抽象 adapter interface，见 BP-01）。

---

## 5. Verification

本阶段不新增测试。契约验收条件（未来实现时）：

1. `rg -n "agentscope|codex" docs/archaeology/deepseek-harness/runtime/{events,event_store,surface,compaction,tool_runtime,turn_step,initiator,recovery}.py` 保持 0 命中；`runtime.py` 只引用 adapter interface（不含 backend 包名）。
2. 任一 Codex rollout 可翻译为 Unified SessionEvent 序列，且每个事件可回源（raw_event_ref）。
3. Step 边界构造规则可复现：同一 rollout + 同一规则 ⇒ 同一 Step 序列。
4. lossiness 清单可被消费方枚举；未映射语义不得写成 VERIFIED。
5. BP-01..BP-10 全部可验证，UNKNOWN/DESIGN PROPOSAL 项不被伪装成 VERIFIED。

---

## 6. Final Verdict

**PARTIAL**

Portability Contract 本身已冻结：BP-01 为 PARTIAL（runtime.py 传递依赖 AgentScope adapter）；BP-02/04/05/07/09 有当前实现或契约证据（VERIFIED）；BP-03/06/08/10 是必须由 Codex Adapter 显式承担的设计要求（DESIGN PROPOSAL）。Codex 侧存在 Step 构造、exec failure、crash unknown outcome、Capability/Initiator、EventLog schema 五类不可消除的差异，因此整体为 PARTIAL，不是 PASS。
