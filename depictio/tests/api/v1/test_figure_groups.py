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
    GROUP_COLUMN,
    MAX_GROUPS,
    MAX_VALUES_PER_GROUP,
    OTHER_COLOR,
    OTHER_LABEL,
    apply_group_coloring_kwargs,
    group_annotation_expr,
    group_source_columns,
    sanitize_group_defs,
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
