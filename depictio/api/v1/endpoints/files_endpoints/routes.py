import mimetypes
from urllib.parse import unquote

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import db
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.api.v1.s3 import s3_client
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.files import File

files_endpoint_router = APIRouter()

files_collection = db[settings.mongodb.collections.files_collection]


class UpsertFilesBatchRequest(BaseModel):
    files: list[File]
    update: bool = False


@files_endpoint_router.post("/upsert_batch")
async def create_file(payload: UpsertFilesBatchRequest, current_user=Depends(get_current_user)):
    """
    Create one or more files in the database using bulk upsert.

    Args:
        files (List[dict]): List of file dictionaries to process.
        update (bool, optional): If True, update an existing file; otherwise, insert only if not present.
        current_user: The current user (dependency injected).

    Returns:
        A dict summarizing the operation (inserted/updated counts).
    """
    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    operations = []
    for file in payload.files:
        file_obj = file
        file_data = file.mongo()
        # convert data_collection_id to PyObjectId
        file_data["data_collection_id"] = ObjectId(file_data["data_collection_id"])

        # Use a different update operator based on the `update` flag.
        if payload.update:
            # $set will update the file if it exists; upsert=True means it will insert if not found.
            op = UpdateOne({"_id": file_obj.id}, {"$set": file_data}, upsert=True)
        else:
            # $setOnInsert will only insert the file if it doesn't already exist.
            op = UpdateOne({"_id": file_obj.id}, {"$setOnInsert": file_data}, upsert=True)
        operations.append(op)

    try:
        # Perform the bulk upsert
        result = files_collection.bulk_write(operations, ordered=False)

        if payload.update:
            # When update=True, some files might be updated and some inserted.
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_count": result.upserted_count,
            }
        else:
            # When update=False, only new files are inserted. Existing ones are not modified.
            inserted_count = result.upserted_count  # Count of newly inserted files
            existing_count = len(payload.files) - inserted_count
            if existing_count > 0:
                logger.error(f"{existing_count} file(s) already exist and were not updated.")
            return {
                "inserted_count": inserted_count,
                "existing_count": existing_count,
            }
    except BulkWriteError as bwe:
        # Return detailed bulk write error information
        raise HTTPException(status_code=500, detail=bwe.details)


@files_endpoint_router.get("/list/{data_collection_id}")
async def list_registered_files(data_collection_id: str, current_user=Depends(get_current_user)):
    """
    Fetch all files registered from a Data Collection registered into a workflow.
    """

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    if not data_collection_id:
        raise HTTPException(
            status_code=400,
            detail="Data collection id must be provided.",
        )

    user_oid = ObjectId(current_user.id)
    target_data_collection_id = ObjectId(data_collection_id)
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"permissions.owners._id": user_oid},  # User is an owner
                    {"permissions.owners.is_admin": True},  # User is an admin
                ]
            }
        },
        {
            "$match": {"data_collection_id": target_data_collection_id}
        },  # Match files with the specific data collection ID
    ]

    result = files_collection.aggregate(pipeline)
    files = list(result)
    return convert_objectid_to_str(files)


@files_endpoint_router.delete("/delete/{file_id}")
async def delete_file(file_id: str, current_user=Depends(get_current_user)):
    """
    Delete a file from the database.
    """

    if not current_user:
        raise HTTPException(
            status_code=400,
            detail="Current user not found.",
        )

    if not file_id:
        raise HTTPException(
            status_code=400,
            detail="File id must be provided.",
        )

    user_oid = ObjectId(current_user.id)
    target_file_id = ObjectId(file_id)
    query = {
        "_id": target_file_id,
        "$or": [
            {"permissions.owners._id": user_oid},  # User is an owner
            {"permissions.owners.is_admin": True},  # User is an admin
        ],
    }

    result = files_collection.delete_one(query)
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No file with id {file_id} found for the current user.",
        )

    return {"message": f"Deleted file with id {file_id} successfully"}


# Supported image extensions for serving
SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"]
)


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse an S3 path into bucket and key components."""
    path = s3_path[5:] if s3_path.startswith("s3://") else s3_path
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"Invalid S3 path format: {s3_path}")
    return parts[0], parts[1]


def _get_mime_type(file_path: str) -> str:
    """Get MIME type for a file based on its extension."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def _validate_image_path(key: str) -> bool:
    """Validate path for security and supported image format."""
    if ".." in key or key.startswith("/"):
        return False
    lower_key = key.lower()
    return any(lower_key.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)


@files_endpoint_router.get("/serve/image")
async def serve_image(
    s3_path: str = Query(
        ..., description="Full S3 path to the image (e.g., s3://bucket/path/image.png)"
    ),
):
    """
    Serve images from S3/MinIO via streaming.

    NOTE: Currently PUBLIC to allow HTML <img> tags to load images.
    TODO: Implement presigned URLs for secure, time-limited access.
    """
    decoded_path = unquote(s3_path)

    try:
        bucket, key = _parse_s3_path(decoded_path)
    except ValueError as e:
        logger.error(f"Invalid S3 path: {decoded_path} - {e}")
        raise HTTPException(status_code=400, detail=f"Invalid S3 path format: {str(e)}")

    if not _validate_image_path(key):
        logger.warning(f"Invalid image path rejected: {key}")
        raise HTTPException(status_code=400, detail="Invalid image path or unsupported format")

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content_type = _get_mime_type(key)
        filename = key.split("/")[-1]

        def iterfile():
            for chunk in response["Body"].iter_chunks(chunk_size=8192):
                yield chunk

        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": f'inline; filename="{filename}"',
            },
        )
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Image not found: {bucket}/{key}")
        raise HTTPException(status_code=404, detail="Image not found")
    except s3_client.exceptions.NoSuchBucket:
        logger.error(f"Bucket not found: {bucket}")
        raise HTTPException(status_code=404, detail="Storage bucket not found")
    except Exception as e:
        logger.error(f"Error serving image {bucket}/{key}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving image: {str(e)}")
