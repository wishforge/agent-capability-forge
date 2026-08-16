"""Phase 5-B.1: backend-neutral assembly seam tests.

The runtime must accept any ModelAdapter via constructor injection, must not
import agentscope (directly or transitively), and both the scripted and
AgentScope backends must still pass after the adapter split.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))

from agentscope.credential import CredentialBase  # noqa: E402
from agentscope.message import TextBlock  # noqa: E402
from agentscope.model import ChatModelBase, ChatResponse  # noqa: E402

from backend.adapters.agentscope import AgentScopeModelAdapter  # noqa: E402
from events import ASSISTANT_MESSAGE  # noqa: E402
from initiator import InitiatorContext  # noqa: E402
from model_adapter import (  # noqa: E402
    ModelFinal,
    ScriptedModelAdapter,
)
from runtime import AgentRuntime, ModelResponse, RuntimeCoordinator  # noqa: E402
from tool_runtime import ToolRuntime  # noqa: E402
from turn_step import Session  # noqa: E402


def assistant_content(session: Session) -> str:
    return next(
        e.payload["content"]
        for e in session.store.events()
        if e.event_type == ASSISTANT_MESSAGE
    )


class ScriptedModel:
    """Phase 4-A deterministic callable kept for RuntimeCoordinator."""

    def __init__(self, response: ModelResponse) -> None:
        self.response = response

    async def __call__(self, messages):
        return self.response


class MinimalAdapter:
    """A backend-neutral ModelAdapter with no dependency on any backend."""

    delegates_tools = False
    model_name = "minimal"

    def __init__(self) -> None:
        self.step_tool_results = []

    async def stream(self, ctx, model_context):
        yield ModelFinal("minimal ok", ())


class AgentScopeEchoModel(ChatModelBase):
    """Minimal AgentScope-compatible deterministic model for the seam test."""

    def __init__(self) -> None:
        super().__init__(
            credential=CredentialBase(),
            model="det-b5",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            max_retries=0,
            retry_delay=0.0,
            context_size=1024,
        )

    async def _call_api(
        self,
        model_name,
        messages,
        tools=None,
        tool_choice=None,
        **kwargs,
    ):
        return ChatResponse(
            content=[TextBlock(text="agentscope ok")],
            is_last=True,
        )


class Phase5B1AssemblyTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_accepts_model_adapter(self) -> None:
        session = Session("s-adapter")
        turn = await AgentRuntime(
            session,
            ToolRuntime(),
            MinimalAdapter(),
            InitiatorContext("agent-a"),
        ).run_turn("hi")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(assistant_content(session), "minimal ok")

    def test_runtime_has_no_agentscope_import(self) -> None:
        runtime_source = (RUNTIME / "runtime.py").read_text()
        neutral_source = (RUNTIME / "model_adapter.py").read_text()
        for source in (runtime_source, neutral_source):
            self.assertNotIn("import agentscope", source)
            self.assertNotIn("from agentscope", source)
            self.assertNotIn("AgentScopeModelAdapter", source)
        self.assertNotIn('backend == "agentscope"', runtime_source)
        self.assertNotIn('"agentscope" == backend', runtime_source)

        tree = ast.parse(runtime_source)
        imported = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for name in (a.name for a in node.names)
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertFalse(
            any("agentscope" in name for name in imported),
            imported,
        )

        # A clean interpreter must be able to import runtime without loading
        # agentscope at all (no transitive backend dependency).
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(RUNTIME)!r}); "
            "import runtime; "
            "assert 'agentscope' not in sys.modules"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    async def test_scripted_backend_still_passes(self) -> None:
        session = Session("s-scripted")
        turn = await AgentRuntime(
            session,
            ToolRuntime(),
            ScriptedModelAdapter(ScriptedModel(ModelResponse("scripted ok"))),
            InitiatorContext("agent-a"),
        ).run_turn("hi")
        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(assistant_content(session), "scripted ok")

        # Phase 4-A RuntimeCoordinator contract: raw callable is auto-wrapped.
        coord_session = Session("s-coord")
        coord = RuntimeCoordinator(
            coord_session,
            ToolRuntime(),
            ScriptedModel(ModelResponse("coord ok")),
            InitiatorContext("agent-a"),
        )
        coord_turn = await coord.run_turn("hi")
        self.assertEqual(coord_turn.end_reason, "completed")
        self.assertEqual(assistant_content(coord_session), "coord ok")

    async def test_agentscope_backend_still_passes(self) -> None:
        session = Session("s-agentscope")
        turn = await AgentRuntime(
            session,
            ToolRuntime(),
            AgentScopeModelAdapter(
                AgentScopeEchoModel(),
                ToolRuntime(),
                name="agent-a",
            ),
            InitiatorContext("agent-a"),
        ).run_turn("hi")

        self.assertEqual(turn.end_reason, "completed")
        self.assertEqual(assistant_content(session), "agentscope ok")


if __name__ == "__main__":
    unittest.main()
