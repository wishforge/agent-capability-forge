"""Phase 4-A in-memory append-only EventStore.

DURABILITY:
PHASE-4A ASSUMPTION (A1)
"""

from __future__ import annotations

from dataclasses import replace

from events import SessionEvent


class EventStore:
    """Monotonic, append-only, in-memory event log for one Session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._events: list[SessionEvent] = []

    def append(self, event: SessionEvent) -> SessionEvent:
        if event.session_id != self.session_id:
            raise ValueError(
                f"event session {event.session_id!r} != store session "
                f"{self.session_id!r}",
            )
        stored = replace(event, seq=self.last_seq() + 1)
        self._events.append(stored)
        return stored

    def append_many(self, events: list[SessionEvent]) -> list[SessionEvent]:
        return [self.append(event) for event in events]

    def events(self) -> tuple[SessionEvent, ...]:
        """Immutable view; events themselves are frozen dataclasses."""
        return tuple(self._events)

    def last_seq(self) -> int:
        return len(self._events)

    def snapshot(self) -> tuple[SessionEvent, ...]:
        return self.events()
