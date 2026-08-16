"""Phase 5-K deterministic Failure Attribution layer.

Pure read-only: ExecutionRecord + EvaluationResult -> FailureAttribution.
Never imports runtime / EventStore; never reads ContextVar; no LLM / RCA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models import FAIL

TOOL_FAILURE = "TOOL_FAILURE"
MODEL_FAILURE = "MODEL_FAILURE"
TIMEOUT = "TIMEOUT"
UNRESOLVED_TOOL = "UNRESOLVED_TOOL"
UNSAFE_RETRY = "UNSAFE_RETRY"
TURN_FAILURE = "TURN_FAILURE"
STEP_FAILURE = "STEP_FAILURE"
EXECUTION_ABORTED = "EXECUTION_ABORTED"
CONTEXT_FAILURE = "CONTEXT_FAILURE"
COMPLETION_FAILURE = "COMPLETION_FAILURE"
VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
UNKNOWN = "UNKNOWN"

MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
ATTRIBUTED = "ATTRIBUTED"
INCONCLUSIVE = "INCONCLUSIVE"

# Hierarchy depth (Phase 5-K 17 §5); only used to pick the primary candidate.
_DEPTH = {
    TOOL_FAILURE: 1,
    MODEL_FAILURE: 1,
    TIMEOUT: 1,
    UNRESOLVED_TOOL: 1,
    CONTEXT_FAILURE: 1,
    STEP_FAILURE: 2,
    UNSAFE_RETRY: 3,
    TURN_FAILURE: 4,
    EXECUTION_ABORTED: 5,
    COMPLETION_FAILURE: 5,
    VERIFICATION_FAILURE: 5,
    UNKNOWN: 5,
}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


@dataclass(frozen=True, slots=True)
class Failure:
    failure_kind: str
    rule_id: str | None
    turn_id: str | None
    step_id: str | None
    attempt_id: str | None
    evidence_refs: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class FailureAttribution:
    failure_id: str
    execution_id: str
    turn_id: str | None
    step_id: str | None
    attempt_id: str | None
    failure_kind: str | None
    evidence_refs: tuple[dict, ...]
    initiator_ref: dict | None
    owner_ref: dict | None
    context_provenance_ref: dict | None
    backend_event_refs: tuple[dict, ...]
    mapping_quality: str
    parent_ref: str | None
    ownership: str
    primary_failure: Failure | None = None
    secondary_failures: tuple[Failure, ...] = ()


def _runtime_kind(record: Any) -> str:
    attempts = tuple(_get(record, "attempts", ()) or ())
    for attempt in attempts:
        if _get(attempt, "status") == "ABORTED":
            return EXECUTION_ABORTED
    for attempt in attempts:
        error = _get(attempt, "error")
        if error == "CONTEXT_WINDOW_EXCEEDED":
            return CONTEXT_FAILURE
        if error == "MODEL_ERROR":
            return MODEL_FAILURE
    steps = tuple(_get(record, "steps", ()) or ())
    if any(_get(step, "outcome") in ("FAILED", "ABORTED") for step in steps):
        return STEP_FAILURE
    if _get(record, "turn_end_reason") == "error":
        return TURN_FAILURE
    return UNKNOWN


def _classify(record: Any, finding: Any) -> str:
    rule_id = _get(finding, "rule_id")
    if rule_id == "RULE-01":
        reason = _get(record, "turn_end_reason")
        return COMPLETION_FAILURE if reason == "max-tokens" else TURN_FAILURE
    if rule_id == "RULE-02":
        return UNRESOLVED_TOOL
    if rule_id == "RULE-03":
        return UNSAFE_RETRY
    if rule_id == "RULE-04":
        return COMPLETION_FAILURE
    if rule_id == "RULE-05":
        # Minimal kind set has no policy kind; do not guess.
        return UNKNOWN
    if rule_id == "RULE-06":
        return TOOL_FAILURE
    if rule_id == "RULE-07":
        return TIMEOUT
    if rule_id == "RULE-08":
        return _runtime_kind(record)
    if rule_id == "RULE-09":
        return COMPLETION_FAILURE
    return UNKNOWN


def _turn_id(record: Any) -> str | None:
    turns = tuple(_get(record, "turns", ()) or ())
    return _get(turns[0], "turn_id") if turns else None


def _tool_item(record: Any, call_id: str) -> dict | None:
    for group in ("tools", "tool_results", "unresolved_tools"):
        for item in tuple(_get(record, group, ()) or ()):
            if (
                _get(item, "call_id") == call_id
                or _get(item, "tool_call_id") == call_id
            ):
                return item
    return None


def _attempt(record: Any, *, status: str | None = None, error: str | None = None) -> Any | None:
    for attempt in tuple(_get(record, "attempts", ()) or ()):
        if status is not None and _get(attempt, "status") == status:
            return attempt
        if error is not None and _get(attempt, "error") == error:
            return attempt
    return None


def _resolve_ids(
    record: Any,
    finding: Any,
    kind: str,
) -> tuple[str | None, str | None, str | None]:
    turn_id = _turn_id(record)
    step_id = None
    attempt_id = None
    refs = tuple(_get(finding, "evidence_refs", ()) or ())
    for ref in refs:
        step_id = _get(ref, "step_id") or step_id
        attempt_id = _get(ref, "attempt_id") or attempt_id
    call_id = next(
        (_get(ref, "tool_call_id") for ref in refs if _get(ref, "tool_call_id")),
        None,
    )
    if call_id is not None:
        item = _tool_item(record, call_id)
        if item is not None:
            step_id = _get(item, "step_id") or step_id
            attempt_id = _get(item, "attempt_id") or attempt_id
    if kind == EXECUTION_ABORTED:
        aborted = _attempt(record, status="ABORTED")
        if aborted is not None:
            attempt_id = _get(aborted, "attempt_id") or attempt_id
            step_id = _get(aborted, "step_id") or step_id
    if kind in (MODEL_FAILURE, CONTEXT_FAILURE):
        error = "CONTEXT_WINDOW_EXCEEDED" if kind == CONTEXT_FAILURE else "MODEL_ERROR"
        failing = _attempt(record, error=error)
        if failing is not None:
            attempt_id = _get(failing, "attempt_id") or attempt_id
            step_id = _get(failing, "step_id") or step_id
    if kind == STEP_FAILURE:
        for step in tuple(_get(record, "steps", ()) or ()):
            if _get(step, "outcome") in ("FAILED", "ABORTED"):
                step_id = _get(step, "step_id") or step_id
                attempt_ids = tuple(_get(step, "attempt_ids", ()) or ())
                if attempt_ids:
                    attempt_id = attempt_ids[0] or attempt_id
                break
    return turn_id, step_id, attempt_id


def _evidence(
    finding: Any,
    turn_id: str | None,
    step_id: str | None,
    attempt_id: str | None,
) -> tuple[dict, ...]:
    refs = [
        dict(ref)
        for ref in tuple(_get(finding, "evidence_refs", ()) or ())
    ]
    for name, value in (("turn_id", turn_id), ("step_id", step_id), ("attempt_id", attempt_id)):
        if value is not None and not any(_get(ref, name) == value for ref in refs):
            refs.append({name: value})
    return tuple(refs)


def _unique_dicts(items) -> tuple[dict, ...]:
    seen: list[dict] = []
    for item in items:
        if item is None or not isinstance(item, dict):
            continue
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def _backend_event_refs(record: Any, candidates: tuple[Failure, ...]) -> tuple[dict, ...]:
    refs = []
    for candidate in candidates:
        for ref in candidate.evidence_refs:
            refs.append(_get(ref, "backend_event_ref"))
    refs.extend(tuple(_get(record, "backend_refs", ()) or ()))
    for attempt in tuple(_get(record, "attempts", ()) or ()):
        refs.append(_get(attempt, "backend_event_ref"))
    for tool in tuple(_get(record, "tools", ()) or ()):
        refs.append(_get(tool, "backend_event_ref"))
    return _unique_dicts(refs)


def _owner_ref(record: Any, candidates: tuple[Failure, ...]) -> dict | None:
    call_ids = {
        _get(ref, "tool_call_id")
        for candidate in candidates
        for ref in candidate.evidence_refs
        if _get(ref, "tool_call_id") is not None
    }
    for group in ("tools", "tool_results", "unresolved_tools"):
        for item in tuple(_get(record, group, ()) or ()):
            item_id = _get(item, "call_id") or _get(item, "tool_call_id")
            if item_id in call_ids:
                owner = _get(item, "owner_ref")
                if owner is not None:
                    return owner
    refs = tuple(_get(record, "owner_refs", ()) or ())
    return refs[0] if refs else None


def _initiator_ref(record: Any, candidates: tuple[Failure, ...]) -> dict | None:
    ref = _get(record, "initiator_ref")
    if ref is not None:
        return ref
    for candidate in candidates:
        for ref in candidate.evidence_refs:
            initiator = _get(ref, "initiator_ref")
            if initiator is not None:
                return initiator
    return None


def _mapping_quality(record: Any, candidates: tuple[Failure, ...]) -> str:
    qualities = [
        _get(item, "mapping_quality")
        for item in tuple(_get(record, "lossiness", ()) or ())
        if isinstance(_get(item, "mapping_quality"), str)
    ]
    if "LOSSY" in qualities:
        return "LOSSY"
    if "BACKEND_SPECIFIC" in qualities:
        return "BACKEND_SPECIFIC"
    if candidates or tuple(_get(record, "backend_refs", ()) or ()):
        return "EXACT"
    return "UNKNOWN"


def _select(
    candidates: tuple[Failure, ...],
) -> tuple[Failure | None, tuple[Failure, ...]]:
    if not candidates:
        return None, ()
    deepest = min(candidates, key=lambda candidate: _DEPTH[candidate.failure_kind])
    tied = [
        candidate
        for candidate in candidates
        if _DEPTH[candidate.failure_kind] == _DEPTH[deepest.failure_kind]
    ]
    if len(tied) == 1:
        return deepest, tuple(
            candidate for candidate in candidates if candidate is not deepest
        )
    return None, tuple(candidates)


def _dedupe(candidates: tuple[Failure, ...]) -> tuple[Failure, ...]:
    """Same kind at the same ids is one failure, not multiple candidates."""
    merged: list[Failure] = []
    seen: set[tuple] = set()
    for candidate in candidates:
        key = (
            candidate.failure_kind,
            candidate.turn_id,
            candidate.step_id,
            candidate.attempt_id,
        )
        if key not in seen:
            seen.add(key)
            merged.append(candidate)
    return tuple(merged)


def _failure_id(execution_id: str, candidates: tuple[Failure, ...]) -> str:
    if not candidates:
        return f"{execution_id}:NO_FAILURE"
    bits = sorted(
        f"{candidate.failure_kind}:{candidate.rule_id or 'record'}"
        for candidate in candidates
    )
    return f"{execution_id}:{'|'.join(bits)}"


def attribute(execution_record: Any, evaluation_result: Any) -> FailureAttribution:
    """Deterministic, read-only attribution of one EvaluationResult."""
    record = execution_record
    candidates = []
    for finding in tuple(_get(evaluation_result, "findings", ()) or ()):
        if _get(finding, "status") != FAIL:
            continue
        kind = _classify(record, finding)
        turn_id, step_id, attempt_id = _resolve_ids(record, finding, kind)
        candidates.append(
            Failure(
                failure_kind=kind,
                rule_id=_get(finding, "rule_id"),
                turn_id=turn_id,
                step_id=step_id,
                attempt_id=attempt_id,
                evidence_refs=_evidence(finding, turn_id, step_id, attempt_id),
            ),
        )
    candidates = _dedupe(tuple(candidates))
    primary, secondary = _select(candidates)
    execution_id = _get(record, "execution_id") or _get(
        evaluation_result, "execution_id"
    )
    anchor = primary or (candidates[0] if candidates else None)
    owner_ref = _owner_ref(record, candidates)
    return FailureAttribution(
        failure_id=_failure_id(execution_id, candidates),
        execution_id=execution_id,
        turn_id=anchor.turn_id if anchor is not None else None,
        step_id=anchor.step_id if anchor is not None else None,
        attempt_id=anchor.attempt_id if anchor is not None else None,
        failure_kind=(
            primary.failure_kind
            if primary is not None
            else MULTIPLE_CANDIDATES if len(candidates) > 1 else None
        ),
        evidence_refs=_unique_dicts(
            ref
            for candidate in candidates
            for ref in candidate.evidence_refs
        ),
        initiator_ref=_initiator_ref(record, candidates),
        owner_ref=owner_ref,
        context_provenance_ref=(
            tuple(_get(record, "context_provenance", ()) or ())[0]
            if tuple(_get(record, "context_provenance", ()) or ())
            else None
        ),
        backend_event_refs=_backend_event_refs(record, candidates),
        mapping_quality=_mapping_quality(record, candidates),
        parent_ref=_parent_ref(record, anchor.attempt_id if anchor is not None else None),
        ownership=ATTRIBUTED if owner_ref is not None else INCONCLUSIVE,
        primary_failure=primary,
        secondary_failures=secondary,
    )


def _parent_ref(record: Any, attempt_id: str | None) -> str | None:
    for attempt in tuple(_get(record, "attempts", ()) or ()):
        if attempt_id is None or _get(attempt, "attempt_id") == attempt_id:
            parent = _get(attempt, "parent_execution_id")
            if parent is not None:
                return parent
    return None


__all__ = [
    "ATTRIBUTED",
    "COMPLETION_FAILURE",
    "CONTEXT_FAILURE",
    "EXECUTION_ABORTED",
    "Failure",
    "FailureAttribution",
    "INCONCLUSIVE",
    "MODEL_FAILURE",
    "MULTIPLE_CANDIDATES",
    "STEP_FAILURE",
    "TIMEOUT",
    "TOOL_FAILURE",
    "TURN_FAILURE",
    "UNKNOWN",
    "UNRESOLVED_TOOL",
    "UNSAFE_RETRY",
    "VERIFICATION_FAILURE",
    "attribute",
]
