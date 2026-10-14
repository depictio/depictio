"""The member count in the group list matches the member list it opens.

A membership array can hold ids with no user document behind them (the seeded
test user on an instance that never created it, a deleted account). The detail
view skips those, so the list must not count them either.
"""

import mongomock
from bson import ObjectId

from depictio.api.v1.endpoints.groups_endpoints import routes


def _users(*ids: ObjectId):
    collection = mongomock.MongoClient().db.users
    if ids:
        collection.insert_many([{"_id": i, "email": f"{i}@example.org"} for i in ids])
    return collection


def test_dangling_member_ids_are_not_counted(monkeypatch):
    me, ghost = ObjectId(), ObjectId()
    monkeypatch.setattr(routes, "users_collection", _users(me))
    group = {"_id": ObjectId(), "name": "users", "users_ids": [ghost, me]}

    live = routes._live_user_ids([group])
    summary = routes._group_summary(group, live)

    assert summary.member_count == 1


def test_count_matches_the_detail_member_list(monkeypatch):
    me, other, ghost = ObjectId(), ObjectId(), ObjectId()
    monkeypatch.setattr(routes, "users_collection", _users(me, other))
    group = {"_id": ObjectId(), "name": "lab", "users_ids": [me, ghost, other]}

    live = routes._live_user_ids([group])

    assert routes._group_summary(group, live).member_count == 2
    assert len(routes._group_detail(group).members) == 2


def test_a_group_with_no_members_needs_no_lookup(monkeypatch):
    monkeypatch.setattr(routes, "users_collection", _users())
    group = {"_id": ObjectId(), "name": "empty", "users_ids": []}

    assert routes._live_user_ids([group]) == set()
    assert routes._group_summary(group, set()).member_count == 0
