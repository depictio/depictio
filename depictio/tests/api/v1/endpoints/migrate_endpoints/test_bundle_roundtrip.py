"""Export -> ZIP -> import into another instance with another bucket (#1303).

Before the bundle service, an import kept the source bucket in every stored
location, left datetimes as strings, never recorded a dashboard version and
could not be told which Depictio produced the bundle.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from datetime import datetime
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import UploadFile

from depictio.api.v1.endpoints.migrate_endpoints import routes
from depictio.api.v1.endpoints.migrate_endpoints.routes import MigrateExportRequest
from depictio.api.v1.services import project_bundle
from depictio.models.models.users import UserBase

from .conftest import COLLECTIONS, FakeS3, make_db, seed_source_project


def _admin(email="admin@target.org"):
    u = UserBase(id=ObjectId(), email=email)
    u.is_admin = True
    return u


@pytest.fixture
def source():
    db = make_db()
    ids = seed_source_project(db)
    s3 = FakeS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    s3.put("src-bucket", f"{ids['mqc_dc']}/abc/multiqc.parquet", b"mqc")
    s3.put("src-bucket", "unrelated/file", b"nope")
    return db, ids, s3


def _export_zip(source, monkeypatch) -> bytes:
    """Run the real export route against the source database."""
    db, ids, s3 = source
    patches = [patch.object(project_bundle, "_db", lambda: db)]
    patches += [patch.object(routes, a, getattr(db, a)) for a in COLLECTIONS if hasattr(routes, a)]
    patches.append(patch.object(routes, "_instance_s3_client", lambda: s3))
    monkeypatch.setattr(routes.settings.s3, "bucket", "src-bucket")
    for p in patches:
        p.start()
    try:
        response = asyncio.run(
            routes.export_project(
                MigrateExportRequest(project_id=str(ids["project_id"]), mode="all"),
                current_user=_admin("admin@source.org"),
            )
        )
        with open(response.path, "rb") as fh:
            payload = fh.read()
        os.unlink(response.path)
        return payload
    finally:
        for p in reversed(patches):
            p.stop()


def test_export_records_version_format_and_streams_data(source, monkeypatch):
    payload = _export_zip(source, monkeypatch)
    _, ids, _ = source
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        meta = json.loads(zf.read("migrate_metadata.json"))
        names = zf.namelist()
        info = zf.getinfo(f"s3_data/{ids['table_dc']}/part-0.parquet")
    assert meta["depictio_version"] not in (None, "", "unknown")
    assert meta["bundle_format_version"] == project_bundle.BUNDLE_FORMAT_VERSION
    assert meta["s3_bucket"] == "src-bucket"
    assert f"s3_data/{ids['mqc_dc']}/abc/multiqc.parquet" in names
    assert "s3_data/unrelated/file" not in names
    assert info.compress_type == zipfile.ZIP_STORED
    data_members = [n for n in names if n.startswith("s3_data/")]
    assert data_members[-1].endswith("_delta_log/00000.json"), "delta logs are written last"


def _import_zip(payload: bytes, user, *, overwrite=False, dry_run=False, s3=None):
    upload = UploadFile(file=io.BytesIO(payload), filename="bundle.zip")
    with patch.object(routes, "_instance_s3_client", lambda: s3 or FakeS3()):
        return asyncio.run(
            routes.import_project_zip(
                file=upload, dry_run=dry_run, overwrite=overwrite, current_user=user
            )
        )


def test_round_trip_into_another_bucket(source, target_db, captures, monkeypatch):
    payload = _export_zip(source, monkeypatch)
    _, ids, _ = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    target_s3 = FakeS3()
    admin = _admin()

    result = _import_zip(payload, admin, s3=target_s3)

    assert result.success, result.message
    pid = ids["project_id"]
    project = target_db.projects_collection.find_one({"_id": pid})
    assert project is not None
    # ObjectIds are back, so the joins that drive listings match.
    assert isinstance(project["workflows"][0]["data_collections"][0]["_id"], ObjectId)
    dashes = list(target_db.dashboards_collection.find({"project_id": pid}))
    assert len(dashes) == 2
    main = next(d for d in dashes if d["is_main_tab"])
    assert isinstance(main["stored_metadata"][0]["dc_id"], ObjectId)
    # Owners remapped to the importing admin; source-local shares dropped.
    assert project["permissions"]["owners"][0]["_id"] == admin.id
    # Locations point at this instance's bucket.
    dt = target_db.deltatables_collection.find_one({"data_collection_id": ids["table_dc"]})
    assert dt["delta_table_location"] == f"s3://tgt-bucket/{ids['table_dc']}"
    assert isinstance(dt["aggregation"][0]["aggregation_time"], datetime)
    mqc = target_db.multiqc_collection.find_one({})
    assert mqc["s3_location"].startswith("s3://tgt-bucket/")
    assert mqc["data_collection_id"] == str(ids["mqc_dc"]), "multiqc keeps its string dc id"
    # The data landed under the same keys in the target bucket.
    assert target_s3.buckets["tgt-bucket"][f"{ids['table_dc']}/part-0.parquet"] == b"rows"
    # Provenance: created version kept, one hop appended.
    prov = project["provenance"]
    assert prov["created_with_version"] == "1.20.0"
    hop = prov["imported_from"][-1]
    assert hop["via"] == "zip" and hop["bundle_sha256"]
    assert sorted(hop["dashboard_ids"]) == sorted([str(ids["main_dash"]), str(ids["child_dash"])])
    # One import version for the family, none for the child tab separately.
    imports = [c for c in captures if c[1] == "import"]
    assert [c[0] for c in imports] == [str(ids["main_dash"])]
    assert "Imported from" in (imports[0][2] or "")


def test_reimport_needs_overwrite_and_records_the_replaced_state(
    source, target_db, captures, monkeypatch
):
    payload = _export_zip(source, monkeypatch)
    _, ids, _ = source
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    admin = _admin()
    assert _import_zip(payload, admin).success

    again = _import_zip(payload, admin)
    assert again.conflict is True and not again.success

    captures.clear()
    replaced = _import_zip(payload, admin, overwrite=True)
    assert replaced.success
    kinds = [c[1] for c in captures]
    assert kinds.index("explicit") < kinds.index("import"), "state before, then the import"


def test_reimport_deletes_dashboards_the_lineage_dropped_but_keeps_copies(
    source, target_db, captures, monkeypatch
):
    db, ids, _ = source
    payload = _export_zip(source, monkeypatch)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    admin = _admin()
    assert _import_zip(payload, admin).success
    visitor_copy = ObjectId()
    target_db.dashboards_collection.insert_one(
        {
            "_id": visitor_copy,
            "dashboard_id": visitor_copy,
            "project_id": ids["project_id"],
            "is_main_tab": True,
        }
    )
    # The source drops its child tab, and the next export no longer carries it.
    db.dashboards_collection.delete_one({"_id": ids["child_dash"]})
    payload2 = _export_zip(source, monkeypatch)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")

    assert _import_zip(payload2, admin, overwrite=True).success

    remaining = {d["_id"] for d in target_db.dashboards_collection.find({})}
    assert ids["child_dash"] not in remaining
    assert visitor_copy in remaining
    assert ids["main_dash"] in remaining


def test_dry_run_writes_nothing(source, target_db, captures, monkeypatch):
    payload = _export_zip(source, monkeypatch)
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    target_s3 = FakeS3()
    result = _import_zip(payload, _admin(), dry_run=True, s3=target_s3)
    assert result.success and result.dry_run
    assert target_db.projects_collection.count_documents({}) == 0
    assert target_s3.buckets == {}
    assert captures == []


def test_cli_json_import_rewrites_bucket_and_records_cli_hop(
    source, target_db, captures, monkeypatch
):
    payload = _export_zip(source, monkeypatch)
    _, ids, _ = source
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        bundle = {
            "data": json.loads(zf.read("bundle.json")),
            "migrate_metadata": json.loads(zf.read("migrate_metadata.json")),
        }
    monkeypatch.setattr(routes.settings.s3, "bucket", "tgt-bucket")
    req = routes.MigrateImportRequest(bundle=bundle)
    result = asyncio.run(routes.import_project(req, current_user=_admin()))
    assert result.success
    project = target_db.projects_collection.find_one({"_id": ids["project_id"]})
    assert project["provenance"]["imported_from"][-1]["via"] == "cli"
    dt = target_db.deltatables_collection.find_one({})
    assert dt["delta_table_location"].startswith("s3://tgt-bucket/")
