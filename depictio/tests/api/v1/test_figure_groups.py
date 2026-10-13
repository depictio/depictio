"""Selection-group figure coloring (issue #89).

The viewer sends untrusted group definitions (name + column + captured values +
color) with a figure render request; the server annotates every row with a
synthetic categorical column (first matching group wins, ``Other`` fallback)
and colors the Plotly Express figure by it. These tests pin the three pure
helpers in ``depictio/api/v1/services/figure/groups.py``:

- ``sanitize_group_defs`` — the whole trust boundary for the request payload;
- ``group_annotation_expr`` — the ``when/then`` chain, on eager and lazy
  frames (the lazy case is the box/histogram aggregation fast path);
- ``apply_group_coloring_kwargs`` — the kwargs override handed to px.
"""

import polars as pl

from depictio.api.v1.services.figure.groups import (
    FACET_COL_WRAP,
    GROUP_COLUMN,
    MAX_COLOR_MAP_ENTRIES,
    MAX_GROUPS,
    MAX_VALUES_PER_GROUP,
    OTHER_COLOR,
    OTHER_LABEL,
    apply_column_coloring_kwargs,
    apply_facet_kwargs,
    apply_group_coloring_kwargs,
    group_annotation_expr,
    group_source_columns,
    sanitize_color_by_column,
    sanitize_group_defs,
    sanitize_grouping_display,
)


def _group(name="A", column="sample", values=("s1", "s2"), color="#1f77b4"):
    return {"name": name, "column_name": column, "values": list(values), "color": color}


class TestSanitizeGroupDefs:
    def test_non_list_input_yields_empty(self):
        assert sanitize_group_defs(None) == []
        assert sanitize_group_defs("junk") == []
        assert sanitize_group_defs({"name": "A"}) == []

    def test_non_dict_entries_are_dropped(self):
        assert sanitize_group_defs(["junk", 42, None, _group()]) == [_group()]

    def test_missing_or_empty_fields_are_dropped(self):
        assert sanitize_group_defs([{"name": "", "column_name": "c", "values": ["v"]}]) == []
        assert sanitize_group_defs([{"name": "A", "column_name": "", "values": ["v"]}]) == []
        assert sanitize_group_defs([{"name": "A", "column_name": "c", "values": []}]) == []
        assert sanitize_group_defs([{"name": "A", "column_name": "c"}]) == []

    def test_values_are_coerced_to_str(self):
        out = sanitize_group_defs([_group(values=[1, 2.5, "x"])])
        assert out[0]["values"] == ["1", "2.5", "x"]

    def test_caps_enforced(self):
        many = [_group(name=f"G{i}") for i in range(MAX_GROUPS + 5)]
        assert len(sanitize_group_defs(many)) == MAX_GROUPS

        big = _group(values=[str(i) for i in range(MAX_VALUES_PER_GROUP + 10)])
        out = sanitize_group_defs([big])
        assert len(out[0]["values"]) == MAX_VALUES_PER_GROUP

    def test_invalid_color_replaced_with_palette_entry(self):
        out = sanitize_group_defs(
            [
                _group(name="A", color="red"),
                _group(name="B", color="#12345"),
                _group(name="C", color=42),
            ]
        )
        for g in out:
            assert g["color"].startswith("#") and len(g["color"]) == 7

    def test_valid_color_preserved(self):
        assert sanitize_group_defs([_group(color="#AbCdEf")])[0]["color"] == "#AbCdEf"

    def test_duplicate_names_first_wins(self):
        out = sanitize_group_defs([_group(name="A", values=["1"]), _group(name="A", values=["2"])])
        assert len(out) == 1
        assert out[0]["values"] == ["1"]

    def test_reserved_other_label_rejected(self):
        assert sanitize_group_defs([_group(name=OTHER_LABEL)]) == []

    def test_group_source_columns(self):
        out = sanitize_group_defs([_group(column="a"), _group(name="B", column="b")])
        assert group_source_columns(out) == {"a", "b"}


