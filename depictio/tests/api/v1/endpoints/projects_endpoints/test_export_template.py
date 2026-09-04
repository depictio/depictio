"""Tests for POST /projects/{id}/export_template (`build_template_bundle`).

The exporter's contract is the round-trip: a bundle written to disk must
re-instantiate through ``resolve_template`` unchanged. These prove the
sanitization (no ids/permissions/hashes in the output), the reverse
parameterization ({MANIFEST_URL}, {DATA_ROOT}), the tag-based dashboard
export, and the actual round-trip against the real resolver.
"""

import io
import zipfile
from unittest.mock import patch

import mongomock
import pytest
import yaml
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.projects_endpoints import export_template
from depictio.models.models.users import UserBase


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _manifest_project_doc(owner_id: ObjectId) -> dict:
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanManifest,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    manifest_url = "https://data.example.org/run42/manifest.json"
    workflow = Workflow(
        name="manifest",
        # Apostrophes are stored HTML-escaped by MongoModel.sanitize_description.
        description="Run42's workflow",
        engine=WorkflowEngine(name="python"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=[manifest_url]),
        data_collections=[
            DataCollection(
                data_collection_tag="samples",
                description="Sample's data",
                # Ingest bookkeeping the deltatable upsert writes per DC.
                flexible_metadata={
                    "deltatable_size_bytes": 4096,
                    "deltatable_size_updated": "2026-01-01T00:00:00",
                },
                config=DataCollectionConfig(
                    type="table",
                    metatype="metadata",
                    scan=Scan(
                        mode="manifest",
                        scan_parameters=ScanManifest(
                            manifest_url=manifest_url, manifest_type="samples"
                        ),
                    ),
                    dc_specific_properties=DCTableConfig(format="csv"),
                ),
            )
        ],
    )
    return {
        "_id": ObjectId(),
        "name": "Run42 Analysis",
        # As persisted: already through the validator once.
        "description": "Run42&#x27;s project",
        "project_type": "basic",
        "is_public": False,
        "permissions": {"owners": [{"_id": owner_id}], "editors": [], "viewers": []},
        "hash": "abc123",
        "registration_time": "2026-01-01 00:00:00",
        "last_modified": "2026-01-02 00:00:00",
        "workflows": [workflow.mongo()],
    }


def _instantiate(bundle: dict[str, str]):
    """Re-instantiate a bundle the way template instantiation does."""
    from depictio.cli.cli.utils.templates import substitute_template_variables
    from depictio.models.models.projects import Project

    cfg = yaml.safe_load(bundle["template.yaml"])
    cfg.pop("template")
    cfg = substitute_template_variables(
        cfg, {"MANIFEST_URL": "https://mirror.example.org/manifest.json"}
    )
    cfg["permissions"] = {"owners": [{"_id": ObjectId(), "email": "owner@example.com"}]}
    return Project(**cfg)


def _dashboard_doc(project_oid: ObjectId, wf_id, dc_id) -> dict:
    return {
        "_id": ObjectId(),
        "dashboard_id": ObjectId(),
        "project_id": project_oid,
        "title": "Run42 Overview",
        "is_main_tab": True,
        "stored_metadata": [
            {
                "index": "11111111-1111-1111-1111-111111111111",
                "component_type": "card",
                "wf_id": str(wf_id),
                "dc_id": str(dc_id),
                "column_name": "depictio_manifest_id",
                "aggregation": "nunique",
                "column_type": "object",
                "title": "Sample entries",
            }
        ],
        "buttons_data": {},
        "stored_layout_data": {},
    }


@pytest.fixture()
def mock_db():
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(export_template, "projects_collection", database["projects"]),
        patch.object(export_template, "dashboards_collection", database["dashboards"]),
        # Tag enrichment inside the dashboard exporter falls back to
        # depictio.api.v1.db.db — point it at the same mongomock database.
        patch("depictio.api.v1.db.db", database),
    ):
        yield database


def _build(project_id: str, user, **kwargs):
    kwargs.setdefault("template_id", "test-lab/exported/1")
    return export_template.build_template_bundle(project_id, user, **kwargs)


def test_unknown_project_404(mock_db):
    with pytest.raises(HTTPException) as exc:
        _build(str(ObjectId()), _user())
    assert exc.value.status_code == 404


