# Pilot/B3 — Option B Architecture Reconnect

- 状态：Architecture Reconnect（只重接架构，不写 `src`、不实现 B3）
- 日期：2026-08-14
- 关联文档：
  - `docs/capability-forge-mvp-spec.md`（v0.3，P0 Contract 与 Runtime Boundary 所在，本文不修改）
  - `research/artifact-contract/verified-task-artifact-bundle-v0.md`（P0 FROZEN，本文不修改）
  - `research/experiments/capability-forge-vs-skill.md`（v0.2，实验设计冻结，本文不修改）
  - `research/experiments/experiment-readiness.md`（Pilot readiness；实现就绪度不受本文影响）

---

# 1. Purpose

把已冻结的 Option B 架构明确重新接回实验计划：

- **24-run Pilot**：3 families × 4 arms × 2 校准 formation tasks
- **B0 / B1 / B2 / B3** 四臂
- **B3 Experimental Slice**：仅实现实验所需最小闭环

主路径（Option B）：

```text
Agent Runtime
    ↓
Runtime Adapter
    ↓
VerifiedTaskArtifactBundle
    ↓
Forge Core
```

本文只做架构重接：不写代码、不实现 B3、不修改 `docs/*`、`src/*`、P0 Contract、`capability-forge-vs-skill.md`、Runtime Boundary Architecture Decision。

---

# 2. Option B Reconnected Architecture

Option B 命名与当前实验命名的映射：

| Option B（冻结） | Pilot/B3 文档 |
|---|---|
| Agent Runtime | Codex Runtime |
| Runtime Adapter | Codex Runtime Adapter |
| VerifiedTaskArtifactBundle | VerifiedTaskArtifactBundle（不变，P0 FROZEN） |
| Forge Core | Runtime-neutral Forge Experimental Slice |

```text
                           Experiment Harness
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                   B0            B1            B2/B3
                    │             │             │
                    │             │             ▼
                    │             │      Codex Runtime
                    │             │             │
                    │             │             ▼
                    │             │     Codex Runtime Adapter
                    │             │             │
                    │             │             ▼
                    │             │ VerifiedTaskArtifactBundle
                    │             │             │
                    │             │             ▼
                    │             └────► Forge Experimental Slice
                    │                         │
                    │                         ▼
                    │                  Candidate / Validation /
                    │                  Evaluation / Promotion
                    │
                    └──────────────────────► Results
```

更准确的主路径：

```text
Codex Runtime
    ↓
Codex Runtime Adapter
    ↓
VerifiedTaskArtifactBundle
    ↓
Runtime-neutral Forge Experimental Slice
```

职责映射：

- **Codex Runtime Adapter** = spec 中 Artifact Builder 的 runtime-specific 职责：rollout 解析、runtime-only capture、final phase authority、verification event capture、workspace snapshot capture、Bundle assembly/sealing。
- **Forge Experimental Slice** = spec 中 Capabilityizer → Candidate → Validator → Evaluator → Promotion 的 runtime-neutral 最小闭环，外加实验用 registry 与 invoke。

---

# 3. Pilot Data Flow

24-run Pilot = 3 families × 4 arms × 2 校准 formation tasks。

每臂数据流：

1. Experiment Harness 以同一 model/config、fresh sandbox、task fixture/oracle 启动 Codex，记录 run metadata 与 cost。
2. B2/B3 共享 `Codex Runtime → Codex Runtime Adapter → VerifiedTaskArtifactBundle` 生产层。
3. B3 在 Bundle 之后进入 Forge Experimental Slice；B2 从同一 generation input 生成 skill。
4. B0/B1 不经过 Adapter/Bundle 管道；B1 由人类基于同一 train 任务产出 curated skill（见 §4）。
5. Harness 只消费 run metadata、VerifiedTaskArtifactBundle、arm-specific result，不解析 Codex native runtime format。

Pilot 目标对应：

- **目标 4（B2/B3 共享同一 generation input）**：由单一 Adapter → Bundle 生产层保证。
- **目标 5（Bundle 足够支撑 B3）**：由 Slice 只消费 Bundle 保证。

---

# 4. B0/B1/B2/B3 Boundaries

| 臂 | formation 输入 | formation 机制 | 复用机制 | 经过 Adapter/Bundle |
|---|---|---|---|---|
| B0 | 无 | 无 | 无；每个任务从零解决 | 否 |
| B1 | 同一 2 个校准 train 任务执行结果（Bundle/trajectory 可作人类参考材料） | 人类专家写 1 个 curated skill，freeze（计 human cost） | skill 目录发现/注入 | 否（skill 由人类形成） |
| B2 | 同一 train 任务 → Adapter → Bundle/trajectory | LLM 直接生成 1 个 skill 文档 + 示例；无确定性验证、无评估、无 promotion gate | skill 目录发现/注入 | 是（共享生产层） |
| B3 | 同一 train 任务 → Adapter → Bundle | 一次 Capabilityizer proposal → 1 个 Candidate → deterministic validation → minimal evaluation → promote/reject → experimental registry → invoke | experimental registry + 沙箱 invoke | 是（共享生产层） |

