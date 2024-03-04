import os
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, FastAPI, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel, ValidationError
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
from depictio.api.v1.endpoints.user_endpoints.models import User, Token, TokenData
from depictio.api.v1.models.base import PyObjectId


from depictio.api.v1.db import db

users_collection = db.users


auth_endpoint_router = APIRouter()


# Load your private key
with open("depictio/private_key.pem", "rb") as f:
    PRIVATE_KEY = f.read()
# Load your private key
with open("depictio/public_key.pem", "rb") as f:
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
    print("\n\n\n")
    print("create_access_token")
    print(data)
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    print(encoded_jwt)
    return encoded_jwt


# Authentication function
def authenticate_user(username: str, password: str):
    user = users_collection.find_one({"username": username})
    if user and verify_password(password, user.get("password")):
        return user
    return None



@auth_endpoint_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    print("\n\n\n")
    print("login_for_access_token")
    print(form_data.username)
    print(user)

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

    # token_data = {
    #     "access_token": access_token,
    #     "token_type": "bearer",
    #     "user_id": user["_id"],
    #     "expires_in": int(access_token_expires.total_seconds()),
    #     "scope": "read",
    # }
    # print(token_data)

    # json_compatible_data = jsonable_encoder(token_data, custom_encoder={ObjectId: str})
    # print("\n\n\n")
    # print("json_compatible_data")
    # print(json_compatible_data)

    # return json_compatible_data


@auth_endpoint_router.get("/fetch_user", response_model=User)
async def fetch_user_from_id(user_id_str: str) -> User:
    user_document = users_collection.find_one({"_id": ObjectId(user_id_str)})
    if not user_document:
        raise HTTPException(status_code=404, detail="User not found")
    return User(
        user_id=user_document["_id"],
        username=user_document["username"],
        email=user_document["email"],
    )


# def fetch_user_from_id(user_id_str: str) -> User:
#     user_document = users_collection.find_one({"_id": ObjectId(user_id_str)})
#     if not user_document:
#         raise HTTPException(status_code=404, detail="User not found")
#     return User(
#         user_id=user_document["_id"],
#         username=user_document["username"],
#         email=user_document["email"],
#     )


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


@auth_endpoint_router.get("/users/me", response_model=User)
async def read_users_me(current_user: TokenData = Depends(get_current_user)):
    return fetch_user_from_id(str(current_user.user_id))
