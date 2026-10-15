"""Effective access: one row per person, highest role wins, every grant listed."""

from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints.effective_access import (
    compute_effective_access,
    referenced_group_ids,
    referenced_user_ids,
)

ALICE, BOB, CARA, GONE = (ObjectId() for _ in range(4))
LAB, CORE = ObjectId(), ObjectId()

USERS = {
    ALICE: {"_id": ALICE, "email": "alice@x.org", "display_name": "Alice"},
    BOB: {"_id": BOB, "email": "bob@x.org"},
    CARA: {"_id": CARA, "email": "cara@x.org"},
}
GROUPS = [
    {"_id": LAB, "name": "lab", "users_ids": [ALICE, BOB, GONE]},
    {"_id": CORE, "name": "core", "users_ids": [BOB, CARA]},
]


def _rows(result):
    return {row["email"]: row for row in result["users"]}


def test_group_members_get_the_group_role_and_a_deleted_account_is_skipped():
    perms = {"group_viewers": [{"_id": LAB, "name": "lab"}]}

    rows = _rows(compute_effective_access(perms, GROUPS, USERS))

    assert set(rows) == {"alice@x.org", "bob@x.org"}
    assert rows["alice@x.org"]["role"] == "viewer"
    assert rows["alice@x.org"]["sources"] == [
        {"kind": "group", "group_id": str(LAB), "group_name": "lab", "role": "viewer"}
    ]


def test_the_highest_role_wins_and_every_grant_is_kept():
    perms = {
        "viewers": [{"_id": BOB, "email": "bob@x.org"}],
        "group_editors": [{"_id": LAB}],
        "group_viewers": [{"_id": CORE}],
    }

    bob = _rows(compute_effective_access(perms, GROUPS, USERS))["bob@x.org"]

    assert bob["role"] == "editor"
    # Highest grant first, so the row's role reads off its first source.
    assert [(s["kind"], s["role"]) for s in bob["sources"]] == [
        ("group", "editor"),
        ("direct", "viewer"),
        ("group", "viewer"),
    ]


def test_rows_are_ordered_by_role_then_email():
    perms = {
        "owners": [{"_id": CARA}],
        "viewers": [{"_id": ALICE}],
        "group_editors": [{"_id": CORE}],
    }

    result = compute_effective_access(perms, GROUPS, USERS)

    assert [(r["email"], r["role"]) for r in result["users"]] == [
        ("cara@x.org", "owner"),
        ("bob@x.org", "editor"),
        ("alice@x.org", "viewer"),
    ]


def test_the_wildcard_is_a_flag_not_a_row():
    for entry in ("*", {"_id": "*", "email": "*"}):
        result = compute_effective_access({"viewers": [entry]}, [], USERS)
        assert result == {"users": [], "everyone_can_view": True}


def test_a_group_missing_from_the_lookup_grants_nothing():
    result = compute_effective_access({"group_owners": [{"_id": ObjectId()}]}, GROUPS, USERS)

    assert result["users"] == []


def test_referenced_ids_cover_every_role_and_membership():
    perms = {
        "owners": [{"_id": ALICE}],
        "group_viewers": [{"_id": LAB}],
        "group_editors": [{"_id": CORE}, {"_id": LAB}],
    }

    assert set(referenced_group_ids(perms)) == {LAB, CORE}
    assert set(referenced_user_ids(perms, GROUPS)) == {ALICE, BOB, CARA, GONE}
