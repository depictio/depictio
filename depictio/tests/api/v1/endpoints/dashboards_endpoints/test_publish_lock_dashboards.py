"""The published lock on the dashboard routes (#1303).

Each mutating route is called directly against mongomock. A locked dashboard
answers 409 before anything is written; a visitor's copy and an unlocked
project are untouched.
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
from depictio.api.v1.endpoints.dashboards_endpoints import versions_routes as ver_routes
from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission, UserBase


@pytest.fixture
def env():
    database = mongomock.MongoClient()["depictio_test"]
    fake_db = SimpleNamespace(
        projects_collection=database["projects"], dashboards_collection=database["dashboards"]
    )
    with (
        patch.object(publish_lock, "_db", return_value=fake_db),
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(ver_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "check_dashboard_mutation_permission", return_value=True),
        patch.object(dash_routes, "check_project_permission", return_value=True),
        patch.object(dash_routes, "get_project_visibility", return_value=False),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "_ensure_baseline_quietly", return_value=None),
        patch.object(dash_routes, "_capture_version_quietly", return_value=None),
        patch.object(versioning, "ensure_baseline_quietly", return_value=None),
        patch.object(versioning, "capture_quietly", return_value=None),
        patch("depictio.api.v1.permissions.get_user_group_ids", return_value=[]),
    ):
        yield database


@pytest.fixture
def editor():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_anonymous = False
    return u


@pytest.fixture
def visitor():
    u = UserBase(id=ObjectId(), email="visitor@example.com")
    u.is_anonymous = False
    return u


def _project(db, *, owner, locked: bool, dashboard_ids=()):
    pid = ObjectId()
    doc = {
        "_id": pid,
        "name": "p",
        "is_public": True,
        "permissions": {"owners": [{"_id": owner.id, "email": owner.email}], "viewers": ["*"]},
    }
    if locked:
        doc["published_lock"] = {
            "locked_at": "2026-01-01T00:00:00",
            "reason": "release",
            "source": "manual",
            "dashboard_ids": [str(d) for d in dashboard_ids],
        }
    db["projects"].insert_one(doc)
    return pid


def _dashboard(db, project_id, *, parent=None, title="D"):
    did = ObjectId()
    db["dashboards"].insert_one(
        {
            "_id": did,
            "dashboard_id": did,
            "project_id": project_id,
            "title": title,
            "is_main_tab": parent is None,
            "parent_dashboard_id": parent,
            "tab_order": 0,
        }
    )
    return did


def _locked_family(db, owner):
    """A locked project holding one published main tab with one child tab."""
    main = ObjectId()
    child = ObjectId()
    project = _project(db, owner=owner, locked=True, dashboard_ids=[main])
    for did, parent in ((main, None), (child, main)):
        db["dashboards"].insert_one(
            {
                "_id": did,
                "dashboard_id": did,
                "project_id": project,
                "title": "T",
                "is_main_tab": parent is None,
                "parent_dashboard_id": parent,
                "tab_order": 1,
            }
        )
    return project, main, child


def _conflict(coro):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(coro)
    assert exc.value.status_code == 409
    return exc.value


def test_edit_on_a_published_dashboard_is_refused(env, editor) -> None:
    _, main, _ = _locked_family(env, editor)

    _conflict(dash_routes.edit_dashboard(main, {"title": "New"}, editor))

    assert env["dashboards"].find_one({"dashboard_id": main})["title"] == "T"


def test_edit_on_an_unlocked_project_still_works(env, editor) -> None:
    project = _project(env, owner=editor, locked=False)
    did = _dashboard(env, project)

    asyncio.run(dash_routes.edit_dashboard(did, {"title": "New"}, editor))

    assert env["dashboards"].find_one({"dashboard_id": did})["title"] == "New"


def test_save_of_a_published_dashboard_is_refused(env, editor) -> None:
    project, main, _ = _locked_family(env, editor)
    data = DashboardData(
        dashboard_id=main,
        title="Changed",
        project_id=project,
        permissions=Permission(owners=[editor]),
    )

    _conflict(dash_routes.save_dashboard(dashboard_id=main, data=data, current_user=editor))

    assert env["dashboards"].find_one({"dashboard_id": main})["title"] == "T"


def _save_new(project, user, **extra):
    did = ObjectId()
    data = DashboardData(
        dashboard_id=did,
        title="Copy",
        project_id=project,
        permissions=Permission(owners=[user]),
        **extra,
    )
    return did, data


def test_a_visitor_may_save_their_own_copy_in_a_published_project(env, editor, visitor) -> None:
    project, _, _ = _locked_family(env, editor)
    did, data = _save_new(project, visitor)

    asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=visitor))

    assert env["dashboards"].find_one({"dashboard_id": did}) is not None


def test_the_visitors_copy_stays_editable(env, editor, visitor) -> None:
    project, _, _ = _locked_family(env, editor)
    did, data = _save_new(project, visitor)
    asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=visitor))

    asyncio.run(dash_routes.edit_dashboard(did, {"title": "Mine"}, visitor))
    data.title = "Mine again"
    asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=visitor))

    assert env["dashboards"].find_one({"dashboard_id": did})["title"] == "Mine again"


def test_the_owner_cannot_create_a_dashboard_in_a_published_project(env, editor) -> None:
    project, _, _ = _locked_family(env, editor)
    did, data = _save_new(project, editor)

    _conflict(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=editor))

    assert env["dashboards"].find_one({"dashboard_id": did}) is None


def test_a_visitor_cannot_add_a_tab_to_a_published_dashboard(env, editor, visitor) -> None:
    project, main, _ = _locked_family(env, editor)
    did, data = _save_new(project, visitor, parent_dashboard_id=main, is_main_tab=False)

    _conflict(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=visitor))


def test_creating_in_an_unlocked_project_is_unaffected(env, editor) -> None:
    project = _project(env, owner=editor, locked=False)
    did, data = _save_new(project, editor)

    asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=editor))

    assert env["dashboards"].find_one({"dashboard_id": did}) is not None


def test_patching_a_published_tab_is_refused(env, editor) -> None:
    _, _, child = _locked_family(env, editor)

    _conflict(dash_routes.update_tab(child, {"title": "X"}, editor))

    assert env["dashboards"].find_one({"dashboard_id": child})["title"] == "T"


def test_deleting_a_published_tab_is_refused(env, editor) -> None:
    _, _, child = _locked_family(env, editor)

    _conflict(dash_routes.delete_tab(child, editor))

    assert env["dashboards"].find_one({"dashboard_id": child}) is not None


def test_deleting_a_published_dashboard_is_refused(env, editor) -> None:
    _, main, child = _locked_family(env, editor)

    _conflict(dash_routes.delete_dashboard(main, editor))

    assert env["dashboards"].count_documents({}) == 2


def test_reordering_a_published_family_is_refused(env, editor) -> None:
    _, main, child = _locked_family(env, editor)

    _conflict(
        dash_routes.reorder_tabs(
            {
                "parent_dashboard_id": str(main),
                "tab_orders": [{"dashboard_id": str(child), "tab_order": 5}],
            },
            editor,
        )
    )

    assert env["dashboards"].find_one({"dashboard_id": child})["tab_order"] == 1


def test_appearance_of_a_published_dashboard_is_refused(env, editor) -> None:
    from depictio.models.models.branding import BrandTheme

    _, main, _ = _locked_family(env, editor)

    _conflict(dash_routes.update_dashboard_appearance(main, BrandTheme(), editor))


def test_the_content_editor_guard_leaves_the_plain_editor_check_alone(env, editor) -> None:
    """Comments reuse `_require_dashboard_editor`, which must stay open."""
    _, main, _ = _locked_family(env, editor)

    assert dash_routes._require_dashboard_editor(main, editor)["dashboard_id"] == main
    with pytest.raises(HTTPException) as exc:
        dash_routes._require_dashboard_content_editor(main, editor)
    assert exc.value.status_code == 409


def test_import_json_into_a_published_project_is_refused_for_editors(env, editor) -> None:
    project, _, _ = _locked_family(env, editor)

    _conflict(
        dash_routes.import_dashboard_from_json(
            {"_depictio_export_version": "1.0", "dashboard": {"title": "I"}},
            project_id=str(project),
            validate_integrity=False,
            current_user=editor,
        )
    )

    assert env["dashboards"].count_documents({}) == 2


def test_import_yaml_into_a_published_project_is_refused_for_editors(env, editor) -> None:
    project, _, _ = _locked_family(env, editor)

    with pytest.raises(HTTPException) as exc:
        dash_routes.import_dashboard_yaml_content(
            "title: Imported\nproject_tag: p\n", project, True, editor
        )

    assert exc.value.status_code == 409
    assert env["dashboards"].count_documents({}) == 2


def _version_record(family_id):
    return {"version_id": "v1", "family_id": str(family_id), "pinned": False, "tabs": [{}]}


def test_restoring_a_version_of_a_published_dashboard_is_refused(env, editor) -> None:
    _, main, _ = _locked_family(env, editor)
    with patch.object(ver_routes, "_guarded_version", return_value=_version_record(main)):
        _conflict(ver_routes.restore_dashboard_version("v1", editor))


def test_deleting_a_version_of_a_published_dashboard_is_refused(env, editor) -> None:
    _, main, _ = _locked_family(env, editor)
    with patch.object(ver_routes, "_guarded_version", return_value=_version_record(main)):
        _conflict(ver_routes.delete_dashboard_version("v1", False, editor))


def test_restoring_a_component_of_a_published_dashboard_is_refused(env, editor) -> None:
    _, main, _ = _locked_family(env, editor)
    payload = ver_routes.RestoreComponentRequest(component_index="c1", tab_id=str(main))
    with patch.object(ver_routes, "_guarded_version", return_value=_version_record(main)):
        _conflict(ver_routes.restore_component_from_version("v1", payload, editor))


def test_get_reports_the_lock_and_a_visitors_copy_has_none(env, editor, visitor) -> None:
    project, main, _ = _locked_family(env, editor)
    copy = _dashboard(env, project, title="Copy")

    locked = dash_routes._public_lock(env["dashboards"].find_one({"dashboard_id": main}))
    free = dash_routes._public_lock(env["dashboards"].find_one({"dashboard_id": copy}))

    assert locked == {"locked_at": "2026-01-01T00:00:00", "reason": "release", "source": "manual"}
    assert free is None


def test_a_save_round_tripping_the_get_payload_is_accepted_and_stores_no_lock(env, editor) -> None:
    """``/get`` adds ``published_lock``; the editor sends the document back to ``/save``.

    The body model forbids extra keys, so without the field every editor save
    was a 422. The lock lives on the project: a save must never write it.
    """
    project = _project(env, owner=editor, locked=False)
    did, data = _save_new(
        project, editor, published_lock={"locked_at": "2026-01-01T00:00:00", "source": "manual"}
    )

    asyncio.run(dash_routes.save_dashboard(dashboard_id=did, data=data, current_user=editor))

    stored = env["dashboards"].find_one({"dashboard_id": did})
    assert stored is not None
    assert "published_lock" not in stored
