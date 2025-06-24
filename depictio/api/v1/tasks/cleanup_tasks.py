"""
Cleanup tasks for Depictio application.

This module contains background tasks for cleaning up expired data.
"""

import asyncio

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import _cleanup_expired_temporary_users


async def periodic_cleanup_expired_temporary_users(interval_hours: int = 1):
    """
    Periodically clean up expired temporary users.

    Args:
        interval_hours: How often to run cleanup (in hours)
    """
    logger.info(f"Starting periodic cleanup task (every {interval_hours} hours)")

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
        await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds


def start_cleanup_tasks():
    """
    Start background cleanup tasks.

    This function should be called during application startup.
    """
    logger.info("Starting cleanup tasks")

    # Start the periodic cleanup task in the background
    asyncio.create_task(periodic_cleanup_expired_temporary_users(interval_hours=1))

    logger.info("Cleanup tasks started")
