"""The MCP endpoint in-process: auth, scope-filtered tools/list, tools/call, mounting."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import mongomock
import pytest
from bson import ObjectId
from fastapi import FastAPI
from pydantic import BaseModel

from depictio.api.v1 import db
from depictio.api.v1.agents import ratelimit
from depictio.api.v1.agents.registry import REGISTRY, agent_tool
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.user_endpoints.token_scopes import current_token_scopes
from depictio.api.v1.mcp import auth as mcp_auth
from depictio.api.v1.mcp.server import mount_mcp

PATH = "/depictio/api/v1/mcp"
PROTOCOL = "2025-06-18"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
TOKENS = {"full": None, "readonly": ["read"]}


class Args(BaseModel):
    text: str


@pytest.fixture
def world():
    user = SimpleNamespace(id=ObjectId())
    seen = {}
    token_ids = {name: ObjectId() for name in TOKENS}

    async def fake_fetch(token):
        if token not in TOKENS:
            return None
        doc = SimpleNamespace(id=token_ids[token], name=f"{token}-token", scopes=TOKENS[token])
        return user, doc

    @agent_tool(name="t_mcp_read", scope="read", description="Read tool", input_model=Args)
    async def read_tool(ctx, args):
        seen["ctx"] = ctx
        seen["scopes"] = current_token_scopes.get()
        return {"echo": args.text}

    @agent_tool(
        name="t_mcp_annotate", scope="annotate", description="Write", input_model=Args, writes=True
    )
    async def annotate_tool(ctx, args):
        return {"written": args.text}

    ratelimit.reset_local()
    audit = mongomock.MongoClient()["depictio_test"]["agent_tool_calls"]
    try:
        with (
            patch.object(mcp_auth, "fetch_user_and_token", fake_fetch),
            patch.object(db, "agent_tool_calls_collection", audit),
            patch.object(ratelimit, "_redis_client", return_value=None),
            patch.object(settings.mcp, "enabled", True),
        ):
            yield SimpleNamespace(user=user, seen=seen, audit=audit, token_ids=token_ids)
    finally:
        REGISTRY.pop("t_mcp_read", None)
        REGISTRY.pop("t_mcp_annotate", None)
        ratelimit.reset_local()


async def _with_client(fn):
    app = FastAPI()
    mcp_app = mount_mcp(app, PATH)
    assert mcp_app is not None
    async with mcp_app.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await fn(client)


def _rpc(client, token, method, params=None, *, path=PATH, extra=None):
    headers = {**HEADERS, "mcp-protocol-version": PROTOCOL, **(extra or {})}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(path, json=body, headers=headers)


def run(coro):
    return asyncio.run(coro)


def test_requires_a_valid_token(world):
    async def go(client):
        return [
            await _rpc(client, None, "tools/list"),
            await _rpc(client, "bogus", "tools/list"),
        ]

    for response in run(_with_client(go)):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_initialize_and_instructions(world):
    async def go(client):
        return await _rpc(
            client,
            "full",
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )

    response = run(_with_client(go))
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["serverInfo"]["name"] == "depictio"
    assert "untrusted" in result["instructions"]


def test_tools_list_is_filtered_by_scopes(world):
    async def go(client):
        full = await _rpc(client, "full", "tools/list")
        read = await _rpc(client, "readonly", "tools/list")
        return full.json(), read.json()

    full, read = run(_with_client(go))
    full_tools = {t["name"]: t for t in full["result"]["tools"]}
    read_names = {t["name"] for t in read["result"]["tools"]}
    assert {"t_mcp_read", "t_mcp_annotate"} <= set(full_tools)
    assert "t_mcp_read" in read_names and "t_mcp_annotate" not in read_names
    schema = full_tools["t_mcp_read"]["inputSchema"]
    assert schema["properties"]["text"]["type"] == "string" and schema["required"] == ["text"]
    assert full_tools["t_mcp_read"]["annotations"]["readOnlyHint"] is True
    assert full_tools["t_mcp_annotate"]["annotations"]["readOnlyHint"] is False


def test_tools_call_ok_and_scope_denied(world):
    async def go(client):
        ok = await _rpc(
            client,
            "readonly",
            "tools/call",
            {"name": "t_mcp_read", "arguments": {"text": "hi"}},
            extra={"X-Depictio-Agent": "claude-desktop", "X-Depictio-Run-Id": "run-42"},
        )
        denied = await _rpc(
            client, "readonly", "tools/call", {"name": "t_mcp_annotate", "arguments": {"text": "x"}}
        )
        return ok.json()["result"], denied.json()["result"]

    ok, denied = run(_with_client(go))
    assert ok["isError"] is False
    payload = json.loads(ok["content"][0]["text"])
    assert payload["data"] == {"echo": "hi"} and payload["truncated"] is False
    assert ok["structuredContent"] == payload
    ctx = world.seen["ctx"]
    assert ctx.agent_name == "claude-desktop" and ctx.run_id == "run-42"
    assert ctx.user is world.user and ctx.token_id
    assert world.seen["scopes"] == ["read"]
    row = world.audit.find_one({"call_id": payload["call_id"]})
    assert row["agent_name"] == "claude-desktop" and row["run_id"] == "run-42"

    assert denied["isError"] is True
    assert "annotate" in json.loads(denied["content"][0]["text"])["error"]


def test_agent_name_falls_back_to_token_name(world):
    async def go(client):
        return await _rpc(
            client, "full", "tools/call", {"name": "t_mcp_read", "arguments": {"text": "x"}}
        )

    run(_with_client(go))
    assert world.seen["ctx"].agent_name == "full-token"


def test_calls_without_a_run_header_share_a_daily_token_run(world):
    """Stateless transport: without X-Depictio-Run-Id, the run is per token and UTC day."""

    async def go(client):
        run_ids = []
        for _ in range(2):
            await _rpc(
                client, "full", "tools/call", {"name": "t_mcp_read", "arguments": {"text": "x"}}
            )
            run_ids.append(world.seen["ctx"].run_id)
        return run_ids

    first, second = run(_with_client(go))
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert first == second == f"token-{world.token_ids['full']}-{day}"


def test_trailing_slash_variants_are_served(world):
    async def go(client):
        return [
            await _rpc(client, "full", "tools/list", path=PATH),
            await _rpc(client, "full", "tools/list", path=PATH + "/"),
        ]

    for response in run(_with_client(go)):
        assert response.status_code == 200 and "tools" in response.json()["result"]


def test_not_mounted_when_disabled():
    async def go():
        app = FastAPI()
        with patch.object(settings.mcp, "enabled", False):
            assert mount_mcp(app, PATH) is None
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(PATH, json={}, headers=HEADERS)

    assert run(go()).status_code == 404


def test_sdk_client_round_trip(world):
    """The official client, over the same ASGI app, sees the tools and calls one."""
    httpx2 = pytest.importorskip("httpx2")
    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        app = FastAPI()
        mcp_app = mount_mcp(app, PATH)
        assert mcp_app is not None
        async with mcp_app.session_manager.run():
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Authorization": "Bearer readonly"},
            )
            async with http:
                transport = streamable_http_client(f"http://testserver{PATH}", http_client=http)
                async with Client(transport) as client:
                    listed = await client.list_tools()
                    called = await client.call_tool("t_mcp_read", {"text": "sdk"})
                    return listed, called

    listed, called = run(go())
    names = {tool.name for tool in listed.tools}
    assert "t_mcp_read" in names and "t_mcp_annotate" not in names
    assert called.is_error is False
    assert called.structured_content["data"] == {"echo": "sdk"}
