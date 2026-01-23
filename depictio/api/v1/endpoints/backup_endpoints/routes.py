import json
import os
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.collection import Collection

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    groups_collection,
    projects_collection,
    runs_collection,
    users_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.users import User

backup_endpoint_router = APIRouter()


class BackupRequest(BaseModel):
    """Request model for backup creation with optional S3 data."""

    include_s3_data: bool = False
    s3_backup_prefix: str = "backup"
    dry_run: bool = False


class BackupResponse(BaseModel):
    success: bool
    message: str
    backup_id: str | None = None  # Server-side backup ID instead of path
    total_documents: int = 0
    excluded_documents: int = 0
    collections_backed_up: list = []
    timestamp: str | None = None
    filename: str | None = None


async def _create_mongodb_backup(current_user: User) -> dict:
    """
    Create a MongoDB backup with standard exclusions.

    Returns a dictionary containing backup data and metadata.
    """
    backup_data = {}
    total_documents = 0
    excluded_documents = 0
    collections_backed_up = []

    # Define collections to backup with their exclusion criteria
    # NOTE: Tokens excluded from backup/restore to avoid circular dependency issues
    collections_config = {
        "users": {"collection": users_collection, "exclude_filter": {"is_temporary": True}},
        "projects": {"collection": projects_collection, "exclude_filter": {}},
        "dashboards": {"collection": dashboards_collection, "exclude_filter": {}},
        "data_collections": {"collection": data_collections_collection, "exclude_filter": {}},
        "workflows": {"collection": workflows_collection, "exclude_filter": {}},
        "files": {"collection": files_collection, "exclude_filter": {}},
        "deltatables": {"collection": deltatables_collection, "exclude_filter": {}},
        "runs": {"collection": runs_collection, "exclude_filter": {}},
        "groups": {"collection": groups_collection, "exclude_filter": {}},
    }

    # First, get list of temporary user IDs to exclude their resources
    temp_users = list(users_collection.find({"is_temporary": True}, {"_id": 1}))
    temp_user_ids = [user["_id"] for user in temp_users]

    logger.info(f"Found {len(temp_user_ids)} temporary users to exclude")

    for collection_name, config in collections_config.items():
        # Extract collection with proper type for type checker
        collection = cast(Collection[dict[str, Any]], config["collection"])
        exclude_filter = cast(dict[str, Any], config["exclude_filter"])
        base_filter = exclude_filter.copy()

        # For dashboards, exclude those owned by temporary users
        if collection_name == "dashboards" and temp_user_ids:
            base_filter["permissions.owners._id"] = {"$nin": temp_user_ids}

        # Get all documents (applying exclusions)
        if base_filter:
            # Count excluded documents
            excluded_count = collection.count_documents(
                {
                    "$or": [
                        exclude_filter,
                        {"permissions.owners._id": {"$in": temp_user_ids}}
                        if collection_name == "dashboards"
                        else {},
                    ]
                }
            )
            excluded_documents += excluded_count

            if collection_name == "dashboards" and temp_user_ids:
                documents = list(
                    collection.find({"permissions.owners._id": {"$nin": temp_user_ids}})
                )
            else:
                # For other collections, use the normal exclude filter
                exclude_conditions = []
                if exclude_filter:
                    exclude_conditions.append(exclude_filter)

                if exclude_conditions:
                    documents = list(collection.find({"$nor": exclude_conditions}))
                else:
                    documents = list(collection.find({}))
        else:
            documents = list(collection.find({}))

        # Convert ObjectIds and DBRef objects to strings for JSON serialization
        for i, doc in enumerate(documents):
            documents[i] = _convert_complex_objects_to_strings(doc)

        backup_data[collection_name] = documents
        total_documents += len(documents)
        collections_backed_up.append(collection_name)

    timestamp = datetime.now()
    backup_id = timestamp.strftime("%Y%m%d_%H%M%S")

    mongodb_backup = {
        "backup_metadata": {
            "timestamp": timestamp.isoformat(),
            "created_by": current_user.email,
            "depictio_version": "0.1.0",
            "total_documents": total_documents,
            "excluded_documents": excluded_documents,
            "collections": collections_backed_up,
            "backup_id": backup_id,
        },
        "data": backup_data,
    }

    return mongodb_backup


