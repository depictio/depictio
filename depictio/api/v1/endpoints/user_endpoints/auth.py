import os
import sys
import bcrypt
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

# from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from datetime import datetime, timedelta

# from werkzeug.security import check_password_hash, generate_password_hash
from depictio.api.v1.endpoints.user_endpoints.core_functions import add_token_to_user, fetch_user_from_email, fetch_user_from_token
from depictio.api.v1.endpoints.user_endpoints.models import TokenRequest, User, Token, TokenData
from depictio.api.v1.models.base import PyObjectId
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.db import users_collection
from depictio.dash.layouts.dashboards_management import convert_objectid_to_str

# users_collection = db.users


auth_endpoint_router = APIRouter()


private_key_file = os.getenv("DEPICTIO_PRIVATE_KEY_FILE", "depictio/private_key.pem")
public_key_file = os.getenv("DEPICTIO_PUBLIC_KEY_FILE", "depictio/public_key.pem")


# Load your private key
with open(private_key_file, "rb") as f:
    PRIVATE_KEY = f.read()
# Load your private key
with open(public_key_file, "rb") as f:
    PUBLIC_KEY = f.read()

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 360 * 3600

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/api/v1/auth/token")


# Helper function to verify password (modify this to hash verification in production)
def verify_password(plain_password, hashed_password):
    # return check_password_hash(
    #     hashed_password,
    #     plain_password,
    # )
    return plain_password == hashed_password


def register_user(username: str, email: str, password: str):
    user = users_collection.find_one({"username": username})
    if user:
        raise HTTPException(status_code=400, detail="Username already registered")
    user = users_collection.find_one({"email": email})
    if user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = password

    user = {
        "username": username,
        "email": email,
        "password": hashed_password,
    }
    users_collection.insert_one(user)
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    logger.info("\n\n\n")
    logger.info("create_access_token")
    logger.info(data)
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    logger.info(encoded_jwt)
    return encoded_jwt


# Authentication function
def authenticate_user(username: str, password: str):
    user = users_collection.find_one({"username": username})
    if user and verify_password(password, user.get("password")):
        return user
    return None


# FIXME: remove this - only for testing purposes
# @auth_endpoint_router.post("/create_user")
# async def create_user():


#     # delete the user
#     users_collection.drop()

#     user = {
#         "username": "cezanne",
#         "password": "paul",
#         "email": "paul.cezanne@embl.de",
#     }

#     users_collection.insert_one(user)

#     return {"message": "User created"}


@auth_endpoint_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    logger.info("\n\n\n")
    logger.info("login_for_access_token")
    logger.info(form_data.username)
    logger.info(user)

    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    user_id = str(user["_id"])  # Get the user ID from the database entry
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_id},  # Use user_id as the subject of the token
        expires_delta=access_token_expires,
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        user_id=PyObjectId(user_id),  # Ensure this is a PyObjectId instance
        expires_in=int(access_token_expires.total_seconds()),
        scope="read",
    )


# @auth_endpoint_router.get("/fetch_user/from_token", response_model=User)
# async def fetch_user_from_token(token: str = Depends(oauth2_scheme)) -> User:
#     logger.info("\n\n\n")
#     logger.info("fetch_user_from_token")
#     payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
#     user_id = payload.get("sub")
#     if user_id is None:
#         logger.info("Token is invalid or expired.")
#         sys.exit(code=1)
#     # Fetch user from the database or wherever it is stored
#     user_document = users_collection.find_one({"_id": ObjectId(str(user_id))})
#     if not user_document:
#         raise HTTPException(status_code=404, detail="User not found")
#     user = User(
#         user_id=user_document["_id"],
#         username=user_document["username"],
#         email=user_document["email"],
#     )
#     logger.info(user)
#     return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])

        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=PyObjectId(user_id))
        return token_data

    except JWTError as e:
        raise credentials_exception


@auth_endpoint_router.post("/register", response_model=User)
async def create_user(user: User) -> User:
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
async def api_fetch_user(email: str):
    user = fetch_user_from_email(email)
    if user:
        return user
    else:
        raise HTTPException(status_code=404, detail="User not found")
    
@auth_endpoint_router.post("/fetch_user/from_token", response_model=User)
async def api_fetch_user_from_token(token: str):
    user = fetch_user_from_token(token)
    if user:
        return user
    else:
        raise HTTPException(status_code=404, detail="User not found")

