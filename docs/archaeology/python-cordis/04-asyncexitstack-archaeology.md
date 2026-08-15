# contextlib.AsyncExitStack 源码考古

CPython 3.13，`contextlib.py:631-766`。

## 1. 核心 API

| API | 行为 | 证据 |
|---|---|---|
| `enter_async_context(cm)` | `await cm.__aenter__()` 成功后 push `__aexit__` | `contextlib.py:654-670` |
| `push_async_callback(cb, *args)` | 把任意 coroutine 函数注册为 cleanup callback | `contextlib.py:690-701` |
| `push_async_exit(exit)` | 注册带 `__aexit__` 签名的函数/对象 | `contextlib.py:672-688` |
| `aclose()` | 立即 unwind，等价 `await __aexit__(None,None,None)` | `contextlib.py:703-714` |
| `__aexit__` | LIFO 执行 callback；异常继续执行剩余 callback；最后抛最后一个异常 | `contextlib.py:716-766` |

## 2. LIFO teardown

```text
while self._exit_callbacks:
    is_sync, cb = self._exit_callbacks.pop()   # 从尾部弹出 = LIFO
    ...
```

证据：`contextlib.py:742`。

## 3. 异常处理

```text
except BaseException as new_exc:
    _fix_exception_context(new_exc, exc)
    pending_raise = True
    exc = new_exc
```

证据：`contextlib.py:753-763`。

含义：

- 一个 callback 抛错不会阻止后续 callback 执行。
- 如果传入 `__aexit__` 的是原有异常，callback 抛的新异常会通过 `__context__` 链到旧异常。
- 结束后抛最后一个异常。

## 4. 幂等性

`aclose()` 两次：第一次已 `pop` 空 `_exit_callbacks`，第二次循环不执行，是 no-op。这是结构性的（`contextlib.py:737-766`），但没有显式“closed”标志，close 后仍可继续 push。

## 5. 能否作为 Cordis `ctx.effect()` 的底层 primitive？

### 5.1 语义映射

```text
Cordis:
    ctx.effect(cleanup)

Python:
    stack.push_async_callback(cleanup)

plugin scope        AsyncExitStack
    ↓                    ↓
register effect     push_async_callback
    ↓                    ↓
scope exit          aclose()
    ↓                    ↓
reverse cleanup     LIFO pop + await
```

### 5.2 成立的边界

| 语义 | AsyncExitStack 提供 | 仍需上层 |
|---|---|---|
| cleanup ownership | ✓ 每个 callback 属于该 stack | plugin 身份、scope 嵌套图 |
| LIFO | ✓ | — |
| async cleanup | ✓ | — |
| 失败继续清理 | ✓ | 错误聚合策略（Cordis 用 logger 吞掉，AsyncExitStack 会重抛） |
| 幂等 close | ✓（结构性） | 显式二次 dispose 约定 |
| plugin dependency | ✗ | 依赖图 / 状态机 |
| service registry | ✗ | service layer |
| plugin loading | ✗ | loader |
| typed event | ✗ | event bus |
| task lifecycle | ✗ | AnyIO TaskGroup |

### 5.3 行为差异（必须注意）

1. Cordis `_unload` 对每个顶层 effect disposer 的错误 `logger.error` 后**继续**，不向调用方抛；AsyncExitStack 会**重抛最后一个异常**。语义等效层需要决定错误策略。
2. Cordis 单 effect 内是**串行** LIFO；AsyncExitStack 也是串行 LIFO，所以这点一致。
3. Cordis fiber 顶层跨 effect 是**并发**启动（`Promise.all`）；AsyncExitStack 是串行。若要用 AsyncExitStack 精确复刻 Cordis，需要把“一个 fiber 的全部顶层 effect”分别包成独立 AsyncExitStack 再并发 close，或用自定义 registry。

## 6. 结论

AsyncExitStack 是 `ctx.effect()` 最合适的底层：它提供任意 cleanup callback 的 owner、LIFO、async、失败继续。**它不提供** plugin dependency、service registry、plugin loading、typed event、dependency-aware composition。
