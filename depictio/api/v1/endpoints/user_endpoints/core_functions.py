from datetime import datetime, timedelta

import bcrypt
from beanie import PydanticObjectId
from fastapi import HTTPException
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import format_pydantic, logger
from depictio.api.v1.endpoints.user_endpoints.utils import create_access_token
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import TokenBase, TokenBeanie, TokenData, UserBeanie


async def _create_permanent_token(user: UserBeanie) -> TokenBeanie:
    """Create a permanent token for a user."""
    token_data = TokenData(
        sub=user.id,  # type: ignore[invalid-argument-type]
        name="anonymous_permanent_token",
        token_lifetime="permanent",  # type: ignore[invalid-argument-type]
    )
    access_token, _ = await create_access_token(token_data, expiry_hours=24 * 365)
    token = TokenBeanie(
        access_token=access_token,
        refresh_token="",
        expire_datetime=datetime.max,
        refresh_expire_datetime=datetime.max,
        name=token_data.name,
        token_lifetime="permanent",
        user_id=user.id,  # type: ignore[invalid-argument-type]
        logged_in=True,
    )
    await token.save()
    return token


async def _create_anonymous_user() -> UserBeanie:
    """Create the anonymous user if it does not exist."""
    user = await UserBeanie.find_one({"email": settings.auth.anonymous_user_email})
    if user:
        return user
    payload = await _create_user_in_db(
        email=settings.auth.anonymous_user_email,
        password="",
        is_admin=False,
        is_anonymous=True,
    )
    return payload["user"] if payload else None  # type: ignore[invalid-return-type]


async def _create_temporary_user(
    expiry_hours: int = 24,
    expiry_minutes: int = 0,
) -> UserBeanie:
    """Create a temporary user that will be automatically cleaned up after expiry_hours.

    Args:
        expiry_hours: Number of hours until the user expires (default: 24)

    Returns:
        The created temporary UserBeanie object
    """
    import secrets
    import uuid

    # Generate a unique temporary email
    temp_id = str(uuid.uuid4())[:8]
    temp_email = f"temp_user_{temp_id}@depictio.temp"

    # Set expiration time
    expiration_time = datetime.now() + timedelta(hours=expiry_hours, minutes=expiry_minutes)

    logger.info(f"Creating temporary user with email: {temp_email}, expires at: {expiration_time}")

    # Generate a random password for the temporary user
    temp_password = secrets.token_urlsafe(32)
    hashed_password = _hash_password(temp_password)

    # Create current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create new temporary UserBeanie
    user_beanie = UserBeanie(
        id=PyObjectId(),
        email=temp_email,
        password=hashed_password,
        is_admin=False,
        is_anonymous=False,
        is_temporary=True,
        expiration_time=expiration_time,
        registration_date=current_time,
        last_login=current_time,
    )

    # Save to database
    await user_beanie.create()
    logger.info(f"Temporary user created with id: {user_beanie.id}, expires at: {expiration_time}")

    return user_beanie


async def _create_temporary_user_session(temp_user: UserBeanie) -> dict:
    """Create a session token for a temporary user.

    Args:
        temp_user: The temporary user to create a session for

    Returns:
        Session data dictionary with access token and user info
    """
    # Create a temporary token with same expiration as user
    token_data = TokenData(
        sub=temp_user.id,  # type: ignore[invalid-argument-type]
        name=f"temp_session_{temp_user.id}",
        token_lifetime="long-lived",  # type: ignore[invalid-argument-type]
    )

    # Calculate hours until expiration
    if temp_user.expiration_time:
        expiry_hours = max(
            1, int((temp_user.expiration_time - datetime.now()).total_seconds() / 3600)
        )
    else:
        expiry_hours = 24

    access_token, expire_datetime = await create_access_token(token_data, expiry_hours=expiry_hours)

    token = TokenBeanie(
        access_token=access_token,
        refresh_token="",
        expire_datetime=expire_datetime,
        refresh_expire_datetime=expire_datetime,
        name=token_data.name,
        token_lifetime="long-lived",
        user_id=temp_user.id,  # type: ignore[invalid-argument-type]
        logged_in=True,
    )
    await token.save()

    # Convert to session data format expected by frontend
    session_data = {
        "logged_in": True,
        "email": temp_user.email,
        "user_id": str(temp_user.id),
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expire_datetime": token.expire_datetime.isoformat(),
        "refresh_expire_datetime": token.refresh_expire_datetime.isoformat(),
        "is_temporary": True,
        "expiration_time": temp_user.expiration_time.isoformat()
        if temp_user.expiration_time
        else None,
        "name": token.name,
        "token_lifetime": token.token_lifetime,
        "token_type": token.token_type or "bearer",
    }

    logger.info(f"Created session for temporary user: {temp_user.email}")
    return session_data


