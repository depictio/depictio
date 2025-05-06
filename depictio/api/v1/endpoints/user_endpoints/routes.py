from datetime import datetime
from typing import Annotated, Any

from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import EmailStr

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.custom_logging import format_pydantic, logger
from depictio.api.v1.db import users_collection
from depictio.api.v1.endpoints.user_endpoints.agent_config_utils import _generate_agent_config
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _add_token,
    _async_fetch_user_from_email,
    _async_fetch_user_from_id,
    _async_fetch_user_from_token,
    _check_if_token_is_valid,
    _check_password,
    _create_user_in_db,
    _delete_token,
    _edit_password,
    _hash_password,
    _list_tokens,
    _purge_expired_tokens,
)
from depictio.api.v1.endpoints.user_endpoints.utils import (
    delete_group_helper,
    update_group_in_users_helper,
)
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.users import (
    CLIConfig,
    GroupBeanie,
    RequestEditPassword,
    RequestUserRegistration,
    TokenBase,
    TokenBeanie,
    TokenData,
    User,
    UserBase,
    UserBaseUI,
    UserBeanie,
)
from depictio.models.utils import convert_model_to_dict

auth_endpoint_router = APIRouter()


# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/depictio/api/v1/auth/login")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
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

    user = await _async_fetch_user_from_token(token)
    logger.debug(f"User: {user}")

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


# Login endpoint
@auth_endpoint_router.post("/login", response_model=TokenBeanie)
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
    _ = await _check_password(login_request.username, login_request.password)
    if not _:
        logger.error("Invalid credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Generate random name for the token
    token_name = f"{login_request.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    user = await _async_fetch_user_from_email(login_request.username)
    logger.debug(f"User: {user}")

    token_data = TokenData(
        name=token_name,
        token_lifetime="short-lived",
        sub=user.id,
    )
    logger.debug(f"Token data: {token_data}")

    # Generate and store token
    token = await _add_token(token_data)
    logger.info(f"Token : {format_pydantic(token)}")
    if token is None:
        logger.error("Token with the same name already exists.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token with the same name already exists",
        )

    # Set logged_in to True
    token.logged_in = True

    return token  # TokenBeanie


@auth_endpoint_router.post("/create_token", include_in_schema=False)
async def create_token(
    token: TokenData,
    api_key: str = Header(..., description="Internal API key for authentication"),
) -> TokenBeanie:
    logger.info(f"API key: {api_key}")
    logger.info(f"Token: {token}")
    logger.info(f"Internal API key: {settings.auth.internal_api_key}")

    if api_key != settings.auth.internal_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    # Generate and store token
    token = await _add_token(token)
    logger.info(f"Token : {format_pydantic(token)}")
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token with the same name already exists",
        )

    return token


@auth_endpoint_router.get("/fetch_user/from_token")
async def api_fetch_user_from_token(token: str, current_user=Depends(get_current_user)) -> User:
    user = await _async_fetch_user_from_token(token)

    if not user:
        raise HTTPException(status_code=404, detail="User not found for the provided token")

    # if user id differs from current user id
    if user.id != current_user.id:
        raise HTTPException(status_code=403, detail="Token does not belong to the current user")

    return user


