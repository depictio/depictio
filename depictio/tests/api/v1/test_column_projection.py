"""Tests for column projection (#7) and the Delta schema cache (#12).

Covers the safety-critical pure logic introduced for scan-level column
projection: extracting the columns a figure references, folding filter columns
into the effective projection (so filtering never silently drops a column), and
the schema-guarded scan projection backed by a per-(collection, version) cache.
"""

from unittest.mock import MagicMock

import polars as pl

from depictio.api.v1 import deltatables_utils as dtu
from depictio.api.v1.deltatables_utils import (
    _effective_projection,
    _filter_columns,
    _get_cached_schema,
    _project_scan,
)
from depictio.api.v1.services.figure.figure_builder import referenced_columns


class TestReferencedColumns:
    """`referenced_columns` extracts exactly the columns a UI figure reads."""

    def test_scalar_params(self):
        assert referenced_columns("scatter", {"x": "a", "y": "b", "color": "c"}) == {"a", "b", "c"}

    def test_size_and_facets(self):
        cols = referenced_columns("scatter", {"x": "a", "y": "b", "size": "s", "facet_col": "f"})
        assert cols == {"a", "b", "s", "f"}

    def test_hover_data_json_list(self):
        cols = referenced_columns("bar", {"x": "a", "y": "b", "hover_data": '["h1", "h2"]'})
        assert cols == {"a", "b", "h1", "h2"}

    def test_custom_data_native_list(self):
        cols = referenced_columns("scatter", {"x": "a", "y": "b", "custom_data": ["id"]})
        assert cols == {"a", "b", "id"}

    def test_hover_data_dict_keys_are_columns(self):
        cols = referenced_columns("scatter", {"x": "a", "hover_data": {"h": True}})
        assert cols == {"a", "h"}

    def test_ignores_styling_and_empty_values(self):
        cols = referenced_columns(
            "scatter",
            {
                "x": "a",
                "y": "b",
                "color": "",  # empty → not a column
                "size": None,  # null → skipped
                "template": "mantine_light",  # styling literal
                "opacity": 0.5,  # styling literal
            },
        )
        assert cols == {"a", "b"}

    def test_heatmap_returns_none(self):
        # Heatmap consumes the whole frame (+ _col_annotations_json) → full load.
        assert referenced_columns("heatmap", {"x": "a"}) is None

    def test_whole_frame_visu_types_return_none(self):
        for visu in ("scatter_matrix", "parallel_coordinates", "parallel_categories", "imshow"):
            assert referenced_columns(visu, {"x": "a"}) is None

    def test_unparseable_list_param_returns_none(self):
        # An opaque string we can't decompose into column names → bail to a full
        # load rather than risk projecting away a referenced column.
        assert referenced_columns("scatter", {"x": "a", "hover_data": "not json"}) is None

    def test_empty_or_styling_only_spec_returns_none(self):
        assert referenced_columns("scatter", {}) is None
        assert referenced_columns("scatter", {"template": "mantine_dark"}) is None

    def test_non_dict_spec_returns_none(self):
        assert referenced_columns("scatter", None) is None  # type: ignore[arg-type]


class TestFilterColumns:
    """`_filter_columns` pulls column names from a filter metadata list."""

    def test_top_level_column(self):
        assert _filter_columns([{"column_name": "f1", "value": 1}]) == {"f1"}

    def test_nested_metadata_column(self):
        assert _filter_columns([{"metadata": {"column_name": "f2"}, "value": 1}]) == {"f2"}

    def test_mixed_and_missing_and_non_dict(self):
        md = [
            {"column_name": "f1"},
            {"metadata": {"column_name": "f2"}},
            {"value": 1},  # no column
            "garbage",  # non-dict entry tolerated
        ]
        assert _filter_columns(md) == {"f1", "f2"}

    def test_none_metadata(self):
        assert _filter_columns(None) == set()


class TestEffectiveProjection:
    """`_effective_projection` folds filter columns into the requested set."""

    def test_none_when_no_projection_requested(self):
        assert _effective_projection(None, [{"column_name": "f"}], False) is None
        assert _effective_projection([], None, False) is None

    def test_unions_filter_columns_sorted(self):
        assert _effective_projection(["y", "x"], [{"column_name": "f"}], False) == ["f", "x", "y"]

    def test_skips_filters_when_loading_for_options(self):
        # load_for_options bypasses filtering, so filter columns aren't needed.
        assert _effective_projection(["x", "y"], [{"column_name": "f"}], True) == ["x", "y"]

    def test_no_metadata_just_sorts(self):
        assert _effective_projection(["b", "a"], None, False) == ["a", "b"]

    def test_deduplicates_overlapping_filter_and_figure_columns(self):
        assert _effective_projection(["x", "y"], [{"column_name": "x"}], False) == ["x", "y"]