async def _cleanup_expired_temporary_users() -> dict:
    """Clean up expired temporary users and their associated tokens.

    Returns:
        Dictionary with cleanup results
    """
    logger.info("Starting cleanup of expired temporary users")

    current_time = datetime.now()

    # Find all expired temporary users
    expired_users = await UserBeanie.find(
        {"is_temporary": True, "expiration_time": {"$lte": current_time}}
    ).to_list()

    cleanup_results = {
        "expired_users_found": len(expired_users),
        "users_deleted": 0,
        "tokens_deleted": 0,
        "errors": [],
    }

    for user in expired_users:
        try:
            # Delete associated tokens first
            user_tokens = await TokenBeanie.find({"user_id": user.id}).to_list()
            for token in user_tokens:
                await token.delete()
                cleanup_results["tokens_deleted"] += 1

            # Delete the user
            await user.delete()
            cleanup_results["users_deleted"] += 1

            logger.info(
                f"Deleted expired temporary user: {user.email} (expired at: {user.expiration_time})"
            )

        except Exception as e:
            error_msg = f"Failed to delete user {user.email}: {str(e)}"
            logger.error(error_msg)
            cleanup_results["errors"].append(error_msg)

    logger.info(f"Cleanup completed: {cleanup_results}")
    return cleanup_results


@validate_call(validate_return=True)
async def _async_fetch_user_from_token(token: str) -> UserBeanie | None:
    """
    Fetch a user based on the provided access token by first querying TokenBeanie.

    Args:
        token: The access token to look up

    Returns:
        The UserBeanie object if found, None otherwise
    """
    # Validate input
    if not isinstance(token, str):
        logger.debug("Invalid token format")
        return None

    logger.debug(
        f"Fetching user from token {token[:10]}..."
    )  # Only log part of the token for security

    if not token:
        logger.debug("Empty token provided")
        return None

    # Find the token in the TokenBeanie collection
    token_doc = await TokenBeanie.find_one({"access_token": token})

    if not token_doc:
        logger.debug(f"No token found matching {token[:10]}...")
        return None

    # Get the user_id from the token and find the corresponding user
    user_id = token_doc.user_id
    user = await UserBeanie.get(user_id)

    if not user:
        logger.debug(f"Token exists but no matching user found with ID {user_id}")
        return None

    # Fetch linked documents if needed
    # await user.fetch_all_links()
    # logger.debug(f"User fetched from token: {user.id}")

    return user


@validate_call(validate_return=True)
async def _async_fetch_user_from_email(email: EmailStr) -> UserBeanie | None:
    """
    Fetch a user based on their email address.

    Args:
        email: The email address to look up
        return_tokens: Whether to include tokens in the response (only long-lived tokens if True)

    Returns:
        The UserBeanie object if found, None otherwise
    """
    # Find the user by email
    user = await UserBeanie.find_one({"email": email})

    if not user:
        logger.debug(f"No user found with email {email}")
        return None

    # Fetch linked documents
    logger.debug(f"User fetched from email: {user}")
    return user


