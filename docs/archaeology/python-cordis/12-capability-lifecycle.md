# Phase 2-C: Capability Lifecycle Contract Validation

Date: 2026-08-16

Goal: prove that Semantic Layer + AgentScope Adapter + Capability Lifecycle
already form a usable Agent Capability Runtime lifecycle contract — without
implementing DSH, a plugin loader, session/event sourcing, or a persistent
event bus.

## 1. Validation boundary

The `Capability` wrapper is **test-local** (defined in
`kernel/tests/test_capability_lifecycle.py`), not a production primitive.
It exists only to exercise the runtime contract on top of:

| Primitive | Role in the contract |
|---|---|
| `PluginScope` | exactly one owner scope per capability; owns every effect |
| `EffectRegistry` (`scope.effect(collect)`) | every runtime effect is registered and reclaimed here |
| `DependencyLifecycle` | provider/dependent ordering; dependent cannot be finalized while dependents are active |
| `adapters.agentscope` | AgentScope-visible effects: `register_tool`, `EventHub.subscribe`, `spawn`, `register_service` |

No production code was modified: `semantic_layer/core.py`, the AgentScope
adapter, the prototype, existing archaeology docs, and AgentScope source are
untouched.

## 2. Capability state machine

```text
CREATED -> INSTALLING -> ACTIVE
CREATED -> INSTALLING -> FAILED   (install raised)
ACTIVE  -> DISPOSING  -> DISPOSED
```

Illegal transitions raise `RuntimeError`; `dispose()` is idempotent and
coalesces concurrent callers onto one physical teardown task.

`Capability.dispose()` never calls cleanup itself: it only asks
`PluginScope.dispose()` (no dependencies) or
`DependencyLifecycle.release(identity, scope.dispose)` (with dependencies).
All tool/event/worker/service cleanup is registered as effects by the
capability's `_install()` and reclaimed by the scope.

One test-only detail: `_OwnedScope` (a `PluginScope` subclass in the test
file) mirrors scope disposal back into capability state. This is needed
because `DependencyLifecycle` disposes a dependent **scope** directly
(provider -> dependent teardown), bypassing the dependent capability's own
`dispose()` wrapper; without the mirror, the dependent capability would show
`ACTIVE` while its scope is already `DISPOSED`.

## 3. EchoCapability: all effect kinds through EffectRegistry

`EchoCapability.install()` performs exactly four registrations inside one
`scope.effect("echo.install", setup)` batch:

1. AgentScope tool — `register_tool(toolkit, FunctionTool(echo))`
2. Event/stream hook — `hub.subscribe(listener)`
3. Background worker — `spawn(worker)` + `worker.stop` cleanup
4. Service — `register_service(services, "echo", self)`

`dispose()` reclaims all four through the scope; the capability contains no
manual `unregister`/cancel/removal calls.

## 4. Dependency teardown

`B` (provider) is installed first, then `A` (dependent) registers
`deps.register_dependent("B", A.scope)` during install.

`B.dispose()` runs `DependencyLifecycle.release("B", B.scope.dispose)`:

```text
wait for A.dispose
  -> A effects cleaned
  -> A fully DISPOSED
run B finalizer (B scope effects)
  -> B DISPOSED
```

The test blocks A's cleanup mid-flight and verifies B's finalizer has not run
while A is still `DISPOSING`; the final order is
`A:cleanup:start -> A:cleanup:end -> B:finalizer`.

## 5. Failure / rollback

`FailingCapability` completes tool, event, worker and service registration,
then raises. `PluginScope.effect` rolls back already-collected effects in
reverse LIFO order and re-raises the original exception; the capability
transitions to `FAILED`. Verified after failure:

- no ghost tool
- no ghost event listener
- no ghost worker (task done, cancellation observed)
- no ghost service
- original exception object preserved (`cm.exception is cap.boom`)

## 6. Replace / reinstall

Reinstall is validated as a fresh capability instance with a fresh scope
(no plugin loader was requested, so there is no loader-owned reinstall
path). After `install -> dispose -> install` with the same Toolkit, EventHub
and service dict:

- no duplicate tool / listener / service
- first worker is stale/done, second worker is a new live task
- `cap2.scope is not cap1.scope` (fresh scope identity)
- effect objects and orders are fresh (distinct `Effect` objects, registry
  order restarted by the fresh scope)

## 7. Concurrent dispose

