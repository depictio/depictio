from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    runs_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.endpoints.utils_endpoints.core_functions import create_bucket
from depictio.api.v1.endpoints.utils_endpoints.process_data_collections import (
    process_initial_data_collections,
)
from depictio.api.v1.s3 import s3_client
from depictio.version import get_version

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
        logger.info(f"Deleting {len(objects_to_delete['Contents'])} objects...")
        delete_keys = [{"Key": obj["Key"]} for obj in objects_to_delete["Contents"]]
        s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_keys})
        objects_to_delete = s3_client.list_objects_v2(Bucket=bucket_name)

    logger.info("All objects deleted from the bucket.")

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
async def status():
    """
    Check if the server is online.
    This endpoint is public and does not require authentication.
    """
    logger.info("Checking server status...")
    logger.info("Server is online.")

    return {"status": "online", "version": get_version()}


@utils_endpoint_router.post("/process_initial_data_collections")
async def process_initial_data_collections_endpoint(
    background_tasks: BackgroundTasks, current_user=Depends(get_current_user)
):
    """
    Process the initial data collections for the first project.
    This endpoint should be called after the API is fully started.

    The processing is done in the background to avoid blocking the request.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Current user not found.")

    # Check if the user is an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=401, detail="User is not an admin.")

    # Add the task to the background tasks
    background_tasks.add_task(process_initial_data_collections)

    return {
        "message": "Processing initial data collections in the background. Check the logs for progress."
    }
