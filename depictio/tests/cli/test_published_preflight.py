"""The CLI stops before uploading into a project published read-only (#1303)."""

from unittest.mock import MagicMock, patch

from depictio.cli.cli.utils import published


def _response(status, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def test_lock_is_read_from_the_server_project():
    lock = {"reason": "release 1", "dashboard_ids": []}
    with patch.object(
        published,
        "api_get_project_from_name",
        return_value=_response(200, {"published_lock": lock}),
    ):
        assert published.published_lock_of("Iris", MagicMock()) == lock


def test_unlocked_missing_or_unreachable_projects_are_not_locked():
    for resp in (_response(200, {"published_lock": None}), _response(404, {})):
        with patch.object(published, "api_get_project_from_name", return_value=resp):
            assert published.published_lock_of("Iris", MagicMock()) is None
    with patch.object(published, "api_get_project_from_name", side_effect=OSError("down")):
        assert published.published_lock_of("Iris", MagicMock()) is None


def test_message_names_the_project_and_the_reason():
    msg = published.published_lock_message("Iris", {"reason": "paper v1"})
    assert "Iris" in msg and "paper v1" in msg and "Nothing was ingested" in msg
