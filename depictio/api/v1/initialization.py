"""
System initialization module for Depictio API.

Handles the orchestration of startup tasks including S3 storage checks,
database initialization, and bucket creation.
"""

from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
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
) -> dict[str, Any]:
    """
    Orchestrate system initialization in a logical order.

    Performs the following steps:
    1. S3 storage accessibility check
    2. Database initialization (users, groups, agent config)
    3. S3 bucket creation
    4. Anonymous user setup (if unauthenticated mode is enabled)

    Args:
        checks: Optional list of S3 checks to perform.
        s3_config_input: Optional S3 configuration (defaults to internal config).

    Returns:
        Dictionary containing initialization status and configuration.
    """
    logger.info("Starting system initialization...")

    if s3_config_input is None:
        s3_config_input = settings.minio

    S3_storage_checks(s3_config_input, checks or ["s3"])

    admin_user = await initialize_db(wipe=bool(settings.mongodb.wipe))

    if admin_user:
        logger.info(f"Admin user retrieved: {admin_user.email}")
        try:
            create_bucket(admin_user)
        except Exception as e:
            logger.error(f"Error creating bucket: {e}")
    else:
        logger.warning("No admin user available, skipping bucket creation")

    from depictio.api.v1.db import initialization_collection

    init_data: dict[str, Any] = {
        "initialization_complete": True,
        "admin_user_id": admin_user.id if admin_user else None,
        "s3_checks": checks,
        "s3_config": s3_config_input.model_dump_json(),
    }

    initialization_collection.insert_one(init_data)

    if settings.auth.unauthenticated_mode:
        anon = await _create_anonymous_user()
        if anon:
            await _create_permanent_token(anon)

    logger.info("System initialization complete.")
    return init_data