class TestGroupAnnotationExpr:
    def test_membership_and_other_fallback(self):
        df = pl.DataFrame({"sample": ["s1", "s2", "s3", "s4"]})
        expr = group_annotation_expr(
            [_group(name="A", values=["s1"]), _group(name="B", values=["s3"])],
            df.columns,
            dict(df.schema),
        )
        labels = df.with_columns(expr)[GROUP_COLUMN].to_list()
        assert labels == ["A", OTHER_LABEL, "B", OTHER_LABEL]

    def test_overlap_first_match_wins(self):
        df = pl.DataFrame({"sample": ["s1", "s2"]})
        expr = group_annotation_expr(
            [_group(name="A", values=["s1", "s2"]), _group(name="B", values=["s2"])],
            df.columns,
            dict(df.schema),
        )
        assert df.with_columns(expr)[GROUP_COLUMN].to_list() == ["A", "A"]

    def test_numeric_column_with_stringified_values(self):
        # Selection values always arrive stringified; the predicate reuses
        # _categorical_predicate so an int64 column still matches.
        df = pl.DataFrame({"id": [1, 2, 3]})
        expr = group_annotation_expr(
            [_group(name="A", column="id", values=["1", "3"])], df.columns, dict(df.schema)
        )
        assert df.with_columns(expr)[GROUP_COLUMN].to_list() == ["A", OTHER_LABEL, "A"]

    def test_none_when_no_group_column_present(self):
        df = pl.DataFrame({"other_col": [1]})
        assert group_annotation_expr([_group()], df.columns, dict(df.schema)) is None

    def test_missing_column_group_skipped_while_other_applies(self):
        df = pl.DataFrame({"sample": ["s1", "s2"]})
        expr = group_annotation_expr(
            [_group(name="A", column="absent"), _group(name="B", values=["s2"])],
            df.columns,
            dict(df.schema),
        )
        assert df.with_columns(expr)[GROUP_COLUMN].to_list() == [OTHER_LABEL, "B"]

    def test_lazyframe_annotation_and_group_by(self):
        # The aggregation fast path injects the expression on a LazyFrame and
        # then group-bys the synthetic column — prove that plan collects.
        lf = pl.LazyFrame({"sample": ["s1", "s1", "s2", "s3"], "depth": [1, 2, 3, 4]})
        expr = group_annotation_expr(
            [_group(name="A", values=["s1"])], lf.collect_schema().names(), None
        )
        counts = lf.with_columns(expr).group_by(GROUP_COLUMN).len().collect().sort(GROUP_COLUMN)
        assert dict(zip(counts[GROUP_COLUMN].to_list(), counts["len"].to_list())) == {
            "A": 2,
            OTHER_LABEL: 2,
        }


class TestApplyGroupColoringKwargs:
    def test_overrides_color_and_preserves_other_kwargs(self):
        groups = sanitize_group_defs([_group(name="A"), _group(name="B", color="#ff7f0e")])
        out = apply_group_coloring_kwargs({"x": "depth", "color": "habitat"}, groups)
        assert out["x"] == "depth"
        assert out["color"] == GROUP_COLUMN
        assert out["color_discrete_map"] == {
            "A": "#1f77b4",
            "B": "#ff7f0e",
            OTHER_LABEL: OTHER_COLOR,
        }

    def test_other_is_last_in_category_orders(self):
        groups = sanitize_group_defs([_group(name="A"), _group(name="B")])
        out = apply_group_coloring_kwargs({}, groups)
        assert out["category_orders"][GROUP_COLUMN] == ["A", "B", OTHER_LABEL]

    def test_existing_category_orders_preserved(self):
        groups = sanitize_group_defs([_group(name="A")])
        out = apply_group_coloring_kwargs({"category_orders": {"habitat": ["x", "y"]}}, groups)
        assert out["category_orders"]["habitat"] == ["x", "y"]
        assert out["category_orders"][GROUP_COLUMN] == ["A", OTHER_LABEL]

    def test_input_not_mutated(self):
        original = {"color": "habitat"}
        apply_group_coloring_kwargs(original, sanitize_group_defs([_group()]))
        assert original == {"color": "habitat"}

    def test_include_other_false_drops_the_category_entirely(self):
        # px keeps every category listed in category_orders even when absent
        # from the (filtered) data — a leftover "Other" draws an empty facet
        # panel in Split mode.
        groups = sanitize_group_defs([_group(name="A"), _group(name="B")])
        out = apply_group_coloring_kwargs({}, groups, include_other=False)
        assert OTHER_LABEL not in out["color_discrete_map"]
        assert out["category_orders"][GROUP_COLUMN] == ["A", "B"]


