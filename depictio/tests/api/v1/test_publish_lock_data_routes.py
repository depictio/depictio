"""The published lock on data-mutating routes (#1303): 409 on a locked project.

Covers the project, data-collection, deltatable, files, multiqc and link routes.
Each test seeds a mongomock project, points ``publish_lock._db`` at it, and calls
the route function directly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.deltatables_endpoints import routes as dt_routes
from depictio.api.v1.endpoints.files_endpoints import routes as files_routes
from depictio.api.v1.endpoints.links_endpoints import routes as links_routes
from depictio.api.v1.endpoints.multiqc_endpoints import routes as mq_routes
from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.api.v1.endpoints.projects_endpoints import routes as proj_routes
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase

PID, WF, DC = ObjectId(), ObjectId(), ObjectId()


def _admin() -> UserBase:
    user = UserBase(id=ObjectId(), email="admin@example.org")
    user.is_admin = True
    return user


def _seed(database, *, locked: bool):
    doc = {
        "_id": PID,
        "name": "Frozen",
        "project_type": "advanced",
        "is_public": False,
        "registration_time": "2024-01-01 10:00:00",
        "workflows": [{"_id": WF, "workflow_tag": "wf", "data_collections": [{"_id": DC}]}],
        "data_collections": [],
        "links": [],
        "permissions": {"owners": [], "editors": [], "viewers": []},
    }
    if locked:
        doc["published_lock"] = {"reason": "release", "dashboard_ids": []}
    database["projects"].insert_one(doc)


@pytest.fixture
def make_db():
    """Factory: a mongomock database wired into every module under test."""
    patches = []

    def _make(locked: bool):
        database = mongomock.MongoClient()["t"]
        _seed(database, locked=locked)
        ns = SimpleNamespace(
            projects_collection=database["projects"],
            dashboards_collection=database["dashboards"],
        )
        for target, name, value in [
            (publish_lock, "_db", lambda: ns),
            (proj_routes, "projects_collection", database["projects"]),
            (dc_utils, "projects_collection", database["projects"]),
            (dt_routes, "projects_collection", database["projects"]),
            (dt_routes, "deltatables_collection", database["deltatables"]),
            (files_routes, "files_collection", database["files"]),
            (links_routes, "projects_collection", database["projects"]),
            (mq_routes, "projects_collection", database["projects"]),
        ]:
            p = patch.object(target, name, value)
            p.start()
            patches.append(p)
        return database

    yield _make
    for p in patches:
        p.stop()


def _assert_409(call):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 409
    assert exc.value.detail == publish_lock.LOCKED_DETAIL


def _project_body(name="Renamed") -> Project:
    return Project(
        id=PID,
        name=name,
        project_type="advanced",
        permissions=Permission(owners=[], editors=[], viewers=[]),
    )


# --- projects ---------------------------------------------------------------


def test_project_update_locked(make_db):
    db = make_db(True)
    _assert_409(
        lambda: asyncio.run(proj_routes.update_project(_project_body(), current_user=_admin()))
    )
    assert db["projects"].find_one({"_id": PID})["name"] == "Frozen"


def test_project_update_unlocked_still_works(make_db):
    db = make_db(False)
    asyncio.run(proj_routes.update_project(_project_body(), current_user=_admin()))
    assert db["projects"].find_one({"_id": PID})["name"] == "Renamed"


def test_project_delete_locked(make_db):
    db = make_db(True)
    # ProjectResponse needs fully-formed collections; the lock reads only the project.
    db["projects"].update_one({"_id": PID}, {"$set": {"workflows": []}})
    with patch.object(proj_routes, "_cascade_delete_project") as cascade:
        _assert_409(
            lambda: asyncio.run(proj_routes.delete_project(project_id=PID, current_user=_admin()))
        )
        cascade.assert_not_called()
    assert db["projects"].count_documents({}) == 1


def test_toggle_public_private_locked_for_a_non_admin(make_db, monkeypatch):
    db = make_db(True)
    owner = UserBase(id=ObjectId(), email="owner@example.org")
    monkeypatch.setattr(proj_routes, "_async_get_project_from_id", lambda *_: {"_id": PID})
    monkeypatch.setattr(proj_routes, "_can_manage_project_sharing", lambda *_: True)
    _assert_409(
        lambda: asyncio.run(
            proj_routes.toggle_public_private(
                project_id=str(PID), is_public="true", current_user=owner
            )
        )
    )
    assert db["projects"].find_one({"_id": PID})["is_public"] is False


def test_an_admin_may_publish_a_locked_release(make_db, monkeypatch):
    """Lock, then make public: visibility is not content (#1303)."""
    db = make_db(True)
    monkeypatch.setattr(proj_routes, "cascade_project_visibility", lambda *_: {})
    asyncio.run(
        proj_routes.toggle_public_private(
            project_id=str(PID), is_public="true", current_user=_admin()
        )
    )
    doc = db["projects"].find_one({"_id": PID})
    assert doc["is_public"] is True and doc.get("published_lock")


def test_project_storage_locked(make_db):
    make_db(True)
    _assert_409(
        lambda: asyncio.run(
            proj_routes.delete_project_storage(project_id=str(PID), current_user=_admin())
        )
    )


# --- data collections -------------------------------------------------------


def test_dc_rename_locked_through_project_with_dc_access(make_db):
    db = make_db(True)
    _assert_409(
        lambda: asyncio.run(dc_utils._update_data_collection_name(str(DC), "new", _admin()))
    )
    assert (
        "data_collection_tag"
        not in db["projects"].find_one({})["workflows"][0]["data_collections"][0]
    )


def test_dc_delete_locked(make_db):
    db = make_db(True)
    _assert_409(lambda: asyncio.run(dc_utils._delete_data_collection_by_id(str(DC), _admin())))
    assert db["projects"].find_one({})["workflows"][0]["data_collections"]


def test_dc_viewer_level_lookup_is_not_blocked(make_db):
    make_db(True)
    project = dc_utils._project_with_dc_access(DC, _admin(), "viewer")
    assert project["_id"] == PID


def test_editable_project_and_token_locked(make_db):
    make_db(True)
    _assert_409(lambda: dc_utils._editable_project_and_token(str(PID), _admin()))


# --- deltatables ------------------------------------------------------------


def test_deltatable_upsert_locked(make_db):
    make_db(True)
    payload = SimpleNamespace(data_collection_id=DC)
    _assert_409(
        lambda: asyncio.run(dt_routes.upsert_deltatable(payload=payload, current_user=_admin()))
    )


def _delta_doc(database):
    dt_id = ObjectId()
    database["deltatables"].insert_one(
        {
            "_id": dt_id,
            "data_collection_id": DC,
            "delta_table_location": f"s3://bucket/{DC}",
        }
    )
    return dt_id


def test_deltatable_delete_locked_leaves_s3_alone(make_db):
    db = make_db(True)
    dt_id = _delta_doc(db)
    with patch.object(dt_routes.boto3, "client") as client:
        _assert_409(
            lambda: asyncio.run(
                dt_routes.delete_deltatable(deltatable_id=str(dt_id), current_user=_admin())
            )
        )
        client.return_value.delete_objects.assert_not_called()
    assert db["deltatables"].count_documents({}) == 1


def test_deltatable_delete_checks_ownership_before_s3(make_db):
    db = make_db(False)
    dt_id = _delta_doc(db)
    stranger = UserBase(id=ObjectId(), email="stranger@example.org")
    stranger.is_admin = False
    with (
        patch.object(dt_routes, "get_user_group_ids", return_value=[]),
        patch.object(dt_routes.boto3, "client") as client,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                dt_routes.delete_deltatable(deltatable_id=str(dt_id), current_user=stranger)
            )
        assert exc.value.status_code == 404
        client.assert_not_called()
    assert db["deltatables"].count_documents({}) == 1


def test_deltatable_delete_owner_strips_bucket_prefix(make_db):
    db = make_db(False)
    dt_id = _delta_doc(db)
    with (
        patch.object(dt_routes.settings.s3, "bucket", "bucket"),
        patch.object(dt_routes.boto3, "client") as client,
    ):
        s3 = client.return_value
        s3.list_objects_v2.return_value = {"Contents": [{"Key": f"{DC}/part.parquet"}]}
        asyncio.run(dt_routes.delete_deltatable(deltatable_id=str(dt_id), current_user=_admin()))
        assert s3.list_objects_v2.call_args.kwargs["Prefix"] == str(DC)
        s3.delete_objects.assert_called_once()
    assert db["deltatables"].count_documents({}) == 0


def test_s3_prefix_helper():
    assert dt_routes._s3_prefix_of("s3://b/abc/def", "b") == "abc/def"
    assert dt_routes._s3_prefix_of("/abc", "b") == "abc"
    assert dt_routes._s3_prefix_of("s3://other/abc", "b") == "abc"


# --- files ------------------------------------------------------------------


def test_files_upsert_batch_locked(make_db):
    make_db(True)
    payload = SimpleNamespace(files=[SimpleNamespace(data_collection_id=DC)], update=False)
    _assert_409(
        lambda: asyncio.run(files_routes.create_file(payload=payload, current_user=_admin()))
    )


def test_files_delete_locked_and_unlocked(make_db):
    db = make_db(True)
    file_id = ObjectId()
    db["files"].insert_one({"_id": file_id, "data_collection_id": DC})
    _assert_409(
        lambda: asyncio.run(files_routes.delete_file(file_id=str(file_id), current_user=_admin()))
    )
    assert db["files"].count_documents({}) == 1
    payload = SimpleNamespace(file_ids=[str(file_id)])
    _assert_409(
        lambda: asyncio.run(files_routes.delete_files_batch(payload=payload, current_user=_admin()))
    )
    assert db["files"].count_documents({}) == 1


# --- multiqc ----------------------------------------------------------------


def test_multiqc_create_locked(make_db):
    make_db(True)
    report = SimpleNamespace(data_collection_id=DC)
    with (
        patch.object(mq_routes, "check_project_permission", return_value=True),
        patch.object(mq_routes, "create_multiqc_report_in_db") as create,
    ):
        _assert_409(
            lambda: asyncio.run(
                mq_routes.create_multiqc_report(report=report, current_user=_admin())
            )
        )
        create.assert_not_called()


def test_multiqc_create_requires_editor(make_db):
    make_db(False)
    report = SimpleNamespace(data_collection_id=DC)
    with (
        patch.object(mq_routes, "check_project_permission", return_value=False),
        patch.object(mq_routes, "create_multiqc_report_in_db") as create,
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(mq_routes.create_multiqc_report(report=report, current_user=_admin()))
        assert exc.value.status_code == 404
        create.assert_not_called()


def test_multiqc_create_unlocked_editor_passes(make_db):
    make_db(False)
    report = SimpleNamespace(data_collection_id=DC)
    saved = MagicMock()
    with (
        patch.object(mq_routes, "check_project_permission", return_value=True),
        patch.object(mq_routes, "create_multiqc_report_in_db", return_value=saved),
        patch.object(mq_routes, "MultiQCReportResponse") as resp,
    ):
        asyncio.run(mq_routes.create_multiqc_report(report=report, current_user=_admin()))
        resp.assert_called_once()


def test_multiqc_viewer_check_not_locked(make_db):
    make_db(True)
    with patch.object(mq_routes, "check_project_permission", return_value=True):
        assert mq_routes._require_dc_permission_or_404(str(DC), _admin(), "viewer") == str(PID)


# --- links ------------------------------------------------------------------


def test_link_create_locked(make_db):
    db = make_db(True)
    request = SimpleNamespace()
    _assert_409(
        lambda: asyncio.run(
            links_routes.create_link(request=request, project_id=str(PID), current_user=_admin())
        )
    )
    assert db["projects"].find_one({})["links"] == []


def test_link_delete_locked(make_db):
    make_db(True)
    _assert_409(
        lambda: asyncio.run(
            links_routes.delete_link(
                project_id=str(PID), link_id=str(ObjectId()), current_user=_admin()
            )
        )
    )
