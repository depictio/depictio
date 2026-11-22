"""``POST /figure/preview`` must check project read permission.

The endpoint takes an in-flight ``metadata`` dict straight from the client and
renders it — any collection, with any code. Before this gate, any authenticated
account (and anyone in public / single-user mode) could preview any private
collection. These tests pin the gate: the owning project is resolved from the
workflow/DC pair in ``metadata`` and run through the same ``check_project_permission``
the dashboard render endpoints use.

Routes are called directly (like ``test_comments_routes.py``); the permission
helper runs for real against a mongomock ``projects`` collection, and the heavy
Celery build is stubbed so an *authorized* preview is observed reaching it
without touching Delta or a broker.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException, Response

from depictio.api.v1 import db as api_db
from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.figure_endpoints import routes as fig_routes

WF = ObjectId()
DC = ObjectId()


def _user(*, admin=False, anonymous=False):
    return SimpleNamespace(
        id=ObjectId(),
        email=f"{ObjectId()}@example.com",
        is_admin=admin,
        is_anonymous=anonymous,
    )


def _metadata(wf_id=WF, dc_id=DC, **extra):
    md = {
        "component_type": "figure",
        "wf_id": str(wf_id),
        "dc_id": str(dc_id),
        "visu_type": "scatter",
        "dict_kwargs": {"x": "x", "y": "y"},
    }
    md.update(extra)
    return md


async def _stub_build(task, args, *, offload, label):
    # Stand in for the Celery preview build; reaching here means the permission
    # gate let the request through.
    return {"figure": {"data": [], "layout": {}}, "metadata": {"visu_type": "scatter"}}


@pytest.fixture
def world():
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(api_db, "projects_collection", database["projects"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(fig_routes, "offload_or_run", _stub_build),
        patch.object(settings.auth, "single_user_mode", False),
    ):
        owner, viewer, outsider, editor = _user(), _user(), _user(), _user()
        private_id, public_id = ObjectId(), ObjectId()
        database["projects"].insert_many(
            [
                {
                    "_id": private_id,
                    "is_public": False,
                    "workflows": [{"_id": WF, "data_collections": [{"_id": DC}]}],
                    "permissions": {
                        "owners": [{"_id": owner.id}],
                        "editors": [{"_id": editor.id}],
                        "viewers": [{"_id": viewer.id}],
                    },
                },
            ]
        )
        yield SimpleNamespace(
            db=database,
            private_id=private_id,
            public_id=public_id,
            owner=owner,
            viewer=viewer,
            editor=editor,
            outsider=outsider,
            anonymous=_user(anonymous=True),
        )


def _preview(user, metadata=None, **body):
    body.setdefault("metadata", metadata if metadata is not None else _metadata())
    return asyncio.run(
        fig_routes.preview_figure(
            response=Response(),
            request=body,
            current_user=user,
        )
    )


def _status(user, **body):
    with pytest.raises(HTTPException) as exc:
        _preview(user, **body)
    return exc.value.status_code


# --- private project --------------------------------------------------------


def test_outsider_is_denied_on_a_private_dc(world):
    # A signed-in account with no role on the project: 403.
    assert _status(world.outsider) == 403


def test_anonymous_is_denied_on_a_private_dc(world):
    assert _status(world.anonymous) == 403


def test_viewer_can_preview(world):
    result = _preview(world.viewer)
    assert result["figure"] == {"data": [], "layout": {}}


def test_owner_can_preview(world):
    result = _preview(world.owner)
    assert "figure" in result


def test_admin_can_preview(world):
    result = _preview(_user(admin=True))
    assert "figure" in result


def test_unknown_workflow_dc_pair_is_404(world):
    # The DC id is real, but paired with a workflow that does not own it.
    md = _metadata(wf_id=ObjectId())
    assert _status(world.viewer, metadata=md) == 404


def test_dc_from_another_project_cannot_borrow_this_workflow(world):
    # A DC id the caller might own elsewhere, paired with this workflow, must
    # not resolve: the DC has to live under the given workflow.
    md = _metadata(dc_id=ObjectId())
    assert _status(world.owner, metadata=md) == 404


# --- public project ---------------------------------------------------------


def test_anonymous_works_on_a_public_project(world):
    pub_wf, pub_dc = ObjectId(), ObjectId()
    world.db["projects"].insert_one(
        {
            "_id": world.public_id,
            "is_public": True,
            "workflows": [{"_id": pub_wf, "data_collections": [{"_id": pub_dc}]}],
            "permissions": {"owners": [], "editors": [], "viewers": []},
        }
    )
    result = _preview(world.anonymous, metadata=_metadata(wf_id=pub_wf, dc_id=pub_dc))
    assert "figure" in result


# --- client-supplied delta_location is stripped -----------------------------


def test_client_delta_location_is_not_forwarded(world):
    """A caller cannot aim the read at an arbitrary table via dc_config."""
    captured = {}

    async def _capture(task, args, *, offload, label):
        captured["payload"] = args[0]
        return {"figure": {"data": [], "layout": {}}, "metadata": {}}

    md = _metadata(dc_config={"delta_location": "s3://evil/secret", "type": "table"})
    with patch.object(fig_routes, "offload_or_run", _capture):
        _preview(world.viewer, metadata=md)

    sent_dc_config = captured["payload"]["metadata"].get("dc_config") or {}
    assert "delta_location" not in sent_dc_config
    assert sent_dc_config.get("type") == "table"


# --- dashboard_id read permission -------------------------------------------


def test_dashboard_id_requires_read_permission(world):
    """A dashboard the caller cannot read must not have its brand applied."""
    other_project = ObjectId()
    dash_id = ObjectId()
    world.db["projects"].insert_one(
        {
            "_id": other_project,
            "is_public": False,
            "permissions": {"owners": [{"_id": world.outsider.id}], "editors": [], "viewers": []},
        }
    )
    world.db["dashboards"].insert_one({"dashboard_id": dash_id, "project_id": str(other_project)})
    with (
        patch.object(dash_routes, "dashboards_collection", world.db["dashboards"]),
        patch.object(api_db, "dashboards_collection", world.db["dashboards"]),
    ):
        # The viewer can read the DC's own project, but not the unrelated
        # dashboard whose brand it asked to apply.
        assert _status(world.viewer, dashboard_id=str(dash_id)) == 403


# --- code mode: code in the request body is editor-only ---------------------
#
# The preview body carries no component id, so its `code_content` cannot be
# matched against stored code: it is arbitrary code and runs for editors
# only. Viewers and anonymous visitors render stored code through
# `/dashboards/render_figure/{id}/{cid}`, which ignores request-supplied code.


def _code_metadata(wf_id=WF, dc_id=DC, code="fig = px.scatter(df.to_pandas(), x='x', y='y')"):
    return _metadata(wf_id=wf_id, dc_id=dc_id, mode="code", code_content=code)


def test_viewer_cannot_run_code_in_a_preview(world):
    assert _status(world.viewer, metadata=_code_metadata()) == 403


def test_anonymous_cannot_run_code_on_a_public_project(world):
    pub_wf, pub_dc = ObjectId(), ObjectId()
    world.db["projects"].insert_one(
        {
            "_id": world.public_id,
            "is_public": True,
            "workflows": [{"_id": pub_wf, "data_collections": [{"_id": pub_dc}]}],
            "permissions": {"owners": [], "editors": [], "viewers": []},
        }
    )
    # Read access alone (public project) is not enough to run code.
    assert _status(world.anonymous, metadata=_code_metadata(pub_wf, pub_dc)) == 403


def test_editor_can_run_code_in_a_preview(world):
    result = _preview(world.editor, metadata=_code_metadata())
    assert "figure" in result


def test_admin_can_run_code_in_a_preview(world):
    result = _preview(_user(admin=True), metadata=_code_metadata())
    assert "figure" in result


def test_blank_code_is_not_arbitrary_code(world):
    """mode=code with no code passes the gate; there is nothing to run."""
    result = _preview(world.viewer, metadata=_code_metadata(code="   "))
    assert "figure" in result


def test_editor_preview_carries_code_error_detail(world):
    captured = {}

    async def _capture(task, args, *, offload, label):
        captured["payload"] = args[0]
        return {"figure": {"data": [], "layout": {}}, "metadata": {}}

    with patch.object(fig_routes, "offload_or_run", _capture):
        _preview(world.editor, metadata=_code_metadata())
    assert captured["payload"]["code_error_detail"] is True


def test_viewer_preview_carries_no_code_error_detail(world):
    captured = {}

    async def _capture(task, args, *, offload, label):
        captured["payload"] = args[0]
        return {"figure": {"data": [], "layout": {}}, "metadata": {}}

    with patch.object(fig_routes, "offload_or_run", _capture):
        _preview(world.viewer)  # UI mode
    assert captured["payload"]["code_error_detail"] is False


# --- /figure/analyze_code: signed-in only, size-capped ----------------------


def _analyze(user, code="fig = px.bar(df, x='a', y='b')"):
    return asyncio.run(
        fig_routes.analyze_code(response=Response(), request={"code": code}, current_user=user)
    )


def test_anonymous_cannot_analyze_code(world):
    with pytest.raises(HTTPException) as exc:
        _analyze(world.anonymous)
    assert exc.value.status_code == 401


def test_anonymous_admin_still_analyzes_code(world):
    """Single-user mode keeps working: there the anonymous user is admin."""

    async def _stub(task, args, *, offload, label):
        assert args[0]  # the code reached the task
        return {"is_valid": True}

    with patch.object(fig_routes, "offload_or_run", _stub):
        assert _analyze(_user(admin=True, anonymous=True))["is_valid"] is True


def test_signed_in_user_can_analyze_code(world):
    async def _stub(task, args, *, offload, label):
        assert args[0] == "fig = px.bar(df, x='a', y='b')"
        return {"is_valid": True}

    with patch.object(fig_routes, "offload_or_run", _stub):
        assert _analyze(world.viewer)["is_valid"] is True


def test_oversized_code_is_refused(world):
    # "x = 1\n" * 40_000 is 240 kB, over the 100 kB cap.
    with pytest.raises(HTTPException) as exc:
        _analyze(world.viewer, code="x = 1\n" * 40_000)
    assert exc.value.status_code == 413
