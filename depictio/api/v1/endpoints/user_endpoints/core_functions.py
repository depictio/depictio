from datetime import datetime

import bcrypt
from beanie import PydanticObjectId
from fastapi import HTTPException
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.endpoints.user_endpoints.utils import create_access_token
from depictio.models.models.users import TokenBase, TokenBeanie, TokenData, UserBeanie


@validate_call(validate_return=True)
async def _async_fetch_user_from_token(token: str) -> UserBeanie | None:
    """
    Fetch a user based on the provided access token by first querying TokenBeanie.

    Args:
        token: The access token to look up

    Returns:
        The UserBeanie object if found, None otherwise
    """
    logger.debug(f"Current token: {token}")

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
    logger.debug(f"User fetched from token: {format_pydantic(user)}")

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
    logger.debug(f"User fetched from email: {format_pydantic(user)}")
    return user


@validate_call(validate_return=True)
async def _async_fetch_user_from_id(user_id: PydanticObjectId) -> UserBeanie:
    logger.debug(f"Fetching user from ID: {user_id}")
    logger.debug(f"Fetching user from ID of type: {type(user_id)}")
    user = await UserBeanie.find_one({"_id": user_id})
    if not user:
        logger.debug(f"No user found with ID {user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    return user


@validate_call(validate_return=True)
async def _check_if_token_is_valid(token: TokenBase) -> bool:
    """
    Check if the provided token is valid and not expired.

    Args:
        token: The token to check

    Returns:
        True if the token is valid, False otherwise
    """
    # Check if the token exists in the database and has not expired
    check = await TokenBeanie.find_one(
        {
            "access_token": token.access_token,
            "expire_datetime": {"$gt": datetime.now()},  # Use datetime object, not string
            "user_id": token.user_id,
        }
    )
    logger.debug(f"Checking token: {token.access_token} : {check}")
    if check:
        # Token exists and is not expired
        return True
    else:
        # Token does not exist or is expired
        return False


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
        {"user_id": user.id, "expire_datetime": {"$lt": datetime.now()}}
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
    if token_lifetime not in ["short-lived", "long-lived", None]:
        raise HTTPException(
            status_code=400,
            detail="Invalid token_lifetime. Must be 'short-lived' or 'long-lived'.",
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
    token_value, expire = await create_access_token(token_data)

    token = TokenBeanie(
        access_token=token_value,
        expire_datetime=expire.strftime("%Y-%m-%d %H:%M:%S"),
        name=token_data.name,
        token_lifetime=token_data.token_lifetime,
        user_id=token_data.sub,
    )
    logger.debug(f"Token: {format_pydantic(token)}")

    await TokenBeanie.save(token)

    logger.info(f"Token created for user {email}.")

    return token


@validate_call(validate_return=True)
def _verify_password(stored_hash: str, password: str) -> bool:
    logger.info(f"Stored hash: {stored_hash}")
    logger.info(f"Password to verify: {password}")
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
    logger.debug(f"Checking password for user {email}.")
    user = await _async_fetch_user_from_email(email)
    logger.debug(f"User found: {user}")
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
    email: EmailStr, password: str, is_admin: bool = False
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
    existing_user = await UserBeanie.find_one({"email": email})

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
        email=email,
        password=hashed_password,
        is_admin=is_admin,
        registration_date=current_time,
        last_login=current_time,
        # groups=[group],
    )

    logger.debug(user_beanie)
    logger.debug(user_beanie.model_dump())

    # Save to database
    await user_beanie.create()
    logger.info(f"User created with id: {user_beanie.id}")

    return {
        "success": True,
        "message": "User created successfully",
        "user": user_beanie,
    }
