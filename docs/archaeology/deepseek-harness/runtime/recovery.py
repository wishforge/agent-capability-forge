"""Phase 4-B recovery: rebuild Session/Turn/Step, replay, and resume.

PHASE-4B ASSUMPTIONS (A4/A5): Phase 4-A logs no execution-started marker, so
every unfinished tool call is conservatively marked TOOL_OUTCOME_UNKNOWN
(TOOL_NOT_STARTED is defined but never determined); resume closes an
interrupted turn with synthetic closers, then starts a fresh turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from event_store import EventStore
from events import (
    AGENT_REQUEST,
    ASSISTANT_MESSAGE,
    EXECUTION_ATTEMPT_END,
    EXECUTION_ATTEMPT_START,
    REQUEST_HEADER,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    SessionEvent,
)
from extensions import ABORTED, FAILED, RUNNING, SUCCEEDED, utc_now
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
    executions: tuple["ReplayExecution", ...] = ()


@dataclass(frozen=True, slots=True)
class ReplayAttempt:
    execution_id: str
    attempt_id: str
    attempt_number: int
    parent_execution_id: str | None
    reason: str | None
    status: str
    started_at: str | None
    ended_at: str | None
    error: str | None = None
    backend_event_ref: dict | None = None
    backend_metadata: dict | None = None
    step_id: str | None = None
    initiator_ref: dict | None = None
    context_provenance: dict | None = None


@dataclass(frozen=True, slots=True)
class ReplayExecution:
    execution_id: str
    attempts: tuple[ReplayAttempt, ...]


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Immutable evaluation-facing projection of one execution (5-G/5-H).

    Pure projection from the Event Log: never a second source of truth and
    never written back into the runtime.
    """

    record_version: str
    projection_rule_version: str
    execution_id: str
    session_id: str
    initiator_ref: dict | None
    owner_refs: tuple[dict, ...]
    attempts: tuple[ReplayAttempt, ...]
    tools: tuple[dict, ...]
    events: tuple[tuple[int, str], ...]
    backend_refs: tuple[dict, ...]
    context_provenance: tuple[dict, ...]
    turns: tuple[dict, ...] = ()
    steps: tuple[dict, ...] = ()
    tool_results: tuple[dict, ...] = ()
    unresolved_tools: tuple[dict, ...] = ()
    execution_outcome: dict | None = None
    turn_end_reason: str | None = None
    turn_outcome: str | None = None
    replay_ref: dict | None = None
    lossiness: tuple[dict, ...] = ()


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
    attempt_starts = [
        e
        for e in store.events()
        if e.event_type == EXECUTION_ATTEMPT_START
    ]
    attempt_ended = {
        e.payload["attempt_id"]
        for e in store.events()
        if e.event_type == EXECUTION_ATTEMPT_END
    }
    if (
        not unresolved
        and not open_steps
        and not open_turns
        and all(
            e.payload["attempt_id"] in attempt_ended
            for e in attempt_starts
        )
    ):
        return ()
    for start in attempt_starts:
        if start.payload["attempt_id"] in attempt_ended:
            continue
        store.append(
            SessionEvent(
                0,
                EXECUTION_ATTEMPT_END,
                store.session_id,
                turn_id=start.turn_id,
                step_id=start.step_id,
                payload={
                    **dict(start.payload),
                    "status": ABORTED,
                    "reason": "interrupted",
                    "ended_at": utc_now(),
                },
            ),
        )
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
    execution_order: list[str] = []
    execution_attempts: dict[str, list[ReplayAttempt]] = {}
    attempts_by_id: dict[str, ReplayAttempt] = {}
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
        elif event.event_type == EXECUTION_ATTEMPT_START:
            p = event.payload
            attempt = ReplayAttempt(
                execution_id=p["execution_id"],
                attempt_id=p["attempt_id"],
                attempt_number=p["attempt_number"],
                parent_execution_id=p.get("parent_execution_id"),
                reason=p.get("reason"),
                status=p.get("status", RUNNING),
                started_at=p.get("started_at"),
                ended_at=None,
                error=None,
                backend_event_ref=p.get("backend_event_ref"),
                backend_metadata=p.get("backend_metadata"),
                step_id=event.step_id,
                initiator_ref=p.get("initiator_ref"),
                context_provenance=p.get("context_provenance"),
            )
            exec_id = p["execution_id"]
            if exec_id not in execution_attempts:
                execution_order.append(exec_id)
                execution_attempts[exec_id] = []
            execution_attempts[exec_id].append(attempt)
            attempts_by_id[attempt.attempt_id] = attempt
        elif event.event_type == EXECUTION_ATTEMPT_END:
            p = event.payload
            attempt = attempts_by_id.get(p["attempt_id"])
            if attempt is None:
                raise ValueError(
                    "attempt/end without matching attempt/start",
                )
            updated = replace(
                attempt,
                status=p.get("status", attempt.status),
                reason=p.get("reason", attempt.reason),
                ended_at=p.get("ended_at"),
                error=p.get("error"),
                backend_event_ref=p.get("backend_event_ref"),
                backend_metadata=p.get("backend_metadata"),
                step_id=p.get("step_id", attempt.step_id),
                initiator_ref=p.get(
                    "initiator_ref",
                    attempt.initiator_ref,
                ),
                context_provenance=p.get(
                    "context_provenance",
                    attempt.context_provenance,
                ),
            )
            attempts_by_id[p["attempt_id"]] = updated
            exec_id = p["execution_id"]
            index = updated.attempt_number - 1
            if index >= len(execution_attempts[exec_id]):
                raise ValueError("attempt/end out of order")
            execution_attempts[exec_id][index] = updated
    if current_turn is not None:
        turns.append(
            ReplayTurn(
                current_turn.turn_id,
                current_turn.end_reason,
                tuple(_finalize_step(s) for s in current_turn.steps),
            ),
        )
    executions = tuple(
        ReplayExecution(exec_id, tuple(execution_attempts[exec_id]))
        for exec_id in execution_order
    )
    return ReplayHistory(store.session_id, tuple(turns), executions)


