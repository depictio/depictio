
from bson import ObjectId
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import User


def add_token_to_user(user, token):
    from depictio.api.v1.db import users_collection

    logger.info(f"Adding token to user: {user}")
    # Ensure _id is an ObjectId
    # user_id = user["_id"]
    user_id = user.id
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    elif isinstance(user_id, dict) and "$oid" in user_id:
        user_id = ObjectId(user_id["$oid"])

    # Log the _id and the query structure
    logger.info(f"User _id (ObjectId): {user_id}")
    query = {"_id": user_id}
    update = {"$push": {"tokens": token}}
    logger.info(f"Query: {query}")
    logger.info(f"Update: {update}")

    # Insert in the user collection
    result = users_collection.update_one(query, update)
    logger.info(f"Update result: {result.modified_count} document(s) updated")

    # Return success status
    return {"success": result.modified_count > 0}

def fetch_user_from_email(email: str, return_tokens: bool = False) -> User:
    from depictio.api.v1.db import users_collection  # Move import inside the function

    # Find the user in the database and exclude the tokens field
    if return_tokens:
        user = users_collection.find_one({"email": email})
    else:
        user = users_collection.find_one({"email": email}, {"tokens": 0})
    logger.info(f"Fetching user with email: {email} : {user}")
    user = User.from_mongo(user)
    logger.info("After conversion to User model")
    logger.info(user)

    if user:
        return user
    else:
        return None