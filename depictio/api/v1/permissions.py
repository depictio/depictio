"""Central, group-aware authorization helpers for permission-carrying documents.

Every enforcement site (projects, dashboards, workflows, files, deltatables,
multiqc, events, screenshots, ...) should build its Mongo predicate with
``build_access_query`` or evaluate an in-memory document with
``has_permission`` / ``resolve_effective_role`` instead of hand-rolling
``$or`` clauses. This is the single place where the semantics live:

- sysadmins (``user.is_admin``) can do everything;
- anonymous users only ever see public documents;
- a user's effective role is the HIGHEST of their direct role
  (``permissions.owners/editors/viewers``) and any role granted to a group
  they belong to (``permissions.group_owners/group_editors/group_viewers``);
- ``is_public`` and the ``"*"`` viewers wildcard grant a viewer floor.

Group membership is resolved live from the ``groups`` collection
(``get_user_group_ids``) — it is never denormalized onto users or tokens, so
membership changes take effect immediately. The collection is injectable so
sync contexts with their own Mongo client (e.g. the Celery screenshot worker)
can pass theirs.
"""

from typing import Any

from bson import ObjectId

LEVELS: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}

# permission level -> (direct permission arrays, group permission arrays)
# cumulative: requiring "editor" also accepts owners, etc.
_DIRECT_FIELDS: dict[str, list[str]] = {
    "owner": ["owners"],
    "editor": ["owners", "editors"],
    "viewer": ["owners", "editors", "viewers"],
}
_GROUP_FIELDS: dict[str, list[str]] = {
    "owner": ["group_owners"],
    "editor": ["group_owners", "group_editors"],
    "viewer": ["group_owners", "group_editors", "group_viewers"],
}


def _default_groups_collection():
    # Lazy import: keeps this module importable from contexts (Celery worker,
    # tests) that construct their own Mongo client and inject the collection.
    from depictio.api.v1.db import groups_collection

    return groups_collection


def _as_object_id(value: Any) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(str(value))


def get_user_group_ids(user_id: Any, groups_collection=None) -> list[ObjectId]:
    """IDs of every group the user belongs to (source of truth: groups.users_ids)."""
    if user_id is None:
        return []
    collection = (
        groups_collection if groups_collection is not None else _default_groups_collection()
    )
    cursor = collection.find({"users_ids": _as_object_id(user_id)}, {"_id": 1})
    return [doc["_id"] for doc in cursor]


def get_administered_group_ids(user_id: Any, groups_collection=None) -> list[ObjectId]:
    """IDs of every group the user is a group admin of."""
    if user_id is None:
        return []
    collection = (
        groups_collection if groups_collection is not None else _default_groups_collection()
    )
    cursor = collection.find({"admin_ids": _as_object_id(user_id)}, {"_id": 1})
    return [doc["_id"] for doc in cursor]


def build_access_query(
    user: Any, level: str = "viewer", group_ids: list[ObjectId] | None = None
) -> dict:
    """Mongo predicate selecting documents the user can access at ``level``.

    Returns ``{}`` for sysadmins (no filtering). Merge the result into an
    existing query with ``{**base, **build_access_query(...)}`` or inside an
    aggregation ``$match`` stage.
    """
    if level not in LEVELS:
        raise ValueError(f"Unknown permission level: {level!r} (expected one of {list(LEVELS)})")

    if getattr(user, "is_admin", False):
        return {}

    if getattr(user, "is_anonymous", False):
        return {"is_public": True}

    user_id = _as_object_id(user.id)
    clauses: list[dict] = [{f"permissions.{field}._id": user_id} for field in _DIRECT_FIELDS[level]]
    if group_ids:
        clauses.extend(
            {f"permissions.{field}._id": {"$in": list(group_ids)}} for field in _GROUP_FIELDS[level]
        )
    if level == "viewer":
        clauses.append({"permissions.viewers": "*"})
        clauses.append({"is_public": True})

    return {"$or": clauses}


def _entry_id(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    return entry.get("_id", entry.get("id"))


def _id_in_entries(target: ObjectId, entries: list) -> bool:
    for entry in entries:
        entry_id = _entry_id(entry)
        if entry_id is None:
            continue
        try:
            if _as_object_id(entry_id) == target:
                return True
        except Exception:
            continue
    return False


def resolve_effective_role(
    doc: dict | None, user: Any, group_ids: list[ObjectId] | None = None
) -> str | None:
    """Highest role the user holds on the document, or None.

    ``doc`` is a raw Mongo document carrying ``permissions`` (and optionally
    ``is_public``). Direct roles and group-granted roles are merged
    highest-wins; ``is_public`` / the ``"*"`` wildcard grant a viewer floor.
    """
    if doc is None:
        return None

    if getattr(user, "is_admin", False):
        return "owner"

    is_public = bool(doc.get("is_public", False))
    if getattr(user, "is_anonymous", False):
        return "viewer" if is_public else None

    permissions = doc.get("permissions") or {}
    user_id = _as_object_id(user.id)
    group_id_set = {_as_object_id(gid) for gid in (group_ids or [])}

    best: int | None = None

    for role, direct_field, group_field in (
        ("owner", "owners", "group_owners"),
        ("editor", "editors", "group_editors"),
        ("viewer", "viewers", "group_viewers"),
    ):
        entries = permissions.get(direct_field, []) or []
        granted = _id_in_entries(user_id, entries)
        if not granted and group_id_set:
            group_entries = permissions.get(group_field, []) or []
            granted = any(
                gid in group_id_set
                for gid in (
                    _as_object_id(entry_id)
                    for entry_id in (_entry_id(entry) for entry in group_entries)
                    if entry_id is not None
                )
            )
        if granted:
            best = LEVELS[role] if best is None else max(best, LEVELS[role])

    if is_public or "*" in (permissions.get("viewers", []) or []):
        best = LEVELS["viewer"] if best is None else max(best, LEVELS["viewer"])

    if best is None:
        return None
    return next(name for name, value in LEVELS.items() if value == best)


def has_permission(
    doc: dict | None,
    user: Any,
    required: str = "viewer",
    group_ids: list[ObjectId] | None = None,
) -> bool:
    """True if the user's effective role on ``doc`` is at least ``required``."""
    if required not in LEVELS:
        raise ValueError(f"Unknown permission level: {required!r} (expected one of {list(LEVELS)})")
    role = resolve_effective_role(doc, user, group_ids)
    return role is not None and LEVELS[role] >= LEVELS[required]