def _unique_dicts(values) -> tuple[dict, ...]:
    seen: set[str] = set()
    out: list[dict] = []
    for value in values:
        key = json.dumps(value, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(dict(value))
    return tuple(out)


def _turn_outcome_from_reason(reason: str | None) -> str | None:
    """Derived TurnRecord outcome; only from the persisted turn/end reason."""
    if reason is None:
        return None
    return {
        "completed": "COMPLETED",
        "interrupted": "ABORTED",
        "aborted": "ABORTED",
        "blocked": "ABORTED",
        "error": "FAILED",
        "max-tokens": "PARTIAL",
    }.get(reason, "UNKNOWN")


def _step_outcome(
    final_status: str | None,
    has_step_end: bool,
    turn_end_reason: str | None,
) -> str:
    """Derive one StepRecord.outcome from persisted attempt/step/turn facts."""
    if final_status == FAILED:
        return FAILED
    if final_status == ABORTED:
        return ABORTED
    if not has_step_end:
        if turn_end_reason in ("interrupted", "aborted"):
            return ABORTED
        return "UNKNOWN"
    if final_status == RUNNING:
        return "UNKNOWN"
    return "COMPLETED"


def _execution_outcome(
    attempts: tuple[ReplayAttempt, ...],
    turn_end_reason: str | None,
) -> dict:
    """Execution outcome is DERIVED: no execution-level source event exists."""
    if not attempts:
        return {"status": "UNKNOWN", "derived": True, "basis": ["no attempts"]}
    final = max(attempts, key=lambda attempt: attempt.attempt_number)
    status = {
        SUCCEEDED: "SUCCESS",
        FAILED: FAILED,
        ABORTED: ABORTED,
    }.get(final.status, "UNKNOWN")
    basis = [f"{attempt.attempt_id}:{attempt.status}" for attempt in attempts]
    if turn_end_reason is not None:
        basis.append(f"turn/end:{turn_end_reason}")
    return {"status": status, "derived": True, "basis": basis}


def build_execution_record(
    store: EventStore,
    execution_id: str,
) -> ExecutionRecord:
    """Immutable per-execution projection of durable evidence (5-J).

    Turns/steps/tools/results are projected from the same append-only log;
    every derived outcome is explicitly marked derived, never persisted fact.
    """
    history = replay(store)
    attempts = next(
        (
            execution.attempts
            for execution in history.executions
            if execution.execution_id == execution_id
        ),
        (),
    )
    step_ids = {attempt.step_id for attempt in attempts if attempt.step_id}
    scoped = [
        event
        for event in store.events()
        if event.step_id in step_ids
    ]
    turn_ids = {event.turn_id for event in scoped if event.turn_id}
    include_seqs = {event.seq for event in scoped}
    include_seqs.update(
        event.seq
        for event in store.events()
        if event.event_type in (TURN_START, TURN_END)
        and event.turn_id in turn_ids
    )
    included = [
        event
        for event in store.events()
        if event.seq in include_seqs
    ]

    turn_id = next(iter(turn_ids), None)
    turn_start = next(
        (
            event
            for event in included
            if event.event_type == TURN_START
        ),
        None,
    )
    turn_end = next(
        (
            event
            for event in included
            if event.event_type == TURN_END
        ),
        None,
    )
    turn_end_reason = (
        turn_end.payload.get("reason") if turn_end is not None else None
    )
    turn_outcome = _turn_outcome_from_reason(turn_end_reason)
    turns = (
        (
            {
                "turn_id": turn_id,
                "end_reason": turn_end_reason,
                "outcome": turn_outcome,
                "derived": True,
                "event_refs": tuple(
                    event.seq
                    for event in (turn_start, turn_end)
                    if event is not None
                ),
            },
        )
        if turn_id is not None
        else ()
    )

    step_order: list[str] = []
    for event in scoped:
        if event.step_id is not None and event.step_id not in step_order:
            step_order.append(event.step_id)
    steps = []
    for step_id in step_order:
        step_attempts = [
            attempt
            for attempt in attempts
            if attempt.step_id == step_id
        ]
        step_start = next(
            (
                event
                for event in included
                if event.event_type == STEP_START
                and event.step_id == step_id
            ),
            None,
        )
        step_end = next(
            (
                event
                for event in included
                if event.event_type == STEP_END
                and event.step_id == step_id
            ),
            None,
        )
        final = (
            max(step_attempts, key=lambda attempt: attempt.attempt_number)
            if step_attempts
            else None
        )
        derived_from = []
        if step_attempts:
            derived_from.append("attempt_status")
        if step_end is not None:
            derived_from.append("step/end")
        if turn_end_reason is not None:
            derived_from.append("turn/end")
        steps.append(
            {
                "step_id": step_id,
                "turn_id": turn_id,
                "outcome": _step_outcome(
                    final.status if final is not None else None,
                    step_end is not None,
                    turn_end_reason,
                ),
                "derived": True,
                "derived_from": tuple(derived_from),
                "attempt_ids": tuple(
                    attempt.attempt_id for attempt in step_attempts
                ),
                "event_refs": tuple(
                    event.seq
                    for event in (step_start, step_end)
                    if event is not None
                ),
            },
        )

    active_attempt: dict[int, str | None] = {}
    current: str | None = None
    for event in included:
        if (
            event.event_type == EXECUTION_ATTEMPT_START
            and event.payload.get("execution_id") == execution_id
        ):
            current = event.payload.get("attempt_id")
        elif (
            event.event_type == EXECUTION_ATTEMPT_END
            and event.payload.get("attempt_id") == current
        ):
            current = None
        active_attempt[event.seq] = current

    call_events = [
        event
        for event in included
        if event.event_type == TOOL_CALL
    ]
    result_events = [
        event
        for event in included
        if event.event_type == TOOL_RESULT
    ]
    calls_by_id = {
        event.payload.get("call_id"): event
        for event in call_events
    }
    results_by_id = {
        event.payload.get("tool_call_id"): event
        for event in result_events
    }
    tools = tuple(
        {
            **dict(event.payload),
            "seq": event.seq,
            "turn_id": event.turn_id,
            "step_id": event.step_id,
            "execution_id": execution_id,
            "attempt_id": active_attempt.get(event.seq),
        }
        for event in call_events
    )
    tool_results = tuple(
        {
            **dict(event.payload),
            "call_id": event.payload.get("tool_call_id"),
            "seq": event.seq,
            "source_event_seqs": tuple(event.source_event_seqs),
            "turn_id": event.turn_id,
            "step_id": event.step_id,
            "execution_id": execution_id,
            "attempt_id": active_attempt.get(event.seq)
            or (
                active_attempt.get(calls_by_id[event.payload["tool_call_id"]].seq)
                if event.payload.get("tool_call_id") in calls_by_id
                else None
            ),
        }
        for event in result_events
    )
    unresolved_tools = tuple(
        {
            "call_id": event.payload.get("call_id"),
            "name": event.payload.get("name"),
            "status": TOOL_OUTCOME_UNKNOWN,
            "seq": event.seq,
            "turn_id": event.turn_id,
            "step_id": event.step_id,
            "execution_id": execution_id,
            "attempt_id": active_attempt.get(event.seq),
        }
        for event in call_events
        if event.payload.get("call_id") not in results_by_id
    )
    owner_refs = _unique_dicts(
        event.payload["owner_ref"]
        for event in included
        if event.event_type in (TOOL_CALL, TOOL_RESULT)
        and "owner_ref" in event.payload
    )
    backend_refs = _unique_dicts(
        event.payload["backend_event_ref"]
        for event in included
        if "backend_event_ref" in event.payload
    )
    context_provenance = tuple(
        dict(attempt.context_provenance)
        for attempt in attempts
        if attempt.context_provenance is not None
    )
    lossiness = _unique_dicts(
        [
            attempt.backend_metadata
            for attempt in attempts
            if attempt.backend_metadata is not None
        ]
        + [
            event.payload["backend_metadata"]
            for event in included
            if "backend_metadata" in event.payload
        ]
    )
    event_range = (
        [included[0].seq, included[-1].seq]
        if included
        else []
    )
    replay_ref = {
        "source": "event_log",
        "session_id": store.session_id,
        "execution_id": execution_id,
        "event_range": event_range,
        "record_version": "5j.1",
        "projection_rule_version": "v2",
    }
    return ExecutionRecord(
        record_version="5j.1",
        projection_rule_version="v2",
        execution_id=execution_id,
        session_id=store.session_id,
        initiator_ref=(
            attempts[0].initiator_ref
            if attempts and attempts[0].initiator_ref is not None
            else None
        ),
        owner_refs=owner_refs,
        attempts=attempts,
        tools=tools,
        events=tuple((event.seq, event.event_type) for event in included),
        backend_refs=backend_refs,
        context_provenance=context_provenance,
        turns=turns,
        steps=tuple(steps),
        tool_results=tool_results,
        unresolved_tools=unresolved_tools,
        execution_outcome=_execution_outcome(attempts, turn_end_reason),
        turn_end_reason=turn_end_reason,
        turn_outcome=turn_outcome,
        replay_ref=replay_ref,
        lossiness=lossiness,
    )


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
    "ExecutionRecord",
    "TOOL_NOT_STARTED",
    "TOOL_OUTCOME_UNKNOWN",
    "ReplayHistory",
    "ReplayAttempt",
    "ReplayExecution",
    "ReplayStep",
    "ReplayToolResult",
    "ReplayTurn",
    "UnresolvedTool",
    "build_execution_record",
    "find_unresolved_tools",
    "rebuild_session",
    "repair_interrupted_turn",
    "replay",
    "resume",
]
