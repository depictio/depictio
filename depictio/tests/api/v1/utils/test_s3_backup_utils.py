"""
Unit tests for S3 backup utilities.

Tests the S3BackupStrategyManager and related functions for backing up
S3 deltatable data using different strategies.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from depictio.api.v1.backup_strategy_manager import (
    S3BackupStrategyManager,
    create_backup_with_strategy,
)


class TestS3BackupStrategyManager:
    """Test S3BackupStrategyManager functionality."""

    @pytest.fixture
    def mock_s3_config(self):
        """Mock S3 configuration."""
        return {
            "endpoint_url": "http://localhost:9000",
            "aws_access_key_id": "test_access_key",
            "aws_secret_access_key": "test_secret_key",
            "bucket": "test-bucket",
            "region_name": "us-east-1",
        }

    @pytest.fixture
    def s3_manager(self, mock_s3_config):
        """Create S3BackupStrategyManager instance with mocked clients."""
        with patch("depictio.api.v1.backup_strategy_manager.boto3.client") as mock_boto3:
            mock_source_client = Mock()
            mock_backup_client = Mock()

            # Mock the list_buckets response for backup client
            mock_backup_client.list_buckets.return_value = {
                "Buckets": [{"Name": "test-backup-bucket"}]
            }

            # Return different clients for source and backup
            def client_side_effect(*args, **kwargs):
                if "play.minio.io" in kwargs.get("endpoint_url", ""):
                    return mock_backup_client
                else:
                    return mock_source_client

            mock_boto3.side_effect = client_side_effect

            with patch("depictio.api.v1.backup_strategy_manager.settings") as mock_settings:
                mock_settings.backup.backup_s3_config = mock_s3_config
                mock_settings.backup.s3_backup_strategy = "s3_to_s3"
                mock_settings.backup.backup_s3_bucket = "test-backup-bucket"

                manager = S3BackupStrategyManager(source_s3_config=mock_s3_config)
                manager.source_client = mock_source_client
                manager.backup_s3_client = mock_backup_client

                return manager

    @pytest.mark.asyncio
    async def test_backup_deltatable_data_success(self, s3_manager):
        """Test successful backup of deltatable data."""
        # Mock S3 responses
        s3_manager.source_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "data/project_123/deltatable_456/part-00000.parquet", "Size": 1024},
                {"Key": "data/project_123/deltatable_456/_delta_log/00000.json", "Size": 256},
            ]
        }

        # Mock get_object response for downloading files
        mock_body = Mock()
        mock_body.read.return_value = b"fake file content"
        s3_manager.source_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/octet-stream",
        }

        deltatable_locations = ["data/project_123/deltatable_456/"]

        result = await s3_manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=False
        )

        assert result["success"] is True
        assert result["locations_processed"] == 1
        assert result["total_files"] == 2
        assert result["total_bytes"] == 1280
        assert len(result["backup_locations"]) == 1

        # Verify put_object was called for each file (cross-service copy)
        assert s3_manager.backup_s3_client.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_backup_deltatable_data_dry_run(self, s3_manager):
        """Test dry run backup of deltatable data."""
        s3_manager.source_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "data/project_123/deltatable_456/part-00000.parquet", "Size": 1024},
                {"Key": "data/project_123/deltatable_456/_delta_log/00000.json", "Size": 256},
            ]
        }

        # Mock get_object response (not used in dry run but needed for consistency)
        mock_body = Mock()
        mock_body.read.return_value = b"fake file content"
        s3_manager.source_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/octet-stream",
        }

        deltatable_locations = ["data/project_123/deltatable_456/"]

        result = await s3_manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=True
        )

        assert result["success"] is True
        assert result["locations_processed"] == 1
        assert result["total_files"] == 2
        assert result["total_bytes"] == 1280

        # Verify put_object was NOT called in dry run
        s3_manager.backup_s3_client.put_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_deltatable_data_empty_location(self, s3_manager):
        """Test backup with empty deltatable location."""
        s3_manager.source_client.list_objects_v2.return_value = {}

        # Mock get_object response (not used but needed for consistency)
        mock_body = Mock()
        mock_body.read.return_value = b"fake file content"
        s3_manager.source_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/octet-stream",
        }

        deltatable_locations = ["data/empty_location/"]

        result = await s3_manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=False
        )

        assert result["success"] is True
        assert result["locations_processed"] == 0  # No files = location not processed
        assert result["total_files"] == 0
        assert result["total_bytes"] == 0

    @pytest.mark.asyncio
    async def test_backup_deltatable_data_s3_error(self, s3_manager):
        """Test backup with S3 error."""
        from botocore.exceptions import ClientError

        # Type ignore because we're mocking and don't need the exact type structure
        error_response: Any = {
            "Error": {"Code": "NoSuchBucket", "Message": "Bucket does not exist"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }
        s3_manager.source_client.list_objects_v2.side_effect = ClientError(
            error_response,  # type: ignore[arg-type]
            "ListObjectsV2",
        )

        # Mock get_object response (not used but needed for consistency)
        mock_body = Mock()
        mock_body.read.return_value = b"fake file content"
        s3_manager.source_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/octet-stream",
        }

        deltatable_locations = ["data/project_123/deltatable_456/"]

        result = await s3_manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=False
        )

        assert result["success"] is False
        assert result["locations_processed"] == 0
        assert len(result["errors"]) > 0
        assert "NoSuchBucket" in str(result["errors"][0])


class TestCreateBackupWithStrategy:
    """Test create_backup_with_strategy function."""

    @pytest.mark.asyncio
    async def test_create_backup_with_strategy_success(self):
        """Test successful backup using strategy function."""
        deltatable_locations = ["data/project_123/deltatable_456/"]

        mock_result = {
            "strategy": "s3_to_s3",
            "backup_timestamp": "20240101_120000",
            "locations_processed": 1,
            "total_files": 2,
            "total_bytes": 1280,
            "success": True,
            "errors": [],
            "backup_locations": {
                "data/project_123/deltatable_456/": "s3://backup-bucket/test_backup/20240101_120000/data/project_123/deltatable_456/"
            },
        }

        with patch(
            "depictio.api.v1.backup_strategy_manager.S3BackupStrategyManager"
        ) as mock_manager_class:
            mock_manager = Mock()
            mock_manager.backup_deltatable_data = AsyncMock(return_value=mock_result)
            mock_manager_class.return_value = mock_manager

            with patch("depictio.api.v1.backup_strategy_manager.settings") as mock_settings:
                mock_settings.minio.bucket = "test-bucket"
                mock_settings.minio.endpoint_url = "http://localhost:9000"
                mock_settings.minio.aws_access_key_id = "test_key"
                mock_settings.minio.aws_secret_access_key = "test_secret"
                mock_settings.backup.s3_backup_strategy = "s3_to_s3"

                result = await create_backup_with_strategy(
                    deltatable_locations=deltatable_locations,
                    backup_prefix="test_backup",
                    dry_run=False,
                )

        assert result["success"] is True
        assert result["locations_processed"] == 1
        assert result["total_files"] == 2
        assert result["strategy"] == "s3_to_s3"
