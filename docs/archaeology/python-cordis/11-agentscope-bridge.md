# Phase 2-B: AgentScope 2.0 Python Bridge

Date: 2026-08-16

Goal: prove that the Python Cordis Semantic Layer can manage
AgentScope-visible capability effects without modifying AgentScope or
depending on its internals.

## 1. AgentScope actual version

- `agentscope.__version__` = `2.0.2`
- Python = `3.13.9` (miniconda base env)
- Import path = `/Users/david/miniconda3/lib/python3.13/site-packages/agentscope/__init__.py`
- No venv was created: AgentScope was already installed in the working
  Python environment.
- `agentscope.manager` / `agentscope.event_manager` do not exist in 2.0.2
  (checked via `importlib.util.find_spec`).

## 2. Public API used

All AgentScope access in the bridge is public API:

| Surface | API |
|---|---|
| Toolkit | `agentscope.tool.Toolkit`, `Toolkit.tool_groups`, `Toolkit.get_tool`, `Toolkit.get_tool_schemas`, `Toolkit.check_tool_available` |
| Tool | `agentscope.tool.ToolGroup.tools`, `agentscope.tool.FunctionTool` |
| Agent | `agentscope.agent.Agent`, `Agent.reply_stream`, `Agent.reply` |
| Event | `agentscope.event.AgentEvent` (streamed from `Agent.reply_stream`) |
| Model | `agentscope.model.ChatModelBase`, `ChatResponse` (test-only deterministic subclass) |
| State / permission | `agentscope.state.AgentState`, `agentscope.permission.PermissionContext`, `PermissionRule`, `PermissionBehavior` |
| Message | `agentscope.message.UserMsg`, `TextBlock`, `ToolCallBlock` |

The deterministic model (`DeterministicModel`) is a test-only adapter:
AgentScope 2.0.2 has no public mock model.

## 3. Tool bridge

- `register_tool(toolkit, tool)` appends one `ToolBase` to the public
  `ToolGroup.tools` list of the named group (default `"basic"`) and returns
  an idempotent unregister.
- Duplicate tool names are rejected before registration because AgentScope's
  available-tool map silently overwrites same-name tools.
- `dispose()` removes only the exact tool instance this adapter added;
  other tools and the built-in groups remain untouched.
- `Toolkit` 2.0.2 has no public per-tool `unregister` (only `clear()`, which
  would destroy unrelated registrations), so ownership is enforced at the
  adapter level via the public list attribute. This is option A from the
  task: adapter-level registry, not `recreate Toolkit` (B, destroys sibling
  registrations), not wrapper indirection (C, hides the gap), and not a
  private API workaround (D).

## 4. Event bridge

- `EventHub` is an adapter-owned listener registry.
  `subscribe(handler)` registers and returns an idempotent unsubscribe;
  `forward(events)` consumes an `AgentEvent` stream and dispatches to the
  currently registered handlers.
- AgentScope 2.0.2 core has no subscribe/unsubscribe event bus: events are
  delivered to the caller of `Agent.reply_stream()`. The bridge therefore
  forwards a caller-supplied reply stream; it does not patch or wrap the
  agent, and there is no persistent cross-reply listener.
- Cleanup is driven by `EffectRegistry` (`collect("event:fs", unsubscribe)`);
  business code never removes a listener manually.
- After dispose, a new reply stream is forwarded to zero listeners: the
  removed handler is not invoked.

## 5. Worker bridge

- `spawn(coro)` starts one `asyncio.Task` and returns a `Worker` whose
  `stop()` cancels and awaits it (`asyncio.gather(..., return_exceptions=True)`).
- No AnyIO was needed; Python 3.13 stdlib `asyncio` covers cancel/await.
- After dispose the worker task is done, was cancelled exactly once, and
  double dispose does not cancel again.

## 6. Service bridge

- `register_service(services, name, obj)` registers into a plain fake
  service dict and returns an idempotent unregister.
- The semantic layer owns registration through `EffectRegistry`; AgentScope
  is never asked to manage services. This proves service ownership and the
  AgentScope runtime are decoupled: the fake registry is a consumer-side
  resource that capabilities install and dispose.

## 7. Adapter boundary

Files added:

- `docs/archaeology/python-cordis/kernel/adapters/__init__.py`
- `docs/archaeology/python-cordis/kernel/adapters/agentscope.py`
- `docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py`
- `docs/archaeology/python-cordis/11-agentscope-bridge.md`

The test lives under `kernel/tests/` next to `test_invariants.py`, matching
the existing Phase 2-A layout instead of a new top-level `tests/` directory.

Dependency direction:

```text
semantic_layer
    -> adapters.agentscope
        -> agentscope (public API only)
```

`rg agentscope kernel/semantic_layer` returns nothing; `core.py` is
AgentScope-independent and was not modified.

## 8. Public API gaps

| Gap | Impact | Bridge decision |
|---|---|---|
| `Toolkit` has no per-tool `unregister` (only `clear()`) | Cannot reversibly register a single tool through a dedicated API | Adapter-owned cleanup over the public `ToolGroup.tools` list |
| Core has no event subscribe/unsubscribe bus | No persistent listener API; events are only visible inside `Agent.reply_stream()` | `EventHub` listener registry + per-stream forwarding |
| No public mock/deterministic model | Cannot test the agent loop without a network model | Test-only `ChatModelBase` subclass (recorded as test-only) |

No private underscore API was used and no AgentScope source was modified.

## 9. Semantic preservation

- Phase 1 probe: `ALL INVARIANTS PASS` (14/14 checks).
- Phase 2-A semantic tests: 12/12 `ok`.
- Phase 2-B bridge tests: 7/7 `ok`.

Phase 2-B only adds files; the Phase 2-A kernel, prototype, and docs were not
modified. The covered semantics still pass unchanged: strict LIFO inside a
batch, reverse batch launch with sibling concurrency, rollback, nested scope
teardown before parent, idempotent dispose, and cleanup-failure continuation.

## 10. No-ghost verification

| Test | Verifies |
|---|---|
| `test_tool_cannot_outlive_scope` | tool visible after install; `get_tool` returns `None` and schema list is empty after dispose |
| `test_event_cannot_outlive_scope` | listener observes streamed events; after dispose listener list is empty and a new stream does not invoke it |
| `test_worker_cannot_outlive_scope` | worker task running after install; done and cancelled after dispose |
| `test_service_cannot_outlive_scope` | service present after install; absent after dispose |
| `test_capability_dispose_is_complete` | all four resource kinds gone after one `capability.dispose()` |
| `test_double_install_and_double_dispose` | second install rejected with no duplicates; second dispose is a no-op |
| `test_agent_invokes_tool_then_dispose_removes_it` | AgentScope Agent invokes the tool (1 call), then after dispose the tool is gone and cannot be invoked again |

## Verdict

**PASS**

Semantic Layer 可以在不修改 AgentScope 的情况下管理 AgentScope-visible
capability effects。

Verification commands:

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py -v
```