@validate_call(validate_return=True)
async def _async_fetch_user_from_id(user_id: PydanticObjectId) -> UserBeanie:
    logger.debug(f"Fetching user from ID: {user_id}")
    user = await UserBeanie.find_one({"_id": user_id})
    if not user:
        logger.debug(f"No user found with ID {user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    logger.debug(f"User fetched from ID: {user}")
    return user


@validate_call(validate_return=True)
async def _check_if_token_is_valid(token: TokenBase) -> dict:
    """
    Check if the provided token is valid and not expired.

    Args:
        token: The token to check

    Returns:
        dict: {
            "access_valid": bool,
            "refresh_valid": bool,
            "can_refresh": bool,
            "action": str  # "valid", "refresh", "logout"
        }
    """
    logger.debug(f"Checking token: {token.access_token[:10]}...")

    # Find token document in database
    token_doc = await TokenBeanie.find_one(
        {
            "access_token": token.access_token,
            "user_id": token.user_id,
        }
    )

    if not token_doc:
        logger.debug("Token not found in database")
        return {
            "access_valid": False,
            "refresh_valid": False,
            "can_refresh": False,
            "action": "logout",
        }

    current_time = datetime.now()

    # Check access token expiry
    access_valid = token_doc.expire_datetime > current_time

    # Check refresh token expiry
    refresh_valid = token_doc.refresh_expire_datetime > current_time

    logger.debug(f"Access token valid: {access_valid}")
    logger.debug(f"Refresh token valid: {refresh_valid}")

    # Determine action
    if access_valid:
        action = "valid"  # Continue normally
    elif refresh_valid:
        action = "refresh"  # Access expired but can refresh
    else:
        action = "logout"  # Both expired, force re-login

    return {
        "access_valid": access_valid,
        "refresh_valid": refresh_valid,
        "can_refresh": refresh_valid,
        "action": action,
    }


@validate_call(validate_return=True)
async def _purge_expired_tokens(user) -> dict[str, bool | int]:
    """
    Purge expired tokens for a user.
    Args:
        user_id: The user ID to purge tokens for
    Returns:
        A dictionary with success status and deleted count
    """

    # Delete the expired tokens - delete many
    outdated_tokens = await TokenBeanie.find(
        {"user_id": user.id, "refresh_expire_datetime": {"$lt": datetime.now()}}
    ).to_list()

    for token in outdated_tokens:
        await token.delete()

    logger.debug(f"Deleted {len(outdated_tokens)} expired tokens")

    # Return success status
    return {
        "success": True,
        "deleted_count": len(outdated_tokens),
    }


@validate_call(validate_return=True)
async def _list_tokens(
    user_id: PydanticObjectId | None = None,
    token_lifetime: str | None = None,
) -> list[TokenBeanie]:
    if token_lifetime not in ["short-lived", "long-lived", "permanent", None]:
        raise HTTPException(
            status_code=400,
            detail="Invalid token_lifetime. Must be 'short-lived', 'long-lived', or 'permanent'.",
        )

    query = {
        "user_id": user_id,
        "expire_datetime": {"$gt": datetime.now()},
    }

    if token_lifetime:
        query["token_lifetime"] = token_lifetime

    cli_configs = await TokenBeanie.find_many(query).to_list()
    logger.debug(f"CLI configs nb: {len(cli_configs)}")

    return cli_configs


@validate_call(validate_return=True)
async def _get_anonymous_user_session() -> dict:
    """
    Fetch the anonymous user and their permanent token for frontend session.

    Returns:
        dict: Session data compatible with frontend authentication
    """
    # Find the anonymous user
    anonymous_user = await UserBeanie.find_one({"email": settings.auth.anonymous_user_email})
    if not anonymous_user:
        raise HTTPException(
            status_code=404,
            detail=f"Anonymous user not found: {settings.auth.anonymous_user_email}",
        )

    # Get the permanent token for the anonymous user
    permanent_tokens = await _list_tokens(user_id=anonymous_user.id, token_lifetime="permanent")

    if not permanent_tokens:
        raise HTTPException(
            status_code=404,
            detail=f"No permanent token found for anonymous user: {anonymous_user.email}",
        )

    # Use the first permanent token (there should only be one)
    permanent_token = permanent_tokens[0]

    # Convert to session data format expected by frontend
    session_data = {
        "logged_in": True,
        "email": anonymous_user.email,
        "user_id": str(anonymous_user.id),
        "access_token": permanent_token.access_token,
        "refresh_token": permanent_token.refresh_token,
        "expire_datetime": permanent_token.expire_datetime.isoformat()
        if permanent_token.expire_datetime
        else "9999-12-31T23:59:59",
        "refresh_expire_datetime": permanent_token.refresh_expire_datetime.isoformat()
        if permanent_token.refresh_expire_datetime
        else "9999-12-31T23:59:59",
        "is_anonymous": True,
        "name": permanent_token.name,
        "token_lifetime": permanent_token.token_lifetime,
        "token_type": permanent_token.token_type or "bearer",
    }

    logger.info(f"Retrieved anonymous user session for: {anonymous_user.email}")
    return session_data


@validate_call(validate_return=True)
async def _delete_token(token_id: PydanticObjectId) -> bool:
    """
    Delete a token by its ID.

    Args:
        token_id: The ID of the token to delete

    Returns:
        True if the token was deleted, False otherwise
    """
    token = await TokenBeanie.get(token_id)
    if not token:
        logger.debug(f"No token found with ID {token_id}")
        return False

    await token.delete()
    logger.debug(f"Token with ID {token_id} deleted")
    return True


@validate_call(validate_return=True)
async def _edit_password(user_id: PydanticObjectId, new_password: str) -> bool:
    """
    Core function to update a user's password in the database.

    Args:
        user_id: The ID of the user
        new_password: The new password to set

    Returns:
        bool: True if the password was updated successfully, False otherwise
    """
    # Get the user from the database
    user = await UserBeanie.get(user_id)
    if not user:
        logger.error(f"User with ID {user_id} not found")
        return False

    # Update the password
    user.password = new_password

    # Save the user to the database
    try:
        await user.save()
        logger.info(f"Password updated successfully for user with email {user.email}")

        # Fetch and log the updated user for verification
        updated_user = await UserBeanie.find_one({"email": user.email})
        logger.info(f"Show updated user from database: {updated_user}")

        return True
    except Exception as e:
        logger.error(f"Failed to update password: {e}")
        return False


@validate_call(validate_return=True)
async def _add_token(token_data: TokenData) -> TokenBeanie:
    email = token_data.sub
    logger.info(f"Adding token for user {email}.")
    logger.info(f"Token: {format_pydantic(token_data)}")
    if token_data.token_lifetime == "permanent":
        access_token, _ = await create_access_token(token_data, expiry_hours=24 * 365)
        refresh_token = ""
        expire = datetime.max
        expire_refresh = datetime.max
    else:
        access_token, expire = await create_access_token(
            token_data,
            expiry_hours=1,
        )  # 1 hour
        refresh_token, expire_refresh = await create_access_token(
            token_data,
            expiry_hours=7 * 24,
        )  # 7 days

    token = TokenBeanie(
        access_token=access_token,
        refresh_token=refresh_token,
        expire_datetime=(  # type: ignore[invalid-argument-type]
            expire.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(expire, datetime) and expire != datetime.max
            else datetime.max
        ),
        refresh_expire_datetime=(  # type: ignore[invalid-argument-type]
            expire_refresh.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(expire_refresh, datetime) and expire_refresh != datetime.max
            else datetime.max
        ),
        name=token_data.name,
        token_lifetime=token_data.token_lifetime,
        user_id=token_data.sub,  # type: ignore[invalid-argument-type]
    )

    await TokenBeanie.save(token)

    logger.info(f"Token created for user {email}.")

    return token


@validate_call(validate_return=True)
def _verify_password(stored_hash: str, password: str) -> bool:
    # Verify the password against the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


@validate_call(validate_return=True)
async def _check_password(email: str, password: str) -> bool:
    """
    Check if the provided password matches the stored password for the user.
    Args:
        email (str): The email of the user.
        password (str): The password to verify.
    Returns:
        bool: True if the password matches, False otherwise.
    """
    logger.info(f"Checking password for user {email}.")
    user = await _async_fetch_user_from_email(email)
    logger.debug(f"User found: {user.email if user else 'None'}")
    if user:
        if _verify_password(user.password, password):
            return True
    return False


@validate_call(validate_return=True)
def _hash_password(password: str) -> str:
    # Generate a salt
    salt = bcrypt.gensalt()
    # Hash the password with the salt
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    # Return the hashed password
    return hashed.decode("utf-8")


@validate_call(validate_return=True)
async def _create_user_in_db(
    email: EmailStr,
    password: str,
    is_admin: bool = False,
    is_anonymous: bool = False,
    id: PyObjectId = None,  # type: ignore[invalid-parameter-default]
    group: str | None = None,
) -> dict[str, bool | str | UserBeanie | None] | None:
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
    search_query = {"email": email}
    if id:
        search_query["_id"] = id
    existing_user = await UserBeanie.find_one(search_query)

    if existing_user:
        logger.warning(f"User {email} already exists in the database")
        return {
            "success": False,
            "message": "User already exists",
            "user": existing_user,  # The CustomJSONResponse will handle serialization
        }

    # Hash the password
    hashed_password = _hash_password(password)

    # Create current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create new UserBeanie
    user_beanie = UserBeanie(
        id=id if id else PyObjectId(),
        email=email,
        password=hashed_password,
        is_admin=is_admin,
        is_anonymous=is_anonymous,
        registration_date=current_time,
        last_login=current_time,
        # groups=[group],
    )

    # Save to database
    await user_beanie.create()
    logger.info(f"User created with id: {user_beanie.id}")

    return {
        "success": True,
        "message": "User created successfully",
        "user": user_beanie,
    }
