# Python 候选 primitives 总览

对每个候选回答 A–O 共 15 个问题：

| 编号 | 问题 |
|---|---|
| A | Plugin（可加载/卸载的插件单元） |
| B | Context（可继承的上下文对象） |
| C | Scope（生命周期/可见性边界） |
| D | DI（依赖注入） |
| E | Lifecycle（加载/激活/卸载状态机） |
| F | Cleanup（资源释放） |
| G | Reverse cleanup（LIFO teardown） |
| H | Nested scope（子 scope 先于父 scope 关闭） |
| I | Async cleanup（async 资源释放） |
| J | Dependency ownership（被依赖方等依赖者卸载） |
| K | Dynamic unload（运行时按身份卸载） |
| L | Failure rollback（部分初始化回滚） |
| M | Resource ownership（任意 effect 有 owner） |
| N | Event / Hook（事件或钩子机制） |
| O | Background task lifecycle（任务不能超过 owner scope） |

## 1. Dishka

| 问题 | 答案 | 证据 |
|---|---|---|
| A Plugin | ✗ 无插件概念 | `src/dishka/` 非 integration 部分无 plugin 语义（`rg "plugin"` 无命中） |
| B Context | ✗ 有 `context` dict，但只是请求级数据 | `container.py:32-41`、`async_container.py:32-41` |
| C Scope | ✓ `Scope.RUNTIME/APP/SESSION/REQUEST/ACTION/STEP`，Registry 链 | `entities/scope.py:43-48`；`registry.py:52-81` |
| D DI | ✓ `Provider.provide/alias/decorate/from_context` | `provider/provider.py:146-273` |
| E Lifecycle | △ 只有容器 enter/exit，没有 plugin 状态机 | `async_container.py:320-352` |
| F Cleanup | ✓ generator/async-generator factory 的 finalizer | `code_tools/factory_compiler.py:196-231` |
| G Reverse cleanup | ✓ `_exits.pop()` LIFO | `container.py:249-279`、`async_container.py:320-352` |
| H Nested scope | ✓ `Container.__call__()` 创建 child，`parent_closer` 链式关闭 | `container.py:96-158`、`async_container.py:95-157` |
| I Async cleanup | ✓ `__aexit__` await `agen.asend(exception)` | `async_container.py:320-352` |
| J Dependency ownership | △ 只有 scope 大小约束，没有“owner 等待依赖者”的生命周期 | `graph_builder/builder.py:375-416`（scope 计算） |
| K Dynamic unload | ✗ 容器整体 close；没有按依赖身份卸载 | `async_container.py:314-352` |
| L Failure rollback | △ cleanup 异常聚合为 `ExitError` 并继续跑剩余 exit；但没有“plugin 启动失败回滚已注册 effect”的概念 | `async_container.py:320-352`；`exceptions.py:28-32` |
| M Resource ownership | △ 只拥有**通过 provider 创建的依赖对象及其 finalizer**；外部副作用（如 `tool_registry.register(tool)`）不在 `_exits` 中 | `container_objects.py:1-16`；运行验证见 `03-dishka-archaeology.md` |
| N Event / Hook | ✗ 无事件总线 | [NOT_FOUND] |
| O Background task lifecycle | ✗ 无任务原语 | [NOT_FOUND] |

结论：Dishka 是“scoped DI + generator finalizer”的好基座，但不是 plugin/effect kernel。

## 2. contextlib.AsyncExitStack

| 问题 | 答案 | 证据 |
|---|---|---|
| A Plugin | ✗ 无插件概念 | `contextlib.py:631-766` |
| B Context | ✗ 无上下文对象 | 同上 |
| C Scope | △ 一个 stack 就是一个可以 dispose 的 scope，但没有身份/可见性 | `contextlib.py:703-714` |
| D DI | ✗ | 同上 |
| E Lifecycle | ✗ 只有 push/close，没有状态机 | 同上 |
| F Cleanup | ✓ `push_async_callback` / `enter_async_context` | `contextlib.py:654-701` |
| G Reverse cleanup | ✓ `_exit_callbacks.pop()` LIFO | `contextlib.py:737-766` |
| H Nested scope | △ 多个 stack 可以嵌套，但嵌套顺序完全由调用方负责 | `contextlib.py:703-714` |
| I Async cleanup | ✓ `aclose()` await 全部 async callback | `contextlib.py:703-714`、`716-766` |
| J Dependency ownership | ✗ | 同上 |
| K Dynamic unload | ✗ 只能整体关闭 stack | `contextlib.py:703-714` |
| L Failure rollback | △ callback 抛错会继续执行剩余 callback，最后抛最后一个异常；但没有“注册阶段失败自动回滚” | `contextlib.py:742-763` |
| M Resource ownership | ✓ 任意 cleanup callback 都有 owner = 该 stack | `contextlib.py:690-701` |
| N Event / Hook | ✗ | 同上 |
| O Background task lifecycle | ✗ 无任务管理 | 同上 |

结论：AsyncExitStack 是 `ctx.effect()` 的最接近底层 primitive，但只解决 cleanup ownership，不解决 plugin/dependency/event/task。

## 3. AnyIO

