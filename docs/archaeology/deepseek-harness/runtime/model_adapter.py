"""Phase 4-D ModelAdapter: one runtime-facing model contract.

semantic core -> adapter -> AgentScope public API (or a deterministic test
model). The runtime only sees ModelRequest/ModelResponse/ModelStream/ModelError;
it never imports OpenAI/Anthropic/DeepSeek/AgentScope model internals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from agentscope.agent import Agent, ModelConfig, ReActConfig
from agentscope.event import (
    ModelCallEndEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import (
    AssistantMsg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
    UserMsg,
)
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionRule,
)
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit, ToolChunk

from compaction import ModelContext
from events import TOOL_RESULT
from tool_runtime import ToolCall, ToolResult, ToolRuntime
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


class AgentScopeModelAdapter:
    """AgentScope 2.0.2 public API adapter: one AgentScope reply per DSH Step.

    The Agent is rebuilt per step from the DSH surface (EventStore is the
    source of truth). AgentScope executes tools through a thin wrapper that
    delegates to the DSH ToolRuntime, so tool/call + tool/result stay in the
    semantic runtime while AgentScope owns dispatch and the model stream.
    """

    def __init__(
        self,
        model,
        tool_runtime: ToolRuntime,
        name: str = "agent",
        system_prompt: str = "",
        max_iters: int = 1,
    ) -> None:
        self.model = model
        self.tool_runtime = tool_runtime
        self.name = name
        self.system_prompt = system_prompt
        self.max_iters = max_iters
        self.model_name = getattr(model, "model", "agentscope")
        self.delegates_tools = True
        self.step_tool_results: list[ToolResult] = []
        self._active_call: tuple[str, str] | None = None
        self._result_text: dict[str, str] = {}

    async def stream(
        self,
        ctx: ExecutionContext,
        model_context: ModelContext,
    ) -> AsyncIterator[
        ModelChunk | ModelFinal | ModelToolCallEvent | ModelToolResultEvent
    ]:
        self.step_tool_results = []
        self._active_call = None
        self._result_text = {}
        state = AgentState(
            session_id=ctx.session.session_id,
            context=self._to_agentscope_messages(ctx, model_context.messages),
        )
        state.permission_context = PermissionContext(
            allow_rules={
                name: [
                    PermissionRule(
                        tool_name=name,
                        rule_content=None,
                        behavior=PermissionBehavior.ALLOW,
                        source="phase4d",
                    ),
                ]
                for name in self.tool_runtime.names()
            },
        )
        agent = Agent(
            name=self.name,
            system_prompt=self.system_prompt,
            model=self.model,
            toolkit=self._build_toolkit(ctx),
            state=state,
            model_config=ModelConfig(max_retries=0),
            react_config=ReActConfig(max_iters=self.max_iters),
        )
        text_parts: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        try:
            async for evt in agent.reply_stream(None):
                if isinstance(evt, TextBlockDeltaEvent):
                    text_parts.append(evt.delta)
                    yield ModelChunk(evt.delta)
                elif isinstance(evt, ToolCallStartEvent):
                    tool_calls[evt.tool_call_id] = {
                        "id": evt.tool_call_id,
                        "name": evt.tool_call_name,
                        "input": "",
                    }
                elif isinstance(evt, ToolCallDeltaEvent):
                    tool_calls[evt.tool_call_id]["input"] += evt.delta
                elif isinstance(evt, ToolCallEndEvent):
                    pass
                elif isinstance(evt, ModelCallEndEvent):
                    parsed = [
                        ModelToolCall(
                            tc["id"],
                            tc["name"],
                            self._parse_input(tc["input"]),
                        )
                        for tc in tool_calls.values()
                    ]
                    yield ModelFinal("".join(text_parts), tuple(parsed))
                    text_parts.clear()
                elif isinstance(evt, ToolResultStartEvent):
                    tc = tool_calls.get(evt.tool_call_id)
                    if tc is not None:
                        self._active_call = (evt.tool_call_id, tc["name"])
                        yield ModelToolCallEvent(
                            evt.tool_call_id,
                            tc["name"],
                            self._parse_input(tc["input"]),
                        )
                elif isinstance(evt, ToolResultTextDeltaEvent):
                    self._result_text.setdefault(evt.tool_call_id, "")
                    self._result_text[evt.tool_call_id] += evt.delta
                elif isinstance(evt, ToolResultEndEvent):
                    self._active_call = None
                    log_result = self._find_log_result(ctx, evt.tool_call_id)
                    if log_result is not None:
                        log_error = bool(log_result.payload.get("is_error"))
                        stream_error = evt.state != ToolResultState.SUCCESS
                        if log_error != stream_error:
                            raise RuntimeError(
                                "AgentScope/DSH tool result state mismatch: "
                                f"event={evt.state} log_is_error={log_error}",
                            )
                        yield ModelToolResultEvent(
                            evt.tool_call_id,
                            log_result.payload["content"],
                            log_error,
                            log_result.payload.get("error_code"),
                        )
                    else:
                        tc = tool_calls.get(evt.tool_call_id)
                        known = bool(
                            tc and tc["name"] in self.tool_runtime.names(),
                        )
                        yield ModelToolResultEvent(
                            evt.tool_call_id,
                            self._result_text.get(
                                evt.tool_call_id,
                                "tool execution failed",
                            ),
                            True,
                            None if known else "UNKNOWN_TOOL",
                        )
                elif isinstance(evt, ReplyEndEvent):
                    pass
        except ModelRequestError:
            raise
        except Exception as exc:
            raise ModelRequestError(
                classify_model_error(exc),
                str(exc),
            ) from exc

    def _build_toolkit(self, ctx: ExecutionContext) -> Toolkit:
        tools = []
        for name in self.tool_runtime.names():
            tools.append(self._make_tool(name, ctx))
        return Toolkit(tools=tools)

    def _make_tool(self, name: str, ctx: ExecutionContext) -> FunctionTool:
        async def wrapper(**kwargs: Any) -> ToolChunk:
            active = self._active_call
            if active is None or active[1] != name:
                raise RuntimeError(f"no active AgentScope tool call for {name}")
            call_id = active[0]
            result = await self.tool_runtime.execute(
                ToolCall(call_id, name, kwargs),
                ctx,
            )
            self.step_tool_results.append(result)
            return ToolChunk(
                content=[TextBlock(text=result.content)],
                state=(
                    ToolResultState.SUCCESS
                    if not result.is_error
                    else ToolResultState.ERROR
                ),
            )

        wrapper.__name__ = name
        return FunctionTool(
            wrapper,
            name=name,
            description="DSH capability tool",
            is_concurrency_safe=False,
        )

    def _to_agentscope_messages(self, ctx: ExecutionContext, messages):
        out = []
        calls_by_id: dict[str, dict[str, Any]] = {}
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == "user":
                out.append(UserMsg("user", msg.content))
                i += 1
            elif msg.role == "assistant":
                content: list[Any] = []
                if msg.content:
                    content.append(TextBlock(text=msg.content))
                if msg.tool_calls:
                    for call in msg.tool_calls:
                        calls_by_id[call["id"]] = call
                        content.append(
                            ToolCallBlock(
                                id=call["id"],
                                name=call["name"],
                                input=json.dumps(
                                    call.get("arguments") or {},
                                    sort_keys=True,
                                ),
                                state=ToolCallState.FINISHED,
                            ),
                        )
                j = i + 1
                while j < len(messages) and messages[j].role == "tool":
                    tool_msg = messages[j]
                    call = calls_by_id.get(tool_msg.tool_call_id)
                    content.append(
                        ToolResultBlock(
                            id=tool_msg.tool_call_id,
                            name=call["name"] if call else "",
                            output=[TextBlock(text=tool_msg.content)],
                            state=(
                                ToolResultState.ERROR
                                if self._tool_result_is_error(
                                    ctx,
                                    tool_msg.tool_call_id,
                                )
                                else ToolResultState.SUCCESS
                            ),
                        ),
                    )
                    j += 1
                out.append(AssistantMsg(self.name, content))
                i = j
            else:
                raise ValueError(f"unsupported DSH message role {msg.role!r}")
        return out

    @staticmethod
    def _find_log_result(ctx: ExecutionContext, call_id: str):
        for event in reversed(ctx.store.events()):
            if (
                event.event_type == TOOL_RESULT
                and event.payload.get("tool_call_id") == call_id
            ):
                return event
        return None

    @staticmethod
    def _tool_result_is_error(ctx: ExecutionContext, call_id: str) -> bool:
        result = AgentScopeModelAdapter._find_log_result(ctx, call_id)
        return bool(result and result.payload.get("is_error"))

    @staticmethod
    def _parse_input(raw: str) -> dict:
        if not raw.strip():
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {"raw": value}
        except json.JSONDecodeError:
            return {"raw": raw}


__all__ = [
    "AgentScopeModelAdapter",
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
