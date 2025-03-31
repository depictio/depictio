from typing import Optional, List

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging import logger
from depictio_models.s3_utils import S3_storage_checks
from depictio_models.models.s3 import MinIOS3Config
from depictio.api.v1.crypto import run_generate_keys
from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket


def run_initialization(
    checks: Optional[List[str]] = None, s3_config: Optional[MinIOS3Config] = None
):
    """
    Orchestrate system initialization in a logical order.

    Args:
        checks: Optional list of S3 checks to perform
        s3_config: Optional S3 configuration (defaults to internal config)
    """
    # Step 1: S3 Storage Accessibility Check (just storage, not bucket)
    logger.info("Starting system initialization...")

    # Use internal S3 config if not provided
    if s3_config is None:
        s3_config = MinIOS3Config(
            provider="minio",
            bucket=settings.minio.bucket,
            endpoint=f"{settings.minio.internal_endpoint}",
            port=settings.minio.port,
            minio_root_user=settings.minio.root_user,
            minio_root_password=settings.minio.root_password,
        )

    # Perform S3 storage accessibility check (without bucket check)
    logger.info("Checking S3 storage accessibility...")
    S3_storage_checks(s3_config, checks or ["s3"])

    # Step 2: Generate Keys (if not already generated)
    logger.info("Generating cryptographic keys...")
    run_generate_keys()

    # Step 3: Initialize Database (users, groups, agent config)
    logger.info("Initializing database...")
    admin_user, test_user = initialize_db()
    logger.info(f"Admin user created: {admin_user}")

    # Step 4: S3 Bucket Creation (optional, can be added if needed)
    logger.info("Creating S3 bucket...")
    create_bucket(admin_user)

    # This step could be implemented based on specific requirements
    logger.info("System initialization complete.")
