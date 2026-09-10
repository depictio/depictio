"""Validation-layer tests for POST /create_from_url (`_create_dc_from_url`).

The full ingest (scan → remote read → Delta write) is exercised by the CLI
unit tests (tests/cli/test_remote_read.py, tests/unit/test_remote_fetch.py);
here we prove the endpoint's ordering and error contract: SSRF-gateway
rejection precedes any database access, project/permission checks behave
like the upload twin, and the project's own storage credentials reach the
CLI config the ingest runs with.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints.storage_config import StorageSecretUnreadable
from depictio.models.models.users import UserBase

STORAGE = "depictio.api.v1.endpoints.projects_endpoints.storage_config"
CLI_HELPER = "depictio.cli.cli.utils.helpers.process_data_collection_helper"


def _call(url: str, project_id: str = str(ObjectId()), user=None, name: str = "remote-dc"):
    user = user or _user()
    return dc_utils._create_dc_from_url(
        project_id=project_id,
        name=name,
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


# ── Per-project storage credentials ─────────────────────────────────────────


def _owned_project_with_token(mock_db, user) -> ObjectId:
    """Owner + a token doc valid as ``TokenBase`` (the CLI config embeds it)."""
    project_id = ObjectId()
    mock_db["projects"].insert_one(
        {"_id": project_id, "permissions": {"owners": [{"_id": user.id}]}, "workflows": []}
    )
    later = datetime.now() + timedelta(days=1)
    mock_db["tokens"].insert_one(
        {
            "user_id": user.id,
            "access_token": "a.b.c",
            "refresh_token": "d.e.f",
            "expire_datetime": later,
            "refresh_expire_datetime": later,
        }
    )
    return project_id


@pytest.mark.parametrize(
    "resolved",
    [
        None,  # no storage config: read with the instance credentials
        {
            "endpoint_url": "https://s3.example.org",
            "aws_access_key_id": "AKIA123",
            "aws_secret_access_key": "s3cr3t",
        },
    ],
)
def test_project_storage_options_reach_the_cli_config(mock_db, resolved):
    user = _user()
    project_id = _owned_project_with_token(mock_db, user)
    seen: list = []

    def _fake_helper(CLI_config, wf, dc_id, mode, command_parameters=None):
        seen.append((mode, CLI_config.remote_storage_options))
        return {"result": "success"}

    with (
        patch(f"{STORAGE}.storage_options_for_project", return_value=resolved) as resolver,
        patch(CLI_HELPER, side_effect=_fake_helper),
    ):
        result = _call("s3://private-bucket/data.csv", project_id=str(project_id), user=user)

    assert result["success"] is True
    resolver.assert_called_once_with(project_id)
    # Both CLI stages (scan, then process) run with the project's credentials.
    assert seen == [("scan", resolved), ("process", resolved)]


def test_unusable_project_storage_is_a_clean_http_error_before_any_write(mock_db):
    user = _user()
    project_id = _owned_project_with_token(mock_db, user)

    with (
        patch(
            f"{STORAGE}.storage_options_for_project",
            side_effect=StorageSecretUnreadable(project_id, "/app/depictio/keys"),
        ),
        patch(CLI_HELPER) as helper,
    ):
        with pytest.raises(HTTPException) as exc:
            _call("s3://private-bucket/data.csv", project_id=str(project_id), user=user)

    assert exc.value.status_code == 500
    assert str(project_id) in exc.value.detail
    assert "/app/depictio/keys" not in exc.value.detail  # sanitized: no server paths
    helper.assert_not_called()
    # Resolved before the workflow $push: nothing to roll back, nothing left behind.
    assert mock_db["projects"].find_one({"_id": project_id})["workflows"] == []


# ── Happy path ──────────────────────────────────────────────────────────────


def _ingest_recorder(outcomes: dict[str, dict] | None = None):
    """Fake CLI helper that records each stage and answers per ``outcomes``."""
    seen: list[dict] = []
    outcomes = outcomes or {}

    def _fake_helper(CLI_config, wf, dc_id, mode, command_parameters=None):
        seen.append(
            {
                "mode": mode,
                "dc_id": dc_id,
                "workflow_id": str(wf.id),
                "command_parameters": command_parameters,
                "cli_config": CLI_config,
            }
        )
        return outcomes.get(mode, {"result": "success"})

    return seen, _fake_helper


def test_https_url_becomes_a_url_scan_workflow_that_is_ingested(mock_db):
    url = "https://example.org/run42/data.csv"
    user = _user()
    project_id = _owned_project_with_token(mock_db, user)
    seen, fake_helper = _ingest_recorder()

    with (
        patch(f"{STORAGE}.storage_options_for_project", return_value=None),
        patch(CLI_HELPER, side_effect=fake_helper),
    ):
        result = _call(url, project_id=str(project_id), user=user, name="  remote-dc  ")

    assert result["success"] is True
    assert "remote-dc" in result["message"]

    # Scan, then process (overwriting), both against the same new DC.
    assert [s["mode"] for s in seen] == ["scan", "process"]
    assert {s["dc_id"] for s in seen} == {result["data_collection_id"]}
    assert {s["workflow_id"] for s in seen} == {result["workflow_id"]}
    assert seen[1]["command_parameters"] == {"overwrite": True}
    cli_config = seen[0]["cli_config"]
    assert str(cli_config.user.id) == str(user.id)
    assert cli_config.remote_storage_options is None  # no project storage: instance creds

    # The workflow the ingest ran on is the one persisted on the project.
    (workflow,) = mock_db["projects"].find_one({"_id": project_id})["workflows"]
    assert str(workflow["_id"]) == result["workflow_id"]
    assert workflow["data_location"]["locations"] == [url]
    (dc,) = workflow["data_collections"]
    assert str(dc["_id"]) == result["data_collection_id"]
    assert dc["data_collection_tag"] == "remote-dc"  # whitespace trimmed
    scan = dc["config"]["scan"]
    assert str(scan["mode"]).lower() == "url"
    assert scan["scan_parameters"] == {"url": url}
    table = dc["config"]["dc_specific_properties"]
    assert table["format"] == "csv"
    assert table["polars_kwargs"]["separator"] == ","
    assert table["polars_kwargs"]["has_header"] is True
    assert "lat_column" not in table


def test_coordinate_columns_select_the_coordinates_table_config(mock_db):
    user = _user()
    project_id = _owned_project_with_token(mock_db, user)
    _, fake_helper = _ingest_recorder()

    with (
        patch(f"{STORAGE}.storage_options_for_project", return_value=None),
        patch(CLI_HELPER, side_effect=fake_helper),
    ):
        result = dc_utils._create_dc_from_url(
            project_id=str(project_id),
            name="sites",
            description="Sampling sites",
            data_type="table",
            file_format="tsv",
            separator="\t",
            custom_separator=None,
            compression="none",
            has_header=True,
            url="https://example.org/sites.tsv",
            current_user=user,
            lat_column="lat",
            lon_column="lon",
        )

    assert result["success"] is True
    (workflow,) = mock_db["projects"].find_one({"_id": project_id})["workflows"]
    (dc,) = workflow["data_collections"]
    assert dc["description"] == "Sampling sites"
    table = dc["config"]["dc_specific_properties"]
    assert table["format"] == "tsv"
    assert table["polars_kwargs"]["separator"] == "\t"
    assert (table["lat_column"], table["lon_column"]) == ("lat", "lon")


def test_failed_processing_is_a_500_and_rolls_the_workflow_back(mock_db):
    user = _user()
    project_id = _owned_project_with_token(mock_db, user)
    seen, fake_helper = _ingest_recorder(
        {"process": {"result": "error", "message": "remote read failed"}}
    )

    with (
        patch(f"{STORAGE}.storage_options_for_project", return_value=None),
        patch(CLI_HELPER, side_effect=fake_helper),
    ):
        with pytest.raises(HTTPException) as exc:
            _call("https://example.org/run42/data.csv", project_id=str(project_id), user=user)

    assert exc.value.status_code == 500
    assert "remote read failed" in exc.value.detail
    assert [s["mode"] for s in seen] == ["scan", "process"]
    # No ghost workflow without a delta table behind it.
    assert mock_db["projects"].find_one({"_id": project_id})["workflows"] == []
