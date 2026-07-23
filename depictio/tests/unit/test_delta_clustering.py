"""Delta tables are clustered on their join keys before being written.

Parquet row-group min/max statistics can only skip rows when related values sit
together. An unsorted table spans nearly the full value range in every row
group, so a filtered read decodes everything. Sorting on the join columns — the
values cross-DC link filters resolve to — is what makes those statistics
selective, and it is the multiplier on the typed filter predicate (see
``test_categorical_filter_pushdown``).

These tests pin the column *selection*; they don't re-measure the speedup.
"""

from types import SimpleNamespace

import polars as pl

from depictio.cli.cli.utils.deltatables import clustering_columns, link_columns_by_dc


def _link(source_dc, target_dc, column, enabled=True):
    return SimpleNamespace(
        source_dc_id=source_dc, target_dc_id=target_dc, source_column=column, enabled=enabled
    )


class TestLinkColumnsByDC:
    """Cross-DC links live on the project, not on the DC — both ends need the key."""

    def test_both_ends_of_a_link_are_covered(self):
        project = SimpleNamespace(links=[_link("dcA", "dcB", "sample_id")])
        assert link_columns_by_dc(project) == {"dcA": ["sample_id"], "dcB": ["sample_id"]}

    def test_a_dc_in_several_links_collects_each_key_once(self):
        project = SimpleNamespace(
            links=[
                _link("dcA", "dcB", "sample_id"),
                _link("dcA", "dcC", "sample_id"),
                _link("dcA", "dcD", "run_id"),
            ]
        )
        assert link_columns_by_dc(project)["dcA"] == ["sample_id", "run_id"]

    def test_disabled_links_are_ignored(self):
        project = SimpleNamespace(links=[_link("dcA", "dcB", "sample_id", enabled=False)])
        assert link_columns_by_dc(project) == {}

    def test_project_without_links_is_empty(self):
        assert link_columns_by_dc(SimpleNamespace(links=[])) == {}
        assert link_columns_by_dc(SimpleNamespace()) == {}


class TestLinkColumnsReachClustering:
    """The `links` topology declares no `join` at all — the regression that hid the sort."""

    def test_link_column_clusters_a_dc_with_no_join_config(self):
        assert clustering_columns({}, ["sample_id", "v"], ["sample_id"]) == ["sample_id"]

    def test_join_and_link_columns_combine_without_duplicates(self):
        cfg = {"join": {"on_columns": ["sample_id"], "with_dc": ["x"]}}
        assert clustering_columns(cfg, ["sample_id", "run_id"], ["sample_id", "run_id"]) == [
            "sample_id",
            "run_id",
        ]

    def test_link_column_absent_from_the_frame_is_dropped(self):
        assert clustering_columns({}, ["v"], ["sample_id"]) == []


class TestColumnSelection:
    def test_uses_the_declared_join_columns(self):
        cfg = {"join": {"on_columns": ["sample_id"], "how": "inner", "with_dc": ["other"]}}
        assert clustering_columns(cfg, ["sample_id", "value"]) == ["sample_id"]

    def test_preserves_the_declared_column_order(self):
        """Sort order is hierarchical, so the declared order is meaningful."""
        cfg = {"join": {"on_columns": ["run_id", "sample_id"], "with_dc": ["x"]}}
        assert clustering_columns(cfg, ["sample_id", "run_id", "v"]) == ["run_id", "sample_id"]

    def test_drops_join_columns_absent_from_the_frame(self):
        """A declared join column the DC doesn't actually emit must not be sorted on."""
        cfg = {"join": {"on_columns": ["sample_id", "missing"], "with_dc": ["x"]}}
        assert clustering_columns(cfg, ["sample_id", "value"]) == ["sample_id"]

    def test_no_join_declared_means_no_clustering(self):
        assert clustering_columns({}, ["a", "b"]) == []
        assert clustering_columns({"join": None}, ["a", "b"]) == []

    def test_empty_on_columns_means_no_clustering(self):
        assert clustering_columns({"join": {"on_columns": [], "with_dc": []}}, ["a"]) == []

    def test_none_config_is_tolerated(self):
        """Called on every DC, including ones whose config never loaded."""
        assert clustering_columns(None, ["a"]) == []  # type: ignore[arg-type]

    def test_no_overlap_means_no_clustering(self):
        cfg = {"join": {"on_columns": ["nope"], "with_dc": ["x"]}}
        assert clustering_columns(cfg, ["a", "b"]) == []


class TestSortMakesStatisticsSelective:
    """The property the sort exists for, on a real parquet file."""

    def test_sorted_frame_narrows_row_group_ranges(self, tmp_path):
        import numpy as np

        rng = np.random.default_rng(0)
        df = pl.DataFrame({"sample_id": rng.integers(0, 1000, 200_000), "v": rng.random(200_000)})

        unsorted_path = tmp_path / "unsorted.parquet"
        sorted_path = tmp_path / "sorted.parquet"
        df.write_parquet(unsorted_path, row_group_size=10_000)
        df.sort("sample_id").write_parquet(sorted_path, row_group_size=10_000)

        def mean_row_group_span(path):
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(path)
            col = pf.schema_arrow.names.index("sample_id")
            md = pf.metadata
            spans = []
            for i in range(md.num_row_groups):
                stats = md.row_group(i).column(col).statistics
                spans.append(stats.max - stats.min)
            return sum(spans) / len(spans)

        # Unsorted: every row group covers nearly the whole 0..999 range, so no
        # predicate can exclude one. Sorted: each covers a narrow slice.
        assert mean_row_group_span(sorted_path) < mean_row_group_span(unsorted_path) / 10

    def test_sorting_does_not_change_the_rows(self, tmp_path):
        df = pl.DataFrame({"sample_id": [3, 1, 2], "v": ["c", "a", "b"]})
        assert sorted(df.sort("sample_id")["v"].to_list()) == sorted(df["v"].to_list())
        assert df.sort("sample_id").height == df.height
