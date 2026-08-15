# Cordis Semantic Matrix（ground truth）

源码基线：

- upstream `cordiverse/cordis` commit `8cc9e33`（`packages/core/src/`）。
- DeepSeek Harness vendored fork commit `47f9438`（`vendor/cordis/src/`）。
- 两处核心语义一致；本表以 vendored fork 行号为主，upstream 行号标注在需要区分处。

## 1. 语义矩阵

| Semantic | Cordis mechanism | Evidence | Required invariant |
|---|---|---|---|
| Plugin | `ctx.plugin(plugin, config)` → 创建/复用 `Plugin.Runtime`，`new Fiber(ctx, config, inject, runtime, ...)` | `vendor/cordis/src/registry.ts:316-343`；`fiber.ts:222-310` | 一个 plugin 应用 = 一个 Fiber，拥有独立生命周期 |
| Context | `Context` 是 Proxy，`root` 持有内置 services；`extend()` 创建原型继承的子上下文 | `context.ts:42-146`；`reflect.ts:133-211` | 每个 fiber 有独立 `ctx`，且继承 parent 的依赖面 |
| Scope | 子上下文通过 `ctx.extend()` 派生；`isolate(name)` 为 service 建立独立 scope 标签 | `context.ts:103-127` | scope 是依赖可见性的边界，不是独立容器 |
| DI | `inject` 声明依赖；`Fiber._checkImpl/_refresh` 决定 PENDING→ACTIVE | `registry.ts:43-80`；`fiber.ts:597-650` | 依赖未齐时 plugin 不执行，依赖消失时自动 unload |
| Service registry | `ctx.provide(name, value)` 写入 `ReflectService.store`，记录 `impl.fiber` | `reflect.ts:277-304` | 每个 service 有 owner fiber，owner dispose 时自动 unregister |
| Typed event | `ctx.on/once/emit/parallel/serial/bail/waterfall`，`EventsService.register()` 走 `ctx.fiber.effect()` | `events.ts:254-302`、`events.ts:131-202` | listener 是 fiber effect，owner dispose 时移除 |
| Event propagation | `dispatch()` 按 `Context.filter` 过滤；scope carrier 只向上传播 | `events.ts:203-218`；`packages/core/scope/src/index.ts:170-190`（dsh） | 子 scope 事件可被父 scope 监听，反向不可 |
| Effect registration | `ctx.effect(execute, label)` 立即执行，返回 disposer；支持 generator 收集多个 disposer | `fiber.ts:415-560` | 每个 effect 有明确 owner fiber |
| Effect ownership | disposer 被 `this._disposables.push(wrapper)`；fiber 持有所有 effect | `fiber.ts:450-460`（collect）、`fiber.ts:520`（push）、`fiber.ts:265-297` | `owner(E) = Fiber(P)`，`dispose(P) ⇒ dispose(E)` |
| Disposable | effect 返回的 disposer 单次执行、幂等、可 await | `fiber.ts:427-441`、`fiber.ts:508-559` | 二次 dispose 是 no-op，且返回同一 cleanup task |
| Reverse teardown | 单 effect 内 `disposables.splice(0).reverse()` 顺序执行；fiber 顶层 `DisposableList.clear()` 返回逆序列表 | `fiber.ts:430-441`；`utils.ts:27-31` | 注册序 LIFO；同一 effect 内严格串行逆序 |
| Dependency lifecycle | `provide` disposer 先 `notify` 依赖者、`await Promise.allSettled(fibers.map(f => f.await()))` 再删自身 store | `reflect.ts:299-303` | 被依赖方等待依赖者卸载完成后再销毁 |
| Nested scope | `ctx.plugin()` 在 parent fiber 上注册 child disposer；parent unload 触发 child dispose | `fiber.ts:265-297`（child disposer 注册为 parent effect） | 子 scope 先于父 scope teardown |
| Dynamic unload | `registry.delete(plugin)` → 每个 fiber `dispose()`；`fiber.dispose` 幂等 | `registry.ts:258-268`、`fiber.ts:265-297` | 运行时可按 plugin identity 卸载 |
| Hot reload | `@cordisjs/plugin-hmr` watch 文件 → `registry.delete(plugin)` → 新 fiber 用旧 config 重载 | `packages/hmr/src/index.ts:127-148`、`327-355` | 重载 = dispose + reload，不是原地改状态 |
| Failure rollback | `effect()` setup 抛错时 `finalizeDisposal(dispose)` 清理已收集 disposer 后重抛；`_reload` 失败时 epoch=INACTIVE 并触发 `_unload` | `fiber.ts:520-537`、`fiber.ts:653-673` | 部分初始化也要回滚已创建 effect |
| Traceability | 每个 effect 有 label；`getEffects()` 返回 `EffectMeta` 树 | `fiber.ts:562-572`、`fiber.ts:97-103` | 可枚举某 fiber 的所有 effect |

