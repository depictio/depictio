"""Dashboard listing exposes usable creation timestamps (issue #932).

The listing is what feeds the React "Created" / "Modified" columns, so the
projection must carry `creation_time`, and documents written before that field
existed must still yield a real creation date rather than a blank cell.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import core_functions


@pytest.fixture
def collections():
    client = mongomock.MongoClient()
    db = client["depictio_test"]
    with (
        patch.object(core_functions, "dashboards_collection", db["dashboards"]),
        patch.object(core_functions, "projects_collection", db["projects"]),
    ):
        yield db


def _insert(db, *, creation_time=None, oid_moment=None, title="Dash"):
    oid = ObjectId.from_datetime(oid_moment) if oid_moment else ObjectId()
    doc = {
        "_id": oid,
        "dashboard_id": oid,
        "title": title,
        "last_saved_ts": "2026-08-04 09:00:00",
        "project_id": ObjectId(),
        "is_main_tab": True,
        "permissions": {"owners": [], "viewers": []},
    }
    if creation_time is not None:
        doc["creation_time"] = creation_time
    db["dashboards"].insert_one(doc)
    return oid


class TestListingCreationTime:
    def test_projection_includes_creation_time(self):
        """A field absent from the projection can never reach the UI."""
        import inspect

        source = inspect.getsource(core_functions.load_dashboards_from_db)
        assert '"creation_time": 1' in source

    def test_stored_creation_time_is_returned_verbatim(self, collections):
        _insert(collections, creation_time="2024-01-01 00:00:00")
        result = core_functions.load_dashboards_from_db(owner=None, admin_mode=True)
        assert result["dashboards"][0]["creation_time"] == "2024-01-01 00:00:00"

    def test_legacy_document_is_backfilled_from_its_objectid(self, collections):
        """Documents predating the field must not render an empty cell."""
        moment = datetime(2023, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        _insert(collections, oid_moment=moment)
        result = core_functions.load_dashboards_from_db(owner=None, admin_mode=True)
        assert result["dashboards"][0]["creation_time"] == "2023-06-15 08:00:00"

    def test_created_and_modified_are_distinct_after_an_edit(self, collections):
        """The core symptom in #932: both columns showed the same value."""
        _insert(collections, creation_time="2024-01-01 00:00:00")
        entry = core_functions.load_dashboards_from_db(owner=None, admin_mode=True)["dashboards"][0]
        assert entry["creation_time"] != entry["last_saved_ts"]

    def test_empty_string_creation_time_is_also_backfilled(self, collections):
        """The model defaults to `""`, which is just as unusable as missing."""
        moment = datetime(2023, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        _insert(collections, creation_time="", oid_moment=moment)
        result = core_functions.load_dashboards_from_db(owner=None, admin_mode=True)
        assert result["dashboards"][0]["creation_time"] == "2023-06-15 08:00:00"


class TestSeedDataObjectIds:
    """Seed dashboards use hand-written ids whose prefix decodes to 2031."""

    def test_future_dated_objectid_falls_back_to_the_save_time(self, collections):
        """Never show a creation date that is after the modification date."""
        oid = ObjectId("746b0f3c1e4a2d7f8e5b9ca2")  # decodes to 2031
        collections["dashboards"].insert_one(
            {
                "_id": oid,
                "dashboard_id": oid,
                "title": "nf-core/viralrecon",
                "last_saved_ts": "2026-08-04 09:00:00",
                "project_id": ObjectId(),
                "is_main_tab": True,
                "permissions": {"owners": [], "viewers": []},
            }
        )
        entry = core_functions.load_dashboards_from_db(owner=None, admin_mode=True)["dashboards"][0]

        assert entry["creation_time"] == "2026-08-04 09:00:00"
        assert entry["creation_time"] <= entry["last_saved_ts"], (
            "creation must never be later than modification"
        )
