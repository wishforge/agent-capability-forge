"""Phase 4-C: minimal context projection + compaction.

All token counts are PHASE-4C ESTIMATION (fixed chars/4 + overhead), not
provider-precise accounting. Summaries use the PHASE-4C TEST SUMMARIZER, not
a production LLM summarizer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Callable

from event_store import EventStore
from events import (
    AGENT_REQUEST,
    ASSISTANT_MESSAGE,
    COMPACTION_END,
    COMPACTION_PRUNE,
    COMPACTION_START,
    COMPACTION_SUMMARY,
    REQUEST_HEADER,
    STEP_END,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)
from surface import Message, SurfaceProjection
from turn_step import Session

RETRY = "RETRY"
NO_RETRY = "NO_RETRY"
FAILED = "FAILED"
CONTEXT_WINDOW_EXCEEDED = "CONTEXT_WINDOW_EXCEEDED"

PHASE4C_ESTIMATION = "PHASE-4C ESTIMATION"
PHASE4C_TEST_SUMMARIZER = "PHASE-4C TEST SUMMARIZER"

CHARS_PER_TOKEN = 4
ROLE_OVERHEAD = 4

# ponytail: single-process busy registry; replace with a real lock/lease if
# multi-process or threaded compaction is ever needed.
_SESSION_BUSY: set[str] = set()


def _acquire(session_id: str) -> None:
    if session_id in _SESSION_BUSY:
        raise CompactionError("busy", "compaction already active")
    _SESSION_BUSY.add(session_id)


def _release(session_id: str) -> None:
    _SESSION_BUSY.discard(session_id)


def _unmatched_compaction_start(store: EventStore) -> bool:
    started = False
    for event in store.events():
        if event.event_type == COMPACTION_START:
            started = True
        elif event.event_type == COMPACTION_END:
            started = False
    return started


class CompactionError(Exception):
    """Explicit compaction failure: busy/cancelled/changed/summary/commit."""

    def __init__(self, category: str, message: str = "") -> None:
        super().__init__(message or category)
        self.category = category


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    system_tokens: int
    tools_tokens: int
    message_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.system_tokens + self.tools_tokens + self.message_tokens


@dataclass(frozen=True, slots=True)
class TokenMeter:
    """Fixed heuristic estimator; not a provider tokenizer (PHASE-4C ESTIMATION)."""

    context_window: int
    threshold_ratio: float = 0.8
    retain_ratio: float = 0.16
    retain_tokens: int | None = None

    @staticmethod
    def estimate_text(text: str) -> int:
        return ceil(len(text) / CHARS_PER_TOKEN) + ROLE_OVERHEAD

    @staticmethod
    def estimate_event(event: SessionEvent) -> int:
        if event.event_type in (USER_MESSAGE, ASSISTANT_MESSAGE, TOOL_RESULT):
            text = event.payload.get("content", "")
            if event.event_type == ASSISTANT_MESSAGE:
                text += json.dumps(
                    event.payload.get("tool_calls", ()),
                    sort_keys=True,
                )
            return TokenMeter.estimate_text(text)
        return 0

    @staticmethod
    def estimate_message(message: Message) -> int:
        return TokenMeter.estimate_text(message.content)

    def threshold_tokens(self) -> int:
        return int(self.context_window * self.threshold_ratio)

    def retain_tokens_for(self) -> int:
        if self.retain_tokens is not None:
            return self.retain_tokens
        return int(self.context_window * self.retain_ratio)

    def estimate(
        self,
        messages: tuple[Message, ...] = (),
        system: str = "",
        tools: tuple[str, ...] = (),
    ) -> TokenEstimate:
        system_tokens = self.estimate_text(system) if system else 0
        tools_tokens = (
            self.estimate_text(json.dumps(tools, sort_keys=True))
            if tools
            else 0
        )
        message_tokens = sum(self.estimate_message(m) for m in messages)
        return TokenEstimate(system_tokens, tools_tokens, message_tokens)

    def pressure(self, estimate: TokenEstimate) -> bool:
        return estimate.total_tokens >= self.threshold_tokens()


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Runtime planning object; never written to the log as an event."""

    start: int
    end: int
    retained_range: tuple[int, int] | None
    summary_content: str
    source_event_seqs: tuple[int, ...]
    replace_generation: int
    reason: str
    token_before: int
    token_after: int


