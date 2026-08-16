"""Phase 5-C minimal Codex rollout JSONL adapter.

Boundary: C (pinned rollout JSONL, openai/codex @
279b93242cfef379e65da97e87e44b83c5934fd7). The adapter translates
RolloutItem lines into ModelAdapter events. The Unified ToolRuntime owns
actual tool execution (delegates_tools=False), so Codex-native tool outputs
remain raw evidence in mapping metadata; Codex-specific logic never enters
the semantic core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from compaction import ModelContext
from model_adapter import (
    ModelChunk,
    ModelFinal,
    ModelRequestError,
    ModelToolCall,
    ModelToolCallEvent,
)
from turn_step import ExecutionContext

EXACT = "EXACT"
ADAPTER = "ADAPTER"
LOSSY = "LOSSY"
BACKEND_SPECIFIC = "BACKEND_SPECIFIC"

# Phase 5-A/5-B established lossiness contract (23 §2); all remain visible.
MISSING_SEMANTICS = (
    "STEP_BOUNDARY_PERSISTED",
    "EXEC_FAILURE_STRUCTURED_SUCCESS",
    "CHUNK_TO_MESSAGE_LINEAGE",
    "CRASH_OUTCOME_NATIVE_MARKER",
    "AMBIENT_INITIATOR",
    "COMPACTION_RETRY_SAME_STEP",
)

_CALL_TYPES = {"function_call", "custom_tool_call"}
_OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}


@dataclass(frozen=True, slots=True)
class BackendMappingMetadata:
    """Per-item translation metadata; never silently swallows lossiness."""

    backend: str = "codex"
    mapping_quality: str = ADAPTER
    missing_semantics: tuple[str, ...] = MISSING_SEMANTICS
    raw_event_ref: dict[str, Any] | None = None
    source_event_type: str | None = None


class CodexAdapter:
    """One pinned-format Codex rollout JSONL -> ModelAdapter stream.

    Each sampling request (assistant message + its tool activity) becomes one
    segment; AgentRuntime maps each segment to one Unified Step.
    """

    delegates_tools = False
    model_name = "codex"

    def __init__(
        self,
        rollout_path: str | Path,
        model_name: str | None = None,
    ) -> None:
        self.rollout_path = Path(rollout_path)
        self.model_name = model_name or "codex"
        self.step_tool_results: list = []
        self.segments: tuple[
            tuple[
                ModelChunk | ModelFinal | ModelToolCallEvent,
                ...,
            ],
            ...,
        ] = ()
        self.mapping_metadata = BackendMappingMetadata(
            raw_event_ref={
                "rollout_path": str(self.rollout_path),
                "line": None,
            },
            source_event_type="session_meta",
        )
        self.ownership_metadata = BackendMappingMetadata(
            mapping_quality=BACKEND_SPECIFIC,
            raw_event_ref={
                "rollout_path": str(self.rollout_path),
                "line": None,
            },
            source_event_type="session_meta",
        )
        self.turn_metadata: BackendMappingMetadata | None = None
        self.step_metadata: tuple[BackendMappingMetadata, ...] = ()
        self.call_metadata: dict[str, BackendMappingMetadata] = {}
        self.error_metadata: BackendMappingMetadata | None = None
        self._index = 0
        self._fatal_error: tuple[int, str] | None = None
        self._load()

    def request(
        self,
        index: int = 0,
    ) -> tuple[ModelChunk | ModelFinal | ModelToolCallEvent, ...]:
        """Adapter-side convenience: one parsed sampling request's events."""
        return self.segments[index]

    async def stream(
        self,
        ctx: ExecutionContext,
        model_context: ModelContext,
    ) -> AsyncIterator[
        ModelChunk | ModelFinal | ModelToolCallEvent
    ]:
        if self._fatal_error is not None and self._index >= len(self.segments):
            line_no, message = self._fatal_error
            raise ModelRequestError(
                "MODEL_ERROR",
                f"codex error (rollout line {line_no}): {message}",
            )
        if self._index < len(self.segments):
            segment = self.segments[self._index]
            self._index += 1
            for event in segment:
                yield event

    # --- parsing -----------------------------------------------------------

    def _load(self) -> None:
        lines = self.rollout_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError("empty codex rollout")
        records = []
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid codex rollout line {line_no}: {exc}",
                ) from exc
            records.append((line_no, data.get("type"), data.get("payload") or {}))

        turn_started = False
        turn_completed = False
        current: _Segment | None = None
        segments: list[tuple[ModelChunk | ModelFinal | ModelToolCallEvent, ...]] = []
        step_refs: list[BackendMappingMetadata] = []

        for line_no, item_type, payload in records:
            if item_type == "session_meta":
                if self.mapping_metadata.raw_event_ref.get("line") is None:
                    ref = {
                        "rollout_path": str(self.rollout_path),
                        "line": line_no,
                    }
                    self.mapping_metadata = BackendMappingMetadata(
                        raw_event_ref=ref,
                        source_event_type="session_meta",
                    )
                    self.ownership_metadata = BackendMappingMetadata(
                        mapping_quality=BACKEND_SPECIFIC,
                        raw_event_ref=ref,
                        source_event_type="session_meta",
                    )
                continue
            if item_type == "event_msg":
                self._handle_event(payload, line_no)
                ev_type = payload.get("type")
                if ev_type == "task_started":
                    if turn_started:
                        raise ValueError(
                            "phase-5c golden path: one turn per rollout",
                        )
                    turn_started = True
                elif ev_type == "task_complete":
                    turn_completed = True
                continue
            if item_type != "response_item":
                continue
            rtype = payload.get("type")
            if rtype == "message":
                if payload.get("role") == "assistant":
                    if current is not None:
                        segments.append(current.events())
                        step_refs.append(current.metadata)
                    current = _Segment(
                        self.rollout_path,
                        line_no,
                        _message_text(payload),
                    )
                continue
            if rtype in _CALL_TYPES:
                if current is None:
                    raise ValueError(
                        f"tool call without assistant message (line {line_no})",
                    )
                call_id = payload.get("call_id", "")
                name = payload["name"]
                raw_args = payload.get(
                    "arguments" if rtype == "function_call" else "input",
                    "",
                )
                current.calls.append(
                    _Call(call_id, name, _parse_args(raw_args)),
                )
                self.call_metadata[call_id] = BackendMappingMetadata(
                    mapping_quality=LOSSY,
                    raw_event_ref=_ref(self.rollout_path, line_no),
                    source_event_type=rtype,
                )
                continue
            if rtype in _OUTPUT_TYPES:
                call_id = payload.get("call_id", "")
                if call_id in self.call_metadata:
                    self.call_metadata[call_id] = BackendMappingMetadata(
                        mapping_quality=EXACT,
                        raw_event_ref=_ref(self.rollout_path, line_no),
                        source_event_type=rtype,
                    )
                else:
                    # Unpaired output: record lossiness, never guess.
                    self.call_metadata[f"output:{call_id}"] = (
                        BackendMappingMetadata(
                            mapping_quality=LOSSY,
                            raw_event_ref=_ref(self.rollout_path, line_no),
                            source_event_type=rtype,
                        )
                    )
                continue

        if not turn_started:
            raise ValueError("codex rollout has no task_started event")
        if self._fatal_error is None and not turn_completed:
            raise ValueError("codex rollout has no task_complete event")
        if current is not None:
            segments.append(current.events())
            step_refs.append(current.metadata)
        if not segments:
            raise ValueError("codex rollout has no assistant message")
        last = segments[-1]
        if self._fatal_error is None and any(
            isinstance(e, ModelFinal) and e.tool_calls
            for e in last
        ):
            raise ValueError(
                "phase-5c golden path: rollout has no terminal answer segment",
            )
        self.segments = tuple(segments)
        self.step_metadata = tuple(step_refs)

    def _handle_event(self, payload: dict, line_no: int) -> None:
        ev_type = payload.get("type")
        if ev_type == "task_started":
            self.turn_metadata = BackendMappingMetadata(
                mapping_quality=ADAPTER,
                raw_event_ref=_ref(self.rollout_path, line_no),
                source_event_type="task_started",
            )
        elif ev_type == "error":
            self._fatal_error = (line_no, payload.get("message", "codex error"))
            self.error_metadata = BackendMappingMetadata(
                mapping_quality=LOSSY,
                raw_event_ref=_ref(self.rollout_path, line_no),
                source_event_type="error",
            )
        # user_message / raw_response_item / exec_* are log-only projections;
        # ResponseItem is canonical and already translated above.


