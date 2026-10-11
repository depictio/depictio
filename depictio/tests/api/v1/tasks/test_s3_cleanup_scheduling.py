"""The periodic S3 cleanup waits for seeding, and one worker runs each cycle.

Every API worker starts the loop. Its first pass used to land 30 s after the
worker started, in the middle of boot-time seeding, once per worker: each pass
could delete a table that was written but not yet registered.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import mongomock
import pytest

from depictio.api.v1.tasks import cleanup_tasks
from depictio.api.v1.tasks.cleanup_tasks import (
    S3_CLEANUP_STATE_ID,
    _claim_s3_cleanup_cycle,
    _wait_for_reference_seeding,
    periodic_cleanup_orphaned_s3_files,
)

METADATA_ID = "reference_datasets_metadata"


@pytest.fixture
def init_collection():
    collection = mongomock.MongoClient().db.initialization
    with patch.object(cleanup_tasks, "initialization_collection", collection):
        yield collection


@pytest.mark.asyncio
async def test_the_wait_lasts_until_seeding_is_done(init_collection):
    init_collection.insert_one({"_id": METADATA_ID, "projects": []})
    polls = 0

    async def seeding_finishes_on_the_second_poll(_seconds):
        nonlocal polls
        polls += 1
        if polls == 2:
            init_collection.update_one(
                {"_id": METADATA_ID}, {"$set": {"background_processing_complete": True}}
            )

    with patch.object(
        cleanup_tasks.asyncio, "sleep", side_effect=seeding_finishes_on_the_second_poll
    ):
        await _wait_for_reference_seeding()

    assert polls == 2


@pytest.mark.asyncio
async def test_failed_seeding_ends_the_wait_too(init_collection):
    init_collection.insert_one({"_id": METADATA_ID, "background_processing_failed": True})
    with patch.object(cleanup_tasks.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        await _wait_for_reference_seeding()
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_to_wait_for_when_nothing_is_seeded(init_collection):
    with patch.object(cleanup_tasks.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        await _wait_for_reference_seeding()
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_the_wait_gives_up_eventually(init_collection):
    """A processing thread that died without a flag must not stop the cleanup for good."""
    init_collection.insert_one({"_id": METADATA_ID})
    with (
        patch.object(cleanup_tasks, "_SEEDING_MAX_WAIT_SECONDS", 30),
        patch.object(cleanup_tasks.asyncio, "sleep", new_callable=AsyncMock) as sleep,
    ):
        await _wait_for_reference_seeding()
    assert sleep.await_count == 3


def test_one_worker_claims_each_cycle(init_collection):
    assert _claim_s3_cleanup_cycle(3600) is True
    assert _claim_s3_cleanup_cycle(3600) is False

    last = init_collection.find_one({"_id": S3_CLEANUP_STATE_ID})["last_run_at"]
    init_collection.update_one(
        {"_id": S3_CLEANUP_STATE_ID},
        {"$set": {"last_run_at": last - timedelta(seconds=3601)}},
    )
    assert _claim_s3_cleanup_cycle(3600) is True


@pytest.mark.asyncio
async def test_the_loop_waits_for_seeding_then_runs_unforced():
    order = MagicMock()
    order.wait = AsyncMock()
    order.cleanup = AsyncMock(return_value={"deleted_count": 0})
    sleep = AsyncMock(side_effect=[None, KeyboardInterrupt("stop the loop")])

    with (
        patch.object(cleanup_tasks, "_wait_for_reference_seeding", order.wait),
        patch.object(cleanup_tasks, "_claim_s3_cleanup_cycle", return_value=True),
        patch.object(cleanup_tasks, "cleanup_orphaned_s3_files", order.cleanup),
        patch.object(cleanup_tasks.asyncio, "sleep", sleep),
        pytest.raises(KeyboardInterrupt),
    ):
        await periodic_cleanup_orphaned_s3_files(interval_hours=1)

    assert order.mock_calls == [call.wait(), call.cleanup(dry_run=False)]


@pytest.mark.asyncio
async def test_a_cycle_another_worker_claimed_runs_nothing():
    cleanup = AsyncMock()
    with (
        patch.object(cleanup_tasks, "_wait_for_reference_seeding", AsyncMock()),
        patch.object(cleanup_tasks, "_claim_s3_cleanup_cycle", return_value=False),
        patch.object(cleanup_tasks, "cleanup_orphaned_s3_files", cleanup),
        patch.object(
            cleanup_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, KeyboardInterrupt("stop the loop")]),
        ),
        pytest.raises(KeyboardInterrupt),
    ):
        await periodic_cleanup_orphaned_s3_files(interval_hours=1)

    cleanup.assert_not_called()
