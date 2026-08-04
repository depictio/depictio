"""End-to-end timestamp behavior of the real save route (issue #932).

These call ``save_dashboard`` / ``update_project`` themselves, against a
mongomock-backed collection, rather than re-implementing their logic — so a
future refactor that drops the write-once rule fails here.

Verification from the issue: "Create then edit a dashboard; both columns show
correct, distinct timestamps."
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission, UserBase

TS_FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        # Screenshot dispatch reaches for celery/Playwright; irrelevant here and
        # already covered by test_dashboard_save_screenshot_guard.py.
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "check_project_permission", return_value=True),
    ):
        yield database


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_anonymous = False
    return u


def _dashboard(dashboard_id, project_id, owner, *, title="My dashboard", creation_time=""):
    return DashboardData(
        dashboard_id=dashboard_id,
        title=title,
        project_id=project_id,
        permissions=Permission(owners=[owner]),
        # A real client round-trips whatever it loaded; an editor that has never
        # seen the field sends the empty default.
        creation_time=creation_time,
    )


def _oid_at(moment_str):
    """An ObjectId whose embedded generation time is `moment_str` (UTC).

    Dashboard ids are minted client-side, so the ObjectId's generation time is
    the dashboard's true creation moment — and it outranks the save-time
    fallback in `preserved_creation_time`. Pinning it makes "created" fully
    deterministic.
    """
    return ObjectId.from_datetime(
        datetime.strptime(moment_str, TS_FMT).replace(tzinfo=timezone.utc)
    )


def _save(dashboard_id, data, user):
    return asyncio.run(
        dash_routes.save_dashboard(dashboard_id=dashboard_id, data=data, current_user=user)
    )


class TestSaveDashboardTimestamps:
    def test_create_then_edit_yields_correct_distinct_timestamps(self, db, user, monkeypatch):
        """The issue's own verification step, end to end."""
        dashboard_id = _oid_at("2024-01-01 10:00:00")
        project_id = ObjectId()

        # Pin the clock so "distinct" is a real assertion rather than a race
        # against sub-second execution.
        clock = ["2024-01-01 10:00:00"]
        monkeypatch.setattr(dash_routes, "utc_now_str", lambda: clock[0])

        _save(dashboard_id, _dashboard(dashboard_id, project_id, user), user)
        created = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert created["creation_time"] == "2024-01-01 10:00:00"
        assert created["last_saved_ts"] == "2024-01-01 10:00:00"

        # ...user edits the dashboard an hour later.
        clock[0] = "2024-01-01 11:00:00"
        _save(dashboard_id, _dashboard(dashboard_id, project_id, user, title="Renamed"), user)
        edited = db["dashboards"].find_one({"dashboard_id": dashboard_id})

        assert edited["title"] == "Renamed", "sanity: the edit actually landed"
        assert edited["creation_time"] == "2024-01-01 10:00:00", "creation must not move"
        assert edited["last_saved_ts"] == "2024-01-01 11:00:00", "modification must advance"
        assert edited["creation_time"] != edited["last_saved_ts"], (
            "issue #932: the two columns must be distinct after an edit"
        )

    def test_client_cannot_forge_the_creation_time(self, db, user, monkeypatch):
        """A malicious or merely stale client payload must not win."""
        dashboard_id = _oid_at("2024-01-01 10:00:00")
        project_id = ObjectId()
        monkeypatch.setattr(dash_routes, "utc_now_str", lambda: "2024-01-01 10:00:00")
        _save(dashboard_id, _dashboard(dashboard_id, project_id, user), user)

        monkeypatch.setattr(dash_routes, "utc_now_str", lambda: "2024-01-02 10:00:00")
        forged = _dashboard(dashboard_id, project_id, user, creation_time="1999-12-31 23:59:59")
        _save(dashboard_id, forged, user)

        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert stored["creation_time"] == "2024-01-01 10:00:00"

    def test_repeated_saves_never_drift_the_creation_time(self, db, user, monkeypatch):
        dashboard_id = _oid_at("2024-01-01 10:00:00")
        project_id = ObjectId()
        monkeypatch.setattr(dash_routes, "utc_now_str", lambda: "2024-01-01 10:00:00")
        _save(dashboard_id, _dashboard(dashboard_id, project_id, user), user)

        for day in range(2, 6):
            monkeypatch.setattr(dash_routes, "utc_now_str", lambda d=day: f"2024-01-0{d} 10:00:00")
            _save(dashboard_id, _dashboard(dashboard_id, project_id, user), user)
            stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
            assert stored["creation_time"] == "2024-01-01 10:00:00"
            assert stored["last_saved_ts"] == f"2024-01-0{day} 10:00:00"

    def test_stored_timestamp_is_utc_not_server_local(self, db, user):
        """The regression that produced the H-2 offset for a CEST user."""
        dashboard_id = ObjectId()
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user), user)

        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        produced = datetime.strptime(stored["last_saved_ts"], TS_FMT)
        expected_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((produced - expected_utc).total_seconds()) < 5

    def test_save_does_not_touch_the_screenshot_cache_buster(self, db, user):
        """`screenshot_ts` belongs to the worker; a save must leave it alone.

        Otherwise the listing would cache-bust against a PNG that hasn't been
        regenerated yet and re-cache the stale bytes.
        """
        dashboard_id = ObjectId()
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user), user)
        db["dashboards"].update_one(
            {"dashboard_id": dashboard_id}, {"$set": {"screenshot_ts": "2024-05-05 05:05:05"}}
        )

        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user, title="Edited"), user)
        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert stored["screenshot_ts"] == "2024-05-05 05:05:05"


