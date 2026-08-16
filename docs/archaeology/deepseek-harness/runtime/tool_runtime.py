"""Phase 4-A Tool Waterfall: pre-execute -> approval -> guard -> execute ->
post-execute -> finalize -> materialize -> tool/result.

No tool-level retry: DSH TOOL_RETRY = NOT FOUND (15 §7). Tool failure is
materialized as ToolResult(is_error=True), never as Step/Turn failure.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable

from events import TOOL_CALL, TOOL_RESULT, SessionEvent
from extensions import (
    ADAPTER_DERIVED,
    BackendEventRef,
    BackendMetadata,
    InitiatorRef,
    OwnerRef,
)
from initiator import current_initiator
from turn_step import ExecutionContext

ALLOW = "allow"
DENY = "deny"
ASK = "ask"


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict
    root_call_id: str | None = None
    parent_call_id: str | None = None
    backend_event_ref: BackendEventRef | None = None
    backend_metadata: BackendMetadata | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    error_code: str | None = None
    additional_contexts: tuple[str, ...] = ()
    concludes_turn: bool = False


@dataclass(slots=True)
class ToolRegistration:
    name: str
    fn: Callable[..., Any]
    owner: str
    timeout_ms: float | None = None
    pre_execute: Callable[..., Any] | None = None
    guard: Callable[..., Any] | None = None
    post_execute: Callable[..., Any] | None = None
    finalize: Callable[..., Any] | None = None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class ToolRuntime:
    def __init__(self, approval: Callable[..., Any] | None = None) -> None:
        self._tools: dict[str, ToolRegistration] = {}
        self._cancelled: dict[str, asyncio.Event] = {}
        self.approval = approval

    def register(self, registration: ToolRegistration) -> Callable[[], None]:
        if registration.name in self._tools:
            raise ValueError(f"tool {registration.name!r} already registered")
        self._tools[registration.name] = registration

        def unregister() -> None:
            self._tools.pop(registration.name, None)

        return unregister

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolRegistration | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def cancel(self, call_id: str) -> None:
        self._cancelled.setdefault(call_id, asyncio.Event()).set()

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
        registration = self._tools.get(call.name)
        initiator_ref = self._current_initiator_ref()
        owner_ref = (
            OwnerRef(owner_type="capability", owner_id=registration.owner)
            if registration is not None
            else None
        )
        payload = {
            "call_id": call.call_id,
            "name": call.name,
            "arguments": call.arguments,
            "root_call_id": call.root_call_id,
            "parent_call_id": call.parent_call_id,
        }
        if initiator_ref is not None:
            payload["initiator_ref"] = asdict(initiator_ref)
        if owner_ref is not None:
            payload["owner_ref"] = asdict(owner_ref)
        if call.backend_event_ref is not None:
            payload["backend_event_ref"] = asdict(call.backend_event_ref)
        if call.backend_metadata is not None:
            payload["backend_metadata"] = asdict(call.backend_metadata)
        call_event = ctx.store.append(
            SessionEvent(
                0,
                TOOL_CALL,
                ctx.session.session_id,
                turn_id=ctx.turn.turn_id,
                step_id=ctx.step.step_id,
                payload=payload,
            ),
        )
        ctx.step.tool_calls.append(call)
        if registration is None:
            result = ToolResult(
                call.call_id,
                f"unknown tool: {call.name}",
                is_error=True,
                error_code="UNKNOWN_TOOL",
            )
        else:
            try:
                result = await self._waterfall(registration, call, ctx)
            finally:
                self._cancelled.pop(call.call_id, None)
        result_payload = {
            "tool_call_id": result.tool_call_id,
            "content": result.content,
            "is_error": result.is_error,
            "error_code": result.error_code,
        }
        if initiator_ref is not None:
            result_payload["initiator_ref"] = asdict(initiator_ref)
        if owner_ref is not None:
            result_payload["owner_ref"] = asdict(owner_ref)
        ctx.store.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                ctx.session.session_id,
                turn_id=ctx.turn.turn_id,
                step_id=ctx.step.step_id,
                payload=result_payload,
                source_event_seqs=(call_event.seq,),
            ),
        )
        return result

    @staticmethod
    def _current_initiator_ref() -> InitiatorRef | None:
        initiator = current_initiator()
        if initiator is None:
            return None
        return InitiatorRef(ref=initiator.agent_id, source=ADAPTER_DERIVED)

    async def _waterfall(
        self,
        reg: ToolRegistration,
        call: ToolCall,
        ctx: ExecutionContext,
    ) -> ToolResult:
        signal = self._cancelled.setdefault(call.call_id, asyncio.Event())
        result: ToolResult | None = None

        decision = ALLOW
        if reg.pre_execute is not None:
            decision = await _maybe_await(reg.pre_execute(call, ctx))
        if decision == ASK:
            granted = await self._approve(call, ctx)
            if not granted:
                result = ToolResult(
                    call.call_id,
                    "approval rejected",
                    is_error=True,
                    error_code="APPROVAL_REJECTED",
                )
        elif decision == DENY:
            result = ToolResult(
                call.call_id,
                "denied by pre-execute",
                is_error=True,
                error_code="DENIED",
            )

        if result is None and reg.guard is not None:
            reason = await _maybe_await(reg.guard(call, ctx))
            if reason:
                result = ToolResult(
                    call.call_id,
                    reason,
                    is_error=True,
                    error_code="GUARD_DENIED",
                )

        if result is None:
            if signal.is_set():
                result = ToolResult(
                    call.call_id,
                    "cancelled before dispatch",
                    is_error=True,
                    error_code="ABORTED_BEFORE_DISPATCH",
                )
            else:
                result = await self._execute(reg, call, ctx, signal)

        if reg.post_execute is not None:
            try:
                replaced = await _maybe_await(reg.post_execute(call, result, ctx))
                if replaced is not None:
                    result = replaced
            except Exception as exc:
                result = ToolResult(
                    call.call_id,
                    f"post-execute failed: {exc}",
                    is_error=True,
                    error_code="POST_EXECUTE_ERROR",
                )

        if reg.finalize is not None:
            try:
                finalized = await _maybe_await(reg.finalize(call, result, ctx))
                if finalized is not None:
                    result = finalized
            except Exception as exc:
                result = ToolResult(
                    call.call_id,
                    f"finalize failed: {exc}",
                    is_error=True,
                    error_code="FINALIZE_ERROR",
                )

        # DSH: failure can never carry concludesTurn (15 §10).
        if result.is_error and result.concludes_turn:
            result = replace(result, concludes_turn=False)
        return result

    async def _approve(self, call: ToolCall, ctx: ExecutionContext) -> bool:
        if self.approval is None:
            return True
        return bool(await _maybe_await(self.approval(call, ctx)))

    async def _execute(
        self,
        reg: ToolRegistration,
        call: ToolCall,
        ctx: ExecutionContext,
        signal: asyncio.Event,
    ) -> ToolResult:
        async def invoke() -> Any:
            value = reg.fn(call.arguments, ctx, signal)
            if inspect.isawaitable(value):
                value = await value
            return value

        try:
            if reg.timeout_ms is None:
                value = await invoke()
            else:
                value = await asyncio.wait_for(invoke(), reg.timeout_ms / 1000)
        except asyncio.TimeoutError:
            return ToolResult(
                call.call_id,
                f"tool call timed out after {reg.timeout_ms}ms",
                is_error=True,
                error_code="TOOL_TIMEOUT",
            )
        except asyncio.CancelledError:
            return ToolResult(
                call.call_id,
                "cancelled during execution",
                is_error=True,
                error_code="ABORTED",
            )
        except Exception as exc:
            return ToolResult(
                call.call_id,
                f"{type(exc).__name__}: {exc}",
                is_error=True,
                error_code="EXECUTION_ERROR",
            )
        if isinstance(value, ToolResult):
            return value
        return ToolResult(call.call_id, str(value))