## 2. Effect Ownership invariant

### 2.1 定义

如果 plugin `P` 创建 effect `E`，Cordis 保证：

```text
owner(E) = Fiber(P)          # 每个 effect 的 wrapper 被 push 进该 fiber 的 _disposables
dispose(P)  ⇒  dispose(E)
```

证据：

- `ctx.on()` → `EventsService.register()` → `this.ctx.fiber.effect(...)`（`events.ts:254-302`）。
- `ctx.provide()` → `this.ctx.fiber.effect(...)`（`reflect.ts:277-304`）。
- `Service` 构造 → `self.ctx.reflect.provide(...)`（`service.ts:42-57`）。
- `tools.register()`（dsh）→ `ScopedLayers.effect()` → `ctx.effect(...)`（`packages/core/tools/src/index.ts:1037-1061`；`packages/core/scope/src/store.ts:226-260`）。
- timer（@cordisjs/plugin-timer）→ `this.ctx.effect(() => { const timer = setInterval(...); return () => clearInterval(timer) })`（`packages/timer/src/index.ts:73-82`）。

### 2.2 多 effect 的 teardown order

单个 effect 内：

```text
E1、E2、E3 按注册序收集
dispose 时: disposables.splice(0).reverse() → E3 → E2 → E1（严格串行 await）
```

证据：`fiber.ts:430-441`（`task = task.then(() => runDisposable(disposable))`）。

fiber 顶层（不同 effect 之间）：

```text
_disposables.clear() 返回逆序列表
但 _unload 用 Promise.all(...) 启动全部 disposer → 启动序逆序、完成序并发
```

证据：`utils.ts:27-31`（`clear()` 返回 `values.reverse()`）；`fiber.ts:675-690`（`Promise.all`）。

> [FACT] 因此 Cordis 的“逆序 teardown”是**单 effect 内严格 LIFO 串行**，跨 effect 是**逆序启动 + 并发完成**。语义等效层必须明确复刻这个粒度，否则依赖“前一个 cleanup 完成后才跑下一个”的代码会得到不同语义。

### 2.3 依赖 teardown ordering

`ctx.provide()` 的 disposer：

```text
delete store[key]
fibers = notify([name])          # 唤醒依赖者
await Promise.allSettled(fibers.map(f => f.await()))
delete this.ctx.fiber.store![name]
```

证据：`reflect.ts:299-303`。

含义：**被依赖方会等待依赖者完成 unload**，然后才把自己从自己的 store 删除。这比单纯 LIFO 更强：teardown 顺序同时受 effect 注册序和依赖图约束。

## 3. plugin P 的资源 ownership 问答

| P 创建的东西 | Cordis 是否原生知道 | 机制 |
|---|---|---|
| event listener | 是 | `ctx.on()` → fiber effect |
| tool | 不直接知道（tool 是 dsh 层概念） | dsh `tools.register()` → `ctx.effect()`，owner = 调用方 fiber |
| service | 是 | `ctx.provide()` → fiber effect |
| middleware / hook | 是（只要用 `ctx.on`/effect 包装） | `EventsService` + effect |
| worker / async task | 不直接知道 | 需要上层用 `ctx.effect` 注册 cancel/join cleanup；DSH 没有把 AnyIO TaskGroup 纳入 Cordis core |
| timer | 不直接知道 | `@cordisjs/plugin-timer` 用 `ctx.effect` 包装 `setInterval/setTimeout` |
| child plugin | 是 | `ctx.plugin()` 本身注册为 parent fiber effect |
| 任意 async resource | 不直接知道 | 需要 `ctx.effect` 返回 async disposer |

## 4. 结论

Cordis 的 ownership 模型是一个**统一的 fiber 级 effect registry**：任何资源只要通过 `ctx.effect()`（或走 effect 的 API）注册，就获得 owner、逆序 teardown、失败继续清理、幂等 dispose 和 traceability。Cordis 不关心资源的具体类型；它只保证“注册了的 effect 一定随 owner 清理”。
