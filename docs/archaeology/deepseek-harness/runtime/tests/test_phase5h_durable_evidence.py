"""Phase 5-H: durable initiator/owner refs + context provenance.

Evidence must survive close/reopen/replay without ContextVar, runtime
objects, or backend object identity.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

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
from events import (  # noqa: E402
    AGENT_REQUEST,
    EXECUTION_ATTEMPT_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_START,
    USER_MESSAGE,
)
from extensions import ADAPTER_DERIVED  # noqa: E402
from initiator import InitiatorContext  # noqa: E402
from model_adapter import (  # noqa: E402
    ModelFinal,
    ModelToolCall,
    ModelToolCallEvent,
)
from recovery import build_execution_record, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import Session  # noqa: E402


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

    async def lookup(args, ctx, signal):
        return "ok"

    runtime.register(ToolRegistration("lookup", lookup, owner="cap-c"))
    return runtime


async def run_basic(session: Session) -> AgentRuntime:
    agent = AgentRuntime(
        session,
        basic_runtime(),
        ScriptedAdapter([("calling", [("c1", "lookup", {})]), "done"]),
        InitiatorContext("agent-a"),
    )
    await agent.run_turn("go")
    return agent


def first_tool_call(store: EventStore) -> dict:
    event = next(e for e in store.events() if e.event_type == TOOL_CALL)
    return event.payload


def first_attempt_start(store: EventStore) -> dict:
    event = next(
        e for e in store.events() if e.event_type == EXECUTION_ATTEMPT_START
    )
    return event.payload


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
        self.calls = 0

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **kwargs,
    ):
        self.calls += 1
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


class Phase5HDurableInitiatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_initiator_ref_persisted(self) -> None:
        session = Session("s5h-init")
        await run_basic(session)

        payload = first_tool_call(session.store)
        ref = payload["initiator_ref"]
        self.assertEqual(ref["ref"], "agent-a")
        self.assertEqual(ref["source"], ADAPTER_DERIVED)
        self.assertIsNone(ref["parent_ref"])
        request = next(
            e for e in session.store.events() if e.event_type == AGENT_REQUEST
        )
        self.assertEqual(request.payload["initiator_ref"]["ref"], "agent-a")

    async def test_initiator_survives_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "init.jsonl"
            store = EventStore("s5h-init-replay", path=path)
            store.open()
            session = Session("s5h-init-replay")
            session.store = store
            await run_basic(session)
            store.close()

            reopened = EventStore("s5h-init-replay", path=path)
            reopened.open()
            history = replay(reopened)
            reopened.close()

        step = history.turns[0].steps[0]
        self.assertEqual(
            step.request["initiator_ref"]["ref"],
            "agent-a",
        )
        self.assertEqual(
            history.executions[0].attempts[0].initiator_ref["ref"],
            "agent-a",
        )

    async def test_owner_ref_persisted(self) -> None:
        session = Session("s5h-owner")
        await run_basic(session)

        payload = first_tool_call(session.store)
        self.assertEqual(
            payload["owner_ref"],
            {"owner_type": "capability", "owner_id": "cap-c"},
        )
        result = next(
            e for e in session.store.events() if e.event_type == TOOL_RESULT
        )
        self.assertEqual(
            result.payload["owner_ref"]["owner_id"],
            "cap-c",
        )

    async def test_owner_survives_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "owner.jsonl"
            store = EventStore("s5h-owner-replay", path=path)
            store.open()
            session = Session("s5h-owner-replay")
            session.store = store
            await run_basic(session)
            store.close()

            reopened = EventStore("s5h-owner-replay", path=path)
            reopened.open()
            history = replay(reopened)
            reopened.close()

        calls = history.turns[0].steps[0].tool_calls
        self.assertEqual(
            calls[0]["owner_ref"],
            {"owner_type": "capability", "owner_id": "cap-c"},
        )

    async def test_owner_not_equal_initiator(self) -> None:
        session = Session("s5h-separate")
        await run_basic(session)

        payload = first_tool_call(session.store)
        self.assertEqual(payload["owner_ref"]["owner_type"], "capability")
        self.assertNotEqual(
            payload["owner_ref"]["owner_id"],
            payload["initiator_ref"]["ref"],
        )

    async def test_authorized_principal_separate(self) -> None:
        session = Session("s5h-principal")
        await run_basic(session)

        payload = first_tool_call(session.store)
        self.assertNotIn("authorized_principal", payload)
        self.assertNotEqual(
            payload["initiator_ref"]["ref"],
            payload["owner_ref"]["owner_id"],
        )
        self.assertNotIn("owner_id", payload["initiator_ref"])
        self.assertNotIn("ref", payload["owner_ref"])

    async def test_tool_call_has_initiator(self) -> None:
        session = Session("s5h-call-init")
        await run_basic(session)

        payload = first_tool_call(session.store)
        self.assertEqual(payload["initiator_ref"]["ref"], "agent-a")
        self.assertEqual(payload["initiator_ref"]["source"], ADAPTER_DERIVED)

    async def test_tool_call_has_owner(self) -> None:
        session = Session("s5h-call-owner")
        await run_basic(session)

        payload = first_tool_call(session.store)
        self.assertEqual(payload["owner_ref"]["owner_type"], "capability")
        self.assertEqual(payload["owner_ref"]["owner_id"], "cap-c")

    async def test_context_provenance_persisted(self) -> None:
        session = Session("s5h-provenance")
        await run_basic(session)

        provenance = first_attempt_start(session.store)[
            "context_provenance"
        ]
        request = next(
            e for e in session.store.events() if e.event_type == AGENT_REQUEST
        )
        user = next(
            e for e in session.store.events() if e.event_type == USER_MESSAGE
        )
        self.assertEqual(provenance["request_ref"], request.seq)
        self.assertEqual(provenance["current_input_ref"], user.seq)
        self.assertIn(user.seq, provenance["source_event_refs"])
        self.assertEqual(provenance["surface_refs"], provenance["source_event_refs"])
        self.assertIsNone(provenance["runtime_context_ref"])
        self.assertEqual(provenance["quality"], "PARTIAL")
        self.assertIn("RUNTIME_CONTEXT_SNAPSHOT", provenance["missing_semantics"])

    async def test_context_provenance_survives_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "prov.jsonl"
            store = EventStore("s5h-prov-replay", path=path)
            store.open()
            session = Session("s5h-prov-replay")
            session.store = store
            await run_basic(session)
            store.close()

            reopened = EventStore("s5h-prov-replay", path=path)
            reopened.open()
            history = replay(reopened)
            reopened.close()

        provenance = history.executions[0].attempts[0].context_provenance
        self.assertEqual(provenance["quality"], "PARTIAL")
        self.assertIn("SYSTEM_PROMPT_SNAPSHOT", provenance["missing_semantics"])
        self.assertIsNotNone(provenance["request_ref"])
        self.assertTrue(provenance["source_event_refs"])

    async def test_execution_record_contains_durable_refs(self) -> None:
        session = Session("s5h-record")
        agent = await run_basic(session)
        execution_id = next(iter(agent.executions))

        record = build_execution_record(session.store, execution_id)

        self.assertEqual(record.record_version, "5j.1")
        self.assertEqual(record.execution_id, execution_id)
        self.assertEqual(record.initiator_ref["ref"], "agent-a")
        self.assertEqual(
            record.owner_refs,
            ({"owner_type": "capability", "owner_id": "cap-c"},),
        )
        self.assertTrue(record.attempts)
        self.assertTrue(record.tools)
        self.assertTrue(record.events)
        self.assertTrue(record.context_provenance)


class Phase5HDurableBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_agentscope_durable_evidence(self) -> None:
        session = Session("s5h-ags")
        runtime = basic_runtime()
        model = DeterministicAgentScopeModel(
            [("calling", [("c1", "lookup", {})]), "done"],
        )
        adapter = AgentScopeModelAdapter(
            model,
            runtime,
            name="agent-a",
            max_iters=2,
        )
        agent = AgentRuntime(
            session,
            runtime,
            adapter,
            InitiatorContext("agent-a"),
        )

        await agent.run_turn("go")

        payload = first_tool_call(session.store)
        self.assertEqual(payload["initiator_ref"]["ref"], "agent-a")
        self.assertEqual(payload["initiator_ref"]["source"], ADAPTER_DERIVED)
        self.assertEqual(payload["owner_ref"]["owner_id"], "cap-c")
        self.assertEqual(payload["backend_event_ref"]["backend"], "agentscope")
        self.assertIn(
            "context_provenance",
            first_attempt_start(session.store),
        )

    async def test_codex_durable_evidence(self) -> None:
        session = Session("s5h-codex")
        runtime = ToolRuntime()

        async def inventory(args, ctx, signal):
            return "stock:5"

        runtime.register(
            ToolRegistration("inventory.lookup", inventory, owner="ERP"),
        )
        agent = AgentRuntime(
            session,
            runtime,
            CodexAdapter(
                Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
            ),
            InitiatorContext("agent-c"),
        )

        await agent.run_turn("查询库存")

        payload = first_tool_call(session.store)
        self.assertEqual(payload["initiator_ref"]["ref"], "agent-c")
        self.assertEqual(payload["initiator_ref"]["source"], ADAPTER_DERIVED)
        self.assertEqual(payload["owner_ref"]["owner_id"], "ERP")
        self.assertEqual(payload["backend_event_ref"]["backend"], "codex")
        self.assertEqual(payload["backend_event_ref"]["event_id"], "call-1")
        self.assertEqual(
            payload["backend_event_ref"]["reference"]["line"],
            7,
        )
        self.assertIn(
            "context_provenance",
            first_attempt_start(session.store),
        )
        self.assertEqual(len(agent.executions), 3)

    async def test_lossiness_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "lossy.jsonl"
            store = EventStore("s5h-lossy", path=path)
            store.open()
            runtime = ToolRuntime()

            async def inventory(args, ctx, signal):
                return "stock:5"

            runtime.register(
                ToolRegistration("inventory.lookup", inventory, owner="ERP"),
            )
            session = Session("s5h-lossy")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                CodexAdapter(
                    Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
                ),
                InitiatorContext("agent-c"),
            ).run_turn("查询库存")
            store.close()

            reopened = EventStore("s5h-lossy", path=path)
            reopened.open()
            history = replay(reopened)
            turn_start = next(
                e for e in reopened.events() if e.event_type == TURN_START
            )
            missing_semantics = turn_start.payload["backend_metadata"][
                "missing_semantics"
            ]
            attempts = history.executions[0].attempts
            init_source = attempts[0].initiator_ref["source"]
            provenance_quality = attempts[0].context_provenance["quality"]
            reopened.close()

        self.assertIn("AMBIENT_INITIATOR", missing_semantics)
        self.assertEqual(init_source, ADAPTER_DERIVED)
        self.assertEqual(provenance_quality, "PARTIAL")

    async def test_backend_ref_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "refs.jsonl"
            store = EventStore("s5h-refs", path=path)
            store.open()
            runtime = ToolRuntime()

            async def inventory(args, ctx, signal):
                return "stock:5"

            runtime.register(
                ToolRegistration("inventory.lookup", inventory, owner="ERP"),
            )
            session = Session("s5h-refs")
            session.store = store
            await AgentRuntime(
                session,
                runtime,
                CodexAdapter(
                    Path(__file__).parent / "fixtures" / "codex_golden.jsonl",
                ),
                InitiatorContext("agent-c"),
            ).run_turn("查询库存")
            store.close()

            reopened = EventStore("s5h-refs", path=path)
            reopened.open()
            call_ev = next(
                e for e in reopened.events() if e.event_type == TOOL_CALL
            )
            ref = call_ev.payload["backend_event_ref"]
            self.assertEqual(ref["backend"], "codex")
            self.assertEqual(ref["event_id"], "call-1")
            self.assertEqual(ref["reference"]["line"], 7)
            attempt_end = next(
                e
                for e in reopened.events()
                if e.event_type == "execution/attempt/end"
            )
            self.assertEqual(
                attempt_end.payload["backend_event_ref"]["backend"],
                "codex",
            )
            reopened.close()

    async def test_no_python_object_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5h-") as td:
            path = Path(td) / "objects.jsonl"
            store = EventStore("s5h-objects", path=path)
            store.open()
            session = Session("s5h-objects")
            session.store = store
            await run_basic(session)
            store.close()

            raw = path.read_text(encoding="utf-8")

        self.assertNotIn("object at 0x", raw)
        self.assertNotIn("InitiatorContext", raw)
        self.assertNotIn("OwnerRef", raw)
        for line in raw.splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            self.assertIsInstance(parsed["payload"], dict)


if __name__ == "__main__":
    unittest.main()