class TestCrossDcLinkProjection:
    """Projection must not break cross-DC linked filters.

    A cross-DC link turns a filter on a *source* DC into a synthetic filter on
    the *target* DC's join column (see ``_resolve_link_filters`` ->
    ``extend_filters_via_links``). That join column is typically NOT one of the
    figure's plotted columns, and may not even exist in the target DC's schema.
    Projection must therefore (a) fold the link filter's column into the scan so
    the filter actually applies, and (b) schema-guard it so a column absent from
    the target never reaches ``.select`` and raises ColumnNotFoundError.

    Neither perf PR touches the link-resolution code itself; this guards the one
    way projection could regress cross-DC filtering.
    """

    def setup_method(self):
        dtu._DELTA_SCHEMA_CACHE.clear()

    def test_link_filter_column_folded_into_projection(self):
        # Figure plots {x, y}; the link injects a filter on the join column
        # "individual_id" (a non-plotted column). It must survive projection,
        # else the cross-DC filter would silently no-op.
        figure_cols = ["x", "y"]
        link_filter_metadata = [{"column_name": "individual_id"}]
        proj = _effective_projection(figure_cols, link_filter_metadata, False)
        assert "individual_id" in proj
        assert proj == ["individual_id", "x", "y"]

    def test_link_filter_column_absent_from_target_is_dropped_not_crashed(self):
        # If the link's join column doesn't exist on the target DC's real schema,
        # _project_scan drops it instead of passing it to .select (which would
        # raise ColumnNotFoundError at collect). The load still succeeds.
        target_scan = pl.LazyFrame({"x": [1, 2], "y": [3, 4]})  # no individual_id
        out = _project_scan(target_scan, ["individual_id", "x", "y"], "dc_target", "v1")
        assert out.collect_schema().names() == ["x", "y"]
        assert out.collect().height == 2


class TestProjectScanAndSchemaCache:
    """`_project_scan` is schema-guarded; `_get_cached_schema` memoizes columns."""

    def setup_method(self):
        dtu._DELTA_SCHEMA_CACHE.clear()

    @staticmethod
    def _lf() -> pl.LazyFrame:
        return pl.LazyFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})

    def test_no_projection_returns_scan_unchanged(self):
        out = _project_scan(self._lf(), None, "dc1", "v1")
        assert out.collect_schema().names() == ["a", "b", "c"]

    def test_projects_to_requested_columns(self):
        out = _project_scan(self._lf(), ["a", "b"], "dc1", "v1")
        assert out.collect_schema().names() == ["a", "b"]

    def test_drops_columns_absent_from_schema_without_crashing(self):
        # A requested column not present on the DC (e.g. a cross-DC filter
        # column) must be dropped, not passed to .select (which would raise at
        # collect). The load must still succeed.
        out = _project_scan(self._lf(), ["a", "zzz"], "dc1", "v1")
        assert out.collect_schema().names() == ["a"]
        assert out.collect().height == 2

    def test_schema_cache_populated_and_reused(self):
        assert ("dc1", "v1") not in dtu._DELTA_SCHEMA_CACHE
        names = _get_cached_schema(self._lf(), "dc1", "v1")
        assert names == frozenset({"a", "b", "c"})
        assert dtu._DELTA_SCHEMA_CACHE[("dc1", "v1")] == frozenset({"a", "b", "c"})

    def test_schema_cache_keyed_on_version(self):
        _get_cached_schema(self._lf(), "dc1", "v1")
        lf2 = pl.LazyFrame({"a": [1], "b": [2], "c": [3], "d": [4]})
        names_v2 = _get_cached_schema(lf2, "dc1", "v2")
        assert "d" in names_v2
        # The v1 entry is untouched under its own key.
        assert dtu._DELTA_SCHEMA_CACHE[("dc1", "v1")] == frozenset({"a", "b", "c"})

    def test_schema_read_failure_returns_none_and_is_not_cached(self):
        bad = MagicMock()
        bad.collect_schema.side_effect = RuntimeError("boom")
        assert _get_cached_schema(bad, "dcX", "v1") is None
        assert ("dcX", "v1") not in dtu._DELTA_SCHEMA_CACHE

    def test_unreadable_schema_skips_projection_instead_of_selecting(self):
        # When the schema can't be read, _project_scan must NOT pass the
        # (unverified) requested columns to .select — an absent column (e.g. a
        # cross-DC filter column) would raise ColumnNotFoundError at collect,
        # turning a transient schema-read failure into a hard render failure.
        # Safe fallback: load the full frame, leaving the scan untouched.
        bad = MagicMock()
        bad.collect_schema.side_effect = RuntimeError("boom")
        out = _project_scan(bad, ["individual_id", "x"], "dcX", "v1")
        assert out is bad
        bad.select.assert_not_called()

    def test_schema_cache_is_bounded(self, monkeypatch):
        monkeypatch.setattr(dtu, "_DELTA_SCHEMA_CACHE_MAX", 2)
        for i in range(3):
            _get_cached_schema(self._lf(), f"dc{i}", "v")
        assert len(dtu._DELTA_SCHEMA_CACHE) <= 2
