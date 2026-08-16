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
EXECUTION_ATTEMPT_START = "execution/attempt/start"
EXECUTION_ATTEMPT_END = "execution/attempt/end"
AGENT_REQUEST = "agent/request"
REQUEST_HEADER = "request/header"
ASSISTANT_CHUNK = "assistant/chunk"
ASSISTANT_MESSAGE = "assistant/message"
TOOL_CALL = "tool/call"
TOOL_RESULT = "tool/result"
COMPACTION_START = "compaction/start"
COMPACTION_SUMMARY = "compaction/summary"
COMPACTION_END = "compaction/end"
COMPACTION_PRUNE = "compaction/prune"

SURFACE_EVENT_TYPES = frozenset({USER_MESSAGE, ASSISTANT_MESSAGE, TOOL_RESULT})


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
    surface_op: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "source_event_seqs", tuple(self.source_event_seqs))
        if isinstance(self.surface_op, Mapping):
            object.__setattr__(
                self,
                "surface_op",
                MappingProxyType(dict(self.surface_op)),
            )
