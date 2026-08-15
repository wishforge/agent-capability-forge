"""Phase 4-A Session / Turn / Step execution boundaries.

NEW/ACTIVE/ENDED are Phase 4-A runtime implementation states, not a
DSH-native Step state machine (14 §7).
"""

from __future__ import annotations

from dataclasses import dataclass

from event_store import EventStore

NEW = "NEW"
ACTIVE = "ACTIVE"
ENDED = "ENDED"


class Session:
    """Durable history boundary: header lineage metadata + one EventStore.

    PHASE-4A COMPATIBILITY MODEL: parent_session / delegation_depth /
    seed_length are metadata only; fork/resume are not implemented.
    """

    def __init__(
        self,
        session_id: str = "session-1",
        parent_session: str | None = None,
        delegation_depth: int = 0,
        seed_length: int = 0,
    ) -> None:
        self.session_id = session_id
        self.parent_session = parent_session
        self.delegation_depth = delegation_depth
        self.seed_length = seed_length
        self.store = EventStore(session_id)
        self.turns: list[Turn] = []


class Turn:
    def __init__(self, turn_id: str, session: Session) -> None:
        self.turn_id = turn_id
        self.session = session
        self.status = NEW
        self.end_reason: str | None = None
        self.steps: list[Step] = []

    def begin(self) -> None:
        self.status = ACTIVE

    def end(self, reason: str) -> None:
        self.status = ENDED
        self.end_reason = reason

    def new_step(self) -> "Step":
        step = Step(f"{self.turn_id}/step-{len(self.steps) + 1}", self)
        self.steps.append(step)
        return step


class Step:
    def __init__(self, step_id: str, turn: Turn) -> None:
        self.step_id = step_id
        self.turn = turn
        self.status = NEW
        self.model_request = None
        self.tool_calls: list = []

    def begin(self) -> None:
        self.status = ACTIVE

    def end(self) -> None:
        self.status = ENDED


@dataclass(slots=True)
class ExecutionContext:
    """Runtime handle passed to tools: session/turn/step + event store."""

    session: Session
    turn: Turn
    step: Step

    @property
    def store(self) -> EventStore:
        return self.session.store