| 问题 | 答案 | 证据 |
|---|---|---|
| A Plugin | ✗ | `anyio/abc/_tasks.py:1-117` |
| B Context | ✗ | 同上 |
| C Scope | △ `CancelScope` 是取消边界；`TaskGroup` 是任务生命周期边界 | `_backends/_asyncio.py:389-663`、`738-938` |
| D DI | ✗ | 同上 |
| E Lifecycle | ✗ 无 plugin 状态机 | 同上 |
| F Cleanup | △ 只清理任务/取消，不管理任意资源 | `_backends/_asyncio.py:751-812` |
| G Reverse cleanup | ✗ 任务等待是集合级，不是注册序 | `_backends/_asyncio.py:766-805` |
| H Nested scope | △ TaskGroup 可嵌套，子组先于父组退出 | `_backends/_asyncio.py:751-812` |
| I Async cleanup | ✓ `__aexit__` await 所有子任务 | `_backends/_asyncio.py:766-805` |
| J Dependency ownership | ✗ | 同上 |
| K Dynamic unload | ✗ 只能取消整个组 | 同上 |
| L Failure rollback | △ 子任务异常聚合为 `BaseExceptionGroup`；没有初始化回滚 | `_backends/_asyncio.py:799-812` |
| M Resource ownership | ✗ 只拥有任务，不拥有 tool/service/listener | 同上 |
| N Event / Hook | ✗ | 同上 |
| O Background task lifecycle | ✓ 子任务不能超过 TaskGroup；退出时 cancel + await，异常聚合 | `_backends/_asyncio.py:751-812`、`860-873` |

结论：AnyIO 解决 **effect ownership 的子集：task ownership**。

## 4. Pluggy

| 问题 | 答案 | 证据 |
|---|---|---|
| A Plugin | ✓ `PluginManager.register(plugin)` / `unregister(plugin)` | `pluggy/_manager.py:122-196`、`198-230` |
| B Context | ✗ 无上下文对象 | `_manager.py:80-116` |
| C Scope | ✗ 无 scope，只有全局 HookRelay | `_manager.py:80-116` |
| D DI | ✗ | 同上 |
| E Lifecycle | ✗ 只有 register/unregister，无状态机 | `_manager.py:122-230` |
| F Cleanup | △ hook wrapper 有 teardown，但按“一次 hook 调用”而不是“插件生命周期” | `_callers.py:53-172` |
| G Reverse cleanup | △ wrapper teardown 逆序（`reversed(teardowns)`），但仅限单次 hook call | `_callers.py:119-153` |
| H Nested scope | ✗ | 同上 |
| I Async cleanup | ✗ 官方不支持 async hooks（wrapper 是同步 generator） | `_callers.py:53-172` |
| J Dependency ownership | ✗ | 同上 |
| K Dynamic unload | ✓ `unregister` 移除该 plugin 的所有 hook impl | `_manager.py:198-230` |
| L Failure rollback | ✗ | 同上 |
| M Resource ownership | ✗ unregister 只删 hook，不销毁插件注册的资源 | `_manager.py:198-230` |
| N Event / Hook | ✓ 1:N hooks、firstresult、wrapper | `_hooks.py:382-…`；`_callers.py:53-172` |
| O Background task lifecycle | ✗ | 同上 |

结论：Pluggy 提供 Plugin + Hook + Unregister，但**没有 plugin-owned scope、effect registry、自动 reverse disposal**。

## 5. NoneBot2（Agent Runtime 代表）

| 问题 | 答案 | 证据 |
|---|---|---|
| A Plugin | ✓ Python 模块即插件，`PluginManager.load_plugin` | `nonebot/plugin/manager.py:156-199` |
| B Context | △ 无 Cordis 式 context；有 `get_driver()` 全局对象 | `nonebot/__init__.py` |
| C Scope | ✗ 无 plugin scope；只有全局 app 生命周期 | `internal/driver/_lifespan.py:1-99` |
| D DI | △ 有 `Dependent`/参数解析，但无生命周期容器 | `nonebot/dependencies/__init__.py` |
| E Lifecycle | △ 只有 app 级 startup/shutdown，无 plugin 级状态机 | `_lifespan.py:58-92` |
| F Cleanup | △ app 级 shutdown 逆序跑 `on_shutdown`，取消后台任务组 | `_lifespan.py:71-92` |
| G Reverse cleanup | △ `reversed(self._shutdown_funcs)`，但只在 app 关闭时 | `_lifespan.py:80` |
| H Nested scope | ✗ 有 parent/sub plugin 记录，但无 teardown 级联 | `plugin/model.py:67-92`；`plugin/__init__.py:96-133` |
| I Async cleanup | ✓ shutdown 是 async，task group 会 await | `_lifespan.py:71-92` |
| J Dependency ownership | ✗ `require()` 只保证加载，不建立生命周期依赖 | `plugin/load.py:134-169` |
| K Dynamic unload | ✗ `Plugin` 无 unload；`_plugins` 只在导入失败时 `_revert_plugin` | `plugin/model.py:67-92`；`plugin/__init__.py:127-133`；[NOT_FOUND] unload |
| L Failure rollback | △ 插件模块导入失败时 `_revert_plugin` 删除注册 | `plugin/manager.py:244-265` |
| M Resource ownership | ✗ Matcher 注册到全局 `matchers`，只有手动 `destroy()` | `internal/matcher/matcher.py:323-330` |
| N Event / Hook | ✓ Matcher 事件响应、`on_bot_connect` 等钩子 | `matcher.py:216-330`；`driver/abstract.py:137-165` |
| O Background task lifecycle | ✓ app 级 `task_group`，shutdown 时 cancel + await | `_lifespan.py:58-92` |

结论：NoneBot2 是 Python 生态里最接近“插件框架 + 生命周期”的 Agent Runtime，但**核心缺口与 Cordis 完全相反：它没有 per-plugin scope、effect registry、动态 unload**。
