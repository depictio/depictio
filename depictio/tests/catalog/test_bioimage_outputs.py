"""Image outputs in the catalog: `dc_type: bioimage` + the `bioimage_viewer` render.

An imaging tool declares its image and mask stores as bioimage outputs and its
per-cell table as an ordinary table output carrying the viewer render, whose
roles name the partner outputs. These tests pin the model rules, the partner
resolution (in-tool and across tools), the `use:` expansion, run-folder
recognition + DC proposals, the preview payload and the manifest, on a
synthetic tool written to disk the way a catalog folder is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import depictio.models.components.advanced_viz.catalog as catalog_mod
from depictio.catalog.payload import (
    BIOIMAGE_PLACEHOLDER,
    advanced_viz_persist_config,
    build_payload,
)
from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogOutput,
    _load_tool_dir,
    check_bioimage_fixture,
    check_bioimage_renders,
    match_run_dir,
    propose_data_collections,
)
from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.models.models.data_collections_types.bioimage import DCBioimageConfig

IMAGE = {
    "id": "imgtool_registered",
    "name": "Registered image",
    "find": {"path_glob": "**/registration/*.ome.tif"},
    "dc_type": "bioimage",
    "bioimage": {"format": "ome-tiff"},
}
MASK = {
    "id": "imgtool_mask",
    "name": "Cell mask",
    "find": {"filename": "*_mask.tif"},
    "dc_type": "bioimage",
    "bioimage": {"format": "tiff", "kind": "labels", "sample_pattern": r"^(.+?)_mask\.tif$"},
}
VIEWER = {
    "id": "cell_viewer",
    "component": "advanced_viz",
    "kind": "bioimage_viewer",
    "roles": {
        "image": "registered",
        "labels": "mask",
        "cell_id": "CellID",
        "x": "X_centroid",
        "y": "Y_centroid",
        "color": "Area",
        "sample": "sample",
    },
}
CELLS = {
    "id": "imgtool_cells",
    "name": "Cell quantification",
    "find": {"filename": "*_cells.csv"},
    "columns": {
        "CellID": "Int64",
        "X_centroid": "Float64",
        "Y_centroid": "Float64",
        "Area": "Float64",
        "sample": "String",
    },
    "renders_as": [{"component": "table"}, VIEWER],
}


def _entry(*outputs: dict, tool_id: str = "imgtool") -> CatalogEntry:
    return CatalogEntry.model_validate({"id": tool_id, "name": tool_id, "outputs": list(outputs)})


def _with(base: dict, **changes) -> dict:
    return {**base, **changes}


def _viewer(**roles) -> dict:
    return _with(VIEWER, roles={k: v for k, v in {**VIEWER["roles"], **roles}.items() if v})


def _write_tool(root: Path, *outputs: dict, tool_id: str = "imgtool") -> Path:
    folder = root / tool_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "module.yaml").write_text(yaml.safe_dump({"id": tool_id, "name": tool_id}))
    for out in outputs:
        (folder / f"{out['id']}.yaml").write_text(yaml.safe_dump(out, sort_keys=False))
    return folder


# ---------------------------------------------------------------------------
# Model: the bioimage output shape
# ---------------------------------------------------------------------------


def test_worked_example_validates():
    entry = _entry(IMAGE, MASK, CELLS)
    outputs = {o.id: o for o in entry.outputs}
    assert outputs["imgtool_registered"].dc_type == "bioimage"
    assert outputs["imgtool_mask"].bioimage.kind == "labels"
    viewer = outputs["imgtool_cells"].renders_as[1]
    assert viewer.bound_columns() == set()  # grounded against the points output instead
    assert viewer.bioimage_column_roles()["cell_id"] == "CellID"


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (_with(IMAGE, bioimage=None), "needs a 'bioimage' block"),
        (_with(CELLS, bioimage={"format": "ome-tiff"}), "needs dc_type: bioimage"),
        (_with(IMAGE, columns={"a": "String"}), "no 'recipe' or 'columns'"),
        (_with(IMAGE, recipe="imgtool/x.py"), "no 'recipe' or 'columns'"),
        (
            _with(IMAGE, renders_as=[{"component": "card", "column": "a", "aggregation": "count"}]),
            "renders only as advanced_viz kind bioimage_viewer",
        ),
        (_with(IMAGE, find={"filename": "*.zarr"}), "cannot match a ome-tiff store"),
        (_with(IMAGE, fixture="sample.zarr"), "must be a ome-tiff store"),
        (_with(MASK, bioimage={"format": "tiff"}), "set kind 'labels'"),
        (
            _with(IMAGE, find={"filename": "*.zarr"}, bioimage={"format": "spatialdata"}),
            "image_path",
        ),
        (_with(MASK, bioimage={**MASK["bioimage"], "sample_pattern": "^.+_mask"}), "capture group"),
        (_with(MASK, bioimage={**MASK["bioimage"], "sample_pattern": "(("}), "not a valid regex"),
    ],
)
def test_bad_bioimage_outputs_are_rejected(output, message):
    with pytest.raises(ValueError, match=message):
        CatalogOutput.model_validate({k: v for k, v in output.items() if v is not None})


def test_bioimage_fixture_is_optional_and_shape_checked(tmp_path):
    folder = _write_tool(
        tmp_path,
        _with(IMAGE, fixture="tiny.ome.tif"),
        _with(
            MASK,
            find={"filename": "*_mask.zarr"},
            fixture="tiny_mask.zarr",
            bioimage={"format": "ome-zarr", "kind": "labels"},
        ),
        _with(MASK, id="imgtool_nofixture"),
    )
    (folder / "tiny.ome.tif").write_bytes(b"II*\x00")
    (folder / "tiny_mask.zarr").write_text("not a directory")
    by_id = {o.id: o for o in _load_tool_dir(folder).outputs}
    assert check_bioimage_fixture(by_id["imgtool_registered"]) == []
    assert "must be a directory" in check_bioimage_fixture(by_id["imgtool_mask"])[0]
    assert check_bioimage_fixture(by_id["imgtool_nofixture"]) == []


def test_zarr_store_find_accepts_a_directory_glob():
    out = CatalogOutput.model_validate(
        _with(
            IMAGE,
            find={"path_glob": "**/sopa/*.zarr"},
            bioimage={"format": "spatialdata", "image_path": "images/he"},
        )
    )
    assert out.bioimage.is_directory_store


# ---------------------------------------------------------------------------
# Model: the viewer render names its partners
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cells", "message"),
    [
        (_with(CELLS, renders_as=[_viewer(image="cells")]), "must name a bioimage output"),
        (_with(CELLS, renders_as=[_viewer(labels="registered")]), "of kind labels"),
        (_with(CELLS, renders_as=[_viewer(image="nope")]), "not an output"),
        (_with(CELLS, renders_as=[_viewer(image=None)]), "needs 'roles.image'"),
        (_with(CELLS, renders_as=[_viewer(color="Missing")]), r"\['Missing'\]"),
        (_with(CELLS, renders_as=[_viewer(image="bad ref!")]), "must name an output"),
        (_with(CELLS, renders_as=[_viewer(cell_id=None)]), "need 'roles.cell_id'"),
        (_with(CELLS, renders_as=[_viewer(y=None)]), "both 'x' and 'y'"),
        (_with(CELLS, renders_as=[_viewer(bogus="x")]), "unknown role"),
    ],
)
def test_bad_viewer_renders_are_rejected(cells, message):
    with pytest.raises(ValueError, match=message):
        _entry(IMAGE, MASK, cells)


def test_viewer_on_the_image_output_defaults_image_to_itself():
    image = _with(
        IMAGE,
        renders_as=[
            {"component": "advanced_viz", "kind": "bioimage_viewer", "roles": {"labels": "mask"}}
        ],
    )
    _entry(image, MASK)  # no `image` role needed


def test_viewer_on_the_image_output_needs_a_points_table_for_columns():
    image = _with(
        IMAGE,
        renders_as=[
            {"component": "advanced_viz", "kind": "bioimage_viewer", "roles": {"color": "X"}}
        ],
    )
    with pytest.raises(ValueError, match="names no points table"):
        _entry(image)


def test_cross_tool_refs_are_resolved_against_the_whole_catalog():
    images = _entry(IMAGE, MASK, tool_id="imgtool")
    cells = _with(
        CELLS,
        id="quant_cells",
        renders_as=[_viewer(image="imgtool/registered", labels="imgtool/mask")],
    )
    quant = _entry(cells, tool_id="quant")  # the tool validator cannot see imgtool: passes

    assert check_bioimage_renders([quant], catalog=[images]) == []
    missing = check_bioimage_renders([quant], catalog=[])
    assert any("unknown catalog tool" in p for p in missing)


def test_point_columns_are_grounded_against_the_points_fixture(tmp_path):
    cells = {k: v for k, v in CELLS.items() if k != "columns"}
    folder = _write_tool(tmp_path, IMAGE, MASK, _with(cells, fixture="cells.csv"))
    (folder / "cells.csv").write_text("CellID,X_centroid,Y_centroid,Area\n1,a,2.0,3.0\n")
    problems = check_bioimage_renders([_load_tool_dir(folder)], catalog=[])
    assert any("'sample'" in p and "absent" in p for p in problems)
    assert any("'X_centroid' is String" in p for p in problems)


def test_cli_validate_accepts_a_bioimage_tool(tmp_path):
    from typer.testing import CliRunner

    from depictio.cli.cli.commands.catalog import dev_app

    folder = _write_tool(tmp_path, IMAGE, MASK, CELLS)
    result = CliRunner().invoke(dev_app, ["validate", "--path", str(folder)])
    assert result.exit_code == 0, result.stdout


# ---------------------------------------------------------------------------
# `use:` expansion
# ---------------------------------------------------------------------------


@pytest.fixture
def imgtool_catalog(monkeypatch):
    entries = (_entry(IMAGE, MASK, CELLS),)
    monkeypatch.setattr(catalog_mod, "load_catalog_entries", lambda: entries)
    return entries


TAGS = {"image_dc_tag": "img", "labels_dc_tag": "mask", "points_dc_tag": "cells"}


def test_use_expands_column_roles_and_keeps_the_tiles_dc_tags(imgtool_catalog):
    c = AdvancedVizLiteComponent(
        workflow_tag="wf",
        data_collection_tag="img",
        use="imgtool/cell_viewer",
        config={**TAGS, "sample_dc_tag": "samples", "sample_column": "sample"},
    )
    assert c.viz_kind == "bioimage_viewer"
    cfg = c.config
    assert (cfg.cell_id_col, cfg.x_col, cfg.y_col, cfg.color_col) == (
        "CellID",
        "X_centroid",
        "Y_centroid",
        "Area",
    )
    assert cfg.points_sample_col == "sample"
    assert (cfg.image_dc_tag, cfg.labels_dc_tag, cfg.points_dc_tag) == ("img", "mask", "cells")
    assert cfg.sample_dc_tag == "samples"


def test_use_lists_every_missing_dc_tag(imgtool_catalog):
    with pytest.raises(ValueError) as err:
        AdvancedVizLiteComponent(
            workflow_tag="wf", data_collection_tag="img", use="imgtool/cell_viewer"
        )
    text = str(err.value)
    for key in ("image_dc_tag", "labels_dc_tag", "points_dc_tag"):
        assert f"config.{key}" in text


def test_use_labels_opt_out_with_explicit_null(imgtool_catalog):
    c = AdvancedVizLiteComponent(
        workflow_tag="wf",
        data_collection_tag="img",
        use="imgtool/cell_viewer",
        config={**TAGS, "labels_dc_tag": None},
    )
    assert c.config.labels_dc_tag is None


# ---------------------------------------------------------------------------
# Run-folder recognition and DC proposals
# ---------------------------------------------------------------------------


def test_match_and_propose_bioimage_and_table_dcs(tmp_path):
    zarr_image = _with(
        IMAGE,
        id="imgtool_zarr",
        find={"path_glob": "**/sopa/*.zarr"},
        bioimage={"format": "spatialdata", "image_path": "images/he"},
    )
    entries = (_entry(IMAGE, MASK, CELLS, zarr_image),)
    run = tmp_path / "run"
    (run / "x" / "registration").mkdir(parents=True)
    (run / "x" / "registration" / "s1.ome.tif").write_bytes(b"II*\x00")
    (run / "seg").mkdir()
    (run / "seg" / "s1_mask.tif").write_bytes(b"II*\x00")
    (run / "seg" / "s1_cells.csv").write_text("CellID\n1\n")
    (run / "x" / "sopa" / "s1.zarr" / "images").mkdir(parents=True)  # a store directory

    matches = match_run_dir(run, entries)
    by_output = {m.output_id: m for m in matches}
    assert by_output["imgtool_zarr"].path == "x/sopa/s1.zarr"
    assert by_output["imgtool_registered"].dc_type == "bioimage"
    assert by_output["imgtool_cells"].dc_type == "table"

    dcs = {d["data_collection_tag"]: d for d in propose_data_collections(matches, entries)}
    mask = dcs["imgtool_mask"]["config"]
    assert mask["type"] == "bioimage"
    assert mask["dc_specific_properties"]["kind"] == "labels"
    DCBioimageConfig.model_validate(mask["dc_specific_properties"])
    assert dcs["imgtool_zarr"]["config"]["dc_specific_properties"]["image_path"] == "images/he"
    assert dcs["imgtool_cells"]["config"]["type"] == "table"
    pattern = mask["scan"]["scan_parameters"]["regex_config"]["pattern"]
    import re

    assert re.match(pattern, "s1_mask.tif") and not re.match(pattern, "s1_cells.csv")


def test_cli_compose_dcs_prints_a_bioimage_dc(tmp_path, imgtool_catalog):
    from typer.testing import CliRunner

    from depictio.cli.cli.commands.catalog import dev_app

    (tmp_path / "registration").mkdir()
    (tmp_path / "registration" / "s1.ome.tif").write_bytes(b"II*\x00")
    result = CliRunner().invoke(dev_app, ["compose", str(tmp_path), "--dcs"])
    assert result.exit_code == 0, result.stdout
    dcs = yaml.safe_load(result.stdout)["data_collections"]
    assert dcs[0]["config"]["type"] == "bioimage"
    assert dcs[0]["config"]["dc_specific_properties"]["format"] == "ome-tiff"


# ---------------------------------------------------------------------------
# Preview payload, manifest, conformance
# ---------------------------------------------------------------------------


def test_payload_shows_the_placeholder_and_needs_no_image_fixture(tmp_path):
    folder = _write_tool(tmp_path, IMAGE, MASK, _with(CELLS, fixture="cells.csv"))
    (folder / "cells.csv").write_text(
        "CellID,X_centroid,Y_centroid,Area,sample\n1,1.0,2.0,3.0,s1\n"
    )
    outputs = {o.id: o for o in _load_tool_dir(folder).outputs}

    cells = build_payload(outputs["imgtool_cells"])
    viewer = cells["renders"][1]
    assert viewer["_unsupported"] == BIOIMAGE_PLACEHOLDER
    assert "_unsupported" not in cells["renders"][0]  # the table still previews

    image = _with(IMAGE, renders_as=[{"component": "advanced_viz", "kind": "bioimage_viewer"}])
    blob = build_payload(CatalogOutput.model_validate(image))
    assert blob["output"]["dc_type"] == "bioimage"
    assert blob["renders"][0]["_unsupported"] == BIOIMAGE_PLACEHOLDER
    assert advanced_viz_persist_config(outputs["imgtool_cells"], viewer_render(outputs)) is None


def viewer_render(outputs):
    return outputs["imgtool_cells"].renders_as[1]


def test_manifest_includes_bioimage_outputs(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from depictio.cli.cli.commands.catalog import dev_app

    catalog_dir = tmp_path / "depictio" / "catalog"
    _write_tool(catalog_dir, IMAGE, MASK, CELLS)
    monkeypatch.setattr(catalog_mod, "CATALOG_DIR", catalog_dir)
    result = CliRunner().invoke(dev_app, ["manifest", "--json"])
    assert result.exit_code == 0, result.stdout
    outputs = {o["id"]: o for o in json.loads(result.stdout)["tools"][0]["outputs"]}
    assert outputs["imgtool_mask"]["dc_type"] == "bioimage"
    assert outputs["imgtool_mask"]["bioimage"]["kind"] == "labels"
    assert outputs["imgtool_registered"]["fixtureContent"] is None


def test_conformance_lanes_leave_bioimage_outputs_unstaged():
    from depictio.projects.init.catalog_conformance.scripts.generate_project import (
        bioimage_outputs,
        raw_outputs,
    )

    entries = (_entry(IMAGE, MASK, CELLS),)
    assert [o.id for _, o in raw_outputs(entries)] == ["imgtool_cells"]
    assert [o.id for o in bioimage_outputs(entries)] == ["imgtool_registered", "imgtool_mask"]


def test_bundled_bioimage_outputs_are_exempt_in_the_conformance_manifest():
    from depictio.projects.init.catalog_conformance.scripts.generate_project import (
        PROJECT_DIR,
        bioimage_outputs,
    )

    manifest = json.loads((PROJECT_DIR / "manifest.json").read_text())
    for output in bioimage_outputs(catalog_mod.load_catalog_entries()):
        assert output.id in manifest["coverage_exemptions"], (
            "Rerun: uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project"
        )
        assert manifest["lanes"].get(output.id) == "bioimage"
