"""Tests for the shared UTC timestamp helpers (issue #932).

The wire format is a naive ``"%Y-%m-%d %H:%M:%S"`` string that clients read as
UTC, so the critical property is that everything produced here really is UTC
and really matches that shape.
"""

import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from depictio.models.timestamps import (
    TIMESTAMP_FORMAT,
    objectid_creation_str,
    utc_now,
    utc_now_str,
)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestUtcNow:
    def test_utc_now_is_timezone_aware_utc(self):
        now = utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(0)

    def test_utc_now_str_matches_wire_format(self):
        assert TS_RE.match(utc_now_str())

    def test_utc_now_str_is_utc_not_local(self):
        """The string must be UTC wall-clock, even when TZ is not UTC.

        This is the actual regression from #932: `datetime.now()` produced the
        server's local time, which a CEST developer saw rendered two hours off.
        """
        produced = datetime.strptime(utc_now_str(), TIMESTAMP_FORMAT)
        expected = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((produced - expected).total_seconds()) < 5

    def test_utc_now_str_is_parseable_with_the_declared_format(self):
        assert datetime.strptime(utc_now_str(), TIMESTAMP_FORMAT)


class TestObjectIdCreationStr:
    def test_derives_generation_time_from_objectid(self):
        oid = ObjectId()
        result = objectid_creation_str(oid)
        assert TS_RE.match(result)
        produced = datetime.strptime(result, TIMESTAMP_FORMAT)
        expected = oid.generation_time.astimezone(timezone.utc).replace(tzinfo=None)
        assert produced == expected.replace(microsecond=0)

    def test_accepts_a_string_objectid(self):
        oid = ObjectId()
        assert objectid_creation_str(str(oid)) == objectid_creation_str(oid)

    def test_known_objectid_round_trips_to_its_embedded_timestamp(self):
        """ObjectIds embed a 4-byte big-endian epoch-seconds prefix."""
        moment = datetime(2024, 3, 1, 12, 34, 56, tzinfo=timezone.utc)
        oid = ObjectId.from_datetime(moment)
        assert objectid_creation_str(oid) == "2024-03-01 12:34:56"

    def test_returns_empty_string_for_garbage(self):
        assert objectid_creation_str("not-an-objectid") == ""
        assert objectid_creation_str(None) == ""


class TestPreservedCreationTime:
    """The write-once rule behind issue #932.

    A client round-trips the whole document on save, so the creation timestamp
    must come from the *stored* document, never from the incoming payload.
    """

    def test_prefers_the_stored_creation_time(self):
        from depictio.models.timestamps import preserved_creation_time

        existing = {"creation_time": "2024-01-01 00:00:00"}
        assert (
            preserved_creation_time(existing, ObjectId(), "2026-08-04 09:00:00")
            == "2024-01-01 00:00:00"
        )

    def test_prefers_the_stored_registration_time_for_projects(self):
        from depictio.models.timestamps import preserved_creation_time

        existing = {"registration_time": "2024-01-01 00:00:00"}
        assert (
            preserved_creation_time(existing, ObjectId(), "2026-08-04 09:00:00")
            == "2024-01-01 00:00:00"
        )

    def test_falls_back_to_the_objectid_for_legacy_documents(self):
        from depictio.models.timestamps import preserved_creation_time

        oid = ObjectId.from_datetime(datetime(2023, 6, 15, 8, 0, 0, tzinfo=timezone.utc))
        assert preserved_creation_time({}, oid, "2026-08-04 09:00:00") == "2023-06-15 08:00:00"

    def test_uses_the_fallback_for_brand_new_documents(self):
        from depictio.models.timestamps import preserved_creation_time

        assert (
            preserved_creation_time(None, "not-an-objectid", "2026-08-04 09:00:00")
            == "2026-08-04 09:00:00"
        )

    def test_an_edit_never_advances_the_creation_time(self):
        """Regression: created and modified must stay distinct after an edit."""
        from depictio.models.timestamps import preserved_creation_time

        created = "2024-01-01 00:00:00"
        stored = {"creation_time": created}
        # Simulate three successive saves, each sending back a payload that
        # (wrongly) claims a fresh creation time.
        for modified in ("2024-01-02 10:00:00", "2024-03-04 11:00:00", "2026-08-04 09:00:00"):
            stored["creation_time"] = preserved_creation_time(stored, ObjectId(), modified)
            assert stored["creation_time"] == created
            assert stored["creation_time"] != modified


class TestHandWrittenObjectIds:
    """Seed data uses literal ids whose 4-byte prefix is not a real timestamp.

    ``746b0f3c...`` decodes to 2031, so a naive backfill showed dashboards as
    "created" years in the future — and *after* their own modification date.
    """

    def test_future_dated_objectid_is_rejected(self):
        # The literal id used by Depictio's viralrecon seed dashboard.
        assert objectid_creation_str(ObjectId("746b0f3c1e4a2d7f8e5b9ca2")) == ""

    def test_past_dated_seed_objectid_is_still_accepted(self):
        # ...while the 6-prefixed seed ids decode to a plausible 2023 date.
        assert objectid_creation_str(ObjectId("646b0f3c1e4a2d7f8e5b8ca2")) == "2023-05-22 06:44:12"

    def test_a_freshly_minted_objectid_is_accepted(self):
        """Guard the boundary: 'now' must not be rejected as 'the future'."""
        assert objectid_creation_str(ObjectId()) != ""

    def test_preserved_creation_time_falls_back_when_objectid_is_bogus(self):
        from depictio.models.timestamps import preserved_creation_time

        assert (
            preserved_creation_time({}, ObjectId("746b0f3c1e4a2d7f8e5b9ca2"), "2026-08-04 09:00:00")
            == "2026-08-04 09:00:00"
        )
