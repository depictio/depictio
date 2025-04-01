from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import workflows_collection, data_collections_collection, runs_collection, files_collection, deltatables_collection, dashboards_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.configs.logging import logger

# Define the router
utils_endpoint_router = APIRouter()

@utils_endpoint_router.get("/create_bucket")
async def create_bucket_endpoint(current_user=Depends(get_current_user)):
    if not current_user:
        logger.error("Current user not found.")
        raise HTTPException(status_code=401, detail="Current user not found.")


    response = create_bucket(current_user)

    if response.status_code == 200:
        logger.info(response.detail)
        return response
    else:
        logger.error(response.detail)
        raise HTTPException(status_code=response.status_code, detail=response.detail)



# TODO - remove this endpoint - only for testing purposes in order to drop the S3 bucket content & the DB collections
@utils_endpoint_router.get("/drop_S3_content")
async def drop_S3_content(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    bucket_name = settings.minio.bucket

    # List and delete all objects in the bucket
    objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)
    while objects_to_delete.get("Contents"):
        print(f"Deleting {len(objects_to_delete['Contents'])} objects...")
        delete_keys = [{"Key": obj["Key"]} for obj in objects_to_delete["Contents"]]
        s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_keys})
        objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)

    print("All objects deleted from the bucket.")

    # FIXME: remove this - only for testing purposes
    # Delete directory content directly from the file system
    # shutil.rmtree(settings.minio.data_dir)

    return {"message": "S3 bucket content dropped"}


@utils_endpoint_router.get("/drop_all_collections")
async def drop_all_collections(current_user=Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    deltatables_collection.drop()
    dashboards_collection.drop()
    return {"message": "All collections dropped"}


@utils_endpoint_router.get("/status")
async def status(current_user=Depends(get_current_user)):
    logger.info("Checking server status...")
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    logger.info("Server is online.")

    return {"status": "online", "version": "v0.0.4"}

from depictio_models.models.users import User
from depictio_models.models.base import PyObjectId
from depictio.api.v1.db import users_collection
@utils_endpoint_router.get("/test_objectid", response_model=User)
async def test_objectid(id: PyObjectId):

    logger.info(f"Received ObjectId: {id} of type {type(id)}")
    # Perform any operations you need with the ObjectId
    # For example, you can fetch a user from the database using this ObjectId
    user = users_collection.find_one({"_id": str(id)})
    # drop email from the user object
    logger.info(f"User before dropping email: {user}")
    user.pop("email", None)
    logger.info(f"User found: {user}")

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user