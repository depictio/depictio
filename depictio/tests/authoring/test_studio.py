"""Tests for the Depictio Studio authoring backend (``depictio/authoring``).

Covers the service-free path end to end: config-by-example, tree/preview,
recognize, the live render payload, and the dashboard export (which must produce
a ``project.yaml`` that validates against ``Project`` and a ``dashboard.yaml``
that round-trips through ``DashboardDataLite``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from depictio.authoring import (
    export_dashboard as export_mod,
)
from depictio.authoring import (
    preview as preview_mod,
)
from depictio.authoring import (
    recognize as recognize_mod,
)
from depictio.authoring import (
    render as render_mod,
)
from depictio.authoring import (
    suggest as suggest_mod,
)
from depictio.authoring import (
    tree as tree_mod,
)
from depictio.authoring.paths import StudioPathError, safe_resolve


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A small fake run tree with two star quant files + a samplesheet."""
    for sample in ("S1", "S2", "S3"):
        d = tmp_path / "star" / sample
        d.mkdir(parents=True)
        (d / "quant.tsv").write_text("gene\tcount\nA\t1\nB\t2\n")
    (tmp_path / "samplesheet.csv").write_text("sample,condition\nS1,ctrl\nS2,treat\n")
    return tmp_path


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def test_safe_resolve_rejects_escape(run_dir: Path) -> None:
    assert safe_resolve(run_dir, "star/S1/quant.tsv").name == "quant.tsv"
    with pytest.raises(StudioPathError):
        safe_resolve(run_dir, "../../etc/passwd")


# --------------------------------------------------------------------------- #
# config-by-example
# --------------------------------------------------------------------------- #
def test_config_by_example_single(run_dir: Path) -> None:
    res = recognize_mod.config_by_example(run_dir, ["star/S1/quant.tsv"])
    assert res["path_glob"] == "**/quant.tsv"
    assert res["match_count"] == 3


def test_config_by_example_anti_unify(run_dir: Path) -> None:
    res = recognize_mod.config_by_example(run_dir, ["star/S1/quant.tsv", "star/S2/quant.tsv"])
    # The varying middle segment collapses; all three siblings match.
    assert res["path_glob"] == "star/S*/quant.tsv"
    assert res["match_count"] == 3
    assert "star/S3/quant.tsv" in res["matched"]


def test_wildcard_token() -> None:
    assert recognize_mod._wildcard_token(["S1.quant", "S2.quant"]) == "S*.quant"
    assert recognize_mod._wildcard_token(["quant.tsv", "quant.tsv"]) == "quant.tsv"


# --------------------------------------------------------------------------- #
# tree + preview + suggest
# --------------------------------------------------------------------------- #
def test_build_tree(run_dir: Path) -> None:
    t = tree_mod.build_tree(run_dir)
    names = {c["name"] for c in t["children"]}
    assert {"star", "samplesheet.csv"} <= names
    sheet = next(c for c in t["children"] if c["name"] == "samplesheet.csv")
    assert sheet["previewable"] is True


def test_preview_file(run_dir: Path) -> None:
    pv = preview_mod.preview_file(run_dir, "samplesheet.csv")
    assert pv["columns"] == ["sample", "condition"]
    assert pv["schema"] == {"sample": "String", "condition": "String"}
    assert pv["format"] == "csv"
    assert pv["n_rows_preview"] == 2


def test_suggest_returns_ranked_kinds(run_dir: Path) -> None:
    pv = preview_mod.preview_file(run_dir, "star/S1/quant.tsv")
    out = suggest_mod.suggest_for_schema(pv["schema"])
    assert out, "expected at least one suggestion"
    scores = [s["score"] for s in out]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- #
# recognize
# --------------------------------------------------------------------------- #
def test_recognize_unknown_file(run_dir: Path) -> None:
    res = recognize_mod.recognize(run_dir, "samplesheet.csv")
    assert res["recognized"] is False
    assert res["config_by_example"]["path_glob"] == "**/samplesheet.csv"


# --------------------------------------------------------------------------- #
# render (build_payload on a transient CatalogOutput)
# --------------------------------------------------------------------------- #
def test_render_card(run_dir: Path) -> None:
    blob = render_mod.render_spec(
        run_dir, "star/S1/quant.tsv", {"component": "card", "column": "count", "aggregation": "sum"}
    )
    assert blob["data"]["cards"]["values"] == {"studio-0": 3}


def test_render_figure(run_dir: Path) -> None:
    blob = render_mod.render_spec(
        run_dir,
        "star/S1/quant.tsv",
        {"component": "figure", "visu_type": "bar", "dict_kwargs": {"x": "gene", "y": "count"}},
    )
    assert "studio-0" in blob["data"]["figures"]
    assert blob["renders"][0]["component_type"] == "figure"


def test_render_invalid_spec_raises(run_dir: Path) -> None:
    with pytest.raises(Exception):
        render_mod.render_spec(run_dir, "star/S1/quant.tsv", {"component": "figure"})


# --------------------------------------------------------------------------- #
# export/dashboard
# --------------------------------------------------------------------------- #
def test_export_dashboard(run_dir: Path) -> None:
    from depictio.models.models.dashboards import DashboardDataLite
    from depictio.models.models.projects import Project

    payload = {
        "name": "Studio Test",
        "title": "Studio Test Dashboard",
        "data_collections": [{"dc_tag": "quant", "path": "star/S1/quant.tsv"}],
        "components": [
            {
                "component_type": "card",
                "data_collection_tag": "quant",
                "aggregation": "sum",
                "column_name": "count",
                "column_type": "int64",
            },
            {
                "component_type": "figure",
                "data_collection_tag": "quant",
                "visu_type": "bar",
                "dict_kwargs": {"x": "gene", "y": "count"},
            },
        ],
    }
    out = export_mod.export_dashboard(run_dir, payload)

    # dashboard.yaml round-trips through the real Lite model.
    lite = DashboardDataLite.from_yaml(out["dashboard_yaml"])
    assert len(lite.components) == 2

    # project.yaml validates against the real Project model (permissions are
    # injected by `depictio run`, so add a stub here to exercise full validation).
    import yaml

    proj = yaml.safe_load(out["project_yaml"])
    proj["permissions"] = {"owners": [], "editors": [], "viewers": []}
    Project.model_validate(proj)

    # Layout was auto-generated for each component.
    for comp in lite.components:
        layout = comp["layout"] if isinstance(comp, dict) else comp.layout
        assert set(layout) == {"x", "y", "w", "h"}


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_routes_via_testclient(run_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from depictio.authoring.server import create_app

    client = TestClient(create_app(run_dir))

    assert client.get("/studio/tree").status_code == 200
    assert client.post("/studio/preview-data", json={"path": "samplesheet.csv"}).status_code == 200
    assert client.post("/studio/suggest", json={"schema": {"a": "Float64"}}).status_code == 200

    r = client.post(
        "/studio/render",
        json={
            "path": "star/S1/quant.tsv",
            "spec": {"component": "card", "column": "count", "aggregation": "sum"},
        },
    )
    assert r.status_code == 200
    assert r.json()["data"]["cards"]["values"] == {"studio-0": 3}

    # Catalogue export is deferred → 501.
    assert client.post("/studio/export/catalog").status_code == 501

    # Path escape → 400.
    assert client.post("/studio/preview-data", json={"path": "../../etc/passwd"}).status_code == 400
