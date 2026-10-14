"""MCP prompts built from the agent-team profiles, directly and over the MCP endpoint."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import mcp_types as types
import pytest
from bson import ObjectId
from fastapi import FastAPI

from depictio.api.v1.agents.profiles import load_profiles
from depictio.api.v1.configs.config import settings
from depictio.api.v1.mcp import auth as mcp_auth
from depictio.api.v1.mcp import prompts
from depictio.api.v1.mcp.server import mount_mcp

PATH = "/depictio/api/v1/mcp"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "mcp-protocol-version": "2025-06-18",
    "Authorization": "Bearer full",
}


def run(coro):
    return asyncio.run(coro)


def test_list_prompts():
    result = run(prompts.list_prompts(None, None))
    names = [p.name for p in result.prompts]
    assert names[0] == "analyze_dashboard" and "review_findings" in names
    assert {"analyze_qc_multiqc", "analyze_microbiome", "analyze_variants"} <= set(names)
    assert "analyze_general" not in names
    args = {a.name: a.required for a in result.prompts[0].arguments}
    assert args == {"dashboard_id": True, "question": False}


def test_get_prompt_renders_role_topic_and_workflow():
    params = types.GetPromptRequestParams(
        name="analyze_microbiome", arguments={"dashboard_id": "d42", "question": "Alpha?"}
    )
    result = run(prompts.get_prompt(None, params))
    text = result.messages[0].content.text
    profiles = load_profiles()
    assert profiles.topic("microbiome").context_md.strip()[:40] in text
    assert profiles.role("analyst").context_md.strip()[:40] in text
    assert "get_dashboard with dashboard_id d42" in text and "create_report" in text
    assert text.rstrip().endswith("Question: Alpha?")
    assert "untrusted" in text


def test_review_prompt_and_errors():
    review = run(
        prompts.get_prompt(
            None,
            types.GetPromptRequestParams(name="review_findings", arguments={"dashboard_id": "d"}),
        )
    )
    assert "verdict" in review.messages[0].content.text
    with pytest.raises(ValueError):
        run(prompts.get_prompt(None, types.GetPromptRequestParams(name="nope", arguments={})))
    with pytest.raises(ValueError):
        run(
            prompts.get_prompt(
                None, types.GetPromptRequestParams(name="analyze_dashboard", arguments={})
            )
        )


def test_prompts_over_the_mcp_endpoint():
    user = SimpleNamespace(id=ObjectId())

    async def fake_fetch(token):
        return user, SimpleNamespace(id=ObjectId(), name="t", scopes=None)

    async def go():
        app = FastAPI()
        mcp_app = mount_mcp(app, PATH)
        async with mcp_app.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                listed = await client.post(
                    PATH,
                    json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list"},
                    headers=HEADERS,
                )
                got = await client.post(
                    PATH,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "prompts/get",
                        "params": {
                            "name": "analyze_dashboard",
                            "arguments": {"dashboard_id": "d1"},
                        },
                    },
                    headers=HEADERS,
                )
                return listed.json(), got.json()

    with (
        patch.object(mcp_auth, "fetch_user_and_token", fake_fetch),
        patch.object(settings.mcp, "enabled", True),
    ):
        listed, got = run(go())
    assert "analyze_dashboard" in [p["name"] for p in listed["result"]["prompts"]]
    assert "d1" in got["result"]["messages"][0]["content"]["text"]
