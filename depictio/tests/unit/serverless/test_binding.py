"""Tests for the bind-and-refill BUILD side (``depictio/serverless/binding.py``).

The contract these pin is consumed by ``packages/depictio-static-core/src/
refill.ts``: a ``BindingTable`` whose ``scaffold`` is the real
``create_figure_from_data`` figure with every row-bound array *deleted*, plus,
per trace, the group-equality predicates and field→column bindings the runtime
re-projects at each filter state. Ambiguity must always degrade to ``None`` (the
caller freezes) — a frozen figure is correct, a mis-bound one is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from depictio.models.models.serverless import BindingTable
from depictio.serverless.binding import build_binding

REPO_ROOT = Path(__file__).resolve().parents[4]
PENGUINS_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "penguins" / "data"


@pytest.fixture(scope="module")
def penguins() -> pl.DataFrame:
    """The worked example's table: the repo's penguins CSV runs joined."""
    parts = []
    for run in sorted(p for p in PENGUINS_DATA.iterdir() if p.is_dir()):
        demographic = pl.read_csv(run / "demographic_data.csv")
        physical = pl.read_csv(run / "physical_features.csv")
        parts.append(demographic.join(physical, on="individual_id", how="inner"))
    return pl.concat(parts)


def _figure(visu_type: str = "scatter", **kwargs: Any) -> dict[str, Any]:
    return {"component_type": "figure", "visu_type": visu_type, "dict_kwargs": kwargs}


def _arrays_in(node: Any) -> list[Any]:
    """Every list/ndarray-ish value reachable in a scaffold trace."""
    found: list[Any] = []
    if isinstance(node, dict):
        if "bdata" in node:  # plotly ≥6 typed-array encoding
            return [node]
        for value in node.values():
            found.extend(_arrays_in(value))
    elif isinstance(node, (list, tuple)) or hasattr(node, "tolist"):
        found.append(node)
    return found


# ---------------------------------------------------------------------------
# The worked example: penguins scatter, coloured by species
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def penguins_binding(penguins: pl.DataFrame) -> BindingTable:
    table = build_binding(
        _figure(x="flipper_length_mm", y="body_mass_g", color="species"), penguins
    )
    assert table is not None
    return table


def test_penguins_scatter_binds(penguins_binding: BindingTable) -> None:
    table = penguins_binding
    assert table.group_cols == ["species"]
    assert table.sampled is False
    assert table.trendlines == []
    assert [t.i for t in table.traces] == [0, 1, 2]
    assert [t.group for t in table.traces] == [
        {"species": "Adelie"},
        {"species": "Chinstrap"},
        {"species": "Gentoo"},
    ]
    for trace in table.traces:
        assert trace.fields == {"x": "flipper_length_mm", "y": "body_mass_g"}
        assert trace.axes == {"xaxis": "x", "yaxis": "y"}
    # Validates as the committed contract (and round-trips through JSON).
    assert BindingTable.model_validate(table.model_dump(mode="json"))


def test_penguins_scaffold_is_stripped_and_layout_intact(penguins_binding: BindingTable) -> None:
    scaffold = penguins_binding.scaffold
    traces = scaffold["data"]
    assert len(traces) == 3
    for trace in traces:
        # Stripping convention: bound fields are ABSENT (refill.ts writes them
        # back with setPath), not emptied — and nothing row-bound survives.
        assert "x" not in trace
        assert "y" not in trace
        assert _arrays_in(trace) == []
        # Everything else px computed is preserved verbatim.
        assert trace["type"] == "scattergl"
        assert trace["marker"]["color"].startswith("#")
        assert "hovertemplate" in trace and "legendgroup" in trace
    # Layout is copied through 100% — the runtime never re-derives structure.
    layout = scaffold["layout"]
    assert layout["legend"]["title"]["text"] == "species"
    assert layout["xaxis"]["title"]["text"] == "flipper_length_mm"
    assert layout["yaxis"]["title"]["text"] == "body_mass_g"
    assert layout["template"]["layout"]  # the mantine template survives
    assert layout["uirevision"] == "persistent"


def test_group_predicates_select_the_real_rows(
    penguins: pl.DataFrame, penguins_binding: BindingTable
) -> None:
    """What the runtime does (mask AND group predicates) must reproduce the
    server's per-trace subframes."""
    total = 0
    for trace in penguins_binding.traces:
        species = trace.group["species"]
        rows = penguins.filter(pl.col("species") == species)
        assert rows.height > 0
        total += rows.height
    assert total == penguins.height == 342


# ---------------------------------------------------------------------------
# px shapes
# ---------------------------------------------------------------------------


def test_color_and_symbol_grouping(penguins: pl.DataFrame) -> None:
    # `sex` carries 9 nulls, which can never match a runtime predicate — the
    # null-free frame is the bindable one (see the null test below).
    table = build_binding(
        _figure(x="flipper_length_mm", y="body_mass_g", color="species", symbol="sex"),
        penguins.drop_nulls("sex"),
    )
    assert table is not None
    assert table.group_cols == ["species", "sex"]  # contract order: color, symbol
    assert len(table.traces) == 6
    assert {(t.group["species"], t.group["sex"]) for t in table.traces} == {
        (species, sex)
        for species in ("Adelie", "Chinstrap", "Gentoo")
        for sex in ("male", "female")
    }


