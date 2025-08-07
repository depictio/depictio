"""
Cleanup tasks for Depictio application.

This module contains background tasks for cleaning up expired data.
"""

import asyncio

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _cleanup_expired_temporary_users


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

    logger.info("Cleanup tasks started")
