"""SurfaceProjection: EventStore -> model-visible messages.

Phase 4-A implementation assumption:
derive_messages is deterministic.
(Not a DSH guarantee; 13 ES-04 is INFERENCE.)
"""

from __future__ import annotations

from dataclasses import dataclass

from event_store import EventStore
from events import ASSISTANT_MESSAGE, TOOL_RESULT, USER_MESSAGE


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[dict, ...] = ()


class SurfaceProjection:
    """Ordered projection of the event log; never a second source of truth."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def derive_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        for event in self.store.events():
            if event.event_type == USER_MESSAGE:
                messages.append(Message("user", event.payload["content"]))
            elif event.event_type == ASSISTANT_MESSAGE:
                messages.append(
                    Message(
                        "assistant",
                        event.payload.get("content", ""),
                        tool_calls=tuple(event.payload.get("tool_calls", ())),
                    ),
                )
            elif event.event_type == TOOL_RESULT:
                messages.append(
                    Message(
                        "tool",
                        event.payload["content"],
                        tool_call_id=event.payload["tool_call_id"],
                    ),
                )
        return tuple(messages)