def _ref(rollout_path: Path, line_no: int) -> dict[str, Any]:
    return {"rollout_path": str(rollout_path), "line": line_no}


def _message_text(payload: dict) -> str:
    return "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "output_text"
    )


def _parse_args(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"raw": value}


class _Call:
    __slots__ = ("call_id", "name", "arguments")

    def __init__(self, call_id: str, name: str, arguments: dict) -> None:
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _Segment:
    """Accumulates one sampling request; flattened at flush time."""

    def __init__(self, rollout_path: Path, start_line: int, text: str) -> None:
        self.rollout_path = rollout_path
        self.start_line = start_line
        self.text = text
        self.calls: list[_Call] = []
        self.metadata = BackendMappingMetadata(
            mapping_quality=ADAPTER,
            raw_event_ref=_ref(rollout_path, start_line),
            source_event_type="message",
        )

    def events(
        self,
    ) -> tuple[ModelChunk | ModelFinal | ModelToolCallEvent, ...]:
        chunks = [ModelChunk(self.text)] if self.text else []
        calls = tuple(
            ModelToolCall(c.call_id, c.name, c.arguments)
            for c in self.calls
        )
        events: list[ModelChunk | ModelFinal | ModelToolCallEvent] = [
            *chunks,
            ModelFinal(self.text, calls),
            *(
                ModelToolCallEvent(c.call_id, c.name, c.arguments)
                for c in self.calls
            ),
        ]
        return tuple(events)


__all__ = [
    "ADAPTER",
    "BACKEND_SPECIFIC",
    "BackendMappingMetadata",
    "CodexAdapter",
    "EXACT",
    "LOSSY",
]
