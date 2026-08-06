"""Validation-layer tests for POST /create_from_url (`_create_dc_from_url`).

The full ingest (scan → remote read → Delta write) is exercised by the CLI
unit tests (tests/cli/test_remote_read.py, tests/unit/test_remote_fetch.py);
here we prove the endpoint's ordering and error contract: SSRF-gateway
rejection precedes any database access, and project/permission checks behave
like the upload twin.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.models.models.users import UserBase


def _call(url: str, project_id: str = str(ObjectId()), user=None):
    user = user or _user()
    return dc_utils._create_dc_from_url(
        project_id=project_id,
        name="remote-dc",
        description="",
        data_type="table",
        file_format="csv",
        separator=",",
        custom_separator=None,
        compression="none",
        has_header=True,
        url=url,
        current_user=user,
    )


def _user(is_admin: bool = False) -> UserBase:
    user = UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)
    return user


def test_bad_scheme_rejected_before_db():
    # No DB patching at all: a gateway rejection must never reach Mongo.
    with pytest.raises(HTTPException) as exc:
        _call("ftp://example.org/data.csv")
    assert exc.value.status_code == 400
    assert "scheme" in exc.value.detail.lower()


def test_private_host_rejected_before_db():
    with pytest.raises(HTTPException) as exc:
        _call("https://127.0.0.1/data.csv")
    assert exc.value.status_code == 400


def test_empty_name_rejected():
    with pytest.raises(HTTPException) as exc:
        dc_utils._create_dc_from_url(
            project_id=str(ObjectId()),
            name="  ",
            description="",
            data_type="table",
            file_format="csv",
            separator=",",
            custom_separator=None,
            compression="none",
            has_header=True,
            url="https://example.org/data.csv",
            current_user=_user(),
        )
    assert exc.value.status_code == 400


@pytest.fixture()
def mock_db(monkeypatch):
    # example.org resolves publicly; keep the gateway green without network
    # by allowlisting the host (allowlisted hosts skip DNS resolution).
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "example.org")
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
    ):
        yield database


def test_unknown_project_404(mock_db):
    with pytest.raises(HTTPException) as exc:
        _call("https://example.org/data.csv")
    assert exc.value.status_code == 404


def test_no_edit_permission_403(mock_db):
    project_id = ObjectId()
    mock_db["projects"].insert_one({"_id": project_id, "permissions": {"owners": []}})
    with pytest.raises(HTTPException) as exc:
        _call("https://example.org/data.csv", project_id=str(project_id))
    assert exc.value.status_code == 403


def test_owner_without_token_401(mock_db):
    user = _user()
    project_id = ObjectId()
    mock_db["projects"].insert_one(
        {"_id": project_id, "permissions": {"owners": [{"_id": user.id}]}}
    )
    with pytest.raises(HTTPException) as exc:
        _call("https://example.org/data.csv", project_id=str(project_id), user=user)
    assert exc.value.status_code == 401
