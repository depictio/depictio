from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

# from depictio.models.models.s3 import S3DepictioCLIConfig
from depictio.api.v1.configs.settings_models import S3DepictioCLIConfig
from depictio.api.v1.db_init import initialize_db
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _create_anonymous_user,
    _create_permanent_token,
)
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
        logger.debug(f"Using S3 config: {s3_config_input}")

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

    # Register initialization complete in the database
    from depictio.api.v1.db import initialization_collection

    init_data = {
        "initialization_complete": True,
        "admin_user_id": admin_user.id if admin_user else None,
        "s3_checks": checks,
        "s3_config": s3_config_input.model_dump_json(),
    }

    # Save initialization data to the database
    initialization_collection.insert_one(init_data)
    logger.info("Initialization data saved to the database.")
    logger.debug(f"Initialization data: {init_data}")

    if settings.auth.unauthenticated_mode:
        anon = await _create_anonymous_user()
        if anon:
            await _create_permanent_token(anon)
    logger.info("System initialization complete.")

    return init_data
