# 最终结论与推荐

## 1. 第一问：Python 是否已经存在 Cordis-equivalent runtime？

**NO。**

没有单个 Python 项目同时提供：

- plugin 身份 + 状态机（PENDING/LOADING/ACTIVE/UNLOADING/DISPOSED）
- 统一 effect registry（任意副作用有 owner）
- 依赖驱动的动态 unload
- service / tool / event / task / resource 的 ownership
- 逆序 teardown + 失败继续 + 幂等

NoneBot2 最接近“插件框架”，但没有 per-plugin scope/effect/dispose；Dishka 有 scope 但没有 plugin 和任意 effect；AnyIO/AsyncExitStack 只是底层 primitive。

## 2. 第二问：哪个项目最接近？

**NoneBot2**（作为 Agent Runtime 的代表）：它有插件加载、parent/sub 插件、事件 Matcher、app 级 lifespan。但它缺的恰好是 Cordis 的 ownership 内核，所以也只是“最接近”。

若只看 DI/scope：**Dishka** 最接近 Cordis 的依赖侧。

## 3. 第三问：哪几个 primitive 可以组合？

```text
Dishka              → scoped DI + generator finalizer
AsyncExitStack      → 任意 cleanup（LIFO / async / 失败继续 / 幂等）
AnyIO TaskGroup     → task ownership（取消 / await / 异常聚合）
Pluggy              → plugin 对象 + hook relay + unregister
```

四者组合可以覆盖 Cordis 语义的大部分“机械”部分，但不能直接拼出 Cordis。

## 4. 第四问：哪些语义必须自己实现？

必须自己实现的（最小集合）：

1. **PluginScope / Fiber 状态机**：plugin 身份、生命周期状态、动态卸载。
2. **EffectRegistry**：把任意副作用注册为 owner-scoped effect，逆序 teardown、幂等、失败继续。
3. **ServiceRegistry / ToolRegistry / EventBus ownership**：每个 registration 是 effect，dispose 时撤销。
4. **DependencyLifecycle**：依赖未齐不执行、依赖消失自动 unload、提供方等待依赖者卸载。
5. **DependencyGraph**（如果用 Dishka，只补“plugin 依赖驱动”一层）。

## 5. 第五问：Effect Ownership 是否是最大缺口？

**是。**

证据：

- AsyncExitStack 是“无身份”的 effect owner。
- Dishka 不跟踪 `tool_registry.register(tool)` 这类副作用（运行验证：container close 后 registration 仍在）。
- NoneBot2 的 Matcher 注册后只能手动 destroy。
- Pluggy unregister 只删 hook，不销毁资源。

没有统一 effect registry，其他一切（DI、scope、事件）都无法自动获得“dispose 即全部清理”的保证。

## 6. 第六问：是否可以实现 Plugin → Scope → Effect Registry → Service Registry → EventBus → Dispose？

**可以。**

最小语义层约 200-400 行（原型见 `prototype/semantic_layer_probe.py`），结构：

```text
Plugin
  → PluginScope
    → EffectRegistry（AsyncExitStack 包装）
    → ServiceRegistry（effect 化的 provide/unprovide）
    → EventBus（effect 化的 on/off）
    → ToolRegistry（effect 化的 register/unregister）
    → TaskGroup（AnyIO/asyncio）
  → dispose()
```

## 7. 第七问：这套 semantic layer 是否适合作为 Agent Capability Runtime？

**适合，前提是只做“语义内核”，不做 agent 逻辑。**

- 它能给 capability（filesystem、code、retrieval…）提供 install/uninstall 的确定性资源语义。
- 它和 DSH 的 `dsh-scope` 模型同构：scope 是注册身份 + 事件路由 + 生命周期。
- 它不应该包含 agent loop / tool 执行器 / model adapter；那些是上层 Agent Runtime 的事。

## 8. 第八问：与 dsh-java 的对应关系是什么？

`[INFERENCE]`：本轮在 workspace 与公开网络均未找到 `dsh-java` 仓库或源码，因此只能按语义对应关系回答：

