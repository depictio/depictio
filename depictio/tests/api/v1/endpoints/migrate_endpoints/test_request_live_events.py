"""An inbound request announces itself to admin browsers over the live channel (#1303)."""

from __future__ import annotations

import pytest
from bson import ObjectId

from depictio.api.v1.monitoring import publish as monitoring_publish
from depictio.api.v1.services import migration_import

from .invite_helpers import invite_world
from .push_helpers import push


@pytest.fixture
def world(monkeypatch, target_db, captures):
    return invite_world(monkeypatch, target_db)


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple[str, str, str | None, str | None]] = []
    monkeypatch.setattr(
        monitoring_publish,
        "publish_migration_event",
        lambda request_id, status, project_name, source: seen.append(
            (request_id, status, project_name, source)
        ),
    )
    return seen


def test_new_request_is_announced_as_pending(world, events):
    out = push(world.payload, world.source)

    assert [(e[0], e[1]) for e in events] == [(out["request_id"], "pending")]
    assert events[0][2]  # the project name travels, for the toast


def test_status_change_is_announced(world, events):
    out = push(world.payload, world.source)
    events.clear()

    migration_import._set_request(ObjectId(out["request_id"]), status="imported")

    assert [(e[0], e[1]) for e in events] == [(out["request_id"], "imported")]


def test_a_write_without_status_stays_quiet(world, events):
    out = push(world.payload, world.source)
    events.clear()

    migration_import._set_request(ObjectId(out["request_id"]), report={})

    assert events == []


def test_a_failing_publisher_never_breaks_the_import(world, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(monitoring_publish, "publish_migration_event", boom)

    out = push(world.payload, world.source)

    assert out["status"] == "pending"
