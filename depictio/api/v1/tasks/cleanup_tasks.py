"""
Cleanup tasks for Depictio application.

This module contains background tasks for cleaning up expired data.
"""

import asyncio

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _cleanup_expired_temporary_users,
    _purge_expired_tokens,
)
from depictio.api.v1.endpoints.utils_endpoints.core_functions import cleanup_orphaned_s3_files
from depictio.api.v1.services.analytics_service import AnalyticsService
from depictio.models.models.users import UserBeanie


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
    # Determine the interval in seconds
    if interval_seconds is not None:
        interval_in_seconds = interval_seconds
        interval_description = f"{interval_seconds} seconds"
    elif interval_minutes is not None:
        interval_in_seconds = interval_minutes * 60
        interval_description = f"{interval_minutes} minutes"
    elif interval_hours is not None:
        interval_in_seconds = interval_hours * 3600
        interval_description = f"{interval_hours} hours"
    else:
        # Default to 1 hour
        interval_in_seconds = 3600
        interval_description = "1 hour"

    logger.info(f"Starting periodic cleanup task (every {interval_description})")

    while True:
        try:
            logger.info("Running periodic cleanup of expired temporary users")

            # Run the cleanup
            cleanup_results = await _cleanup_expired_temporary_users()

            if cleanup_results["users_deleted"] > 0:
                logger.info(
                    f"Cleanup completed: deleted {cleanup_results['users_deleted']} users "
                    f"and {cleanup_results['tokens_deleted']} tokens"
                )
            else:
                logger.debug("No expired temporary users found to clean up")

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
    # Determine the interval in seconds
    if interval_seconds is not None:
        interval_in_seconds = interval_seconds
    elif interval_minutes is not None:
        interval_in_seconds = interval_minutes * 60
    elif interval_hours is not None:
        interval_in_seconds = interval_hours * 3600
    else:
        interval_in_seconds = 24 * 3600  # Default: 24 hours

    logger.info(f"Starting periodic analytics cleanup with interval: {interval_in_seconds} seconds")

    analytics_service = AnalyticsService(
        session_timeout_minutes=settings.analytics.session_timeout_minutes,
        cleanup_days=settings.analytics.cleanup_days,
    )

    while True:
        try:
            # Run the cleanup
            cleanup_results = await analytics_service.cleanup_old_sessions()

            if (
                cleanup_results["ended_sessions"] > 0
                or cleanup_results.get("deleted_sessions", 0) > 0
            ):
                logger.info(
                    f"Analytics cleanup completed: ended {cleanup_results['ended_sessions']} sessions, "
                    f"deleted {cleanup_results.get('deleted_sessions', 0)} old sessions, "
                    f"deleted {cleanup_results.get('deleted_activities', 0)} old activities"
                )
            else:
                logger.debug("No old analytics data found to clean up")

        except Exception as e:
            logger.error(f"Error during periodic analytics cleanup: {e}")

        # Wait for the next cleanup cycle
        await asyncio.sleep(interval_in_seconds)


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
    # Determine the interval in seconds
    if interval_seconds is not None:
        interval_in_seconds = interval_seconds
    elif interval_minutes is not None:
        interval_in_seconds = interval_minutes * 60
    elif interval_hours is not None:
        interval_in_seconds = interval_hours * 3600
    else:
        interval_in_seconds = 7 * 24 * 3600  # Default: 7 days

    logger.info(
        f"Starting periodic S3 cleanup with interval: {interval_in_seconds} seconds ({interval_in_seconds / 86400:.1f} days)"
    )

    while True:
        try:
            logger.info("Running periodic cleanup of orphaned S3 files")

            # Run the cleanup
            # Use force=True when mongodb.wipe is enabled (development/testing mode)
            # This allows cleanup when DB was intentionally wiped but S3 wasn't
            force_cleanup = settings.mongodb.wipe
            if force_cleanup:
                logger.info(
                    "MongoDB wipe mode enabled - forcing S3 cleanup even if all prefixes appear orphaned"
                )

            cleanup_results = await cleanup_orphaned_s3_files(dry_run=False, force=force_cleanup)

            if cleanup_results["deleted_count"] > 0:
                logger.info(
                    f"S3 cleanup completed: deleted {cleanup_results['deleted_count']} files/folders "
                    f"({cleanup_results['total_size_bytes'] / (1024**3):.2f} GB) "
                    f"from {cleanup_results['orphaned_prefixes_count']} orphaned data collections"
                )
            else:
                logger.debug("No orphaned S3 files found to clean up")

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
    # Determine the interval in seconds
    if interval_seconds is not None:
        interval_in_seconds = interval_seconds
        interval_description = f"{interval_seconds} seconds"
    elif interval_minutes is not None:
        interval_in_seconds = interval_minutes * 60
        interval_description = f"{interval_minutes} minutes"
    elif interval_hours is not None:
        interval_in_seconds = interval_hours * 3600
        interval_description = f"{interval_hours} hours"
    else:
        # Default to 1 hour (balances cleanup frequency vs system load)
        interval_in_seconds = 3600
        interval_description = "1 hour"

    logger.info(f"Starting periodic token purge task (every {interval_description})")

    while True:
        try:
            logger.info("Running periodic purge of expired tokens for all users")

            # Get all non-anonymous users (anonymous user has permanent token)
            users = await UserBeanie.find({"is_anonymous": {"$ne": True}}).to_list()

            total_tokens_deleted = 0

            # Purge expired tokens for each user
            for user in users:
                try:
                    result = await _purge_expired_tokens(user)
                    if result["deleted_count"] > 0:
                        total_tokens_deleted += result["deleted_count"]
                        logger.debug(
                            f"Purged {result['deleted_count']} expired tokens for user {user.email}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to purge tokens for user {user.email}: {e}")

            if total_tokens_deleted > 0:
                logger.info(
                    f"Token purge completed: deleted {total_tokens_deleted} expired tokens "
                    f"across {len(users)} users"
                )
            else:
                logger.debug("No expired tokens found to purge")

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
    logger.info("Starting cleanup tasks")

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

    logger.info("Cleanup tasks started")
