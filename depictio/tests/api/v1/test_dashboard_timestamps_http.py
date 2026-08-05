"""Full-stack HTTP verification of issue #932 against a real MongoDB.

Everything else in the suite mocks the database (mongomock) or calls route
functions directly. This drives the actual FastAPI app over HTTP with
TestClient, against a real mongod, so the whole chain is exercised:
request → auth → pydantic model → MongoDB write → listing projection → response.

That matters because the two integrity bugs this work uncovered (a `$set` on
the immutable `_id`, and a blanked `screenshot_ts`) are precisely the kind that
only a real server rejects — mongomock is more permissive than mongod.

Requires a mongod reachable at DEPICTIO_TEST_MONGO_PORT (default 27055):

    docker run -d --name depictio-issue932-mongo -p 27055:27017 mongo:8.0.14
"""

import os
import socket
from datetime import datetime, timezone

import bcrypt
import pytest
from bson import ObjectId

TS_FMT = "%Y-%m-%d %H:%M:%S"
MONGO_PORT = int(os.environ.get("DEPICTIO_TEST_MONGO_PORT", "27055"))


def _mongo_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", MONGO_PORT), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_reachable(),
    reason=(
        f"no mongod on localhost:{MONGO_PORT}; start one with: docker run -d "
        f"--name depictio-issue932-mongo -p {MONGO_PORT}:27017 mongo:8.0.14"
    ),
)


@pytest.fixture(scope="module")
def client_and_db():
    """TestClient wired to the real app, plus a handle on the real collections."""
    from fastapi.testclient import TestClient

    from depictio.api.main import app
    from depictio.api.v1.db import dashboards_collection, users_collection
    from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
    from depictio.models.models.users import UserBase

    owner = UserBase(id=ObjectId(), email="owner@example.com")
    owner.is_admin = True
    # Drop any row left by an interrupted earlier run: the app validates every
    # user document at startup, so one malformed leftover breaks the whole app.
    users_collection.delete_many({"email": owner.email})
    # `password` is required by the UserBeanie document the app validates on
    # startup; the value is irrelevant since auth is overridden below.
    users_collection.insert_one(
        {
            "_id": owner.id,
            "email": owner.email,
            "is_admin": True,
            "is_anonymous": False,
            # Must look bcrypt-hashed ($2b$) or the User model rejects it at
            # startup. The value is never checked: auth is overridden below.
            "password": bcrypt.hashpw(b"unused", bcrypt.gensalt()).decode(),
        }
    )

    # Auth itself is not what's under test here; override it so the test
    # targets the timestamp/document behavior rather than token plumbing.
    app.dependency_overrides[get_user_or_anonymous] = lambda: owner

    with TestClient(app) as c:
        yield c, dashboards_collection, owner

    app.dependency_overrides.clear()
    users_collection.delete_many({"_id": owner.id})


def _payload(dashboard_id, project_id, owner, *, title="My dashboard", **extra):
    """A payload shaped like the React client's `createDashboard` — notably
    WITHOUT `_id`, which is what triggered the immutable-field failure."""
    body = {
        "dashboard_id": str(dashboard_id),
        "version": 1,
        "title": title,
        "project_id": str(project_id),
        "permissions": {
            "owners": [{"_id": str(owner.id), "email": owner.email}],
            "editors": [],
            "viewers": [],
        },
        "is_public": False,
        "last_saved_ts": "",
        "is_main_tab": True,
        "tab_order": 0,
    }
    body.update(extra)
    return body


@pytest.fixture
def project(client_and_db):
    """A real project row so the save route's permission check passes."""
    from depictio.api.v1.db import projects_collection

    _, _, owner = client_and_db
    pid = ObjectId()
    projects_collection.insert_one(
        {
            "_id": pid,
            "name": f"proj-{pid}",
            "is_public": False,
            "permissions": {
                "owners": [{"_id": owner.id, "email": owner.email}],
                "editors": [],
                "viewers": [],
            },
        }
    )
    yield pid
    projects_collection.delete_many({"_id": pid})


