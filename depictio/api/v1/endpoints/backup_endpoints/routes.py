import calendar
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from bson import DBRef, ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pymongo.collection import Collection

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    branding_assets_collection,
    dashboards_collection,
    data_collections_collection,
    deltatables_collection,
    files_collection,
    groups_collection,
    initialization_collection,
    instance_settings_collection,
    projects_collection,
    runs_collection,
    users_collection,
    workflows_collection,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.users import User
from depictio.version import get_version

backup_endpoint_router = APIRouter()

# Uploaded backup files are read fully into memory before being written to the
# backup directory, so cap their size. Module-level so tests can patch it.
MAX_BACKUP_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB

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


def _write_backup_file(backup_payload: dict, backup_id: str) -> str:
    """Write a backup payload and its SHA-256 sidecar; return the filename.

    Shared by the ``/create`` endpoint and the scheduled backup task so both
    produce byte-identical artefacts — including the sidecar, without which a
    later restore refuses to run unless the admin passes allow_unverified.
    """
    backup_dir = settings.backup.backup_path
    os.makedirs(backup_dir, exist_ok=True)

    backup_filename = f"depictio_backup_{backup_id}.json"
    backup_path = os.path.join(backup_dir, backup_filename)

    with open(backup_path, "w") as backup_file:
        json.dump(backup_payload, backup_file, indent=2, default=str)

    # Integrity: store a SHA-256 sidecar so restores can verify the backup
    # file has not been tampered with or truncated. The sidecar is written
    # after the backup file so the digest reflects the final contents.
    backup_checksum = _compute_file_sha256(backup_path)
    with open(f"{backup_path}.sha256", "w") as checksum_file:
        checksum_file.write(f"{backup_checksum}  {backup_filename}\n")

    return backup_filename


