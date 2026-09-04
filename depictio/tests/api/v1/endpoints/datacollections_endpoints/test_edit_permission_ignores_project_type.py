"""Adding data to a project is an editing right, not a project-type privilege.

The viewer used to refuse the create-data-collection form outright for
`project_type: "advanced"`, telling the user to go and run depictio-cli. The
backend never agreed: the three creation helpers gate on
`_user_can_edit_project` and nothing else. Removing that client-side refusal
makes the two surfaces consistent, and these tests pin the backend half so the
UI cannot silently break if someone later adds a project-type check here.
"""

import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints.utils import _user_can_edit_project

PROJECT_TYPES = ["basic", "advanced"]


def _project(project_type: str, *, owners=(), editors=(), viewers=()) -> dict:
    return {
        "_id": ObjectId(),
        "name": "demo",
        "project_type": project_type,
        "permissions": {
            "owners": [{"_id": oid} for oid in owners],
            "editors": [{"_id": oid} for oid in editors],
            "viewers": [{"_id": oid} for oid in viewers],
        },
    }


@pytest.mark.parametrize("project_type", PROJECT_TYPES)
class TestEditPermissionIgnoresProjectType:
    def test_an_owner_may_edit(self, project_type):
        user_id = ObjectId()

        assert _user_can_edit_project(_project(project_type, owners=[user_id]), user_id, False)

    def test_an_editor_may_edit(self, project_type):
        user_id = ObjectId()

        assert _user_can_edit_project(_project(project_type, editors=[user_id]), user_id, False)

    def test_a_viewer_may_not(self, project_type):
        user_id = ObjectId()

        assert not _user_can_edit_project(_project(project_type, viewers=[user_id]), user_id, False)

    def test_a_stranger_may_not(self, project_type):
        assert not _user_can_edit_project(_project(project_type), ObjectId(), False)

    def test_an_admin_may_edit(self, project_type):
        assert _user_can_edit_project(_project(project_type), ObjectId(), True)


def test_the_two_project_types_are_treated_identically():
    """The point of the whole change, stated once as a single assertion."""
    user_id = ObjectId()

    decisions = {
        project_type: _user_can_edit_project(
            _project(project_type, owners=[user_id]), user_id, False
        )
        for project_type in PROJECT_TYPES
    }

    assert len(set(decisions.values())) == 1, decisions
