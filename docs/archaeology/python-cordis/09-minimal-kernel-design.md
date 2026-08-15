# 最小 Semantic Kernel 设计

> 第一阶段只给出设计与最小 probe，不实现完整框架。

## 1. 目标模型

```text
PluginScope
    ├── ServiceRegistry      # ctx.provide / ctx.get
    ├── EventBus             # ctx.on / ctx.emit
    ├── DependencyGraph      # inject → PENDING/ACTIVE/UNLOADING
    ├── EffectRegistry       # 任意 cleanup 的 owner 列表
    └── TaskGroup            # AnyIO TaskGroup / asyncio.TaskGroup
```

`scope.dispose()` 必须自动执行：

```text
1. stop child scopes
2. cancel tasks
3. unregister services
4. unregister tools
5. remove events
6. close resources
7. reverse cleanup
```

## 2. EffectRegistry 应该自己实现还是依赖 AsyncExitStack？

### 方案对比

| | A: EffectRegistry → AsyncExitStack | B: EffectRegistry → Dishka | C: EffectRegistry → AnyIO TaskGroup + AsyncExitStack | D: 全部自己实现 |
|---|---|---|---|---|
| correctness | 高（LIFO/async/失败继续都是官方语义） | 中（Dishka 只认依赖对象） | 高（任务归 TaskGroup，其余归 AsyncExitStack） | 取决于实现质量 |
| ownership | 高（stack = owner） | 低（外部副作用不跟踪） | 高 | 中 |
| lifecycle | 低（无状态机） | 中（scope） | 中 | 低 |
| async | ✓ | ✓ | ✓ | 需要自己处理 |
| error handling | ✓（继续跑 + 重抛） | ✓（ExitError 聚合） | ✓（TaskGroup 聚合） | 容易漏 |
| nested scope | 调用方负责 | ✓ parent_closer | ✓ 嵌套 TaskGroup | 需要自己实现 |
| dependency | ✗ | △（scope 推断） | ✗ | 需要自己实现 |
| testability | 高（stdlib） | 中 | 高 | 低 |
| complexity | 低 | 中 | 中 | 高 |
| Agent Runtime 集成 | 只解决 cleanup | 只解决 DI | 解决 task + cleanup | 全包 |

**推荐：方案 C。**

理由：

- AsyncExitStack 已经实现任意 cleanup 的 LIFO、async、失败继续、幂等——自己实现是重写 stdlib。
- AnyIO TaskGroup 已经实现任务取消、等待、异常聚合——自己实现是重写 structured concurrency。
- Dishka 作为 DI 子层（不是 effect owner）提供 scoped dependency objects 与 generator finalizer。
- 语义层只需要约 200-400 行：PluginScope + EffectRegistry 包装 + ServiceRegistry/EventBus/ToolRegistry 薄封装 + DependencyLifecycle。

## 3. 最小语义层组成

```python
# 伪代码，完整 probe 见 prototype/semantic_layer_probe.py
class PluginScope:
    def __init__(self, parent=None, name="root"):
        self.parent = parent
        self.children = []
        self.effects = []                 # [(label, cleanup)]
        self.tasks = asyncio.TaskGroup()  # 或 anyio
        self._disposed = False

    def effect(self, label, cleanup):
        # 登记 cleanup；owner = self
        self.effects.append((label, cleanup))
        return cleanup

    def child(self, name):
        scope = PluginScope(parent=self, name=name)
        self.children.append(scope)
        return scope

    async def dispose(self):
        if self._disposed: return
        self._disposed = True
        for child in reversed(self.children):   # 1. child scopes
            await child.dispose()
        self.tasks.cancel_scope.cancel()        # 2. tasks
        await self.tasks.__aexit__(None, None, None)
        for _, cleanup in reversed(self.effects):  # 3-7. reverse cleanup
            try:
                await cleanup()
            except Exception:
                pass                              # 失败不阻止后续
```

## 4. 关键语义决策

1. **teardown 粒度**：复刻 Cordis——单 effect 内严格 LIFO 串行；跨 effect 可按逆序启动（若要完全等效，跨 effect 也要并发）。
2. **错误策略**：默认 logger + 继续（Cordis `_unload`），可选聚合抛错（Dishka/AnyIO 风格）。
3. **依赖等待**：service unregister 时先唤醒依赖者并等待其 dispose（对应 `reflect.ts:299-303`）。
4. **tool/service/event** 都是 `effect()` 的薄封装：注册动作返回 undo，undo 再登记进 scope。
5. **幂等**：`dispose()` 用 `_disposed` 标志 + 单次执行。

## 5. 与方案 A/B/D 的差别

- A 缺任务管理和依赖图。
- B 的错误在于把“任意 effect”硬塞给 Dishka；Dishka 的 `_exits` 是依赖对象的 finalizer，不是通用 effect registry。
- D 需要重写 AsyncExitStack / AnyIO 的错误、取消、聚合语义，收益为零。

## 6. 最小 probe

`prototype/semantic_layer_probe.py` 模拟 `filesystem` capability：

```text
filesystem.install(scope)
  ├── register tool
  ├── register service
  ├── register event listener
  ├── spawn background worker
  ├── create timer
  └── open async resource

filesystem.uninstall(scope) == scope.dispose()
```

验证 TEST-01..12（见 `08-semantic-equivalence.md`），并记录 `resource_id / owner_scope / cleanup_callback / registration_order`。
