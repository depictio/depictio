from datetime import datetime
import logging
from typing import Dict, Any, Optional
from pydantic import validate_call, EmailStr
from fastapi import HTTPException

from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.endpoints.user_endpoints.utils import (
    hash_password,
    get_users_group,
)

from depictio_models.models.users import User, UserBeanie
from depictio_models.utils import convert_model_to_dict
from depictio_models.models.base import PyObjectId


@validate_call(validate_return=True)
async def create_user_in_db(
    email: EmailStr, password: str, group: Optional[str] = None, is_admin: bool = False
) -> Optional[UserBeanie]:
    """
    Helper function to create a user in the database using Beanie.

    Args:
        email: User's email address
        password: Raw password (will be hashed)
        group: User's group (optional)
        is_admin: Whether user is admin

    Returns:
        The created UserBeanie object if successful
    """
    logger.info(f"Creating user with email: {email}")

    # Check if the user already exists
    existing_user = await UserBeanie.find_one({"email": email})

    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    # Hash the password
    hashed_password = hash_password(password)

    # Get default group if not provided
    # if not group:
    #     group = get_users_group()
    #     logger.info(f"Using default users group: {group}")

    # Create current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create new UserBeanie
    user_beanie = UserBeanie(
        email=email,
        password=hashed_password,
        is_admin=is_admin,
        registration_date=current_time,
        last_login=current_time,
        # groups=[group],
    )

    # Save to database
    await user_beanie.create()
    logger.info(f"User created with id: {user_beanie.id}")

    return user_beanie
