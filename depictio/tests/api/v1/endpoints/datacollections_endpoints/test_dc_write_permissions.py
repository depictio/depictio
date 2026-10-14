"""Who may rename, edit the properties of, or delete a data collection.

Rename and properties are metadata edits, so editor level (like creating a data
collection or saving a dashboard). Delete removes the collection's data and
cannot be undone, so owner level (like deleting a dashboard or a project).
Group roles count, a sysadmin passes, and a refusal is the same 404 as a
missing collection. A viewer, direct or through a group, may do none of it.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils

MODULE = "depictio.api.v1.endpoints.datacollections_endpoints.utils"

DC_ID = ObjectId()
PROJECT_ID = ObjectId()
GROUP_ID = ObjectId()


def _user(*, admin: bool = False, anonymous: bool = False):
    return SimpleNamespace(
        id=ObjectId(), email="u@example.org", is_admin=admin, is_anonymous=anonymous
    )


def _project(
    *,
    owners=(),
    editors=(),
    viewers=(),
    group_owners=(),
    group_editors=(),
    group_viewers=(),
    public=False,
):
    def entries(ids):
        return [{"_id": i} for i in ids]

    return {
        "_id": PROJECT_ID,
        "is_public": public,
        "permissions": {
            "owners": entries(owners),
            "editors": entries(editors),
            "viewers": entries(viewers),
            "group_owners": entries(group_owners),
            "group_editors": entries(group_editors),
            "group_viewers": entries(group_viewers),
        },
        "workflows": [{"data_collections": [{"_id": DC_ID, "data_collection_tag": "t"}]}],
    }


def _run(action, user, project, groups=()):
    """Run one write endpoint against ``project``; True if it was allowed."""
    collection = MagicMock()
    collection.find_one.return_value = project
    collection.update_one.return_value = SimpleNamespace(modified_count=1)
    with (
        patch(f"{MODULE}.projects_collection", collection),
        patch(f"{MODULE}.get_user_group_ids", return_value=list(groups)),
        patch(f"{MODULE}._cleanup_s3_delta_table", new=AsyncMock()),
        patch(f"{MODULE}._delete_orphan_links_for_dc", return_value=0),
    ):
        if action == "rename":
            coro = utils._update_data_collection_name(str(DC_ID), "new", user)
        elif action == "properties":
            coro = utils._update_dc_specific_properties(str(DC_ID), {"s3_location": "x"}, user)
        else:
            coro = utils._delete_data_collection_by_id(str(DC_ID), user)
        try:
            asyncio.run(coro)
            return True, collection
        except HTTPException as exc:
            assert exc.status_code == 404
            return False, collection


EDITOR_ACTIONS = ("rename", "properties")


@pytest.mark.parametrize("action", EDITOR_ACTIONS)
class TestMetadataEdits:
    def test_direct_editor_and_owner_may(self, action):
        editor, owner = _user(), _user()
        assert _run(action, editor, _project(editors=[editor.id]))[0]
        assert _run(action, owner, _project(owners=[owner.id]))[0]

    def test_group_editor_and_group_owner_may(self, action):
        member = _user()
        assert _run(action, member, _project(group_editors=[GROUP_ID]), groups=[GROUP_ID])[0]
        assert _run(action, member, _project(group_owners=[GROUP_ID]), groups=[GROUP_ID])[0]

    def test_sysadmin_may(self, action):
        assert _run(action, _user(admin=True), _project())[0]

    def test_viewers_strangers_and_public_visitors_may_not(self, action):
        viewer = _user()
        stranger = _user()
        assert not _run(action, viewer, _project(viewers=[viewer.id]))[0]
        assert not _run(action, viewer, _project(group_viewers=[GROUP_ID]), groups=[GROUP_ID])[0]
        assert not _run(action, stranger, _project(public=True))[0]
        assert not _run(action, _user(anonymous=True), _project(public=True))[0]

    def test_a_refusal_writes_nothing(self, action):
        viewer = _user()
        allowed, collection = _run(action, viewer, _project(viewers=[viewer.id]))
        assert not allowed
        collection.update_one.assert_not_called()


class TestDelete:
    def test_direct_and_group_owner_may(self):
        owner, member = _user(), _user()
        assert _run("delete", owner, _project(owners=[owner.id]))[0]
        assert _run("delete", member, _project(group_owners=[GROUP_ID]), groups=[GROUP_ID])[0]

    def test_sysadmin_may(self):
        assert _run("delete", _user(admin=True), _project())[0]

    def test_editors_and_viewers_may_not_and_nothing_is_touched(self):
        editor, viewer, member = _user(), _user(), _user()
        for user, project, groups in (
            (editor, _project(editors=[editor.id]), ()),
            (member, _project(group_editors=[GROUP_ID]), [GROUP_ID]),
            (viewer, _project(viewers=[viewer.id]), ()),
            (_user(), _project(public=True), ()),
        ):
            allowed, collection = _run("delete", user, project, groups)
            assert not allowed
            collection.update_one.assert_not_called()

    def test_an_unknown_collection_answers_the_same_404(self):
        assert not _run("delete", _user(admin=True), None)[0]


class TestPropertyNames:
    @pytest.mark.parametrize("key", ["a.b", "$set", "", "x$y"])
    def test_a_name_that_would_leave_its_slot_is_refused(self, key):
        owner = _user()
        with (
            patch(f"{MODULE}.projects_collection", MagicMock()),
            patch(f"{MODULE}.get_user_group_ids", return_value=[]),
            pytest.raises(HTTPException) as exc_info,
        ):
            asyncio.run(utils._update_dc_specific_properties(str(DC_ID), {key: 1}, owner))
        assert exc_info.value.status_code == 400