class TestFigureIntegration:
    def _annotated_df(self):
        df = pl.DataFrame(
            {
                "sample": [f"s{i}" for i in range(20)],
                "x": list(range(20)),
                "y": [v * 2.0 for v in range(20)],
            }
        )
        groups = sanitize_group_defs(
            [
                _group(name="A", values=[f"s{i}" for i in range(5)], color="#1f77b4"),
                _group(name="B", values=[f"s{i}" for i in range(5, 10)], color="#ff7f0e"),
            ]
        )
        expr = group_annotation_expr(groups, df.columns, dict(df.schema))
        return df.with_columns(expr), groups

    def test_scatter_one_trace_per_group_with_mapped_colors(self):
        from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

        df, groups = self._annotated_df()
        fig = create_figure_from_data(
            df=df,
            visu_type="scatter",
            dict_kwargs=apply_group_coloring_kwargs({"x": "x", "y": "y"}, groups),
        )
        by_name = {t.name: t for t in fig.data}
        assert set(by_name) == {"A", "B", OTHER_LABEL}
        assert by_name["A"].marker.color == "#1f77b4"
        assert by_name["B"].marker.color == "#ff7f0e"
        assert by_name[OTHER_LABEL].marker.color == OTHER_COLOR
        # Creation order first, Other last (category_orders).
        assert [t.name for t in fig.data] == ["A", "B", OTHER_LABEL]

    def test_box_split_by_group(self):
        from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

        df, groups = self._annotated_df()
        fig = create_figure_from_data(
            df=df,
            visu_type="box",
            dict_kwargs=apply_group_coloring_kwargs({"y": "y"}, groups),
        )
        assert {t.name for t in fig.data} == {"A", "B", OTHER_LABEL}


class TestSanitizeColorByColumn:
    def test_non_dict_input_yields_none(self):
        assert sanitize_color_by_column(None) is None
        assert sanitize_color_by_column("variety") is None
        assert sanitize_color_by_column(["variety"]) is None

    def test_missing_or_empty_column_yields_none(self):
        assert sanitize_color_by_column({}) is None
        assert sanitize_color_by_column({"column_name": ""}) is None
        assert sanitize_color_by_column({"column_name": "   "}) is None
        assert sanitize_color_by_column({"column_name": 42}) is None

    def test_column_only_yields_empty_map(self):
        out = sanitize_color_by_column({"column_name": " variety "})
        assert out == {"column_name": "variety", "color_map": {}}

    def test_invalid_map_entries_are_dropped(self):
        out = sanitize_color_by_column(
            {
                "column_name": "variety",
                "color_map": {
                    "Setosa": "#4C72B0",
                    "Versicolor": "not-a-color",
                    "Virginica": 42,
                    3: "#000000",
                },
            }
        )
        assert out is not None
        assert out["color_map"] == {"Setosa": "#4C72B0"}

    def test_map_cap_enforced(self):
        big_map = {f"v{i}": "#112233" for i in range(MAX_COLOR_MAP_ENTRIES + 20)}
        out = sanitize_color_by_column({"column_name": "c", "color_map": big_map})
        assert out is not None
        assert len(out["color_map"]) == MAX_COLOR_MAP_ENTRIES

    def test_overlong_column_name_yields_none(self):
        assert sanitize_color_by_column({"column_name": "c" * 500}) is None


