import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
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
from depictio.version import get_version

backup_endpoint_router = APIRouter()

# Backup IDs are generated as ``datetime.strftime("%Y%m%d_%H%M%S")`` in
# ``_create_mongodb_backup`` (e.g. ``20250627_123456``). Enforcing this strict
# format prevents path-traversal / arbitrary-filename injection because the
# ``backup_id`` is concatenated into a filename on the server.
_BACKUP_ID_PATTERN = re.compile(r"^\d{8}_\d{6}$")


def _validate_backup_id(backup_id: str) -> None:
    """Reject any ``backup_id`` that does not match the canonical timestamp format.

    Raises HTTP 422 before the value is ever used to build a filesystem path.
    """
    if not isinstance(backup_id, str) or not _BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise HTTPException(
            status_code=422,
            detail="Invalid backup_id format. Expected 'YYYYMMDD_HHMMSS'.",
        )


def _resolve_backup_path(backup_dir: str, backup_id: str) -> str:
    """Build and validate the backup file path for a (already format-checked) backup_id.

    Performs a resolved-path containment check so that even an unexpected
    ``backup_id`` cannot escape the configured backup directory.
    """
    base = Path(backup_dir).resolve()
    candidate = (base / f"depictio_backup_{backup_id}.json").resolve()
    if not candidate.is_relative_to(base):
        # Path escaped the backup directory — treat as a validation error and
        # log internally without echoing the resolved path back to the caller.
        logger.error(f"Rejected backup path outside backup directory: backup_id={backup_id!r}")
        raise HTTPException(
            status_code=422,
            detail="Invalid backup_id format. Expected 'YYYYMMDD_HHMMSS'.",
        )
    return str(candidate)


def _compute_file_sha256(file_path: str) -> str:
    """Compute the SHA-256 hex digest of a file's contents (streamed)."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _read_expected_checksum(checksum_path: str) -> str | None:
    """Read the expected SHA-256 digest from a ``.sha256`` sidecar file.

    The sidecar follows the ``sha256sum`` convention ("<hexdigest>  <filename>").
    Returns the lowercase hex digest, or ``None`` if the sidecar is missing or
    malformed.
    """
    if not os.path.exists(checksum_path):
        return None
    try:
        with open(checksum_path, "r") as fh:
            first_line = fh.readline().strip()
    except OSError:
        return None
    if not first_line:
        return None
    digest = first_line.split()[0].strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        return digest
    return None


def _verify_backup_integrity(backup_path: str, allow_unverified: bool) -> None:
    """Verify a backup file's SHA-256 against its sidecar before restore.

    - Missing sidecar (legacy pre-checksum backups): allowed only when
      ``allow_unverified`` is True, otherwise HTTP 409.
    - Sidecar present but digest mismatch: always HTTP 400 (never bypassable),
      since a mismatch indicates tampering or corruption.
    """
    checksum_path = f"{backup_path}.sha256"
    expected = _read_expected_checksum(checksum_path)

    if expected is None:
        if allow_unverified:
            logger.warning(
                "Restoring backup without checksum verification "
                "(allow_unverified=True); no valid .sha256 sidecar found."
            )
            return
        raise HTTPException(
            status_code=409,
            detail=(
                "Backup integrity could not be verified: checksum is missing. "
                "Re-create the backup, or set allow_unverified=true to restore "
                "a legacy backup at your own risk."
            ),
        )

    actual = _compute_file_sha256(backup_path)
    if actual != expected:
        logger.error(
            "Backup checksum mismatch detected during restore "
            f"(path basename={os.path.basename(backup_path)})"
        )
        raise HTTPException(
            status_code=400,
            detail="Backup integrity check failed: checksum mismatch.",
        )


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
            "depictio_version": get_version(),
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

        # Integrity: store a SHA-256 sidecar so restores can verify the backup
        # file has not been tampered with or truncated. The sidecar is written
        # after the backup file so the digest reflects the final contents.
        backup_checksum = _compute_file_sha256(backup_path)
        checksum_path = f"{backup_path}.sha256"
        with open(checksum_path, "w") as checksum_file:
            checksum_file.write(f"{backup_checksum}  {backup_filename}\n")

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
        raise HTTPException(status_code=500, detail="Backup creation failed.")


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
    # Escape hatch for legacy backups created before checksum sidecars existed.
    # Only bypasses a *missing* checksum; a checksum *mismatch* is never bypassable.
    allow_unverified: bool = False


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
        raise HTTPException(status_code=500, detail="Failed to list backups.")


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

    # Reject malformed backup_id before it touches the filesystem.
    _validate_backup_id(request.backup_id)

    try:
        backup_dir = settings.backup.backup_path
        backup_path = _resolve_backup_path(backup_dir, request.backup_id)

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backup validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Backup validation failed.")


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

    # Reject malformed backup_id before it touches the filesystem.
    _validate_backup_id(request.backup_id)

    logger.info(
        f"Admin user {current_user.email} initiating restore from backup {request.backup_id}"
    )

    try:
        backup_dir = settings.backup.backup_path
        backup_path = _resolve_backup_path(backup_dir, request.backup_id)

        if not os.path.exists(backup_path):
            return BackupRestoreResponse(
                success=False,
                message=f"Backup not found: {request.backup_id}",
                errors=["Backup file does not exist."],
            )

        # Integrity gate: verify the backup file checksum before reading/applying
        # any data. Raises 400 (mismatch) or 409 (missing, unless allow_unverified).
        _verify_backup_integrity(backup_path, request.allow_unverified)

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
                # Log full detail internally; return a sanitized message.
                logger.error(f"Failed to restore {collection_name}: {str(e)}")
                errors.append(f"Failed to restore collection '{collection_name}'.")
                restored_collections[collection_name] = {
                    "count": 0,
                    "status": "failed",
                    "error": "restore failed",
                }

        return BackupRestoreResponse(
            success=len(errors) == 0,
            message=f"Restored {total_restored} documents from backup",
            restored_collections=restored_collections,
            total_restored=total_restored,
            errors=errors,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore operation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Restore operation failed.")