class TestSaveOverHttp:
    def test_create_then_edit_over_http(self, client_and_db, project):
        """Issue #932's verification step, end to end over HTTP."""
        client, dashboards, owner = client_and_db
        did = ObjectId()

        r1 = client.post(
            f"/depictio/api/v1/dashboards/save/{did}", json=_payload(did, project, owner)
        )
        assert r1.status_code == 200, r1.text

        created = dashboards.find_one({"dashboard_id": did})
        assert created is not None, "dashboard was not persisted"
        first_saved = created["last_saved_ts"]
        assert created["creation_time"], "creation_time must be stamped on insert"

        r2 = client.post(
            f"/depictio/api/v1/dashboards/save/{did}",
            json=_payload(did, project, owner, title="Renamed"),
        )
        assert r2.status_code == 200, r2.text

        edited = dashboards.find_one({"dashboard_id": did})
        assert edited["title"] == "Renamed", "the edit must actually land"
        assert edited["creation_time"] == created["creation_time"], "creation must not move"
        assert edited["last_saved_ts"] >= first_saved, "modification must not go backwards"

        dashboards.delete_many({"dashboard_id": did})

    def test_real_mongod_accepts_repeated_saves_without_id(self, client_and_db, project):
        """The immutable-`_id` regression: real mongod REJECTS a `$set` on `_id`.

        mongomock is more permissive, so only this test proves the fix against
        the database the product actually runs on.
        """
        client, dashboards, owner = client_and_db
        did = ObjectId()

        for i in range(3):
            r = client.post(
                f"/depictio/api/v1/dashboards/save/{did}",
                json=_payload(did, project, owner, title=f"v{i}"),
            )
            assert r.status_code == 200, f"save {i} failed: {r.text}"

        assert dashboards.count_documents({"dashboard_id": did}) == 1
        stored = dashboards.find_one({"dashboard_id": did})
        assert stored["title"] == "v2"
        assert stored["_id"] == did, "_id must stay pinned to dashboard_id"

        dashboards.delete_many({"dashboard_id": did})

    def test_stored_time_is_utc_over_http(self, client_and_db, project):
        client, dashboards, owner = client_and_db
        did = ObjectId()
        client.post(f"/depictio/api/v1/dashboards/save/{did}", json=_payload(did, project, owner))

        stored = dashboards.find_one({"dashboard_id": did})
        produced = datetime.strptime(stored["last_saved_ts"], TS_FMT)
        expected = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((produced - expected).total_seconds()) < 10

        dashboards.delete_many({"dashboard_id": did})

    def test_screenshot_ts_survives_a_save_over_http(self, client_and_db, project):
        client, dashboards, owner = client_and_db
        did = ObjectId()
        client.post(f"/depictio/api/v1/dashboards/save/{did}", json=_payload(did, project, owner))
        dashboards.update_one(
            {"dashboard_id": did}, {"$set": {"screenshot_ts": "2024-05-05 05:05:05"}}
        )

        r = client.post(
            f"/depictio/api/v1/dashboards/save/{did}",
            json=_payload(did, project, owner, title="Edited"),
        )
        assert r.status_code == 200, r.text
        assert dashboards.find_one({"dashboard_id": did})["screenshot_ts"] == "2024-05-05 05:05:05"

        dashboards.delete_many({"dashboard_id": did})


class TestListingOverHttp:
    def test_listing_returns_creation_time(self, client_and_db, project):
        """The field must survive the projection and reach the JSON response."""
        client, dashboards, owner = client_and_db
        did = ObjectId()
        client.post(f"/depictio/api/v1/dashboards/save/{did}", json=_payload(did, project, owner))

        r = client.get("/depictio/api/v1/dashboards/list")
        assert r.status_code == 200, r.text
        body = r.json()
        entries = body if isinstance(body, list) else body.get("dashboards", [])
        entry = next((e for e in entries if str(e.get("dashboard_id")) == str(did)), None)

        assert entry is not None, "saved dashboard missing from the listing"
        assert entry.get("creation_time"), "listing must expose creation_time to the UI"

        dashboards.delete_many({"dashboard_id": did})

    def test_legacy_document_is_backfilled_over_http(self, client_and_db, project):
        """A row written before `creation_time` existed still gets a real date."""
        client, dashboards, owner = client_and_db
        moment = datetime(2023, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        did = ObjectId.from_datetime(moment)
        dashboards.insert_one(
            {
                "_id": did,
                "dashboard_id": did,
                "title": "Legacy",
                "project_id": project,
                "is_main_tab": True,
                "last_saved_ts": "2026-08-04 09:00:00",
                "permissions": {
                    "owners": [{"_id": owner.id, "email": owner.email}],
                    "viewers": [],
                },
            }
        )

        r = client.get("/depictio/api/v1/dashboards/list")
        entries = r.json() if isinstance(r.json(), list) else r.json().get("dashboards", [])
        entry = next((e for e in entries if str(e.get("dashboard_id")) == str(did)), None)

        assert entry is not None
        assert entry["creation_time"] == "2023-06-15 08:00:00"
        assert entry["creation_time"] != entry["last_saved_ts"], "columns must be distinct"

        dashboards.delete_many({"dashboard_id": did})
