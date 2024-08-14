from datetime import datetime, timedelta
import httpx
import jwt
import bcrypt

from depictio.api.v1.configs.config import API_BASE_URL, logger, PRIVATE_KEY, ALGORITHM
from depictio.api.v1.endpoints.user_endpoints.core_functions import add_token_to_user, fetch_user_from_email
from depictio.api.v1.endpoints.user_endpoints.models import Token
from depictio.api.v1.models.base import convert_objectid_to_str


def login_user(email):
    return {"logged_in": True, "email": email}


# Dummy logout function
def logout_user():
    return {"logged_in": False, "access_token": None}


# Check if user is logged in
def is_user_logged_in(session_data):
    return session_data.get("logged_in", False)


def hash_password(password: str) -> str:
    # Generate a salt
    salt = bcrypt.gensalt()
    # Hash the password with the salt
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    # Return the hashed password
    return hashed.decode("utf-8")


def verify_password(stored_hash: str, password: str) -> bool:
    logger.info(f"Stored hash: {stored_hash}")
    logger.info(f"Password to verify: {password}")
    # Verify the password against the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))


def find_user(email, return_tokens=False):
    # Call the core function directly
    user_data = fetch_user_from_email(email, return_tokens)
    if user_data:
        logger.info(f"Found user data: {user_data}")
        return user_data
    return None


# Function to add a new user
def add_user(email, password, is_admin=False):
    hashed_password = hash_password(password)
    user_dict = {"email": email, "password": hashed_password, "is_admin": is_admin}
    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/register", json=user_dict)
    if response.status_code == 200:
        logger.info(f"User {email} added successfully.")
    else:
        logger.error(f"Error adding user {email}: {response.text}")
    return response


def edit_password(email, old_password, new_password, headers):
    logger.info(f"Editing password for user {email}.")
    logger.info(f"Old password: {old_password}")
    logger.info(f"New password: {new_password}")
    user = find_user(email)
    user = convert_objectid_to_str(user.dict())
    if user:
        if verify_password(user["password"], old_password):
            hashed_password = hash_password(new_password)
            user_dict = {"new_password": hashed_password, "old_password": old_password}
            logger.info(f"Updating password for user {email} with new password: {new_password}")
            response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/edit_password", json=user_dict, headers=headers)
            if response.status_code == 200:
                logger.info(f"Password for user {email} updated successfully.")
            else:
                logger.error(f"Error updating password for user {email}: {response.text}")
            return response
        else:
            logger.error(f"Old password for user {email} is incorrect.")
            return {"error": "Old password is incorrect."}
    else:
        logger.error(f"User {email} not found.")
        return {"error": "User not found."}


def check_password(email, password):
    user = find_user(email)
    logger.info(f"User: {user}")
    if user:
        if verify_password(user.password, password):
            return True
    return False


def create_access_token(token_data):
    token_lifetime = token_data["token_lifetime"]

    if token_lifetime == "short-lived":
        expires_delta = timedelta(hours=12)
    elif token_lifetime == "long-lived":
        expires_delta = timedelta(days=365)
    else:
        raise ValueError("Invalid token type. Must be 'short-lived' or 'long-lived'.")

    to_encode = token_data.copy()
    expire = datetime.now() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire


def add_token(token_data: dict) -> dict:
    email = token_data["sub"]
    logger.info(f"Adding token for user {email}.")
    logger.info(f"Token: {token_data}")
    token, expire = create_access_token(token_data)
    token_data = {"access_token": token, "expire_datetime": expire.strftime("%Y-%m-%d %H:%M:%S"), "name": token_data["name"], "token_lifetime": token_data["token_lifetime"]}

    logger.info(f"Adding token for user {email}.")
    user = find_user(email)
    logger.info(f"User: {user}")
    if user:
        # Check if the token already exists based on the name
        tokens = list_existing_tokens(email)
        logger.info(f"Tokens: {tokens}")
        for t in tokens:
            if t["name"] == token_data["name"]:
                logger.error(f"Token with name {token_data['name']} already exists for user {email}.")
                return None

        logger.info(f"Adding token for user {email}.")
        token = Token(**token_data)
        logger.info(f"Token: {token}")
        logger.info(f"Token.mongo(): {token.mongo()}")

        result = add_token_to_user(user, token.mongo())
        logger.info(f"Result: {result}")
        if result["success"]:
            logger.info(f"Token added for user {email}.")
        else:
            logger.error(f"Error adding token for user {email}")
        # return token
    return token


def delete_token(email, token_id):
    logger.info(f"Deleting token for user {email}.")
    user = find_user(email)
    user = convert_objectid_to_str(user.dict())
    logger.info(f"User: {user}")
    if user:
        logger.info(f"Deleting token for user {email}.")
        request_body = {"user": user, "token_id": token_id}
        response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/delete_token", json=request_body)
        if response.status_code == 200:
            logger.info(f"Token deleted for user {email}.")
        else:
            logger.error(f"Error deleting token for user {email}: {response.text}")
        return response
    return None


def fetch_user_from_token(token):
    logger.info(f"Fetching user from token.")
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_token", params={"token": token})
    if response.status_code == 200:
        user_data = response.json()
        logger.info(f"Raw user data from response: {user_data}")
        return user_data
    return None


def list_existing_tokens(email):
    logger.info(f"Listing tokens for user {email}.")
    user = find_user(email, return_tokens=True)
    logger.info(f"User: {user}")
    if user:
        user = user.dict()
        return user.get("tokens", [])
    return None


def generate_agent_config(email, token, current_token):
    user = find_user(email)
    user = convert_objectid_to_str(user.dict())
    logger.info(f"User: {user}")

    token = convert_objectid_to_str(token)
    token = {"access_token": token["access_token"], "expire_datetime": token["expire_datetime"], "name": token["name"]}

    logger.info(f"Generating agent config for user {user}.")
    result = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/generate_agent_config", json={"user": user, "token": token}, headers={"Authorization": f"Bearer {current_token}"})
    logger.info(f"Result: {result.json()}")
    if result.status_code == 200:
        logger.info(f"Agent config generated for user {user}.")
        return result.json()
    else:
        logger.error(f"Error generating agent config for user {user}: {result.text}")