`asyncio.gather(cap.dispose(), cap.dispose(), cap.dispose())` returns
`[[], [], []]`; `physical_disposes == 1`; both the capability and its scope
keep exactly one shared dispose task. All callers await the same completion.

## 8. AgentScope visibility E2E

Same `Agent` instance, no manual refresh:

```text
install cap1 -> agent calls echo tool   -> success (cap1.calls == 1)
dispose cap1 -> Toolkit.get_tool -> None, schema list empty
install cap2 -> same agent calls echo tool again -> success (cap2.calls == 1)
```

AgentScope's `Toolkit.get_tool_schemas()` reads the live public tool list on
every reply, so the removed tool is gone and the reinstalled tool is visible
immediately.

## 9. Lifecycle invariants

| ID | Invariant | Verified by |
|---|---|---|
| CAP-01 | Capability has exactly one owner Scope | echo install test (`effect.owner is cap.scope`) |
| CAP-02 | ACTIVE capability has live scope | state machine + echo install tests |
| CAP-03 | every runtime effect belongs to capability scope | echo install test |
| CAP-04 | DISPOSED capability owns zero live effects | dispose test (registries empty, effects CLEANED) |
| CAP-05 | dependency cannot finalize before dependents | dependency teardown test |
| CAP-06 | failed install leaves zero live effects | failure/rollback test |
| CAP-07 | reinstall gets fresh scope/effect identity | reinstall test |
| CAP-08 | concurrent dispose has one physical teardown | concurrent dispose test |
| CAP-09 | disposed capability cannot register new effects | sealed-scope test |
| CAP-10 | capability effects cannot outlive AgentScope adapter | dispose + AgentScope E2E tests |

## 10. Test suite

`kernel/tests/test_capability_lifecycle.py` — 9 tests:

1. `test_state_machine_rejects_invalid_transitions`
2. `test_echo_install_registers_all_effects_through_effect_registry`
3. `test_dispose_reclaims_every_effect_through_scope`
4. `test_dependency_dispose_waits_for_dependent_before_finalizer`
5. `test_failed_install_rolls_back_all_effects_and_preserves_exception`
6. `test_reinstall_gets_fresh_scope_and_fresh_effect_identity`
7. `test_concurrent_dispose_has_one_physical_teardown`
8. `test_disposed_capability_cannot_register_new_effects`
9. `test_agentscope_visibility_install_dispose_reinstall`

## 11. Verification

```bash
python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_invariants.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_agentscope_bridge.py -v
python3 -m unittest docs/archaeology/python-cordis/kernel/tests/test_capability_lifecycle.py -v
```

Results:

| Suite | Result |
|---|---|
| Phase 1 probe | `ALL INVARIANTS PASS` (14/14 checks) |
| Phase 2-A semantic tests | 12/12 ok |
| Phase 2-B AgentScope bridge tests | 7/7 ok |
| Phase 2-C capability lifecycle tests | 9/9 ok |

`git status --short`: only pre-existing `.gitignore` modification plus the
already-untracked `docs/archaeology/` and `research/control-plane-loop/`
trees. The archaeology tree is untracked, so `git diff --stat` reports
nothing for it; the two new files in this phase are
`12-capability-lifecycle.md` and
`kernel/tests/test_capability_lifecycle.py`. Existing python-cordis files
were verified byte-identical against a SHA snapshot taken before this phase.
No business code, prototype, or AgentScope source was touched.

## Verdict

**PASS**

## Contract boundaries

- **Semantic contract**: `PluginScope` + `EffectRegistry` +
  `DependencyLifecycle` already provide ownership, rollback, dependency
  ordering, idempotent dispose and single-teardown coalescing. The missing
  piece is *not* semantic: a capability-facing wrapper is needed only to add
  the `CREATED/INSTALLING` states and to mirror scope disposal back into
  capability state (test-local `_OwnedScope`).
- **AgentScope contract**: the 2-B adapter is sufficient. Tools are added and
  removed through the public `ToolGroup.tools` list; events are adapter-owned
  `EventHub` subscriptions; workers are adapter-owned `spawn` tasks; services
  are plain registered values. No AgentScope modification, no private API,
  no `Toolkit.unregister` patch.
- **Capability contract**: `identity + scope + dependencies + install() +
  dispose()` is a usable minimal contract today, with one explicit ceiling:
  reinstall is represented by a fresh instance/scope because no plugin
  loader exists yet. A loader-owned reinstall (and dependency registration
  rollback on failed dependent install) is the boundary of the next phase.
