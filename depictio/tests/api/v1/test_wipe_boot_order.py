"""Under a wipe, no worker starts Beanie before the database is dropped.

Beanie creates its indexes as it initialises. Every worker used to start it
first and only then race for the init lock, so the winner's ``drop_database``
landed while a sibling was still creating indexes: on EMBL dev that worker
failed with DatabaseDropPending and hung instead of exiting, and any index
created before the drop was lost with it.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import mongomock
import pytest

from depictio.api.v1 import db_init
from depictio.api.v1.services import lifespan
from depictio.api.v1.services.lifespan import handle_initialization

_STEPS = (
    "check_and_set_initialization",
    "wait_for_initialization_complete",
    "wipe_database",
    "init_pymongo_beanie",
    "run_initialization",
    "mark_initialization_complete",
    "clean_screenshots",
    "cleanup_failed_initialization",
)


@pytest.fixture
def boot():
    """The startup steps of ``handle_initialization``, recorded in call order."""
    steps = MagicMock()
    for name in _STEPS:
        setattr(steps, name, AsyncMock())
    steps.init_pymongo_beanie.return_value = "client"

    settings = MagicMock()
    with patch.multiple(lifespan, settings=settings, **{n: getattr(steps, n) for n in _STEPS}):
        yield steps, settings


def _order(steps: MagicMock) -> list[str]:
    return [name for name, _, _ in steps.mock_calls]


@pytest.mark.asyncio
async def test_the_initializer_wipes_before_beanie_creates_indexes(boot):
    steps, settings = boot
    settings.mongodb.wipe = True
    steps.check_and_set_initialization.return_value = True

    assert await handle_initialization() == (True, "client")
    assert _order(steps) == [
        "check_and_set_initialization",
        "wipe_database",
        "init_pymongo_beanie",
        "run_initialization",
        "mark_initialization_complete",
        "clean_screenshots",
    ]


@pytest.mark.asyncio
async def test_other_workers_start_beanie_once_initialization_is_done(boot):
    steps, settings = boot
    settings.mongodb.wipe = True
    steps.check_and_set_initialization.return_value = False

    assert await handle_initialization() == (False, "client")
    assert _order(steps) == [
        "check_and_set_initialization",
        "wait_for_initialization_complete",
        "init_pymongo_beanie",
    ]


@pytest.mark.asyncio
async def test_nothing_is_wiped_without_the_setting(boot):
    steps, settings = boot
    settings.mongodb.wipe = False
    steps.check_and_set_initialization.return_value = True

    await handle_initialization()
    steps.wipe_database.assert_not_called()
    assert _order(steps)[:3] == [
        "check_and_set_initialization",
        "init_pymongo_beanie",
        "run_initialization",
    ]


@pytest.mark.asyncio
async def test_a_failed_wipe_releases_the_lock(boot):
    steps, settings = boot
    settings.mongodb.wipe = True
    steps.check_and_set_initialization.return_value = True
    steps.wipe_database.side_effect = RuntimeError("mongo gone")

    with pytest.raises(RuntimeError):
        await handle_initialization()
    steps.init_pymongo_beanie.assert_not_called()
    steps.cleanup_failed_initialization.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failed_beanie_start_releases_the_lock(boot):
    """The lock is now held across Beanie's start, so its failure must free it."""
    steps, settings = boot
    settings.mongodb.wipe = False
    steps.check_and_set_initialization.return_value = True
    steps.init_pymongo_beanie.side_effect = RuntimeError("index build failed")

    with pytest.raises(RuntimeError):
        await handle_initialization()
    steps.cleanup_failed_initialization.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_init_lock_is_held_throughout_the_wipe():
    """Dropping the database and restoring the lock let a sibling take it in between."""
    db = mongomock.MongoClient().db
    db.initialization.insert_one({"_id": "init_lock", "worker_id": 70})
    db.initialization.insert_one({"_id": "reference_datasets_metadata"})
    db.users.insert_one({"email": "someone@example.com"})
    db.magic_link_tickets.create_index("ticket", unique=True)
    cleanup = AsyncMock(return_value={"deleted_count": 0})

    drop_collection = db.drop_collection

    def drop_while_checking_the_lock(name):
        assert db.initialization.find_one({"_id": "init_lock"}), f"lock gone while dropping {name}"
        drop_collection(name)

    with (
        patch("depictio.api.v1.db.db", db),
        patch("depictio.api.v1.db.initialization_collection", db.initialization),
        patch.object(db, "drop_collection", drop_while_checking_the_lock),
        patch.object(db_init, "_ensure_mongodb_connection"),
        patch(
            "depictio.api.v1.endpoints.utils_endpoints.core_functions.cleanup_orphaned_s3_files",
            cleanup,
        ),
    ):
        await db_init.wipe_database()

    assert db.list_collection_names() == ["initialization"]
    assert list(db.initialization.find()) == [{"_id": "init_lock", "worker_id": 70}]
    assert cleanup.mock_calls == [call(dry_run=False, force=True, min_age_seconds=0)]
