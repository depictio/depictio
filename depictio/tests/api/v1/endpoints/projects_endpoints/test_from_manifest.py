"""Tests for POST /projects/from_manifest (`_create_project_from_manifest`).

Orchestration-contract tests: SSRF-gateway rejection precedes everything,
template resolution + manifest coverage checks produce the right errors and
plans, project creation persists the resolved manifest scan configs with the
caller as owner under a free name, and the per-DC ingest / dashboard-import
fan-out is reported per item, the dashboards keyed as the CLI keys them. The heavy legs (scan → Delta, dashboard tag binding) are covered by
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

from depictio.api.v1.endpoints.projects_endpoints import from_manifest, manifest_ingest, routes
from depictio.api.v1.remote_fetch import RemoteURLRejected
from depictio.models.models.users import UserBase

_IMPORTER = "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content"

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
    with (
        patch.object(from_manifest, "projects_collection", database["projects"]),
        # The duplicate-name check is POST /projects/create's, which reads here.
        patch.object(routes, "projects_collection", database["projects"]),
    ):
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


def test_a_metadata_file_variable_is_never_opened_on_the_server(mock_db, tmp_path, monkeypatch):
    """A request's METADATA_FILE names a path on the server's disk: resolving
    the template for a browser must not open it, or the file's first line
    would come back as the project's column variables."""
    from depictio.cli.cli.utils import templates

    # Importing the CLI app elsewhere in the session flips the context to CLI.
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")

    server_file = tmp_path / "server-only.tsv"
    server_file.write_text("private_header\tother\n")
    with (
        _served(),
        patch.object(templates, "_auto_detect_metadata_columns") as detect,
    ):
        report = from_manifest._create_project_from_manifest(
            manifest_url="https://example.org/manifest.json",
            template_id=TEMPLATE_ID,
            current_user=_user(),
            project_name=None,
            variables={"METADATA_FILE": str(server_file)},
            dry_run=True,
        )
    assert report.success is True
    detect.assert_not_called()


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
            _IMPORTER,
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

    # The template's base dashboard was imported against the new project,
    # under the source key the CLI files it under.
    assert importer.call_count == 1
    kwargs = importer.call_args.kwargs
    assert kwargs["project_id"] == ObjectId(report.project_id)
    assert kwargs["source_key"] == "generic/manifest-tables:dashboards/base.yaml"
    assert kwargs["existing"] == "keep"
    assert report.dashboards[0].success is True
    assert report.dashboards[0].title == "Manifest Overview"


def test_failed_dc_ingest_reported_and_project_kept(mock_db):
    with (
        _served(),
        patch.object(from_manifest, "_run_dc_ingest", return_value=(False, "boom")),
        patch(
            _IMPORTER,
            return_value={"success": True, "dashboard_id": str(ObjectId()), "title": "t"},
        ),
    ):
        report = _call(project_name="run43")

    assert report.success is False
    assert all(r.status == "failed" for r in report.ingestion)
    assert "boom" in (report.ingestion[0].message or "")
    # The project survives for inspection / re-ingest via /projects/ingest_manifest.
    assert mock_db["projects"].count_documents({"name": "run43"}) == 1


def test_a_taken_project_name_is_refused_as_create_refuses_it(mock_db):
    """The same check and error as POST /projects/create, before anything is written."""
    user = _user()
    imported = {"success": True, "dashboard_id": str(ObjectId()), "title": "t"}
    with (
        _served(),
        patch.object(from_manifest, "_run_dc_ingest", return_value=(True, None)) as ingest,
        patch(_IMPORTER, return_value=imported),
    ):
        _call(user=user, project_name="run42")
        ingest.reset_mock()
        with pytest.raises(HTTPException) as exc:
            _call(user=user, project_name="run42")

    assert exc.value.status_code == 409
    assert exc.value.detail == routes._project_taken("name")["message"]
    assert mock_db["projects"].count_documents({}) == 1
    ingest.assert_not_called()


