"""Phase 4-B recovery: rebuild Session/Turn/Step, replay, and resume.

PHASE-4B ASSUMPTIONS (A4/A5): Phase 4-A logs no execution-started marker, so
every unfinished tool call is conservatively marked TOOL_OUTCOME_UNKNOWN
(TOOL_NOT_STARTED is defined but never determined); resume closes an
interrupted turn with synthetic closers, then starts a fresh turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from event_store import EventStore
from events import (
    AGENT_REQUEST,
    ASSISTANT_MESSAGE,
    REQUEST_HEADER,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    SessionEvent,
)
from runtime import RuntimeCoordinator
from tool_runtime import ToolCall, ToolRuntime
from turn_step import Session, Step, Turn

TOOL_NOT_STARTED = "TOOL_NOT_STARTED"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class UnresolvedTool:
    status: str
    call: SessionEvent
    turn_id: str | None
    step_id: str | None


@dataclass(frozen=True, slots=True)
class ReplayToolResult:
    call_id: str
    content: str
    is_error: bool
    error_code: str | None
    seq: int
    source_event_seqs: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReplayStep:
    step_id: str
    request: dict | None
    assistant_messages: tuple[dict, ...]
    tool_calls: tuple[dict, ...]
    tool_results: tuple[ReplayToolResult, ...]


@dataclass(frozen=True, slots=True)
class ReplayTurn:
    turn_id: str
    end_reason: str | None
    steps: tuple[ReplayStep, ...]


@dataclass(frozen=True, slots=True)
class ReplayHistory:
    session_id: str
    turns: tuple[ReplayTurn, ...]


@dataclass
class _StepBuilder:
    step_id: str
    request: dict | None = None
    assistant_messages: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)


@dataclass
class _TurnBuilder:
    turn_id: str
    steps: list = field(default_factory=list)
    end_reason: str | None = None


def find_unresolved_tools(store: EventStore) -> tuple[UnresolvedTool, ...]:
    """tool/call events with no matching tool/result."""
    resolved = {
        (event.payload["tool_call_id"], seq)
        for event in store.events()
        if event.event_type == TOOL_RESULT
        for seq in event.source_event_seqs
    }
    unresolved = []
    for event in store.events():
        if (
            event.event_type == TOOL_CALL
            and (event.payload["call_id"], event.seq) not in resolved
        ):
            unresolved.append(
                UnresolvedTool(
                    # ponytail: no execution-started marker exists in Phase 4-A,
                    # so every unfinished call is conservatively outcome-unknown;
                    # TOOL_NOT_STARTED needs that marker before it can be set.
                    TOOL_OUTCOME_UNKNOWN,
                    event,
                    event.turn_id,
                    event.step_id,
                ),
            )
    return tuple(unresolved)


def _open_turns(store: EventStore) -> tuple[SessionEvent, ...]:
    ended = {e.turn_id for e in store.events() if e.event_type == TURN_END}
    return tuple(
        e
        for e in store.events()
        if e.event_type == TURN_START and e.turn_id not in ended
    )


def _open_steps(store: EventStore) -> tuple[SessionEvent, ...]:
    ended = {e.step_id for e in store.events() if e.event_type == STEP_END}
    return tuple(
        e
        for e in store.events()
        if e.event_type == STEP_START and e.step_id not in ended
    )


def repair_interrupted_turn(store: EventStore) -> tuple[UnresolvedTool, ...]:
    """Append synthetic closers for the last unclosed turn, per Phase 3 contract.

    Order matches DSH repair: synthetic tool/result -> step/end ->
    turn/end{interrupted} (15 §11). This is a Phase 4-B implementation
    behavior, not a claim of full DSH durable semantics.
    """
    unresolved = find_unresolved_tools(store)
    open_steps = _open_steps(store)
    open_turns = _open_turns(store)
    if not unresolved and not open_steps and not open_turns:
        return ()
    for tool in unresolved:
        store.append(
            SessionEvent(
                0,
                TOOL_RESULT,
                store.session_id,
                turn_id=tool.turn_id,
                step_id=tool.step_id,
                payload={
                    "tool_call_id": tool.call.payload["call_id"],
                    "content": (
                        "tool execution outcome unknown; "
                        "the outcome was not completed"
                    ),
                    "is_error": True,
                    "error_code": TOOL_OUTCOME_UNKNOWN,
                },
                source_event_seqs=(tool.call.seq,),
            ),
        )
    for step in open_steps:
        store.append(
            SessionEvent(
                0,
                STEP_END,
                store.session_id,
                turn_id=step.turn_id,
                step_id=step.step_id,
            ),
        )
    for turn in open_turns:
        store.append(
            SessionEvent(
                0,
                TURN_END,
                store.session_id,
                turn_id=turn.turn_id,
                payload={"reason": "interrupted"},
            ),
        )
    return unresolved


def rebuild_session(store: EventStore) -> Session:
    """Reconstruct Session/Turn/Step from the event log (source of truth)."""
    session = Session(store.session_id)
    session.store = store
    current_turn: Turn | None = None
    current_step: Step | None = None
    for event in store.events():
        if event.event_type == TURN_START:
            if event.turn_id is None:
                raise ValueError("turn/start without turn_id")
            current_turn = Turn(event.turn_id, session)
            current_turn.begin()
            session.turns.append(current_turn)
            current_step = None
        elif event.event_type == STEP_START:
            if current_turn is None or event.step_id is None:
                raise ValueError("step/start outside an open turn")
            current_step = Step(event.step_id, current_turn)
            current_step.begin()
            current_turn.steps.append(current_step)
        elif event.event_type == TOOL_CALL:
            if current_step is None:
                raise ValueError("tool/call outside an open step")
            current_step.tool_calls.append(
                ToolCall(
                    event.payload["call_id"],
                    event.payload["name"],
                    dict(event.payload.get("arguments") or {}),
                    root_call_id=event.payload.get("root_call_id"),
                    parent_call_id=event.payload.get("parent_call_id"),
                ),
            )
        elif event.event_type in (AGENT_REQUEST, REQUEST_HEADER):
            if current_step is not None:
                current_step.request_header = dict(event.payload)
        elif event.event_type == STEP_END:
            if current_step is None or event.step_id != current_step.step_id:
                raise ValueError("step/end without matching open step")
            current_step.end()
        elif event.event_type == TURN_END:
            if current_turn is None or event.turn_id != current_turn.turn_id:
                raise ValueError("turn/end without matching open turn")
            current_turn.end(str(event.payload.get("reason") or "interrupted"))
    return session


def replay(store: EventStore, session_id: str | None = None) -> ReplayHistory:
    """Reconstruct execution history without re-executing anything."""
    if session_id is not None and session_id != store.session_id:
        raise ValueError(
            f"replay session {session_id!r} != store session "
            f"{store.session_id!r}",
        )
    turns: list[ReplayTurn] = []
    current_turn: _TurnBuilder | None = None
    current_step: _StepBuilder | None = None
    for event in store.events():
        if event.event_type == TURN_START:
            current_turn = _TurnBuilder(event.turn_id)
            current_step = None
        elif event.event_type == TURN_END:
            if current_turn is None or current_turn.turn_id != event.turn_id:
                raise ValueError("turn/end without matching open turn")
            current_turn.end_reason = event.payload.get("reason")
            turns.append(
                ReplayTurn(
                    current_turn.turn_id,
                    current_turn.end_reason,
                    tuple(_finalize_step(s) for s in current_turn.steps),
                ),
            )
            current_turn = None
            current_step = None
        elif event.event_type == STEP_START:
            if current_turn is None:
                raise ValueError("step/start outside an open turn")
            current_step = _StepBuilder(event.step_id)
            current_turn.steps.append(current_step)
        elif event.event_type in (AGENT_REQUEST, REQUEST_HEADER):
            if current_step is not None:
                current_step.request = dict(event.payload)
        elif event.event_type == ASSISTANT_MESSAGE:
            if current_step is not None:
                current_step.assistant_messages.append(dict(event.payload))
        elif event.event_type == TOOL_CALL:
            if current_step is not None:
                current_step.tool_calls.append(dict(event.payload))
        elif event.event_type == TOOL_RESULT:
            if current_step is not None:
                current_step.tool_results.append(
                    ReplayToolResult(
                        call_id=event.payload["tool_call_id"],
                        content=event.payload["content"],
                        is_error=bool(event.payload.get("is_error")),
                        error_code=event.payload.get("error_code"),
                        seq=event.seq,
                        source_event_seqs=event.source_event_seqs,
                    ),
                )
    if current_turn is not None:
        turns.append(
            ReplayTurn(
                current_turn.turn_id,
                current_turn.end_reason,
                tuple(_finalize_step(s) for s in current_turn.steps),
            ),
        )
    return ReplayHistory(store.session_id, tuple(turns))


def _finalize_step(builder: _StepBuilder) -> ReplayStep:
    return ReplayStep(
        builder.step_id,
        builder.request,
        tuple(builder.assistant_messages),
        tuple(builder.tool_calls),
        tuple(builder.tool_results),
    )


async def resume(
    store: EventStore,
    tool_runtime: ToolRuntime,
    model,
    initiator,
    user_message: str = "continue",
) -> tuple[Session, tuple[UnresolvedTool, ...], Turn]:
    """Reload, repair, close interrupted turns, then run a fresh turn.

    PHASE-4B ASSUMPTION (A5): the safe resume point is after the last
    completed turn. An interrupted turn is closed with synthetic closers and
    its unresolved tools are never re-executed; execution continues with a
    new turn driven by the deterministic model.
    """
    store.repair_tail()
    unresolved = repair_interrupted_turn(store)
    session = rebuild_session(store)
    turn = await RuntimeCoordinator(
        session,
        tool_runtime,
        model,
        initiator,
    ).run_turn(user_message)
    return session, unresolved, turn


__all__ = [
    "TOOL_NOT_STARTED",
    "TOOL_OUTCOME_UNKNOWN",
    "ReplayHistory",
    "ReplayStep",
    "ReplayToolResult",
    "ReplayTurn",
    "UnresolvedTool",
    "find_unresolved_tools",
    "rebuild_session",
    "repair_interrupted_turn",
    "replay",
    "resume",
]
