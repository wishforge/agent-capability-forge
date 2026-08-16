"""Phase 5-I deterministic rules.

Rules only read the ExecutionRecord + TaskSpecification passed to them.
Missing evidence is reported INCONCLUSIVE; LOSSY is never treated as EXACT.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from models import FAIL, INCONCLUSIVE, PASS, Finding, TaskSpecification


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _tools(record: Any) -> tuple:
    return tuple(_get(record, "tools", ()) or ())


def _results(record: Any) -> tuple | None:
    results = _get(record, "tool_results", None)
    return None if results is None else tuple(results)


def _attempts(record: Any) -> tuple:
    return tuple(_get(record, "attempts", ()) or ())


def _call_id(item: Any) -> str | None:
    return _get(item, "call_id") or _get(item, "tool_call_id")


def _mapping_quality(item: Any) -> str | None:
    quality = _get(item, "mapping_quality")
    if isinstance(quality, str) and quality == "LOSSY":
        return quality
    meta = _get(item, "backend_metadata")
    if isinstance(meta, Mapping) and _get(meta, "mapping_quality") == "LOSSY":
        return "LOSSY"
    return None


def _evidence(record: Any, tool: Any = None, attempt: Any = None, **extra) -> dict:
    ref = {"execution_id": _get(record, "execution_id")}
    if tool is not None:
        ref["tool_call_id"] = _call_id(tool)
        backend_ref = _get(tool, "backend_event_ref")
        if backend_ref is not None:
            ref["backend_event_ref"] = backend_ref
        seq = _get(tool, "seq")
        if seq is not None:
            ref["event_ref"] = seq
    if attempt is not None:
        ref["attempt_id"] = _get(attempt, "attempt_id")
        ref["step_id"] = _get(attempt, "step_id")
    ref.update(extra)
    return {key: value for key, value in ref.items() if value is not None}


def _finding(
    rule_id: str,
    status: str,
    message: str,
    evidence: tuple[dict, ...],
) -> Finding:
    severity = {
        PASS: "info",
        INCONCLUSIVE: "warning",
        FAIL: "error",
    }[status]
    return Finding(rule_id, status, severity, message, evidence)


def rule_01_turn_completed(record: Any, spec: TaskSpecification) -> Finding:
    reason = _get(record, "turn_end_reason", _get(record, "turn_outcome"))
    if reason is None:
        return _finding(
            "RULE-01",
            INCONCLUSIVE,
            "turn outcome not in ExecutionRecord",
            (_evidence(record),),
        )
    if reason == "completed":
        return _finding(
            "RULE-01",
            PASS,
            "turn completed",
            (_evidence(record),),
        )
    return _finding(
        "RULE-01",
        FAIL,
        f"turn ended with {reason!r}, not completed",
        (_evidence(record),),
    )


def rule_02_no_unresolved_tool(record: Any, spec: TaskSpecification) -> Finding:
    calls = _tools(record)
    results = _results(record)
    if results is None:
        return _finding(
            "RULE-02",
            INCONCLUSIVE,
            "tool results not in ExecutionRecord; unresolved tools cannot be determined",
            (_evidence(record),),
        )
    resolved = {_call_id(result) for result in results}
    unresolved = [call for call in calls if _call_id(call) not in resolved]
    if unresolved:
        return _finding(
            "RULE-02",
            FAIL,
            f"{len(unresolved)} tool call(s) have no tool result",
            tuple(_evidence(record, tool=call) for call in unresolved),
        )
    return _finding(
        "RULE-02",
        PASS,
        "all tool calls have a matching tool result",
        (_evidence(record),),
    )


def rule_03_no_unsafe_retry(record: Any, spec: TaskSpecification) -> Finding:
    attempts = _attempts(record)
    if not attempts:
        return _finding(
            "RULE-03",
            INCONCLUSIVE,
            "attempts not in ExecutionRecord",
            (_evidence(record),),
        )
    unsafe = [
        attempt
        for attempt in attempts
        if "UNSAFE_RETRY_BLOCKED" in str(_get(attempt, "reason", ""))
    ]
    if unsafe:
        return _finding(
            "RULE-03",
            FAIL,
            "unsafe retry was blocked",
            tuple(_evidence(record, attempt=attempt) for attempt in unsafe),
        )
    return _finding(
        "RULE-03",
        PASS,
        "no unsafe retry evidence",
        (_evidence(record),),
    )


def rule_04_all_required_tools_called(
    record: Any,
    spec: TaskSpecification,
) -> Finding:
    required = tuple(spec.required_tools or ())
    if not required:
        return _finding(
            "RULE-04",
            PASS,
            "no required tools specified",
            (_evidence(record),),
        )
    calls = _tools(record)
    if not calls and _get(record, "tools", None) is None:
        return _finding(
            "RULE-04",
            INCONCLUSIVE,
            "tool calls not in ExecutionRecord",
            (_evidence(record),),
        )
    called = {_get(call, "name") for call in calls}
    missing = [name for name in required if name not in called]
    if missing:
        return _finding(
            "RULE-04",
            FAIL,
            "required tools not called: " + ", ".join(missing),
            tuple(_evidence(record, required_tool=name) for name in missing),
        )
    return _finding(
        "RULE-04",
        PASS,
        "all required tools called",
        (_evidence(record),),
    )


def rule_05_no_forbidden_tool_called(
    record: Any,
    spec: TaskSpecification,
) -> Finding:
    forbidden = set(spec.forbidden_tools or ())
    if not forbidden:
        return _finding(
            "RULE-05",
            PASS,
            "no forbidden tools specified",
            (_evidence(record),),
        )
    calls = _tools(record)
    if not calls and _get(record, "tools", None) is None:
        return _finding(
            "RULE-05",
            INCONCLUSIVE,
            "tool calls not in ExecutionRecord",
            (_evidence(record),),
        )
    hits = [call for call in calls if _get(call, "name") in forbidden]
    if hits:
        return _finding(
            "RULE-05",
            FAIL,
            "forbidden tool called: "
            + ", ".join(_get(call, "name") for call in hits),
            tuple(_evidence(record, tool=call) for call in hits),
        )
    return _finding(
        "RULE-05",
        PASS,
        "no forbidden tool called",
        (_evidence(record),),
    )


def rule_06_required_tool_succeeded(
    record: Any,
    spec: TaskSpecification,
) -> Finding:
    required = tuple(spec.required_tools or ())
    if not required:
        return _finding(
            "RULE-06",
            PASS,
            "no required tools specified",
            (_evidence(record),),
        )
    results = _results(record)
    if results is None:
        return _finding(
            "RULE-06",
            INCONCLUSIVE,
            "tool results not in ExecutionRecord; required tool success cannot be verified",
            (_evidence(record),),
        )
    by_call_id = {_call_id(result): result for result in results}
    for name in required:
        call = next(
            (call for call in _tools(record) if _get(call, "name") == name),
            None,
        )
        if call is None:
            continue  # RULE-04 reports the missing call
        result = by_call_id.get(_call_id(call))
        if result is None:
            return _finding(
                "RULE-06",
                INCONCLUSIVE,
                f"result for required tool {name!r} missing",
                (_evidence(record, tool=call),),
            )
        if bool(_get(result, "is_error", False)):
            return _finding(
                "RULE-06",
                FAIL,
                f"required tool {name!r} failed: "
                + str(_get(result, "error_code", "UNKNOWN")),
                (_evidence(record, tool=result),),
            )
        if _mapping_quality(result) == "LOSSY":
            return _finding(
                "RULE-06",
                INCONCLUSIVE,
                f"required tool {name!r} result is LOSSY; "
                "success cannot be treated as EXACT",
                (_evidence(record, tool=result),),
            )
    return _finding(
        "RULE-06",
        PASS,
        "all called required tools succeeded",
        (_evidence(record),),
    )


def rule_07_no_timeout(record: Any, spec: TaskSpecification) -> Finding:
    if _get(record, "timed_out", False) is True:
        return _finding(
            "RULE-07",
            FAIL,
            "execution marked timed out",
            (_evidence(record),),
        )
    results = _results(record)
    if results is not None:
        timed_out = [
            result
            for result in results
            if "TIMEOUT" in str(_get(result, "error_code", "")).upper()
        ]
        if timed_out:
            return _finding(
                "RULE-07",
                FAIL,
                "tool call timed out",
                tuple(_evidence(record, tool=result) for result in timed_out),
            )
        if any(_mapping_quality(result) == "LOSSY" for result in results):
            return _finding(
                "RULE-07",
                INCONCLUSIVE,
                "tool results include LOSSY mapping; "
                "absence of timeout cannot be treated as EXACT",
                (_evidence(record),),
            )
        return _finding(
            "RULE-07",
            PASS,
            "no timeout evidence",
            (_evidence(record),),
        )
    attempts = _attempts(record)
    timed_out = [
        attempt
        for attempt in attempts
        if "TIMEOUT"
        in str(_get(attempt, "error", "")) + str(_get(attempt, "reason", ""))
    ]
    if timed_out:
        return _finding(
            "RULE-07",
            FAIL,
            "attempt marked timed out",
            tuple(_evidence(record, attempt=attempt) for attempt in timed_out),
        )
    return _finding(
        "RULE-07",
        INCONCLUSIVE,
        "tool results not in ExecutionRecord; timeout cannot be ruled out",
        (_evidence(record),),
    )


def rule_08_no_internal_runtime_failure(
    record: Any,
    spec: TaskSpecification,
) -> Finding:
    turn_reason = _get(record, "turn_end_reason", _get(record, "turn_outcome"))
    attempts = _attempts(record)
    if turn_reason == "error":
        return _finding(
            "RULE-08",
            FAIL,
            "turn ended with internal runtime error",
            (_evidence(record),),
        )
    for attempt in attempts:
        reason = str(_get(attempt, "reason", ""))
        if reason == "interrupted" or reason == "UNSAFE_RETRY_BLOCKED":
            continue
        if _get(attempt, "status") == "ABORTED":
            return _finding(
                "RULE-08",
                FAIL,
                f"attempt aborted internally: {reason}",
                (_evidence(record, attempt=attempt),),
            )
    if not attempts and turn_reason is None:
        return _finding(
            "RULE-08",
            INCONCLUSIVE,
            "attempts and turn outcome not in ExecutionRecord",
            (_evidence(record),),
        )
    return _finding(
        "RULE-08",
        PASS,
        "no internal runtime failure evidence",
        (_evidence(record),),
    )


def rule_09_terminal_condition(record: Any, spec: TaskSpecification) -> Finding:
    condition = spec.terminal_condition
    if condition is None:
        return _finding(
            "RULE-09",
            PASS,
            "terminal condition not specified",
            (_evidence(record),),
        )
    try:
        satisfied = bool(condition(record))
    except Exception as exc:  # noqa: BLE001 - a broken predicate is inconclusive
        return _finding(
            "RULE-09",
            INCONCLUSIVE,
            f"terminal condition could not be evaluated: {exc}",
            (_evidence(record),),
        )
    if satisfied:
        return _finding(
            "RULE-09",
            PASS,
            "terminal condition satisfied",
            (_evidence(record),),
        )
    return _finding(
        "RULE-09",
        FAIL,
        "terminal condition not satisfied",
        (_evidence(record, task_id=spec.task_id),),
    )


def rule_10_execution_replayable(record: Any, spec: TaskSpecification) -> Finding:
    replay_ref = _get(record, "replay_ref")
    if replay_ref is None:
        return _finding(
            "RULE-10",
            INCONCLUSIVE,
            "replay_ref not in ExecutionRecord",
            (_evidence(record),),
        )
    missing = [
        field
        for field in (
            "record_version",
            "projection_rule_version",
            "execution_id",
            "session_id",
        )
        if _get(record, field) is None
    ]
    if missing:
        return _finding(
            "RULE-10",
            INCONCLUSIVE,
            "record identity fields missing: " + ", ".join(missing),
            (_evidence(record),),
        )
    return _finding(
        "RULE-10",
        PASS,
        "execution is replayable from the record",
        (_evidence(record, replay_ref=replay_ref),),
    )


def rule_11_attribution_evidence(record: Any, spec: TaskSpecification) -> Finding:
    initiator_ref = _get(record, "initiator_ref")
    if initiator_ref is None:
        return _finding(
            "RULE-11",
            INCONCLUSIVE,
            "initiator_ref missing; attribution cannot be determined",
            (_evidence(record),),
        )
    return _finding(
        "RULE-11",
        PASS,
        "initiator evidence available",
        (_evidence(record, initiator_ref=initiator_ref),),
    )


def rule_12_ownership_evidence(record: Any, spec: TaskSpecification) -> Finding:
    owner_refs = _get(record, "owner_refs", ()) or ()
    if not owner_refs:
        return _finding(
            "RULE-12",
            INCONCLUSIVE,
            "owner_refs missing; ownership cannot be determined",
            (_evidence(record),),
        )
    return _finding(
        "RULE-12",
        PASS,
        "ownership evidence available",
        (_evidence(record, owner_refs=list(owner_refs)),),
    )


def rule_13_context_evidence(record: Any, spec: TaskSpecification) -> Finding:
    provenance = _get(record, "context_provenance", ()) or ()
    if not provenance:
        return _finding(
            "RULE-13",
            INCONCLUSIVE,
            "context provenance missing; context evidence unavailable",
            (_evidence(record),),
        )
    return _finding(
        "RULE-13",
        PASS,
        "context provenance evidence available",
        (_evidence(record, context_provenance_ref=provenance),),
    )


RULES = (
    ("RULE-01", rule_01_turn_completed),
    ("RULE-02", rule_02_no_unresolved_tool),
    ("RULE-03", rule_03_no_unsafe_retry),
    ("RULE-04", rule_04_all_required_tools_called),
    ("RULE-05", rule_05_no_forbidden_tool_called),
    ("RULE-06", rule_06_required_tool_succeeded),
    ("RULE-07", rule_07_no_timeout),
    ("RULE-08", rule_08_no_internal_runtime_failure),
    ("RULE-09", rule_09_terminal_condition),
    ("RULE-10", rule_10_execution_replayable),
    ("RULE-11", rule_11_attribution_evidence),
    ("RULE-12", rule_12_ownership_evidence),
    ("RULE-13", rule_13_context_evidence),
)

__all__ = ["RULES"]
