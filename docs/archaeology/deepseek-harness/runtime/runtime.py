"""Phase 4-A/4-D RuntimeCoordinator + AgentRuntime: Session -> Turn -> Step loop.

RuntimeCoordinator keeps the Phase 4-A constructor contract; AgentRuntime is
the stream-driven loop that also runs AgentScope adapters, compaction retry,
and tool delegation. Only internal scheduler/runtime failures may produce
turn/end{error}; tool failures are ToolResult(is_error=True) and the loop
continues (15 §11).
"""

from __future__ import annotations

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
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    SessionEvent,
)
from initiator import InitiatorContext, with_initiator
from surface import SurfaceProjection
from tool_runtime import ToolCall, ToolResult, ToolRuntime
from turn_step import ENDED, ExecutionContext, Session, Turn


class AgentRuntime:
    """Deterministic/AgentScope loop: events are appended before projection."""

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
            store.append(
                SessionEvent(
                    0,
                    TURN_START,
                    self.session.session_id,
                    turn_id=turn.turn_id,
                ),
            )
            step = None
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
                    store.append(
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
                    while True:
                        chunk_seqs = []
                        tool_results = []
                        try:
                            async for evt in self.adapter.stream(ctx, mctx):
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
                                            },
                                            source_event_seqs=tuple(chunk_seqs),
                                        ),
                                    )
                                    if not evt.tool_calls:
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
                            break
                        except ModelRequestError as exc:
                            if self.compaction is None:
                                raise
                            decision = self.compaction.handle_request_error(
                                exc.code,
                            )
                            if decision.kind != RETRY:
                                raise
                            mctx = self._build_context(current_input, tools)
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

    def _build_context(self, current_input: str, tools: tuple[str, ...]):
        return build_model_context(
            self.session,
            system_prompt=self.system_prompt,
            tools=tools,
            runtime_context=self.runtime_context,
            current_input=current_input,
        )

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
        ctx.store.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                ctx.session.session_id,
                turn_id=ctx.turn.turn_id,
                step_id=ctx.step.step_id,
                payload={
                    "tool_call_id": evt.call_id,
                    "content": evt.content,
                    "is_error": True,
                    "error_code": evt.error_code or "UNKNOWN_TOOL",
                },
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
