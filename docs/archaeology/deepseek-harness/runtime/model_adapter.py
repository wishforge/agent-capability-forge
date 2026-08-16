"""Phase 5-B.1 ModelAdapter: backend-neutral runtime-facing model contract.

The runtime only depends on this interface and the deterministic
ScriptedModelAdapter. Backend-specific adapters (AgentScope today, Codex
later) live under backend/adapters/ and are injected by the caller, so the
runtime never imports a concrete backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from compaction import ModelContext
from tool_runtime import ToolResult
from turn_step import ExecutionContext


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Legacy deterministic response shape kept for Phase 4-A callables."""

    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelChunk:
    content: str


@dataclass(frozen=True, slots=True)
class ModelFinal:
    content: str
    tool_calls: tuple[ModelToolCall, ...]


@dataclass(frozen=True, slots=True)
class ModelToolCallEvent:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ModelToolResultEvent:
    call_id: str
    content: str
    is_error: bool
    error_code: str | None


class ModelRequestError(Exception):
    """Uniform model failure. code is the DSH error vocabulary."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


_CONTEXT_MARKERS = (
    "CONTEXT_WINDOW_EXCEEDED",
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "token limit",
)


def classify_model_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in _CONTEXT_MARKERS):
        return "CONTEXT_WINDOW_EXCEEDED"
    return "MODEL_ERROR"


class ModelAdapter(Protocol):
    """One runtime interface for deterministic and AgentScope models."""

    delegates_tools: bool
    step_tool_results: list[ToolResult]

    async def stream(
        self,
        ctx: ExecutionContext,
        model_context: ModelContext,
    ) -> AsyncIterator[
        ModelChunk | ModelFinal | ModelToolCallEvent | ModelToolResultEvent
    ]: ...


class ScriptedModelAdapter:
    """Deterministic test model adapter: keeps Phase 4-A callable models."""

    def __init__(self, model) -> None:
        self.model = model
        self.delegates_tools = False
        self.step_tool_results: list[ToolResult] = []

    async def stream(
        self,
        ctx: ExecutionContext,
        model_context: ModelContext,
    ) -> AsyncIterator[
        ModelChunk | ModelFinal | ModelToolCallEvent | ModelToolResultEvent
    ]:
        response = await self.model(model_context.messages)
        if response.content:
            yield ModelChunk(response.content)
        calls = tuple(
            ModelToolCall(call.call_id, call.name, dict(call.arguments))
            for call in response.tool_calls
        )
        yield ModelFinal(response.content, calls)
        for call in calls:
            yield ModelToolCallEvent(call.call_id, call.name, call.arguments)


__all__ = [
    "ModelAdapter",
    "ModelChunk",
    "ModelFinal",
    "ModelRequestError",
    "ModelResponse",
    "ModelToolCall",
    "ModelToolCallEvent",
    "ModelToolResultEvent",
    "ScriptedModelAdapter",
    "classify_model_error",
]
