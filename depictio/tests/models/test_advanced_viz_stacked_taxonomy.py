"""stacked_taxonomy options for a composition that is not a taxonomy."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import ScatterXyConfig, StackedTaxonomyConfig


def test_defaults_keep_the_taxonomy_tile() -> None:
    cfg = StackedTaxonomyConfig()
    assert cfg.hidden_controls is None
    assert cfg.rank_label is None
    assert cfg.x_title is None
    # The legend has sat in a column right of the bars since it collided with
    # the tilted sample labels underneath them.
    assert cfg.legend_pos == "right"


def test_non_taxonomy_options_validate() -> None:
    cfg = StackedTaxonomyConfig(
        hidden_controls=["rank", "top_n", "sample_sort"],
        rank_label="Level",
        x_title="",
        legend_pos="bottom",
        taxon_palette={"FSM": "#228be6"},
    )
    assert cfg.hidden_controls == ["rank", "top_n", "sample_sort"]
    assert cfg.x_title == ""
    assert cfg.legend_pos == "bottom"


@pytest.mark.parametrize(
    "bad",
    [
        {"hidden_controls": ["legend"]},
        {"legend_pos": "top"},
        {"hide_rank": True},
        # The component's own colours are `taxon_palette`; the dashboard's
        # `category_colors` cover the rest.
        {"category_palette": {"FSM": "#228be6"}},
    ],
)
def test_unknown_values_are_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        StackedTaxonomyConfig(**bad)


def test_scatter_colours_come_from_the_dashboard() -> None:
    """A scatter's categories take `category_colors`, never a per-tile map."""
    with pytest.raises(ValidationError):
        ScatterXyConfig(color_col="engine", category_palette={"esmfold": "#228be6"})


# --- General composition bar: sorting, grouping, zoom, orientation ---------


def test_new_options_default_to_the_shipped_tile() -> None:
    cfg = StackedTaxonomyConfig()
    assert cfg.sample_sort == "input"
    assert cfg.sort_category is None
    assert cfg.group_col is None
    assert cfg.y_zoom == "off"
    assert cfg.orientation == "v"
    assert cfg.value_title is None
    # The rank column keeps its default; a single-level composition sets null.
    assert cfg.rank_col == "rank"
    assert StackedTaxonomyConfig(rank_col=None).rank_col is None


@pytest.mark.parametrize("sort", ["input", "name", "total_abundance", "first_taxon", "category"])
def test_every_sample_sort_validates(sort: str) -> None:
    assert StackedTaxonomyConfig(sample_sort=sort).sample_sort == sort


def test_general_composition_options_validate() -> None:
    cfg = StackedTaxonomyConfig(
        rank_col=None,
        sample_sort="category",
        sort_category="Complete (single copy)",
        group_col="lineage",
        y_zoom="auto",
        orientation="h",
        value_title="Share of BUSCOs",
        hidden_controls=["rank", "group", "zoom"],
    )
    assert cfg.y_zoom == "auto"
    assert cfg.orientation == "h"
    assert cfg.hidden_controls == ["rank", "group", "zoom"]


@pytest.mark.parametrize(
    "bad",
    [
        {"sample_sort": "alphabetical"},
        {"y_zoom": True},
        {"y_zoom": "on"},
        {"orientation": "horizontal"},
        {"hidden_controls": ["sort_category"]},
    ],
)
def test_unknown_composition_values_are_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        StackedTaxonomyConfig(**bad)


def test_rank_is_an_optional_role() -> None:
    """A table with sample / category / value and no level column still binds."""
    from depictio.models.components.advanced_viz.schemas import (
        _OPTIONAL_ROLES,
        CANONICAL_SCHEMAS,
    )

    assert set(CANONICAL_SCHEMAS["stacked_taxonomy"]) == {"sample_id", "taxon", "abundance"}
    assert set(_OPTIONAL_ROLES["stacked_taxonomy"]) == {"rank"}


