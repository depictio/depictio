"""A group grant opens the same doors in the AI, agent/MCP and comment paths as in REST.

Every access check goes through ``depictio.api.v1.permissions`` (user groups,
#972): a project shared with a group is open to its members at the level the
group was given, and to nobody else. The AI context loaders, the agent tools,
the dashboard generator's gates and the comments service each reach that
through ``check_project_permission`` or ``build_access_query``; this runs them
for real against one group-shared project per level, so a hand-rolled check
that only knew direct ``owners``/``editors``/``viewers`` would fail here.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1 import db
from depictio.api.v1.agents import ratelimit
from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.registry import invoke
from depictio.api.v1.agents.tools import discovery
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints import context as ai_context
from depictio.api.v1.endpoints.ai_endpoints import dashboard_gen
from depictio.api.v1.endpoints.ai_endpoints.schemas import GenerateDashboardRequest
from depictio.api.v1.endpoints.comments_endpoints import service as cs
from depictio.api.v1.endpoints.dashboards_endpoints import core_functions as dash_core
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.users import effective_scopes


def _user():
    return SimpleNamespace(
        id=ObjectId(), email=f"{ObjectId()}@example.com", is_admin=False, is_anonymous=False
    )


def run(coro):
    return asyncio.run(coro)


def status_of(exc_info) -> int:
    return exc_info.value.status_code


@pytest.fixture
def world():
    """Three private projects shared with one group, as viewers, editors and owners."""
    database = mongomock.MongoClient()["depictio_test_group_access"]
    projects, dashboards = database["projects"], database["dashboards"]
    owner, member, outsider = _user(), _user(), _user()
    group_id = ObjectId()
    database["groups"].insert_one({"_id": group_id, "name": "lab", "users_ids": [member.id]})

    def project(name: str, level: str):
        project_id, wf_id, dc_id, dash_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        permissions = {
            "owners": [{"_id": owner.id, "email": owner.email}],
            "editors": [],
            "viewers": [],
            "group_owners": [],
            "group_editors": [],
            "group_viewers": [],
        }
        permissions[f"group_{level}s"] = [{"_id": group_id, "name": "lab"}]
        projects.insert_one(
            {
                "_id": project_id,
                "name": name,
                "is_public": False,
                "permissions": permissions,
                "workflows": [
                    {
                        "_id": wf_id,
                        "name": "wf",
                        "workflow_tag": f"python/{name}",
                        "data_collections": [
                            {
                                "_id": dc_id,
                                "data_collection_tag": "table",
                                "config": {"type": "table", "metatype": "Metadata"},
                            }
                        ],
                    }
                ],
            }
        )
        dashboards.insert_one(
            {
                "dashboard_id": dash_id,
                "project_id": project_id,
                "title": f"{name} dashboard",
                "is_main_tab": True,
                "stored_metadata": [],
                "permissions": {"owners": [{"_id": owner.id}], "editors": [], "viewers": []},
            }
        )
        return SimpleNamespace(
            project_id=str(project_id), dash_id=str(dash_id), dc_id=str(dc_id), dash_oid=dash_id
        )

    shared_as_viewer = project("viewer-shared", "viewer")
    shared_as_editor = project("editor-shared", "editor")
    shared_as_owner = project("owner-shared", "owner")
    ratelimit.reset_local()
    with (
        patch.object(db, "groups_collection", database["groups"]),
        patch.object(db, "agent_tool_calls_collection", database["agent_tool_calls"]),
        patch.object(ratelimit, "_redis_client", return_value=None),
        patch.object(discovery, "projects_collection", projects),
        patch.object(discovery, "dashboards_collection", dashboards),
        patch.object(dash_routes, "projects_collection", projects),
        patch.object(dash_routes, "dashboards_collection", dashboards),
        patch.object(dash_core, "projects_collection", projects),
        patch.object(dash_core, "dashboards_collection", dashboards),
        patch.object(ai_context, "projects_collection", projects),
        patch.object(ai_context, "dashboards_collection", dashboards),
        patch.object(dashboard_gen, "projects_collection", projects),
        patch.object(dashboard_gen, "dashboards_collection", dashboards),
        patch.object(cs, "dashboards_collection", dashboards),
        patch.object(cs, "comment_threads_collection", database["comment_threads"]),
        patch.object(settings.auth, "single_user_mode", False),
        patch.object(settings.ai, "generate_dashboard_enabled", True),
    ):
        yield SimpleNamespace(
            viewer_shared=shared_as_viewer,
            editor_shared=shared_as_editor,
            owner_shared=shared_as_owner,
            owner=owner,
            member=member,
            outsider=outsider,
            dashboards=dashboards,
        )
    ratelimit.reset_local()


# ---------------------------------------------------------------------------
# Agent tools and MCP resources
# ---------------------------------------------------------------------------
def test_projects_listing_follows_the_group_grant(world):
    seen = {p["project_id"] for p in discovery.projects_summary(world.member)}
    assert seen == {
        world.viewer_shared.project_id,
        world.editor_shared.project_id,
        world.owner_shared.project_id,
    }
    assert discovery.projects_summary(world.outsider) == []


def test_list_projects_tool_for_a_group_member(world):
    ctx = ToolContext(user=world.member, scopes=effective_scopes(None), agent_name="tester")  # type: ignore[arg-type]
    result = run(invoke("list_projects", ctx, {}))
    assert result.ok
    assert {p["project_id"] for p in result.data} == {
        world.viewer_shared.project_id,
        world.editor_shared.project_id,
        world.owner_shared.project_id,
    }


def test_dashboards_listing_follows_the_group_grant(world):
    ids = {d["dashboard_id"] for d in discovery.dashboards_summary(world.member)}
    assert ids == {
        world.viewer_shared.dash_id,
        world.editor_shared.dash_id,
        world.owner_shared.dash_id,
    }
    assert discovery.dashboards_summary(world.outsider) == []


def test_a_group_member_loads_a_dashboard_a_stranger_cannot(world):
    doc = discovery.load_viewable_dashboard(world.member, world.viewer_shared.dash_id)
    assert str(doc["dashboard_id"]) == world.viewer_shared.dash_id
    with pytest.raises(HTTPException) as e:
        discovery.load_viewable_dashboard(world.outsider, world.viewer_shared.dash_id)
    assert status_of(e) == 403


# ---------------------------------------------------------------------------
# AI context
# ---------------------------------------------------------------------------
def test_ai_dashboard_context_for_a_group_member(world):
    ctx, _ = run(ai_context.build_dashboard_context(world.viewer_shared.dash_id, world.member))
    assert ctx.dashboard_id == world.viewer_shared.dash_id
    with pytest.raises(HTTPException) as e:
        run(ai_context.build_dashboard_context(world.viewer_shared.dash_id, world.outsider))
    assert status_of(e) == 403


def test_ai_data_collection_lookup_for_a_group_member(world):
    resolved = run(ai_context._resolve_dc_and_project(world.viewer_shared.dc_id, world.member))
    assert resolved[2]["data_collection_tag"] == "table"
    with pytest.raises(HTTPException) as e:
        run(ai_context._resolve_dc_and_project(world.viewer_shared.dc_id, world.outsider))
    assert status_of(e) == 404


# ---------------------------------------------------------------------------
# Dashboard generation gates
# ---------------------------------------------------------------------------
def test_generation_needs_a_group_editor_grant_not_a_viewer_one(world):
    body = GenerateDashboardRequest(project_id=world.editor_shared.project_id)
    assert dashboard_gen.gate_generate_request(body, world.member)["name"] == "editor-shared"

    viewer_body = GenerateDashboardRequest(project_id=world.viewer_shared.project_id)
    with pytest.raises(HTTPException) as e:
        dashboard_gen.gate_generate_request(viewer_body, world.member)
    assert status_of(e) == 403
    with pytest.raises(HTTPException) as e:
        dashboard_gen.gate_generate_request(body, world.outsider)
    assert status_of(e) == 403


def test_generation_history_is_readable_by_a_group_viewer(world):
    with patch.object(dashboard_gen.generations, "list_for_project", return_value=[]):
        response = dashboard_gen.list_generations(world.viewer_shared.project_id, world.member)
        assert response.generations == []
        with pytest.raises(HTTPException) as e:
            dashboard_gen.list_generations(world.viewer_shared.project_id, world.outsider)
    assert status_of(e) == 403


def test_draft_review_follows_the_group_editor_grant(world):
    for shared in (world.viewer_shared, world.editor_shared):
        world.dashboards.update_one(
            {"dashboard_id": shared.dash_oid},
            {"$set": {"ai_generation": {"status": "draft", "run_id": "r1"}}},
        )
    dashboard_gen.require_draft_dashboard(world.editor_shared.dash_id, world.member)
    with pytest.raises(HTTPException) as e:
        dashboard_gen.require_draft_dashboard(world.viewer_shared.dash_id, world.member)
    assert status_of(e) == 403


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
def test_comment_access_follows_the_group_grant(world):
    editor = run(cs.get_comment_access(world.member, world.editor_shared.dash_id))
    assert editor.can_comment and editor.can_moderate
    viewer = run(cs.get_comment_access(world.member, world.viewer_shared.dash_id))
    assert not viewer.can_comment
    stranger = run(cs.get_comment_access(world.outsider, world.editor_shared.dash_id))
    assert not stranger.can_comment


def test_a_group_viewer_comments_but_does_not_moderate_when_viewers_may_comment(world):
    with patch.object(settings.comments, "viewers_can_comment", True):
        access = run(cs.get_comment_access(world.member, world.viewer_shared.dash_id))
        assert access.can_comment and not access.can_moderate
        dashboard = cs._require_commenter(world.viewer_shared.dash_oid, world.member)
        assert str(dashboard["dashboard_id"]) == world.viewer_shared.dash_id
        assert not cs._can_moderate(dashboard, world.member)
        with pytest.raises(HTTPException) as e:
            cs._require_commenter(world.viewer_shared.dash_oid, world.outsider)
        assert status_of(e) == 403


def test_project_ownership_for_thread_deletes_includes_group_owners(world):
    # Who may delete another person's thread comes from the same chokepoint.
    assert cs._is_project_owner(ObjectId(world.owner_shared.project_id), world.member)
    assert not cs._is_project_owner(ObjectId(world.editor_shared.project_id), world.member)
    assert not cs._is_project_owner(ObjectId(world.owner_shared.project_id), world.outsider)