@backup_endpoint_router.post("/create", response_model=BackupResponse)
async def create_backup(
    request: BackupRequest = BackupRequest(),
    current_user: User = Depends(get_current_user),
):
    """
    Create a backup of the MongoDB database with optional S3 deltatable data.

    This endpoint creates a full backup excluding:
    - Short-lived tokens
    - Temporary users and their related resources

    Optionally includes S3 deltatable data for complete backups.

    Only administrators can perform backup operations.
    """
    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can create backups"
        )

    logger.info(
        f"Admin user {current_user.email} initiating backup creation (S3: {request.include_s3_data})"
    )

    try:
        # Create MongoDB backup
        mongodb_backup = await _create_mongodb_backup(current_user)

        # Add S3 backup if requested
        if request.include_s3_data:
            logger.info("Adding S3 deltatable backup")
            from depictio.api.v1.backup_strategy_manager import (
                create_backup_with_strategy,
            )

            # Get deltatable locations from database
            deltatable_locations = []
            for deltatable in deltatables_collection.find({}):
                # Check both possible field names for S3 location
                location = deltatable.get("delta_table_location") or deltatable.get("location")
                if location:
                    # Extract the S3 path (remove s3://bucket/ prefix)
                    if location.startswith("s3://"):
                        # Extract just the path part after bucket name
                        parts = location.replace("s3://", "").split("/", 1)
                        if len(parts) > 1:
                            deltatable_locations.append(parts[1])
                    else:
                        deltatable_locations.append(location)

            # Create S3 backup
            s3_backup_result = await create_backup_with_strategy(
                deltatable_locations=deltatable_locations,
                backup_prefix=request.s3_backup_prefix,
                dry_run=request.dry_run,
            )

            # Add S3 backup metadata to the backup
            enhanced_backup = mongodb_backup.copy()
            enhanced_backup["s3_backup_metadata"] = s3_backup_result
        else:
            enhanced_backup = mongodb_backup

        backup_dir = settings.backup.backup_path
        os.makedirs(backup_dir, exist_ok=True)

        backup_id_str = mongodb_backup["backup_metadata"]["backup_id"]
        backup_filename = f"depictio_backup_{backup_id_str}.json"
        backup_path = os.path.join(backup_dir, backup_filename)

        with open(backup_path, "w") as backup_file:
            json.dump(enhanced_backup, backup_file, indent=2, default=str)

        logger.info(f"Backup created successfully: {backup_filename}")

        response_data = {
            "success": True,
            "message": "Backup created successfully"
            + (" with S3 data" if request.include_s3_data else ""),
            "backup_id": mongodb_backup["backup_metadata"]["backup_id"],
            "total_documents": mongodb_backup["backup_metadata"]["total_documents"],
            "excluded_documents": mongodb_backup["backup_metadata"]["excluded_documents"],
            "collections_backed_up": mongodb_backup["backup_metadata"]["collections"],
            "timestamp": mongodb_backup["backup_metadata"]["timestamp"],
            "filename": backup_filename,
        }

        # Add S3 metadata to response if included
        if request.include_s3_data and "s3_backup_metadata" in enhanced_backup:
            response_data["s3_backup_metadata"] = enhanced_backup["s3_backup_metadata"]

        return BackupResponse(**response_data)  # type: ignore[misc]

    except Exception as e:
        logger.error(f"Backup creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {str(e)}")


