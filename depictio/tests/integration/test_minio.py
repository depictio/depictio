import os

import boto3
import pytest
from testcontainers.minio import MinioContainer

from depictio.models.models.s3 import S3DepictioCLIConfig
from depictio.models.s3_utils import MinIOManager, S3_storage_checks

# ensure Docker socket is set (you already have this in your env or .env file)
os.environ.setdefault("DOCKER_HOST", "unix:///Users/tweber/.docker/run/docker.sock")


@pytest.fixture(scope="session")
def minio_server():
    """Start a throwaway MinIO server in Docker for the entire test session."""
    container = (
        MinioContainer("minio/minio:latest", access_key="minio", secret_key="minio123")
        # explicitly expose the container port so we can read it back
        .with_exposed_ports(9000)
    )
    container.start()
    yield container
    container.stop()


@pytest.fixture
def minio_config(minio_server):
    """Create a S3DepictioCLIConfig for the running MinIO container."""
    cfg = minio_server.get_config()
    # cfg["endpoint"] comes back as "localhost:XXXXX"
    host, port = cfg["endpoint"].split(":")
    endpoint_url = f"http://{host}:{port}"

    return S3DepictioCLIConfig(
        service_name="minio",
        endpoint_url=endpoint_url,
        root_user=cfg["access_key"],
        root_password=cfg["secret_key"],
        bucket="depictio-bucket",
        on_premise_service=False,
    )


@pytest.fixture
def create_test_bucket(minio_config):
    """Create a test bucket in the MinIO container."""
    s3 = boto3.client(
        "s3",
        endpoint_url=minio_config.endpoint_url,
        aws_access_key_id=minio_config.root_user,
        aws_secret_access_key=minio_config.root_password,
    )
    try:
        s3.head_bucket(Bucket=minio_config.bucket)
    except s3.exceptions.NoSuchBucket:
        s3.create_bucket(Bucket=minio_config.bucket)
    yield
    # cleanup omitted for brevity


@pytest.mark.docker
class TestMinIOManagerWithRealServer:
    def test_init(self, minio_server):
        print("MinIO server config:", minio_server.get_config())

    def test_minio_manager_initialization(self, minio_config):
        manager = MinIOManager(minio_config)
        assert manager.endpoint_url == minio_config.endpoint_url
        assert manager.bucket_name == minio_config.bucket
        assert manager.access_key == minio_config.root_user
        assert manager.secret_key == minio_config.root_password
        assert manager.s3_client is not None

    def test_s3_accessibility(self, minio_config):
        """Test that the MinIOManager can access the S3 API."""
        manager = MinIOManager(minio_config)
        assert manager.check_s3_accessibility() is True

    def test_bucket_creation_and_access(self, minio_config, create_test_bucket):
        """Test that the bucket can be created and accessed."""
        manager = MinIOManager(minio_config)
        assert manager.check_bucket_accessibility() is True

    def test_write_policy(self, minio_config, create_test_bucket):
        """Test that write operations are possible in the bucket."""
        manager = MinIOManager(minio_config)
        assert manager.check_write_policy() is True

    def test_suggest_adjustments(self, minio_config, create_test_bucket):
        """Test that no adjustments are suggested when everything is working."""
        manager = MinIOManager(minio_config)
        # This should not raise an exception
        manager.suggest_adjustments()

    def test_s3_storage_checks_function(self, minio_config, create_test_bucket):
        """Test the S3_storage_checks function."""
        # This should not raise an exception
        S3_storage_checks(minio_config)

    def test_write_and_read_object(self, minio_config, create_test_bucket):
        """Test writing an object to the bucket and reading it back."""
        manager = MinIOManager(minio_config)

        # Test data
        test_key = "test/path/test_file.txt"
        test_content = "This is a test file content"

        # Write the object
        manager.s3_client.put_object(Bucket=manager.bucket_name, Key=test_key, Body=test_content)

        # Read it back
        response = manager.s3_client.get_object(Bucket=manager.bucket_name, Key=test_key)

        content = response["Body"].read().decode("utf-8")
        assert content == test_content

        # Clean up
        manager.s3_client.delete_object(Bucket=manager.bucket_name, Key=test_key)

    def test_with_nonexistent_bucket(self, minio_config):
        """Test behavior with a nonexistent bucket."""
        # Create config with nonexistent bucket
        bad_config = S3DepictioCLIConfig(
            service_name=minio_config.service_name,
            endpoint_url=minio_config.endpoint_url,
            root_user=minio_config.root_user,
            root_password=minio_config.root_password,
            bucket="nonexistent-bucket",
            on_premise_service=False,
        )

        manager = MinIOManager(bad_config)

        # S3 should be accessible
        assert manager.check_s3_accessibility() is True

        # But the bucket should not be
        assert manager.check_bucket_accessibility() is False

        # And write policy check should fail
        assert manager.check_write_policy() is False

        # suggest_adjustments should raise an exception
        with pytest.raises(Exception, match="S3 storage is not correctly configured"):
            manager.suggest_adjustments()

    def test_with_bad_credentials(self, minio_config):
        """Test behavior with incorrect credentials."""
        # Create config with bad credentials
        bad_config = S3DepictioCLIConfig(
            service_name=minio_config.service_name,
            endpoint_url=minio_config.endpoint_url,
            root_user="wrong_user",
            root_password="wrong_password",
            bucket=minio_config.bucket,
            on_premise_service=False,
        )

        manager = MinIOManager(bad_config)

        # S3 should not be accessible with bad credentials
        assert manager.check_s3_accessibility() is False

        # And suggest_adjustments should raise an exception
        with pytest.raises(Exception, match="S3 storage is not correctly configured"):
            manager.suggest_adjustments()
