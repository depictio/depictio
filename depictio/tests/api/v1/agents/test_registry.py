"""The agent tool registry: one call path with scope, validation, errors, budget and audit."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field

from depictio.api.v1 import db
from depictio.api.v1.agents import ratelimit, registry
from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import (
    TRUNCATION_MARKER,
    fit_to_budget,
    json_size,
    untrusted,
)
from depictio.api.v1.agents.registry import (
    REGISTRY,
    ToolError,
    agent_tool,
    invoke,
    to_litellm_tools,
    tools_for,
)
from depictio.models.models.users import effective_scopes


class Point(BaseModel):
    x: float
    y: float


class EchoArgs(BaseModel):
    text: str
    repeat: int = Field(default=1, ge=1, le=100_000)
    points: list[Point] = Field(default_factory=list)


def _ctx(scopes=None, token_id="tok1"):
    return ToolContext(
        user=SimpleNamespace(id=ObjectId()),  # type: ignore[arg-type]
        scopes=effective_scopes(scopes),
        agent_name="tester",
        token_id=token_id,
    )


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def audit_rows():
    coll = mongomock.MongoClient()["depictio_test"]["agent_tool_calls"]
    ratelimit.reset_local()
    with (
        patch.object(db, "agent_tool_calls_collection", coll),
        patch.object(ratelimit, "_redis_client", return_value=None),
    ):
        yield coll
    ratelimit.reset_local()


@pytest.fixture
def tools():
    """Temporary tools, removed after the test so nothing leaks into the registry."""
    added = []

    def register(name, scope="read", **kwargs):
        def wrap(fn):
            agent_tool(name=name, scope=scope, description=f"{name} tool", **kwargs)(fn)
            added.append(name)
            return fn

        return wrap

    yield register
    for name in added:
        REGISTRY.pop(name, None)


def test_call_ok_and_audit_row(tools, audit_rows):
    @tools("t_echo", input_model=EchoArgs)
    async def echo(ctx, args):
        return {"text": args.text * args.repeat, "agent": ctx.agent_name}

    result = run(invoke("t_echo", _ctx(), {"text": "ab", "repeat": 2}))
    assert result.ok and result.data == {"text": "abab", "agent": "tester"}
    assert not result.truncated
    row = audit_rows.find_one({"call_id": result.call_id})
    assert row["tool"] == "t_echo" and row["ok"] is True and row["token_id"] == "tok1"
    assert row["agent_name"] == "tester" and json.loads(row["args"])["text"] == "ab"


def test_scope_refusal_is_audited(tools, audit_rows):
    @tools("t_write", scope="annotate", input_model=EchoArgs, writes=True)
    async def write(ctx, args):  # pragma: no cover - must not run
        raise AssertionError("called without scope")

    result = run(invoke("t_write", _ctx(["read"]), {"text": "x"}))
    assert not result.ok and "annotate" in result.error
    assert audit_rows.find_one({"call_id": result.call_id})["ok"] is False
    # A legacy token (scopes None) has every scope.
    assert "t_write" in [s.name for s in tools_for(effective_scopes(None))]
    assert "t_write" not in [s.name for s in tools_for(effective_scopes(["read"]))]


def test_unknown_and_disabled_tools(tools, audit_rows):
    @tools("t_off", input_model=EchoArgs, enabled=lambda: False)
    async def off(ctx, args):  # pragma: no cover
        return "never"

    assert run(invoke("t_missing", _ctx(), {})).error == "Unknown tool: t_missing"
    assert not run(invoke("t_off", _ctx(), {"text": "x"})).ok
    assert "t_off" not in [s.name for s in tools_for(effective_scopes(None))]


def test_validation_error_is_readable(tools, audit_rows):
    @tools("t_echo", input_model=EchoArgs)
    async def echo(ctx, args):  # pragma: no cover
        return "x"

    result = run(invoke("t_echo", _ctx(), {"repeat": 0}))
    assert not result.ok
    assert result.error.startswith("Invalid arguments:")
    assert "text" in result.error and "repeat" in result.error


def test_http_and_tool_errors_are_mapped(tools, audit_rows):
    @tools("t_404", input_model=EchoArgs)
    async def not_found(ctx, args):
        raise HTTPException(status_code=404, detail="Dashboard not found")

    @tools("t_refuse", input_model=EchoArgs)
    async def refuse(ctx, args):
        raise ToolError("Nope, too many threads")

    @tools("t_boom", input_model=EchoArgs)
    async def boom(ctx, args):
        raise RuntimeError("secret internals")

    assert run(invoke("t_404", _ctx(), {"text": "x"})).error == "Dashboard not found"
    assert run(invoke("t_refuse", _ctx(), {"text": "x"})).error == "Nope, too many threads"
    boom_result = run(invoke("t_boom", _ctx(), {"text": "x"}))
    assert not boom_result.ok and "secret" not in boom_result.error


def test_output_budget_truncates(tools, audit_rows):
    class Row(BaseModel):
        i: int
        label: str

    @tools("t_big", input_model=EchoArgs, max_chars=500)
    async def big(ctx, args):
        return {"rows": [Row(i=i, label="x" * 20) for i in range(200)], "total": 200}

    result = run(invoke("t_big", _ctx(), {"text": "x"}))
    assert result.ok and result.truncated
    assert json_size(result.data) <= 500
    assert result.data["total"] == 200 and 0 < len(result.data["rows"]) < 200
    assert result.data["rows"][0] == {"i": 0, "label": "x" * 20}
    assert audit_rows.find_one({"call_id": result.call_id})["truncated"] is True


def test_rate_limit(tools, audit_rows):
    @tools("t_echo", input_model=EchoArgs)
    async def echo(ctx, args):
        return "ok"

    with patch.object(registry.settings.mcp, "rate_per_min", 2):
        results = [run(invoke("t_echo", _ctx(token_id="rl"), {"text": "x"})) for _ in range(3)]
    assert [r.ok for r in results] == [True, True, False]
    assert "Rate limit" in results[2].error


def test_audit_failure_does_not_fail_the_call(tools, audit_rows):
    @tools("t_echo", input_model=EchoArgs)
    async def echo(ctx, args):
        return "ok"

    with patch.object(audit_rows, "insert_one", side_effect=RuntimeError("mongo down")):
        assert run(invoke("t_echo", _ctx(), {"text": "x"})).ok


def test_litellm_schema_has_no_refs(tools):
    @tools("t_points", input_model=EchoArgs)
    async def points(ctx, args):  # pragma: no cover
        return "x"

    assert "$defs" in EchoArgs.model_json_schema()
    declared = {t["function"]["name"]: t for t in to_litellm_tools(effective_scopes(None))}
    params = declared["t_points"]["function"]["parameters"]
    dumped = json.dumps(params)
    assert "$ref" not in dumped and "$defs" not in dumped
    assert params["properties"]["points"]["items"]["properties"]["x"]["type"] == "number"


def test_duplicate_name_from_another_function_is_refused(tools):
    @tools("t_dup", input_model=EchoArgs)
    async def first(ctx, args):  # pragma: no cover
        return "x"

    with pytest.raises(ValueError):

        @agent_tool(name="t_dup", scope="read", description="d", input_model=EchoArgs)
        async def second(ctx, args):  # pragma: no cover
            return "y"


def test_untrusted_strips_control_and_bidi():
    raw = "ok‮evil⁦x⁩\x00\x1b[31m​hidden\nline\ttab"
    assert untrusted(raw) == {"untrusted": "okevilx[31mhidden\nline\ttab"}
    assert untrusted(None) is None


def test_fit_to_budget_strings_and_fallback():
    data, truncated = fit_to_budget({"body": "é" * 5000, "id": "a"}, 300)
    assert truncated and json_size(data) <= 300
    assert data["id"] == "a" and data["body"].endswith(TRUNCATION_MARKER)
    small, cut = fit_to_budget({"a": 1}, 300)
    assert small == {"a": 1} and not cut
    many = {f"k{i}": i for i in range(200)}
    fallback, cut = fit_to_budget(many, 200)
    assert cut and isinstance(fallback, str) and json_size(fallback) <= 200


def test_ensure_tools_loaded_skips_missing_modules():
    with (
        patch.object(registry, "TOOL_MODULES", ("definitely_not_a_module",)),
        patch.object(registry, "_tools_loaded", False),
    ):
        registry.ensure_tools_loaded()
        assert registry._tools_loaded
