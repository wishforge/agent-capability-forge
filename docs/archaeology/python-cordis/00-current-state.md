# Python Cordis Semantic Kernel：源码考古 — 当前状态

> 目标不是写一个新框架，而是验证 Python 现有开源项目是否已经具备足够的 runtime primitives，可以组合出语义上等效于 Cordis 的 Semantic Kernel。

## 1. 研究范围与证据基线

| 项目 | 来源 | commit / 版本 | 证据位置 |
|---|---|---|---|
| Cordis（upstream） | `cordiverse/cordis` | `8cc9e33fab69e2d0476d126baaf2acb24e6a6ab4`（core 4.0.0-rc.8） | `packages/core/src/{context,fiber,events,reflect,registry,service,utils}.ts` |
| Cordis（DeepSeek vendored fork） | `deepseek-harness/vendor/cordis` | `47f943859bef60e4160492346772ded9b24f765a`（4.0.1） | `vendor/cordis/src/*.ts` |
| DeepSeek Harness 上层（dsh） | 同一 checkout | 同上 | `packages/core/scope/src/*.ts`、`packages/core/tools/src/index.ts` |
| Dishka | `reagento/dishka` | `79057588a1fa5fd664ee6687b5492e6942ca805b` | `src/dishka/{async_container,container,registry,provider,factory_compiler,entities/scope}.py` |
| contextlib.AsyncExitStack | CPython 3.13（本机 miniconda） | 3.13 | `contextlib.py:631-766` |
| AnyIO | 本机 site-packages | 4.13.0 | `anyio/_backends/_asyncio.py`、`anyio/abc/_tasks.py` |
| Pluggy | 本机 site-packages | 1.5.0 | `pluggy/_manager.py`、`pluggy/_callers.py` |
| NoneBot2 | `nonebot/nonebot2` | `f521614c0d02508512580338fe8d09ae807f619c`（2.5.0） | `nonebot/plugin/*.py`、`nonebot/internal/driver/_lifespan.py` |
| @cordisjs/plugin-timer | upstream checkout | 1.1.2 | `packages/timer/src/index.ts` |
| @cordisjs/plugin-hmr | upstream checkout | — | `packages/hmr/src/index.ts` |

## 2. 执行方式

1. 先读 Cordis core 源码，建立 ground truth（Fiber / Effect / Event / Service / Registry）。
2. 用 DeepSeek Harness vendored fork 与 upstream 做 diff，确认 fork 没有改变核心语义（仅加了 effect inertia 与 plugin-disposed 通知，`_unload`、`provide` disposer、effect 链与 upstream 一致）。
3. 分别考古 Dishka、AsyncExitStack、AnyIO、Pluggy、NoneBot2，全部以源码为准。
4. 对 Dishka 用克隆源码做了一次真实运行验证（LIFO、错误聚合、外部副作用不被跟踪）。
5. 构造一个极小的 semantic probe（`prototype/semantic_layer_probe.py`），验证 12 条 invariant。
6. 第一阶段不修改任何业务源码，不实现完整框架。

## 3. 证据等级

- `[FACT]`：源码/运行验证直接证明。
- `[INFERENCE]`：由多个 FACT 推导，无直接源码证明。
- `[NOT_FOUND]`：明确搜索但没有找到实现。
- `[UNKNOWN]`：源码无法证明。

## 4. 当前状态

- Cordis ground truth：完成。
- Python primitives：完成（Dishka / AsyncExitStack / AnyIO / Pluggy / NoneBot2）。
- Semantic matrix：见 `01-cordis-semantic-matrix.md`。
- Dishka 考古：见 `03-dishka-archaeology.md`，含真实运行验证。
- 语义等效测试与最小 kernel 设计：见 `08`、`09`。
- 推荐结论：见 `10-recommendation.md`。
