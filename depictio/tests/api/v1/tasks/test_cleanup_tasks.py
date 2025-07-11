import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from depictio.api.v1.tasks.cleanup_tasks import (
    periodic_cleanup_expired_temporary_users,
    start_cleanup_tasks,
)

# ------------------------------------------------------
# Test periodic_cleanup_expired_temporary_users function
# ------------------------------------------------------


class TestPeriodicCleanupExpiredTemporaryUsers:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock the cleanup function
        self.cleanup_patcher = patch(
            "depictio.api.v1.tasks.cleanup_tasks._cleanup_expired_temporary_users",
            new_callable=AsyncMock,
        )
        self.mock_cleanup = self.cleanup_patcher.start()

        # Mock asyncio.sleep to avoid actual waiting
        self.sleep_patcher = patch("depictio.api.v1.tasks.cleanup_tasks.asyncio.sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.cleanup_patcher.stop()
        self.sleep_patcher.stop()

    @pytest.mark.asyncio
    async def test_periodic_cleanup_successful_run(self):
        """Test successful cleanup execution with users deleted."""
        # Arrange
        self.mock_cleanup.return_value = {
            "expired_users_found": 2,
            "users_deleted": 2,
            "tokens_deleted": 3,
            "errors": [],
        }

        # Make sleep raise exception to break the infinite loop after first iteration
        self.mock_sleep.side_effect = KeyboardInterrupt("Test interrupt")

        # Act & Assert
        with pytest.raises(KeyboardInterrupt):
            await periodic_cleanup_expired_temporary_users(interval_hours=2)

        # Verify cleanup was called
        self.mock_cleanup.assert_called_once()
        # Verify sleep was called with correct interval (2 hours = 7200 seconds)
        self.mock_sleep.assert_called_once_with(7200)

    @pytest.mark.asyncio
    async def test_periodic_cleanup_no_users_found(self):
        """Test cleanup execution when no expired users are found."""
        # Arrange
        self.mock_cleanup.return_value = {
            "expired_users_found": 0,
            "users_deleted": 0,
            "tokens_deleted": 0,
            "errors": [],
        }

        # Make sleep raise exception to break the infinite loop after first iteration
        self.mock_sleep.side_effect = KeyboardInterrupt("Test interrupt")

        # Act & Assert
        with pytest.raises(KeyboardInterrupt):
            await periodic_cleanup_expired_temporary_users(interval_hours=1)

        # Verify cleanup was called
        self.mock_cleanup.assert_called_once()
        # Verify sleep was called with default interval (1 hour = 3600 seconds)
        self.mock_sleep.assert_called_once_with(3600)

    @pytest.mark.asyncio
    async def test_periodic_cleanup_handles_exception(self):
        """Test that cleanup task continues running even when cleanup function fails."""
        # Arrange
        self.mock_cleanup.side_effect = Exception("Database connection error")

        # Make sleep raise exception to break the infinite loop after first iteration
        self.mock_sleep.side_effect = KeyboardInterrupt("Test interrupt")

        # Act & Assert - Should not raise the cleanup exception
        with pytest.raises(KeyboardInterrupt):
            await periodic_cleanup_expired_temporary_users(interval_hours=1)

        # Verify cleanup was attempted
        self.mock_cleanup.assert_called_once()
        # Verify sleep was still called (task continues despite error)
        self.mock_sleep.assert_called_once_with(3600)


# ------------------------------------------------------
# Test start_cleanup_tasks function
# ------------------------------------------------------


class TestStartCleanupTasks:
    def setup_method(self):
        """Set up test fixtures."""
        # Mock asyncio.create_task
        self.create_task_patcher = patch("depictio.api.v1.tasks.cleanup_tasks.asyncio.create_task")
        self.mock_create_task = self.create_task_patcher.start()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.create_task_patcher.stop()

    def test_start_cleanup_tasks_creates_background_task(self):
        """Test that start_cleanup_tasks creates a background task."""
        # Act
        start_cleanup_tasks()

        # Assert
        self.mock_create_task.assert_called_once()
        # Verify the task is created with the correct function call
        call_args = self.mock_create_task.call_args[0][0]
        # Should be a coroutine for periodic_cleanup_expired_temporary_users
        assert asyncio.iscoroutine(call_args)

    def test_start_cleanup_tasks_uses_default_interval(self):
        """Test that start_cleanup_tasks uses the default 1-hour interval."""
        # Mock the periodic function to capture its arguments
        with patch(
            "depictio.api.v1.tasks.cleanup_tasks.periodic_cleanup_expired_temporary_users"
        ) as mock_periodic:
            # Act
            start_cleanup_tasks()

            # Assert
            mock_periodic.assert_called_once_with(interval_hours=1)

    def test_start_cleanup_tasks_logging(self):
        """Test that start_cleanup_tasks logs appropriate messages."""
        # Mock the logger
        with patch("depictio.api.v1.tasks.cleanup_tasks.logger") as mock_logger:
            # Act
            start_cleanup_tasks()

            # Assert
            # Should log start and completion messages
            assert mock_logger.info.call_count == 2
            mock_logger.info.assert_any_call("Starting cleanup tasks")
            mock_logger.info.assert_any_call("Cleanup tasks started")
