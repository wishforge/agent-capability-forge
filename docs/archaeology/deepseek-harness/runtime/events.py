"""Phase 4-A SessionEvent schema (in-memory execution truth)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

USER_MESSAGE = "user/message"
TURN_START = "turn/start"
TURN_END = "turn/end"
STEP_START = "step/start"
STEP_END = "step/end"
AGENT_REQUEST = "agent/request"
ASSISTANT_CHUNK = "assistant/chunk"
ASSISTANT_MESSAGE = "assistant/message"
TOOL_CALL = "tool/call"
TOOL_RESULT = "tool/result"


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One append-only event. Payload is a read-only mapping after init."""

    seq: int
    event_type: str
    session_id: str
    turn_id: str | None = None
    step_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    source_event_seqs: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "source_event_seqs", tuple(self.source_event_seqs))