```text
Cordis            = effect/plugin/fiber 语义
dsh-core          = Cordis + dsh-scope + tool runtime（TypeScript）
dsh-java          = 上述语义的 Java 实现/移植（若存在）
Python Semantic Kernel = 同一语义的 Python 实现
```

对应关系是**逐层映射**，不是 API 同名：

| 语义 | dsh-java（推断） | Python Semantic Kernel |
|---|---|---|
| Fiber / PluginScope | PluginScope / Fiber | PluginScope |
| effect registry | EffectRegistry | EffectRegistry（AsyncExitStack） |
| service provide | ServiceRegistry | ServiceRegistry |
| event | EventBus + scope filter | EventBus + scope filter |
| task | TaskGroup | AnyIO TaskGroup |
| DI | Dishka 等价物 | Dishka |

如果 dsh-java 是用户内部项目，建议后续用同一份 TEST-01..12 矩阵对它做语义审计；本结论不涉及它的具体实现。

## 9. 架构图

```text
┌─────────────────────────────────────────────────────┐
│ Cordis                                               │
│   Plugin / Fiber / Context / Effect / Event / DI    │
│   ownership + reverse teardown + dependency lifecycle│
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ dsh-core                                             │
│   Cordis + dsh-scope + tool runtime + presets        │
│   （TypeScript 实现层）                               │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ Python Semantic Kernel（本轮结论：需要新建的最小层） │
│   PluginScope / EffectRegistry / ServiceRegistry    │
│   EventBus / TaskGroup / DependencyLifecycle        │
│   底层：Dishka + AsyncExitStack + AnyIO + Pluggy    │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ Agent Runtime                                       │
│   agent loop / model adapter / tool 执行器          │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ Capability Runtime                                  │
│   filesystem / code / retrieval 等 capability       │
│   install = 注册；uninstall = scope.dispose()       │
└─────────────────────────────────────────────────────┘
```

每层职责：

| 层 | 负责 |
|---|---|
| Cordis | 语义定义（effect ownership / fiber / dependency lifecycle） |
| dsh-core | 语义在 TypeScript 的具体化 + agent 领域扩展（scope、tool） |
| Python Semantic Kernel | 语义在 Python 的具体化（本报告的核心结论） |
| Agent Runtime | 用 kernel 组合 agent 行为 |
| Capability Runtime | 用 kernel 安装/卸载具体 capability |

## 10. 最终推荐

### 选 B：Dishka + AsyncExitStack + AnyIO + Pluggy

准确表述：**用 Dishka（DI）+ AsyncExitStack（effect cleanup）+ AnyIO（task lifecycle）+ Pluggy（hook relay）作为底层，在其上新增约 200-400 行的 Cordis Semantic Layer（PluginScope / EffectRegistry / ServiceRegistry / EventBus / DependencyLifecycle）。**

### 为什么不选另外三个

| 选项 | 拒绝原因 |
|---|---|
| A. 直接采用 Dishka | Dishka 只拥有“依赖对象”，不拥有任意 effect；`tool_registry.register(tool)` 在 close 后仍然存活（运行验证），无法满足 TEST-01/03/09/10 |
| C. 在 Agent Framework 上增加 Cordis Semantic Layer | NoneBot2/LangGraph/PydanticAI 都自带 agent 耦合；语义内核应位于 Agent Runtime 之下，而不是某个 agent framework 之上；且它们仍然缺 ownership 内核，等于 C + 自己实现同一层 |
| D. 从零实现整个 Kernel | AsyncExitStack 和 AnyIO 已经把最难的 LIFO/async/取消/聚合语义做对；重写它们只会增加 3am 复杂度，没有收益 |

### 需要显式补上的语义（B 不含的部分）

```text
PluginScope 状态机
EffectRegistry（owner/order/idempotence/rollback）
ServiceRegistry / ToolRegistry / EventBus 的 effect 化
DependencyLifecycle（依赖等待 + 自动 unload）
```

这就是“Python 是否已经具备全部 primitive”的答案：**机械 primitive 已具备，Cordis 语义层仍需自己写，但只需要很薄的一层。**
