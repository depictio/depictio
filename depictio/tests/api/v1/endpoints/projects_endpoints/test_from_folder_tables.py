"""Tests for POST /projects/{id}/add_tables_from_folder (``from_folder_tables``).

No network and no server: the handler is called directly, the database is
mongomock, the S3 listing is the shared CLI stub, and the scan/process helper
(the heavy leg, covered by its own suites) is patched at its seam.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.projects_endpoints import from_folder_tables as fft
from depictio.api.v1.endpoints.projects_endpoints import storage_config
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import install_s3_listing

BUCKET = "tables-bucket"

TREE = {
    "counts.csv": b"a,b\n1,2\n",
    "deg.tsv": b"a\tb\n1\t2\n",
    "data.parquet": b"PAR1",
    "notes.txt": b"hello",
    "empty.csv": b"",
    "sub/deep.csv": b"a\n1\n",
    ".hidden.csv": b"a\n1\n",
}


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)


@pytest.fixture()
def admin():
    return UserBase(id=ObjectId(), email="admin@example.com", is_admin=True)


@pytest.fixture()
def db(monkeypatch, admin):
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(fft, "projects_collection", database["projects"]),
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
        patch.object(storage_config, "project_storage_collection", database["project_storage"]),
    ):
        database["tokens"].insert_one(
            {
                "user_id": admin.id,
                "access_token": "t",
                "refresh_token": "r",
                "token_type": "bearer",
                "name": "n",
                "token_lifetime": "long-lived",
                "expire_datetime": "2999-01-01 00:00:00",
                "refresh_expire_datetime": "2999-01-01 00:00:00",
                "created_at": "2024-01-01 00:00:00",
            }
        )
        yield database


def _project(db, **extra) -> str:
    oid = ObjectId()
    db["projects"].insert_one(
        {"_id": oid, "name": "p", "workflows": [], "permissions": {"owners": [], "editors": []}}
        | extra
    )
    return str(oid)


def _request(host: str = "localhost:8058") -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"host", host.encode())]}
    )


def _call(project_id, user, **kwargs):
    kwargs.setdefault("location", "")
    return asyncio.run(
        fft.add_tables_from_folder(
            project_id, fft.FolderTablesRequest(**kwargs), _request(), current_user=user
        )
    )


@pytest.fixture()
def local_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for rel, body in TREE.items():
        path = home / "tables" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local-home"))
    (tmp_path / "local-home").mkdir()
    return home / "tables"


@pytest.fixture()
def ingest_ok():
    with patch(
        "depictio.cli.cli.utils.helpers.process_data_collection_helper",
        return_value={"result": "success"},
    ) as helper:
        yield helper


def test_dry_run_lists_tables_and_flags_the_rest(db, admin, local_home):
    report = _call(_project(db), admin, location=str(local_home))
    assert report.source == "local" and report.dry_run is True
    by_path = {f.path: f for f in report.files}
    assert set(by_path) == {"counts.csv", "deg.tsv", "data.parquet", "notes.txt", "empty.csv"}
    assert by_path["counts.csv"].table and by_path["counts.csv"].format == "csv"
    assert by_path["counts.csv"].name == "counts"
    assert by_path["data.parquet"].format == "parquet"
    assert not by_path["notes.txt"].table and by_path["notes.txt"].reason
    assert not by_path["empty.csv"].table
    assert report.created == []
    assert db["projects"].find_one()["workflows"] == []


def test_recursive_lists_subfolders(db, admin, local_home):
    report = _call(_project(db), admin, location=str(local_home), recursive=True)
    assert "sub/deep.csv" in {f.path for f in report.files}


def test_gzip_csv_is_a_table_with_compression(db, admin, local_home):
    (local_home / "big.csv.gz").write_bytes(b"\x1f\x8b123")
    (local_home / "bad.parquet.gz").write_bytes(b"\x1f\x8b123")
    by_path = {f.path: f for f in _call(_project(db), admin, location=str(local_home)).files}
    assert by_path["big.csv.gz"].table and by_path["big.csv.gz"].compression == "gzip"
    assert by_path["big.csv.gz"].name == "big"
    assert not by_path["bad.parquet.gz"].table


def test_names_are_unique_within_the_project(db, admin, local_home):
    pid = _project(
        db,
        workflows=[{"data_collections": [{"data_collection_tag": "counts"}]}],
    )
    by_path = {f.path: f for f in _call(pid, admin, location=str(local_home)).files}
    assert by_path["counts.csv"].name == "counts_2"


def test_path_outside_the_listing_is_422(db, admin, local_home):
    with pytest.raises(HTTPException) as exc:
        _call(
            _project(db),
            admin,
            location=str(local_home),
            dry_run=False,
            files=["../secret.csv"],
        )
    assert exc.value.status_code == 422


def test_a_non_table_is_422(db, admin, local_home):
    with pytest.raises(HTTPException) as exc:
        _call(_project(db), admin, location=str(local_home), dry_run=False, files=["notes.txt"])
    assert exc.value.status_code == 422


def test_local_folder_outside_the_roots_is_refused(db, admin, local_home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.csv").write_text("a\n1\n")
    response = _call(_project(db), admin, location=str(outside))
    assert response.status_code == 422
    assert b"local_path_outside" in response.body


def test_local_folders_off_is_refused(db, admin, tmp_path):
    response = _call(_project(db), admin, location=str(tmp_path))
    assert response.status_code == 422
    assert b"local_folders_off" in response.body


def test_a_real_run_creates_one_dc_per_file_with_folder_origin(db, admin, local_home, ingest_ok):
    pid = _project(db)
    report = _call(
        pid,
        admin,
        location=str(local_home),
        dry_run=False,
        files=["counts.csv", "data.parquet"],
    )
    assert [c.status for c in report.created] == ["ingested", "ingested"]
    assert [c.data_collection_tag for c in report.created] == ["counts", "data"]
    workflows = db["projects"].find_one({"_id": ObjectId(pid)})["workflows"]
    assert len(workflows) == 2
    dcs = [wf["data_collections"][0] for wf in workflows]
    for dc in dcs:
        origin = dc["config"]["origin"]
        assert origin["kind"] == "folder"
        assert origin["location"].endswith("tables")
        assert origin["added_at"] is not None
    # The real file is scanned in place, not a temp copy.
    scan = dcs[0]["config"]["scan"]
    assert scan["mode"] == "single"
    assert scan["scan_parameters"]["filename"].endswith("tables/counts.csv")


def test_one_failing_file_does_not_abort_the_others(db, admin, local_home):
    def helper(**kwargs):
        if kwargs["mode"] == "scan" and "deg" in kwargs["wf"].workflow_tag:
            return {"result": "error", "message": "boom"}
        return {"result": "success"}

    with patch("depictio.cli.cli.utils.helpers.process_data_collection_helper", side_effect=helper):
        report = _call(
            _project(db),
            admin,
            location=str(local_home),
            dry_run=False,
            files=["deg.tsv", "counts.csv"],
        )
    assert [c.status for c in report.created] == ["failed", "ingested"]
    assert "boom" in (report.created[0].error or "")
    # The failed one was rolled back.
    assert len(db["projects"].find_one()["workflows"]) == 1


def test_a_locked_project_is_409(db, admin, local_home):
    pid = _project(db, published_lock={"locked_at": "2024-01-01", "dashboard_ids": []})
    with pytest.raises(HTTPException) as exc:
        _call(pid, admin, location=str(local_home))
    assert exc.value.status_code == 409


def test_s3_dry_run_and_real_run(db, admin, monkeypatch, ingest_ok):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", BUCKET)
    install_s3_listing(monkeypatch, TREE, key_prefix="results/")
    pid = _project(db)
    location = f"s3://{BUCKET}/results"
    dry = _call(pid, admin, location=location)
    assert dry.source == "s3" and dry.location == f"s3://{BUCKET}/results/"
    assert {f.path for f in dry.files if f.table} == {"counts.csv", "deg.tsv", "data.parquet"}

    report = _call(pid, admin, location=location, dry_run=False, files=["deg.tsv"])
    assert report.created[0].status == "ingested"
    dc = db["projects"].find_one({"_id": ObjectId(pid)})["workflows"][0]["data_collections"][0]
    assert dc["config"]["scan"]["mode"] == "url"
    assert dc["config"]["scan"]["scan_parameters"]["url"] == f"s3://{BUCKET}/results/deg.tsv"
    assert dc["config"]["origin"]["kind"] == "folder"


def test_s3_bucket_nobody_listed_is_refused(db, admin, monkeypatch):
    from depictio.models.s3_access import S3AccessRefused

    install_s3_listing(monkeypatch, TREE, key_prefix="results/")
    with pytest.raises(S3AccessRefused):
        _call(_project(db), admin, location=f"s3://{BUCKET}/results")


def test_unsupported_location_is_422(db, admin):
    response = _call(_project(db), admin, location="https://example.org/x")
    assert response.status_code == 422
    assert b"location_unsupported" in response.body