边界要点：

- B0/B1 是 sibling arms；B1 的 skill freeze/inject 是臂内机制，不是 Forge Slice 管道。
- B2/B3 的差异只发生在 Bundle 之后；Adapter → Bundle 是两者共享的输入生产层。
- Pilot 用每族 2 个校准 formation task（Pilot 文本）；main-study formation unit 保持冻结的 `3 train → 1 artifact`（`capability-forge-vs-skill.md` §6）。Pilot formation 规模裁决（`experiment-readiness.md` P1-8）不在本文解决。

---

# 5. B2 vs B3 Causal Boundary

B2 和 B3 使用相同的：

- formation tasks
- train inputs
- Bundle / trajectory inputs
- LLM model/config
- generation prompt/input

区别只发生在 Bundle 之后：

- **B2**：generated Skill → freeze → inject
- **B3**：same generation input → Candidate → validation → evaluation → promote/reject → experimental registry → invoke

**Codex Runtime Adapter 不是 B2/B3 的 treatment difference。** 它是两者共享的输入生产层。

因此 B2 vs B3 的因果对比 = governed/validated pipeline（deterministic validation / evaluation / promotion / registry / invoke）vs naive execution-derived self-generation，与 `capability-forge-vs-skill.md` H2 对齐。

---

# 6. Experiment Harness Boundary

Experiment Harness 可以：

- 启动 Codex
- 启动 B0/B1/B2/B3
- 创建 fresh sandbox
- 控制 model/config
- 记录 run
- 执行 oracle
- 收集 cost

Experiment Harness 不得解析 Codex native runtime format。

它只能消费：

- Run metadata
- VerifiedTaskArtifactBundle
- arm-specific result

结论：rollout 解析与 runtime-only 捕获必须被 Codex Runtime Adapter 封装；Harness 把 Codex 视为黑盒。

---

# 7. B3 Experimental Slice

B3 不是完整 Capability Forge。只实现实验所需最小闭环：

```text
Codex Runtime
→ Codex Runtime Adapter
→ Bundle
→ Capabilityizer
→ Deterministic Validation
→ Minimal Evaluation
→ Promote/Reject
→ Experimental Registry
→ Invoke
```

不实现：

- 第二 Runtime Adapter
- Generic RuntimeAdapter interface
- Production Registry
- Full P2/P3/P4/P5
- Dynamic Capability Plugin
- Revoke product
- Rollback
- Scope
- Marketplace

---

# 8. Non-Goals

- 不写代码、不实现 B3（本文是架构重接，不是实现计划）。
- 不修改 `docs/*`、`src/*`、P0 Contract、`capability-forge-vs-skill.md`、Runtime Boundary Architecture Decision。
- 不引入第二 Runtime Adapter 或 Generic RuntimeAdapter interface。
- 不实现 Production Registry、Full P2/P3/P4/P5、Dynamic Capability Plugin、Revoke product、Rollback、Scope、Marketplace。
- 不把 Adapter 归入 B3 treatment，也不把 Harness 归入 Forge Core。

---

# 9. Architecture Invariants

冻结：

1. Runtime-specific complexity stops at Adapter.
2. Bundle is the runtime/forge API boundary.
3. Forge Core is runtime-neutral.
4. Experiment Harness is not Forge Core.
5. Codex Adapter is shared infrastructure, not B3 treatment.
6. B2/B3 difference starts after Bundle generation.
7. P1 may implement Codex Adapter + Artifact Builder as same module, but logical boundary must remain visible.
8. Future second Runtime should require adding Adapter, not modifying Forge Core.

---

# 10. Future Second Runtime

第二个 Runtime 出现时：

- 新增该 Runtime 自己的 Adapter：负责该 runtime 的 rollout 解析、runtime-only capture、final phase authority、verification event capture、workspace snapshot capture、Bundle assembly/sealing。
- 产出同一份 VerifiedTaskArtifactBundle（P0 FROZEN 契约是 runtime/forge 的唯一 API boundary）。
- Forge Core / Forge Experimental Slice 不改：仍只消费 Bundle。
- Experiment Harness 不改：仍只消费 run metadata、Bundle、arm-specific result。

即 Invariant 8 的可执行含义：**添加 Adapter，不修改 Forge Core。**

---

**Option B Reconnected = PASS**

架构重接成立（与 P0 Contract、Runtime Boundary、实验设计一致）；实现就绪度不变——B3 最小 pipeline 仍是 `experiment-readiness.md` 的 implementation blocker。
