import mimetypes
import posixpath
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
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.s3 import s3_client
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.data_collections_types.indexed_file import (
    DEFAULT_INDEX_SUFFIX,
    indexed_file_s3_key,
)
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
        # SECURITY: do not leak BulkWriteError internals (which can include raw
        # documents / index details) to the client. Log internally, return a
        # generic message.
        logger.error(f"Bulk write error during batch upsert: {bwe.details}")
        raise HTTPException(status_code=500, detail="Internal error during batch upsert")


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
    # SECURITY: same predicate shape as delete_file below — admin status is
    # a property of the *caller*, not of the file's owners. Keying off
    # ``permissions.owners.is_admin`` previously let any caller list every
    # file whose owner happened to be admin.
    if current_user.is_admin:
        permission_match: dict = {}
    else:
        permission_match = {"permissions.owners._id": user_oid}
    pipeline = [
        {"$match": {**permission_match, "data_collection_id": target_data_collection_id}},
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
    # SECURITY: the previous predicate ``{"permissions.owners.is_admin": True}``
    # matched any file whose owner happens to be an admin — meaning a
    # non-admin user could delete *another* admin's files. The correct check
    # is on the caller (``current_user.is_admin``), not on the file's owners.
    if current_user.is_admin:
        query: dict = {"_id": target_file_id}
    else:
        query = {
            "_id": target_file_id,
            "permissions.owners._id": user_oid,
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
    # Explicit mapping for image types that may not be in system mimetypes
    ext_lower = file_path.lower()
    if ext_lower.endswith(".webp"):
        return "image/webp"
    if ext_lower.endswith(".avif"):
        return "image/avif"

    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def _validate_image_path(key: str) -> bool:
    """Validate an S3 key for traversal safety and supported image format.

    S3 keys are POSIX-style, so normalization is done with ``posixpath``. The
    raw key is rejected up front for any ``..`` segment or leading slash, then
    the same assertions are re-run on the normalized form to catch sequences
    that collapse into an escape (e.g. ``a/../../b``) or that resolve to an
    absolute path after normalization.
    """
    # Reject empty keys and obvious traversal markers on the raw input.
    if not key or ".." in key or key.startswith("/"):
        return False

    # Re-assert on the normalized form. normpath collapses ``.``/``..``
    # segments and duplicate slashes; if the result escapes upward, becomes
    # absolute, or differs from the (trailing-slash-stripped) original, reject.
    normalized = posixpath.normpath(key)
    if (
        normalized.startswith("/")
        or normalized == ".."
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized != key.rstrip("/")
    ):
        return False

    lower_key = normalized.lower()
    return any(lower_key.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)


@files_endpoint_router.get("/serve/image")
async def serve_image(
    s3_path: str = Query(
        ..., description="Full S3 path to the image (e.g., s3://bucket/path/image.png)"
    ),
):
    """
    Serve images from S3 via streaming.

    NOTE: Currently PUBLIC to allow HTML <img> tags to load images. Access is
    bucket-locked to the configured S3 bucket and the key is
    traversal-hardened, so this endpoint can only stream objects from
    Depictio's own bucket.
    TODO: Presigned, time-limited URLs remain future work for per-object
    access control.
    """
    decoded_path = unquote(s3_path)

    try:
        bucket, key = _parse_s3_path(decoded_path)
    except ValueError as e:
        logger.error(f"Invalid S3 path: {decoded_path} - {e}")
        raise HTTPException(status_code=400, detail=f"Invalid S3 path format: {str(e)}")

    # SECURITY: lock serving to Depictio's configured bucket. Without this an
    # attacker could point s3_path at any bucket the S3 credentials can read.
    if bucket != settings.s3.bucket:
        logger.warning(f"Image request for disallowed bucket rejected: {bucket}")
        raise HTTPException(status_code=403, detail="Access to the requested bucket is forbidden")

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
        # SECURITY: log the underlying error internally, but do not leak
        # exception details (which may include S3 internals) to the client.
        logger.error(f"Error serving image {bucket}/{key}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving image")


# ---------------------------------------------------------------------------
# indexed_file DCs: presigned, range-capable URLs
# ---------------------------------------------------------------------------
#
# GenomeSpy's lazy data sources (vcf, bam, bigwig, bigbed, gff3, tabix,
# indexedFasta) read their objects straight from storage with HTTP range
# requests, so the bytes must never pass through this API. What the API hands
# out is a short-lived presigned URL and the manifest saying which samples
# exist. Two consequences shape the code below:
#
# 1. The URL is signed against the *browser-reachable* endpoint
#    (``settings.minio.external_url``), not the in-cluster one. SigV4 signs the
#    host, so a URL signed for ``http://minio:9000`` fails from a browser even
#    when the bytes are reachable another way.
# 2. The storage must send CORS headers for Range, and expose
#    Content-Range / Accept-Ranges. See the MinIO service in
#    docker-compose.dev.yaml and docs/indexed-files.md.

#: Lifetime of a presigned indexed-file URL. Long enough for a reader to pan a
#: track, short enough that a leaked link dies on its own.
INDEXED_FILE_URL_TTL_SECONDS = 15 * 60

_presign_client = None


def _presigning_s3_client():
    """boto3 client whose signatures are valid for the browser's endpoint.

    Built lazily and once: instantiating a boto3 client costs a session load,
    and this one is only needed by deployments that expose indexed files.
    """
    global _presign_client
    if _presign_client is None:
        import boto3
        from botocore.client import Config

        _presign_client = boto3.client(
            "s3",
            aws_access_key_id=settings.minio.aws_access_key_id,
            aws_secret_access_key=settings.minio.aws_secret_access_key,
            endpoint_url=settings.minio.external_url,
            verify=settings.minio.verify_tls,
            config=Config(signature_version="s3v4"),
        )
    return _presign_client


def presign_indexed_file(key: str, ttl_seconds: int = INDEXED_FILE_URL_TTL_SECONDS) -> str:
    """Presigned GET URL for one bucket object, valid for ``ttl_seconds``."""
    return _presigning_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.minio.bucket, "Key": key},
        ExpiresIn=ttl_seconds,
    )


