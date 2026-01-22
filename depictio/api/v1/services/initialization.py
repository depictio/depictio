"""
Application initialization management.

Handles worker coordination for initialization tasks in multi-worker deployments.
"""

import asyncio
import os
import time
from datetime import datetime, timezone

import pymongo

from depictio.api.v1.configs.logging_init import logger

WORKER_ID = os.getpid()


async def check_and_set_initialization() -> bool:
    """
    Atomically check if initialization is needed and mark it as in-progress.

    Returns:
        True if this worker should perform initialization, False otherwise
    """
    from depictio.api.v1.db import initialization_collection

    try:
        # Check if initialization is already complete
        if initialization_collection.find_one({"initialization_complete": True}):
            return False

        # Try to insert an initialization document atomically
        # This will only succeed for the first worker that tries
        initialization_collection.insert_one(
            {
                "_id": "init_lock",
                "initialization_complete": False,
                "initialization_in_progress": True,
                "worker_id": WORKER_ID,
                "started_at": datetime.now(timezone.utc),
            }
        )
        logger.info(f"Worker {WORKER_ID}: Acquired initialization lock")
        return True

    except pymongo.errors.DuplicateKeyError:  # type: ignore[unresolved-attribute]
        logger.info(f"Worker {WORKER_ID}: Another worker is handling initialization")
        return False

    except Exception as e:
        logger.error(f"Worker {WORKER_ID}: Error checking initialization: {e}")
        # Fallback: check if initialization was already completed
        existing = initialization_collection.find_one({"initialization_complete": True})
        return existing is None


async def mark_initialization_complete() -> bool:
    """
    Mark initialization as complete atomically.

    Returns:
        True if the update was successful, False otherwise
    """
    from depictio.api.v1.db import initialization_collection

    result = initialization_collection.update_one(
        {"_id": "init_lock", "initialization_in_progress": True},
        {
            "$set": {
                "initialization_complete": True,
                "initialization_in_progress": False,
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )
    logger.info(f"Worker {WORKER_ID}: Marked initialization as complete")
    return result.modified_count > 0


async def cleanup_failed_initialization() -> None:
    """Clean up initialization lock if initialization fails."""
    from depictio.api.v1.db import initialization_collection

    initialization_collection.delete_one({"_id": "init_lock", "initialization_in_progress": True})
    logger.info(f"Worker {WORKER_ID}: Cleaned up failed initialization lock")


async def wait_for_initialization_complete(timeout: int = 300) -> bool:
    """
    Wait for another worker to complete initialization.

    Args:
        timeout: Maximum time to wait in seconds (default: 300)

    Returns:
        True if initialization completed within timeout

    Raises:
        TimeoutError: If initialization did not complete within timeout period
    """
    from depictio.api.v1.db import initialization_collection

    logger.info(f"Worker {WORKER_ID}: Waiting for initialization to complete...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        if initialization_collection.find_one({"initialization_complete": True}):
            logger.info(f"Worker {WORKER_ID}: Initialization completed by another worker")
            return True
        await asyncio.sleep(1)

    raise TimeoutError("Initialization did not complete within timeout period")
