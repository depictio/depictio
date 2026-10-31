"""nanoseq's `design` collection: the hub's confounder columns, apart from the hub.

The template drops it when there is no design table, and with it the filters and
rings bound to it, so the hub keeps its columns (a run without a design table
still writes `unknown`) while no tile draws them.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.recipes import load_recipe, validate_schema

RECIPE = "nf-core/nanoseq/design.py"
TEMPLATE = Path(__file__).parents[2] / "projects/nf-core/nanoseq/3.0.0/template.yaml"
BASE = Path(__file__).parents[2] / "projects/nf-core/nanoseq/3.0.0/dashboards/base.yaml"


def _hub() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample_id": ["B_R1", "A_R1"],
            "condition": ["B", "A"],
            "replicate": [1, 1],
            "protocol": ["cdna", "directcdna"],
            "source_replicate": ["r1", "r3"],
            "run_id": ["run1", "run2"],
            "reference": ["ref", "ref"],
        }
    )


@pytest.mark.no_db
def test_the_design_columns_of_the_hub_one_row_per_sample() -> None:
    module = load_recipe(RECIPE)
    out = module.transform({"hub": _hub()})
    validate_schema(out, module.OUTPUT_SCHEMA, "design", None)
    assert out.columns == ["sample_id", "protocol", "source_replicate", "run_id"]
    assert out["sample_id"].to_list() == ["A_R1", "B_R1"]
    assert out["protocol"].to_list() == ["directcdna", "cdna"]


def test_no_design_table_drops_design_and_every_tile_bound_to_it_is_design_only() -> None:
    raw = yaml.safe_load(TEMPLATE.read_text())
    absent = next(r for r in raw["template"]["conditional"] if r.get("if_var_absent"))
    assert "design" in absent["remove_dc_tags"]
    links = {(link["source_dc_tag"], link["target_dc_tag"]) for link in raw["links"]}
    assert {("design", "samples"), ("samples", "design")} <= links

    dashboard = yaml.safe_load(BASE.read_text())
    components = list(dashboard["main_dashboard"]["components"])
    design_bound = {
        c["column_name"] if c["component_type"] == "interactive" else c["breakdown_col"]
        for c in components
        if c.get("data_collection_tag") == "design"
    }
    # Preparation, run and source replicate only: nothing else may leave with it.
    assert design_bound == {"protocol", "run_id", "source_replicate"}
    for c in components:
        if c.get("data_collection_tag") == "samples":
            assert c.get("column_name") not in design_bound
            assert c.get("breakdown_col") not in design_bound