def _indexed_file_dc_properties(dc_oid: ObjectId) -> dict:
    """``dc_specific_properties`` of an indexed_file DC, from the project doc.

    Data collections live embedded under ``workflows[].data_collections[]``;
    there is no top-level document to look up. Returns an empty dict when the
    DC is not an indexed_file one, which the callers turn into a 404.
    """
    from depictio.api.v1.db import projects_collection

    project_doc = projects_collection.find_one(
        {"workflows.data_collections._id": dc_oid},
        {"workflows.data_collections": 1},
    )
    if not project_doc:
        return {}
    for wf in project_doc.get("workflows", []) or []:
        for dc in wf.get("data_collections", []) or []:
            if (dc.get("_id") or dc.get("id")) != dc_oid:
                continue
            config = dc.get("config") or {}
            if str(config.get("type", "")).lower() != "indexed_file":
                return {}
            return config.get("dc_specific_properties") or {}
    return {}


def _effective_index_suffix(properties: dict) -> str:
    """Index suffix for a DC's properties dict, falling back to the format default."""
    explicit = properties.get("index_suffix")
    if explicit is not None:
        return str(explicit)
    return DEFAULT_INDEX_SUFFIX.get(str(properties.get("format", "")).lower(), "")


@files_endpoint_router.get("/indexed/{data_collection_id}")
async def list_indexed_files(
    data_collection_id: str,
    current_user=Depends(get_user_or_anonymous),
):
    """Manifest of an indexed_file DC: one entry per sample, with presigned URLs.

    This is what a file-backed track fetches before it builds its GenomeSpy
    spec: it needs the format (which lazy source to declare), the assembly and,
    per sample, a URL for the object and one for its index.
    """
    try:
        dc_oid = ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dc_id: {exc}") from exc

    _assert_indexed_file_access(dc_oid, current_user)

    properties = _indexed_file_dc_properties(dc_oid)
    if not properties:
        raise HTTPException(
            status_code=404, detail="Data collection not found or not an indexed_file collection."
        )

    index_suffix = _effective_index_suffix(properties)
    docs = files_collection.find(
        {"data_collection_id": dc_oid, "s3_key": {"$ne": None}},
        {"sample": 1, "filename": 1, "filesize": 1, "s3_key": 1, "index_s3_key": 1},
    )

    entries = []
    for doc in docs:
        key = doc.get("s3_key")
        if not key:
            continue
        index_key = doc.get("index_s3_key")
        entries.append(
            {
                "sample": doc.get("sample") or "",
                "name": doc.get("filename") or posixpath.basename(str(key)),
                "size_bytes": doc.get("filesize"),
                "url": presign_indexed_file(str(key)),
                "index_url": presign_indexed_file(str(index_key)) if index_key else None,
            }
        )
    entries.sort(key=lambda e: (e["sample"], e["name"]))

    return {
        "data_collection_id": str(dc_oid),
        "format": str(properties.get("format", "")).lower(),
        "index_suffix": index_suffix,
        "assembly": properties.get("assembly"),
        "sample_col": properties.get("sample_col", "sample"),
        "expires_in": INDEXED_FILE_URL_TTL_SECONDS,
        "files": entries,
    }


@files_endpoint_router.get("/{data_collection_id}/{sample}/{name}")
async def get_indexed_file_url(
    data_collection_id: str,
    sample: str,
    name: str,
    current_user=Depends(get_user_or_anonymous),
):
    """Presigned URL for one object of an indexed_file DC, valid 15 minutes.

    The key is rebuilt from the path parameters through ``indexed_file_s3_key``
    rather than read from the request, so a caller-supplied ``sample`` or
    ``name`` cannot reach outside the DC's own prefix. The object must also be
    registered for this DC, which is what stops a reader with access to one DC
    from guessing keys in another.
    """
    try:
        dc_oid = ObjectId(str(data_collection_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid dc_id: {exc}") from exc

    _assert_indexed_file_access(dc_oid, current_user)

    try:
        key = indexed_file_s3_key(str(dc_oid), unquote(sample), unquote(name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = files_collection.find_one(
        {"data_collection_id": dc_oid, "$or": [{"s3_key": key}, {"index_s3_key": key}]},
        {"filesize": 1, "index_filesize": 1, "s3_key": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="File not found for this data collection.")

    is_index = doc.get("s3_key") != key
    return {
        "url": presign_indexed_file(key),
        "expires_in": INDEXED_FILE_URL_TTL_SECONDS,
        "size_bytes": doc.get("index_filesize") if is_index else doc.get("filesize"),
    }


def _assert_indexed_file_access(dc_oid: ObjectId, current_user) -> None:
    """Project-level read check, shared with the advanced-viz DC routes.

    Imported lazily: ``advanced_viz_endpoints`` and this module are both pulled
    in by ``routers.py``, and a module-level import would tie their import
    order together for no gain.
    """
    from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _assert_dc_access

    _assert_dc_access(dc_oid, current_user)