def test_a_child_tab_names_its_parent_by_key(mock_db, tmp_path):
    """As the CLI sends it: the tab's parent is found by key, so a renamed parent keeps it."""
    main = tmp_path / "main.yaml"
    main.write_text("title: Overview\n")
    tab = tmp_path / "tab.yaml"
    tab.write_text("title: Details\nparent_dashboard_tag: Overview\n")

    with patch(_IMPORTER, return_value={"success": True}) as importer:
        results = from_manifest._import_template_dashboards(
            [main, tab],
            template_id="generic/not-shipped/1",
            project_id=ObjectId(),
            variables={},
            current_user=_user(),
        )

    assert [entry.success for entry in results] == [True, True]
    main_call, tab_call = importer.call_args_list
    assert main_call.kwargs["parent_source_key"] is None
    assert tab_call.kwargs["parent_source_key"] == main_call.kwargs["source_key"]
    assert tab_call.kwargs["source_key"] != main_call.kwargs["source_key"]


# One entry on a host the gateway rejects (the other host passes).
MANIFEST_WITH_INTERNAL_ENTRY = """
[
  {"id": "s1", "type": "samples", "url": "https://example.org/s1.csv"},
  {"id": "s2", "type": "samples", "url": "https://internal.example/s2.csv"}
]
"""


def test_rejected_entry_url_400_and_nothing_created(mock_db):
    def _gate(url):
        if "internal.example" in url:
            raise RemoteURLRejected(
                "Host 'internal.example' resolves to a non-public address and was rejected."
            )

    with (
        _served(MANIFEST_WITH_INTERNAL_ENTRY),
        patch.object(manifest_ingest, "validate_remote_url", side_effect=_gate),
        patch.object(from_manifest, "_run_dc_ingest") as ingest,
        pytest.raises(HTTPException) as exc,
    ):
        _call(project_name="run44")

    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail["rejected_count"] == 1
    assert detail["rejected_entries"][0]["id"] == "s2"
    assert detail["rejected_entries"][0]["type"] == "samples"
    assert "samples/s2" in detail["message"]
    ingest.assert_not_called()
    assert mock_db["projects"].count_documents({}) == 0


@pytest.mark.parametrize(
    "template_id", ["../x", "/etc/passwd", "generic/../../x", "~/x", ".hidden/x", ""]
)
def test_request_rejects_path_like_template_ids(template_id):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="slash-separated"):
        from_manifest.FromManifestRequest(
            manifest_url="https://example.org/m.json", template_id=template_id
        )


@pytest.mark.parametrize(
    "template_id",
    ["generic/manifest-tables/1", "nf-core/ampliseq/latest", "nf-core/ampliseq", "lab/tool/1.0.0"],
)
def test_request_accepts_catalogue_ids(template_id):
    request = from_manifest.FromManifestRequest(
        manifest_url="https://example.org/m.json", template_id=template_id
    )
    assert request.template_id == template_id


def test_path_like_template_id_422_before_any_lookup(mock_db):
    # Direct callers bypass the request model; the flow re-checks the id itself.
    with _served(), pytest.raises(HTTPException) as exc:
        _call(template_id="../../etc/passwd")
    assert exc.value.status_code == 422
    assert "slash-separated" in exc.value.detail
    assert mock_db["projects"].count_documents({}) == 0


def _custom_template(tmp_path, scan_overrides: dict[str, dict], extra: dict | None = None):
    """The reference template with per-tag ``scan_parameters`` overrides (and
    ``extra`` top-level keys), on disk.

    Returns the patch that makes ``resolve_template`` load it.
    """
    from pathlib import Path

    import yaml

    from depictio.cli.cli.utils import templates as templates_module

    source = Path(templates_module.__file__).resolve().parents[4] / "depictio" / "projects"
    config = yaml.safe_load((source / TEMPLATE_ID / "template.yaml").read_text())
    for workflow in config["workflows"]:
        for dc in workflow["data_collections"]:
            dc["config"]["scan"]["scan_parameters"].update(
                scan_overrides.get(dc["data_collection_tag"], {})
            )
    config.update(extra or {})
    target = tmp_path / "template.yaml"
    target.write_text(yaml.safe_dump(config))
    return patch.object(templates_module, "locate_template", return_value=target)


