"""Unit tests for the project-as-template export helpers."""

import copy

from bson import ObjectId

from depictio.api.v1.endpoints.templates_endpoints.utils import (
    build_template_config,
    collect_fs_paths,
    compute_data_root,
    strip_identity,
)
from depictio.models.models.projects import Project
from depictio.models.models.templates import TemplateMetadata
from depictio.models.models.users import Permission


def _iris_project_doc() -> dict:
    """A minimal iris-like stored project document (with identity fields)."""
    return {
        "_id": ObjectId("646b0f3c1e4a2d7f8e5b8c9a"),
        "name": "Iris Dataset Project Data Analysis",
        "project_type": "basic",
        "is_public": True,
        "hash": "deadbeef",
        "registration_time": "2024-01-01 00:00:00",
        "permissions": {"owners": [{"_id": ObjectId(), "email": "admin@example.com"}]},
        "workflows": [
            {
                "_id": ObjectId("646b0f3c1e4a2d7f8e5b8c9b"),
                "name": "iris_workflow",
                "engine": {"name": "python"},
                "data_location": {
                    "structure": "flat",
                    "locations": ["/app/depictio/projects/init/iris"],
                },
                "data_collections": [
                    {
                        "_id": ObjectId("646b0f3c1e4a2d7f8e5b8c9c"),
                        "data_collection_tag": "iris_table",
                        "description": "Iris dataset in CSV format",
                        "config": {
                            "type": "Table",
                            "metatype": "Metadata",
                            "scan": {
                                "mode": "single",
                                "scan_parameters": {
                                    "filename": "/app/depictio/projects/init/iris/data/iris.csv"
                                },
                            },
                            "dc_specific_properties": {
                                "format": "CSV",
                                "polars_kwargs": {"separator": ","},
                            },
                        },
                    }
                ],
            }
        ],
    }


def test_strip_identity_removes_db_keys():
    src = {
        "_id": 1,
        "id": 2,
        "hash": "x",
        "registration_time": "t",
        "name": "keep",
        "nested": [{"_id": 3, "k": "v"}],
    }
    out = strip_identity(src)
    assert out == {"name": "keep", "nested": [{"k": "v"}]}


def test_compute_data_root_common_prefix():
    paths = [
        "/data/project/run_a",
        "/data/project/run_b/file.csv",
    ]
    assert compute_data_root(paths) == "/data/project"


def test_compute_data_root_single_file_uses_dirname():
    assert compute_data_root(["/data/project/file.csv"]) == "/data/project"


def test_compute_data_root_empty_returns_none():
    assert compute_data_root([]) is None


def test_collect_fs_paths():
    doc = _iris_project_doc()
    paths = collect_fs_paths(doc)
    assert "/app/depictio/projects/init/iris" in paths
    assert "/app/depictio/projects/init/iris/data/iris.csv" in paths


def test_build_template_config_strips_identity_and_parameterizes():
    doc = _iris_project_doc()
    original = copy.deepcopy(doc)

    template_dict, data_root = build_template_config(
        doc,
        ["dashboards/overview.yaml"],
        template_id="user/iris/1.0.0",
        version="1.0.0",
        description="Iris template",
    )

    # Input document is not mutated.
    assert doc == original

    assert data_root == "/app/depictio/projects/init/iris"

    # Identity and permission fields are gone.
    assert "_id" not in template_dict
    assert "permissions" not in template_dict
    assert "hash" not in template_dict
    wf = template_dict["workflows"][0]
    assert "_id" not in wf
    dc = wf["data_collections"][0]
    assert "_id" not in dc

    # Paths are parameterized to {DATA_ROOT}.
    assert wf["data_location"]["locations"] == ["{DATA_ROOT}"]
    assert dc["config"]["scan"]["scan_parameters"]["filename"] == "{DATA_ROOT}/data/iris.csv"

    # The template: block is present and valid.
    assert "template" in template_dict
    TemplateMetadata(**template_dict["template"])
    assert template_dict["template"]["dashboards"] == ["dashboards/overview.yaml"]


def test_exported_config_is_instantiable_as_project():
    """After substituting {DATA_ROOT} and adding permissions, the cleaned
    config must validate as a Project — i.e. it is re-importable."""
    doc = _iris_project_doc()
    template_dict, _ = build_template_config(
        doc,
        ["dashboards/overview.yaml"],
        template_id="user/iris/1.0.0",
        version="1.0.0",
        description="Iris template",
    )

    # Simulate the template engine: drop the template block, substitute the
    # DATA_ROOT variable, and assign the importing user's permissions.
    config = {k: v for k, v in template_dict.items() if k != "template"}

    def _subst(obj):
        if isinstance(obj, str):
            return obj.replace("{DATA_ROOT}", "/home/colleague/iris")
        if isinstance(obj, dict):
            return {k: _subst(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_subst(i) for i in obj]
        return obj

    config = _subst(config)
    config["permissions"] = Permission().model_dump()

    project = Project(**config)
    assert project.name == "Iris Dataset Project Data Analysis"
    loc = project.workflows[0].data_location.locations[0]
    assert loc == "/home/colleague/iris"