@dataclass(frozen=True, slots=True)
class RetryDecision:
    kind: str
    reason: str = ""
    replace_generation: int = 0


@dataclass(frozen=True, slots=True)
class ModelContext:
    """Request-time view; not persisted and not a second source of truth."""

    system_prompt: str
    tools: tuple[str, ...]
    runtime_context: str
    messages: tuple[Message, ...]
    current_input: str


def retry_safe(store: EventStore) -> bool:
    """Overflow retry is allowed only with no committed message/tool side-effect
    since the latest model request."""
    for event in reversed(store.events()):
        if event.event_type in (ASSISTANT_MESSAGE, TOOL_CALL, TOOL_RESULT):
            return False
        if event.event_type in (AGENT_REQUEST, REQUEST_HEADER):
            return True
        if event.event_type == STEP_END:
            return False
    return True


def deterministic_summarizer(
    shadowed: list[SessionEvent],
    max_chars: int,
) -> str:
    """PHASE-4C TEST SUMMARIZER: deterministic, text-only, never production."""
    joined = " | ".join(e.payload.get("content", "") for e in shadowed)
    limit = min(max_chars, 120)
    return f"<compacted-summary n={len(shadowed)}> {joined[:limit]}"


def _messages_from_events(events: tuple[SessionEvent, ...]) -> tuple[Message, ...]:
    messages: list[Message] = []
    for event in events:
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


def _surface_units(active: tuple[SessionEvent, ...]) -> list[list[SessionEvent]]:
    """Group assistant tool-call messages with their tool results so cuts never
    split a call/result pair."""
    units: list[list[SessionEvent]] = []
    i = 0
    while i < len(active):
        event = active[i]
        if event.event_type == ASSISTANT_MESSAGE and event.payload.get(
            "tool_calls",
        ):
            calls = {c["id"] for c in event.payload["tool_calls"]}
            j = i + 1
            while (
                j < len(active)
                and active[j].event_type == TOOL_RESULT
                and active[j].payload.get("tool_call_id") in calls
            ):
                j += 1
            units.append(list(active[i:j]))
            i = j
        else:
            units.append([event])
            i += 1
    return units


def _select_range(
    active: tuple[SessionEvent, ...],
    retain_tokens: int,
    meter: TokenMeter,
) -> tuple[int, int, tuple[int, int]] | None:
    units = _surface_units(active)
    if len(units) <= 1:
        return None
    first_kept = len(units)
    tokens = 0
    for u in range(len(units) - 1, -1, -1):
        tokens += sum(meter.estimate_event(e) for e in units[u])
        first_kept = u
        if tokens >= retain_tokens:
            break
    if first_kept == 0:
        return None
    return (
        units[0][0].seq,
        units[first_kept - 1][-1].seq,
        (units[first_kept][0].seq, units[-1][-1].seq),
    )