def test_single_trace_without_grouping(penguins: pl.DataFrame) -> None:
    table = build_binding(_figure(x="flipper_length_mm", y="body_mass_g"), penguins)
    assert table is not None
    assert table.group_cols == []
    assert len(table.traces) == 1
    assert table.traces[0].group == {}  # no predicate: the whole mask
    assert table.traces[0].fields == {"x": "flipper_length_mm", "y": "body_mass_g"}


def test_facets_bind_per_cell(penguins: pl.DataFrame) -> None:
    table = build_binding(
        _figure(x="flipper_length_mm", y="body_mass_g", facet_col="island", color="species"),
        penguins,
    )
    assert table is not None
    assert table.group_cols == ["species", "island"]
    # 5 of the 9 species×island combinations exist in the data.
    assert len(table.traces) == 5
    # Facet cells are recorded by subplot axis (px emits name='' for facet-only
    # figures, so axes — not names — are what disambiguates them).
    assert {t.axes["xaxis"] for t in table.traces} == {"x", "x2", "x3"}


def test_continuous_color_and_size_bind_as_fields(penguins: pl.DataFrame) -> None:
    table = build_binding(
        _figure(
            x="flipper_length_mm",
            y="body_mass_g",
            color="bill_depth_mm",
            size="bill_length_mm",
        ),
        penguins,
    )
    assert table is not None
    assert table.group_cols == []  # numeric colour is continuous, never a group
    assert table.traces[0].fields == {
        "x": "flipper_length_mm",
        "y": "body_mass_g",
        "marker.color": "bill_depth_mm",
        "marker.size": "bill_length_mm",
    }


def test_ols_trendline_pairs_with_its_raw_trace(penguins: pl.DataFrame) -> None:
    table = build_binding(
        _figure(x="flipper_length_mm", y="body_mass_g", color="species", trendline="ols"),
        penguins,
    )
    assert table is not None
    assert [(t.i, t.on) for t in table.trendlines] == [(1, 0), (3, 2), (5, 4)]
    # Every trendline's source trace carries x and y (refill.ts refits on them).
    by_index = {t.i: t for t in table.traces}
    for trendline in table.trendlines:
        assert {"x", "y"} <= set(by_index[trendline.on].fields)
    # Fitted arrays are stripped too — the runtime recomputes the segment.
    for trendline in table.trendlines:
        assert _arrays_in(table.scaffold["data"][trendline.i]) == []


# ---------------------------------------------------------------------------
# Refusals — every ambiguity must freeze
# ---------------------------------------------------------------------------


def test_ambiguous_groups_return_none() -> None:
    """Two groups with identical data: no trace can be attributed to one of
    them rather than the other."""
    frame = pl.DataFrame(
        {"grp": ["a", "a", "b", "b"], "x": [1.0, 2.0, 1.0, 2.0], "y": [3.0, 4.0, 3.0, 4.0]}
    )
    assert build_binding(_figure(x="x", y="y", color="grp"), frame) is None


def test_null_grouping_value_returns_none(penguins: pl.DataFrame) -> None:
    # A null cell never matches a group predicate at runtime, so its rows would
    # silently vanish — freeze instead.
    assert (
        build_binding(_figure(x="flipper_length_mm", y="body_mass_g", color="sex"), penguins)
        is None
    )


def test_two_dimensional_customdata_returns_none(penguins: pl.DataFrame) -> None:
    # hover_data/custom_data produce an (n, k) customdata array; the runtime
    # only writes 1-D arrays, so a bound figure would break its hovertemplate.
    assert (
        build_binding(
            _figure(x="flipper_length_mm", y="body_mass_g", hover_data=["island"]), penguins
        )
        is None
    )


def test_whole_frame_and_unsupported_trendline_return_none(penguins: pl.DataFrame) -> None:
    assert build_binding(_figure("scatter_matrix", dimensions=["body_mass_g"]), penguins) is None
    assert (
        build_binding(_figure(x="flipper_length_mm", y="body_mass_g", trendline="lowess"), penguins)
        is None
    )


def test_empty_frame_returns_none() -> None:
    empty = pl.DataFrame({"x": [], "y": []}, schema={"x": pl.Float64, "y": pl.Float64})
    assert build_binding(_figure(x="x", y="y"), empty) is None


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def test_sampled_build_rebuilds_uncapped_and_flags_partial() -> None:
    """Above FIGURE_MAX_POINTS the scaffold is rebuilt with sampling disabled
    (the runtime refills from the full column, so the trace set must cover every
    group of the *full* frame) and the table is flagged ``sampled``."""
    height = 60_000
    frame = pl.DataFrame(
        {
            "x": [float(i) for i in range(height)],
            "y": [float(i) * 2 for i in range(height)],
            "grp": ["a", "b"] * (height // 2),
        }
    )
    table = build_binding(_figure(x="x", y="y", color="grp"), frame)
    assert table is not None
    assert table.sampled is True
    assert len(table.traces) == 2
    assert _arrays_in(table.scaffold["data"][0]) == []
