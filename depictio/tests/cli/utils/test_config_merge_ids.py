"""`depictio run` against an existing project it co-owns must not hard-fail."""

import pytest

from depictio.cli.cli.utils.config import merge_existing_ids


def _project(*owner_ids: str, name: str = "demo") -> dict:
    return {
        "name": name,
        "id": "651be0000000000000000000",
        "permissions": {
            "owners": [{"id": oid, "email": f"{oid}@example.org"} for oid in owner_ids]
        },
        "workflows": [],
    }


class TestMergeExistingIdsOwnership:
    def test_the_cli_user_may_be_any_of_the_owners(self):
        """A shared project has no meaningful "first" owner, and the stored
        order is whatever the last write produced."""
        existing = _project("someone-else", "cli-user")
        incoming = _project("cli-user")

        merged = merge_existing_ids(existing, incoming)

        assert merged["name"] == "demo"

    def test_the_first_owner_still_works(self):
        merged = merge_existing_ids(_project("cli-user", "someone-else"), _project("cli-user"))

        assert merged["name"] == "demo"

    def test_a_genuine_stranger_is_still_refused(self):
        with pytest.raises(ValueError, match="owned by a different user"):
            merge_existing_ids(_project("someone-else"), _project("cli-user"))

    def test_no_existing_project_is_a_passthrough(self):
        incoming = _project("cli-user")

        assert merge_existing_ids({}, incoming) == incoming
