"""Unit tests for the central authorization chokepoint (depictio.api.v1.permissions)."""

from types import SimpleNamespace

import mongomock
from bson import ObjectId

from depictio.api.v1.permissions import (
    LEVELS,
    build_access_query,
    get_administered_group_ids,
    get_user_group_ids,
    has_permission,
    resolve_effective_role,
)


def make_user(user_id=None, is_admin=False, is_anonymous=False):
    return SimpleNamespace(id=user_id or ObjectId(), is_admin=is_admin, is_anonymous=is_anonymous)


class TestBuildAccessQuery:
    def test_admin_gets_no_filter(self):
        assert build_access_query(make_user(is_admin=True), "viewer") == {}
        assert build_access_query(make_user(is_admin=True), "owner") == {}

    def test_anonymous_gets_public_only(self):
        for level in LEVELS:
            assert build_access_query(make_user(is_anonymous=True), level) == {"is_public": True}

    def test_owner_level_direct_only(self):
        user = make_user()
        query = build_access_query(user, "owner")
        assert query == {"$or": [{"permissions.owners._id": ObjectId(str(user.id))}]}

    def test_editor_level_cumulative(self):
        user = make_user()
        clauses = build_access_query(user, "editor")["$or"]
        fields = [next(iter(clause)) for clause in clauses]
        assert fields == ["permissions.owners._id", "permissions.editors._id"]

    def test_viewer_level_includes_public_and_wildcard(self):
        user = make_user()
        clauses = build_access_query(user, "viewer")["$or"]
        assert {"permissions.viewers": "*"} in clauses
        assert {"is_public": True} in clauses

    def test_group_clauses_added_per_level(self):
        user = make_user()
        group_id = ObjectId()
        clauses = build_access_query(user, "editor", [group_id])["$or"]
        assert {"permissions.group_owners._id": {"$in": [group_id]}} in clauses
        assert {"permissions.group_editors._id": {"$in": [group_id]}} in clauses
        assert not any("permissions.group_viewers._id" in clause for clause in clauses)

    def test_no_group_clauses_without_groups(self):
        user = make_user()
        clauses = build_access_query(user, "viewer", [])["$or"]
        assert not any("group_" in next(iter(clause)) for clause in clauses)

    def test_unknown_level_raises(self):
        try:
            build_access_query(make_user(), "superuser")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestResolveEffectiveRole:
    def test_none_doc(self):
        assert resolve_effective_role(None, make_user()) is None

    def test_admin_is_owner(self):
        assert resolve_effective_role({}, make_user(is_admin=True)) == "owner"

    def test_anonymous_public_floor(self):
        anon = make_user(is_anonymous=True)
        assert resolve_effective_role({"is_public": True, "permissions": {}}, anon) == "viewer"
        assert resolve_effective_role({"permissions": {}}, anon) is None

    def test_direct_roles(self):
        user = make_user()
        uid = ObjectId(str(user.id))
        assert resolve_effective_role({"permissions": {"owners": [{"_id": uid}]}}, user) == "owner"
        assert (
            resolve_effective_role({"permissions": {"editors": [{"_id": uid}]}}, user) == "editor"
        )
        assert (
            resolve_effective_role({"permissions": {"viewers": [{"_id": uid}]}}, user) == "viewer"
        )

    def test_string_ids_in_doc_match(self):
        user = make_user()
        doc = {"permissions": {"owners": [{"_id": str(user.id)}]}}
        assert resolve_effective_role(doc, user) == "owner"

    def test_group_role(self):
        user = make_user()
        group_id = ObjectId()
        doc = {"permissions": {"group_editors": [{"_id": group_id, "name": "lab"}]}}
        assert resolve_effective_role(doc, user, [group_id]) == "editor"
        assert resolve_effective_role(doc, user, []) is None

    def test_highest_wins_direct_vs_group(self):
        user = make_user()
        uid = ObjectId(str(user.id))
        group_id = ObjectId()
        doc = {
            "permissions": {
                "viewers": [{"_id": uid}],
                "group_owners": [{"_id": group_id, "name": "lab"}],
            }
        }
        assert resolve_effective_role(doc, user, [group_id]) == "owner"
        assert resolve_effective_role(doc, user, []) == "viewer"

    def test_wildcard_and_public_floor(self):
        user = make_user()
        assert resolve_effective_role({"permissions": {"viewers": ["*"]}}, user) == "viewer"
        assert resolve_effective_role({"is_public": True, "permissions": {}}, user) == "viewer"

    def test_no_access(self):
        doc = {"permissions": {"owners": [{"_id": ObjectId()}]}}
        assert resolve_effective_role(doc, make_user()) is None


class TestHasPermission:
    def test_matrix(self):
        user = make_user()
        uid = ObjectId(str(user.id))
        editor_doc = {"permissions": {"editors": [{"_id": uid}]}}
        assert has_permission(editor_doc, user, "viewer")
        assert has_permission(editor_doc, user, "editor")
        assert not has_permission(editor_doc, user, "owner")

    def test_group_owner_grants_everything(self):
        user = make_user()
        group_id = ObjectId()
        doc = {"permissions": {"group_owners": [{"_id": group_id, "name": "lab"}]}}
        for required in LEVELS:
            assert has_permission(doc, user, required, [group_id])


class TestGroupLookups:
    def test_membership_and_admin_lookup(self):
        collection = mongomock.MongoClient().db.groups
        user_id = ObjectId()
        member_group = collection.insert_one(
            {"name": "lab-a", "users_ids": [user_id], "admin_ids": []}
        ).inserted_id
        admin_group = collection.insert_one(
            {"name": "lab-b", "users_ids": [user_id], "admin_ids": [user_id]}
        ).inserted_id
        collection.insert_one({"name": "other", "users_ids": [ObjectId()], "admin_ids": []})

        assert set(get_user_group_ids(user_id, collection)) == {member_group, admin_group}
        assert get_administered_group_ids(user_id, collection) == [admin_group]
        assert get_user_group_ids(str(user_id), collection) == get_user_group_ids(
            user_id, collection
        )

    def test_none_user_id(self):
        assert get_user_group_ids(None) == []
        assert get_administered_group_ids(None) == []
