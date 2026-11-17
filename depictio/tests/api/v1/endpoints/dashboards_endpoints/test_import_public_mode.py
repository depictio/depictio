"""Dashboard import on a public instance refuses the visitor, not the mode (#1335).

In public mode every visitor is auto-minted as a temporary user that passes
`get_current_user`. Both import routes refuse that user (and the anonymous
one); an admin, or an editor of the target project, imports as on any
instance, and a signed-in user with no editor role is refused by the project
permission check.

Both routes are called directly against mongomock, with the real permission
check.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.api.v1.endpoints.dashboards_endpoints import versioning
from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import UserBase

VISITOR_DETAIL = "Dashboard import is disabled in public/demo mode"


def _user(email: str, **flags) -> UserBase:
    return UserBase(id=ObjectId(), email=email, **flags)


@pytest.fixture
def owner():
    return _user("owner@example.com")


@pytest.fixture
def env(owner):
    database = mongomock.MongoClient()["depictio_test"]
    fake_db = SimpleNamespace(
        projects_collection=database["projects"], dashboards_collection=database["dashboards"]
    )
    with (
        patch.object(dash_routes.settings.auth, "public_mode", True),
        patch.object(dash_routes.settings.auth, "single_user_mode", False),
        patch.object(publish_lock, "_db", return_value=fake_db),
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(dash_routes, "get_user_group_ids", return_value=[]),
        patch.object(dash_routes, "get_project_visibility", return_value=True),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "_ensure_baseline_quietly", return_value=None),
        patch.object(dash_routes, "_capture_version_quietly", return_value=None),
        patch.object(versioning, "ensure_baseline_quietly", return_value=None),
        patch.object(versioning, "capture_quietly", return_value=None),
        patch("depictio.api.v1.permissions.get_user_group_ids", return_value=[]),
    ):
        assert dash_routes.settings.auth.is_public_mode
        yield database


@pytest.fixture
def editor():
    return _user("editor@example.com")


@pytest.fixture
def project_id(env, owner, editor):
    pid = ObjectId()
    env["projects"].insert_one(
        {
            "_id": pid,
            "name": "p",
            "is_public": True,
            "permissions": {
                "owners": [{"_id": owner.id, "email": owner.email}],
                "editors": [{"_id": editor.id, "email": editor.email}],
                "viewers": ["*"],
            },
        }
    )
    return pid


def _import_yaml(user, project_id):
    return asyncio.run(
        dash_routes.import_dashboard_from_yaml(
            yaml_content="title: Imported\nproject_tag: p\n",
            project_id=PyObjectId(project_id),
            overwrite=False,
            source_key=None,
            keep_titles=False,
            main_title=None,
            parent_source_key=None,
            existing=None,
            template_id=None,
            template_version=None,
            current_user=user,
        )
    )


def _import_json(user, project_id):
    return asyncio.run(
        dash_routes.import_dashboard_from_json(
            {"_depictio_export_version": "1.0", "dashboard": {"title": "Imported"}},
            project_id=str(project_id),
            validate_integrity=False,
            current_user=user,
        )
    )


IMPORTS = pytest.mark.parametrize("do_import", [_import_yaml, _import_json], ids=["yaml", "json"])


@IMPORTS
def test_a_temporary_visitor_is_refused(env, project_id, do_import) -> None:
    visitor = _user("temp_user@example.com", is_temporary=True)

    with pytest.raises(HTTPException) as exc:
        do_import(visitor, project_id)

    assert exc.value.status_code == 403
    assert exc.value.detail == VISITOR_DETAIL
    assert env["dashboards"].count_documents({}) == 0


@IMPORTS
def test_a_temporary_visitor_is_refused_even_with_editor_rights(env, project_id, do_import) -> None:
    """The visitor gate runs before any project check: a role cannot reopen it."""
    visitor = _user("temp_user@example.com", is_temporary=True)
    env["projects"].update_one(
        {"_id": project_id},
        {"$push": {"permissions.editors": {"_id": visitor.id, "email": visitor.email}}},
    )

    with pytest.raises(HTTPException) as exc:
        do_import(visitor, project_id)

    assert exc.value.status_code == 403
    assert exc.value.detail == VISITOR_DETAIL


@IMPORTS
def test_the_anonymous_user_is_refused(env, project_id, do_import) -> None:
    anonymous = _user("anonymous@depict.io", is_anonymous=True)

    with pytest.raises(HTTPException) as exc:
        do_import(anonymous, project_id)

    assert exc.value.status_code == 403
    assert exc.value.detail == VISITOR_DETAIL


@IMPORTS
def test_an_admin_imports(env, project_id, do_import) -> None:
    admin = _user("admin@example.com", is_admin=True)

    result = do_import(admin, project_id)

    assert result["dashboard_id"]
    assert env["dashboards"].count_documents({"project_id": project_id}) == 1


@IMPORTS
def test_an_editor_of_the_project_imports(env, project_id, editor, do_import) -> None:
    result = do_import(editor, project_id)

    assert result["dashboard_id"]
    assert env["dashboards"].count_documents({"project_id": project_id}) == 1


@IMPORTS
def test_a_signed_in_user_without_editor_rights_is_refused(env, project_id, do_import) -> None:
    """A public project grants viewers only: reading it is no right to import into it."""
    reader = _user("reader@example.com")

    with pytest.raises(HTTPException) as exc:
        do_import(reader, project_id)

    assert exc.value.status_code == 403
    assert exc.value.detail != VISITOR_DETAIL
    assert env["dashboards"].count_documents({}) == 0


def test_the_anonymous_user_passes_the_gate_in_single_user_mode() -> None:
    """In single-user mode the anonymous user is the admin."""
    anonymous = _user("anonymous@depict.io", is_anonymous=True, is_admin=True)
    with (
        patch.object(dash_routes.settings.auth, "public_mode", False),
        patch.object(dash_routes.settings.auth, "single_user_mode", True),
    ):
        dash_routes.refuse_visitor_import(anonymous)
