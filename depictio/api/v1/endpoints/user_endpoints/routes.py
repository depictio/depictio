from typing import Annotated
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime

from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    add_token_to_user,
    check_if_token_is_valid,
    fetch_user_from_email,
    fetch_user_from_id,
    fetch_user_from_token,
    generate_agent_config,
    purge_expired_tokens_from_user,
)

from depictio.api.v1.endpoints.user_endpoints.utils import (
    add_token,
    check_password,
    create_group_helper,
    delete_group_helper,
)
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.db import users_collection

from depictio_models.models.base import convert_objectid_to_str
from depictio_models.models.users import User, UserBase, UserBaseGroupLess
from depictio_models.utils import convert_model_to_dict

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
    logger.info(f"User: {user}")

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token with the same name already exists",
        )

    logger.info(f"Token generated for user: {login_request.username}")

    # Update last-login field in the user document
    result = users_collection.update_one(
        {"email": login_request.username},
        {"$set": {"last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}},
    )

    return {
        "access_token": token.access_token,
        "token_type": "bearer",
        "expire_datetime": token.expire_datetime,
        "name": token.name,
        "token_lifetime": token.token_lifetime,
        "logged_in": True,
    }


@auth_endpoint_router.post("/register")
async def create_user(user: User):
    # Add user to the database
    logger.info(f"Creating user: {user}")
    user_dict = convert_model_to_dict(user)
    logger.info(f"User dict: {user_dict}")
    # Check if the user already exists
    existing_user = users_collection.find_one({"email": user.email})
    logger.info(f"Existing user: {existing_user}")
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    # Insert the user into the database
    else:
        user_db = User.from_mongo(user_dict).mongo()
        logger.info(f"User: {user_db}")
        result = users_collection.insert_one(user_db)

        # Retrieve the user from the database and convert ObjectIds to strings
        created_user = users_collection.find_one({"_id": result.inserted_id})
        if created_user:
            return convert_objectid_to_str(created_user)
        else:
            raise HTTPException(
                status_code=500, detail="Failed to retrieve created user"
            )


@auth_endpoint_router.get("/get_all_groups")
async def get_all_groups(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")
    from depictio.api.v1.db import groups_collection

    groups = groups_collection.find()
    groups = [convert_objectid_to_str(group) for group in groups]
    return groups


@auth_endpoint_router.get("/get_all_groups_including_users")
async def get_all_groups_with_users(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")
    from depictio.api.v1.db import groups_collection, users_collection

    groups = groups_collection.find()
    groups = [convert_objectid_to_str(group) for group in groups]

    for group in groups:
        group_id = ObjectId(group["_id"])
        logger.info(f"Finding users for group: {group_id}")

        # Based on the actual user document structure where groups is an array of objects
        # with _id field that contains a $oid field
        users = list(users_collection.find({"groups._id": ObjectId(group_id)}))
        logger.info(f"users found: {users}")

        if users:
            users = [
                convert_objectid_to_str(
                    UserBaseGroupLess(
                        id=user["_id"],
                        email=user["email"],
                        is_admin=user["is_admin"],
                    ).model_dump(exclude_none=True)
                )
                for user in users
            ]
            # # drop groups field from users
            # for user in users:
            #     user.pop("groups", None)
            group["users"] = users

    logger.info(f"Groups with users: {groups}")
    return groups


@auth_endpoint_router.get("/get_users_group")
async def get_users_group():
    from depictio.api.v1.db import groups_collection

    groups = groups_collection.find({"name": "users"})
    groups = [convert_objectid_to_str(group) for group in groups]
    if len(groups) == 0:
        return None
    if len(groups) > 1:
        raise HTTPException(
            status_code=500, detail="Multiple groups with the same name"
        )
    return groups[0]


@auth_endpoint_router.get("/fetch_user/from_id")
async def api_fetch_user(user_id: str, current_user=Depends(get_current_user)):
    if not user_id:
        raise HTTPException(status_code=400, detail="No user_id provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user = fetch_user_from_id(user_id)
    if user:
        # Ensure ObjectIds are converted to strings
        if isinstance(user, dict):
            return convert_objectid_to_str(user)
        else:
            # If it's already a model, convert to dict first
            return convert_model_to_dict(user)
    else:
        raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.get("/fetch_user/from_email")
async def api_fetch_user(email: str, current_user=Depends(get_current_user)):
    if not email:
        raise HTTPException(status_code=400, detail="No email provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    user = fetch_user_from_email(email)
    if user:
        # Ensure ObjectIds are converted to strings
        if isinstance(user, dict):
            return convert_objectid_to_str(user)
        else:
            # If it's already a model, convert to dict first
            return convert_model_to_dict(user)
    else:
        raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.get("/fetch_user/from_token")
async def api_fetch_user_from_token(token: str, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    if not token:
        raise HTTPException(status_code=400, detail="No token provided")

    user = fetch_user_from_token(token)
    if user:
        # Ensure ObjectIds are converted to strings
        if isinstance(user, dict):
            return convert_objectid_to_str(user)
        else:
            # If it's already a model, convert to dict first
            return convert_model_to_dict(user)
    else:
        raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.post("/edit_password")
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
        raise HTTPException(
            status_code=400,
            detail="New password cannot be the same as the old password",
        )

    current_user.password = new_password

    update_data = current_user.mongo()
    logger.info(f"Update data: {update_data}")

    # Ensure user_id is an ObjectId for the query
    user_id = current_user.id
    if not isinstance(user_id, ObjectId):
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        else:
            user_id = ObjectId(str(user_id))

    # Update the user in the database by replacing ONLY the password field
    result = users_collection.update_one(
        {"_id": user_id}, {"$set": {"password": new_password}}
    )

    # Log the update result
    logger.info(f"Update result: {result.modified_count} document(s) updated")
    logger.info(
        f"Show updated user from database: {users_collection.find_one({'email': current_user.email})}"
    )

    if result.modified_count == 1:
        return convert_model_to_dict(current_user)
    else:
        raise HTTPException(status_code=500, detail="Failed to update password")


@auth_endpoint_router.post("/add_token")
async def add_token_endpoint(request: dict, current_user=Depends(get_current_user)):
    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    logger.info(f"Request: {request}")
    user = convert_model_to_dict(current_user)
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

    # Ensure user_id is an ObjectId
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])
    elif isinstance(user_id, ObjectId):
        # Already an ObjectId, no conversion needed
        pass
    else:
        # Convert to string first, then to ObjectId
        user_id = ObjectId(str(user_id))

    # Log the _id and the query structure
    logger.debug(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}

    # Get existing tokens from the user and remove the token to be deleted
    user_data = users_collection.find_one(query)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    tokens = user_data.get("tokens", [])
    logger.debug(f"Tokens: {tokens}")
    tokens = [e for e in tokens if str(e["_id"]) != str(token_id)]
    logger.debug(f"Tokens after deletion: {tokens}")

    # Update the user with the new tokens
    update = {"$set": {"tokens": tokens}}
    logger.debug(f"Query: {query}")

    # Update the user collection
    result = users_collection.update_one(query, update)
    logger.debug(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": result.modified_count > 0}


@auth_endpoint_router.post("/purge_expired_tokens")
async def purge_expired_tokens_endpoint(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Convert user_id to string to ensure compatibility
    user_id = str(current_user.id)

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
def generate_agent_config_endpoint(
    request: dict, current_user=Depends(get_current_user)
):
    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if "token" not in request:
        raise HTTPException(status_code=400, detail="No token provided")

    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Convert current_user to dict with ObjectIds as strings
    user_dict = convert_model_to_dict(current_user)

    depictio_agent_config = generate_agent_config(
        current_user=user_dict, request=request
    )

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


@auth_endpoint_router.delete("/delete/{user_id}")
def delete_user(user_id: str, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    # Ensure user_id is an ObjectId
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])
    elif isinstance(user_id, ObjectId):
        # Already an ObjectId, no conversion needed
        pass
    else:
        # Convert to string first, then to ObjectId
        user_id = ObjectId(str(user_id))

    # Delete the user from the database
    result = users_collection.delete_one({"_id": user_id})
    if result.deleted_count == 1:
        return {"success": True}
    else:
        return {"success": False}


@auth_endpoint_router.post("/turn_sysadmin/{user_id}")
def turn_sysadmin(user_id: str, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    # Ensure user_id is an ObjectId
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])
    elif isinstance(user_id, ObjectId):
        # Already an ObjectId, no conversion needed
        pass
    else:
        # Convert to string first, then to ObjectId
        user_id = ObjectId(str(user_id))

    # Update the user in the database
    result = users_collection.update_one({"_id": user_id}, {"$set": {"is_admin": True}})
    if result.modified_count == 1:
        return {"success": True}
    else:
        return {"success": False}


@auth_endpoint_router.post("/create_group")
def create_group(request: dict, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if "name" not in request:
        raise HTTPException(status_code=400, detail="No name provided")

    response = create_group_helper(request)
    return response


@auth_endpoint_router.delete("/delete_group/{group_id}")
def delete_group(group_id: str, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    # Ensure group_id is an ObjectId
    if isinstance(group_id, str):
        group_id = ObjectId(group_id)
    elif isinstance(group_id, dict) and "$oid" in group_id:
        group_id = ObjectId(group_id["$oid"])
    elif isinstance(group_id, ObjectId):
        # Already an ObjectId, no conversion needed
        pass
    else:
        # Convert to string first, then to ObjectId
        group_id = ObjectId(str(group_id))

    response = delete_group_helper(group_id)
    return response