class TestApplyColumnColoringKwargs:
    def test_overrides_color_and_pins_map_and_order(self):
        cmap = {"Setosa": "#4C72B0", "Versicolor": "#DD8452"}
        out = apply_column_coloring_kwargs({"x": "a", "color": "other"}, "variety", cmap)
        assert out["x"] == "a"
        assert out["color"] == "variety"
        assert out["color_discrete_map"] == cmap
        # Category order pinned to the map's (universe) order.
        assert out["category_orders"]["variety"] == ["Setosa", "Versicolor"]

    def test_empty_map_only_sets_color(self):
        out = apply_column_coloring_kwargs({"x": "a"}, "variety", {})
        assert out["color"] == "variety"
        assert "color_discrete_map" not in out
        assert "category_orders" not in out

    def test_empty_map_drops_authored_map(self):
        # An authored map is keyed to the figure's own color column; keeping it
        # while recoloring by another column would repaint overlapping values.
        out = apply_column_coloring_kwargs(
            {"color": "habitat", "color_discrete_map": {"reef": "#112233"}}, "variety", {}
        )
        assert out["color"] == "variety"
        assert "color_discrete_map" not in out

    def test_existing_category_orders_preserved(self):
        out = apply_column_coloring_kwargs(
            {"category_orders": {"habitat": ["x", "y"]}}, "variety", {"Setosa": "#4C72B0"}
        )
        assert out["category_orders"]["habitat"] == ["x", "y"]
        assert out["category_orders"]["variety"] == ["Setosa"]

    def test_input_not_mutated(self):
        original = {"color": "habitat"}
        apply_column_coloring_kwargs(original, "variety", {"Setosa": "#4C72B0"})
        assert original == {"color": "habitat"}


class TestFacetDisplay:
    def test_sanitize_grouping_display(self):
        assert sanitize_grouping_display("facet") == "facet"
        assert sanitize_grouping_display("color") == "color"
        assert sanitize_grouping_display(None) == "color"
        assert sanitize_grouping_display("junk") == "color"
        assert sanitize_grouping_display(42) == "color"

    def test_apply_facet_kwargs_sets_facet_and_wrap(self):
        out = apply_facet_kwargs({"x": "a", "color": GROUP_COLUMN}, GROUP_COLUMN)
        assert out["facet_col"] == GROUP_COLUMN
        assert out["facet_col_wrap"] == FACET_COL_WRAP
        assert out["x"] == "a"
        assert out["color"] == GROUP_COLUMN

    def test_apply_facet_kwargs_overrides_authored_facet(self):
        out = apply_facet_kwargs({"facet_col": "habitat", "facet_row": "year"}, GROUP_COLUMN)
        assert out["facet_col"] == GROUP_COLUMN
        # facet_row is the author's own split axis; a grid is still readable.
        assert out["facet_row"] == "year"

    def test_apply_facet_kwargs_does_not_mutate(self):
        original = {"x": "a"}
        apply_facet_kwargs(original, GROUP_COLUMN)
        assert original == {"x": "a"}

    def test_scatter_faceted_by_group_builds_subplots(self):
        from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

        df = pl.DataFrame(
            {
                "sample": [f"s{i}" for i in range(10)],
                "x": list(range(10)),
                "y": [v * 2.0 for v in range(10)],
            }
        )
        groups = sanitize_group_defs(
            [
                _group(name="A", values=[f"s{i}" for i in range(5)]),
                _group(name="B", values=[f"s{i}" for i in range(5, 10)]),
            ]
        )
        expr = group_annotation_expr(groups, df.columns, dict(df.schema))
        kwargs = apply_facet_kwargs(
            apply_group_coloring_kwargs({"x": "x", "y": "y"}, groups), GROUP_COLUMN
        )
        fig = create_figure_from_data(
            df=df.with_columns(expr), visu_type="scatter", dict_kwargs=kwargs
        )
        # One subplot per present category: A, B (no Other rows here).
        xaxes = {t.xaxis for t in fig.data}
        assert len(xaxes) == 2


class TestColumnColoringIntegration:
    def test_scatter_colored_by_real_column_with_stable_map(self):
        from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

        df = pl.DataFrame(
            {
                "x": [1.0, 2.0, 3.0, 4.0],
                "y": [2.0, 4.0, 6.0, 8.0],
                "variety": ["Setosa", "Setosa", "Virginica", "Virginica"],
            }
        )
        cmap = {"Setosa": "#4C72B0", "Versicolor": "#DD8452", "Virginica": "#55A467"}
        fig = create_figure_from_data(
            df=df,
            visu_type="scatter",
            dict_kwargs=apply_column_coloring_kwargs({"x": "x", "y": "y"}, "variety", cmap),
        )
        by_name = {t.name: t for t in fig.data}
        # Only the present categories get traces, with the universe's colors.
        assert set(by_name) == {"Setosa", "Virginica"}
        assert by_name["Setosa"].marker.color == "#4C72B0"
        assert by_name["Virginica"].marker.color == "#55A467"


