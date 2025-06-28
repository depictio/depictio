"""
Integration tests for S3 backup utilities using testcontainers.

This module provides real integration testing with MinIO containers,
avoiding complex mocking and providing more realistic test scenarios.
"""

from unittest.mock import patch

import pytest

# Check if testcontainers is available
try:
    from testcontainers.minio import MinioContainer

    testcontainers_available = True
except ImportError:
    testcontainers_available = False

from depictio.api.v1.backup_strategy_manager import (
    S3BackupStrategyManager,
    create_backup_with_strategy,
)


@pytest.mark.skipif(not testcontainers_available, reason="testcontainers not available")
class TestS3BackupIntegration:
    """Integration tests using real MinIO containers."""

    @pytest.fixture
    def minio_container(self):
        """Start MinIO container for testing."""
        with MinioContainer() as minio:
            yield minio

    @pytest.fixture
    def s3_config(self, minio_container):
        """Create S3 config from running MinIO container."""
        config = minio_container.get_config()
        return {
            "endpoint_url": f"http://{config['endpoint']}",
            "aws_access_key_id": config["access_key"],
            "aws_secret_access_key": config["secret_key"],
            "region_name": "us-east-1",
        }

    @pytest.fixture
    def s3_manager_with_real_minio(self, s3_config):
        """Create S3 backup manager with real MinIO container."""
        import boto3

        # Create source bucket and add test data
        source_client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint_url"],
            aws_access_key_id=s3_config["aws_access_key_id"],
            aws_secret_access_key=s3_config["aws_secret_access_key"],
            region_name=s3_config["region_name"],
        )

        # Create buckets
        source_client.create_bucket(Bucket="test-bucket")
        source_client.create_bucket(Bucket="backup-bucket")

        # Add test files to source bucket
        test_files = [
            ("data/project_123/deltatable_456/part-00000.parquet", b"parquet data content"),
            ("data/project_123/deltatable_456/_delta_log/00000.json", b'{"version": 0}'),
        ]

        for key, content in test_files:
            source_client.put_object(Bucket="test-bucket", Key=key, Body=content)

        # Mock settings for backup configuration
        backup_config = s3_config.copy()
        backup_config.pop("bucket", None)  # Remove bucket from client config

        with patch("depictio.api.v1.backup_strategy_manager.settings") as mock_settings:
            mock_settings.backup.backup_s3_config = backup_config
            mock_settings.backup.s3_backup_strategy = "s3_to_s3"
            mock_settings.backup.backup_s3_bucket = "backup-bucket"

            # Add bucket to source config for the manager
            source_config = s3_config.copy()
            source_config["bucket"] = "test-bucket"

            manager = S3BackupStrategyManager(source_s3_config=source_config)
            yield manager, source_client

    @pytest.mark.asyncio
    async def test_real_s3_backup_success(self, s3_manager_with_real_minio):
        """Test successful backup with real MinIO containers."""
        manager, source_client = s3_manager_with_real_minio

        deltatable_locations = ["data/project_123/deltatable_456/"]

        result = await manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=False
        )

        assert result["success"] is True
        assert result["locations_processed"] == 1
        assert result["total_files"] == 2
        assert result["total_bytes"] > 0
        assert len(result["backup_locations"]) == 1

        # Verify files were actually copied to backup bucket
        backup_client = manager.backup_s3_client
        backup_response = backup_client.list_objects_v2(
            Bucket="backup-bucket", Prefix="test_backup/"
        )

        backup_files = backup_response.get("Contents", [])
        assert len(backup_files) == 2

        # Check that the actual file content matches
        for backup_file in backup_files:
            backup_obj = backup_client.get_object(Bucket="backup-bucket", Key=backup_file["Key"])
            backup_content = backup_obj["Body"].read()
            assert len(backup_content) > 0

    @pytest.mark.asyncio
    async def test_real_s3_backup_dry_run(self, s3_manager_with_real_minio):
        """Test dry run with real MinIO containers."""
        manager, source_client = s3_manager_with_real_minio

        deltatable_locations = ["data/project_123/deltatable_456/"]

        result = await manager.backup_deltatable_data(
            deltatable_locations=deltatable_locations, backup_prefix="test_backup", dry_run=True
        )

        assert result["success"] is True
        assert result["locations_processed"] == 1
        assert result["total_files"] == 2
        assert result["total_bytes"] > 0

        # Verify no files were actually copied in dry run
        backup_client = manager.backup_s3_client
        backup_response = backup_client.list_objects_v2(
            Bucket="backup-bucket", Prefix="test_backup/"
        )

        backup_files = backup_response.get("Contents", [])
        assert len(backup_files) == 0  # No files should be copied in dry run

    @pytest.mark.asyncio
    async def test_real_create_backup_with_strategy(self, s3_config):
        """Test the create_backup_with_strategy function with real MinIO."""
        import boto3

        # Setup source bucket with test data
        source_client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint_url"],
            aws_access_key_id=s3_config["aws_access_key_id"],
            aws_secret_access_key=s3_config["aws_secret_access_key"],
            region_name=s3_config["region_name"],
        )

        source_client.create_bucket(Bucket="test-bucket")
        source_client.put_object(
            Bucket="test-bucket",
            Key="data/test_location/test.parquet",
            Body=b"test parquet content",
        )

        backup_config = s3_config.copy()

        with patch("depictio.api.v1.backup_strategy_manager.settings") as mock_settings:
            # Mock minio settings (source)
            mock_settings.minio.bucket = "test-bucket"
            mock_settings.minio.endpoint_url = s3_config["endpoint_url"]
            mock_settings.minio.aws_access_key_id = s3_config["aws_access_key_id"]
            mock_settings.minio.aws_secret_access_key = s3_config["aws_secret_access_key"]

            # Mock backup settings (destination)
            mock_settings.backup.backup_s3_config = backup_config
            mock_settings.backup.s3_backup_strategy = "s3_to_s3"
            mock_settings.backup.backup_s3_bucket = "backup-bucket"

            # Create backup bucket
            backup_client = boto3.client(
                "s3",
                endpoint_url=backup_config["endpoint_url"],
                aws_access_key_id=backup_config["aws_access_key_id"],
                aws_secret_access_key=backup_config["aws_secret_access_key"],
                region_name=backup_config["region_name"],
            )
            backup_client.create_bucket(Bucket="backup-bucket")

            result = await create_backup_with_strategy(
                deltatable_locations=["data/test_location/"],
                backup_prefix="integration_test",
                dry_run=False,
            )

            assert result["success"] is True
            assert result["locations_processed"] == 1
            assert result["total_files"] == 1
            assert result["strategy"] == "s3_to_s3"


# If testcontainers is not available, provide instructions
if not testcontainers_available:

    def test_testcontainers_installation_info():
        """Provide information about installing testcontainers for better testing."""
        # Type: ignore because pytest.skip is a valid function but type checker might not recognize it
        pytest.skip(  # type: ignore[misc]
            "testcontainers not available. Install with: pip install testcontainers[minio] "
            "for better S3 backup integration testing with real MinIO containers"
        )
