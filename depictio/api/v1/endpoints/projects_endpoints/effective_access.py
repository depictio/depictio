"""Who can open a project, whichever way they were given access.

A project is shared with users directly (``owners``/``editors``/``viewers``)
and with groups (``group_owners``/``group_editors``/``group_viewers``). The
permissions page lists the two kinds apart, so nothing shows the people a group
grant actually reaches, nor the net role of someone listed on both sides. This
resolves both into one row per person, highest role wins, with every grant that
contributes to it, mirroring ``permissions.resolve_effective_role``.
"""

from typing import Any

from bson import ObjectId

# Highest first: the first role a person holds is their effective one.
ROLES = ("owner", "editor", "viewer")
_DIRECT_FIELDS = {"owner": "owners", "editor": "editors", "viewer": "viewers"}
_GROUP_FIELDS = {"owner": "group_owners", "editor": "group_editors", "viewer": "group_viewers"}


def _entry_id(entry: Any) -> ObjectId | None:
    """The ObjectId a permission entry points at; None for ``"*"`` or garbage."""
    raw = entry.get("_id", entry.get("id")) if isinstance(entry, dict) else entry
    try:
        return ObjectId(str(raw))
    except Exception:
        return None


def referenced_group_ids(permissions: dict) -> list[ObjectId]:
    """Every group the permissions mention, in any role."""
    ids = (
        _entry_id(entry)
        for field in _GROUP_FIELDS.values()
        for entry in permissions.get(field) or []
    )
    return list(dict.fromkeys(oid for oid in ids if oid is not None))


def referenced_user_ids(permissions: dict, group_docs: list[dict]) -> list[ObjectId]:
    """Every user a direct grant or a group membership mentions."""
    ids = [
        _entry_id(entry)
        for field in _DIRECT_FIELDS.values()
        for entry in permissions.get(field) or []
    ]
    ids += [_entry_id(uid) for doc in group_docs for uid in doc.get("users_ids") or []]
    return list(dict.fromkeys(oid for oid in ids if oid is not None))


def compute_effective_access(
    permissions: dict, group_docs: list[dict], user_docs: dict[ObjectId, dict]
) -> dict:
    """One row per person who can open the project through a grant.

    ``everyone_can_view`` is the ``"*"`` viewer wildcard; ``is_public`` and
    sysadmins are not rows, they reach every project and the page says so.
    A user id with no document (deleted account) is skipped, like the group
    detail does.
    """
    people: dict[ObjectId, dict] = {}

    def grant(user_id: ObjectId | None, role: str, source: dict) -> None:
        user_doc = user_docs.get(user_id) if user_id is not None else None
        if user_doc is None:
            return
        row = people.setdefault(
            user_id,
            {
                "id": str(user_id),
                "email": user_doc.get("email", ""),
                "display_name": user_doc.get("display_name"),
                "role": role,
                "sources": [],
            },
        )
        if ROLES.index(role) < ROLES.index(row["role"]):
            row["role"] = role
        row["sources"].append({**source, "role": role})

    groups_by_id = {doc["_id"]: doc for doc in group_docs}
    everyone_can_view = False
    for role in ROLES:
        for entry in permissions.get(_DIRECT_FIELDS[role]) or []:
            if entry == "*" or (isinstance(entry, dict) and entry.get("email") == "*"):
                everyone_can_view = True
                continue
            grant(_entry_id(entry), role, {"kind": "direct"})
        for entry in permissions.get(_GROUP_FIELDS[role]) or []:
            group = groups_by_id.get(_entry_id(entry))
            if group is None:
                continue
            source = {
                "kind": "group",
                "group_id": str(group["_id"]),
                "group_name": group.get("name", ""),
            }
            for member_id in group.get("users_ids") or []:
                grant(_entry_id(member_id), role, source)

    rows = sorted(people.values(), key=lambda r: (ROLES.index(r["role"]), r["email"].lower()))
    return {"users": rows, "everyone_can_view": everyone_can_view}
