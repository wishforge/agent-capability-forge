# Agent Capability Forge

> 把成功的 Agent 执行转化为经过验证、可复用的能力——并衡量“能力形成”这条路径是否真的值得成本。

**项目状态：** 实验性 / 研究工程

- 运行时边界（Runtime Boundary）：已冻结
- VerifiedTaskArtifactBundle v0：已冻结
- Option B 运行时适配器边界：已实现
- F+ 预演（Rehearsal）：**PASS**
- 完整 Skill vs Capability Forge 试点：**尚未完成**
- Capability Forge 的业务价值：**尚未确立**

---

## 1. 这是什么？

Agent Capability Forge 是一个实验性框架，用于研究：一次成功的 Agent 执行，能否被转化为一个经过验证、可复用的能力，并且比单纯生成一个 Skill 创造更多长期价值。

本项目**并不假设** Capability Forge 一定优于 Skill。

它提出的核心问题是：

> 当一个 Agent 成功完成一项任务后，是应该忘记这次经验、把它变成 Skill，还是把它送进一条“能力形成与验证”流水线？

### 核心问题

如今，Agent 可以成功解决一项任务，但任务结束后，这次执行中有用的经验可能随之消失。

常见的替代做法是手动或自动生成一个 Skill：

```text
任务
  ↓
Agent 解决任务
  ↓
生成 Skill
  ↓
以后复用
```

Capability Forge 探索一条更受管控的路径：

```text
Agent 执行
      ↓
运行时适配器
      ↓
VerifiedTaskArtifactBundle
      ↓
能力形成
      ↓
验证 / 评估
      ↓
提升（Promotion）
      ↓
可复用能力
```

目标不是发明另一种 Skill 或 Plugin 格式。

目标是确定：由执行衍生的能力形成，能否创造可衡量的增量价值。

## 2. 为什么这很重要？

业务问题很简单：

> 为捕获、验证、评估和管理一个可复用能力而付出的额外努力，产出的价值是否大于其成本？

换句话说：

```text
价值 = 产出 - 投入
```

其中：

**产出**

- 更高的未来任务成功率
- 更少的重复工作
- 更低的 token / 运行时 / 人力成本
- 更少的回归和有害复用

**投入**

- 能力创建成本
- 验证与评估成本
- 运行时成本
- 维护成本
- 错误复用能力造成的成本

如果一个简单的 Skill 已经能提供相同的价值，Capability Forge 就不应该存在。

## 3. 核心研究问题

主实验比较四种方案：

| 实验组 | 方案 |
|--------|------|
| B0 | 仅 Agent |
| B1 | Agent + 精选 Skill |
| B2 | Agent + 生成 Skill |
| B3 | Agent + 执行衍生的 Capability Forge |

实验设计明确允许得出以下结论：

- Capability Forge 值得构建
- Skill 已经足够
- Capability Forge 应收缩为 Skill 生成 / 评估

## 4. 架构

项目采用 Option B 运行时适配器边界：

```text
Agent 运行时
      ↓
运行时适配器
      ↓
VerifiedTaskArtifactBundle
      ↓
运行时无关的 Forge 核心
```

当前 MVP 中，Codex 是第一个运行时：

```text
Codex 运行时
      ↓
Codex 运行时适配器
      ↓
VerifiedTaskArtifactBundle
      ↓
Capability Forge
```

最重要的架构规则是：

> 运行时特定逻辑止步于适配器边界。

Forge 核心不导入、不解析任何 Codex 特有的运行时类型。

这允许未来以同样的模式接入其他运行时：

```text
Codex      ──→ Codex 适配器  ──┐
SWE-agent  ──→ SWE 适配器    ──┤
Claude     ──→ Claude 适配器 ──┤
                              ↓
                VerifiedTaskArtifactBundle
                              ↓
                        Forge 核心
```

当前 MVP 刻意不引入通用的 RuntimeAdapter 接口，因为目前只有一种实现。

## 5. 当前实验流水线

当前 B3 实验切片为：

```text
Codex 运行时
    ↓
Codex 运行时适配器
    ↓
VerifiedTaskArtifactBundle
    ↓
Capabilityizer
    ↓
确定性验证
    ↓
评估
    ↓
提升 / 拒绝
    ↓
实验注册表
    ↓
调用
```

