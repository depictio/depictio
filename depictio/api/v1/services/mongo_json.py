"""JSON <-> Mongo helpers shared by backup restore and project migration.

Backups and migrate bundles are plain JSON: every ObjectId was flattened to a
string and every datetime to an ISO string. These helpers undo that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import DBRef, ObjectId


def convert_complex_objects_to_strings(obj: Any) -> Any:
    """Convert DBRef and ObjectId to strings for JSON serialization."""
    if isinstance(obj, DBRef):
        return str(obj.id)
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {key: convert_complex_objects_to_strings(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [convert_complex_objects_to_strings(item) for item in obj]
    return obj


def restore_complex_objects(obj: Any) -> Any:
    """Re-hydrate the ObjectIds that JSON serialization flattened to strings.

    ``convert_complex_objects_to_strings`` turns *every* ObjectId in a document
    into a string, not just the top-level ``_id``: ``dashboards.project_id``,
    ``permissions.owners[]._id``, ``projects.workflows[].data_collections[]._id``,
    ``stored_metadata[].dc_id`` and so on. Inserting those back as strings
    produces documents Mongo can no longer join: the dashboard listing filters
    on ``{"project_id": {"$in": [<ObjectId>]}}``, which matches nothing.

    The rule mirrors ``MongoModel.mongo()``, the writer the application itself
    uses: any string that is a valid ObjectId is one. DBRefs cannot be rebuilt
    (only ``str(ref.id)`` was kept) and come back as plain ObjectIds, which is
    the shape ``db_init`` writes.
    """
    if isinstance(obj, dict):
        return {key: restore_complex_objects(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [restore_complex_objects(item) for item in obj]
    if isinstance(obj, str) and ObjectId.is_valid(obj):
        return ObjectId(obj)
    return obj


def parse_json_datetime(value: Any) -> Any:
    """A datetime written as an ISO string, back as a UTC datetime.

    Anything that is not such a string is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_json_datetime_naive(value: Any) -> Any:
    """Like ``parse_json_datetime``, but naive UTC: the shape PyMongo reads back."""
    parsed = parse_json_datetime(value)
    if isinstance(parsed, datetime) and parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
