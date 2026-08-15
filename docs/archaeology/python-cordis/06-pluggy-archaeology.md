# Pluggy 源码考古

版本 1.5.0。

## 1. PluginManager

### 1.1 register

```text
PluginManager.register(plugin, name=None)
  → 写入 _name2plugin
  → 扫描 plugin 的 dir()，找到带 hookimpl 标记的方法
  → 为每个 hook 创建/复用 HookCaller
  → hook._add_hookimpl(hookimpl)
```

证据：`pluggy/_manager.py:122-196`。

### 1.2 unregister

```text
PluginManager.unregister(plugin)
  → 对 plugin 的每个 hookcaller 调用 _remove_plugin(plugin)
  → del _name2plugin[name]
```

证据：`pluggy/_manager.py:198-230`。

unregister 只移除 hook implementation，**不执行任何资源清理**。

## 2. Hook 执行与 wrapper teardown

`_multicall`（`pluggy/_callers.py:53-172`）：

```text
for hook_impl in reversed(hook_impls):
    if wrapper:
        gen = hook_impl.function(...)
        next(gen)
        teardowns.append(gen)
    else:
        res = hook_impl.function(...)

# 调用结束后:
for teardown in reversed(teardowns):
    teardown.send(result) / teardown.throw(exception)
```

证据：`_callers.py:71-119`（wrapper setup）、`_callers.py:119-153`（逆序 teardown）。

注意：

- teardown 是**单次 hook 调用**的环绕逻辑，不是插件生命周期。
- 是同步 generator，没有 async 支持。
- 一个 wrapper teardown 抛错会覆盖结果并继续（`_callers.py:127-151`），但这是“调用链”语义，不是“资源 registry”语义。

## 3. 回答：Pluggy 提供什么、不提供什么

| 提供 | 证据 |
|---|---|
| Plugin 对象 + register/unregister | `_manager.py:122-230` |
| 1:N Hook 调用（普通 / firstresult / wrapper） | `_hooks.py:382-…`、`_callers.py:53-172` |
| plugin 发现（setuptools entrypoints） | `_manager.py:397-…` |
| hook 调用级逆序 wrapper teardown | `_callers.py:119-153` |

| 不提供 | 证据 |
|---|---|
| Plugin-owned Scope | [NOT_FOUND] |
| Effect Registry | [NOT_FOUND] |
| 自动 reverse disposal | [NOT_FOUND]（只有 per-call wrapper teardown） |
| DI / service registry | [NOT_FOUND] |
| 事件传播过滤（scope-aware） | [NOT_FOUND] |
| async hook | [NOT_FOUND]（官方 wrapper 是同步 generator） |

## 4. 结论

Pluggy 可以作为 Cordis `ctx.on` / hook relay 的底层，但它需要被包进 effect registry：每次 `register` 返回的 hook 应通过 `ctx.effect` 注册 unregister，才能在 plugin dispose 时自动撤销。Pluggy 自身没有这个语义。
