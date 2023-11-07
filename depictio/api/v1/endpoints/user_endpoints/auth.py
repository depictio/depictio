from fastapi import APIRouter, FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel
from datetime import datetime, timedelta

from depictio.api.v1.configs.models import TokenData, Token

auth_endpoint_router = APIRouter()

# Load your private key
with open('/Users/tweber/Gits/depictio/dev/token/public_key.pem', 'rb') as f:
    PUBLIC_KEY = f.read()

ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 360

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PUBLIC_KEY, algorithm=ALGORITHM)
    print(encoded_jwt)
    return encoded_jwt

@auth_endpoint_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    # Here you would verify username and password from form_data
    # For example:
    # user = authenticate_user(fake_users_db, form_data.username, form_data.password)
    # if not user:
    #     raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    # For simplicity, we're skipping the actual user authentication
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": form_data.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(token: str = Depends(oauth2_scheme)):
    print("\n\n\n")
    print("get_current_user")
    print(token)
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    print(credentials_exception)
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
        print(payload)
        username: str = payload.get("username")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
        print(token_data)
    except JWTError as e:
        print(f"JWT Error: {e}")
        raise credentials_exception
    print(token_data)
    return token_data

@auth_endpoint_router.get("/users/me")
async def read_users_me(current_user: TokenData = Depends(get_current_user)):
    return {"username": current_user.username}