class TestCodeModeGrouping:
    """A code-mode figure honours Colour/Split by spreading the server's kwargs.

    The server never rewrites user code, so a code figure opts in by naming
    ``depictio_group_kwargs`` and spreading it into its own px call. What it
    receives is the output of the same two helpers UI mode applies, which is
    what stops the two paths from disagreeing about what "Split" means.
    """

    GROUPS = [
        {"name": "North", "column_name": "sample", "values": ["s1", "s2"], "color": "#4C72B0"},
        {"name": "South", "column_name": "sample", "values": ["s3", "s4"], "color": "#DD8452"},
    ]
    CODE = (
        "colors = {'Soil': '#E24A33', 'River': '#348ABD'}\n"
        "opts = {'color': 'habitat', 'color_discrete_map': colors, **depictio_group_kwargs}\n"
        "fig = px.scatter(df.to_pandas(), x='x', y='y', **opts)\n"
    )

    def _frame(self):
        return pl.DataFrame(
            {
                "x": [1.0, 2.0, 3.0, 4.0],
                "y": [2.0, 4.0, 6.0, 8.0],
                "habitat": ["Soil", "Soil", "River", "River"],
                "sample": ["s1", "s2", "s3", "s4"],
                GROUP_COLUMN: ["North", "North", "South", "South"],
            }
        )

    # An aggregating figure: `group_by` would drop the annotation, so the same
    # handover also names the grouping keys to spread into it.
    AGG_CODE = (
        "df_modified = df.group_by(list(dict.fromkeys([*depictio_group_by, 'habitat']))).agg("
        "pl.col('y').mean().alias('mean_y'))\n"
        "fig = px.bar(df_modified.to_pandas(), x='habitat', y='mean_y', "
        "**depictio_group_kwargs)\n"
    )

    def _run(self, group_kwargs, code=None, group_by=None):
        from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor
        from depictio.api.v1.services.figure.groups import CODE_GROUP_BY, CODE_GROUP_KWARGS

        ok, fig, message = SimpleCodeExecutor().execute_code(
            code or self.CODE,
            self._frame(),
            {CODE_GROUP_KWARGS: group_kwargs, CODE_GROUP_BY: group_by or []},
        )
        assert ok, message
        return fig

    def test_empty_kwargs_leave_the_authored_coloring_alone(self):
        # Grouping off: the name is still bound, so spreading it is a no-op and
        # the figure keeps the colors its author chose.
        fig = self._run({})
        assert {t.name for t in fig.data} == {"Soil", "River"}

    def test_group_kwargs_override_the_authored_color(self):
        fig = self._run(apply_group_coloring_kwargs({}, self.GROUPS))
        by_name = {t.name: t for t in fig.data}
        assert set(by_name) == {"North", "South"}
        assert by_name["North"].marker.color == "#4C72B0"
        assert len({t.xaxis for t in fig.data}) == 1  # overlaid, one panel

    def test_grouping_keys_survive_an_aggregation(self):
        fig = self._run(
            apply_group_coloring_kwargs({}, self.GROUPS),
            code=self.AGG_CODE,
            group_by=[GROUP_COLUMN],
        )
        assert {t.name for t in fig.data} == {"North", "South"}

    def test_an_aggregating_figure_renders_ungrouped_when_grouping_is_off(self):
        # Same source line, nothing bound: the group_by spreads an empty list
        # and the bar is the one its author wrote.
        fig = self._run({}, code=self.AGG_CODE)
        assert len(fig.data) == 1

    def test_a_handed_over_column_the_figure_already_groups_by(self):
        # "Colour by habitat" on a figure already keyed by habitat: polars
        # refuses a repeated group_by key, so the idiom deduplicates.
        fig = self._run({"color": "habitat"}, code=self.AGG_CODE, group_by=["habitat"])
        assert len(fig.data) == 2

    def test_split_kwargs_facet_the_code_figure(self):
        fig = self._run(
            apply_facet_kwargs(apply_group_coloring_kwargs({}, self.GROUPS), GROUP_COLUMN)
        )
        assert {t.name for t in fig.data} == {"North", "South"}
        # One panel per group: the whole point of Split reaching code mode.
        assert len({t.xaxis for t in fig.data}) == 2


