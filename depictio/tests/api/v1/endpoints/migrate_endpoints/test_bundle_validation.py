"""A bundle is checked before anything is written (#1303).

An import upserts by ``_id``, so a bundle naming ids another project owns here
would silently rewrite that project. These are refused on every import path;
the push path (``strict``) also refuses what an admin's CLI import tolerates.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from bson import ObjectId

from depictio.api.v1.services import project_bundle
from depictio.api.v1.services.mongo_json import convert_complex_objects_to_strings

from .conftest import make_db, seed_source_project


@pytest.fixture
def bundle():
    """A bundle (metadata, data) built from a seeded source project."""
    db = make_db()
    ids = seed_source_project(db)
    project = db.projects_collection.find_one({"_id": ids["project_id"]})
    from unittest.mock import patch

    with patch.object(project_bundle, "_db", lambda: db):
        scope = project_bundle.resolve_project_scope(project)
        data = project_bundle.collect_bundle_docs(project, scope, "all")
    data = convert_complex_objects_to_strings(data)
    metadata = {
        "project_id": str(ids["project_id"]),
        "source_instance": "private.example.org",
        "depictio_version": "1.20.3",
        "bundle_format_version": 2,
        "s3_bucket": "src-bucket",
    }
    return metadata, data, ids


def test_clean_bundle_is_ok(bundle, target_db):
    metadata, data, ids = bundle
    keys = [f"{ids['table_dc']}/part-0.parquet"]
    report = project_bundle.validate_bundle(metadata, data, keys, strict=True)
    assert report.ok, report.errors
    assert report.conflict == "none"
    assert sorted(report.dashboards_added) == sorted(
        [str(ids["main_dash"]), str(ids["child_dash"])]
    )


def test_keys_outside_the_project_are_an_error_only_when_strict(bundle, target_db):
    metadata, data, ids = bundle
    keys = ["someone-else/secret.parquet"]
    assert project_bundle.validate_bundle(metadata, data, keys, strict=True).errors
    lax = project_bundle.validate_bundle(metadata, data, keys, strict=False)
    assert lax.ok and lax.warnings


def test_dashboard_of_another_project_is_refused(bundle, target_db):
    metadata, data, _ = bundle
    data["dashboards"][0]["project_id"] = str(ObjectId())
    report = project_bundle.validate_bundle(metadata, data, [], strict=False)
    assert any("another project" in e for e in report.errors)


def test_dc_id_owned_by_another_project_here_is_refused(bundle, target_db):
    metadata, data, ids = bundle
    target_db.projects_collection.insert_one(
        {
            "_id": ObjectId(),
            "name": "Other",
            "workflows": [{"data_collections": [{"_id": ids["table_dc"]}]}],
        }
    )
    report = project_bundle.validate_bundle(metadata, data, [], strict=False)
    assert any("data collection id" in e for e in report.errors)


def test_dashboard_id_owned_by_another_project_here_is_refused(bundle, target_db):
    metadata, data, ids = bundle
    target_db.dashboards_collection.insert_one({"_id": ids["main_dash"], "project_id": ObjectId()})
    report = project_bundle.validate_bundle(metadata, data, [], strict=False)
    assert any("dashboard id" in e for e in report.errors)


def test_existing_project_of_same_lineage_is_a_re_push(bundle, target_db):
    metadata, data, ids = bundle
    target_db.projects_collection.insert_one(
        {
            "_id": ids["project_id"],
            "name": "Iris published",
            "provenance": {"imported_from": [{"source_instance": "private.example.org"}]},
        }
    )
    report = project_bundle.validate_bundle(metadata, data, [], strict=True)
    assert report.conflict == "re_push"
    assert report.ok, report.errors


def test_existing_project_of_another_lineage_is_refused_when_strict(bundle, target_db):
    metadata, data, ids = bundle
    target_db.projects_collection.insert_one({"_id": ids["project_id"], "name": "Iris published"})
    strict = project_bundle.validate_bundle(metadata, data, [], strict=True)
    assert strict.conflict == "foreign" and strict.errors
    lax = project_bundle.validate_bundle(metadata, data, [], strict=False)
    assert lax.conflict == "foreign" and lax.ok, "an admin may still --overwrite"


def test_authenticated_source_wins_over_the_claimed_one(bundle, target_db):
    metadata, data, ids = bundle
    target_db.projects_collection.insert_one(
        {
            "_id": ids["project_id"],
            "name": "Iris published",
            "provenance": {"imported_from": [{"source_instance": "private.example.org"}]},
        }
    )
    report = project_bundle.validate_bundle(
        metadata, data, [], strict=True, source_instance="another-source"
    )
    assert report.conflict == "foreign"


def test_newer_bundle_format_is_refused(bundle, target_db):
    metadata, data, _ = bundle
    metadata["bundle_format_version"] = project_bundle.BUNDLE_FORMAT_VERSION + 1
    assert project_bundle.validate_bundle(metadata, data, [], strict=False).errors


def test_location_in_another_bucket_is_flagged(bundle, target_db):
    metadata, data, _ = bundle
    data["deltatables"][0]["delta_table_location"] = "s3://elsewhere/x"
    assert project_bundle.validate_bundle(metadata, data, [], strict=True).errors
    assert project_bundle.validate_bundle(metadata, data, [], strict=False).warnings


def _zip(entries: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    buf.seek(0)
    return buf


def test_zip_slip_is_refused():
    buf = _zip(
        {"bundle.json": b"{}", "migrate_metadata.json": b"{}", "s3_data/../../etc/passwd": b"x"}
    )
    with pytest.raises(project_bundle.BundleError):
        project_bundle.open_bundle_zip(buf)


def test_declared_size_over_the_limit_is_refused():
    buf = _zip({"bundle.json": b"{}", "migrate_metadata.json": b"{}", "s3_data/a/b": b"x" * 2048})
    limits = project_bundle.BundleLimits(max_uncompressed_bytes=1024)
    with pytest.raises(project_bundle.BundleError):
        project_bundle.open_bundle_zip(buf, limits)


def test_missing_bundle_json_is_refused():
    with pytest.raises(project_bundle.BundleError):
        project_bundle.open_bundle_zip(_zip({"migrate_metadata.json": b"{}"}))


def test_not_a_zip_is_refused():
    with pytest.raises(project_bundle.BundleError):
        project_bundle.open_bundle_zip(io.BytesIO(b"definitely not a zip"))


def test_s3_entries_list_delta_logs_last():
    buf = _zip(
        {
            "bundle.json": json.dumps({}).encode(),
            "migrate_metadata.json": b"{}",
            "s3_data/dc/_delta_log/0.json": b"{}",
            "s3_data/dc/part-1.parquet": b"x",
        }
    )
    opened = project_bundle.open_bundle_zip(buf)
    try:
        assert [k for _, k in opened.s3_entries] == ["dc/part-1.parquet", "dc/_delta_log/0.json"]
    finally:
        opened.close()
