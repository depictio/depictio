"""The `spatial_cells` kind: config, roles, sampling and the showcase binding.

Segmented cells drawn in image coordinates. The kind is INCUBATING (pending the
docs/design/advanced-viz.md section 8 review against an `embedding` bound to
the centroids), so the showcase tab that draws both is its only binding and is
checked here against the real fixture columns.

Pure-model + fixture reads: no DB, no network.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from depictio.models.components.advanced_viz.catalog import role_config_key
from depictio.models.components.advanced_viz.configs import SpatialCellsConfig, VizConfig
from depictio.models.components.advanced_viz.record_link import SELECTION_EMITTING_KINDS
from depictio.models.components.advanced_viz.sampling import policy_for_kind
from depictio.models.components.advanced_viz.schemas import (
    _OPTIONAL_ROLES,
    CANONICAL_SCHEMAS,
    INCUBATING,
    KIND_METADATA,
    ROLE_NAMES,
    role_dtype_specs,
    suggest_viz_kinds,
    validate_binding,
)

REPO = Path(__file__).resolve().parents[3]
SHOWCASE = REPO / "depictio" / "projects" / "init" / "advanced_viz_showcase"
FIXTURE = SHOWCASE / "data" / "spatial_cells_demo.tsv"
TAB = SHOWCASE / "dashboards" / "spatial_cells.yaml"

VIZ_CONFIG = TypeAdapter(VizConfig)

# The column set nf-core/mcmicro's mcquant writes for one image.
MCQUANT_SCHEMA = {
    "CellID": "Int64",
    "DNA_1": "Float64",
    "CD3": "Float64",
    "CD20": "Float64",
    "PanCK": "Float64",
    "X_centroid": "Float64",
    "Y_centroid": "Float64",
    "Area": "Int64",
    "MajorAxisLength": "Float64",
    "MinorAxisLength": "Float64",
    "Eccentricity": "Float64",
    "Solidity": "Float64",
    "Extent": "Float64",
    "Orientation": "Float64",
}


def _fixture_rows() -> tuple[list[str], list[dict[str, str]]]:
    with FIXTURE.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    return list(reader.fieldnames or []), rows


def _fixture_schema() -> dict[str, str]:
    """Column -> polars dtype name, as a scanned DC would report it."""
    header, rows = _fixture_rows()
    schema: dict[str, str] = {}
    for column in header:
        values = [row[column] for row in rows[:500]]
        if all(re.fullmatch(r"-?\d+", v) for v in values):
            schema[column] = "Int64"
        elif all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in values):
            schema[column] = "Float64"
        else:
            schema[column] = "String"
    return schema


def _tab_component(kind: str) -> dict:
    doc = yaml.safe_load(TAB.read_text())
    return next(c for c in doc["components"] if c.get("viz_kind") == kind)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registered_in_every_table():
    assert set(CANONICAL_SCHEMAS["spatial_cells"]) == {"cell_id", "x", "y"}
    assert set(_OPTIONAL_ROLES["spatial_cells"]) == {"value", "category", "sample", "area"}
    assert set(ROLE_NAMES["spatial_cells"]) >= {"cell_id", "x", "y", "area"}
    assert KIND_METADATA["spatial_cells"]["icon"] == "tabler:microscope"
    # Incubating until the section 8 review, with the reason written beside it.
    assert "spatial_cells" in INCUBATING
    specs = role_dtype_specs("spatial_cells")
    assert specs["cell_id"]["required"] and not specs["area"]["required"]
    assert all(specs[role]["description"] for role in specs)


def test_a_cell_table_is_sampled_uniformly_and_selects_on_its_id():
    # One marker per cell and no aggregate, like embedding: a uniform subset of
    # a tissue is the same tissue, less dense.
    assert policy_for_kind("spatial_cells") == "hash"
    assert policy_for_kind("spatial_cells") == policy_for_kind("embedding")
    assert SELECTION_EMITTING_KINDS["spatial_cells"] == (
        "selection_column",
        "cell_id_col",
        "=cell_id",
    )
    assert role_config_key("spatial_cells", "value_columns") == "value_columns"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_defaults_draw_an_image_frame():
    cfg = SpatialCellsConfig()
    assert cfg.y_axis == "image"
    assert cfg.sample_display == "select"
    assert (cfg.clip_low_pct, cfg.clip_high_pct) == (1.0, 99.0)
    assert cfg.size_by_area is True
    assert cfg.selection_enabled is False
    assert cfg.transform == "none"
    assert 1_000 <= cfg.max_cells <= 1_000_000


def test_round_trips_through_the_union():
    cfg = VIZ_CONFIG.validate_python(
        {
            "viz_kind": "spatial_cells",
            "cell_id_col": "CellID",
            "x_col": "X_centroid",
            "y_col": "Y_centroid",
            "value_columns_pattern": "^(CD|Pan)",
            "transform": "asinh",
            "asinh_cofactor": 5,
            "background_url": "/previews/{sample}.png",
            "background_width": 1000,
            "background_height": 800,
        }
    )
    assert isinstance(cfg, SpatialCellsConfig)
    assert cfg.asinh_cofactor == 5


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"value_columns": ["CD3"], "value_columns_pattern": "^CD"}, "mutually exclusive"),
        ({"value_columns_pattern": "("}, "regular expression"),
        ({"clip_low_pct": 50, "clip_high_pct": 50}, "below clip_high_pct"),
        ({"background_url": "/a.png"}, "background_width"),
        ({"color_by": "category"}, "category_col"),
        ({"y_axis": "polar"}, None),
        ({"max_cells": 10}, None),
        ({"not_a_field": 1}, None),
    ],
)
def test_rejects_what_the_renderer_could_not_draw(bad: dict, message: str | None):
    with pytest.raises(ValidationError) as err:
        SpatialCellsConfig(**bad)
    if message:
        assert message in str(err.value)


def test_accepts_a_narrow_clip_window():
    # The window is the reader's to choose, as long as it is a window.
    assert SpatialCellsConfig(clip_low_pct=40, clip_high_pct=60).clip_high_pct == 60


def test_an_empty_marker_list_does_not_compete_with_a_pattern():
    # What the builder writes when its Marker columns picker is cleared.
    cfg = SpatialCellsConfig(value_columns=[], value_columns_pattern="^CD")
    assert cfg.value_columns == []


# ---------------------------------------------------------------------------
# Binding and suggestion
# ---------------------------------------------------------------------------


def test_binds_an_mcquant_table():
    cfg = SpatialCellsConfig(
        cell_id_col="CellID",
        x_col="X_centroid",
        y_col="Y_centroid",
        area_col="Area",
        value_col="CD3",
    )
    assert validate_binding(cfg, MCQUANT_SCHEMA) == []


def test_an_mcquant_table_suggests_spatial_cells_by_name():
    ranked = {s.viz_kind: s for s in suggest_viz_kinds(MCQUANT_SCHEMA)}
    spatial = ranked["spatial_cells"]
    assert spatial.match == "named"
    assert spatial.role_candidates["x"][0] == "X_centroid"
    assert spatial.role_candidates["y"][0] == "Y_centroid"
    assert spatial.role_candidates["cell_id"][0] == "CellID"


def test_a_plain_xy_table_is_not_a_cell_table():
    # Every scatter table has an x and a y; without a centroid or a morphology
    # column the kind stays pickable but is not recommended.
    ranked = {
        s.viz_kind: s for s in suggest_viz_kinds({"cell": "String", "x": "Float64", "y": "Float64"})
    }
    assert ranked["spatial_cells"].match == "weak"
    assert ranked["spatial_cells"].score < 0.8


# ---------------------------------------------------------------------------
# Showcase fixture and tab
# ---------------------------------------------------------------------------


def test_fixture_is_two_images_of_unique_cells():
    header, rows = _fixture_rows()
    assert header[:1] == ["CellID"] and {"X_centroid", "Y_centroid", "Area"} <= set(header)
    by_sample: dict[str, int] = {}
    for row in rows:
        by_sample[row["sample"]] = by_sample.get(row["sample"], 0) + 1
    assert set(by_sample) == {"tonsil_1", "tonsil_2"}
    assert all(3_000 <= n <= 5_000 for n in by_sample.values()), by_sample
    # mcquant's CellID restarts per image; the qualified id the tab selects on
    # does not.
    assert len({row["cell_id"] for row in rows}) == len(rows)
    assert len({row["CellID"] for row in rows}) < len(rows)
    # Centroids are inside their image (1000 x 800 and 900 x 900 px).
    size = {"tonsil_1": (1000, 800), "tonsil_2": (900, 900)}
    for row in rows:
        w, h = size[row["sample"]]
        assert 0 <= float(row["X_centroid"]) <= w and 0 <= float(row["Y_centroid"]) <= h


def test_fixture_markers_are_spatially_structured():
    """CD20 marks the B cells and PanCK the epithelium, so the tab has something to show."""
    _, rows = _fixture_rows()

    def mean(cell_type: str, marker: str) -> float:
        values = [float(r[marker]) for r in rows if r["cell_type"] == cell_type]
        return sum(values) / len(values)

    assert mean("B cell", "CD20") > 5 * mean("T cell", "CD20")
    assert mean("T cell", "CD3") > 5 * mean("B cell", "CD3")
    assert mean("Epithelial", "PanCK") > 5 * mean("T cell", "PanCK")
    assert mean("Germinal centre B", "Ki67") > 3 * mean("B cell", "Ki67")
    # The epithelium is the band along the top of each image.
    epithelial_y = [float(r["Y_centroid"]) for r in rows if r["cell_type"] == "Epithelial"]
    assert max(epithelial_y) < 250


def test_showcase_tab_binds_the_fixture_twice():
    schema = _fixture_schema()
    spatial = _tab_component("spatial_cells")
    cfg = VIZ_CONFIG.validate_python(spatial["config"])
    assert isinstance(cfg, SpatialCellsConfig)
    assert validate_binding(cfg, schema) == []
    assert cfg.value_columns and set(cfg.value_columns) <= set(schema)
    assert all(schema[c] == "Float64" for c in cfg.value_columns)
    # The comparison tile reads the same collection and selects on the same id,
    # so a lasso in one marks the cells in the other.
    embedding = _tab_component("embedding")
    assert embedding["data_collection_tag"] == spatial["data_collection_tag"]
    emb = VIZ_CONFIG.validate_python(embedding["config"])
    assert (emb.dim_1_col, emb.dim_2_col) == (cfg.x_col, cfg.y_col)
    assert emb.sample_id_col == cfg.cell_id_col
    assert emb.selection_enabled and cfg.selection_enabled
    # Side by side, controls left to the width-based dock (RULES section 8).
    assert spatial["layout"]["y"] == embedding["layout"]["y"]
    for tile in (spatial, embedding):
        assert tile["layout"]["w"] == 4
        assert "controls_placement" not in tile["config"]
