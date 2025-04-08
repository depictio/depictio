import secrets
from fastapi.concurrency import asynccontextmanager
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import Document, init_beanie, PydanticObjectId
from pydantic import BaseModel, Field, EmailStr, field_serializer
from datetime import datetime, timedelta
from typing import Any, Optional, List, Annotated
import jwt
from passlib.context import CryptContext
from bson import ObjectId
import logging
from rich.logging import RichHandler

# Create a custom JSON response class for proper ObjectId serialization
from pydantic_core import core_schema
from pydantic.json_schema import JsonSchemaValue

# Configure logger to use RichHandler
logging.basicConfig(
    level="INFO", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logging.getLogger("passlib").setLevel(logging.ERROR)
logger = logging.getLogger("rich")


# Configuration
JWT_SECRET = "your-secret-key-change-this-in-production"
JWT_ALGORITHM = "HS256"
MONGODB_URL = "mongodb://localhost:27017"
DB_NAME = "beanie_test_db"


# Password context for hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Define a custom type adapter for PydanticObjectId
def objectid_serializer(oid: PydanticObjectId | ObjectId) -> str:
    return str(oid)


# Updated JSON Response class that utilizes the serializer
class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        # Convert PydanticObjectId and ObjectId to str when serializing
        return super().render(
            jsonable_encoder(
                content,
                custom_encoder={
                    PydanticObjectId: objectid_serializer,
                    ObjectId: objectid_serializer,
                },
            )
        )



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database, etc.
    await init_db()
    yield
    # Shutdown: add cleanup tasks if needed
    # await shutdown_db(wipe=True)


# Initialize FastAPI
app = FastAPI(
    title="Token Management API",
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class Test(Document):
    name: str
    test_field: Optional[str] = None

    class Settings:
        name = "test"
        use_revision = True  # Track document revisions


# Document models
class User(Document):
    email: EmailStr
    hashed_password: str
    full_name: Optional[str] = None
    disabled: bool = False

    class Settings:
        name = "users"  # Collection name
        use_revision = True  # Track document revisions

    # Define which fields to exclude when returning the model
    model_config = {"exclude": {"hashed_password"}, "arbitrary_types_allowed": True}

    # Field serializer for Pydantic v2
    @field_serializer("id")
    def serialize_id(self, id: PydanticObjectId) -> str:
        return str(id)

    @classmethod
    def get_hashed_password(cls, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.hashed_password)


class Token(Document):
    user_id: PydanticObjectId  # Reference to User's ObjectId
    access_token: str
    token_type: str = "bearer"
    token_lifetime: str = "short-lived"
    expire_datetime: datetime
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model_config = {"arbitrary_types_allowed": True}

    class Settings:
        name = "tokens"  # Collection name
        use_revision = True  # Track document revisions

    # Field serializers for Pydantic v2
    @field_serializer("id")
    def serialize_id(self, id: PydanticObjectId) -> str:
        return str(id)

    @field_serializer("user_id")
    def serialize_user_id(self, user_id: PydanticObjectId) -> str:
        return str(user_id)

    # For consistent responses in the API
    def to_response_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": int(
                (self.expire_datetime - datetime.utcnow()).total_seconds()
            ),
            "expires_at": self.expire_datetime,
            "created_at": self.created_at,
        }


# Request models (still needed)
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class LoginForm(BaseModel):
    email: EmailStr
    password: str


# Database initialization
async def init_db():
    client = AsyncIOMotorClient(MONGODB_URL)
    # drop existing database for testing
    # client.drop_database(DB_NAME)
    await init_beanie(database=client[DB_NAME], document_models=[User, Token, Test])

async def shutdown_db(wipe: bool = False):
    # Close the database connection
    client = AsyncIOMotorClient(MONGODB_URL)
    
    # Only wipe the database if explicitly requested
    if wipe:
        client.drop_database(DB_NAME)
        logger.info(f"Database {DB_NAME} dropped.")
    
    client.close()
    logger.info("Database connection closed.")