# @auth_endpoint_router.get("/fetch_user/from_email")
# async def fetch_user(email: str):
#     user = users_collection.find_one({"email": email})
#     logger.info(f"Fetching user with email: {email} : {user}")
#     # user = User.from_mongo(user)
#     logger.info("Before")
#     logger.info(user)
#     user = User.from_mongo(user)
#     logger.info("After")
#     logger.info(user)

#     if user:
#         return user
#     else:
#         raise HTTPException(status_code=404, detail="User not found")


@auth_endpoint_router.post("/edit_password", response_model=User)
async def edit_password(email: str, new_password: str) -> User:
    user_data = users_collection.find_one({"email": email})
    if user_data:
        logger.info("Before")
        logger.info(user_data)

        user = User.from_mongo(user_data)

        if user.password == new_password:
            raise HTTPException(status_code=400, detail="New password cannot be the same as the old password")

        user.password = new_password
        logger.info("After")
        logger.info(user)

        update_data = user.mongo()
        logger.info(f"Update data: {update_data}")

        result = users_collection.update_one({"_id": user.id}, {"$set": update_data})

        # Log the update result
        logger.info(f"Update result: {result.modified_count} document(s) updated")
        logger.info(f"Show updated user from database: {users_collection.find_one({'email' : email})}")

        if result.modified_count == 1:
            return user
        else:
            raise HTTPException(status_code=500, detail="Failed to update password")
    else:
        raise HTTPException(status_code=404, detail="User not found")





@auth_endpoint_router.post("/add_token")
async def add_token(request: dict):
    user = request["user"]
    token = request["token"]
    logger.info(f"Request: {request}")
    logger.info(f"User: {user}")
    logger.info(f"Token: {token}")

    result = add_token_to_user(user, token)
    if not result["success"]:
        raise HTTPException(status_code=500, detail="Failed to add token")

    return result



# @auth_endpoint_router.post("/add_token")
# async def add_token(request: dict):
#     user = request["user"]
#     token = request["token"]
#     logger.info(f"Request: {request}")
#     logger.info(f"User: {user}")
#     logger.info(f"Token: {token}")

#     # Ensure _id is an ObjectId
#     user_id = user["_id"]
#     if isinstance(user_id, str):
#         user_id = ObjectId(user_id)
#     elif isinstance(user_id, dict) and "$oid" in user_id:
#         user_id = ObjectId(user_id["$oid"])

#     # Log the _id and the query structure
#     logger.info(f"User _id (ObjectId): {user_id}")
#     query = {"_id": user_id}
#     update = {"$push": {"tokens": token}}
#     logger.info(f"Query: {query}")
#     logger.info(f"Update: {update}")

#     # Insert in the user collection
#     result = users_collection.update_one(query, update)
#     logger.info(f"Update result: {result.modified_count} document(s) updated")

#     # Return success status
#     return {"success": result.modified_count > 0}

@auth_endpoint_router.post("/delete_token")
async def delete_token(request: dict):
    logger.info(f"Request: {request}") 
    user = request["user"]
    token_id = request["token_id"]
    user_id = user["id"]
    logger.info(f"User: {user}")
    logger.info(f"Token ID: {token_id}")

    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.info(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}
    
    # Get existing tokens from the user and remove the token to be deleted
    user_data = users_collection.find_one(query)
    tokens = user_data.get("tokens", [])
    logger.info(f"Tokens: {tokens}")
    tokens = [e for e in tokens if str(e["_id"]) != str(token_id)]
    logger.info(f"Tokens after deletion: {tokens}")

    # Update the user with the new tokens
    update = {"$set": {"tokens": tokens}}
    logger.info(f"Query: {query}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.info(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": result.modified_count > 0}

@auth_endpoint_router.post("/generate_agent_config")
def generate_agent_config(request: dict):
    logger.info(f"Request: {request}")
    user = request["user"]
    
    # Keep only email and is_admin fields from user
    user = {
        "email": user["email"],
        "is_admin": user["is_admin"],
    }

    token = request["token"]

    # Add token to user
    user["token"] = token

    # Depictio API config
    from depictio.api.v1.configs.config import API_BASE_URL
    depictio_agent_config = {
        "api_base_url": API_BASE_URL,
        "user": user,
    }
    return depictio_agent_config
    
