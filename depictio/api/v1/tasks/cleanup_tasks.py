"""
Cleanup tasks for Depictio application.

This module contains background tasks for cleaning up expired data.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import initialization_collection
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _cleanup_expired_temporary_users,
    _purge_expired_tokens,
)
from depictio.api.v1.endpoints.utils_endpoints.core_functions import cleanup_orphaned_s3_files
from depictio.api.v1.services.analytics_service import AnalyticsService
from depictio.models.models.users import UserBeanie

WORKER_ID = os.getpid()


def _calculate_interval(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
    default_seconds: int = 3600,
) -> tuple[int, str]:
    """
    Calculate interval in seconds with human-readable description.

    Args:
        interval_hours: Interval in hours
        interval_minutes: Interval in minutes
        interval_seconds: Interval in seconds
        default_seconds: Default interval if none specified

    Returns:
        Tuple of (interval_in_seconds, description)
    """
    if interval_seconds is not None:
        return interval_seconds, f"{interval_seconds} seconds"
    elif interval_minutes is not None:
        return interval_minutes * 60, f"{interval_minutes} minutes"
    elif interval_hours is not None:
        return interval_hours * 3600, f"{interval_hours} hours"
    else:
        return default_seconds, f"{default_seconds // 3600} hour(s)"


async def periodic_cleanup_expired_temporary_users(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
):
    """
    Periodically clean up expired temporary users.

    Args:
        interval_hours: How often to run cleanup (in hours)
        interval_minutes: How often to run cleanup (in minutes)
        interval_seconds: How often to run cleanup (in seconds)

    Note: Only one interval should be specified. If multiple are provided, precedence is:
          seconds > minutes > hours. If none are provided, defaults to 1 hour.
    """
    interval_in_seconds, interval_description = _calculate_interval(
        interval_hours, interval_minutes, interval_seconds, default_seconds=3600
    )

    while True:
        try:
            # Run the cleanup
            cleanup_results = await _cleanup_expired_temporary_users()

            if cleanup_results["users_deleted"] > 0:
                pass
            else:
                pass
        except Exception as e:
            logger.error(f"Error during periodic cleanup: {e}")

        # Wait for the next cleanup cycle
        await asyncio.sleep(interval_in_seconds)


async def periodic_cleanup_analytics_data(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
):
    """
    Periodically clean up old analytics data.

    Args:
        interval_hours: How often to run cleanup (in hours)
        interval_minutes: How often to run cleanup (in minutes)
        interval_seconds: How often to run cleanup (in seconds)

    Note: Only one interval should be specified. If multiple are provided, precedence is:
          seconds > minutes > hours. If none are provided, defaults to 24 hours.
    """
    interval_in_seconds, _ = _calculate_interval(
        interval_hours, interval_minutes, interval_seconds, default_seconds=24 * 3600
    )

    analytics_service = AnalyticsService(
        session_timeout_minutes=settings.analytics.session_timeout_minutes,
        cleanup_days=settings.analytics.cleanup_days,
    )

    while True:
        try:
            # Run the cleanup
            await analytics_service.cleanup_old_sessions()

        except Exception as e:
            logger.error(f"Error during periodic analytics cleanup: {e}")

        # Wait for the next cleanup cycle
        await asyncio.sleep(interval_in_seconds)


#: How often the S3 cleanup re-checks whether reference seeding is done, and how
#: long it waits for it at most.
_SEEDING_POLL_SECONDS = 10
_SEEDING_MAX_WAIT_SECONDS = 3600

#: ``initialization_collection`` document holding the last S3 cleanup run, which
#: is what lets one worker per cycle run it.
S3_CLEANUP_STATE_ID = "s3_orphan_cleanup_state"
_NEVER_RAN = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def _wait_for_reference_seeding() -> None:
    """Return once boot-time reference seeding has finished or failed.

    Seeding writes each table to S3 before registering it in MongoDB, so a cleanup
    pass that lands during seeding sees tables being created with no document yet
    and deletes them. ``process_all_reference_datasets`` sets one of two flags on
    the metadata document when it is done; with no document, nothing is seeded.

    Gives up after ``_SEEDING_MAX_WAIT_SECONDS``: a processing thread that died
    without setting either flag must not switch the cleanup off for good, and the
    age check in ``cleanup_orphaned_s3_files`` still keeps fresh tables.
    """
    waited = 0
    while waited < _SEEDING_MAX_WAIT_SECONDS:
        doc = initialization_collection.find_one(
            {"_id": "reference_datasets_metadata"},
            {"background_processing_complete": 1, "background_processing_failed": 1},
        )
        if (
            doc is None
            or doc.get("background_processing_complete")
            or doc.get("background_processing_failed")
        ):
            return
        await asyncio.sleep(_SEEDING_POLL_SECONDS)
        waited += _SEEDING_POLL_SECONDS
    logger.warning(
        f"S3 cleanup task: reference seeding still running after {_SEEDING_MAX_WAIT_SECONDS}s, "
        "starting anyway"
    )


def _claim_s3_cleanup_cycle(interval_seconds: int) -> bool:
    """Claim this cycle's S3 cleanup across every API worker.

    Each worker runs the loop, so without a claim a deployment with N workers runs
    N passes per interval. Same pattern as ``claim_auto_backup_slot``: the last run
    time lives in MongoDB and the claim is one conditional update, which only the
    first worker to find the cycle due can match.
    """
    now = datetime.now(timezone.utc)
    try:
        initialization_collection.update_one(
            {"_id": S3_CLEANUP_STATE_ID},
            {"$setOnInsert": {"last_run_at": _NEVER_RAN}},
            upsert=True,
        )
        claimed = initialization_collection.find_one_and_update(
            {
                "_id": S3_CLEANUP_STATE_ID,
                "last_run_at": {"$lte": now - timedelta(seconds=interval_seconds)},
            },
            {"$set": {"last_run_at": now, "worker_id": WORKER_ID}},
        )
    except Exception as exc:
        # Skipping a cycle is the safe failure: the next one retries.
        logger.warning(f"S3 cleanup task: could not claim this cycle: {exc}")
        return False
    return claimed is not None


async def periodic_cleanup_orphaned_s3_files(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
):
    """
    Periodically clean up orphaned S3 files from non-existent data collections.

    Args:
        interval_hours: How often to run cleanup (in hours)
        interval_minutes: How often to run cleanup (in minutes)
        interval_seconds: How often to run cleanup (in seconds)

    Note: Only one interval should be specified. If multiple are provided, precedence is:
          seconds > minutes > hours. If none are provided, defaults to 7 days.
    """
    interval_in_seconds, _ = _calculate_interval(
        interval_hours, interval_minutes, interval_seconds, default_seconds=7 * 24 * 3600
    )

    # Delay first run to allow workers to complete startup
    # Running cleanup immediately can block worker readiness and cause Gunicorn to kill workers
    logger.info("S3 cleanup task: Waiting 30s before first run to allow worker startup")
    await asyncio.sleep(30)
    await _wait_for_reference_seeding()

    while True:
        try:
            if _claim_s3_cleanup_cycle(interval_in_seconds):
                # Not forced, even under a MongoDB wipe: wipe_database already ran
                # the wipe-time pass before seeding, so from here on an "everything
                # looks orphaned" listing means something is wrong, and the safety
                # check should stop it.
                await cleanup_orphaned_s3_files(dry_run=False)
        except Exception as e:
            logger.error(f"Error during periodic S3 cleanup: {e}")

        # Wait for the next cleanup cycle
        await asyncio.sleep(interval_in_seconds)


async def periodic_purge_expired_tokens(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
):
    """
    Periodically purge expired tokens for all users.

    This task was moved from Dash frontend (app_layout.py) to improve performance.
    Instead of purging on every page load (30-50ms overhead), tokens are now
    cleaned up hourly in the background.

    Args:
        interval_hours: How often to run token purge (in hours)
        interval_minutes: How often to run token purge (in minutes)
        interval_seconds: How often to run token purge (in seconds)

    Note: Only one interval should be specified. If multiple are provided, precedence is:
          seconds > minutes > hours. If none are provided, defaults to 1 hour.
    """
    interval_in_seconds, interval_description = _calculate_interval(
        interval_hours, interval_minutes, interval_seconds, default_seconds=3600
    )

    while True:
        try:
            # Get all non-anonymous users (anonymous user has permanent token)
            users = await UserBeanie.find({"is_anonymous": {"$ne": True}}).to_list()

            total_tokens_deleted = 0

            # Purge expired tokens for each user
            for user in users:
                try:
                    result = await _purge_expired_tokens(user)
                    if result["deleted_count"] > 0:
                        total_tokens_deleted += result["deleted_count"]
                except Exception as e:
                    logger.warning(f"Failed to purge tokens for user {user.email}: {e}")

            if total_tokens_deleted > 0:
                pass
            else:
                pass
        except Exception as e:
            logger.error(f"Error during periodic token purge: {e}")

        # Wait for the next cleanup cycle
        await asyncio.sleep(interval_in_seconds)


def start_cleanup_tasks(
    interval_hours: int | None = None,
    interval_minutes: int | None = None,
    interval_seconds: int | None = None,
):
    """
    Start background cleanup tasks.

    Args:
        interval_hours: How often to run cleanup (in hours)
        interval_minutes: How often to run cleanup (in minutes)
        interval_seconds: How often to run cleanup (in seconds)

    Note: Only one interval should be specified. If multiple are provided, precedence is:
          seconds > minutes > hours. If none are provided, defaults to 1 hour.

    This function should be called during application startup.
    """

    # Start the periodic cleanup task in the background
    asyncio.create_task(
        periodic_cleanup_expired_temporary_users(
            interval_hours=interval_hours,
            interval_minutes=interval_minutes,
            interval_seconds=interval_seconds,
        )
    )

    # Start analytics cleanup if enabled
    if settings.analytics.enabled and settings.analytics.cleanup_enabled:
        asyncio.create_task(
            periodic_cleanup_analytics_data(
                interval_hours=24,  # Run analytics cleanup daily
            )
        )

    # Start S3 orphaned files cleanup
    asyncio.create_task(
        periodic_cleanup_orphaned_s3_files(
            interval_hours=1,  # Run S3 cleanup hourly
        )
    )

    # Start periodic token purge (moved from Dash frontend for performance)
    asyncio.create_task(
        periodic_purge_expired_tokens(
            interval_hours=1,  # Run token purge hourly
        )
    )
