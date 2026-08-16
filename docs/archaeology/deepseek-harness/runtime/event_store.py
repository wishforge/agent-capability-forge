"""Phase 4-A in-memory / Phase 4-B JSONL append-only EventStore.

DURABILITY:
PHASE-4B ASSUMPTION (A1): appends are flushed to the OS, but flush != fsync;
physical durability semantics are implementation-defined.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from events import AGENT_REQUEST, REQUEST_HEADER, SessionEvent


def _disk_type(event_type: str) -> str:
    # A10: agent/request is runtime-only; its durable surrogate is request/header.
    return REQUEST_HEADER if event_type == AGENT_REQUEST else event_type


def _encode(event: SessionEvent) -> str:
    return json.dumps(
        {
            "seq": event.seq,
            "event_type": _disk_type(event.event_type),
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "step_id": event.step_id,
            "payload": dict(event.payload),
            "timestamp": event.timestamp,
            "source_event_seqs": list(event.source_event_seqs),
            "surface_op": (
                dict(event.surface_op)
                if isinstance(event.surface_op, Mapping)
                else event.surface_op
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode(data: dict) -> SessionEvent:
    return SessionEvent(
        seq=data["seq"],
        event_type=data["event_type"],
        session_id=data["session_id"],
        turn_id=data.get("turn_id"),
        step_id=data.get("step_id"),
        payload=dict(data.get("payload") or {}),
        timestamp=data.get(
            "timestamp",
            datetime.now(timezone.utc).isoformat(),
        ),
        source_event_seqs=tuple(data.get("source_event_seqs") or ()),
        surface_op=data.get("surface_op"),
    )


class EventStore:
    """Monotonic, append-only event log for one Session.

    With path=None this keeps the Phase 4-A in-memory behavior. With path set,
    every append is written as one UTF-8 JSON line; open() reloads the log and
    repair_tail() truncates a corrupt trailing region.
    """

    def __init__(self, session_id: str, path: str | Path | None = None) -> None:
        self.session_id = session_id
        self._events: list[SessionEvent] = []
        self._path = Path(path) if path is not None else None
        self._file = None
        self._invalid_tail_start: int | None = None

    def append(self, event: SessionEvent) -> SessionEvent:
        if event.session_id != self.session_id:
            raise ValueError(
                f"event session {event.session_id!r} != store session "
                f"{self.session_id!r}",
            )
        if self._path is not None:
            self._ensure_open()
            if self._invalid_tail_start is not None:
                self.repair_tail()
        next_seq = self.last_seq() + 1
        if event.seq != 0 and event.seq != next_seq:
            raise ValueError(
                f"seq {event.seq} rejected: expected 0 (auto) or {next_seq}; "
                "append-only sequences are continuous and never reused",
            )
        stored = replace(event, seq=next_seq)
        self._events.append(stored)
        if self._path is not None:
            self._file.write(_encode(stored) + "\n")
            self._file.flush()
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

    # --- Phase 4-B persistence API ---

    def read_all(self) -> tuple[SessionEvent, ...]:
        return self.events()

    def read_from(self, seq: int) -> tuple[SessionEvent, ...]:
        return tuple(event for event in self._events if event.seq >= seq)

    def open(self) -> None:
        """(Re)open the JSONL log and reload all complete events."""
        if self._path is None:
            return
        if self._file is not None:
            self.close()
        self._file = self._path.open("a", encoding="utf-8", newline="\n")
        self._load()

    def close(self) -> None:
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

    def flush(self) -> None:
        """Flush to the OS. flush != fsync (PHASE-4B ASSUMPTION A1)."""
        if self._file is not None:
            self._file.flush()

    def repair_tail(self) -> bool:
        """Truncate the first unreadable tail line; keep the valid prefix.

        PHASE-4B ASSUMPTION (A3): repair keeps the longest valid prefix and
        drops everything from the first invalid line onward.
        """
        if self._path is None:
            return False
        self._ensure_open()
        if self._invalid_tail_start is None:
            return False
        self._file.truncate(self._invalid_tail_start)
        self._file.flush()
        self._invalid_tail_start = None
        return True

    def _ensure_open(self) -> None:
        if self._path is not None and (self._file is None or self._file.closed):
            self.open()

    def _load(self) -> None:
        events: list[SessionEvent] = []
        invalid_start: int | None = None
        raw = self._path.read_bytes() if self._path.exists() else b""
        parts = raw.split(b"\n")
        offset = 0
        for i, part in enumerate(parts):
            line_start = offset
            offset += len(part) + 1
            if i == len(parts) - 1:
                if part == b"":
                    break  # terminator newline (or empty file)
                invalid_start = line_start  # unterminated final line
                break
            if not part.strip():
                invalid_start = line_start
                break
            try:
                event = _decode(json.loads(part.decode("utf-8")))
            except Exception:
                invalid_start = line_start
                break
            if (
                event.seq != len(events) + 1
                or event.session_id != self.session_id
            ):
                invalid_start = line_start
                break
            events.append(event)
        self._events = events
        self._invalid_tail_start = invalid_start
