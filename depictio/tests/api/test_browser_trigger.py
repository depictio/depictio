"""Tests for the preconditions on browser-triggered ingestion.

The failure this guards against is the quiet one: a server that cannot see the
project's data starting an ingestion anyway, finding nothing, and reporting
success. Every check below exists to make that impossible to reach, so they are
worth pinning down independently of the endpoint that calls them.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.projects_endpoints.routes import (
    _may_trigger_ingestion,
    _unreachable_data_locations,
)


class _User:
    def __init__(self, user_id: str, is_admin: bool = False) -> None:
        self.id = user_id
        self.is_admin = is_admin


def _project(locations: list[str]) -> dict:
    return {"workflows": [{"data_location": {"structure": "flat", "locations": locations}}]}


class TestReachability:
    def test_an_existing_directory_is_reachable(self, tmp_path):
        assert _unreachable_data_locations(_project([str(tmp_path)])) == []

    def test_a_missing_directory_is_reported(self, tmp_path):
        missing = str(tmp_path / "not-mounted")

        assert _unreachable_data_locations(_project([missing])) == [missing]

    def test_a_file_is_not_a_data_location(self, tmp_path):
        """A path that exists but is not a directory cannot be scanned."""
        target = tmp_path / "runs.txt"
        target.write_text("not a directory")

        assert _unreachable_data_locations(_project([str(target)])) == [str(target)]

    def test_every_missing_location_is_listed(self, tmp_path):
        present = str(tmp_path)
        absent_a = str(tmp_path / "a")
        absent_b = str(tmp_path / "b")

        result = _unreachable_data_locations(_project([present, absent_a, absent_b]))

        assert result == [absent_a, absent_b]

    def test_a_project_with_no_workflows_is_vacuously_reachable(self):
        # Nothing to read means nothing unreadable; the ingestion itself is a
        # no-op, which is a different (and visible) outcome.
        assert _unreachable_data_locations({"workflows": []}) == []

    def test_a_workflow_without_a_data_location_does_not_explode(self):
        assert _unreachable_data_locations({"workflows": [{"name": "wf"}]}) == []


def _permissions(owner: str = "u-owner", editor: str = "u-editor") -> dict:
    return {
        "permissions": {
            "owners": [{"_id": owner}],
            "editors": [{"_id": editor}],
            "viewers": [{"_id": "u-viewer"}],
        }
    }


class TestPermission:
    @pytest.mark.parametrize("user_id", ["u-owner", "u-editor"])
    def test_owners_and_editors_may_trigger(self, user_id):
        assert _may_trigger_ingestion(_permissions(), _User(user_id)) is True

    def test_viewers_may_not(self):
        # Triggering rewrites data collections, so it takes write access, not
        # read access.
        assert _may_trigger_ingestion(_permissions(), _User("u-viewer")) is False

    def test_a_stranger_may_not(self):
        assert _may_trigger_ingestion(_permissions(), _User("u-nobody")) is False

    def test_admins_may(self):
        assert _may_trigger_ingestion(_permissions(), _User("u-nobody", is_admin=True)) is True

    def test_a_project_with_no_permissions_block_denies(self):
        assert _may_trigger_ingestion({}, _User("u-owner")) is False
