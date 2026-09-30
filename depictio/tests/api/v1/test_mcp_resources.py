"""MCP resources in-process: listing, templates, reads per kind, errors, audit, budget."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST

from depictio.api.v1.agents.tools import annotations, data, discovery, reports
from depictio.api.v1.configs.config import settings
from depictio.api.v1.mcp import resources
from depictio.api.v1.mcp.server import mount_mcp
from depictio.tests.api.v1 import test_mcp_server
from depictio.tests.api.v1.test_mcp_server import PATH, PROTOCOL, _rpc, _with_client, run

# Same authenticated world as the server tests (fake tokens, mongomock audit).
world = test_mcp_server.world

DASH = "6650f0a1b2c3d4e5f6a7b8c9"


def _read(client, uri, token="readonly"):
    return _rpc(client, token, "resources/read", {"uri": uri})


def _payload(response):
    body = response.json()
    assert "result" in body, body
    content = body["result"]["contents"][0]
    assert content["mimeType"] == "application/json"
    return content["uri"], json.loads(content["text"])


def test_resources_capability_is_advertised(world):
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

    caps = run(_with_client(go)).json()["result"]["capabilities"]
    assert "resources" in caps and "tools" in caps


def test_list_resources_flattens_tabs_and_caps(world):
    rows = [
        {
            "dashboard_id": f"d{i}",
            "title": {"untrusted": f"Main ‮{i}"},
            "tabs": [{"dashboard_id": f"d{i}-t", "title": {"untrusted": "Tab"}}],
        }
        for i in range(40)
    ]
    seen = {}

    def fake_summary(user, project_id=None):
        seen["user"] = user
        return rows

    async def go(client):
        return await _rpc(client, "readonly", "resources/list")

    with patch.object(discovery, "dashboards_summary", fake_summary):
        body = run(_with_client(go)).json()
    listed = body["result"]["resources"]
    assert len(listed) == resources.MAX_LISTED_DASHBOARDS
    assert listed[0]["uri"] == "depictio://dashboard/d0"
    assert listed[1]["uri"] == "depictio://dashboard/d0-t"
    assert listed[0]["title"] == "Main 0"  # bidi override stripped
    assert listed[0]["mimeType"] == "application/json"
    assert seen["user"] is world.user
    assert world.audit.find_one({"tool": "resource:list"})["ok"] is True


def test_list_resource_templates(world):
    async def go(client):
        return await _rpc(client, "readonly", "resources/templates/list")

    templates = run(_with_client(go)).json()["result"]["resourceTemplates"]
    assert {t["uriTemplate"] for t in templates} == {
        "depictio://dashboard/{dashboard_id}",
        "depictio://dashboard/{dashboard_id}/component/{index}",
        "depictio://dashboard/{dashboard_id}/component/{index}/data",
        "depictio://thread/{thread_id}",
        "depictio://report/{report_id}",
    }


def test_read_each_kind(world):
    calls = {}

    def dashboard_summary(user, dashboard_id):
        calls["dashboard"] = (user, dashboard_id)
        return {"dashboard_id": dashboard_id, "title": {"untrusted": "T"}}

    def component_detail(user, dashboard_id, index):
        calls["component"] = (user, dashboard_id, index)
        return {"index": index}

    async def component_data(user, args):
        calls["data"] = (user, args)
        return {"rows": [{"x": 1}]}

    async def get_thread(ctx, args):
        calls["thread"] = (ctx, args.thread_id)
        return {"id": args.thread_id, "comments": [{"body": {"untrusted": "hi"}}]}

    async def get_report(ctx, args):
        calls["report"] = (ctx, args.report_id)
        return {"id": args.report_id}

    uris = [
        f"depictio://dashboard/{DASH}",
        f"depictio://dashboard/{DASH}/component/comp%201",
        f"depictio://dashboard/{DASH}/component/c2/data",
        "depictio://thread/th1",
        "depictio://report/r1",
    ]

    async def go(client):
        return [await _read(client, uri) for uri in uris]

    with (
        patch.object(discovery, "dashboard_summary", dashboard_summary),
        patch.object(discovery, "component_detail", component_detail),
        patch.object(data, "component_data", component_data),
        patch.object(annotations, "get_thread", get_thread),
        patch.object(reports, "get_report", get_report),
    ):
        responses = run(_with_client(go))

    payloads = [_payload(r) for r in responses]
    assert [uri for uri, _ in payloads] == uris
    assert payloads[0][1]["data"]["title"] == {"untrusted": "T"}
    assert payloads[1][1]["data"] == {"index": "comp 1"}
    assert payloads[2][1]["data"] == {"rows": [{"x": 1}]}
    assert payloads[3][1]["data"]["comments"][0]["body"] == {"untrusted": "hi"}
    assert payloads[4][1]["data"] == {"id": "r1"}

    assert calls["dashboard"] == (world.user, DASH)
    assert calls["component"] == (world.user, DASH, "comp 1")
    user, args = calls["data"]
    assert user is world.user and (args.dashboard_id, args.index) == (DASH, "c2")
    assert calls["thread"][0].user is world.user and calls["thread"][1] == "th1"
    assert calls["report"][1] == "r1"

    kinds = ["dashboard", "component", "component_data", "thread", "report"]
    for kind, (_uri, payload) in zip(kinds, payloads):
        row = world.audit.find_one({"call_id": payload["call_id"]})
        assert row["tool"] == f"resource:{kind}" and row["ok"] is True
        assert payload["truncated"] is False


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (
            HTTPException(status_code=403, detail="Not allowed to view this dashboard"),
            INVALID_REQUEST,
        ),
        (HTTPException(status_code=404, detail="Dashboard not found"), INVALID_PARAMS),
    ],
)
def test_permission_errors_map_to_mcp_errors(world, exc, code):
    def denied(user, dashboard_id):
        raise exc

    async def go(client):
        return await _read(client, f"depictio://dashboard/{DASH}")

    with patch.object(discovery, "dashboard_summary", denied):
        response = run(_with_client(go))
    assert response.status_code == 200
    error = response.json()["error"]
    assert error["code"] == code and error["message"] == exc.detail
    assert error["data"]["status"] == exc.status_code
    row = world.audit.find_one({"call_id": error["data"]["call_id"]})
    assert row["tool"] == "resource:dashboard" and row["ok"] is False


def test_unknown_uri_and_internal_error(world):
    async def go(client):
        return [
            await _read(client, "depictio://nothing/here"),
            await _read(client, "depictio://report/r1"),
        ]

    boom = AsyncMock(side_effect=RuntimeError("secret internals"))
    with patch.object(reports, "get_report", boom):
        unknown, internal = run(_with_client(go))
    assert unknown.json()["error"]["code"] == INVALID_PARAMS
    error = internal.json()["error"]
    assert error["code"] == INTERNAL_ERROR and "secret" not in error["message"]


def test_read_is_cut_to_budget(world):
    def big(user, dashboard_id):
        return {"rows": [{"v": "x" * 100} for _ in range(100)]}

    async def go(client):
        return await _read(client, f"depictio://dashboard/{DASH}")

    with (
        patch.object(discovery, "dashboard_summary", big),
        patch.object(settings.mcp, "max_output_chars", 1000),
    ):
        _uri, payload = _payload(run(_with_client(go)))
    assert payload["truncated"] is True
    assert 0 < len(payload["data"]["rows"]) < 100


def test_resources_require_a_valid_token(world):
    async def go(client):
        return [
            await _rpc(client, None, "resources/list"),
            await _rpc(client, "bogus", "resources/read", {"uri": "depictio://report/r1"}),
        ]

    for response in run(_with_client(go)):
        assert response.status_code == 401


def test_sdk_client_reads_resources(world):
    """The official client lists and reads a resource over the same ASGI app."""
    httpx2 = pytest.importorskip("httpx2")
    from fastapi import FastAPI
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
                    listed = await client.list_resources()
                    templates = await client.list_resource_templates()
                    read = await client.read_resource(f"depictio://dashboard/{DASH}")
                    return listed, templates, read

    with (
        patch.object(
            discovery, "dashboards_summary", lambda user, project_id=None: [{"dashboard_id": DASH}]
        ),
        patch.object(
            discovery, "dashboard_summary", lambda user, dashboard_id: {"id": dashboard_id}
        ),
    ):
        listed, templates, read = run(go())
    assert [str(r.uri) for r in listed.resources] == [f"depictio://dashboard/{DASH}"]
    assert len(templates.resource_templates) == 5
    assert json.loads(read.contents[0].text)["data"] == {"id": DASH}