# User authentication utilities
def create_jwt_token(
    user_id: PydanticObjectId, expires_delta: timedelta = timedelta(minutes=30)
):
    expire = datetime.utcnow() + expires_delta
    to_encode = {"sub": str(user_id), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode JWT
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception

        try:
            # Convert string to ObjectId
            user_id = PydanticObjectId(user_id_str)
        except:
            raise credentials_exception

        # Check if token exists in database
        db_token = await Token.find_one({"access_token": token, "user_id": user_id})
        if not db_token:
            raise credentials_exception

        # Check if token is expired
        if db_token.expire_datetime < datetime.utcnow():
            # Clean up expired token
            await db_token.delete()
            raise credentials_exception

    except jwt.PyJWTError:
        raise credentials_exception

    # Get user from database
    user = await User.get(user_id)
    if user is None:
        raise credentials_exception

    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user


# Endpoint to create a user
@app.post("/users")
async def create_user(user_data: UserCreate):
    # Check if user exists
    existing_user = await User.find_one({"email": user_data.email})
    logger.info(f"User found: {existing_user}")
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new user
    new_user = User(
        email=user_data.email,
        hashed_password=User.get_hashed_password(user_data.password),
        full_name=user_data.full_name,
    )
    logger.info(f"Creating new user: {new_user}")
    await new_user.insert()

    test = Test(name="test")
    await test.insert()
    logger.info(f"Test document created: {test}")




    # Return the user directly (hashed_password will be excluded via Config)
    return new_user


# Login endpoint
@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Find user by email
    user = await User.find_one({"email": form_data.username})
    logger.info(f"User found: {user}")
    if not user or not user.verify_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate token with 30 minutes expiration
    expires_delta = timedelta(minutes=30)
    access_token = create_jwt_token(user.id, expires_delta)

    # Store token in database
    token = Token(
        user_id=user.id,
        access_token=access_token,
        expire_datetime=datetime.utcnow() + expires_delta,
    )
    logger.info(f"Token created: {token}")
    await token.insert()

    # Return the token response directly using to_response_dict
    return token.to_response_dict()


# Protected endpoint example
@app.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    # Return the user object directly
    logger.info(f"Current user: {current_user}")

    test = await Test.find_one()
    if test:
        logger.info(f"Test document found: {test}")

    return current_user


# Endpoint to get user by ID
@app.get("/users/{user_id}")
async def get_user(user_id: PydanticObjectId):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Get user's tokens
@app.get("/tokens")
async def get_user_tokens(current_user: User = Depends(get_current_user)):
    tokens = await Token.find({"user_id": current_user.id}).to_list()
    logger.info(f"Tokens for user {current_user.email}: {tokens}")

    # Return tokens directly - they'll be serialized with PydanticObjectId as strings
    return tokens


# Logout endpoint (invalidate token)
@app.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user), token: str = Depends(oauth2_scheme)
):
    # Find and delete token
    db_token = await Token.find_one({"access_token": token})
    if db_token:
        await db_token.delete()
    return {"detail": "Successfully logged out"}


# Token refresh endpoint
@app.post("/refresh")
async def refresh_token(current_user: User = Depends(get_current_user)):
    # Generate new token with 30 minutes expiration
    expires_delta = timedelta(minutes=30)
    new_access_token = create_jwt_token(current_user.id, expires_delta)

    # Store new token in database
    token = Token(
        user_id=current_user.id,
        access_token=new_access_token,
        expire_datetime=datetime.utcnow() + expires_delta,
    )
    await token.insert()

    # Return the new token response directly
    return token.to_response_dict()


# Revoke specific token by ID
@app.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: PydanticObjectId, current_user: User = Depends(get_current_user)
):
    # Ensure token belongs to current user
    token = await Token.find_one({"_id": token_id, "user_id": current_user.id})
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found"
        )

    await token.delete()
    return None


# Utility to clean up expired tokens (could be called periodically)
@app.post("/admin/cleanup-tokens", status_code=status.HTTP_204_NO_CONTENT)
async def cleanup_expired_tokens(current_user: User = Depends(get_current_user)):
    # Only allow this for admins in a real application
    # Here we're just using the authenticated user for simplicity

    # Find and delete all expired tokens
    now = datetime.utcnow()
    expired_tokens = await Token.find({"expire_datetime": {"$lt": now}}).to_list()
    for token in expired_tokens:
        await token.delete()

    return None


# Main function to run the app
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
