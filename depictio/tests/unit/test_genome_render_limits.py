"""Server-side limits of the genome and flow kinds.

- ``region_scope``: a genome region reaches coordinate-bound components only.
- ``_bin_coverage_frame``: a coverage track wider than its pixel budget is
  binned per sample instead of shipping every row.
- ``_sankey_result_from_frame``: the flow aggregates every row, and the step
  pickers are listed from the same frame rather than from a capped fetch.
"""

import polars as pl

from depictio.api.v1.celery_tasks import _bin_coverage_frame, _sankey_result_from_frame
from depictio.api.v1.region_scope import follows_region, scope_region_filters


def _region_pair(dc_id: str = "dc-cov") -> list[dict]:
    return [
        {
            "index": "nav",
            "value": ["chr2"],
            "source": "genome_selection",
            "metadata": {
                "dc_id": dc_id,
                "column_name": "chrom",
                "interactive_component_type": "MultiSelect",
            },
        },
        {
            "index": "nav::pos",
            "value": [100, 200],
            "source": "genome_selection",
            "metadata": {
                "dc_id": dc_id,
                "column_name": "start",
                "interactive_component_type": "RangeSlider",
            },
        },
    ]


SAMPLE_FILTER = {
    "index": "sidebar-sample",
    "value": ["S1"],
    "metadata": {
        "dc_id": "dc-cov",
        "column_name": "sample",
        "interactive_component_type": "MultiSelect",
    },
}


class TestRegionScope:
    def test_card_drops_the_region_and_keeps_other_filters(self):
        out = scope_region_filters([SAMPLE_FILTER, *_region_pair()], "card", {"index": "c"})
        assert out == [SAMPLE_FILTER]

    def test_card_opting_in_keeps_the_region(self):
        filters = [SAMPLE_FILTER, *_region_pair()]
        card = {"index": "c", "follow_region_filter": True}
        assert follows_region(card)
        assert scope_region_filters(filters, "card", card) == filters

    def test_figure_without_a_region_column_drops_it(self):
        figure = {"dict_kwargs": {"x": "sample", "y": "depth"}}
        assert scope_region_filters(_region_pair(), "figure", figure) == []

    def test_figure_encoding_the_position_keeps_it(self):
        figure = {"dict_kwargs": {"x": "start", "y": "depth", "color": "sample"}}
        assert scope_region_filters(_region_pair(), "figure", figure) == _region_pair()

    def test_interactive_options_ignore_the_region(self):
        # The funnel narrows a sidebar selector under every other filter; a
        # contig picker must not collapse to the navigator's contig.
        contig_picker = {"index": "f", "component_type": "interactive"}
        out = scope_region_filters([SAMPLE_FILTER, *_region_pair()], "interactive", contig_picker)
        assert out == [SAMPLE_FILTER]
        opted_in = {**contig_picker, "follow_region_filter": True}
        assert scope_region_filters(_region_pair(), "interactive", opted_in) == _region_pair()

    def test_other_types_are_untouched(self):
        filters = _region_pair()
        for kind in ("table", "advanced_viz", "multiqc", "map"):
            assert scope_region_filters(filters, kind, {}) == filters

    def test_no_region_is_a_copy(self):
        filters = [SAMPLE_FILTER]
        out = scope_region_filters(filters, "card")
        assert out == filters and out is not filters


def _coverage(n_per_sample: int, samples=("S1", "S2")) -> pl.DataFrame:
    rows = []
    for s in samples:
        for i in range(n_per_sample):
            rows.append(
                {
                    "chrom": "chr1",
                    "pos": i * 10,
                    "end": i * 10 + 10,
                    "depth": float(i % 7),
                    "sample": s,
                }
            )
    return pl.DataFrame(rows)


class TestCoverageBinning:
    kwargs = dict(
        chromosome_col="chrom",
        position_col="pos",
        value_col="depth",
        end_col="end",
        sample_col="sample",
        category_col=None,
    )

    def test_within_budget_is_untouched(self):
        df = _coverage(100)
        out, width = _bin_coverage_frame(df, max_bins=4000, **self.kwargs)
        assert width is None
        assert out.equals(df)

    def test_wide_track_is_binned_per_sample(self):
        df = _coverage(10_000)
        out, width = _bin_coverage_frame(df, max_bins=1000, **self.kwargs)
        assert width == 100  # 100,000 bp over 1,000 bins
        per_sample = out.group_by("sample").len().get_column("len").to_list()
        assert all(n <= 1000 for n in per_sample)
        assert set(out.get_column("sample").to_list()) == {"S1", "S2"}
        # Bins keep their extent and a mean value.
        first = out.filter(pl.col("sample") == "S1").row(0, named=True)
        assert first["pos"] == 0 and first["end"] == 100
        assert abs(first["depth"] - df.head(10).get_column("depth").mean()) < 1e-9

    def test_zero_budget_disables_binning(self):
        df = _coverage(5000)
        out, width = _bin_coverage_frame(df, max_bins=0, **self.kwargs)
        assert width is None and out.height == df.height


class TestSankeyAggregation:
    def _frame(self) -> pl.DataFrame:
        # 5,652 rows, more than the 5,000-row cap the renderer's option fetch
        # used to apply: the flow and the options must both see every row.
        n = 5652
        return pl.DataFrame(
            {
                "kingdom": ["Bacteria" if i % 3 else "Archaea" for i in range(n)],
                "phylum": [f"P{i % 5}" if i < 5600 else "Rare" for i in range(n)],
            }
        )

    def test_flow_aggregates_every_row(self):
        out = _sankey_result_from_frame(
            self._frame(),
            step_cols=["kingdom", "phylum"],
            value_col=None,
            sort_mode="total_flow",
            min_link_value=0,
            step_filters={},
        )
        assert out["total_flow"] == 5652
        assert out["input_rows"] == 5652
        assert "Rare" in out["step_options"]["phylum"]

    def test_options_ignore_the_step_filters(self):
        out = _sankey_result_from_frame(
            self._frame(),
            step_cols=["kingdom", "phylum"],
            value_col=None,
            sort_mode="total_flow",
            min_link_value=0,
            step_filters={"kingdom": ["Archaea"]},
            option_cols=["kingdom", "phylum"],
        )
        assert out["step_options"]["kingdom"] == ["Archaea", "Bacteria"]
        assert out["row_count"] < out["input_rows"]
