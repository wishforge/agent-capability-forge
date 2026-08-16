# 24 — Phase 5-B.1 Report: Backend-Neutral Runtime Assembly Refactor

> 阶段结论：**PASS**（仅 Backend Assembly Seam；不实现 Codex Adapter）
> 基线：Phase 5-A `21-backend-portability-contract.md`（BP-01 PARTIAL）+ Phase 5-B `23-codex-adapter-boundary.md`
> 变更：`runtime/model_adapter.py` 拆分为 backend-neutral 契约；新增
> `runtime/backend/adapters/agentscope.py`；新增 `runtime/tests/test_phase5b1.py`；
> 更新 `runtime/tests/test_phase4d.py` import；新增本报告

---

## 1. 原 Seam（Before）

```text
runtime.py
    └── model_adapter.py            # 顶层 import agentscope
            └── AgentScopeModelAdapter
```

`runtime.py` 直接 `from model_adapter import ...`，而 `model_adapter.py` 顶层
`import agentscope`。因此 AgentRuntime / RuntimeCoordinator 的编译与运行依赖
具体 AgentScope backend，违反 BP-01（`21-backend-portability-contract.md` §2.1）。

## 2. 新 Boundary（After）

```text
runtime.py
    └── model_adapter.py            # backend-neutral: contract + ScriptedModelAdapter
            ^
            | constructor injection
            |
caller ── backend/adapters/agentscope.py   # AgentScope 2.0.2 backend adapter
            └── agentscope (public API only)
```

`runtime.py` 现在只依赖 `model_adapter` 中的 neutral contract：
`ModelAdapter` / `ModelChunk` / `ModelFinal` / `ModelToolCallEvent` /
`ModelToolResultEvent` / `ModelRequestError` / `ScriptedModelAdapter`。
AgentScope 具体实现整体移到 `backend/adapters/agentscope.py`，从
`model_adapter` 导入 neutral 类型，不再反向依赖。

依赖方向（Dependency Direction）：

- `runtime.py -> model_adapter.py`（neutral，无 backend import）
- `backend/adapters/agentscope.py -> model_adapter.py + agentscope`（backend 向 neutral 依赖）
- runtime 不 import `agentscope` / `AgentScopeModelAdapter`，无
  `if backend == "agentscope"` 分支。

## 3. DI Construction

`AgentRuntime.__init__(adapter=...)` 与 `RuntimeCoordinator.__init__(model=...)`
不变：调用方构造具体 adapter 后注入。`RuntimeCoordinator` 对无 `stream`
属性的 Phase 4-A callable 仍自动包 `ScriptedModelAdapter`。未引入任何 DI
framework，stdlib 即可。

Future Codex Adapter 可以新增 `backend/adapters/codex.py` 实现同一
`ModelAdapter` 并注入，不需要修改 `runtime.py`（本阶段不实现）。

## 4. 兼容性结果

| Suite | Before | After |
| --- | --- | --- |
| Phase 1 probe | 14/14 | 14/14 |
| Phase 2（kernel tests） | 40/40 | 40/40 |
| Phase 4-A | 15/15 | 15/15 |
| Phase 4-B | 14/14 | 14/14 |
| Phase 4-C | 20/20 | 20/20 |
| Phase 4-D | 13/13 | 13/13 |
| Phase 5-B.1（新增） | — | 4/4 |

验证命令：

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py \
  docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py \
  docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -q
python3 -m unittest discover -s docs/archaeology/deepseek-harness/runtime/tests \
  -p 'test_phase*.py' -q
```

新增 4 个 seam 测试：

1. `test_runtime_accepts_model_adapter` — 任意实现 neutral 接口的 adapter 可注入。
2. `test_runtime_has_no_agentscope_import` — 源码 AST + 干净子进程双检查：
   runtime / neutral model_adapter 无 agentscope import，import runtime 不加载
   agentscope。
3. `test_scripted_backend_still_passes` — ScriptedModelAdapter + Phase 4-A
   RuntimeCoordinator 自动包装均通过。
4. `test_agentscope_backend_still_passes` — 移动后的 AgentScopeModelAdapter
   仍通过真实 AgentScope 2.0.2 单轮 turn。

## 5. Why This Is Not Semantic Change

- 只移动类与 import 边界，未改动任何 runtime loop / event / adapter 逻辑；
  `AgentScopeModelAdapter` 本体逐行搬移到新文件。
- Session / Turn / Step / Tool Waterfall / EventStore / Surface / Compaction /
  Replay / Recovery / Initiator / Capability Ownership 均未触碰。
- 既有 Phase 1/2/4 测试除 `test_phase4d.py` 的一行 import 路径外零修改，全部 PASS。
- 不实现 Codex Adapter、Codex process、ExecutionAttempt、Lossiness metadata，
  不修改 Codex / AgentScope / semantic contracts。

## 6. Final Status

**PASS** — Backend Assembly Seam 修复完成：`runtime.py` 只依赖
`ModelAdapter` neutral interface，AgentScope 实现位于
`backend/adapters/agentscope.py`，可注册后续 Codex Adapter 而无需修改
`runtime.py`。按阶段指令，完成后停止，不进入 Phase 5-C。
