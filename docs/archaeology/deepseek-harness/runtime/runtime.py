"""Phase 4-A/4-D RuntimeCoordinator + AgentRuntime: Session -> Turn -> Step loop.

RuntimeCoordinator keeps the Phase 4-A constructor contract; AgentRuntime is
the stream-driven loop that also runs backend adapters, compaction retry,
and tool delegation. Only internal scheduler/runtime failures may produce
turn/end{error}; tool failures are ToolResult(is_error=True) and the loop
continues (15 §11).
"""

from __future__ import annotations

from dataclasses import asdict, replace

from model_adapter import (
    ModelChunk,
    ModelFinal,
    ModelRequestError,
    ModelResponse,
    ModelToolCall,
    ModelToolCallEvent,
    ModelToolResultEvent,
    ScriptedModelAdapter,
)
from compaction import NO_RETRY, RETRY, build_model_context
from events import (
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    EXECUTION_ATTEMPT_END,
    EXECUTION_ATTEMPT_START,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    SessionEvent,
)
from extensions import (
    ABORTED,
    ADAPTER_DERIVED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    BackendMetadata,
    Execution,
    ExecutionAttempt,
    InitiatorRef,
    utc_now,
)
from initiator import InitiatorContext, with_initiator
from surface import SurfaceProjection
from tool_runtime import ToolCall, ToolResult, ToolRuntime
from turn_step import ENDED, ExecutionContext, Session, Turn


