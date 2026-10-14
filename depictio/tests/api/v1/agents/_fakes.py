"""Scripted LLM and tools for the agent-team tests (no network, no database)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from bson import ObjectId

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.profiles import load_profiles
from depictio.api.v1.agents.registry import ToolResult
from depictio.api.v1.agents.runner import LLMToolCall, LLMTurn, Toolbox
from depictio.api.v1.endpoints.ai_endpoints.llm_client import CompletionUsage
from depictio.models.models.users import effective_scopes


def turn(
    content: Any = "",
    calls: list[LLMToolCall] | None = None,
    tokens: int = 100,
    cost: float | None = 0.001,
) -> LLMTurn:
    if not isinstance(content, str):
        content = json.dumps(content)
    return LLMTurn(
        content=content,
        tool_calls=calls or [],
        usage=CompletionUsage(tokens // 2, tokens - tokens // 2, tokens, cost),
    )


def call(name: str, args: dict[str, Any], call_id: str = "tc1") -> LLMToolCall:
    return LLMToolCall(id=call_id, name=name, arguments=args, raw_arguments=json.dumps(args))


class FakeLLM:
    """Answers from a script: a list of turns, or a function of the conversation."""

    model = "fake/model"

    def __init__(
        self,
        script: list[LLMTurn] | Callable[[list[dict[str, Any]], Any, Any], LLMTurn],
        tools: bool = True,
    ) -> None:
        self.script = script
        self.tools = tools
        self.calls: list[dict[str, Any]] = []

    def supports_tools(self) -> bool:
        return self.tools

    async def complete(self, messages, *, tools=None, tool_choice=None) -> LLMTurn:
        self.calls.append(
            {"messages": copy.deepcopy(messages), "tools": tools, "tool_choice": tool_choice}
        )
        if callable(self.script):
            return self.script(messages, tools, tool_choice)
        return self.script.pop(0)


@dataclass
class FakeTool:
    scope: str = "read"
    evidence: bool = False
    fn: Callable[[dict[str, Any]], Any] = lambda args: {"ok": True}
    fail: str | None = None


@dataclass
class FakeToolbox(Toolbox):
    tools: dict[str, FakeTool] = field(default_factory=dict)
    invoked: list[tuple[str, ToolContext, dict[str, Any]]] = field(default_factory=list)
    counter: int = 0

    def __post_init__(self) -> None:
        super().__init__(invoke=self._invoke)

    def declarations(self, scopes, names):
        allowed = set(scopes)
        return [
            {
                "type": "function",
                "function": {"name": n, "description": f"{n} tool", "parameters": {}},
            }
            for n in names
            if n in self.tools and self.tools[n].scope in allowed
        ]

    def is_evidence(self, name: str) -> bool:
        return name in self.tools and self.tools[name].evidence

    async def _invoke(self, name, ctx, args) -> ToolResult:
        self.counter += 1
        call_id = f"call-{self.counter}"
        self.invoked.append((name, ctx, args))
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(ok=False, call_id=call_id, error=f"Unknown tool: {name}")
        if not ctx.has(tool.scope):  # type: ignore[arg-type]
            return ToolResult(ok=False, call_id=call_id, error=f"needs {tool.scope}")
        if tool.fail:
            return ToolResult(ok=False, call_id=call_id, error=tool.fail)
        return ToolResult(ok=True, call_id=call_id, data=tool.fn(args))

    def calls_to(self, name: str) -> list[dict[str, Any]]:
        return [args for n, _, args in self.invoked if n == name]


def user() -> Any:
    return SimpleNamespace(id=ObjectId())


def ctx(scopes=None, agent_name="analyst/general@1") -> ToolContext:
    return ToolContext(
        user=user(),  # type: ignore[arg-type]
        scopes=effective_scopes(scopes),
        agent_name=agent_name,
        run_id="run-1",
    )


def role_of(messages: list[dict[str, Any]]) -> str:
    """Which role a conversation belongs to, read off its system prompt."""
    system = messages[0]["content"]
    for role_id, profile in load_profiles().roles.items():
        if system.startswith(profile.context_md.strip()[:60]):
            return role_id
    raise AssertionError("unknown role in system prompt")


def default_tools() -> dict[str, FakeTool]:
    return {
        "get_dashboard": FakeTool(fn=lambda a: {"components": []}),
        "get_component": FakeTool(fn=lambda a: {"index": a.get("index"), "type": "figure"}),
        "get_component_data": FakeTool(evidence=True, fn=lambda a: {"rows": [[1, 2]]}),
        "query_data": FakeTool(evidence=True, fn=lambda a: {"value": 42.0}),
        "list_threads": FakeTool(fn=lambda a: {"threads": []}),
        "create_annotation": FakeTool(
            scope="annotate",
            fn=lambda a: {"thread_id": f"t-{a['component_index']}", "created": True},
        ),
        "ask_question": FakeTool(
            scope="annotate",
            fn=lambda a: {"thread_id": f"q-{a.get('component_index')}", "created": True},
        ),
        "create_report": FakeTool(scope="report", fn=lambda a: {"report_id": "r1"}),
    }
