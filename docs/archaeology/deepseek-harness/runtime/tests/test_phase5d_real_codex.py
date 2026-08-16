"""Phase 5-D: Real Codex E2E verification.

Driven by a rollout captured from the pinned openai/codex executable
(commit 279b93242cfef379e65da97e87e44b83c5934fd7, built locally and run
against the user's configured DeepSeek provider). The test replays that real
rollout through the Unified runtime, verifies persistence/replay, and
compares the Unified shape with an AgentScope 2.0.2 backend on the same
deterministic golden path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_ROLLOUT = FIXTURES / "codex_real_golden.jsonl"
sys.path.insert(0, str(RUNTIME))

from agentscope.credential import CredentialBase  # noqa: E402
from agentscope.message import TextBlock, ToolCallBlock, ToolCallState  # noqa: E402
from agentscope.model import ChatModelBase, ChatResponse  # noqa: E402

from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from backend.adapters.codex import ADAPTER, EXACT, CodexAdapter  # noqa: E402
from event_store import EventStore  # noqa: E402
from events import (  # noqa: E402
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    STEP_END,
    STEP_START,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
)
from initiator import InitiatorContext  # noqa: E402
from recovery import rebuild_session, replay  # noqa: E402
from runtime import AgentRuntime  # noqa: E402
from surface import SurfaceProjection  # noqa: E402
from tool_runtime import ToolRegistration, ToolRuntime  # noqa: E402
from turn_step import ENDED, Session  # noqa: E402

REAL_EVENTS = [
    USER_MESSAGE,
    TURN_START,
    STEP_START,
    AGENT_REQUEST,
    ASSISTANT_MESSAGE,
    TOOL_CALL,
    TOOL_RESULT,
    STEP_END,
    STEP_START,
    AGENT_REQUEST,
    ASSISTANT_CHUNK,
    ASSISTANT_MESSAGE,
    STEP_END,
    TURN_END,
]


def event_types(store: EventStore) -> list[str]:
    return [e.event_type for e in store.events()]


def rollout_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def final_answer_from_rollout(path: Path) -> str:
    lines = rollout_lines(path)
    complete = next(
        line["payload"]
        for line in lines
        if line.get("type") == "event_msg"
        and line["payload"].get("type") == "task_complete"
    )
    return complete["last_agent_message"]


def read_only_exec(workspace: Path):
    """Deterministic read-only shell tool for the golden path."""

    def run(args, ctx, signal):
        cmd = str(args.get("cmd", ""))
        parts = cmd.split()
        if not parts or parts[0] not in (
            "cat",
            "ls",
            "head",
            "tail",
            "wc",
            "sed",
            "grep",
            "find",
            "pwd",
            "echo",
        ):
            return f"blocked: read-only command only: {cmd}"
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"exit {result.returncode}: {result.stderr.strip()}"
        return result.stdout.strip()

    return run


def capability_runtime(workspace: Path, executed: list[str] | None = None) -> ToolRuntime:
    runtime = ToolRuntime()

    def exec_command(args, ctx, signal):
        if executed is not None:
            executed.append(args.get("cmd", ""))
        return read_only_exec(workspace)(args, ctx, signal)

    runtime.register(
        ToolRegistration("exec_command", exec_command, owner="capability"),
    )
    return runtime


def make_workspace(td: str) -> Path:
    workspace = Path(td) / "ws"
    workspace.mkdir()
    (workspace / "data.txt").write_text(
        "Q3 revenue: 42 units\nProduct: codex-harness\n",
        encoding="utf-8",
    )
    return workspace


class DeterministicAgentScopeModel(ChatModelBase):
    """AgentScope-compatible deterministic model mirroring the Codex rollout."""

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
        text, calls = self.script.pop(0)
        blocks = []
        if text:
            blocks.append(TextBlock(text=text))
        for call_id, name, args in calls:
            blocks.append(
                ToolCallBlock(
                    id=call_id,
                    name=name,
                    input=json.dumps(args, sort_keys=True),
                    state=ToolCallState.PENDING,
                ),
            )
        return ChatResponse(content=blocks, is_last=True)


def agentscope_script_from_rollout(path: Path) -> list[tuple[str, list[tuple]]]:
    adapter = CodexAdapter(path)
    script = []
    for segment in adapter.segments:
        text = ""
        calls = []
        for event in segment:
            if type(event).__name__ == "ModelChunk":
                text = event.content
            elif type(event).__name__ == "ModelFinal":
                calls = [
                    (call.call_id, call.name, call.arguments)
                    for call in event.tool_calls
                ]
        script.append((text, calls))
    return script


@unittest.skipUnless(REAL_ROLLOUT.exists(), "real Codex rollout fixture missing")
class Phase5DRealCodexTests(unittest.IsolatedAsyncioTestCase):
    def test_real_rollout_is_complete_golden_path(self) -> None:
        lines = rollout_lines(REAL_ROLLOUT)
        self.assertTrue(any(l.get("type") == "session_meta" for l in lines))
        self.assertTrue(
            any(
                l.get("type") == "event_msg"
                and l["payload"].get("type") == "task_started"
                for l in lines
            ),
        )
        self.assertTrue(
            any(
                l.get("type") == "event_msg"
                and l["payload"].get("type") == "task_complete"
                for l in lines
            ),
        )
        calls = [
            l["payload"]
            for l in lines
            if l.get("type") == "response_item"
            and l["payload"].get("type") == "function_call"
        ]
        outputs = [
            l["payload"]
            for l in lines
            if l.get("type") == "response_item"
            and l["payload"].get("type") == "function_call_output"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(calls[0]["call_id"], outputs[0]["call_id"])
        self.assertEqual(calls[0]["name"], "exec_command")
        args = json.loads(calls[0]["arguments"])
        self.assertEqual(args["cmd"], "cat data.txt")
        final = final_answer_from_rollout(REAL_ROLLOUT)
        self.assertIn("42 units", final)

    async def test_real_codex_golden_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5d-") as td:
            workspace = make_workspace(td)
            executed: list[str] = []
            session = Session("s-real-golden")
            adapter = CodexAdapter(REAL_ROLLOUT)

            turn = await AgentRuntime(
                session,
                capability_runtime(workspace, executed),
                adapter,
                InitiatorContext("agent-c"),
            ).run_turn("Read the file data.txt ...")

            self.assertEqual(turn.end_reason, "completed")
            self.assertEqual(len(turn.steps), 2)
            self.assertEqual([len(s.tool_calls) for s in turn.steps], [1, 0])
            self.assertEqual({s.status for s in turn.steps}, {ENDED})
            self.assertEqual(executed, ["cat data.txt"])
            self.assertEqual(event_types(session.store), REAL_EVENTS)
            call = turn.steps[0].tool_calls[0]
            self.assertEqual(call.call_id, "call_00_7Mq3Bp92nwb9UtXJhZUU4713")
            self.assertEqual(call.name, "exec_command")
            self.assertEqual(call.arguments["cmd"], "cat data.txt")
            result = next(
                e
                for e in session.store.events()
                if e.event_type == TOOL_RESULT
            )
            self.assertEqual(result.payload["content"], "Q3 revenue: 42 units\nProduct: codex-harness")
            self.assertFalse(result.payload["is_error"])
            final = next(
                e
                for e in session.store.events()
                if e.event_type == ASSISTANT_MESSAGE
                and e.payload["content"].startswith("data.txt contains")
            )
            self.assertEqual(final.payload["content"], final_answer_from_rollout(REAL_ROLLOUT))

    async def test_real_codex_mapping(self) -> None:
        adapter = CodexAdapter(REAL_ROLLOUT)

        self.assertEqual(adapter.mapping_metadata.backend, "codex")
        self.assertEqual(adapter.mapping_metadata.mapping_quality, ADAPTER)
        self.assertEqual(adapter.mapping_metadata.raw_event_ref["line"], 1)
        self.assertEqual(adapter.turn_metadata.mapping_quality, ADAPTER)
        self.assertEqual(adapter.turn_metadata.raw_event_ref["line"], 2)
        self.assertEqual(
            [(m.source_event_type, m.raw_event_ref["line"], m.mapping_quality) for m in adapter.step_metadata],
            [
                ("function_call", 12, ADAPTER),
                ("message", 17, ADAPTER),
            ],
        )
        call_meta = adapter.call_metadata["call_00_7Mq3Bp92nwb9UtXJhZUU4713"]
        self.assertEqual(call_meta.mapping_quality, EXACT)
        self.assertEqual(call_meta.raw_event_ref["line"], 13)
        self.assertEqual(call_meta.source_event_type, "function_call_output")
        for missing in (
            "STEP_BOUNDARY_PERSISTED",
            "EXEC_FAILURE_STRUCTURED_SUCCESS",
            "CHUNK_TO_MESSAGE_LINEAGE",
            "CRASH_OUTCOME_NATIVE_MARKER",
            "AMBIENT_INITIATOR",
            "COMPACTION_RETRY_SAME_STEP",
        ):
            self.assertIn(missing, adapter.mapping_metadata.missing_semantics)

    async def test_real_codex_persistence_replay(self) -> None:
        executed: list[str] = []
        with tempfile.TemporaryDirectory(prefix="phase5d-") as td:
            workspace = make_workspace(td)
            path = Path(td) / "real.jsonl"
            store = EventStore("s-real-persist", path=path)
            store.open()
            session = Session("s-real-persist")
            session.store = store
            await AgentRuntime(
                session,
                capability_runtime(workspace, executed),
                CodexAdapter(REAL_ROLLOUT),
                InitiatorContext("agent-c"),
            ).run_turn("Read the file data.txt ...")
            surface_a = SurfaceProjection(store).derive_messages()
            seq_count = store.last_seq()
            store.close()

            reopened = EventStore("s-real-persist", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                surface_a,
            )
            rebuilt = rebuild_session(reopened)
            self.assertEqual(len(rebuilt.turns), 1)
            self.assertEqual(len(rebuilt.turns[0].steps), 2)
            history = replay(reopened)
            reopened.close()

        self.assertEqual(executed, ["cat data.txt"])  # no re-execution on replay
        self.assertEqual(len(history.turns), 1)
        golden = history.turns[0]
        self.assertEqual(golden.end_reason, "completed")
        self.assertEqual(len(golden.steps), 2)
        self.assertEqual(
            golden.steps[0].tool_calls[0]["call_id"],
            "call_00_7Mq3Bp92nwb9UtXJhZUU4713",
        )
        self.assertEqual(
            golden.steps[0].tool_results[0].content,
            "Q3 revenue: 42 units\nProduct: codex-harness",
        )
        self.assertEqual(
            golden.steps[-1].assistant_messages[-1]["content"],
            final_answer_from_rollout(REAL_ROLLOUT),
        )

    async def test_cross_backend_agentscope_same_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5d-") as td:
            workspace = make_workspace(td)
            runtime = capability_runtime(workspace)
            model = DeterministicAgentScopeModel(
                agentscope_script_from_rollout(REAL_ROLLOUT),
            )
            adapter = AgentScopeModelAdapter(
                model,
                runtime,
                name="agent-a",
                system_prompt="system prompt",
            )
            path = Path(td) / "cross.jsonl"
            store = EventStore("s-cross", path=path)
            store.open()
            session = Session("s-cross")
            session.store = store

            turn = await AgentRuntime(
                session,
                runtime,
                adapter,
                InitiatorContext("agent-a"),
            ).run_turn("Read the file data.txt ...")

            self.assertEqual(turn.end_reason, "completed")
            self.assertEqual(len(turn.steps), 2)
            self.assertEqual(event_types(session.store), REAL_EVENTS)
            final = next(
                e
                for e in session.store.events()
                if e.event_type == ASSISTANT_MESSAGE
                and e.payload["content"].startswith("data.txt contains")
            )
            self.assertEqual(final.payload["content"], final_answer_from_rollout(REAL_ROLLOUT))
            result = next(
                e for e in session.store.events() if e.event_type == TOOL_RESULT
            )
            self.assertEqual(result.payload["content"], "Q3 revenue: 42 units\nProduct: codex-harness")
            surface_a = SurfaceProjection(store).derive_messages()
            seq_count = store.last_seq()
            store.close()

            reopened = EventStore("s-cross", path=path)
            reopened.open()
            self.assertEqual(reopened.last_seq(), seq_count)
            self.assertEqual(
                SurfaceProjection(reopened).derive_messages(),
                surface_a,
            )
            history = replay(reopened)
            reopened.close()
            self.assertEqual(len(history.turns), 1)
            self.assertEqual(len(history.turns[0].steps), 2)
            self.assertEqual(
                history.turns[0].steps[-1].assistant_messages[-1]["content"],
                final_answer_from_rollout(REAL_ROLLOUT),
            )

    def test_semantic_core_has_no_codex_reference(self) -> None:
        for name in ("runtime.py", "model_adapter.py"):
            source = (RUNTIME / name).read_text(encoding="utf-8")
            self.assertNotIn("codex", source.lower())
            self.assertNotIn("CodexAdapter", source)


if __name__ == "__main__":
    unittest.main()