@backup_endpoint_router.post("/create-enhanced", response_model=BackupResponse, deprecated=True)
async def create_enhanced_backup(
    request: BackupRequest,
    current_user: User = Depends(get_current_user),
):
    """
    DEPRECATED: Use /create endpoint instead.

    Create an enhanced backup including optional S3 deltatable data.
    This endpoint is deprecated and redirects to the unified /create endpoint.
    """
    # Simply call the unified create_backup endpoint
    return await create_backup(request, current_user)


class BackupListResponse(BaseModel):
    success: bool
    backups: list
    count: int


class BackupValidateRequest(BaseModel):
    backup_id: str


class BackupValidateResponse(BaseModel):
    success: bool
    message: str
    valid: bool = False
    total_documents: int = 0
    valid_documents: int = 0
    invalid_documents: int = 0
    collections_validated: dict = {}
    errors: list = []


class BackupRestoreRequest(BaseModel):
    backup_id: str
    dry_run: bool = True
    collections: list[str] | None = None  # If None, restore all collections


class BackupRestoreResponse(BaseModel):
    success: bool
    message: str
    restored_collections: dict = {}
    total_restored: int = 0
    errors: list = []


@backup_endpoint_router.get("/list", response_model=BackupListResponse)
async def list_backups(
    current_user: User = Depends(get_current_user),
):
    """List available backups on the server."""

    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can list backups"
        )

    try:
        backup_dir = settings.backup.backup_path
        if not os.path.exists(backup_dir):
            return BackupListResponse(success=True, backups=[], count=0)

        backup_files = []
        for filename in os.listdir(backup_dir):
            if filename.startswith("depictio_backup_") and filename.endswith(".json"):
                file_path = os.path.join(backup_dir, filename)
                file_stat = os.stat(file_path)

                # Extract backup ID from filename
                backup_id = filename.replace("depictio_backup_", "").replace(".json", "")

                # Try to read metadata
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                        metadata = data.get("backup_metadata", {})

                    backup_info = {
                        "backup_id": backup_id,
                        "filename": filename,
                        "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
                        "created": datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        "created_by": metadata.get("created_by", "unknown"),
                        "total_documents": metadata.get("total_documents", 0),
                        "collections": metadata.get("collections", []),
                    }
                except Exception:
                    # If can't read metadata, just use file info
                    backup_info = {
                        "backup_id": backup_id,
                        "filename": filename,
                        "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
                        "created": datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        "created_by": "unknown",
                        "total_documents": 0,
                        "collections": [],
                    }

                backup_files.append(backup_info)

        # Sort by creation time (newest first)
        backup_files.sort(key=lambda x: x["created"], reverse=True)

        return BackupListResponse(success=True, backups=backup_files, count=len(backup_files))

    except Exception as e:
        logger.error(f"Failed to list backups: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {str(e)}")


@backup_endpoint_router.post("/validate", response_model=BackupValidateResponse)
async def validate_backup(
    request: BackupValidateRequest,
    current_user: User = Depends(get_current_user),
):
    """Validate a backup file on the server."""

    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can validate backups"
        )

    try:
        BACKUP_DIR = settings.backup.backup_path
        backup_filename = f"depictio_backup_{request.backup_id}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        if not os.path.exists(backup_path):
            return BackupValidateResponse(
                success=False, message=f"Backup not found: {request.backup_id}", valid=False
            )

        # Import validation function
        from depictio.cli.cli.utils.backup_validation import validate_backup_file

        # Validate the backup
        result = validate_backup_file(backup_path)

        return BackupValidateResponse(
            success=True,
            message="Validation completed",
            valid=result.get("valid", False),
            total_documents=result.get("total_documents", 0),
            valid_documents=result.get("valid_documents", 0),
            invalid_documents=result.get("invalid_documents", 0),
            collections_validated=result.get("collections_validated", {}),
            errors=result.get("errors", []),
        )

    except Exception as e:
        logger.error(f"Backup validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Backup validation failed: {str(e)}")


