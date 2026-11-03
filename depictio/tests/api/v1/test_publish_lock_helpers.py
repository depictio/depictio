"""The published-lock helpers (#1303): what is frozen, and who may still add."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.models.models.users import UserBase


@pytest.fixture
def db():
    database = mongomock.MongoClient()["t"]
    ns = SimpleNamespace(
        projects_collection=database["projects"], dashboards_collection=database["dashboards"]
    )
    with patch.object(publish_lock, "_db", lambda: ns):
        yield ns


@pytest.fixture
def world(db):
    owner = UserBase(id=ObjectId(), email="owner@x.org")
    owner.is_admin = False
    visitor = UserBase(id=ObjectId(), email="visitor@x.org")
    visitor.is_admin = False
    pid, dc, wf = ObjectId(), ObjectId(), ObjectId()
    published, child, copy = ObjectId(), ObjectId(), ObjectId()
    db.projects_collection.insert_one(
        {
            "_id": pid,
            "is_public": True,
            "permissions": {"owners": [{"_id": owner.id}], "editors": [], "viewers": ["*"]},
            "workflows": [{"_id": wf, "data_collections": [{"_id": dc}]}],
            "published_lock": {"reason": "release 1", "dashboard_ids": [str(published)]},
        }
    )
    db.dashboards_collection.insert_many(
        [
            {"_id": published, "dashboard_id": published, "project_id": pid, "is_main_tab": True},
            {
                "_id": child,
                "dashboard_id": child,
                "project_id": pid,
                "is_main_tab": False,
                "parent_dashboard_id": published,
            },
            {"_id": copy, "dashboard_id": copy, "project_id": pid, "is_main_tab": True},
        ]
    )
    return SimpleNamespace(
        owner=owner, visitor=visitor, pid=pid, dc=dc, wf=wf, published=published, child=child, copy=copy
    )


def _is_409(fn, *args):
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    return exc.value.status_code == 409


def test_project_dc_and_workflow_of_a_locked_project_refuse(world):
    assert _is_409(publish_lock.assert_project_unlocked, world.pid)
    assert _is_409(publish_lock.assert_project_unlocked, str(world.pid))
    assert _is_409(publish_lock.assert_dc_project_unlocked, world.dc)
    assert _is_409(publish_lock.assert_workflow_project_unlocked, world.wf)


def test_published_dashboard_and_its_tabs_refuse_but_a_copy_does_not(world):
    assert _is_409(publish_lock.assert_dashboard_unlocked, world.published)
    assert _is_409(publish_lock.assert_dashboard_unlocked, world.child)
    publish_lock.assert_dashboard_unlocked(world.copy)  # a visitor's copy stays editable


def test_a_visitor_may_create_a_copy_but_not_a_tab_of_the_release(world):
    publish_lock.assert_dashboard_creation_allowed(world.pid, world.visitor)
    assert _is_409(
        publish_lock.assert_dashboard_creation_allowed, world.pid, world.visitor, world.published
    )


def test_owner_and_admin_cannot_add_to_a_release(world):
    assert _is_409(publish_lock.assert_dashboard_creation_allowed, world.pid, world.owner)
    admin = UserBase(id=ObjectId(), email="admin@x.org")
    admin.is_admin = True
    assert _is_409(publish_lock.assert_dashboard_creation_allowed, world.pid, admin)


def test_unlocked_project_is_unaffected(world, db):
    db.projects_collection.update_one({"_id": world.pid}, {"$set": {"published_lock": None}})
    publish_lock.assert_project_unlocked(world.pid)
    publish_lock.assert_dc_project_unlocked(world.dc)
    publish_lock.assert_dashboard_unlocked(world.published)
    publish_lock.assert_dashboard_creation_allowed(world.pid, world.owner)


def test_unknown_ids_do_not_raise(world):
    publish_lock.assert_project_unlocked(ObjectId())
    publish_lock.assert_dc_project_unlocked("not-an-id")
    publish_lock.assert_dashboard_unlocked(ObjectId())