class TestSaveDashboardDocumentIntegrity:
    """Guards for two failure modes the timestamp work surfaced."""

    def test_save_succeeds_when_the_client_omits_id(self, db, user):
        """`_id` is immutable; `$set`-ting a regenerated one aborts the write.

        `MongoModel.ensure_id` mints a fresh `_id` whenever the payload lacks
        one — which the React `createDashboard` shape does — so the second save
        would otherwise fail with "the (immutable) field '_id' was found to
        have been altered".
        """
        dashboard_id = ObjectId()
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user), user)
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user, title="Second"), user)

        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert stored["title"] == "Second"

    def test_insert_pins_id_to_dashboard_id(self, db, user):
        """The `_id == dashboard_id` invariant the import paths mark CRITICAL.

        Several call sites look a dashboard up by `_id` (cascade delete on user
        removal, db_init), so a freshly inserted document whose `_id` is a
        random ObjectId would be invisible to them.
        """
        dashboard_id = ObjectId()
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user), user)

        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert stored["_id"] == dashboard_id

    def test_screenshot_ts_survives_a_client_save(self, db, user):
        """The worker owns `screenshot_ts`; the model defaults it to "".

        A client round-trip would otherwise blank it, dropping the thumbnail
        cache-buster and letting the listing re-cache stale PNG bytes.
        """
        dashboard_id = ObjectId()
        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user), user)
        db["dashboards"].update_one(
            {"dashboard_id": dashboard_id}, {"$set": {"screenshot_ts": "2024-05-05 05:05:05"}}
        )

        _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user, title="Edited"), user)
        stored = db["dashboards"].find_one({"dashboard_id": dashboard_id})
        assert stored["screenshot_ts"] == "2024-05-05 05:05:05"

    def test_a_single_document_is_created_per_dashboard(self, db, user):
        """A regenerated `_id` must not fan out into duplicate documents."""
        dashboard_id = ObjectId()
        for i in range(3):
            _save(dashboard_id, _dashboard(dashboard_id, ObjectId(), user, title=f"v{i}"), user)
        assert db["dashboards"].count_documents({"dashboard_id": dashboard_id}) == 1
