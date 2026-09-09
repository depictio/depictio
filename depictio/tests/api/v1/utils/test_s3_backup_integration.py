"""
Integration tests for S3 backup utilities using testcontainers.

This module provides real integration testing against a throwaway S3-compatible
container (SeaweedFS ``weed mini``, the same store bundled in docker-compose),
avoiding complex mocking and providing more realistic test scenarios.
"""

import os
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

# Check if testcontainers is available
try:
    from testcontainers.core.container import DockerContainer

    testcontainers_available = True
except ImportError:
    testcontainers_available = False

from depictio.api.v1.backup_strategy_manager import (
    S3BackupStrategyManager,
    create_backup_with_strategy,
)

# Keep in sync with the `minio` service image in docker-compose.yaml.
S3_TEST_IMAGE = os.environ.get("DEPICTIO_TEST_S3_IMAGE", "chrislusf/seaweedfs:4.46")
S3_TEST_ACCESS_KEY = "testkey"
S3_TEST_SECRET_KEY = "testsecret_12345"
S3_TEST_PORT = 8333


def _wait_http_ok(url: str, timeout: float = 90.0) -> None:
    """Poll ``url`` until it answers 2xx (SeaweedFS exposes ``/healthz`` on the S3 port)."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 - local test URL
                if 200 <= resp.status < 300:
                    return
        except (urllib.error.URLError, OSError, ValueError) as exc:  # container still booting
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"S3 test container never became healthy at {url}: {last_error}")


@pytest.mark.skipif(not testcontainers_available, reason="testcontainers not available")
class TestS3BackupIntegration:
    """Integration tests using a real S3-compatible container."""

    @pytest.fixture
    def s3_container(self):
        """Start a SeaweedFS ``weed mini`` container for testing."""
        container = (
            DockerContainer(S3_TEST_IMAGE)
            .with_env("AWS_ACCESS_KEY_ID", S3_TEST_ACCESS_KEY)
            .with_env("AWS_SECRET_ACCESS_KEY", S3_TEST_SECRET_KEY)
            .with_exposed_ports(S3_TEST_PORT)
            .with_command("mini -dir=/data -admin.ui=false -webdav=false")
        )
        with container:
            endpoint = (
                f"http://{container.get_container_host_ip()}:"
                f"{container.get_exposed_port(S3_TEST_PORT)}"
            )
            _wait_http_ok(f"{endpoint}/healthz")
            yield endpoint

    @pytest.fixture
    def s3_config(self, s3_container):
        """Create S3 config from the running container."""
        return {
            "endpoint_url": s3_container,
            "aws_access_key_id": S3_TEST_ACCESS_KEY,
            "aws_secret_access_key": S3_TEST_SECRET_KEY,
            "region_name": "us-east-1",
        }

    @pytest.fixture
    def s3_manager_with_real_s3(self, s3_config):
        """Create S3 backup manager backed by the real container."""
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
    async def test_real_s3_backup_success(self, s3_manager_with_real_s3):
        """Test successful backup with a real S3 container."""
        manager, source_client = s3_manager_with_real_s3

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
    async def test_real_s3_backup_dry_run(self, s3_manager_with_real_s3):
        """Test dry run with a real S3 container."""
        manager, source_client = s3_manager_with_real_s3

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
        """Test the create_backup_with_strategy function against the real container."""
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
            # Mock source S3 settings (attribute is still named `minio` for config compat)
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
            "testcontainers not available. Install with: pip install testcontainers "
            "for S3 backup integration testing against a real S3 container"
        )
