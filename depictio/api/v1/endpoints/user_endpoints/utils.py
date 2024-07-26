from datetime import datetime, timedelta
import httpx
import jwt
from depictio.api.v1.configs.config import API_BASE_URL, logger, PRIVATE_KEY, ALGORITHM


# Dummy login function
import bcrypt




def login_user(email):
    return {"logged_in": True, "email": email}


# Dummy logout function
def logout_user():
    return {"logged_in": False, "email": None}


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



# Function to find user by email
def find_user(email):
    # return users_collection.find_one({"email": email})
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_email", params={"email": email})
    if response.status_code == 200:
        return response.json()
    return None



# Function to add a new user
def add_user(email, password):
    hashed_password = hash_password(password)
    user_dict = {"email": email, "password": hashed_password}
    response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/register", json=user_dict)
    if response.status_code == 200:
        logger.info(f"User {email} added successfully.")
    else:
        logger.error(f"Error adding user {email}: {response.text}")
    return response

def edit_password(email, old_password, new_password):
    user = find_user(email)
    if user:
        if verify_password(user["password"], old_password):
            hashed_password = hash_password(new_password)
            user_dict = {"email": email, "new_password": hashed_password}
            logger.info(f"Updating password for user {email} with new password: {new_password}")
            response = httpx.post(f"{API_BASE_URL}/depictio/api/v1/auth/edit_password", params=user_dict)
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
    if user:
        if verify_password(user["password"], password):
            return True
    return False


def create_access_token(data, expires_delta=timedelta(minutes=15)):
    to_encode = data.copy()
    expire = datetime.now() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    created_time = datetime.now().strftime("%b %d, %Y, %I:%M:%S %p")
    return encoded_jwt, created_time

def list_existing_tokens(email):
    user = find_user(email)
    if user:
        return user.get("tokens", [])
    return None