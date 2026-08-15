# Dishka 源码考古

commit：`79057588a1fa5fd664ee6687b5492e6942ca805b`（2026-08-14）。

## 1. 目标调用链

### 1.1 resolve()

```text
AsyncContainer.get(T)
  → AsyncContainer._get(key)
    → AsyncContainer._get_unlocked(key)
      → registry.get_compiled_async(key)          # Registry.get_compiled_async
        → registry._compile_factory_async(factory) # Registry._compile_factory_async
          → compile_factory(...)                   # code_tools/factory_compiler.py
            → builder.make_getter() → 生成 getter 函数
      → compiled(getter, exits, cache, context, container, has)
```

证据：

- `async_container.py:275-312`（`_get_unlocked` 调 `registry.get_compiled_async`，再调 `compiled(...)`）。
- `registry.py:186-218`（`get_compiled_async` → `_compile_factory_async`）。
- `code_tools/factory_compiler.py:442-479`（`compile_factory` 生成 getter 并返回 `builder.build_getter()`）。

### 1.2 resource creation + finalizer

async generator factory 的生成体：

```text
generator = source(...)
solved = await anext(generator)
exits.append((None, generator))          # finalizer 进入当前容器的 _exits
cache[key] = solved                       # 若 cache=True
return solved
```

证据：`code_tools/factory_compiler.py:217-231`（`_async_generator_body`）。

同步 generator 同理：`code_tools/factory_compiler.py:196-214`（`_generator_body`）。

### 1.3 scope close

```text
await container.close()
  → AsyncContainer.__aexit__
    while self._exits:
      gen, agen = self._exits.pop()       # LIFO
      await agen.asend(exception)          # 把异常传给每个 generator
    self._cache = {}
    await self.parent_closer(...)          # 关闭父 scope
    if errors: raise ExitError(...)        # 所有 cleanup 跑完后才聚合抛错
```

证据：`async_container.py:314-352`（`close` / `__aexit__`）；`container.py:243-279`（同步版）。

### 1.4 嵌套 scope

```text
container()
  → registry.child_registry
  → new AsyncContainer(parent=container, parent_getter=container._get, parent_closer=container.__aexit__)
```

证据：`async_container.py:95-157`（`__call__`）。

`parent_closer` 的存在使子容器关闭后自动关闭父容器（`async_container.py:347-350`）。

## 2. Scope 到底拥有什么？

### 2.1 依赖对象

每个容器有 `_cache: dict[Any, object]` 和 `_exits: list[Exit]`（`async_container.py:32-48`）。

- `_cache` 拥有**已解析依赖对象**（`cache[key] = solved`，`factory_compiler.py:265-267`）。
- `_exits` 拥有**通过 generator factory 创建的资源的 finalizer**（`factory_compiler.py:217-231`）。

### 2.2 任意 runtime effect？

**不能。** `_exits` 只包含 provider factory 生成的 generator；任何非 factory 副作用都不在容器记录里。

运行验证（使用克隆源码 `PYTHONPATH=/tmp/dishka-src/src`）：

```text
async with container() as c:
    await c.get(A); await c.get(B)
    undo = tool_registry.register("tool-x", fn)

# 输出：
# cleanup order after child scope close: ['enter A', 'enter B', 'exit B', 'exit A']
# tool still registered after container close: True
```

即：Dishka 知道 A/B 的 finalizer 并 LIFO 清理，但 `tool_registry.register(tool)` 这个副作用在容器 close 后**仍然存在**。

### 2.3 语义断裂的位置

```text
plugin 代码:
    tool_registry.register(tool)     ← 外部容器/注册表的可变操作
    service_registry.register(svc)   ← 另一个外部可变操作

Dishka:
    resolve() 只解析 DependencyKey
    _exits 只记录 provider generator
    ⇒ Dishka 不知道上述 registration 属于哪个 plugin，也无法在 scope close 时撤销
```

要恢复 ownership，必须由调用方把撤销动作包装成 provider factory（`@provide` + generator）或外部 effect registry。Dishka 自身没有“effect”抽象。

## 3. Dependency teardown ordering

### 3.1 scope 传播

未显式指定 scope 的 factory 由依赖图推断：`scope = max(各依赖的 scope)`，无依赖时用请求方 scope（`graph_builder/builder.py:375-416`）。GraphValidator 再校验子 factory 的 scope 合法性（`graph_builder/validator.py:16-94`）。

### 3.2 没有“被依赖方等待依赖者”

Dishka 的 close 只按 `_exits` 的 LIFO 顺序跑 finalizer；finalizer 之间没有依赖图等待。若两个依赖对象有构造依赖（A 依赖 B），close 时 B 的 finalizer 会先于 A 运行（后创建的先关），这通常符合直觉；但**没有 Cordis `provide` disposer 中 `await dependents` 的显式保证**（对比 `vendor/cordis/src/reflect.ts:299-303`）。

## 4. Failure rollback

`__aexit__` 对每个 finalizer 用 `try/except Exception` 收集错误，全部跑完后 `raise ExitError`（ExceptionGroup）。运行验证：

```text
bad 的 finally 抛 RuntimeError("boom")
ok 的 finally 仍然执行
close 抛 ExitError
```

证据：`async_container.py:325-341`（错误收集与继续循环）；运行输出见上文。

## 5. 结论

| 能力 | Dishka | Cordis 对应 |
|---|---|---|
| scoped DI | ✓ | `ctx.inject` / service resolution |
| generator 资源 finalizer | ✓ | `ctx.effect` 的 cleanup |
| LIFO close | ✓ | fiber `_unload` |
| 任意 effect ownership | ✗ | fiber effect registry |
| plugin 身份 | ✗ | Fiber |
| 依赖驱动的 plugin 生命周期 | ✗ | PENDING/ACTIVE/UNLOADING |
| 事件/工具注册撤销 | ✗ | `ctx.on` / dsh `tools.register` |

Dishka 是**依赖对象容器**，不是 **effect 容器**。关键区别：Cordis 的 Scope 拥有“注册到它的一切”，Dishka 的 Scope 只拥有“通过它解析出的依赖对象”。