class CompactionEngine:
    def __init__(
        self,
        store: EventStore,
        meter: TokenMeter | None = None,
        summarizer: Callable[[list[SessionEvent], int], str] | None = None,
        system_prompt: str = "",
        tools: tuple[str, ...] = (),
        max_overflow_retries: int = 1,
    ) -> None:
        self.store = store
        self.meter = meter or TokenMeter(context_window=1000)
        self.summarizer = summarizer or deterministic_summarizer
        self.system_prompt = system_prompt
        self.tools = tuple(tools)
        self.max_overflow_retries = max_overflow_retries
        self.overflow_retries = 0
        self._generation = 0
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _store(self, session: Session | None) -> EventStore:
        return session.store if session is not None else self.store

    def plan(
        self,
        session: Session | None = None,
        reason: str = "pressure",
        retain_tokens: int | None = None,
    ) -> CompactionPlan | None:
        store = self._store(session)
        if self._cancelled:
            return None
        surface = SurfaceProjection(store)
        before = self.meter.estimate(
            surface.derive_messages(),
            self.system_prompt,
            self.tools,
        )
        if reason == "pressure" and not self.meter.pressure(before):
            return None
        active = surface.active_events()
        retain = (
            self.meter.retain_tokens_for()
            if retain_tokens is None
            else retain_tokens
        )
        selected = _select_range(active, retain, self.meter)
        if selected is None:
            return None
        start, end, retained_range = selected
        shadowed = [e for e in active if start <= e.seq <= end]
        summary = self._summarize(shadowed)
        after_messages = (Message("user", summary),) + _messages_from_events(
            tuple(e for e in active if retained_range[0] <= e.seq <= retained_range[1]),
        )
        after = self.meter.estimate(
            after_messages,
            self.system_prompt,
            self.tools,
        )
        return CompactionPlan(
            start=start,
            end=end,
            retained_range=retained_range,
            summary_content=summary,
            source_event_seqs=tuple(e.seq for e in shadowed),
            replace_generation=self._generation + 1,
            reason=reason,
            token_before=before.total_tokens,
            token_after=after.total_tokens,
        )

    def compact(
        self,
        session: Session | None = None,
        reason: str = "pressure",
        retain_tokens: int | None = None,
    ) -> RetryDecision:
        store = self._store(session)
        _acquire(store.session_id)
        try:
            if _unmatched_compaction_start(store):
                raise CompactionError(
                    "busy",
                    "unmatched compaction/start blocks new compaction",
                )
            if self._cancelled:
                return RetryDecision(NO_RETRY, "cancelled")
            plan = self.plan(session, reason, retain_tokens)
            if plan is None:
                if self._cancelled:
                    return RetryDecision(NO_RETRY, "cancelled")
                return RetryDecision(
                    NO_RETRY,
                    "no_pressure"
                    if reason == "pressure"
                    else "nothing_to_compact",
                )
            current = SurfaceProjection(store).active_seqs()
            if plan.start not in current or plan.end not in current:
                return RetryDecision(NO_RETRY, "changed")

            compaction_id = f"{store.session_id}/compact-{plan.replace_generation}"
            start_ev = store.append(
                SessionEvent(
                    0,
                    COMPACTION_START,
                    store.session_id,
                    payload={
                        "compaction_id": compaction_id,
                        "reason": plan.reason,
                        "replace_generation": plan.replace_generation,
                    },
                ),
            )
            try:
                summary_ev = store.append(
                    SessionEvent(
                        0,
                        COMPACTION_SUMMARY,
                        store.session_id,
                        payload={
                            "compaction_id": compaction_id,
                            "summary": plan.summary_content,
                            "shadowed_range": [plan.start, plan.end],
                            "shadowed_seqs": list(plan.source_event_seqs),
                            "shadowed_token_count": plan.token_before,
                            "provider": "deterministic-test",
                            "model": "deterministic-test",
                        },
                        source_event_seqs=(start_ev.seq,),
                    ),
                )
                if self._cancelled:
                    self._append_end(store, compaction_id, plan, "cancelled")
                    return RetryDecision(NO_RETRY, "cancelled")
                store.append(
                    SessionEvent(
                        0,
                        USER_MESSAGE,
                        store.session_id,
                        payload={
                            "content": plan.summary_content,
                            "source": {
                                "kind": "plugin",
                                "plugin": "compact",
                                "compaction_id": compaction_id,
                            },
                        },
                        surface_op={
                            "op": "replace",
                            "start": plan.start,
                            "end": plan.end,
                        },
                        source_event_seqs=(
                            start_ev.seq,
                            summary_ev.seq,
                            *plan.source_event_seqs,
                        ),
                    ),
                )
                self._append_end(store, compaction_id, plan, None)
                try:
                    store.flush()
                except Exception as exc:
                    raise CompactionError("persistence", str(exc)) from exc
            except Exception as exc:
                if isinstance(exc, CompactionError):
                    raise
                try:
                    self._append_end(store, compaction_id, plan, "commit")
                except Exception:
                    pass
                raise CompactionError("commit", str(exc)) from exc
            self._generation = plan.replace_generation
            return RetryDecision(
                RETRY if reason == "overflow" else NO_RETRY,
                "compacted",
                plan.replace_generation,
            )
        finally:
            _release(store.session_id)

    def maybe_compact(self, session: Session | None = None) -> RetryDecision:
        """Trigger A: pre-step pressure."""
        return self.compact(session, reason="pressure")

    def handle_request_error(
        self,
        error_code: str,
        session: Session | None = None,
    ) -> RetryDecision:
        """Trigger B: request error CONTEXT_WINDOW_EXCEEDED."""
        store = self._store(session)
        if error_code != CONTEXT_WINDOW_EXCEEDED:
            return RetryDecision(NO_RETRY, "not_overflow")
        if not retry_safe(store):
            return RetryDecision(NO_RETRY, "retry_not_safe")
        if self.overflow_retries >= self.max_overflow_retries:
            return RetryDecision(NO_RETRY, "max_overflow_retries")
        try:
            decision = self.compact(session, reason="overflow", retain_tokens=0)
        except CompactionError as exc:
            if exc.category in ("busy", "cancelled", "changed"):
                return RetryDecision(NO_RETRY, exc.category)
            return RetryDecision(FAILED, exc.category)
        if decision.kind == RETRY:
            self.overflow_retries += 1
        return decision

    def _summarize(self, shadowed: list[SessionEvent]) -> str:
        shadowed_tokens = sum(self.meter.estimate_event(e) for e in shadowed)
        shadowed_chars = sum(
            len(e.payload.get("content", "")) for e in shadowed
        )
        prefix = f"<compacted-summary n={len(shadowed)}> "
        max_chars = max(0, shadowed_chars - len(prefix) - 8)
        try:
            summary = self.summarizer(shadowed, max_chars)
        except Exception as exc:
            raise CompactionError("summary", str(exc)) from exc
        if self.meter.estimate_text(summary) >= shadowed_tokens:
            raise CompactionError(
                "summary",
                "summary is not smaller than shadowed surface",
            )
        return summary

    @staticmethod
    def _append_end(
        store: EventStore,
        compaction_id: str,
        plan: CompactionPlan,
        error: str | None,
    ) -> None:
        store.append(
            SessionEvent(
                0,
                COMPACTION_END,
                store.session_id,
                payload={
                    "compaction_id": compaction_id,
                    "replace_generation": plan.replace_generation,
                    "error": error,
                },
            ),
        )