def _convert_complex_objects_to_strings(obj):
    """Convert DBRef and ObjectId to strings for JSON serialization."""
    from bson import DBRef, ObjectId

    if isinstance(obj, DBRef):
        return str(obj.id)
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {key: _convert_complex_objects_to_strings(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_convert_complex_objects_to_strings(item) for item in obj]
    return obj


@backup_endpoint_router.post("/restore", response_model=BackupRestoreResponse)
async def restore_backup(
    request: BackupRestoreRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Restore data from a backup file.

    WARNING: This is a destructive operation that will replace existing data.
    Use dry_run=True to preview what would be restored.
    """

    # Check if user is admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can restore backups"
        )

    logger.info(
        f"Admin user {current_user.email} initiating restore from backup {request.backup_id}"
    )

    try:
        backup_dir = settings.backup.backup_path
        backup_filename = f"depictio_backup_{request.backup_id}.json"
        backup_path = os.path.join(backup_dir, backup_filename)

        if not os.path.exists(backup_path):
            return BackupRestoreResponse(
                success=False,
                message=f"Backup not found: {request.backup_id}",
                errors=[f"Backup file does not exist: {backup_filename}"],
            )

        with open(backup_path, "r") as f:
            backup_data = json.load(f)

        if "data" not in backup_data:
            return BackupRestoreResponse(
                success=False,
                message="Invalid backup format",
                errors=["Backup file missing 'data' section"],
            )

        data_section = backup_data["data"]

        # Tokens excluded to avoid circular dependency
        collection_map = {
            "users": users_collection,
            "projects": projects_collection,
            "dashboards": dashboards_collection,
            "data_collections": data_collections_collection,
            "workflows": workflows_collection,
            "files": files_collection,
            "deltatables": deltatables_collection,
            "runs": runs_collection,
            "groups": groups_collection,
        }

        collections_to_restore = request.collections or list(data_section.keys())

        restored_collections = {}
        total_restored = 0
        errors = []

        if request.dry_run:
            for collection_name in collections_to_restore:
                if collection_name not in data_section:
                    errors.append(f"Collection '{collection_name}' not found in backup")
                    continue

                documents = data_section[collection_name]
                restored_collections[collection_name] = {
                    "count": len(documents),
                    "status": "would_restore",
                }
                total_restored += len(documents)

            return BackupRestoreResponse(
                success=True,
                message=f"DRY RUN: Would restore {total_restored} documents",
                restored_collections=restored_collections,
                total_restored=total_restored,
                errors=errors,
            )

        for collection_name in collections_to_restore:
            if collection_name not in data_section:
                errors.append(f"Collection '{collection_name}' not found in backup")
                continue

            if collection_name not in collection_map:
                errors.append(f"Collection '{collection_name}' not recognized")
                continue

            try:
                collection = collection_map[collection_name]
                documents = data_section[collection_name]
                from bson import ObjectId

                for doc in documents:
                    if "id" in doc:
                        doc["_id"] = ObjectId(doc.pop("id"))
                    if "_id" in doc and isinstance(doc["_id"], str):
                        doc["_id"] = ObjectId(doc["_id"])

                if documents:
                    try:
                        collection.delete_many({})
                        collection.insert_many(documents)
                    except Exception as e:
                        logger.error(f"Failed to restore {collection_name}: {e}")
                        raise
                else:
                    collection.delete_many({})

                restored_collections[collection_name] = {
                    "count": len(documents),
                    "status": "restored",
                }
                total_restored += len(documents)

            except Exception as e:
                error_msg = f"Failed to restore {collection_name}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                restored_collections[collection_name] = {
                    "count": 0,
                    "status": "failed",
                    "error": str(e),
                }

        return BackupRestoreResponse(
            success=len(errors) == 0,
            message=f"Restored {total_restored} documents from backup",
            restored_collections=restored_collections,
            total_restored=total_restored,
            errors=errors,
        )

    except Exception as e:
        logger.error(f"Restore operation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Restore operation failed: {str(e)}")