def test_no_edit_permission_403(mock_db):
    doc = _manifest_project_doc(ObjectId())
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _build(str(doc["_id"]), _user())
    assert exc.value.status_code == 403


def test_bad_template_id_422(mock_db):
    user = _user()
    doc = _manifest_project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    with pytest.raises(HTTPException) as exc:
        _build(str(doc["_id"]), user, template_id="../escape")
    assert exc.value.status_code == 422


def test_bundle_sanitized_and_parameterized(mock_db):
    user = _user()
    doc = _manifest_project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    wf = doc["workflows"][0]
    mock_db["dashboards"].insert_one(
        _dashboard_doc(doc["_id"], wf["_id"], wf["data_collections"][0]["_id"])
    )

    bundle = _build(str(doc["_id"]), user, description="A test template")

    assert set(bundle) == {"template.yaml", "dashboards/run42_overview.yaml"}
    template = yaml.safe_load(bundle["template.yaml"])

    meta = template["template"]
    assert meta["template_id"] == "test-lab/exported/1"
    assert meta["version"] == "1.0.0"
    assert [v["name"] for v in meta["variables"]] == ["MANIFEST_URL"]
    assert meta["dashboards"] == ["dashboards/run42_overview.yaml"]

    # Sanitization: no runtime key survives at any nesting level.
    forbidden_keys = {
        "permissions",
        "_id",
        "id",
        "hash",
        "registration_time",
        "last_modified",
        "flexible_metadata",
    }

    def _assert_clean(node):
        if isinstance(node, dict):
            assert not forbidden_keys & set(node), f"runtime key leaked: {node.keys()}"
            for value in node.values():
                _assert_clean(value)
        elif isinstance(node, list):
            for item in node:
                _assert_clean(item)

    _assert_clean(template)
    assert "abc123" not in bundle["template.yaml"]  # the stored project hash
    assert "deltatable_size" not in bundle["template.yaml"]  # per-DC ingest bookkeeping

    # Descriptions are authored text again, not the HTML-escaped stored form.
    assert "&#x27;" not in bundle["template.yaml"]
    assert template["description"] == "Run42's project"
    assert template["workflows"][0]["description"] == "Run42's workflow"
    assert template["workflows"][0]["data_collections"][0]["description"] == "Sample's data"

    # Reverse parameterization: stored URL became the placeholder everywhere.
    scan = template["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["scan_parameters"]["manifest_url"] == "{MANIFEST_URL}"
    assert template["workflows"][0]["data_location"]["locations"] == ["{MANIFEST_URL}"]
    assert "data.example.org" not in bundle["template.yaml"]

    # Dashboard export is tag-based, not id-based.
    dash_yaml = bundle["dashboards/run42_overview.yaml"]
    assert "workflow_tag" in dash_yaml
    assert "data_collection_tag" in dash_yaml
    assert str(wf["_id"]) not in dash_yaml


def test_descriptions_round_trip_unchanged(mock_db):
    """Project -> bundle -> Project must give back the stored description
    (escaped exactly once), not an ever-growing &amp;#x27; chain."""
    user = _user()
    doc = _manifest_project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    wf = doc["workflows"][0]
    dc = wf["data_collections"][0]
    assert dc["description"] == "Sample&#x27;s data"  # stored form, escaped once

    project = _instantiate(_build(str(doc["_id"]), user))

    assert project.description == doc["description"]
    assert project.workflows[0].description == wf["description"]
    assert project.workflows[0].data_collections[0].description == dc["description"]
    assert project.workflows[0].data_collections[0].flexible_metadata is None

    # A second export/instantiate cycle is a fixed point.
    again = _instantiate(_build(str(doc["_id"]), user))
    assert again.workflows[0].data_collections[0].description == dc["description"]


def test_data_root_parameterization(mock_db):
    from depictio.models.models.data_collections import (
        DataCollection,
        DataCollectionConfig,
        Scan,
        ScanSingle,
    )
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.workflows import (
        Workflow,
        WorkflowConfig,
        WorkflowDataLocation,
        WorkflowEngine,
    )

    user = _user()
    workflow = Workflow(
        name="local",
        engine=WorkflowEngine(name="python"),
        config=WorkflowConfig(),
        data_location=WorkflowDataLocation(structure="flat", locations=["/data/run42"]),
        data_collections=[
            DataCollection(
                data_collection_tag="table",
                config=DataCollectionConfig(
                    type="table",
                    metatype="metadata",
                    scan=Scan(
                        mode="single",
                        scan_parameters=ScanSingle(filename="/data/run42/table.csv"),
                    ),
                    dc_specific_properties=DCTableConfig(format="csv"),
                ),
            )
        ],
    )
    doc = {
        "_id": ObjectId(),
        "name": "Local Project",
        "permissions": {"owners": [{"_id": user.id}]},
        "workflows": [workflow.mongo()],
    }
    mock_db["projects"].insert_one(doc)

    bundle = _build(str(doc["_id"]), user, data_root="/data/run42")
    template = yaml.safe_load(bundle["template.yaml"])

    assert [v["name"] for v in template["template"]["variables"]] == ["DATA_ROOT"]
    assert template["workflows"][0]["data_location"]["locations"] == ["{DATA_ROOT}"]
    scan = template["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["scan_parameters"]["filename"] == "{DATA_ROOT}/table.csv"
    assert "/data/run42" not in bundle["template.yaml"]


def test_round_trip_through_resolve_template(mock_db, tmp_path):
    """The exported bundle must re-instantiate through the real resolver."""
    from depictio.cli.cli.utils import templates as templates_mod

    user = _user()
    doc = _manifest_project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    wf = doc["workflows"][0]
    mock_db["dashboards"].insert_one(
        _dashboard_doc(doc["_id"], wf["_id"], wf["data_collections"][0]["_id"])
    )

    bundle = _build(str(doc["_id"]), user)

    template_dir = tmp_path / "test-lab" / "exported" / "1"
    for rel_path, content in bundle.items():
        target = template_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    with patch.object(
        templates_mod, "locate_template", return_value=template_dir / "template.yaml"
    ):
        resolved, meta, origin, dashboard_paths, variables = templates_mod.resolve_template(
            "test-lab/exported/1",
            None,  # manifest-driven: no data root
            project_name="Round Trip",
            extra_vars={"MANIFEST_URL": "https://mirror.example.org/manifest.json"},
        )

    assert meta.template_id == "test-lab/exported/1"
    assert resolved["name"] == "Round Trip"
    scan = resolved["workflows"][0]["data_collections"][0]["config"]["scan"]
    assert scan["scan_parameters"]["manifest_url"] == "https://mirror.example.org/manifest.json"
    assert [p.name for p in dashboard_paths] == ["run42_overview.yaml"]
    assert variables["MANIFEST_URL"] == "https://mirror.example.org/manifest.json"


# ── bundle_to_zip: the bytes the route actually sends ───────────────────────


def test_bundle_to_zip_round_trips_every_member():
    bundle = {
        "template.yaml": "name: Run42's project\n",
        "dashboards/run42_overview.yaml": "title: Run42 Overview\n",
    }

    data = export_template.bundle_to_zip(bundle)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == list(bundle)  # bundle order is archive order
        assert {name: archive.read(name).decode("utf-8") for name in bundle} == bundle
        assert {info.compress_type for info in archive.infolist()} == {zipfile.ZIP_DEFLATED}


def test_bundle_to_zip_keeps_non_ascii_text():
    text = "description: Café résumé 中文\n"

    data = export_template.bundle_to_zip({"template.yaml": text})

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.read("template.yaml").decode("utf-8") == text


def test_zipped_bundle_is_what_the_cli_unpacks(mock_db, tmp_path):
    """Route body to CLI: the archive built from a real bundle passes the CLI's
    zip-slip guard and unpacks into the template directory layout."""
    from depictio.cli.cli.commands.template import _members_within

    user = _user()
    doc = _manifest_project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    wf = doc["workflows"][0]
    mock_db["dashboards"].insert_one(
        _dashboard_doc(doc["_id"], wf["_id"], wf["data_collections"][0]["_id"])
    )
    bundle = _build(str(doc["_id"]), user)

    data = export_template.bundle_to_zip(bundle)

    target = tmp_path / "test-lab" / "exported" / "1"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(_members_within(archive, target)) == sorted(bundle)
        target.mkdir(parents=True)
        archive.extractall(target)
    template = yaml.safe_load((target / "template.yaml").read_text())
    assert template["template"]["template_id"] == "test-lab/exported/1"
    assert (target / "dashboards" / "run42_overview.yaml").read_text() == (
        bundle["dashboards/run42_overview.yaml"]
    )