# Same rows as MANIFEST_JSON, with the id under "sample".
MANIFEST_SAMPLE_COLUMN = """
[
  {"sample": "s1", "type": "samples", "url": "https://example.org/s1.csv"},
  {"sample": "s2", "type": "samples", "url": "https://example.org/s2.csv"},
  {"sample": "s1", "type": "measurements", "url": "https://example.org/m1.csv"}
]
"""


def test_coverage_reads_the_manifest_with_the_dcs_columns(mock_db, tmp_path):
    """A template whose DCs say ``id_field: sample`` reads a manifest without
    an ``id`` column; the coverage check must parse it the same way."""
    overrides = {tag: {"id_field": "sample"} for tag in ("samples", "measurements")}
    with _custom_template(tmp_path, overrides), _served(MANIFEST_SAMPLE_COLUMN):
        report = _call(dry_run=True)

    assert report.success is True
    by_tag = {r.data_collection_tag: r.entries for r in report.ingestion}
    assert by_tag == {"samples": 2, "measurements": 1}


def test_dcs_reading_different_columns_422(mock_db, tmp_path):
    overrides = {"samples": {"id_field": "sample"}}  # measurements keeps "id"
    with (
        _custom_template(tmp_path, overrides),
        _served(MANIFEST_SAMPLE_COLUMN),
        pytest.raises(HTTPException) as exc,
    ):
        _call(dry_run=True)

    assert exc.value.status_code == 422
    assert "samples read id from 'sample'" in exc.value.detail
    assert "measurements read id from 'id'" in exc.value.detail


def test_an_empty_manifest_type_reads_the_tag_like_refresh_does(mock_db, tmp_path):
    """Coverage check and refresh pre-flight share one rule: a missing or
    empty ``manifest_type`` reads the DC's tag, never rows of type ''."""
    with _custom_template(tmp_path, {"samples": {"manifest_type": ""}}), _served():
        report = _call(dry_run=True)

    assert {r.data_collection_tag: r.entries for r in report.ingestion}["samples"] == 2
    assert manifest_ingest._manifest_type_of({"manifest_type": ""}, "samples") == "samples"
    assert manifest_ingest._manifest_type_of({}, "samples") == "samples"
    assert manifest_ingest._manifest_type_of({"manifest_type": " counts "}, "x") == "counts"


def test_template_links_are_stored_with_the_new_dc_ids(mock_db, tmp_path):
    """A template (an exported bundle, say) links its DCs by tag; the project
    is stored with the ids of its own new DCs next to those tags."""
    link = {
        "source_dc_tag": "samples",
        "source_column": "depictio_manifest_id",
        "target_dc_tag": "measurements",
        "target_type": "table",
    }
    with (
        _custom_template(tmp_path, {}, extra={"links": [link]}),
        _served(),
        patch.object(from_manifest, "_run_dc_ingest", return_value=(True, None)),
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.import_dashboard_yaml_content",
            return_value={"success": True, "dashboard_id": str(ObjectId()), "title": "t"},
        ),
    ):
        report = _call(project_name="linked")

    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    ids = {
        dc["data_collection_tag"]: str(dc["_id"])
        for wf in stored["workflows"]
        for dc in wf["data_collections"]
    }
    (stored_link,) = stored["links"]
    assert str(stored_link["source_dc_id"]) == ids["samples"]
    assert str(stored_link["target_dc_id"]) == ids["measurements"]


def test_unknown_template_404_hides_server_paths(mock_db):
    from pathlib import Path

    from depictio.cli.cli.utils import templates as templates_module

    with _served(), pytest.raises(HTTPException) as exc:
        _call(template_id="generic/does-not-exist/1")

    assert exc.value.status_code == 404
    detail = exc.value.detail
    assert detail.startswith("Template 'generic/does-not-exist/1' not found.")
    projects_dir = Path(templates_module.__file__).resolve().parents[4] / "depictio" / "projects"
    assert str(projects_dir) not in detail
    # The catalogue of usable ids still rides along.
    assert TEMPLATE_ID in detail
