from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    add_token_to_user,
    check_if_token_is_valid,
    fetch_user_from_email,
    fetch_user_from_token,
    generate_agent_config,
    purge_expired_tokens_from_user,
)
from depictio.api.v1.endpoints.user_endpoints.models import User, UserBase
from depictio.api.v1.endpoints.user_endpoints.utils import add_token, check_password
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.db import users_collection
from depictio.api.v1.models.base import convert_objectid_to_str


auth_endpoint_router = APIRouter()


# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/depictio/api/v1/auth/login")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    """Returns the current user from the token.

    Args:
        token (Annotated[str, Depends): _description_

    Raises:
        HTTPException: _description_
        HTTPException: _description_

    Returns:
        _type_: _description_
    """
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = fetch_user_from_token(token)

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


# Login endpoint
@auth_endpoint_router.post("/login")
async def login(login_request: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint

    Args:
        login_request (OAuth2PasswordRequestForm, optional): _description_. Defaults to Depends().

    Raises:
        HTTPException: _description_
        HTTPException: _description_

    Returns:
        _type_: _description_
    """
    logger.info(f"Login attempt for user: {login_request.username}")

    # Verify credentials
    _ = check_password(login_request.username, login_request.password)
    if not _:
        logger.error("Invalid credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Generate random name for the token
    token_name = f"{login_request.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Add token details to user info
    token_data = {
        "sub": login_request.username,
        "name": token_name,
        "token_lifetime": "short-lived",
    }

    # Generate and store token
    token = add_token(token_data)
    logger.info(f"Token : {token}")
    if token is None:
        logger.error("Token with the same name already exists.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token with the same name already exists")

    logger.info(f"Token generated for user: {login_request.username}")

    # Update last-login field in the user document
    result = users_collection.update_one({"email": login_request.username}, {"$set": {"last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}})

    return {
        "access_token": token.access_token,
        "token_type": "bearer",
        "expire_datetime": token.expire_datetime,
        "name": token.name,
        "token_lifetime": token.token_lifetime,
        "logged_in": True,
    }


@auth_endpoint_router.post("/register", response_model=User)
async def create_user(user: User):
    # Add user to the database
    user_dict = user.dict()
    # Check if the user already exists
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    # Insert the user into the database
    else:
        users_collection.insert_one(User(**user_dict).mongo())
        return user


@auth_endpoint_router.get("/fetch_user/from_email")
async def api_fetch_user(email: str, current_user=Depends(get_current_user)):
    if not email:
        raise HTTPException(status_code=400, detail="No email provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user = fetch_user_from_email(email)
    if user:
        return user
    else:
        raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.get("/fetch_user/from_token", response_model=User)
async def api_fetch_user_from_token(token: str, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    if not token:
        raise HTTPException(status_code=400, detail="No token provided")

    user = fetch_user_from_token(token)
    if user:
        return user
    else:
        raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.post("/edit_password", response_model=User)
async def edit_password(request: dict, current_user=Depends(get_current_user)):
    # user_data = users_collection.find_one({"id": current_user.id})

    logger.info(f"Current user: {current_user}")

    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if not "old_password" in request:
        raise HTTPException(status_code=400, detail="No old password provided")

    if not "new_password" in request:
        raise HTTPException(status_code=400, detail="No new password provided")

    old_password = request.get("old_password")
    new_password = request.get("new_password")

    if not old_password:
        raise HTTPException(status_code=400, detail="No old password provided")

    if not new_password:
        raise HTTPException(status_code=400, detail="No new password provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    if not check_password(current_user.email, old_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")

    if current_user.password == new_password:
        raise HTTPException(status_code=400, detail="New password cannot be the same as the old password")

    current_user.password = new_password

    update_data = current_user.mongo()
    logger.info(f"Update data: {update_data}")

    # Update the user in the database by replacing ONLY the password field
    result = users_collection.update_one({"_id": current_user.id}, {"$set": {"password": new_password}})

    # Log the update result
    logger.info(f"Update result: {result.modified_count} document(s) updated")
    logger.info(f"Show updated user from database: {users_collection.find_one({'email' : current_user.email})}")

    if result.modified_count == 1:
        return current_user
    else:
        raise HTTPException(status_code=500, detail="Failed to update password")


@auth_endpoint_router.post("/add_token")
async def add_token_endpoint(request: dict, current_user=Depends(get_current_user)):
    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    logger.info(f"Request: {request}")
    user = current_user.dict()
    token = request["token"]
    logger.info(f"Request: {request}")
    logger.info(f"User: {user}")
    logger.info(f"Token: {token}")

    result = add_token_to_user(user, token)
    if not result["success"]:
        raise HTTPException(status_code=500, detail="Failed to add token")

    return result


@auth_endpoint_router.post("/delete_token")
async def delete_token(request: dict, current_user=Depends(get_current_user)):
    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    logger.debug(f"Request: {request}")

    token_id = request["token_id"]
    user_id = current_user.id
    logger.debug(f"Token ID: {token_id}")

    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.debug(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}

    # Get existing tokens from the user and remove the token to be deleted
    user_data = users_collection.find_one(query)
    tokens = user_data.get("tokens", [])
    logger.debug(f"Tokens: {tokens}")
    tokens = [e for e in tokens if str(e["_id"]) != str(token_id)]
    logger.debug(f"Tokens after deletion: {tokens}")

    # Update the user with the new tokens
    update = {"$set": {"tokens": tokens}}
    logger.debug(f"Query: {query}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.debug(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": result.modified_count > 0}


@auth_endpoint_router.post("/purge_expired_tokens")
async def purge_expired_tokens_endpoint(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user_id = current_user.id

    result = purge_expired_tokens_from_user(user_id)

    if result["success"]:
        return {"success": True}

    else:
        raise HTTPException(status_code=500, detail="Failed to purge expired tokens")


@auth_endpoint_router.post("/check_token_validity")
async def check_token_validity_endpoint(request: dict):
    token = request.get("token")

    logger.info(f"Checking token validity.")
    logger.info(f"Token: {token}")
    if not token:
        raise HTTPException(status_code=400, detail="No token provided")

    is_valid = check_if_token_is_valid(token)

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {"detail": "Token is valid"}


@auth_endpoint_router.post("/generate_agent_config")
def generate_agent_config_endpoint(request: dict, current_user=Depends(get_current_user)):
    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if "token" not in request:
        raise HTTPException(status_code=400, detail="No token provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    depictio_agent_config = generate_agent_config(current_user=current_user, request=request)

    return depictio_agent_config


@auth_endpoint_router.get("/list")
def list_users(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")
    
    users = users_collection.find()
    users = [convert_objectid_to_str(user) for user in users]
    return users