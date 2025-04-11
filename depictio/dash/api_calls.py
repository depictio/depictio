from typing import Dict, Any, Optional
import httpx
from pydantic import EmailStr, validate_call

from depictio.api.v1.configs.config import settings, API_BASE_URL
from depictio.api.v1.configs.custom_logging import format_pydantic, logger

from depictio_models.models.users import User
from depictio_models.utils import convert_model_to_dict


@validate_call(validate_return=True)
def api_call_register_user(
    email: EmailStr, 
    password: str, 
    group: Optional[str] = None, 
    is_admin: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Register a new user by calling the API.
    
    Args:
        email: User's email address
        password: User's password
        group: User's group (optional)
        is_admin: Whether user is admin
        
    Returns:
        Response from registration or None if failed
    """
    try:
        logger.info(f"Registering user with email: {email}")
        logger.debug(f"Password: {password}")
        logger.debug(f"Group: {group}")
        logger.debug(f"Is Admin: {is_admin}")

        # Create payload with parameters
        params = {
            "email": email,
            "password": password,
            "is_admin": is_admin
        }
        
        # Add group if provided
        if group:
            params["group"] = group
        
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/register",
            params=params,
        )
        
        if response.status_code == 200:
            logger.info("User registered successfully.")
            return response.json()
        else:
            logger.error(f"Registration error: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Registration exception: {str(e)}")
        return None

@validate_call(validate_return=True)
def api_call_fetch_user_from_token(token: str) -> Optional[User]:
    """
    Fetch a user from the authentication service using a token.
    Synchronous version for Dash compatibility.

    Args:
        token: The authentication token

    Returns:
        Optional[User]: The user if found, None otherwise
    """
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token",
        params={"token": token},
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code == 404:
        return None

    user_data = response.json()
    logger.debug(f"User data fetched: {user_data}")

    if not user_data:
        return None

    user = User(**user_data)

    logger.debug(f"User object created: {format_pydantic(user)}")

    return user


@validate_call(validate_return=True)
def purge_expired_tokens(token: str) -> Optional[Dict[str, Any]]:
    """
    Purge expired tokens from the database.
    Args:
        token: The authentication token
    Returns:
        Optional[Dict[str, Any]]: The response from the purge operation
    """
    if token:
        # Clean existing expired token from DB
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/auth/purge_expired_tokens",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            logger.info("Expired tokens purged successfully.")
            return response.json()
        else:
            logger.error(f"Error purging expired tokens: {response.text}")
            return None
    else:
        logger.error("Token not found.")
        return None
