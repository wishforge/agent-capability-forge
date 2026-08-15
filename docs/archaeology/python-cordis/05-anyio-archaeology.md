# AnyIO structured concurrency 源码考古

版本 4.13.0，`anyio/_backends/_asyncio.py`。

## 1. CancelScope

```text
class CancelScope(BaseCancelScope):
    def cancel(self, reason=None):          # 设置 _cancel_called，向 host task 投递取消
    def __enter__/__exit__                  # 激活/退出取消域
```

证据：`_backends/_asyncio.py:389-663`（类定义与 `cancel` at 637）。

关键属性：

- `_tasks: set[asyncio.Task]`（`_asyncio.py:407`）。
- `_child_scopes: set[CancelScope]`（`_asyncio.py:404`）。
- 取消会递归投递给未屏蔽的子 scope（`_asyncio.py:600-618`）。

## 2. TaskGroup

```text
class TaskGroup(abc.TaskGroup):
    def __init__(self):
        self.cancel_scope = CancelScope()
        self._tasks = set()
        self._exceptions = []

    async def __aenter__(self):
        self.cancel_scope.__enter__()
        self._active = True

    async def __aexit__(...):
        if exc_val is not None:
            self.cancel_scope.cancel()
        while self._tasks:
            await self._on_completed_fut        # 等待所有子任务结束
        if self._exceptions:
            raise BaseExceptionGroup("unhandled errors in a TaskGroup", ...)
```

证据：`_asyncio.py:738-812`（类、`__aenter__`、`__aexit__`）。

子任务异常处理：

```text
task_done():
    if exc is not None:
        self._exceptions.append(exc)
        if not cancel_scope._effectively_cancelled:
            self.cancel_scope.cancel()          # 一个任务失败 → 取消整个组
```

证据：`_asyncio.py:838-873`。

## 3. CapabilityScope 映射

```text
CapabilityScope
    ├── Task A
    ├── Task B
    └── Task C

实现:
    async with create_task_group() as tg:
        tg.start_soon(task_a)
        tg.start_soon(task_b)
        tg.start_soon(task_c)

CapabilityScope.dispose():
    cancel_scope.cancel()      # 取消子任务
    await __aexit__(...)       # await 所有子任务 + 聚合异常
```

证据：

- `start_soon` 把任务加入 `cancel_scope._tasks` 与 `self._tasks`（`_asyncio.py:914-920`、`_spawn` 的 `_asyncio.py:880-886`）。
- `__aexit__` 先 cancel，再等待全部任务，再抛 `BaseExceptionGroup`（`_asyncio.py:759-812`）。

## 4. 这构成 effect ownership 的哪个子集？

**是 task ownership 的完整子集**：

- 任务不能超过 owner scope（`__aexit__` 等待所有子任务结束）。
- dispose 会取消任务（`cancel_scope.cancel()`）。
- 失败聚合（`BaseExceptionGroup`）。

**不是完整 effect ownership**：

- TaskGroup 只拥有任务，不拥有 tool/service/event/listener/timer/subprocess。
- 子任务之间没有注册序 LIFO（是集合级等待）。
- 没有依赖图。

## 5. 与 Cordis 对照

| 问题 | AnyIO | Cordis |
|---|---|---|
| 任务不能超过 owner scope | ✓ | ✗（Cordis core 无任务原语，需上层包装） |
| 取消 + await | ✓ | 无 |
| 异常聚合 | ✓ `BaseExceptionGroup` | `logger.error` + 继续 |
| 任务 teardown 顺序 | 集合级 | 无 |
| 任意 effect ownership | ✗ | ✓ fiber effect |

结论：AnyIO 补上 Cordis 缺失的 **background task lifecycle** 子集；但它必须挂在 effect registry 下（`ctx.effect(() => () => tg.cancel_scope.cancel())` 或等效），才能获得 plugin scope 语义。
