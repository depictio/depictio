"""Tests for POST /projects/from_manifest (`_create_project_from_manifest`).

Orchestration-contract tests: SSRF-gateway rejection precedes everything,
template resolution + manifest coverage checks produce the right errors and
plans, project creation persists the resolved manifest scan configs with the
caller as owner, and the per-DC ingest / dashboard-import fan-out is reported
per item. The heavy legs (scan → Delta, dashboard tag binding) are covered by
their own suites — here they are patched at their seams (`_run_dc_ingest`,
`import_dashboard_yaml_content`).

Uses the real reference template `generic/manifest-tables/1`, so these tests
also validate that shipped fixture end-to-end.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints import from_manifest, manifest_ingest
from depictio.models.models.users import UserBase

TEMPLATE_ID = "generic/manifest-tables/1"

MANIFEST_JSON = """
[
  {"id": "s1", "type": "samples", "url": "https://example.org/s1.csv"},
  {"id": "s2", "type": "samples", "url": "https://example.org/s2.csv", "run": "batch1"},
  {"id": "s1", "type": "measurements", "url": "https://example.org/m1.csv"},
  {"id": "x1", "type": "unmapped_type", "url": "https://example.org/x.csv"}
]
"""

# No "measurements" rows: the optional DC must be pruned, not fail.
MANIFEST_SAMPLES_ONLY = """
[
  {"id": "s1", "type": "samples", "url": "https://example.org/s1.csv"}
]
"""

# No "samples" rows: the required DC must 422.
MANIFEST_NO_SAMPLES = """
[
  {"id": "m1", "type": "measurements", "url": "https://example.org/m1.csv"}
]
"""


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=False)


def _call(
    manifest_url: str = "https://example.org/manifest.json",
    template_id: str = TEMPLATE_ID,
    user=None,
    project_name: str | None = None,
    dry_run: bool = False,
):
    return from_manifest._create_project_from_manifest(
        manifest_url=manifest_url,
        template_id=template_id,
        current_user=user or _user(),
        project_name=project_name,
        dry_run=dry_run,
    )


@pytest.fixture()
def mock_db(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "example.org")
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with patch.object(from_manifest, "projects_collection", database["projects"]):
        yield database


def _served(content: str = MANIFEST_JSON):
    def _fake_download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(content)
        return len(content)

    return patch.object(manifest_ingest, "bounded_download", side_effect=_fake_download)


def test_bad_scheme_rejected_first():
    with pytest.raises(HTTPException) as exc:
        _call("ftp://example.org/manifest.json")
    assert exc.value.status_code == 400


def test_s3_manifest_rejected():
    with pytest.raises(HTTPException) as exc:
        _call("s3://bucket/manifest.json")
    assert exc.value.status_code == 400


def test_unknown_template_404(mock_db):
    with _served(), pytest.raises(HTTPException) as exc:
        _call(template_id="generic/does-not-exist/1")
    assert exc.value.status_code == 404


def test_missing_required_manifest_type_422(mock_db):
    with _served(MANIFEST_NO_SAMPLES), pytest.raises(HTTPException) as exc:
        _call(dry_run=True)
    assert exc.value.status_code == 422
    assert "samples" in exc.value.detail


def test_dry_run_reports_plan_without_creating(mock_db):
    with _served():
        report = _call(dry_run=True)

    assert report.success is True
    assert report.dry_run is True
    assert report.project_id is None
    assert report.project_name == "Manifest Tables"
    assert report.manifest_entries == 4
    by_tag = {r.data_collection_tag: r for r in report.ingestion}
    assert by_tag["samples"].entries == 2
    assert by_tag["measurements"].entries == 1
    assert all(r.status == "planned" for r in report.ingestion)
    assert report.unmatched_manifest_types == ["unmapped_type"]
    assert mock_db["projects"].count_documents({}) == 0


def test_optional_dc_without_rows_is_pruned(mock_db):
    with _served(MANIFEST_SAMPLES_ONLY):
        report = _call(dry_run=True)

    assert report.success is True
    assert report.pruned_optional_dcs == ["measurements"]
    assert [r.data_collection_tag for r in report.ingestion] == ["samples"]


def test_full_flow_creates_project_ingests_and_imports_dashboards(mock_db):
    user = _user()
    with (
        _served(),
        patch.object(from_manifest, "_run_dc_ingest", return_value=(True, None)) as ingest,
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content",
            return_value={
                "success": True,
                "dashboard_id": str(ObjectId()),
                "title": "Manifest Overview",
            },
        ) as importer,
    ):
        report = _call(user=user, project_name="run42")

    assert report.success is True
    assert report.project_id is not None
    assert report.project_name == "run42"

    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    assert stored is not None
    assert stored["name"] == "run42"
    assert stored["permissions"]["owners"][0]["_id"] == user.id
    scans = [dc["config"]["scan"] for wf in stored["workflows"] for dc in wf["data_collections"]]
    assert all(s["mode"] == "manifest" for s in scans)
    assert all(
        s["scan_parameters"]["manifest_url"] == "https://example.org/manifest.json" for s in scans
    )

    # One ingest call per manifest DC (samples + measurements).
    assert ingest.call_count == 2
    assert {r.data_collection_tag for r in report.ingestion} == {"samples", "measurements"}
    assert all(r.status == "ingested" for r in report.ingestion)
    assert all(r.data_collection_id for r in report.ingestion)

    # The template's base dashboard was imported against the new project.
    assert importer.call_count == 1
    _yaml_text, project_oid = importer.call_args.args[:2]
    assert project_oid == ObjectId(report.project_id)
    assert report.dashboards[0].success is True
    assert report.dashboards[0].title == "Manifest Overview"


def test_failed_dc_ingest_reported_and_project_kept(mock_db):
    with (
        _served(),
        patch.object(from_manifest, "_run_dc_ingest", return_value=(False, "boom")),
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content",
            return_value={"success": True, "dashboard_id": str(ObjectId()), "title": "t"},
        ),
    ):
        report = _call(project_name="run43")

    assert report.success is False
    assert all(r.status == "failed" for r in report.ingestion)
    assert "boom" in (report.ingestion[0].message or "")
    # The project survives for inspection / re-ingest via /projects/ingest_manifest.
    assert mock_db["projects"].count_documents({"name": "run43"}) == 1


def test_duplicate_project_name_409(mock_db):
    mock_db["projects"].insert_one({"_id": ObjectId(), "name": "run42"})
    with _served(), pytest.raises(HTTPException) as exc:
        _call(project_name="run42")
    assert exc.value.status_code == 409