def _stacked_taxonomy_nodes(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        if node.get("viz_kind") == "stacked_taxonomy":
            yield node
        for value in node.values():
            yield from _stacked_taxonomy_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _stacked_taxonomy_nodes(value)


def test_shipped_stacked_taxonomy_configs_still_validate() -> None:
    """Every stacked_taxonomy config in a shipped dashboard YAML still validates."""
    repo = Path(__file__).resolve().parents[3]
    seen = 0
    for path in sorted(repo.glob("depictio/projects/**/dashboards/*.yaml")):
        text = path.read_text()
        if "stacked_taxonomy" not in text:
            continue
        for node in _stacked_taxonomy_nodes(yaml.safe_load(text)):
            cfg = node.get("config") if isinstance(node.get("config"), dict) else node
            # Only the config keys: a component node also carries layout keys.
            keys = set(StackedTaxonomyConfig.model_fields)
            StackedTaxonomyConfig(**{k: v for k, v in cfg.items() if k in keys})
            seen += 1
    assert seen > 0


def test_figure_builder_sorts_by_name_and_by_category_share() -> None:
    from depictio.api.v1.services.advanced_viz.figure_registry import build

    rows = {
        "sample_id": ["S10", "S10", "S2", "S2", "s1", "s1"],
        "taxon": ["A", "B", "A", "B", "A", "B"],
        "abundance": [10, 30, 50, 10, 5, 5],
    }
    base = {
        "sample_id_col": "sample_id",
        "taxon_col": "taxon",
        "rank_col": None,
        "abundance_col": "abundance",
    }
    by_name = build(
        "stacked_taxonomy", config={**base, "sample_sort": "name"}, rows=rows, theme="light"
    )
    assert by_name["data"][0]["x"] == ["s1", "S2", "S10"]
    by_share = build(
        "stacked_taxonomy",
        config={**base, "sample_sort": "category", "sort_category": "B"},
        rows=rows,
        theme="light",
    )
    # Share of B: S10 0.75, s1 0.5, S2 0.17.
    assert by_share["data"][0]["x"] == ["S10", "s1", "S2"]


# --- Wide tables: one numeric column per category ---------------------------

_WIDE = {
    "sample_id_col": "species",
    "value_cols": ["genes_in_orthogroups", "unassigned_genes"],
    "value_labels": {"unassigned_genes": "Unassigned"},
}


def test_wide_form_validates_and_long_form_stays_the_default() -> None:
    assert StackedTaxonomyConfig().value_cols is None
    assert StackedTaxonomyConfig().value_labels is None
    cfg = StackedTaxonomyConfig(**_WIDE)
    assert cfg.value_cols == ["genes_in_orthogroups", "unassigned_genes"]
    with pytest.raises(ValidationError):
        StackedTaxonomyConfig(value_cols=[])


def test_wide_form_binds_the_sample_id_and_numeric_value_columns() -> None:
    from depictio.models.components.advanced_viz.schemas import validate_binding

    schema = {"species": "String", "genes_in_orthogroups": "Int64", "unassigned_genes": "Int64"}
    # No taxon / abundance / rank column needed.
    assert validate_binding(StackedTaxonomyConfig(**_WIDE), schema) == []
    missing = validate_binding(StackedTaxonomyConfig(**_WIDE), {"species": "String"})
    assert {e.column for e in missing} == {"genes_in_orthogroups", "unassigned_genes"}
    text = validate_binding(
        StackedTaxonomyConfig(**_WIDE), {**schema, "unassigned_genes": "String"}
    )
    assert [e.column for e in text] == ["unassigned_genes"]
    # The long form still needs its bindings.
    assert validate_binding(StackedTaxonomyConfig(sample_id_col="species"), schema)


def test_figure_builder_melts_a_wide_table() -> None:
    from depictio.api.v1.services.advanced_viz.figure_registry import build, required_columns

    assert required_columns("stacked_taxonomy", _WIDE) == [
        "species",
        "genes_in_orthogroups",
        "unassigned_genes",
    ]
    rows = {
        "species": ["human", "mouse"],
        "genes_in_orthogroups": [18000, 17000],
        "unassigned_genes": [2000, 3000],
    }
    spec = build("stacked_taxonomy", config=_WIDE, rows=rows, theme="light")
    by_name = {trace["name"]: trace["y"] for trace in spec["data"]}
    assert by_name == {"genes_in_orthogroups": [0.9, 0.85], "Unassigned": [0.1, 0.15]}