def prune_tool_result(
    store: EventStore,
    seq: int,
    head: int = 80,
    tail: int = 20,
    marker: str | None = None,
) -> SessionEvent | None:
    """Independent tool-result pruning: original event stays in the log."""
    original = next(
        (e for e in store.events() if e.seq == seq),
        None,
    )
    if original is None or original.event_type != TOOL_RESULT:
        raise ValueError("prune target must be an existing tool/result event")
    content = original.payload["content"]
    if len(content) <= head + tail:
        return None
    marker = marker or f"\n…[pruned {len(content) - head - tail} chars]…\n"
    pruned = content[:head] + marker + content[-tail:]
    store.append(
        SessionEvent(
            0,
            COMPACTION_PRUNE,
            store.session_id,
            payload={
                "source_seq": seq,
                "chars_before": len(content),
                "chars_after": len(pruned),
            },
        ),
    )
    return store.append(
        SessionEvent(
            0,
            TOOL_RESULT,
            store.session_id,
            payload={**dict(original.payload), "content": pruned},
            surface_op={"op": "replace", "start": seq, "end": seq},
            source_event_seqs=(seq,),
        ),
    )


def build_model_context(
    session: Session,
    system_prompt: str = "",
    tools: tuple[str, ...] = (),
    runtime_context: str = "",
    current_input: str = "",
) -> ModelContext:
    """Request-time view: projection messages only, never capability state."""
    return ModelContext(
        system_prompt=system_prompt,
        tools=tuple(tools),
        runtime_context=runtime_context,
        messages=SurfaceProjection(session.store).derive_messages(),
        current_input=current_input,
    )


__all__ = [
    "COMPACTION_END",
    "COMPACTION_PRUNE",
    "COMPACTION_START",
    "COMPACTION_SUMMARY",
    "CONTEXT_WINDOW_EXCEEDED",
    "FAILED",
    "NO_RETRY",
    "PHASE4C_ESTIMATION",
    "PHASE4C_TEST_SUMMARIZER",
    "RETRY",
    "CompactionEngine",
    "CompactionError",
    "CompactionPlan",
    "ModelContext",
    "RetryDecision",
    "TokenEstimate",
    "TokenMeter",
    "build_model_context",
    "deterministic_summarizer",
    "prune_tool_result",
    "retry_safe",
]
