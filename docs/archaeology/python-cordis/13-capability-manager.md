# Phase 2-D: Plugin / Capability Manager

Date: 2026-08-16

Goal: promote the Phase 2-C Capability scaffold into a formal
`PluginManager` that owns descriptor registration and dependency-aware
lifecycle orchestration, while keeping the semantic layer
(`PluginScope` / `EffectRegistry` / `DependencyLifecycle`) and the AgentScope
adapter boundary intact.

## 1. New files

| File | Role |
|---|---|
| `kernel/capability.py` | `CapabilityDescriptor` + runtime `Capability` (one installation generation, owned scope, strict state machine, dispose coalescing) |
| `kernel/manager.py` | `CapabilityRecord` registry + `PluginManager` (install/unload/reinstall, dependency chain, rollback, concurrency coalescing) |
| `kernel/tests/test_capability_manager.py` | 12 contract tests |
| `13-capability-manager.md` | this document |

One additive change to the semantic layer:
`DependencyLifecycle.unregister_dependent()` — removes a dependent scope
registration idempotently so a failed/unloaded capability leaves no stale
dependency edge. Phase 1 semantics are unchanged (all 12 invariant tests and
the 14-check probe still pass).

## 2. Data model

```python
@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    version: str
    factory: Callable[[PluginScope], Any]   # returns object with async install()
    dependencies: tuple[str, ...] = ()

@dataclass
class CapabilityRecord:      # registry metadata
    descriptor: CapabilityDescriptor
    installation_generation: int = 0
    instance: Capability | None = None
    scope / state / dependencies / dependents  # properties over instance
```

`version` is identity/reinstall metadata only; no semver resolver.

## 3. State machine

```text
REGISTERED -> INSTALLING -> ACTIVE
INSTALLING -> FAILED
ACTIVE | INSTALLING | FAILED -> DISPOSING -> DISPOSED
```

`record.state` is `REGISTERED` before the first install; `Capability` starts
at `INSTALLING`. `DISPOSED -> ACTIVE` is impossible on the same instance:
reinstall increments the record generation and creates a fresh `Capability`,
fresh `_OwnedScope`, and fresh `EffectRegistry`.

## 4. Dependency resolution

For `A -> B -> C`, `install(A)` resolves a dependencies-first chain
`[C, B, A]`; `unload(A)` disposes `A`, then cascades only to dependencies
whose `dependents` set is empty:

```text
install: C -> B -> A
unload:  A -> B -> C
```

Shared providers are protected: with `A -> B` and `X -> B`, `unload(B)`
raises `RuntimeError` while `B.dependents == {"A", "X"}`. No silent cascade.

## 5. Failed dependency rollback

If `C` and `B` install successfully and `A` fails, `_do_install` rolls back
every capability created by that install in strict reverse order. The
dependent edge removal in `Capability._dispose` plus
`DependencyLifecycle.unregister_dependent` make the cascade exactly
`A -> B -> C`. Verified post-failure:

- no ACTIVE record
- every scope `DISPOSED`, every effect `CLEANED`
- `manager.deps._dependents == {}` (no stale dependency registration)
- original exception re-raised to the caller

## 6. Reinstall

`install -> unload -> install` produces generation 1 then generation 2:

- `record.installation_generation` increments
- new `Capability`, new scope, new `EffectRegistry` (effect orders restart)
- no reused tool / event listener / worker / service
- old worker task is done, new worker is live

`reinstall(id)` is `unload(id)` + `install(id)`.

## 7. Concurrency

`install(A)` / `install(A)` coalesce onto one per-id install task: one
factory call, one ACTIVE instance, both callers await the same result.

`unload(A)` / `unload(A)` coalesce onto one per-id unload task:
`physical_disposes == 1`, both callers await the same completion.

Rollback skips a created capability that still has active dependents, so a
concurrent owner of a shared provider is not destroyed.

## 8. AgentScope boundary

`PluginManager` and `Capability` never import AgentScope:

```text
PluginManager -> Capability -> PluginScope -> EffectRegistry
                                              -> adapters.agentscope (public API)
```

`rg agentscope kernel/capability.py kernel/manager.py` returns nothing, and
`kernel/semantic_layer` still has no capability/manager dependency.

## 9. Tests

`kernel/tests/test_capability_manager.py` — 12 tests:

1. `test_manager_register`
2. `test_manager_install`
3. `test_dependency_install_order`
4. `test_dependency_unload_order`
5. `test_unload_with_active_dependents`
6. `test_failed_dependency_rollback`
7. `test_reinstall_new_generation`
8. `test_concurrent_install_single_instance`
9. `test_concurrent_unload_single_dispose`
10. `test_no_ghost_capability`
11. `test_no_ghost_effects`
12. `test_agent_visibility_after_reinstall`

## 10. Verification

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_capability_manager.py -v
```

Results:

| Suite | Result |
|---|---|
| Phase 1 probe | `ALL INVARIANTS PASS` (14/14) |
| Phase 2-A semantic tests | 12/12 ok |
| Phase 2-B AgentScope bridge tests | 7/7 ok |
| Phase 2-C capability lifecycle tests | 9/9 ok |
| Phase 2-D capability manager tests | 12/12 ok |

## Verdict

**PASS**

Python Semantic Layer 已具备 Runtime-managed Capability 的最小完整生命周期。
