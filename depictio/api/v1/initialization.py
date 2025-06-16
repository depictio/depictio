from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.db import initialization_collection


def acquire_initialization_lock() -> bool:
    """Attempt to acquire an initialization lock.

    Returns ``True`` if the lock was acquired successfully, ``False`` otherwise.
    This relies on the uniqueness of the ``_id`` field in MongoDB.
    """

    try:
        initialization_collection.insert_one({"_id": "init_lock", "initialization_complete": False})
        return True
    except DuplicateKeyError:
        # Lock already acquired by another worker
        return False


def mark_initialization_complete(init_data: dict) -> None:
    """Mark initialization as complete in the database."""

    initialization_collection.update_one(
        {"_id": "init_lock"},
        {"$set": init_data},
        upsert=True,
    )


# from depictio.models.models.s3 import S3DepictioCLIConfig
from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket
from depictio.models.s3_utils import S3_storage_checks


async def run_initialization(
    checks: list[str] | None = None, s3_config_input: S3DepictioCLIConfig | None = None
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
    if s3_config_input is None:
        s3_config_input = settings.minio
        logger.info(f"Using S3 config: {s3_config_input}")

    # logger.info(f"OS Environment: {os.environ}")

    # Perform S3 storage accessibility check (without bucket check)
    logger.info("Checking S3 storage accessibility...")
    S3_storage_checks(s3_config_input, checks or ["s3"])

    # Step 2: Initialize Database (users, groups, agent config)
    logger.info("Initializing database...")

    # Get the admin user from the initialization process
    admin_user = await initialize_db(wipe=bool(settings.mongodb.wipe))

    if admin_user:
        logger.info(f"Admin user retrieved: {admin_user.email}")

        # Step 3: S3 Bucket Creation
        try:
            logger.info("Creating S3 bucket...")
            bucket_result = create_bucket(admin_user)
            logger.info(f"Bucket operation result: {bucket_result}")
        except Exception as e:
            logger.error(f"Error creating bucket: {str(e)}")
            # Continue initialization even if bucket creation fails
    else:
        logger.warning("No admin user available, skipping bucket creation")

    init_data = {
        "initialization_complete": True,
        "admin_user_id": admin_user.id if admin_user else None,
        "s3_checks": checks,
        "s3_config": s3_config_input.model_dump_json(),
    }

    logger.info("System initialization complete.")

    return init_data
