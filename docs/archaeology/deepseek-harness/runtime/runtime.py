"""Phase 4-A RuntimeCoordinator: deterministic Session -> Turn -> Step loop.

Only internal scheduler/runtime failures may produce turn/end{error}; tool
failures are ToolResult(is_error=True) and the loop continues (15 §11).
"""

from __future__ import annotations

from dataclasses import dataclass

from events import (
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    STEP_END,
    STEP_START,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    SessionEvent,
)
from initiator import InitiatorContext, with_initiator
from surface import Message, SurfaceProjection
from tool_runtime import ToolCall, ToolRuntime
from turn_step import ExecutionContext, Session, Turn


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()


class RuntimeCoordinator:
    def __init__(
        self,
        session: Session,
        tool_runtime: ToolRuntime,
        model,
        initiator: InitiatorContext | str,
    ) -> None:
        self.session = session
        self.tool_runtime = tool_runtime
        self.model = model
        self.initiator = (
            InitiatorContext(initiator)
            if isinstance(initiator, str)
            else initiator
        )
        self.surface = SurfaceProjection(session.store)

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
                    messages = self.surface.derive_messages()
                    response = await self.model(messages)
                    step.model_request = messages
                    store.append(
                        SessionEvent(
                            0,
                            AGENT_REQUEST,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                            payload={
                                "model": "deterministic-fake",
                                "tools": self.tool_runtime.names(),
                            },
                        ),
                    )
                    chunk_seq = None
                    if response.content:
                        chunk_event = store.append(
                            SessionEvent(
                                0,
                                ASSISTANT_CHUNK,
                                self.session.session_id,
                                turn_id=turn.turn_id,
                                step_id=step.step_id,
                                payload={"content": response.content},
                            ),
                        )
                        chunk_seq = chunk_event.seq
                    store.append(
                        SessionEvent(
                            0,
                            ASSISTANT_MESSAGE,
                            self.session.session_id,
                            turn_id=turn.turn_id,
                            step_id=step.step_id,
                            payload={
                                "content": response.content,
                                "tool_calls": [
                                    {
                                        "id": call.call_id,
                                        "name": call.name,
                                        "arguments": call.arguments,
                                    }
                                    for call in response.tool_calls
                                ],
                            },
                            source_event_seqs=(
                                (chunk_seq,) if chunk_seq is not None else ()
                            ),
                        ),
                    )

                    if not response.tool_calls:
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
                                payload={"reason": "completed"},
                            ),
                        )
                        return turn

                    results = []
                    for call in response.tool_calls:
                        result = await self.tool_runtime.execute(
                            ToolCall(call.call_id, call.name, call.arguments),
                            ctx,
                        )
                        results.append(result)

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
