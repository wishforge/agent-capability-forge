#!/usr/bin/env python3
"""Cordis semantic probe — minimal PluginScope/EffectRegistry demo.

Runs on Python 3.11+ stdlib only. The probe tracks tasks directly; the
production semantic layer should use anyio/asyncio TaskGroup for the
cancel/await/aggregate semantics shown in docs/05.

Usage:
    python3 docs/archaeology/python-cordis/prototype/semantic_layer_probe.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class Record:
    resource_id: str
    owner_scope: str
    cleanup_callback: object
    registration_order: int


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def register(self, name: str, fn: object) -> callable:
        if name in self.tools:
            raise ValueError(f"tool {name} already registered")
        self.tools[name] = fn
        return lambda: self.tools.pop(name, None)


class ServiceRegistry:
    def __init__(self) -> None:
        self.services: dict[str, object] = {}

    def register(self, name: str, obj: object) -> callable:
        if name in self.services:
            raise ValueError(f"service {name} already registered")
        self.services[name] = obj
        return lambda: self.services.pop(name, None)


class EventBus:
    def __init__(self) -> None:
        self.listeners: dict[str, list[callable]] = {}

    def subscribe(self, event: str, cb: callable) -> callable:
        self.listeners.setdefault(event, []).append(cb)

        def undo() -> None:
            lst = self.listeners.get(event, [])
            if cb in lst:
                lst.remove(cb)

        return undo

    def emit(self, event: str, *args: object) -> list[object]:
        return [cb(*args) for cb in self.listeners.get(event, [])]


class PluginScope:
    """Minimal Cordis-like scope: every registration is an owned effect."""

    def __init__(self, parent: "PluginScope | None" = None, name: str = "root") -> None:
        self.parent = parent
        self.name = name
        self.children: list[PluginScope] = []
        self._effects: list[Record] = []
        self._tasks: set[asyncio.Task] = set()
        self._disposed = False
        self._order = 0
        if parent is None:
            self.tools = ToolRegistry()
            self.services = ServiceRegistry()
            self.events = EventBus()
            self.records: list[Record] = []
            self.cleanup_events: list[str] = []
        else:
            self.tools = parent.tools
            self.services = parent.services
            self.events = parent.events
            self.records = parent.records
            self.cleanup_events = parent.cleanup_events

    def child(self, name: str) -> "PluginScope":
        scope = PluginScope(self, name)
        self.children.append(scope)
        return scope

    def effect(self, resource_id: str, cleanup: callable) -> callable:
        """Register an arbitrary cleanup; owner is this scope."""
        self._order += 1
        rec = Record(resource_id, self.name, cleanup, self._order)
        self._effects.append(rec)
        self.records.append(rec)
        return cleanup

    def register_tool(self, name: str, fn: object) -> None:
        self.effect(f"tool:{name}", self.tools.register(name, fn))

    def register_service(self, name: str, obj: object) -> None:
        self.effect(f"service:{name}", self.services.register(name, obj))

    def listen(self, event: str, cb: callable) -> None:
        self.effect(f"event:{event}", self.events.subscribe(event, cb))

    def spawn(self, name: str, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        async def stop() -> None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.effect(f"task:{name}", stop)

    def create_timer(self, name: str, delay: float, cb: callable) -> None:
        loop = asyncio.get_running_loop()
        handle = loop.call_later(delay, cb)
        self.effect(f"timer:{name}", lambda: handle.cancel())

    async def open_resource(self, name: str, cm) -> object:
        value = await cm.__aenter__()
        self.effect(f"resource:{name}", lambda: cm.__aexit__(None, None, None))
        return value

    async def dispose(self) -> list[BaseException]:
        """Idempotent dispose: children → tasks → reverse effects."""
        if self._disposed:
            return []
        self._disposed = True
        errors: list[BaseException] = []
        for child in reversed(self.children):  # TEST-11
            errors.extend(await child.dispose())
        tasks = list(self._tasks)  # TEST-08
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for rec in reversed(self._effects):  # TEST-04
            self.cleanup_events.append(rec.resource_id)
            try:
                result = rec.cleanup_callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # TEST-12: keep going
                errors.append(exc)
        return errors


class FakeResource:
    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log

    async def __aenter__(self) -> "FakeResource":
        self.log.append(f"open:{self.name}")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append(f"close:{self.name}")


async def main() -> None:
    checks: list[tuple[str, bool, str]] = []
    root = PluginScope(name="root")
    fs = root.child("filesystem")
    log: list[str] = []
    events_fired: list[str] = []
    worker_stopped = False
    worker_started = asyncio.Event()

    async def worker() -> None:
        nonlocal worker_stopped
        worker_started.set()
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            worker_stopped = True
            raise

    # filesystem.install(): 1 tool, 1 service, 1 listener, 1 worker, 1 timer,
    # 1 async resource, 1 nested sub-capability scope.
    fs.register_tool("fs_read", lambda: "ok")
    fs.register_service("fs_service", object())
    fs.listen("fs/event", lambda: events_fired.append("fs"))
    fs.spawn("fs_worker", worker())
    fs.create_timer("fs_timer", 0.05, lambda: events_fired.append("timer"))
    await fs.open_resource("fs_resource", FakeResource("fs", log))
    sub = fs.child("fs_sub")
    sub.register_tool("fs_sub_tool", lambda: "sub")
    root.register_service("root_service", object())  # parent effect, must run last
    await worker_started.wait()

    # TEST-01 / TEST-02
    checks.append(("TEST-01 every effect has an owner",
                   all(r.owner_scope for r in root.records),
                   f"{len(root.records)} records"))
    checks.append(("TEST-02 owner has a lifecycle scope",
                   all(r.owner_scope in {"root", "filesystem", "fs_sub"} for r in root.records),
                   "PluginScope per owner"))

    # failure cleanup: registered between worker/timer and resource effects
    def boom() -> None:
        raise RuntimeError("cleanup boom")

    fs.effect("failing:boom", boom)

    errors = await root.dispose()  # filesystem.uninstall() == scope.dispose()

    # TEST-03/09/10: owned effects are gone
    checks.append(("TEST-03 disposing owner disposes owned effects",
                   "fs_read" not in root.tools.tools
                   and "fs_sub_tool" not in root.tools.tools
                   and "fs_service" not in root.services.services
                   and "root_service" not in root.services.services,
                   "tools/services removed"))
    checks.append(("TEST-09 event registrations cannot outlive owner",
                   not root.events.listeners.get("fs/event"),
                   "listener removed"))
    checks.append(("TEST-10 tool/service registrations cannot outlive owner",
                   "fs_read" not in root.tools.tools
                   and "fs_service" not in root.services.services,
                   "all gone"))
    checks.append(("TEST-08 async tasks cannot outlive owner",
                   worker_stopped,
                   f"worker_stopped={worker_stopped}"))
    checks.append(("TEST-08b timer cleaned",
                   "timer" not in events_fired,
                   f"events_fired={events_fired}"))
    checks.append(("TEST-08c async resource released",
                   "close:fs" in log,
                   f"log={log}"))

    # TEST-04 deterministic reverse order: parent's root_service must run last
    expected = [
        "tool:fs_sub_tool",
        "failing:boom",
        "resource:fs_resource",
        "timer:fs_timer",
        "task:fs_worker",
        "event:fs/event",
        "service:fs_service",
        "tool:fs_read",
        "service:root_service",
    ]
    checks.append(("TEST-04 teardown order is deterministic",
                   root.cleanup_events == expected,
                   f"events={root.cleanup_events}"))

    # TEST-05 dependency ordering: child scope (dependent) before parent service
    dep_index = root.cleanup_events.index("tool:fs_sub_tool")
    root_index = root.cleanup_events.index("service:root_service")
    checks.append(("TEST-05 dependency teardown respects dependency ordering",
                   dep_index < root_index,
                   "nested dependent disposed before parent service"))

    # TEST-06 idempotent dispose
    await root.dispose()
    checks.append(("TEST-06 cleanup is idempotent",
                   len(root.cleanup_events) == len(expected),
                   "second dispose was a no-op"))

    # TEST-12 failed teardown does not leak remaining effects
    checks.append(("TEST-12 failed teardown does not leak remaining effects",
                   len(errors) == 1
                   and "resource:fs_resource" in root.cleanup_events
                   and "tool:fs_read" in root.cleanup_events,
                   f"errors={[type(e).__name__ for e in errors]}"))

    # TEST-07 partial initialization rollback
    partial = root.child("partial")
    partial.register_tool("partial_tool", lambda: None)
    try:
        partial.register_service("partial_service", object())
        raise RuntimeError("install failed")
    except RuntimeError:
        await partial.dispose()
    checks.append(("TEST-07 partial initialization rollback",
                   "partial_tool" not in root.tools.tools
                   and "partial_service" not in root.services.services,
                   "already-created effects cleaned"))

    # TEST-11 nested scopes teardown before parent (already covered, make explicit)
    fs_index = root.cleanup_events.index("tool:fs_read")
    checks.append(("TEST-11 nested scopes teardown before parent",
                   fs_index > root.cleanup_events.index("tool:fs_sub_tool"),
                   "fs_sub disposed before fs parent effects"))

    failed = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({detail})")
        failed += not ok
    if failed:
        raise SystemExit(f"{failed} check(s) failed")
    print("\nALL INVARIANTS PASS")


if __name__ == "__main__":
    asyncio.run(main())