class AgentRuntime:
    """Deterministic/backend loop: events are appended before projection."""

    def __init__(
        self,
        session: Session,
        tool_runtime: ToolRuntime,
        adapter,
        initiator: InitiatorContext | str,
        *,
        system_prompt: str = "",
        tools: tuple[str, ...] = (),
        runtime_context: str = "",
        compaction=None,
        model_name: str | None = None,
    ) -> None:
        self.session = session
        self.tool_runtime = tool_runtime
        self.adapter = adapter
        self.initiator = (
            InitiatorContext(initiator)
            if isinstance(initiator, str)
            else initiator
        )
        self.system_prompt = system_prompt
        self.tools = tuple(tools)
        self.runtime_context = runtime_context
        self.compaction = compaction
        self.model_name = model_name
        self.executions: dict[str, Execution] = {}

    async def run_turn(
        self,
        user_message: str,
        turn_id: str | None = None,
    ) -> Turn:
        with with_initiator(self.initiator):
            store = self.session.store
            turn = Turn(
                turn_id
                or f"{self.session.session_id}/turn-{len(self.session.turns) + 1}",
                self.session,
            )
            self.session.turns.append(turn)
            store.append(
                SessionEvent(
                    0,
                    USER_MESSAGE,
                    self.session.session_id,
                    turn_id=turn.turn_id,
                    payload={"content": user_message},
                ),
            )
            turn.begin()
            turn_payload: dict = {}
            mapping = getattr(self.adapter, "mapping_metadata", None)
            if isinstance(mapping, BackendMetadata):
                turn_payload["backend_metadata"] = asdict(mapping)
            store.append(
                SessionEvent(
                    0,
                    TURN_START,
                    self.session.session_id,
                    turn_id=turn.turn_id,
                    payload=turn_payload,
                ),
            )
            step = None
            attempt = None
            try:
                while True:
                    step = turn.new_step()
                    step.begin()
                    ctx = ExecutionContext(self.session, turn, step)
                    store.append(
                        SessionEvent(
                            0,
                            STEP_START,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                        ),
                    )
                    tools = self.tools or self.tool_runtime.names()
                    request_ev = store.append(
                        SessionEvent(
                            0,
                            AGENT_REQUEST,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                            payload={
                                "model": self.model_name
                                or getattr(
                                    self.adapter,
                                    "model_name",
                                    "deterministic-fake",
                                ),
                                "tools": tools,
                                "initiator_ref": asdict(
                                    self._initiator_ref(),
                                ),
                            },
                        ),
                    )
                    current_input = (
                        user_message if len(turn.steps) == 1 else ""
                    )
                    mctx = self._build_context(current_input, tools)
                    if self.compaction is not None:
                        decision = self.compaction.maybe_compact()
                        if decision.kind == NO_RETRY and decision.reason == "compacted":
                            mctx = self._build_context(current_input, tools)
                    step.model_request = mctx.messages
                    chunk_seqs: list[int] = []
                    tool_results: list[ToolResult] = []
                    attempt_reason = "model_request"
                    while True:
                        chunk_seqs = []
                        tool_results = []
                        attempt = self._start_attempt(
                            step,
                            reason=attempt_reason,
                            context_provenance=self._build_context_provenance(
                                request_ev.seq,
                                current_input,
                            ),
                        )
                        attempt_ref = None
                        attempt_meta = None
                        try:
                            async for evt in self.adapter.stream(ctx, mctx):
                                if attempt_ref is None:
                                    attempt_ref = getattr(
                                        evt,
                                        "backend_event_ref",
                                        None,
                                    )
                                if attempt_meta is None:
                                    attempt_meta = getattr(
                                        evt,
                                        "backend_metadata",
                                        None,
                                    )
                                if isinstance(evt, ModelChunk):
                                    chunk_seqs.append(
                                        store.append(
                                            SessionEvent(
                                                0,
                                                ASSISTANT_CHUNK,
                                                self.session.session_id,
                                                turn_id=turn.turn_id,
                                                step_id=step.step_id,
                                                payload={
                                                    "content": evt.content,
                                                    **self._extension_payload(
                                                        evt,
                                                    ),
                                                },
                                            ),
                                        ).seq,
                                    )
                                elif isinstance(evt, ModelFinal):
                                    store.append(
                                        SessionEvent(
                                            0,
                                            ASSISTANT_MESSAGE,
                                            self.session.session_id,
                                            turn_id=turn.turn_id,
                                            step_id=step.step_id,
                                            payload={
                                                "content": evt.content,
                                                "tool_calls": [
                                                    {
                                                        "id": call.call_id,
                                                        "name": call.name,
                                                        "arguments": call.arguments,
                                                    }
                                                    for call in evt.tool_calls
                                                ],
                                                **self._extension_payload(evt),
                                            },
                                            source_event_seqs=tuple(chunk_seqs),
                                        ),
                                    )
                                    if not evt.tool_calls:
                                        self._end_attempt(
                                            attempt,
                                            SUCCEEDED,
                                            step,
                                            backend_ref=attempt_ref,
                                            backend_meta=attempt_meta,
                                        )
                                        step.end()
                                        store.append(
                                            SessionEvent(
                                                0,
                                                STEP_END,
                                                self.session.session_id,
                                                turn_id=turn.turn_id,
                                                step_id=step.step_id,
                                            ),
                                        )
                                        turn.end("completed")
                                        store.append(
                                            SessionEvent(
                                                0,
                                                TURN_END,
                                                self.session.session_id,
                                                turn_id=turn.turn_id,
                                                payload={
                                                    "reason": "completed",
                                                },
                                            ),
                                        )
                                        return turn
                                elif isinstance(evt, ModelToolCallEvent):
                                    if self.tool_runtime.get(evt.name) is None:
                                        store.append(
                                            SessionEvent(
                                                0,
                                                TOOL_CALL,
                                                self.session.session_id,
                                                turn_id=turn.turn_id,
                                                step_id=step.step_id,
                                                payload={
                                                    "call_id": evt.call_id,
                                                    "name": evt.name,
                                                    "arguments": evt.arguments,
                                                    "initiator_ref": asdict(
                                                        self._initiator_ref(),
                                                    ),
                                                    **self._extension_payload(
                                                        evt,
                                                    ),
                                                },
                                            ),
                                        )
                                    elif not self.adapter.delegates_tools:
                                        tool_results.append(
                                            await self.tool_runtime.execute(
                                                ToolCall(
                                                    evt.call_id,
                                                    evt.name,
                                                    evt.arguments,
                                                    backend_event_ref=(
                                                        evt.backend_event_ref
                                                    ),
                                                    backend_metadata=(
                                                        evt.backend_metadata
                                                    ),
                                                ),
                                                ctx,
                                            ),
                                        )
                                elif isinstance(evt, ModelToolResultEvent):
                                    if self.adapter.delegates_tools:
                                        self._record_or_validate_tool_result(
                                            ctx,
                                            evt,
                                        )
                            attempt = self._end_attempt(
                                attempt,
                                SUCCEEDED,
                                step,
                                backend_ref=attempt_ref,
                                backend_meta=attempt_meta,
                            )
                            break
                        except ModelRequestError as exc:
                            if self.compaction is None:
                                attempt = self._end_attempt(
                                    attempt,
                                    FAILED,
                                    step,
                                    error=exc.code,
                                    backend_ref=attempt_ref,
                                    backend_meta=attempt_meta,
                                )
                                raise
                            decision = self.compaction.handle_request_error(
                                exc.code,
                            )
                            status = FAILED
                            end_reason = "model_request"
                            if decision.kind != RETRY:
                                if decision.reason == "retry_not_safe":
                                    status = ABORTED
                                    end_reason = "UNSAFE_RETRY_BLOCKED"
                                elif decision.reason:
                                    end_reason = decision.reason
                                attempt = self._end_attempt(
                                    attempt,
                                    status,
                                    step,
                                    reason=end_reason,
                                    error=exc.code,
                                    backend_ref=attempt_ref,
                                    backend_meta=attempt_meta,
                                )
                                raise
                            attempt = self._end_attempt(
                                attempt,
                                FAILED,
                                step,
                                reason=end_reason,
                                error=exc.code,
                                backend_ref=attempt_ref,
                                backend_meta=attempt_meta,
                            )
                            mctx = self._build_context(current_input, tools)
                            attempt_reason = "compaction_retry"
                            continue
                    step.end()
                    store.append(
                        SessionEvent(
                            0,
                            STEP_END,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                        ),
                    )
                    results = (
                        self.adapter.step_tool_results
                        if self.adapter.delegates_tools
                        else tool_results
                    )
                    if any(result.concludes_turn for result in results):
                        turn.end("completed")
                        store.append(
                            SessionEvent(
                                0,
                                TURN_END,
                                self.session.session_id,
                                turn_id=turn.turn_id,
                                payload={"reason": "completed"},
                            ),
                        )
                        return turn
                    for result in results:
                        for context in result.additional_contexts:
                            store.append(
                                SessionEvent(
                                    0,
                                    USER_MESSAGE,
                                    self.session.session_id,
                                    turn_id=turn.turn_id,
                                    payload={
                                        "content": context,
                                        "source": "additional-context",
                                    },
                                ),
                            )
            except Exception:
                if attempt is not None and attempt.status == RUNNING:
                    attempt = self._end_attempt(
                        attempt,
                        ABORTED,
                        step,
                        reason="interrupted",
                    )
                if step is not None and step.status != ENDED:
                    step.end()
                    store.append(
                        SessionEvent(
                            0,
                            STEP_END,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                        ),
                    )
                turn.end("error")
                store.append(
                    SessionEvent(
                        0,
                        TURN_END,
                        self.session.session_id,
                        turn_id=turn.turn_id,
                        payload={"reason": "error"},
                    ),
                )
                raise

    @staticmethod
    def _extension_payload(evt) -> dict:
        payload: dict = {}
        ref = getattr(evt, "backend_event_ref", None)
        if ref is not None:
            payload["backend_event_ref"] = asdict(ref)
        meta = getattr(evt, "backend_metadata", None)
        if meta is not None:
            payload["backend_metadata"] = asdict(meta)
        return payload

    def _start_attempt(
        self,
        step,
        *,
        reason: str = "model_request",
        context_provenance: dict | None = None,
    ) -> ExecutionAttempt:
        execution = self.executions.setdefault(
            step.step_id,
            Execution(step.step_id),
        )
        number = len(execution.attempts) + 1
        started = utc_now()
        attempt = ExecutionAttempt(
            execution_id=step.step_id,
            attempt_id=f"{step.step_id}/attempt-{number}",
            attempt_number=number,
            parent_execution_id=step.step_id if number > 1 else None,
            reason=reason,
            status=RUNNING,
            started_at=started,
        )
        execution.attempts.append(attempt)
        payload = {
            "execution_id": attempt.execution_id,
            "attempt_id": attempt.attempt_id,
            "attempt_number": attempt.attempt_number,
            "parent_execution_id": attempt.parent_execution_id,
            "reason": attempt.reason,
            "status": attempt.status,
            "started_at": started,
            "initiator_ref": asdict(self._initiator_ref()),
        }
        if context_provenance is not None:
            payload["context_provenance"] = context_provenance
        self.session.store.append(
            SessionEvent(
                0,
                EXECUTION_ATTEMPT_START,
                self.session.session_id,
                turn_id=step.turn.turn_id,
                step_id=step.step_id,
                payload=payload,
            ),
        )
        return attempt

    def _end_attempt(
        self,
        attempt: ExecutionAttempt,
        status: str,
        step,
        *,
        reason: str | None = None,
        error: str | None = None,
        backend_ref=None,
        backend_meta=None,
    ) -> ExecutionAttempt:
        if attempt.status != RUNNING:
            return attempt
        ended = replace(
            attempt,
            status=status,
            reason=reason if reason is not None else attempt.reason,
            ended_at=utc_now(),
            backend_event_ref=backend_ref,
            backend_metadata=backend_meta,
        )
        execution = self.executions[attempt.execution_id]
        execution.attempts[attempt.attempt_number - 1] = ended
        payload: dict = {
            "execution_id": ended.execution_id,
            "attempt_id": ended.attempt_id,
            "attempt_number": ended.attempt_number,
            "parent_execution_id": ended.parent_execution_id,
            "reason": ended.reason,
            "status": ended.status,
            "started_at": ended.started_at,
            "ended_at": ended.ended_at,
            "initiator_ref": asdict(self._initiator_ref()),
        }
        if error is not None:
            payload["error"] = error
        if backend_ref is not None:
            payload["backend_event_ref"] = asdict(backend_ref)
        if backend_meta is not None:
            payload["backend_metadata"] = asdict(backend_meta)
        self.session.store.append(
            SessionEvent(
                0,
                EXECUTION_ATTEMPT_END,
                self.session.session_id,
                turn_id=step.turn.turn_id,
                step_id=step.step_id,
                payload=payload,
            ),
        )
        return ended

    def _build_context(self, current_input: str, tools: tuple[str, ...]):
        return build_model_context(
            self.session,
            system_prompt=self.system_prompt,
            tools=tools,
            runtime_context=self.runtime_context,
            current_input=current_input,
        )

    def _initiator_ref(self) -> InitiatorRef:
        return InitiatorRef(
            ref=self.initiator.agent_id,
            source=ADAPTER_DERIVED,
        )

    def _build_context_provenance(
        self,
        request_ref: int,
        current_input: str,
    ) -> dict:
        """Request-time context refs; never copies message bodies.

        source_event_refs and surface_refs are the same seqs in this runtime
        because surface nodes are event refs. system_prompt / runtime_context
        have no durable snapshot yet, so quality stays PARTIAL.
        """
        store = self.session.store
        surface_seqs = SurfaceProjection(store).active_seqs()
        current_input_ref = None
        if current_input:
            current_input_ref = next(
                (
                    e.seq
                    for e in reversed(store.events())
                    if e.event_type == USER_MESSAGE
                    and e.payload.get("content") == current_input
                ),
                None,
            )
        return {
            "request_ref": request_ref,
            "source_event_refs": list(surface_seqs),
            "surface_refs": list(surface_seqs),
            "current_input_ref": current_input_ref,
            "runtime_context_ref": None,
            "quality": "PARTIAL",
            "missing_semantics": [
                "SYSTEM_PROMPT_SNAPSHOT",
                "RUNTIME_CONTEXT_SNAPSHOT",
            ],
        }

    @staticmethod
    def _record_or_validate_tool_result(ctx: ExecutionContext, evt) -> None:
        call_ev = next(
            (
                e
                for e in ctx.store.events()
                if e.event_type == TOOL_CALL
                and e.payload.get("call_id") == evt.call_id
            ),
            None,
        )
        results = [
            e
            for e in ctx.store.events()
            if e.event_type == TOOL_RESULT
            and e.payload.get("tool_call_id") == evt.call_id
        ]
        if results:
            latest = results[-1]
            if bool(latest.payload.get("is_error")) != evt.is_error:
                raise RuntimeError(
                    "tool result state mismatch: "
                    f"event_is_error={evt.is_error} log_is_error="
                    f"{bool(latest.payload.get('is_error'))}",
                )
            return
        if call_ev is None:
            raise RuntimeError(f"tool result without tool call: {evt.call_id}")
        payload = {
            "tool_call_id": evt.call_id,
            "content": evt.content,
            "is_error": True,
            "error_code": evt.error_code or "UNKNOWN_TOOL",
            **AgentRuntime._extension_payload(evt),
        }
        for key in ("initiator_ref", "owner_ref"):
            if key in call_ev.payload:
                payload[key] = call_ev.payload[key]
        ctx.store.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                ctx.session.session_id,
                turn_id=ctx.turn.turn_id,
                step_id=ctx.step.step_id,
                payload=payload,
                source_event_seqs=(call_ev.seq,),
            ),
        )


class RuntimeCoordinator:
    """Phase 4-A constructor contract over the upgraded AgentRuntime loop."""

    def __init__(
        self,
        session: Session,
        tool_runtime: ToolRuntime,
        model,
        initiator: InitiatorContext | str,
        **kwargs,
    ) -> None:
        self.session = session
        self.tool_runtime = tool_runtime
        self.adapter = (
            model if hasattr(model, "stream") else ScriptedModelAdapter(model)
        )
        self.initiator = initiator
        self.surface = SurfaceProjection(session.store)
        self.kwargs = kwargs

    async def run_turn(
        self,
        user_message: str,
        turn_id: str | None = None,
    ) -> Turn:
        return await AgentRuntime(
            self.session,
            self.tool_runtime,
            self.adapter,
            self.initiator,
            **self.kwargs,
        ).run_turn(user_message, turn_id)


__all__ = [
    "AgentRuntime",
    "ModelResponse",
    "ModelToolCall",
    "RuntimeCoordinator",
]
