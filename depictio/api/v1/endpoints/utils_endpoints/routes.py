import shutil
from fastapi import APIRouter, Depends

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import workflows_collection, data_collections_collection, runs_collection, files_collection, deltatables_collection, users_collection, dashboards_collection
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.s3 import s3_client

# Define the router
utils_endpoint_router = APIRouter()


@utils_endpoint_router.get("/create_bucket")
async def create_bucket():
    bucket_name = settings.minio.bucket
    # check if the bucket already exists
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return {"message": "Bucket already exists"}
    except Exception as e:
        # Create a new bucket
        s3_client.create_bucket(Bucket=bucket_name)
        return {"message": "Bucket created"}
    else:
        return {"message": "Bucket creation failed"}
    
# TODO - remove this endpoint - only for testing purposes in order to drop the S3 bucket content & the DB collections
@utils_endpoint_router.get("/drop_S3_content")
async def drop_S3_content():
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
async def drop_all_collections():
    workflows_collection.drop()
    data_collections_collection.drop()
    runs_collection.drop()
    files_collection.drop()
    deltatables_collection.drop()
    dashboards_collection.drop()
    return {"message": "All collections dropped"}

@utils_endpoint_router.get("/status")
async def status():
    return {"status": "ok"}