@auth_endpoint_router.get("/fetch_user/from_email", include_in_schema=False)
async def api_fetch_user_from_email(
    email: EmailStr,
    api_key: str = Header(..., description="Internal API key for authentication"),
) -> User:
    logger.info(f"API key: {api_key}")
    logger.info(f"Email: {email}")
    logger.info(f"Internal API key: {settings.auth.internal_api_key}")

    if api_key != settings.auth.internal_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    user = await _async_fetch_user_from_email(email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found for the provided email")

    return user


@auth_endpoint_router.get("/fetch_user/from_id")
async def api_fetch_user_from_id(
    user_id: PydanticObjectId, current_user=Depends(get_current_user)
) -> User:
    user = await _async_fetch_user_from_id(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found for the provided ID")

    # if user id differs from current user id
    if user.id != current_user.id:
        raise HTTPException(status_code=403, detail="ID does not belong to the current user")

    return user


@auth_endpoint_router.post("/register")
async def register(
    request: RequestUserRegistration,
) -> dict[str, Any]:
    """
    Endpoint to register a new user.

    Args:
        request: User registration data containing email and password

    Returns:
        Dictionary with user data, success status and message
    """
    logger.info(f"Registering user with email: {request.email}")
    try:
        return await _create_user_in_db(request.email, request.password, request.is_admin)

    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")


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
        logger.debug(f"Finding users for group: {group_id}")

        # Based on the actual user document structure where groups is an array of objects
        # with _id field that contains a $oid field
        users = list(users_collection.find({"groups._id": ObjectId(group_id)}))
        logger.debug(f"users found: {users}")

        if users:
            users = [
                convert_objectid_to_str(
                    UserBase(
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
    from depictio.models.models.users import GroupWithUsers

    groups = [GroupWithUsers.from_mongo(group) for group in groups]
    groups = [convert_model_to_dict(group, exclude_none=True) for group in groups]

    logger.debug(f"Groups with users: {groups}")
    return groups


@auth_endpoint_router.get("/get_users_group")
async def get_users_group():
    from depictio.api.v1.db import groups_collection

    groups = groups_collection.find({"name": "users"})
    groups = [convert_objectid_to_str(group) for group in groups]
    if len(groups) == 0:
        return None
    if len(groups) > 1:
        raise HTTPException(status_code=500, detail="Multiple groups with the same name")
    return groups[0]


@auth_endpoint_router.post("/edit_password")
async def edit_password(
    request: RequestEditPassword, current_user: UserBeanie = Depends(get_current_user)
) -> dict:
    """
    Endpoint to handle user password updates.
    """
    logger.debug(f"User data: {current_user}")

    # Validate password change request
    if not _check_password(current_user.email, request.old_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")

    # Hash the new password
    hashed_password = _hash_password(request.new_password)

    if current_user.password == hashed_password:
        raise HTTPException(
            status_code=400,
            detail="New password cannot be the same as the old password",
        )

    # Call the core function to update the password
    success = await _edit_password(current_user.id, hashed_password)

    if success:
        return {"success": True, "message": "Password updated successfully"}
    else:
        return {"success": False, "message": "Failed to update password"}


@auth_endpoint_router.post("/delete_token", include_in_schema=False)
async def delete_token(
    token_id: PydanticObjectId,
    api_key: str = Header(..., description="Internal API key for authentication"),
):
    if api_key != settings.auth.internal_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    result = await _delete_token(token_id)

    return {"success": result, "message": "Token deleted successfully"}


# @auth_endpoint_router.post("/delete_token")
# async def delete_token(request: dict, current_user=Depends(get_current_user)):
#     if not request:
#         raise HTTPException(status_code=400, detail="No request provided")

#     if not current_user:
#         raise HTTPException(status_code=401, detail="Current user not found.")

#     logger.debug(f"Request: {request}")

#     token_id = request["token_id"]
#     user_id = current_user.id
#     logger.debug(f"Token ID: {token_id}")

#     # Ensure user_id is an ObjectId
#     if isinstance(user_id, str):
#         user_id = ObjectId(user_id)
#     elif isinstance(user_id, dict) and "$oid" in user_id:
#         user_id = ObjectId(user_id["$oid"])
#     elif isinstance(user_id, ObjectId):
#         # Already an ObjectId, no conversion needed
#         pass
#     else:
#         # Convert to string first, then to ObjectId
#         user_id = ObjectId(str(user_id))

#     # Log the _id and the query structure
#     logger.debug(f"User _id (ObjectId): {user_id}")
#     query = {"_id": user_id}

#     # Get existing tokens from the user and remove the token to be deleted
#     user_data = users_collection.find_one(query)
#     if not user_data:
#         raise HTTPException(status_code=404, detail="User not found")

#     tokens = user_data.get("tokens", [])
#     logger.debug(f"Tokens: {tokens}")
#     tokens = [e for e in tokens if str(e["_id"]) != str(token_id)]
#     logger.debug(f"Tokens after deletion: {tokens}")

#     # Update the user with the new tokens
#     update = {"$set": {"tokens": tokens}}
#     logger.debug(f"Query: {query}")

#     # Update the user collection
#     result = users_collection.update_one(query, update)
#     logger.debug(f"Update result: {result.modified_count} document(s) updated")

#     # Return success status
#     return {"success": result.modified_count > 0}


@auth_endpoint_router.post("/purge_expired_tokens", include_in_schema=False)
async def purge_expired_tokens_endpoint(
    # api_key: str = Header(..., description="Internal API key for authentication"),
    current_user: UserBase = Depends(get_current_user),
):
    # logger.debug(f"API key: {api_key}")
    # logger.debug(f"Internal API key: {FASTAPI_INTERNAL_API_KEY}")
    # if api_key != FASTAPI_INTERNAL_API_KEY:
    #     raise HTTPException(
    #         status_code=403,
    #         detail="Invalid API key",
    #     )

    result = await _purge_expired_tokens(current_user)

    if result["success"]:
        return {"success": True}
    else:
        raise HTTPException(status_code=500, detail="Failed to purge expired tokens")


@auth_endpoint_router.post("/check_token_validity")
async def check_token_validity_endpoint(token: TokenBase):
    is_valid = await _check_if_token_is_valid(token)

    return {"success": is_valid}


@auth_endpoint_router.post("/generate_agent_config", response_model=CLIConfig)
async def generate_agent_config_endpoint(
    token: TokenBeanie, current_user: UserBase = Depends(get_current_user)
) -> CLIConfig:
    logger.info(f"Token: {token}")
    logger.info(f"Token: {format_pydantic(token)}")
    depictio_agent_config = await _generate_agent_config(user=current_user, token=token)

    return depictio_agent_config


@auth_endpoint_router.get("/list_tokens", response_model=list[TokenBeanie])
async def list_tokens_(
    current_user: UserBase = Depends(get_current_user),
    token_lifetime: str | None = None,
):
    cli_configs = await _list_tokens(
        user_id=current_user.id,
        token_lifetime=token_lifetime,
    )
    return cli_configs


@auth_endpoint_router.get("/list", response_model=list[UserBaseUI])
async def list_users(current_user: UserBase = Depends(get_current_user)):
    users = await UserBeanie.find_all().to_list()
    logger.debug(f"Users: {users}")
    users = [user.turn_to_userbaseui() for user in users]
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


@auth_endpoint_router.post("/turn_sysadmin/{user_id}/{is_admin}")
def turn_sysadmin(user_id: str, is_admin: bool, current_user=Depends(get_current_user)):
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
    result = users_collection.update_one({"_id": user_id}, {"$set": {"is_admin": is_admin}})
    if result.modified_count == 1:
        return {"success": True}
    else:
        return {"success": False}


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


@auth_endpoint_router.post("/update_group_in_users/{group_id}")
def update_group_in_users(group_id: str, request: dict, current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")
    # Check if the current user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="Current user is not an admin.")

    if not request:
        raise HTTPException(status_code=400, detail="No request provided")

    if not group_id:
        raise HTTPException(status_code=400, detail="No group_id provided")

    if "users" not in request:
        raise HTTPException(status_code=400, detail="No users provided in request")

    logger.info(f"Request: {request}")

    # Convert user dicts to UserBase objects
    users = [UserBase(**user) for user in request["users"]]

    logger.info(f"Users: {users}")

    # Ensure group_id is an ObjectId
    group_id_obj = (
        ObjectId(group_id["$oid"])
        if isinstance(group_id, dict) and "$oid" in group_id
        else (
            ObjectId(group_id)
            if isinstance(group_id, str)
            else group_id
            if isinstance(group_id, ObjectId)
            else ObjectId(str(group_id))
        )
    )
    logger.info(f"Group ID: {group_id_obj}")

    response = update_group_in_users_helper(group_id_obj, users)
    return response


@auth_endpoint_router.get("/get_group_with_users/{group_id}")
def get_group_with_users(group_id: str, current_user=Depends(get_current_user)):
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

    from depictio.api.v1.db import groups_collection

    group = groups_collection.find_one({"_id": group_id})

    if group:
        # find users in the group by querying the users collection
        from depictio.api.v1.db import users_collection

        users = list(users_collection.find({"groups._id": ObjectId(group_id)}))
        logger.debug(f"users found: {users}")

        if users:
            users = [
                convert_objectid_to_str(
                    UserBase(
                        id=user["_id"],
                        email=user["email"],
                        is_admin=user["is_admin"],
                    ).model_dump(exclude_none=True)
                )
                for user in users
            ]
            group["users"] = users

            # Check if group can be converted to GroupWithUsers
            from depictio.models.models.users import GroupWithUsers

            group_with_users = GroupWithUsers.from_mongo(group)
            return convert_model_to_dict(group_with_users)
        else:
            return convert_model_to_dict(group)
    else:
        raise HTTPException(status_code=404, detail="Group not found")


@auth_endpoint_router.get("/get_group/{group_id}")
async def get_group(group_id: str):
    group = await GroupBeanie.get(group_id)
    if not group:
        return {
            "message": "Group not found",
            "success": False,
        }

    logger.debug(group)
    await group.fetch_all_links()
    logger.debug(group)

    return {
        "message": "Group found",
        "success": True,
        "group": group,
    }


# @auth_endpoint_router.get("/get_all_groups_including_users")
# async def get_all_groups_including_users(current_user=Depends(get_current_user)):
#     if not current_user:
#         raise HTTPException(status_code=401, detail="Current user not found.")
#     if not current_user.is_admin:
#         raise HTTPException(status_code=401, detail="Current user is not an admin.")
#     from depictio.api.v1.db import groups_collection

#     groups = groups_collection.find()

#     # for group in groups leverage the existing function to get users
#     new_groups = []
#     for group in groups:
#         group_id = ObjectId(group["_id"])
#         logger.debug(f"Finding users for group: {group_id}")
#         group_data = await get_group_with_users(group_id, current_user)
#         logger.debug(f"Group data: {group_data}")
#         new_groups.append(group_data)
#     new_groups = [convert_model_to_dict(group) for group in new_groups]

#     # groups = [convert_model_to_dict(group) for group in groups]
#     return new_groups


# @auth_endpoint_router.post("/create_group")
# async def create_group(
#     group: GroupBeanie, current_user=Depends(get_current_user)
# ) -> Dict:
#     if not current_user:
#         raise HTTPException(status_code=401, detail="Current user not found.")
#     # Check if the current user is an admin
#     if not current_user.is_admin:
#         raise HTTPException(status_code=401, detail="Current user is not an admin.")

#     if not group:
#         raise HTTPException(status_code=400, detail="No group provided")

#     if not group.name:
#         raise HTTPException(status_code=400, detail="No group name provided")

#     response = await create_group_helper(group)
#     return response  # The CustomJSONResponse will handle serialization


# # @auth_endpoint_router.post("/create_group")
# # def create_group(group: Group, current_user=Depends(get_current_user)):
# #     if not current_user:
# #         raise HTTPException(status_code=401, detail="Current user not found.")
# #     # Check if the current user is an admin
# #     if not current_user.is_admin:
# #         raise HTTPException(status_code=401, detail="Current user is not an admin.")

# #     if not group:
# #         raise HTTPException(status_code=400, detail="No group provided")

# #     if not group.name:
# #         raise HTTPException(status_code=400, detail="No group name provided")

# #     response = create_group_helper(group)
# #     return response
