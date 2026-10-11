"""The S3 orphan cleanup never deletes a table that is still being created.

Every Delta write lands on S3 before its ``deltatables`` document exists, so for
a moment each new table looks orphaned. A cleanup pass in that window used to
delete it: at boot, seeding lost a few collections on every fresh deployment.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.utils_endpoints import core_functions
from depictio.api.v1.endpoints.utils_endpoints.core_functions import cleanup_orphaned_s3_files

REGISTERED = "646b0f3c1e4a2d7f8e5b8c9c"
OLD_ORPHAN = "646b0f3c1e4a2d7f8e5b8d03"
BEING_WRITTEN = "646b0f3c1e4a2d7f8e5b8cd3"

NOW = datetime.now(timezone.utc)
LONG_AGO = NOW - timedelta(days=2)


class FakeS3:
    """Enough of a boto3 S3 client for the cleanup: two listings and a delete."""

    def __init__(self, objects: dict[str, datetime]):
        self.objects = dict(objects)
        self.deleted: list[str] = []
        self.on_prefix_listing = None

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Delimiter=None, Prefix=None):
        if Delimiter:
            prefixes = sorted({key.split("/", 1)[0] + "/" for key in self.objects})
            return [{"CommonPrefixes": [{"Prefix": p} for p in prefixes]}]
        if self.on_prefix_listing:
            self.on_prefix_listing(Prefix.rstrip("/"))
        contents = [
            {"Key": key, "LastModified": written, "Size": 10}
            for key, written in sorted(self.objects.items())
            if key.startswith(Prefix)
        ]
        return [{"Contents": contents}] if contents else [{}]

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)
            self.deleted.append(obj["Key"])
        return {"Deleted": Delete["Objects"]}


def _table(dc_id: str, written: datetime) -> dict[str, datetime]:
    return {
        f"{dc_id}/part-00000.parquet": written,
        f"{dc_id}/_delta_log/00000000000000000000.json": written,
    }


@pytest.fixture
def store():
    db = mongomock.MongoClient().db
    db.deltatables.insert_one({"data_collection_id": ObjectId(REGISTERED)})
    s3 = FakeS3(
        {
            **_table(REGISTERED, LONG_AGO),
            **_table(OLD_ORPHAN, LONG_AGO),
            **_table(BEING_WRITTEN, NOW - timedelta(seconds=2)),
        }
    )
    with (
        patch.object(core_functions, "s3_client", s3),
        patch.object(core_functions, "deltatables_collection", db.deltatables),
        patch.object(core_functions, "multiqc_collection", db.multiqc),
    ):
        yield s3, db


def _prefixes(s3: FakeS3) -> set[str]:
    return {key.split("/", 1)[0] for key in s3.objects}


@pytest.mark.asyncio
async def test_a_table_written_seconds_ago_is_kept(store):
    s3, _ = store
    result = await cleanup_orphaned_s3_files(dry_run=False)

    assert result["orphaned_prefixes"] == [OLD_ORPHAN]
    assert result["recent_prefixes"] == [BEING_WRITTEN]
    assert _prefixes(s3) == {REGISTERED, BEING_WRITTEN}


@pytest.mark.asyncio
async def test_without_an_age_limit_a_fresh_orphan_goes_too(store):
    """The wipe-time pass in initialize_db runs before anything writes."""
    s3, _ = store
    result = await cleanup_orphaned_s3_files(dry_run=False, min_age_seconds=0)

    assert result["orphaned_prefixes"] == [BEING_WRITTEN, OLD_ORPHAN]
    assert _prefixes(s3) == {REGISTERED}


@pytest.mark.asyncio
async def test_a_table_registered_during_the_pass_is_kept(store):
    """MongoDB is read once up front; a write finishing after that is re-checked."""
    s3, db = store

    def register_while_listing(dc_id: str) -> None:
        if dc_id == OLD_ORPHAN:
            db.deltatables.insert_one({"data_collection_id": ObjectId(OLD_ORPHAN)})

    s3.on_prefix_listing = register_while_listing
    result = await cleanup_orphaned_s3_files(dry_run=False, min_age_seconds=0)

    assert OLD_ORPHAN in _prefixes(s3)
    assert result["orphaned_prefixes"] == [BEING_WRITTEN]


@pytest.mark.asyncio
async def test_a_multiqc_report_keeps_its_prefix(store):
    s3, db = store
    db.multiqc.insert_one({"data_collection_id": OLD_ORPHAN})
    await cleanup_orphaned_s3_files(dry_run=False)

    assert OLD_ORPHAN in _prefixes(s3)


@pytest.mark.asyncio
async def test_a_dry_run_reports_without_deleting(store):
    s3, _ = store
    result = await cleanup_orphaned_s3_files(dry_run=True)

    assert result["orphaned_prefixes"] == [OLD_ORPHAN]
    assert result["deleted_count"] == 2
    assert s3.deleted == []


@pytest.mark.asyncio
async def test_the_safety_check_still_stops_an_all_orphaned_listing(store):
    s3, db = store
    db.deltatables.delete_many({})
    result = await cleanup_orphaned_s3_files(dry_run=False, min_age_seconds=0)

    assert "Safety check failed" in result["error"]
    assert s3.deleted == []
