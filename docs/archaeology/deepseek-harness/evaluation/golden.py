"""Phase 5-I golden deterministic tasks: TaskSpecification + record fixture."""

from __future__ import annotations

from types import SimpleNamespace

from models import TaskSpecification


def _record(**kwargs) -> SimpleNamespace:
    defaults = dict(
        record_version="5i.1",
        projection_rule_version="v1",
        execution_id="exec-1",
        session_id="session-1",
        replay_ref={
            "session_id": "session-1",
            "event_range": [1, 12],
            "record_version": "5i.1",
        },
        initiator_ref={
            "ref": "agent-a",
            "source": "ADAPTER_DERIVED",
            "parent_ref": None,
        },
        owner_refs=(
            {"owner_type": "capability", "owner_id": "cap-c"},
        ),
        attempts=(
            SimpleNamespace(
                execution_id="exec-1",
                attempt_id="exec-1/attempt-1",
                attempt_number=1,
                parent_execution_id=None,
                reason="model_request",
                status="SUCCEEDED",
                step_id="step-1",
            ),
        ),
        tools=(),
        tool_results=(),
        turn_end_reason="completed",
        context_provenance=(
            {
                "request_ref": 2,
                "source_event_refs": [1],
                "surface_refs": [1],
                "current_input_ref": 1,
                "runtime_context_ref": None,
                "quality": "PARTIAL",
                "missing_semantics": ["SYSTEM_PROMPT_SNAPSHOT"],
            },
        ),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


TASK_01 = TaskSpecification(
    task_id="TASK-01",
    natural_language_goal="查询库存，如果不足则生成采购建议。",
    required_tools=("inventory.lookup",),
)

TASK_01_RECORD = _record(
    tools=(
        {
            "call_id": "t1",
            "name": "inventory.lookup",
            "arguments": {"sku": "A"},
        },
    ),
    tool_results=(
        {
            "tool_call_id": "t1",
            "content": "stock:5",
            "is_error": False,
            "error_code": None,
            "seq": 8,
        },
    ),
)

TASK_02 = TaskSpecification(
    task_id="TASK-02",
    natural_language_goal="调用必选工具并成功。",
    required_tools=("lookup",),
)

TASK_02_RECORD = _record(
    tools=({"call_id": "t2", "name": "lookup", "arguments": {}},),
    tool_results=(
        {
            "tool_call_id": "t2",
            "content": "boom",
            "is_error": True,
            "error_code": "EXECUTION_ERROR",
            "seq": 8,
        },
    ),
)

TASK_03 = TaskSpecification(
    task_id="TASK-03",
    natural_language_goal="不允许 unsafe retry。",
)

TASK_03_RECORD = _record(
    attempts=(
        SimpleNamespace(
            execution_id="exec-1",
            attempt_id="exec-1/attempt-1",
            attempt_number=1,
            parent_execution_id=None,
            reason="model_request",
            status="FAILED",
            step_id="step-1",
        ),
        SimpleNamespace(
            execution_id="exec-1",
            attempt_id="exec-1/attempt-2",
            attempt_number=2,
            parent_execution_id="exec-1",
            reason="UNSAFE_RETRY_BLOCKED",
            status="ABORTED",
            step_id="step-1",
        ),
    ),
    turn_end_reason="error",
)

TASK_04 = TaskSpecification(
    task_id="TASK-04",
    natural_language_goal="最终回答必须包含采购建议。",
    terminal_condition=(
        lambda record: any(
            "采购建议" in message
            for message in getattr(record, "assistant_messages", ())
        )
    ),
    terminal_condition_desc="final assistant message contains 采购建议",
)

TASK_04_RECORD = _record(
    tools=(),
    assistant_messages=("库存不足，但没有生成建议。",),
)

GOLDEN_TASKS = (
    (TASK_01, TASK_01_RECORD),
    (TASK_02, TASK_02_RECORD),
    (TASK_03, TASK_03_RECORD),
    (TASK_04, TASK_04_RECORD),
)

__all__ = [
    "GOLDEN_TASKS",
    "TASK_01",
    "TASK_01_RECORD",
    "TASK_02",
    "TASK_02_RECORD",
    "TASK_03",
    "TASK_03_RECORD",
    "TASK_04",
    "TASK_04_RECORD",
]