class TestFacetTidy:
    """A split figure has to be readable inside a tile, not a notebook page."""

    def _faceted(self):
        import pandas as pd
        import plotly.express as px

        frame = pd.DataFrame(
            {
                "x": ["A", "B", "C"] * 3,
                "y": range(9),
                GROUP_COLUMN: ["North"] * 3 + ["South"] * 3 + [OTHER_LABEL] * 3,
            }
        )
        return px.bar(frame, x="x", y="y", facet_row=GROUP_COLUMN)

    def test_row_labels_come_off_the_border_and_lose_the_column_prefix(self):
        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = self._faceted()
        assert all(a.textangle == 90 for a in fig.layout.annotations)
        tidy_facet_layout(fig)
        labels = {a.text for a in fig.layout.annotations}
        assert labels == {"North", "South", OTHER_LABEL}
        # Level, and at the left edge rather than rotated against the right one.
        assert all(a.textangle == 0 and a.x == 0 for a in fig.layout.annotations)

    def test_labels_sit_at_the_top_of_the_band_they_name(self):
        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = self._faceted()
        tidy_facet_layout(fig)
        tops = sorted(
            axis["domain"][1]
            for name, axis in fig.layout.to_plotly_json().items()
            if name.startswith("yaxis")
        )
        assert sorted(a.y for a in fig.layout.annotations) == tops

    def test_tick_labels_get_measured_instead_of_clipped(self):
        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = self._faceted()
        tidy_facet_layout(fig)
        assert fig.layout.xaxis.automargin is True

    def test_a_label_the_figure_already_stripped_is_still_laid_flat(self):
        """The two defects are independent: several shipped code figures strip
        the ``col=`` prefix themselves, and used to keep their rotated labels
        because the prefix was the gate for both fixes."""
        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = self._faceted()
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        assert all("=" not in a.text for a in fig.layout.annotations)
        tidy_facet_layout(fig)
        assert {a.text for a in fig.layout.annotations} == {"North", "South", OTHER_LABEL}
        assert all(a.textangle == 0 and a.x == 0 for a in fig.layout.annotations)

    def test_a_figure_that_facets_itself_is_tidied_with_grouping_off(self):
        """Faceting is a property of the figure, not of the request: several
        shipped code figures lay their own facets out and must still be tidied
        when nobody asked for a split."""
        import pandas as pd
        import plotly.express as px

        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        frame = pd.DataFrame(
            {
                "value": range(6),
                "Phylum": ["candidate_division_WPS-1", "Proteobacteria"] * 3,
                "habitat": ["Soil"] * 2 + ["River"] * 2 + ["Sediment"] * 2,
            }
        )
        fig = px.bar(frame, x="value", y="Phylum", orientation="h", facet_col="habitat")
        tidy_facet_layout(fig)
        assert fig.layout.yaxis.automargin is True

    def test_a_single_panel_figure_keeps_the_margins_it_was_given(self):
        """`automargin` rewrites the whole figure's margins, so it must not fire
        on a chart that has one panel and never mentioned facets."""
        import pandas as pd
        import plotly.express as px

        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = px.bar(pd.DataFrame({"x": ["A", "B"], "y": [1, 2]}), x="x", y="y")
        tidy_facet_layout(fig)
        assert fig.layout.yaxis.automargin is None
        assert fig.layout.xaxis.automargin is None

    def test_a_figure_with_no_facets_keeps_its_annotations(self):
        import pandas as pd
        import plotly.express as px

        from depictio.api.v1.services.figure.groups import tidy_facet_layout

        fig = px.bar(pd.DataFrame({"x": ["A"], "y": [1]}), x="x", y="y")
        fig.add_annotation(text="author's own note", x=0.5, y=0.5)
        tidy_facet_layout(fig)
        assert [a.text for a in fig.layout.annotations] == ["author's own note"]
