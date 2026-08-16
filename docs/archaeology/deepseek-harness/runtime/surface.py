"""SurfaceProjection: EventStore -> model-visible messages.

Phase 4-A implementation assumption:
derive_messages is deterministic.
(Not a DSH guarantee; 13 ES-04 is INFERENCE.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from event_store import EventStore
from events import (
    ASSISTANT_MESSAGE,
    SURFACE_EVENT_TYPES,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)


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

    def active_seqs(self) -> tuple[int, ...]:
        return _fold_active_seqs(self.store.events())

    def active_events(self) -> tuple[SessionEvent, ...]:
        by_seq = {event.seq: event for event in self.store.events()}
        return tuple(by_seq[seq] for seq in self.active_seqs())

    def derive_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        for event in self.active_events():
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


def _fold_active_seqs(events: tuple[SessionEvent, ...]) -> tuple[int, ...]:
    """Fold the log into the active surface, applying replace ops in order."""
    active: list[int] = []
    for event in events:
        op = event.surface_op
        if op is not None and event.event_type not in SURFACE_EVENT_TYPES:
            raise ValueError(
                f"surface_op on non-surface event {event.event_type!r}",
            )
        if event.event_type not in SURFACE_EVENT_TYPES:
            continue
        if op is None or op == "append":
            active.append(event.seq)
            continue
        if not isinstance(op, Mapping) or op.get("op") != "replace":
            raise ValueError(f"unsupported surface_op {op!r}")
        start, end = op["start"], op["end"]
        replaced = [seq for seq in active if start <= seq <= end]
        if start not in active or end not in active or not replaced:
            raise ValueError(
                f"replace range [{start},{end}] not on active surface",
            )
        if not set(replaced).issubset(set(event.source_event_seqs)):
            raise ValueError(
                "source_event_seqs missing replaced surface nodes",
            )
        if event.event_type == TOOL_RESULT:
            if len(replaced) != 1:
                raise ValueError(
                    "tool/result replacement must replace exactly one node",
                )
            original = next(e for e in events if e.seq == replaced[0])
            if original.event_type != TOOL_RESULT or not _tool_payloads_match(
                original.payload,
                event.payload,
            ):
                raise ValueError(
                    "tool/result replacement changed fields other than content",
                )
        active = [seq for seq in active if not (start <= seq <= end)]
        active.append(event.seq)
    return tuple(active)


def _tool_payloads_match(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    pa = dict(a)
    pb = dict(b)
    pa.pop("content", None)
    pb.pop("content", None)
    return pa == pb
