from datetime import datetime, timedelta
from passlib.context import CryptContext
from passlib.hash import bcrypt

from jose import JWTError, jwt
from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo import MongoClient
from bson import ObjectId
from json import JSONEncoder

from pydantic import BaseModel, Field, SecretStr, root_validator
from typing import Optional
from src import config


app = FastAPI()


settings = config.Settings.from_yaml("config.yaml")

SECRET_KEY = "mysecretkey"
# SECRET_KEY = settings.user_secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


mongo_client = MongoClient(settings.mongo_url)
mongo_db = mongo_client[settings.mongo_db]


class ObjectIdEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return JSONEncoder.default(self, o)


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    username: str = Field(..., max_length=32)
    email: str = Field(..., regex=r"^[\w\.-]+@[\w\.-]+\.\w{2,}$")
    password_hash: str = Field(..., min_length=60, max_length=60, alias="password")

    class Config:
        allow_population_by_field_name = True
        json_encoders = {ObjectId: ObjectIdEncoder}
        schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "johndoe@example.com",
                "password_hash": bcrypt.hash("secret"),
            }
        }
        arbitrary_types_allowed = True

    def dict(self, *args, **kwargs):
        return super().dict(*args, **kwargs, exclude={"password_hash"})


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


# Hash passwords using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Generate a random secret key
def generate_secret_key():
    return pwd_context.hash(SECRET_KEY)


# Verify a password hash
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


# Hash a password
def hash_password(password):
    return pwd_context.hash(password)


# Create access token
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Verify access token
def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Authenticate user
def authenticate_user(username: str, password: str):
    # Check if username and password match a user in the database
    user = get_user_by_username(username)
    if not user:
        return False
    if not verify_password(password, user["password_hash"]):
        return False
    return user


# Get user by username
def get_user_by_username(username: str):
    # Query the database for the user with the specified username
    user = mongo_db.users.find_one({"username": username})
    if user:
        user["_id"] = str(user["_id"])
    return user


# Assume you have a function that retrieves the current user from the request headers
def get_current_user(api_key: str = Header(...)):
    user = authenticate_user(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


def get_user_by_id(user_id: str) -> Optional[User]:
    user_data = mongo_db.users.find_one({"username": str(user_id)})
    if user_data:
        # Check if user_data has the expected keys
        expected_keys = {"_id", "username", "password_hash"}
        if not expected_keys.issubset(user_data.keys()):
            raise ValueError(f"Unexpected keys in user_data: {user_data.keys()}")
        user_data_jsonify = jsonable_encoder(user_data, custom_encoder={ObjectId: str})
        user = User.parse_obj(user_data_jsonify)
        return user
    return None


# Create a new user
def create_user(user: User, db):
    # Hash the user's password
    password_hash = hash_password(user.password)
    # Insert the new user into the database
    result = db.users.insert_one(
        {
            "username": user.username,
            "email": user.email,
            "password_hash": password_hash,
        }
    )
    # Return the new user object with the generated ID
    new_user = {
        "_id": str(result.inserted_id),
        "username": user.username,
        "email": user.email,
    }
    return new_user


def seed_initial_admin_user(mongo_db):
    # Create the users collection
    users_collection = mongo_db["users"]

    # Check if there are any existing users
    if users_collection.count_documents({}) == 0:
        # If there are no users, create a new admin user
        password = "adminpassword"
        admin_user = User(username="admin", email="admin@example.com", password=password, is_admin=True)
        create_user(admin_user, mongo_db)
        print("Created initial admin user")


@app.post("/users", response_model=User)
async def create_user_api(user: User, current_user: User = Depends(get_current_user)):
    # Check if the user is already authenticated
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Check if the user has admin privileges
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    # Check if the username is already taken
    existing_user = get_user_by_username(user.username)
    if existing_user is not None:
        raise HTTPException(status_code=400, detail="Username already taken")
    # Create the new user in the database
    new_user = create_user(user, mongo_db)
    return new_user


@app.get("/users")
async def get_users(token: str = Depends(oauth2_scheme)):
    # Verify the token and get the user ID from the "sub" claim
    print(token)
    payload = decode_access_token(token)
    print(payload)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid token")
    # Get the user object from the database using the user ID
    user = get_user_by_id(user_id)
    print(user)
    if user is None:
        raise HTTPException(status_code=400, detail="User not found")
    users = list(mongo_db.users.find({}))
    return jsonable_encoder(users, custom_encoder={ObjectId: str})


@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Check if the user is authenticated
    # print(form_data.username, form_data.password)
    user = authenticate_user(form_data.username, form_data.password)
    # print(user)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    # Create an access token for the user
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user["username"]}, expires_delta=access_token_expires)
    # Return the access token
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/protected")
async def protected_route(token: str = Depends(oauth2_scheme)):
    # print(token)
    # Verify the token and get the user ID from the "sub" claim
    payload = decode_access_token(token)
    # print(payload)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid token")
    # Get the user object from the database using the user ID
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="User not found")
    return {"user": user}
