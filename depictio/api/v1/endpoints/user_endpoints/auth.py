import sys
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

# from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from datetime import datetime, timedelta

# from werkzeug.security import check_password_hash, generate_password_hash
from depictio.api.v1.endpoints.user_endpoints.models import User, Token, TokenData
from depictio.api.v1.models.base import PyObjectId
from depictio.api.v1.configs.config import logger, PRIVATE_KEY, PUBLIC_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

from depictio.api.v1.db import db

users_collection = db.users


auth_endpoint_router = APIRouter()


# # Load your private key
# with open("depictio/private_key.pem", "rb") as f:
#     PRIVATE_KEY = f.read()
# # Load your private key
# with open("depictio/public_key.pem", "rb") as f:
#     PUBLIC_KEY = f.read()

# ALGORITHM = "RS256"
# ACCESS_TOKEN_EXPIRE_MINUTES = 360 * 3600

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
@auth_endpoint_router.post("/create_user")
async def create_user():


    # delete the user
    users_collection.drop()

    user = {
        "username": "cezanne",
        "password": "paul",
        "email": "paul.cezanne@embl.de",
    }

    users_collection.insert_one(user)

    return {"message": "User created"}



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


@auth_endpoint_router.get("/fetch_user", response_model=User)
async def fetch_user_from_token(token: str = Depends(oauth2_scheme)) -> User:
    logger.info("\n\n\n")
    logger.info("fetch_user_from_token")
    logger.info(token)
    logger.info(PUBLIC_KEY)
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("sub")
    logger.info(ObjectId(str(user_id)))
    logger.info(user_id)
    if user_id is None:
        logger.info("Token is invalid or expired.")
        sys.exit(code=1)
    # Fetch user from the database or wherever it is stored
    user_document = users_collection.find_one({"_id": ObjectId(str(user_id))})
    logger.info(user_document)
    if not user_document:
        raise HTTPException(status_code=404, detail="User not found")
    user = User(
        user_id=user_document["_id"],
        username=user_document["username"],
        email=user_document["email"],
    )
    logger.info(user)
    return user


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
