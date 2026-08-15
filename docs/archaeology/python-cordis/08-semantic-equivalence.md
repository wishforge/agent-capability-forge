# 语义等效测试与差距分析

## 1. 语义等效的定义

两个 runtime 语义等效，当且仅当下面 12 条 invariant 在相同的操作序列下产生相同结果。

## 2. TEST-01..12

| # | Invariant | Cordis 证据 | Python 候选 | 结论 |
|---|---|---|---|---|
| TEST-01 | Every effect has an owner | fiber `_disposables`（`fiber.ts:450-460`、`fiber.ts:520`） | AsyncExitStack 的 stack 是 owner；Dishka `_exits` 只覆盖依赖对象；AnyIO 只覆盖任务；Pluggy 无 | 需语义层统一 |
| TEST-02 | Every owner has a lifecycle scope | Fiber 状态机（`fiber.ts:159-170`、`222-310`） | AsyncExitStack 可 close 但无状态机；Dishka 有 scope 但无 plugin 身份 | 需语义层 |
| TEST-03 | Disposing owner disposes owned effects | `_unload` 清 `_disposables`（`fiber.ts:675-690`） | AsyncExitStack `aclose` ✓；Dishka close 只清依赖 ✓/✗ 按资源类型 | 组合可达 |
| TEST-04 | Teardown order is deterministic | 单 effect 内严格 LIFO；跨 effect 逆序启动（`fiber.ts:430-441`、`utils.ts:27-31`） | AsyncExitStack 严格 LIFO ✓；Dishka LIFO ✓；AnyIO 集合级 ✗ | 组合可达，需明确粒度 |
| TEST-05 | Dependency teardown respects dependency ordering | `provide` disposer await 依赖者（`reflect.ts:299-303`） | Dishka 只有 scope 推断，无等待；NoneBot2 无 | **必须自己实现** |
| TEST-06 | Cleanup is idempotent | `dispose` 单次执行返回同一 task（`fiber.ts:427-441`、`508-559`） | AsyncExitStack 结构性幂等 ✓；Dishka close 二次基本 no-op（`_exits` 已空） | 组合可达 |
| TEST-07 | Partial initialization rollback | `effect()` setup 失败时清理已收集 disposer（`fiber.ts:520-537`） | AsyncExitStack 需要调用方 try/except + aclose；Dishka 无 effect 概念 | 需语义层包装 |
| TEST-08 | Async tasks cannot outlive owner scope | Cordis core 无任务原语（[NOT_FOUND]）；由上层用 effect 包装 | AnyIO TaskGroup `__aexit__` 等待全部子任务（`_asyncio.py:751-812`） | AnyIO 提供 |
| TEST-09 | Event registrations cannot outlive owner scope | `ctx.on` → fiber effect（`events.ts:254-302`） | Pluggy unregister 手动；NoneBot2 全局 matchers | 需语义层 + EventBus |
| TEST-10 | Tool/service registrations cannot outlive owner scope | `ctx.provide` → fiber effect；dsh `tools.register` → `ctx.effect`（`reflect.ts:277-304`；`tools/src/index.ts:1037-1061`） | Dishka 不跟踪外部 registration（运行验证：close 后仍在） | **必须自己实现** |
| TEST-11 | Nested scopes teardown before parent | child fiber disposer 是 parent effect（`fiber.ts:265-297`） | Dishka `parent_closer` 链式 ✓；AsyncExitStack 由调用方保证；AnyIO 嵌套 TaskGroup ✓ | 组合可达 |
| TEST-12 | Failed teardown does not silently leak remaining effects | `_unload` 每项 try/logger（`fiber.ts:675-690`） | AsyncExitStack 继续跑后续 callback ✓；Dishka 聚合后抛 ✓；AnyIO 聚合任务异常 ✓ | 组合可达 |

## 3. 最大缺口

**Effect Ownership 是最大缺口**，具体分为三层：

1. **统一 effect registry**：Python 没有任何库让“任意副作用注册 + 自动撤销”成为一等语义（AsyncExitStack 最接近，但没有 plugin 身份、依赖图、事件、服务注册表）。
2. **Plugin 身份与状态机**：Dishka 有 scope 无 plugin；NoneBot2 有 plugin 无 scope；Pluggy 有 plugin 无生命周期。
3. **依赖驱动的动态 unload**：只有 Cordis 有“依赖消失 → 自动 unload → 依赖回来 → 自动 reload”。

## 4. 结论

```text
Python 已具备的 primitive:
    AsyncExitStack    → 任意 cleanup + LIFO + 失败继续
    AnyIO TaskGroup   → task ownership + 取消 + 异常聚合
    Dishka            → scoped DI + generator finalizer
    Pluggy            → plugin 对象 + hook relay + unregister

Python 缺失的语义层:
    PluginScope
    EffectRegistry（带 owner/order/idempotence/rollback）
    ServiceRegistry / ToolRegistry / EventBus（全部走 EffectRegistry）
    DependencyLifecycle（PENDING/ACTIVE/UNLOADING + 依赖等待）
```
