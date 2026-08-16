"""Phase 5-I tests: deterministic Evaluation Engine.

Covers the ten core rules + attribution/ownership/context evidence rules,
golden tasks, lossiness, AgentScope/Codex fixtures, cross-backend semantics,
and replay stability. No LLM, no RCA, no regression/promotion.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

EVAL = Path(__file__).resolve().parents[1]
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
FIXTURES = RUNTIME / "tests" / "fixtures"
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(RUNTIME))

from evaluator import evaluate  # noqa: E402
from golden import (  # noqa: E402
    TASK_01,
    TASK_01_RECORD,
    TASK_02,
    TASK_02_RECORD,
    TASK_03,
    TASK_03_RECORD,
    TASK_04,
    TASK_04_RECORD,
)
from models import FAIL, INCONCLUSIVE, PASS, TaskSpecification  # noqa: E402

from agentscope.credential import CredentialBase  # noqa: E402
from agentscope.message import (  # noqa: E402
    TextBlock,
    ToolCallBlock,
    ToolCallState,
)
from agentscope.model import ChatModelBase, ChatResponse  # noqa: E402

from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from backend.adapters.codex import CodexAdapter  # noqa: E402
from event_store import EventStore  # noqa: E402
from initiator import InitiatorContext  # noqa: E402
from model_adapter import ModelFinal, ModelToolCall, ModelToolCallEvent  # noqa: E402
from recovery import build_execution_record, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import Session  # noqa: E402


def finding_map(result) -> dict[str, object]:
    return {finding.rule_id: finding for finding in result.findings}


def _without(record, *names) -> SimpleNamespace:
    data = {
        name: getattr(record, name)
        for name in vars(record)
        if name not in names
    }
    return SimpleNamespace(**data)


def _with(record, **changes) -> SimpleNamespace:
    data = dict(vars(record))
    data.update(changes)
    return SimpleNamespace(**data)


class GoldenTaskTests(unittest.TestCase):
    def test_task_pass(self) -> None:
        result = evaluate(TASK_01_RECORD, TASK_01)
        self.assertEqual(result.status, PASS)
        self.assertEqual(
            {finding.status for finding in result.findings},
            {PASS},
        )
        self.assertIsNone(result.score)

    def test_required_tool_missing(self) -> None:
        spec = replace(
            TASK_01,
            required_tools=("inventory.lookup", "procurement.suggest"),
        )
        result = evaluate(TASK_01_RECORD, spec)
        self.assertEqual(result.status, FAIL)
        self.assertEqual(
            finding_map(result)["RULE-04"].status,
            FAIL,
        )
        self.assertIn("procurement.suggest", finding_map(result)["RULE-04"].message)

    def test_forbidden_tool_called(self) -> None:
        spec = replace(TASK_01, forbidden_tools=("inventory.lookup",))
        result = evaluate(TASK_01_RECORD, spec)
        self.assertEqual(result.status, FAIL)
        finding = finding_map(result)["RULE-05"]
        self.assertEqual(finding.status, FAIL)
        self.assertEqual(finding.evidence_refs[0]["tool_call_id"], "t1")

    def test_required_tool_failed(self) -> None:
        result = evaluate(TASK_02_RECORD, TASK_02)
        self.assertEqual(result.status, FAIL)
        finding = finding_map(result)["RULE-06"]
        self.assertEqual(finding.status, FAIL)
        self.assertEqual(
            finding.evidence_refs[0]["tool_call_id"],
            "t2",
        )

    def test_unresolved_tool(self) -> None:
        record = SimpleNamespace(
            **{
                name: value
                for name, value in vars(TASK_01_RECORD).items()
                if name != "tool_results"
            },
            tool_results=(),
        )
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, FAIL)
        finding = finding_map(result)["RULE-02"]
        self.assertEqual(finding.status, FAIL)
        self.assertEqual(finding.evidence_refs[0]["tool_call_id"], "t1")

    def test_unsafe_retry(self) -> None:
        result = evaluate(TASK_03_RECORD, TASK_03)
        self.assertEqual(result.status, FAIL)
        finding = finding_map(result)["RULE-03"]
        self.assertEqual(finding.status, FAIL)
        self.assertEqual(
            finding.evidence_refs[0]["attempt_id"],
            "exec-1/attempt-2",
        )

    def test_timeout(self) -> None:
        record = SimpleNamespace(
            **{
                name: value
                for name, value in vars(TASK_01_RECORD).items()
                if name != "tool_results"
            },
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "slow",
                    "is_error": True,
                    "error_code": "TOOL_TIMEOUT",
                },
            ),
        )
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, FAIL)
        self.assertEqual(finding_map(result)["RULE-07"].status, FAIL)

    def test_runtime_failure(self) -> None:
        record = _with(TASK_01_RECORD, turn_end_reason="error")
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, FAIL)
        self.assertEqual(finding_map(result)["RULE-08"].status, FAIL)

    def test_terminal_condition(self) -> None:
        result = evaluate(TASK_04_RECORD, TASK_04)
        self.assertEqual(result.status, FAIL)
        self.assertEqual(finding_map(result)["RULE-09"].status, FAIL)

        passed = _with(
            TASK_04_RECORD,
            assistant_messages=("库存不足，采购建议已生成。",),
        )
        result = evaluate(passed, TASK_04)
        self.assertEqual(result.status, PASS)
        self.assertEqual(finding_map(result)["RULE-09"].status, PASS)

    def test_replayability(self) -> None:
        result = evaluate(_without(TASK_01_RECORD, "replay_ref"), TASK_01)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(finding_map(result)["RULE-10"].status, INCONCLUSIVE)

        result = evaluate(TASK_01_RECORD, TASK_01)
        self.assertEqual(finding_map(result)["RULE-10"].status, PASS)

    def test_missing_initiator_inconclusive(self) -> None:
        record = _with(TASK_01_RECORD, initiator_ref=None)
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(finding_map(result)["RULE-11"].status, INCONCLUSIVE)

    def test_missing_owner_inconclusive(self) -> None:
        record = _with(TASK_01_RECORD, owner_refs=())
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(finding_map(result)["RULE-12"].status, INCONCLUSIVE)

    def test_lossy_mapping_visible(self) -> None:
        record = SimpleNamespace(
            **{
                name: value
                for name, value in vars(TASK_01_RECORD).items()
                if name != "tool_results"
            },
            tool_results=(
                {
                    "tool_call_id": "t1",
                    "content": "stock:5",
                    "is_error": False,
                    "error_code": None,
                    "mapping_quality": "LOSSY",
                },
            ),
        )
        result = evaluate(record, TASK_01)
        self.assertEqual(result.status, INCONCLUSIVE)
        finding = finding_map(result)["RULE-06"]
        self.assertEqual(finding.status, INCONCLUSIVE)
        self.assertIn("LOSSY", finding.message)


class DeterministicAgentScopeModel(ChatModelBase):
    """AgentScope-compatible deterministic model (test-only)."""

    def __init__(self, script) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="det-agent",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            max_retries=0,
            retry_delay=0.0,
            context_size=1024,
        )
        self.script = list(script)

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **kwargs,
    ):
        if not self.script:
            return ChatResponse(
                content=[TextBlock(text="final answer")],
                is_last=True,
            )
        item = self.script.pop(0)
        if isinstance(item, str):
            return ChatResponse(content=[TextBlock(text=item)], is_last=True)
        text, calls = item
        blocks = [TextBlock(text=text)]
        for call_id, name, args in calls:
            blocks.append(
                ToolCallBlock(
                    id=call_id,
                    name=name,
                    input=json.dumps(args),
                    state=ToolCallState.PENDING,
                ),
            )
        return ChatResponse(content=blocks, is_last=True)


class ScriptedAdapter:
    """Backend-neutral deterministic adapter: tool call(s) then final answer."""

    delegates_tools = False
    model_name = "minimal"

    def __init__(self, script) -> None:
        self.script = list(script)
        self.step_tool_results = []

    async def stream(self, ctx, model_context):
        item = self.script.pop(0)
        if isinstance(item, str):
            yield ModelFinal(item, ())
            return
        text, calls = item
        tool_calls = tuple(
            ModelToolCall(call_id, name, args)
            for call_id, name, args in calls
        )
        yield ModelFinal(text, tool_calls)
        for call in tool_calls:
            yield ModelToolCallEvent(call.call_id, call.name, call.arguments)


def basic_runtime() -> ToolRuntime:
    runtime = ToolRuntime()

    async def inventory(args, ctx, signal):
        return "stock:5"

    runtime.register(
        ToolRegistration("inventory.lookup", inventory, owner="cap-c"),
    )
    return runtime


async def run_agentscope() -> SimpleNamespace:
    runtime = basic_runtime()
    model = DeterministicAgentScopeModel(
        [("calling", [("c1", "inventory.lookup", {"sku": "A"})]), "done"],
    )
    adapter = AgentScopeModelAdapter(
        model,
        runtime,
        name="agent-a",
        max_iters=2,
    )
    session = Session("s5i-agentscope")
    agent = AgentRuntime(
        session,
        runtime,
        adapter,
        InitiatorContext("agent-a"),
    )
    await agent.run_turn("查询库存")
    execution_id = next(iter(agent.executions))
    return build_execution_record(session.store, execution_id)


async def run_codex() -> SimpleNamespace:
    runtime = basic_runtime()
    session = Session("s5i-codex")
    agent = AgentRuntime(
        session,
        runtime,
        CodexAdapter(FIXTURES / "codex_golden.jsonl"),
        InitiatorContext("agent-c"),
    )
    await agent.run_turn("查询库存，如果不足则生成采购建议。")
    execution_id = next(iter(agent.executions))
    return build_execution_record(session.store, execution_id)


class BackendFixtureTests(unittest.IsolatedAsyncioTestCase):
    CROSS_SPEC = TaskSpecification(
        task_id="cross-inventory",
        natural_language_goal="查询库存",
        required_tools=("inventory.lookup",),
    )

    async def test_agent_scope_fixture(self) -> None:
        record = await run_agentscope()
        result = evaluate(record, self.CROSS_SPEC)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertTrue(all(f.evidence_refs for f in result.findings))
        self.assertEqual(finding_map(result)["RULE-11"].status, PASS)
        self.assertEqual(finding_map(result)["RULE-13"].status, PASS)

    async def test_codex_fixture(self) -> None:
        record = await run_codex()
        result = evaluate(record, self.CROSS_SPEC)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertTrue(all(f.evidence_refs for f in result.findings))
        self.assertEqual(finding_map(result)["RULE-11"].status, PASS)
        self.assertEqual(finding_map(result)["RULE-13"].status, PASS)
        tool = record.tools[0]
        self.assertEqual(tool["backend_event_ref"]["backend"], "codex")
        self.assertIn(
            "EXEC_FAILURE_STRUCTURED_SUCCESS",
            tool["backend_metadata"]["missing_semantics"],
        )

    async def test_same_task_cross_backend(self) -> None:
        agentscope_result = evaluate(
            await run_agentscope(),
            self.CROSS_SPEC,
        )
        codex_result = evaluate(await run_codex(), self.CROSS_SPEC)
        self.assertEqual(
            [(f.rule_id, f.status) for f in agentscope_result.findings],
            [(f.rule_id, f.status) for f in codex_result.findings],
        )
        self.assertTrue(
            all(f.evidence_refs for f in agentscope_result.findings)
        )
        self.assertTrue(all(f.evidence_refs for f in codex_result.findings))

    async def test_replay_semantic_result_stable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5i-") as td:
            path = Path(td) / "record.jsonl"
            store = EventStore("s5i-replay", path=path)
            store.open()
            session = Session("s5i-replay")
            session.store = store
            agent = AgentRuntime(
                session,
                basic_runtime(),
                ScriptedAdapter(
                    [("calling", [("c1", "inventory.lookup", {})]), "done"],
                ),
                InitiatorContext("agent-a"),
            )
            await agent.run_turn("go")
            execution_id = next(iter(agent.executions))
            record_a = build_execution_record(store, execution_id)
            store.close()

            reopened = EventStore("s5i-replay", path=path)
            reopened.open()
            replay(reopened)
            record_b = build_execution_record(reopened, execution_id)
            reopened.close()

        result_a = evaluate(record_a, self.CROSS_SPEC)
        result_b = evaluate(record_b, self.CROSS_SPEC)
        self.assertEqual(result_a.status, result_b.status)
        self.assertEqual(
            [(f.rule_id, f.status, f.message) for f in result_a.findings],
            [(f.rule_id, f.status, f.message) for f in result_b.findings],
        )
        self.assertIsNot(record_a, record_b)


if __name__ == "__main__":
    unittest.main()
