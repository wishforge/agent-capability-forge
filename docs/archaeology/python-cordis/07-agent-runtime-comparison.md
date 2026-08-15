# Agent Runtime 对比：NoneBot2

## 1. 为什么选 NoneBot2

四个候选（OpenAI Agents Python / LangGraph / PydanticAI / NoneBot2）中，NoneBot2 是唯一把 **plugin loading + event 响应 + app lifecycle** 都做在源码里的 Python 框架，最接近 Cordis 的“插件运行时”定位。OpenAI Agents / LangGraph / PydanticAI 更偏 agent 执行图，plugin/lifecycle 语义更弱，因此只作为参照。

## 2. NoneBot2 插件模型

### 2.1 加载

```text
PluginManager.load_plugin(name)
  → importlib.import_module
  → PluginLoader.exec_module
    → _new_plugin(...)             # 创建 Plugin 对象，写入全局 _plugins
    → exec 模块代码
    → 失败时 _revert_plugin(plugin)
```

证据：

- `nonebot/plugin/manager.py:156-199`（load_plugin）。
- `nonebot/plugin/manager.py:244-265`（exec_module 创建 plugin、失败回滚）。
- `nonebot/plugin/__init__.py:96-133`（_new_plugin / _revert_plugin）。

### 2.2 父子插件

`Plugin` 有 `parent_plugin` 和 `sub_plugins`（`plugin/model.py:67-92`），`id_` 是 `parent:id`（`model.py:88-91`）。但子插件只是记录，卸载父插件不会级联卸载子插件（`plugin/__init__.py:127-133` 只在导入失败时移除单个 plugin）。

### 2.3 卸载

**没有 unload。** `rg "unload" nonebot/plugin` 无命中；`_plugins` 只在导入失败时 `_revert_plugin`。Matcher 注册进全局 `matchers` 后没有 plugin 级自动移除；只有手动 `Matcher.destroy()` 或 `temp=True` 触发后自毁（`internal/matcher/matcher.py:323-330`），且 `destroy` 只删 matcher，不关停插件资源。

## 3. 生命周期

### 3.1 app 级 Lifespan

```text
Lifespan.startup():
    创建 anyio TaskGroup
    按序跑 on_startup, on_ready

Lifespan.shutdown():
    逆序跑 on_shutdown（reversed）
    task_group.cancel_scope.cancel()
    await task_group.__aexit__(...)   # suppress 异常
```

证据：`internal/driver/_lifespan.py:58-92`。

这是**全局**生命周期，不是 plugin 级：

- `on_startup/on_shutdown` 是全局列表（`_lifespan.py:36-46`）。
- 没有按 plugin 归属的 cleanup registry。

### 3.2 Driver hooks

```text
Driver._adapters: ClassVar[dict[str, Adapter]]   # 全局适配器注册表
Driver.on_bot_connect/on_bot_disconnect           # 写入 class-level set
```

证据：`internal/driver/abstract.py:61`、`137-165`。

没有 `unregister_adapter`、没有 hook 的自动移除。

## 4. 与 Cordis 语义对照

| Cordis 语义 | NoneBot2 |
|---|---|
| Plugin | ✓（模块即插件，有 parent/sub） |
| Plugin-owned Scope | ✗ |
| Context | ✗ |
| DI（生命周期容器） | △（Dependent 参数解析，无容器） |
| Service registry | ✗（适配器是全局 dict） |
| Event listener ownership | ✗（Matcher 全局注册，手动 destroy） |
| Effect registry | ✗ |
| 自动 reverse teardown | △（仅 app shutdown 的 on_shutdown 逆序） |
| Dependency lifecycle | ✗（require 只保证加载） |
| Dynamic unload | ✗ |
| Hot reload | ✗ |
| Background task lifecycle | ✓（app 级 TaskGroup） |
| Failure rollback | △（模块导入失败回滚注册） |

## 5. 结论

NoneBot2 解决了“Python 插件怎么加载、事件怎么响应、app 怎么启动/停止”，但**没有解决** Cordis 的核心问题：per-plugin scope 与 effect ownership。把它作为 Agent Runtime 上层是合适的；作为 Cordis-equivalent kernel 不够。

## 6. 其他 Agent Runtime 的简短判断

`[INFERENCE]`（未逐文件考古，基于公开 API 定位）：

- **OpenAI Agents Python**：以 Agent/Runner/Handoff 为中心，tool 与 hook 是执行期对象，无 plugin lifecycle。
- **LangGraph**：以 StateGraph/Node/Checkpoint 为中心，无 plugin scope/effect registry。
- **PydanticAI**：以 Agent/Tool/Dependency 为中心，无 plugin 生命周期。

如果后续需要更精确证据，这三个仓库可以按同样方法考古；本轮不展开。