B2 和 B3 共享同一份执行衍生的输入：

```text
Agent 执行
      ↓
Codex 适配器
      ↓
VerifiedTaskArtifactBundle
      ↓
     ┌───────────────┐
     │               │
     ▼               ▼
    B2              B3
生成 Skill    能力形成
```

这对 B2 vs B3 的比较至关重要。

## 6. 已有证据

### F+ 预演：PASS

第一次 F+ 工程预演已成功完成。

它证明了以下流水线可以端到端运行：

```text
Codex 运行时
→ 运行时适配器
→ VerifiedTaskArtifactBundle
→ 生成 Skill / 能力候选
→ 验证 / 评估
→ 未来复用
```

预演还验证了 B2 和 B3 共享相同的生成输入。

**这证明了什么**

证明：

- 工程流水线是可执行的。

**这没有证明什么**

没有证明：

- Capability Forge 比 Skill 更有价值。

完整的业务价值实验尚未完成。

## 7. 实验设计

当前研究使用三个任务族：

**F+ — 对 Forge 友好**

复用度高，输入/输出契约稳定。

示例：

- 数据清洗
- 规范化
- 报告生成

**F− — 对 Forge 不友好**

复用度低、方差高，或包含任务私有状态。

示例：

- 仓库特有的迁移修复
- 一次性事故处理

**F0 — Skill 已经足够**

任务可以完全由指令描述，不需要一个实质性的可执行能力。

主研究规模：

```text
3 个任务族
×
21 个唯一任务
×
4 个实验组
=
84 次运行
```

在正式研究之前先运行一个小规模试点。

## 8. 决策逻辑

实验从三个维度分离评估：

- **经济性** — 净价值
- **可靠性** — 未来任务成功率
- **安全性** — 陷阱 / 回归 / 有害复用

只有在以下条件同时满足时，Capability Forge 才值得构建：

- 经济性占优
- 且
- 可靠性非劣
- 且
- 安全性非劣

高经济收益不能补偿显著的可靠性或安全性回退。

## 9. 本项目不是什么

本项目不是：

- 另一个 Skill 市场
- 另一个 Plugin 框架
- Agent 运行时的替代品
- “Capability 优于 Skill”的主张
- 生产级 Agent 控制平面
- 一个已完成的自主自进化系统

Skill 和 Plugin 被视为可能的能力交付机制，而不是研究目标本身。

## 10. 研究方向

核心假设是：

> 一次成功的 Agent 执行可能包含可复用的行为，可以被系统地捕获、验证并提升为可复用能力。

关键问题是：这样做能否创造足够的增量价值，以证明新增复杂度的合理性。

可能的结果是刻意不对称的：

```text
Forge 胜出
    → 继续 Capability Forge

Skill 已经足够
    → 停止 / 收缩 Forge

受管控的形成有帮助，但完整 Capability 运行时不需要
    → 保留 Skill 生成器 / 评估器 / 治理

Forge 更差
    → 停止这个方向
```

负面结果同样是有效的研究结论。

## 11. 仓库结构

```text
agent-capability-forge/
├── docs/
│   └── Capability Forge 规范文档
├── research/
│   ├── artifact-boundary-comparison.md
│   ├── artifact-contract/
│   ├── atif/
│   ├── codex-artifact/
│   ├── codex-runtime-capture/
│   ├── codex/
│   ├── deepseek/
│   ├── experiments/
│   ├── source-baseline.md
│   └── swe-agent/
├── src/
│   └── forge/
├── pilot/
└── tests/
```

仓库刻意把研究证据、架构决策、实现和实验结果放在一起。

## 12. 当前状态

| 项目 | 状态 |
|------|------|
| 架构 | ✅ |
| Artifact 契约 | ✅ |
| 运行时适配器边界 | ✅ |
| F+ 工程预演 | ✅ |
| 完整试点 | ⏳ |
| 主研究 | ⏳ |
| 业务价值 | ❓ |

项目目前正处在以下过渡阶段：

```text
架构 / 考古
        ↓
实验验证
```