def _parse_backup_created(filename: str) -> datetime | None:
    """Creation time of a backup from its filename, or None if it is not one.

    The age comes from the ``backup_id`` in the filename rather than the file's
    mtime: mtimes do not survive a volume restore or an rsync, and the id is the
    creation timestamp by construction.
    """
    if not (filename.startswith("depictio_backup_") and filename.endswith(".json")):
        return None
    backup_id = filename[len("depictio_backup_") : -len(".json")]
    if not _BACKUP_ID_PATTERN.fullmatch(backup_id):
        return None
    try:
        return datetime.strptime(backup_id, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _subtract_months(moment: datetime, months: int) -> datetime:
    """Step back whole calendar months, clamping the day to the target month.

    The monthly tier is expressed in calendar months, so its boundary cannot be
    a fixed number of days without drifting against the buckets it is meant to
    bound (31 March minus one month is 28 February, not 3 March).
    """
    month_index = (moment.year * 12 + moment.month - 1) - months
    year, month = divmod(month_index, 12)
    day = min(moment.day, calendar.monthrange(year, month + 1)[1])
    return moment.replace(year=year, month=month + 1, day=day)


def select_expired_backups(
    backups: list[tuple[datetime, str]],
    now: datetime,
    retention_days: int,
    weekly_weeks: int,
    monthly_months: int,
) -> list[str]:
    """Apply the grandfather-father-son policy; return the filenames to delete.

    Three tiers, each covering the age range where the one before it stops:

    - every backup younger than ``retention_days`` is kept;
    - for the next ``weekly_weeks`` weeks, the newest backup of each ISO week;
    - for the next ``monthly_months`` calendar months, the newest of each month.

    Anything older than the last tier, or landing in a bucket a newer backup
    already fills, is expired. With both tier sizes at 0 this reduces exactly to
    a plain ``retention_days`` age cutoff, which is what a deployment that never
    touches the tiers keeps getting. ``retention_days <= 0`` means keep forever.

    A backup kept by an earlier tier also fills its week and month buckets, so a
    week that still has a daily-tier survivor does not additionally retain a
    weekly copy of itself.

    Pure and total: takes the clock as an argument and touches no filesystem, so
    the policy can be tested directly over a set of dates.
    """
    if retention_days <= 0:
        return []

    daily_cutoff = now - timedelta(days=retention_days)
    weekly_cutoff = daily_cutoff - timedelta(weeks=weekly_weeks)
    monthly_cutoff = _subtract_months(weekly_cutoff, monthly_months)

    expired: list[str] = []
    kept_weeks: set[tuple[int, int]] = set()
    kept_months: set[tuple[int, int]] = set()

    # Newest first: the first backup to reach a bucket is the one that fills it.
    for created, filename in sorted(backups, reverse=True):
        week = created.isocalendar()[:2]
        month = (created.year, created.month)

        if created >= daily_cutoff:
            kept_weeks.add(week)
            kept_months.add(month)
        elif created >= weekly_cutoff and week not in kept_weeks:
            kept_weeks.add(week)
            kept_months.add(month)
        elif monthly_cutoff <= created < weekly_cutoff and month not in kept_months:
            kept_months.add(month)
        else:
            expired.append(filename)

    return expired


def prune_expired_backups() -> int:
    """Delete the backups the retention policy no longer covers; return the count.

    Runs after every backup, scheduled or manual — nothing else prunes this
    directory, and each snapshot is the size of the whole database, so without
    this the backup volume grows without bound.

    Files that do not parse as a backup are left alone. Never raises.
    """
    config = get_backup_schedule_config()
    retention_days = config["retention_days"]
    if retention_days <= 0:
        return 0

    backup_dir = settings.backup.backup_path
    if not os.path.isdir(backup_dir):
        return 0

    try:
        filenames = os.listdir(backup_dir)
    except OSError as exc:
        logger.warning(f"Backup retention: cannot list {backup_dir}: {exc}")
        return 0

    backups = []
    for filename in filenames:
        created = _parse_backup_created(filename)
        if created is not None:
            backups.append((created, filename))

    expired = select_expired_backups(
        backups,
        datetime.now(),
        retention_days,
        config["weekly_weeks"],
        config["monthly_months"],
    )

    removed = 0
    for filename in expired:
        backup_path = os.path.join(backup_dir, filename)
        try:
            os.remove(backup_path)
            # The sidecar is worthless on its own; drop it with the backup.
            if os.path.exists(f"{backup_path}.sha256"):
                os.remove(f"{backup_path}.sha256")
            removed += 1
        except OSError as exc:
            logger.warning(f"Backup retention: failed to delete {filename}: {exc}")

    if removed:
        logger.info(
            f"Backup retention: removed {removed} backup(s) outside the policy "
            f"(keep {retention_days}d, then {config['weekly_weeks']}w, "
            f"then {config['monthly_months']}m)"
        )
    return removed


#: ``_id`` of the document holding the scheduled-backup state. Lives in the
#: initialization collection alongside the other cross-worker coordination
#: documents (the init lock, the YAML watcher lock).
AUTO_BACKUP_STATE_ID = "auto_backup_state"

#: Sentinel for "never ran". A fresh deployment is therefore due immediately,
#: while a restart of an existing one resumes its schedule instead of firing a
#: backup on every boot.
_NEVER_RAN = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime read back from MongoDB.

    The pymongo client is not tz-aware, so stored UTC datetimes come back naive.
    Serializing those without an offset makes the browser read them as local
    time, which is how a "next run" lands hours away from where it should be.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


#: An "HH:MM" time-of-day anchor, 24-hour clock. Empty string clears the anchor.
_TIME_OF_DAY_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_time_of_day(value: str | None) -> int | None:
    """Minutes from midnight UTC for an "HH:MM" anchor, or None if unset/invalid.

    Invalid input degrades to "no anchor" rather than raising: a malformed value
    in the environment should leave the schedule rolling, not stop it backing up.
    """
    if not value or not isinstance(value, str):
        return None
    match = _TIME_OF_DAY_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def scheduled_slot(now: datetime, interval_seconds: int, anchor_minutes: int) -> datetime:
    """The most recent scheduled slot at or before ``now``.

    Slots sit on a fixed grid anchored at the chosen time of day, so a daily
    backup lands at that time every day, and a six-hourly one lands at that time
    and every six hours after it. Anchoring to a fixed epoch rather than to the
    last run is what stops the schedule drifting later and later: a run that
    fires a few minutes late does not push tomorrow's slot back with it.
    """
    base = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=anchor_minutes)
    elapsed = (now - base).total_seconds()
    return base + timedelta(seconds=(elapsed // interval_seconds) * interval_seconds)


def claim_auto_backup_slot(
    interval_seconds: int, anchor_minutes: int | None = None
) -> datetime | None:
    """Claim the right to take the next scheduled backup, across all workers.

    Every API worker runs the scheduler loop — gating on the initialization
    election would not work, because that election has no winner once a
    deployment has booted before. Instead the due time lives in MongoDB and the
    claim is a single conditional update: the first worker whose update matches
    moves ``last_run_at`` forward, and every other worker's update matches
    nothing and returns None.

    Returns the claim time, or None when the slot is not due or is already taken.
    """
    now = datetime.now(timezone.utc)
    # Without an anchor the schedule stays rolling: due once an interval has
    # passed since the last run, wherever in the day that lands.
    if anchor_minutes is None:
        due_filter = {"$lte": now - timedelta(seconds=interval_seconds)}
    else:
        due_filter = {"$lt": scheduled_slot(now, interval_seconds, anchor_minutes)}
    try:
        initialization_collection.update_one(
            {"_id": AUTO_BACKUP_STATE_ID},
            {"$setOnInsert": {"last_run_at": _NEVER_RAN}},
            upsert=True,
        )
        claimed = initialization_collection.find_one_and_update(
            {"_id": AUTO_BACKUP_STATE_ID, "last_run_at": due_filter},
            {"$set": {"last_run_at": now}},
        )
    except Exception as exc:
        # Declining to back up is the safe failure: the next tick retries.
        logger.warning(f"Scheduled backup: could not claim slot: {exc}")
        return None
    return now if claimed else None


#: ``_id`` of the document naming the backup this deployment's data was last
#: restored from. Lives beside the scheduler state, in a collection that restore
#: never touches — a document inside a restored collection would be overwritten
#: by the very restore it is meant to record.
LAST_RESTORE_STATE_ID = "last_restore_state"


def record_last_restore(backup_id: str, restored_by: str) -> None:
    """Remember which backup was just restored. Never raises.

    A bookkeeping failure must not turn a completed restore into an error the
    caller sees, so this only logs.
    """
    try:
        initialization_collection.update_one(
            {"_id": LAST_RESTORE_STATE_ID},
            {
                "$set": {
                    "backup_id": backup_id,
                    "restored_at": datetime.now(timezone.utc),
                    "restored_by": restored_by,
                }
            },
            upsert=True,
        )
    except Exception as exc:
        logger.warning(f"Could not record the last restore: {exc}")


def get_last_restore_state() -> dict:
    """Read the last-restore marker. Never raises."""
    try:
        return initialization_collection.find_one({"_id": LAST_RESTORE_STATE_ID}) or {}
    except Exception as exc:
        logger.warning(f"Could not read the last restore state: {exc}")
        return {}


def get_auto_backup_state() -> dict:
    """Read the scheduled-backup state document. Never raises."""
    try:
        return initialization_collection.find_one({"_id": AUTO_BACKUP_STATE_ID}) or {}
    except Exception as exc:
        logger.warning(f"Scheduled backup: could not read state: {exc}")
        return {}


#: Schedule fields an admin can change from the Backups tab. Everything else
#: about backups (paths, S3 targets, credentials) stays deployment configuration.
SCHEDULE_FIELDS = (
    "enabled",
    "interval_hours",
    "retention_days",
    "weekly_weeks",
    "monthly_months",
    "time_of_day",
)


def get_backup_schedule_config() -> dict:
    """Resolve the schedule an admin actually gets: stored values over settings.

    The environment supplies the *default*; a value stored from the Backups tab
    overrides it. Read this way round, an admin's click is never silently
    reverted on the next restart by an env var they cannot see from the page,
    while a deployment that never touches the UI keeps behaving exactly as its
    Helm values say.

    Read fresh on every use rather than cached at startup, so enabling the
    schedule from the UI takes effect without restarting the API.
    """
    config = {
        "enabled": settings.backup.auto_backup_enabled,
        "interval_hours": settings.backup.auto_backup_interval_hours,
        "retention_days": settings.backup.backup_file_retention_days,
        "weekly_weeks": settings.backup.backup_retention_weekly_weeks,
        "monthly_months": settings.backup.backup_retention_monthly_months,
        "time_of_day": settings.backup.auto_backup_time_of_day,
    }
    state = get_auto_backup_state()
    overrides = {field: state[field] for field in SCHEDULE_FIELDS if field in state}
    config.update(overrides)
    config["is_customized"] = bool(overrides)
    return config


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
    # Populated only when include_s3_data was requested. Must be a declared
    # field — response_model filtering silently drops undeclared keys.
    s3_backup_metadata: dict | None = None


async def _create_mongodb_backup(created_by: str, *, automatic: bool = False) -> dict:
    """
    Create a MongoDB backup with standard exclusions.

    ``created_by`` is the admin's email for a manual backup and ``"scheduler"``
    for one the background task took; ``automatic`` records the same distinction
    as a flag so the UI can label rows without parsing the email.

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
        # Instance branding: the overrides singleton and the uploaded logo
        # bytes it points at. Both are needed, or a restore brings back every
        # dashboard's `brand_theme` while losing the instance identity those
        # themes inherit from.
        "instance_settings": {"collection": instance_settings_collection, "exclude_filter": {}},
        "branding_assets": {"collection": branding_assets_collection, "exclude_filter": {}},
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
            "created_by": created_by,
            "automatic": automatic,
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
        mongodb_backup = await _create_mongodb_backup(current_user.email)

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

        backup_filename = _write_backup_file(
            enhanced_backup, mongodb_backup["backup_metadata"]["backup_id"]
        )
        prune_expired_backups()

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


class BackupListItem(BaseModel):
    backup_id: str
    filename: str
    size_mb: float
    created: str
    created_by: str = "unknown"
    total_documents: int = 0
    collections: list[str] = []
    depictio_version: str | None = None
    # Set only on the backup this deployment's data was last restored from, so
    # the admin can tell which snapshot the live data actually came from.
    restored_at: str | None = None
    restored_by: str | None = None
    # False for legacy backups without a .sha256 sidecar — those can only be
    # restored with allow_unverified=true.
    has_checksum: bool = False
    # True for snapshots the scheduler took. Absent in backups written before
    # scheduled backups existed, which read back as manual.
    is_automatic: bool = False


class BackupListResponse(BaseModel):
    success: bool
    backups: list[BackupListItem]
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
    warnings: list = []


class BackupUploadResponse(BaseModel):
    success: bool
    message: str
    backup_id: str | None = None
    filename: str | None = None
    # Validation runs automatically on upload; the file is stored either way —
    # the restore endpoint's validation gate is what protects the database.
    validation: BackupValidateResponse | None = None


class BackupRestoreRequest(BaseModel):
    backup_id: str
    dry_run: bool = True
    collections: list[str] | None = None  # If None, restore all collections
    # Escape hatch for legacy backups created before checksum sidecars existed.
    # Only bypasses a *missing* checksum; a checksum *mismatch* is never bypassable.
    allow_unverified: bool = False
    # Escape hatch for the pre-restore Pydantic validation gate. Restoring
    # documents that fail model validation can leave the app broken.
    skip_validation: bool = False


class BackupRestoreResponse(BaseModel):
    success: bool
    message: str
    restored_collections: dict = {}
    total_restored: int = 0
    errors: list = []


class BackupScheduleResponse(BaseModel):
    """The schedule in force, plus when it last ran and when it runs next."""

    enabled: bool
    interval_hours: int
    retention_days: int
    # Grandfather-father-son tiers past retention_days; 0 means the tier is off.
    weekly_weeks: int = 0
    monthly_months: int = 0
    # "HH:MM" UTC anchor for the schedule grid; null means a rolling schedule.
    time_of_day: str | None = None
    last_run: str | None = None
    next_run: str | None = None
    # True once any field has been set from the Backups tab, so the UI can say
    # why this deployment's env vars are no longer what is in force.
    is_customized: bool = False


class BackupScheduleUpdate(BaseModel):
    """Partial update of the schedule. Omitted fields are left as they are."""

    enabled: bool | None = None
    # One hour is the floor because a snapshot is the size of the whole
    # database; a year is a generous ceiling that still rejects typos.
    interval_hours: int | None = Field(default=None, ge=1, le=8760)
    # 0 means "keep forever"; ten years is the ceiling.
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    # Retention tiers past retention_days. 0 turns a tier off; the ceilings are
    # generous enough for any real policy while still rejecting typos.
    weekly_weeks: int | None = Field(default=None, ge=0, le=520)
    monthly_months: int | None = Field(default=None, ge=0, le=120)
    # "HH:MM" on a 24-hour clock, UTC. The empty string clears the anchor and
    # returns the schedule to rolling; null means "leave it as it is".
    time_of_day: str | None = Field(default=None, pattern=r"^$|^([01]\d|2[0-3]):([0-5]\d)$")


def _schedule_response() -> BackupScheduleResponse:
    """Build the schedule payload from the config in force."""
    config = get_backup_schedule_config()

    last_run = _as_utc(get_auto_backup_state().get("last_run_at"))
    # _NEVER_RAN is a sentinel, not a real run: report it as "never".
    if last_run is not None and last_run <= _NEVER_RAN:
        last_run = None

    anchor_minutes = parse_time_of_day(config["time_of_day"])
    interval_seconds = config["interval_hours"] * 3600

    next_run = None
    if config["enabled"]:
        if anchor_minutes is None:
            # With no run on record the first tick fires as soon as the loop wakes.
            base = last_run or datetime.now(timezone.utc)
            next_run = base + timedelta(seconds=interval_seconds)
        else:
            slot = scheduled_slot(datetime.now(timezone.utc), interval_seconds, anchor_minutes)
            # An unclaimed current slot is itself the next run: it fires on the
            # next poll rather than waiting a further interval.
            next_run = (
                slot
                if last_run is None or last_run < slot
                else slot + timedelta(seconds=interval_seconds)
            )

    return BackupScheduleResponse(
        enabled=config["enabled"],
        interval_hours=config["interval_hours"],
        retention_days=config["retention_days"],
        weekly_weeks=config["weekly_weeks"],
        monthly_months=config["monthly_months"],
        time_of_day=config["time_of_day"] or None,
        last_run=last_run.isoformat() if last_run else None,
        next_run=next_run.isoformat() if next_run else None,
        is_customized=config["is_customized"],
    )


@backup_endpoint_router.get("/schedule", response_model=BackupScheduleResponse)
async def get_backup_schedule(
    current_user: User = Depends(get_current_user),
):
    """Report whether scheduled backups run, how often, and when they last did."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only administrators can view the backup schedule",
        )
    return _schedule_response()


@backup_endpoint_router.put("/schedule", response_model=BackupScheduleResponse)
async def update_backup_schedule(
    request: BackupScheduleUpdate,
    current_user: User = Depends(get_current_user),
):
    """Turn scheduled backups on or off, and set the interval and retention.

    Stored in MongoDB rather than pushed back into the environment: the running
    scheduler re-reads this on every tick, so a change takes effect without a
    restart, and every worker picks it up at once.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only administrators can change the backup schedule",
        )

    updates = {
        field: value
        for field, value in request.model_dump().items()
        if field in SCHEDULE_FIELDS and value is not None
    }
    if not updates:
        raise HTTPException(status_code=422, detail="No schedule fields to update.")

    try:
        initialization_collection.update_one(
            {"_id": AUTO_BACKUP_STATE_ID},
            # last_run_at must exist for the claim query to ever match, and this
            # update can be what creates the document.
            {"$set": updates, "$setOnInsert": {"last_run_at": _NEVER_RAN}},
            upsert=True,
        )
    except Exception as exc:
        logger.error(f"Failed to update the backup schedule: {exc}")
        raise HTTPException(status_code=500, detail="Failed to update the backup schedule.")

    logger.info(f"Admin user {current_user.email} updated the backup schedule: {updates}")
    return _schedule_response()


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

        # Read once for the whole listing rather than per row.
        last_restore = get_last_restore_state()
        restored_backup_id = last_restore.get("backup_id")
        restored_at = _as_utc(last_restore.get("restored_at"))

        backup_files = []
        for filename in os.listdir(backup_dir):
            if filename.startswith("depictio_backup_") and filename.endswith(".json"):
                file_path = os.path.join(backup_dir, filename)
                file_stat = os.stat(file_path)

                # Extract backup ID from filename
                backup_id = filename.replace("depictio_backup_", "").replace(".json", "")
                has_checksum = os.path.exists(f"{file_path}.sha256")

                # Try to read metadata
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                        metadata = data.get("backup_metadata", {})

                    backup_info = BackupListItem(
                        backup_id=backup_id,
                        filename=filename,
                        size_mb=round(file_stat.st_size / (1024 * 1024), 2),
                        created=datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        created_by=metadata.get("created_by", "unknown"),
                        total_documents=metadata.get("total_documents", 0),
                        collections=metadata.get("collections", []),
                        depictio_version=metadata.get("depictio_version"),
                        has_checksum=has_checksum,
                        is_automatic=bool(metadata.get("automatic", False)),
                        restored_at=(
                            restored_at.isoformat()
                            if restored_at and backup_id == restored_backup_id
                            else None
                        ),
                        restored_by=(
                            last_restore.get("restored_by")
                            if backup_id == restored_backup_id
                            else None
                        ),
                    )
                except Exception:
                    # If can't read metadata, just use file info
                    backup_info = BackupListItem(
                        backup_id=backup_id,
                        filename=filename,
                        size_mb=round(file_stat.st_size / (1024 * 1024), 2),
                        created=datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        has_checksum=has_checksum,
                        restored_at=(
                            restored_at.isoformat()
                            if restored_at and backup_id == restored_backup_id
                            else None
                        ),
                        restored_by=(
                            last_restore.get("restored_by")
                            if backup_id == restored_backup_id
                            else None
                        ),
                    )

                backup_files.append(backup_info)

        # Sort by creation time (newest first)
        backup_files.sort(key=lambda x: x.created, reverse=True)

        return BackupListResponse(success=True, backups=backup_files, count=len(backup_files))

    except Exception as e:
        logger.error(f"Failed to list backups: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list backups.")


def _build_validate_response(result: dict) -> BackupValidateResponse:
    """Map a ``validate_backup_file`` result dict onto the API response model.

    Shared by ``/validate`` and ``/upload`` so both surfaces report validation
    identically.
    """
    return BackupValidateResponse(
        success=True,
        message="Validation completed",
        valid=result.get("valid", False),
        total_documents=result.get("total_documents", 0),
        valid_documents=result.get("valid_documents", 0),
        invalid_documents=result.get("invalid_documents", 0),
        collections_validated=result.get("collections_validated", {}),
        errors=result.get("errors", []),
        warnings=result.get("warnings", []),
    )


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

        return _build_validate_response(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backup validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Backup validation failed.")


@backup_endpoint_router.get("/download/{backup_id}")
async def download_backup(
    backup_id: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download a backup file from the server.

    Streams the backup JSON as an attachment so admins can keep off-server
    copies (and re-upload them later via ``/upload``).
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can download backups"
        )

    # Reject malformed backup_id before it touches the filesystem.
    _validate_backup_id(backup_id)

    backup_dir = settings.backup.backup_path
    backup_path = _resolve_backup_path(backup_dir, backup_id)

    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup not found: {backup_id}")

    # The filename is derived from the strictly validated backup_id, so it is
    # plain ASCII — no RFC 5987 encoding needed (unlike migrate's export_project
    # which embeds user-controlled project names).
    return FileResponse(
        backup_path,
        media_type="application/json",
        filename=f"depictio_backup_{backup_id}.json",
    )


def _mint_upload_backup_id(backup_dir: str) -> str:
    """Mint a fresh server-side backup_id for an uploaded file.

    Uses the same ``YYYYMMDD_HHMMSS`` convention as ``/create``; bumps by one
    second while the target path already exists so rapid uploads cannot
    overwrite each other.
    """
    timestamp = datetime.now()
    while True:
        backup_id = timestamp.strftime("%Y%m%d_%H%M%S")
        if not os.path.exists(os.path.join(backup_dir, f"depictio_backup_{backup_id}.json")):
            return backup_id
        timestamp += timedelta(seconds=1)


@backup_endpoint_router.post("/upload", response_model=BackupUploadResponse)
async def upload_backup(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a backup file to the server and validate it.

    The uploaded file is stored in the backup directory under a freshly minted
    server-side backup_id (with a SHA-256 sidecar), making it a first-class
    backup: it appears in ``/list`` and can be validated, downloaded, and
    restored like any server-created backup. Validation runs automatically and
    its result is returned; a failing validation does not reject the upload —
    the restore endpoint refuses invalid backups by default.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Access denied: Only administrators can upload backups"
        )

    try:
        # Read fully into memory (matches the repo's upload pattern); the size
        # cap bounds memory usage.
        body = await file.read()
        if len(body) > MAX_BACKUP_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Uploaded backup exceeds the maximum allowed size of "
                    f"{MAX_BACKUP_UPLOAD_BYTES // (1024 * 1024)} MB."
                ),
            )

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Uploaded file is not valid JSON.")

        if (
            not isinstance(payload, dict)
            or "data" not in payload
            or not isinstance(payload["data"], dict)
        ):
            raise HTTPException(
                status_code=400,
                detail="Not a depictio backup file (missing 'data' section).",
            )

        backup_dir = settings.backup.backup_path
        os.makedirs(backup_dir, exist_ok=True)

        # Assign a server-side id so the filename-derived id and the metadata
        # agree; everything else in the file is preserved.
        backup_id = _mint_upload_backup_id(backup_dir)
        metadata = payload.setdefault("backup_metadata", {})
        if isinstance(metadata, dict):
            metadata["backup_id"] = backup_id

        backup_filename = f"depictio_backup_{backup_id}.json"
        backup_path = _resolve_backup_path(backup_dir, backup_id)

        with open(backup_path, "w") as backup_file:
            json.dump(payload, backup_file, indent=2, default=str)

        # Same sidecar convention as /create; computed over the re-serialized
        # file so the checksum always matches what is on disk.
        backup_checksum = _compute_file_sha256(backup_path)
        with open(f"{backup_path}.sha256", "w") as checksum_file:
            checksum_file.write(f"{backup_checksum}  {backup_filename}\n")

        logger.info(
            f"Admin user {current_user.email} uploaded backup {backup_filename} ({len(body)} bytes)"
        )

        from depictio.cli.cli.utils.backup_validation import validate_backup_file

        validation = _build_validate_response(validate_backup_file(backup_path))

        return BackupUploadResponse(
            success=True,
            message="Backup uploaded"
            + (" and validated" if validation.valid else "; validation found errors"),
            backup_id=backup_id,
            filename=backup_filename,
            validation=validation,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backup upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Backup upload failed.")


def _convert_complex_objects_to_strings(obj):
    """Convert DBRef and ObjectId to strings for JSON serialization."""
    if isinstance(obj, DBRef):
        return str(obj.id)
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {key: _convert_complex_objects_to_strings(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_convert_complex_objects_to_strings(item) for item in obj]
    return obj


def _restore_complex_objects(obj):
    """Re-hydrate the ObjectIds that backup serialization flattened to strings.

    Backups are plain JSON, so ``_convert_complex_objects_to_strings`` turns
    *every* ObjectId in a document into a string, not just the top-level
    ``_id``: ``dashboards.project_id``, ``permissions.owners[]._id``,
    ``projects.workflows[].data_collections[]._id``,
    ``stored_metadata[].dc_id`` and so on. Inserting those back as strings
    produces documents Mongo can no longer join — the dashboard listing filters
    on ``{"project_id": {"$in": [<ObjectId>]}}``, which matches nothing, so
    every dashboard silently disappears after a restore.

    The rule mirrors ``MongoModel.mongo()``, the writer the application itself
    uses: any string that is a valid ObjectId is one. DBRefs cannot be rebuilt
    (the backup only kept ``str(ref.id)``, dropping the collection name) and
    come back as plain ObjectIds, which is the shape ``db_init`` writes.
    """
    if isinstance(obj, dict):
        return {key: _restore_complex_objects(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_restore_complex_objects(item) for item in obj]
    if isinstance(obj, str) and ObjectId.is_valid(obj):
        return ObjectId(obj)
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

    Before any data is touched, the backup is validated against the current
    Pydantic models (same validator as /validate); restores of invalid backups
    are refused unless skip_validation=true.
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
            "instance_settings": instance_settings_collection,
            "branding_assets": branding_assets_collection,
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

        # Validation gate: refuse to wipe collections for documents that fail
        # Pydantic model validation. Same validator as /validate and the CLI,
        # so UI and CLI share one "validate then restore" path. Scoped to the
        # collections actually being restored, so a partial restore is not
        # blocked by unrelated broken documents.
        if not request.skip_validation:
            from depictio.cli.cli.utils.backup_validation import validate_backup_file

            validation_result = validate_backup_file(backup_path)
            per_collection = validation_result.get("collections_validated", {})
            invalid_selected = sum(
                per_collection.get(name, {}).get("invalid", 0) for name in collections_to_restore
            )
            if invalid_selected > 0:
                # validate_backup_file formats errors as "Document {i} in {collection}: ..."
                selected_errors = [
                    err
                    for err in validation_result.get("errors", [])
                    if any(f" in {name}:" in err for name in collections_to_restore)
                ]
                return BackupRestoreResponse(
                    success=False,
                    message=(
                        f"Backup failed model validation: {invalid_selected} invalid "
                        "document(s) in the selected collections. Refusing to restore. "
                        "Run validation for details, or set skip_validation=true to "
                        "override at your own risk."
                    ),
                    errors=selected_errors[:25],
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
                documents = [_restore_complex_objects(doc) for doc in data_section[collection_name]]

                for doc in documents:
                    # Backups written from Mongo carry ``_id``; documents dumped
                    # through a Pydantic model carry ``id``. Accept both.
                    if "id" in doc:
                        doc["_id"] = doc.pop("id")

                # Restore is wipe-and-replace, so a failed insert would leave
                # the collection empty. Keep the previous contents in memory and
                # put them back if the insert fails, rather than losing both the
                # old and the new data.
                previous_documents = list(collection.find({}))
                collection.delete_many({})
                if documents:
                    try:
                        collection.insert_many(documents)
                    except Exception as e:
                        logger.error(f"Failed to restore {collection_name}: {e}")
                        try:
                            collection.delete_many({})
                            if previous_documents:
                                collection.insert_many(previous_documents)
                            logger.warning(
                                f"Rolled {collection_name} back to its pre-restore contents "
                                f"({len(previous_documents)} documents)"
                            )
                        except Exception as rollback_error:
                            logger.error(
                                f"Rollback of {collection_name} failed after a failed restore; "
                                f"the collection may be empty: {rollback_error}"
                            )
                        raise

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

        # Mark the source only once the restore actually stuck: a partial
        # restore leaves the deployment in a state no single backup describes,
        # so labelling a row "restored" there would be a lie.
        if not errors:
            record_last_restore(request.backup_id, current_user.email)

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
