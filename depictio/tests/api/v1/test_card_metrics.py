"""Numeric / QC card layouts: histogram, threshold, completeness, attrition.

Each exists because an existing layout structurally *cannot* answer its
question, and the tests below pin those specific properties rather than the
arithmetic in general:

* ``histogram`` must distinguish shapes that ``box_plot`` renders identically;
* ``threshold`` must not silently invert a QC verdict, and must not count a
  missing measurement as a failed one;
* ``completeness`` must reveal what a hero ``count`` hides, since ``count``
  already skips nulls;
* ``attrition`` must preserve the pipeline's stage order, which is the entire
  content of the chart.
"""

import polars as pl
import pytest

from depictio.api.v1.services.card_metrics import (
    HISTOGRAM_BINS,
    NUMERIC_LAYOUTS,
    compute_attrition,
    compute_completeness,
    compute_histogram,
    compute_threshold,
    numeric_layout_payload,
)
from depictio.models.components.lite import CardLiteComponent


class TestHistogram:
    def test_reveals_a_shape_box_plot_cannot(self):
        """The layout's entire reason to exist. These two columns share min, max
        and median, so a five-number summary draws them the same; the histogram
        must not."""
        bimodal = pl.DataFrame({"v": [1.0] * 40 + [9.0] * 40})
        uniform = pl.DataFrame({"v": [float(x) for x in range(1, 10)] * 9})
        b = compute_histogram(bimodal, "v", bins=10)
        u = compute_histogram(uniform, "v", bins=10)
        assert b is not None and u is not None
        # Same summary...
        assert (b["min"], b["max"]) == (u["min"], u["max"])
        # ...different shape: the bimodal column leaves a gap in the middle.
        middle = b["bins"][3:7]
        assert sum(middle) == 0
        assert sum(u["bins"][3:7]) > 0

    def test_counts_are_complete(self):
        df = pl.DataFrame({"v": [float(x) for x in range(100)]})
        h = compute_histogram(df, "v", bins=10)
        assert h is not None
        assert sum(h["bins"]) == 100

    def test_breakpoints_align_with_bins(self):
        df = pl.DataFrame({"v": [float(x) for x in range(50)]})
        h = compute_histogram(df, "v", bins=8)
        assert h is not None
        assert len(h["breakpoints"]) == len(h["bins"])

    def test_constant_column_has_no_histogram(self):
        """Every bar identical would read as a uniform distribution when the
        truth is a single value."""
        assert compute_histogram(pl.DataFrame({"v": [7.0] * 20}), "v") is None

    def test_single_row_has_no_histogram(self):
        assert compute_histogram(pl.DataFrame({"v": [1.0]}), "v") is None

    def test_empty_column_has_no_histogram(self):
        df = pl.DataFrame({"v": []}, schema={"v": pl.Float64})
        assert compute_histogram(df, "v") is None

    def test_nulls_are_reported_not_binned(self):
        """A mostly-empty column must not masquerade as a narrow distribution."""
        df = pl.DataFrame({"v": [1.0, 2.0, 3.0, None, None]})
        h = compute_histogram(df, "v", bins=4)
        assert h is not None
        assert h["nulls"] == 2
        assert sum(h["bins"]) == 3

    def test_default_bin_count_is_the_documented_one(self):
        df = pl.DataFrame({"v": [float(x) for x in range(200)]})
        h = compute_histogram(df, "v")
        assert h is not None and len(h["bins"]) == HISTOGRAM_BINS


class TestThreshold:
    @pytest.fixture
    def frame(self) -> pl.DataFrame:
        # 10 clearly passing, 5 in a warn band, 3 failing, 2 unmeasured.
        return pl.DataFrame({"q": [95.0] * 10 + [75.0] * 5 + [50.0] * 3 + [None] * 2})

    def test_counts_split_the_measured_rows(self, frame):
        r = compute_threshold(frame, "q", 80.0, "min")
        assert r is not None
        assert r["passing"] + r["warning"] + r["failing"] == r["measured"]

    def test_nulls_are_not_failures(self, frame):
        """A missing measurement is not a failed one — counting it as a failure
        would invent QC problems that do not exist."""
        r = compute_threshold(frame, "q", 80.0, "min")
        assert r is not None
        assert r["nulls"] == 2
        assert r["measured"] == 18
        assert r["total"] == 20
        assert r["failing"] == 8  # the 5 warn-band rows + 3 low ones, no nulls

    def test_direction_min_means_higher_is_better(self, frame):
        r = compute_threshold(frame, "q", 80.0, "min")
        assert r is not None and r["passing"] == 10

    def test_direction_max_inverts_the_verdict(self, frame):
        """``max`` is for duplication / contamination, where low passes. The two
        directions must not agree, or the field does nothing."""
        low_passes = compute_threshold(frame, "q", 80.0, "max")
        high_passes = compute_threshold(frame, "q", 80.0, "min")
        assert low_passes is not None and high_passes is not None
        assert low_passes["passing"] == 8
        assert low_passes["passing"] != high_passes["passing"]

    def test_warn_band_sits_between_pass_and_fail(self, frame):
        r = compute_threshold(frame, "q", 80.0, "min", warn_threshold=70.0)
        assert r is not None
        assert (r["passing"], r["warning"], r["failing"]) == (10, 5, 3)

    def test_warn_on_the_passing_side_is_ignored(self, frame):
        """A warn threshold above the pass cut-off would relabel passing rows as
        warnings; refusing it is safer than honouring a contradiction."""
        r = compute_threshold(frame, "q", 80.0, "min", warn_threshold=90.0)
        assert r is not None
        assert r["warn_threshold"] is None
        assert r["warning"] == 0
        assert r["passing"] == 10

    def test_warn_band_respects_max_direction(self):
        df = pl.DataFrame({"dup": [5.0] * 10 + [25.0] * 4 + [60.0] * 2})
        r = compute_threshold(df, "dup", 20.0, "max", warn_threshold=30.0)
        assert r is not None
        assert (r["passing"], r["warning"], r["failing"]) == (10, 4, 2)

    def test_boundary_value_passes(self, frame):
        """``>=`` not ``>``: a sample at exactly 30x coverage meets a 30x
        criterion."""
        df = pl.DataFrame({"v": [30.0, 29.9]})
        r = compute_threshold(df, "v", 30.0, "min")
        assert r is not None and r["passing"] == 1

    def test_all_null_column_yields_no_rate(self):
        df = pl.DataFrame({"v": [None, None]}, schema={"v": pl.Float64})
        r = compute_threshold(df, "v", 1.0, "min")
        assert r is not None
        assert r["measured"] == 0
        assert r["pass_rate"] == 0.0


class TestCompleteness:
    def test_reports_what_a_count_hides(self):
        """``count`` skips nulls, so a hero value of 3 looks complete on a
        5-row table. This is the layout that says otherwise."""
        df = pl.DataFrame({"v": [1.0, 2.0, 3.0, None, None]})
        r = compute_completeness(df, "v")
        assert r is not None
        assert (r["total"], r["filled"], r["nulls"]) == (5, 3, 2)
        assert r["fill_rate"] == pytest.approx(0.6)

    def test_full_column_is_one(self):
        r = compute_completeness(pl.DataFrame({"v": [1, 2, 3]}), "v")
        assert r is not None and r["fill_rate"] == 1.0

    def test_empty_frame_does_not_divide_by_zero(self):
        df = pl.DataFrame({"v": []}, schema={"v": pl.Float64})
        r = compute_completeness(df, "v")
        assert r is not None and r["fill_rate"] == 0.0

    def test_empty_strings_are_not_counted_as_missing(self):
        """Documented limitation: sentinels are a domain convention this layer
        cannot distinguish from data, and guessing would report a number the
        user cannot reproduce."""
        df = pl.DataFrame({"v": ["a", "", "c"]})
        r = compute_completeness(df, "v")
        assert r is not None and r["nulls"] == 0


class TestAttrition:
    def test_shares_are_relative_to_the_first_stage(self):
        df = pl.DataFrame({"raw": [100.0], "trim": [90.0], "map": [45.0]})
        r = compute_attrition(df, ["raw", "trim", "map"])
        assert r is not None
        assert [s["share"] for s in r["stages"]] == [1.0, 0.9, 0.45]
        assert r["retained"] == 0.45

    def test_step_share_isolates_the_damaging_stage(self):
        """A 45% cumulative survival reads very differently when one step lost
        half the reads versus a gradual decline — the cumulative curve alone
        cannot tell them apart."""
        df = pl.DataFrame({"raw": [100.0], "trim": [90.0], "map": [45.0]})
        r = compute_attrition(df, ["raw", "trim", "map"])
        assert r is not None
        assert r["stages"][0]["step_share"] is None
        assert r["stages"][1]["step_share"] == pytest.approx(0.9)
        assert r["stages"][2]["step_share"] == pytest.approx(0.5)

    def test_stage_order_is_the_pipeline_order_not_sorted(self):
        """Sorting by value would destroy the chart's meaning."""
        df = pl.DataFrame({"a": [10.0], "b": [50.0], "c": [30.0]})
        r = compute_attrition(df, ["a", "b", "c"])
        assert r is not None
        assert [s["name"] for s in r["stages"]] == ["a", "b", "c"]

    def test_a_rising_stage_is_reported_not_clamped(self):
        """It means the columns were listed in the wrong order; hiding that
        leaves the user with a chart they cannot explain."""
        df = pl.DataFrame({"a": [10.0], "b": [50.0]})
        r = compute_attrition(df, ["a", "b"])
        assert r is not None and r["stages"][1]["share"] == 5.0

    def test_aggregation_choice_changes_the_reduction(self):
        df = pl.DataFrame({"a": [10.0, 30.0], "b": [5.0, 15.0]})
        summed = compute_attrition(df, ["a", "b"], "sum")
        averaged = compute_attrition(df, ["a", "b"], "average")
        assert summed is not None and averaged is not None
        assert summed["stages"][0]["value"] == 40.0
        assert averaged["stages"][0]["value"] == 20.0
        # The *share* is scale-invariant, which is what the bars draw.
        assert summed["retained"] == averaged["retained"]

    def test_fewer_than_two_stages_is_not_a_funnel(self):
        df = pl.DataFrame({"a": [1.0]})
        assert compute_attrition(df, ["a"]) is None

    def test_zero_first_stage_does_not_divide_by_zero(self):
        df = pl.DataFrame({"a": [0.0], "b": [0.0]})
        r = compute_attrition(df, ["a", "b"])
        assert r is not None and r["retained"] == 0.0


class TestDispatcher:
    """``numeric_layout_payload`` is what both callers go through, so the
    config-to-helper wiring is what actually ships."""

    @pytest.fixture
    def frame(self) -> pl.DataFrame:
        return pl.DataFrame(
            {"v": [float(x) for x in range(20)], "b": [float(x) for x in range(20)]}
        )

    def test_threshold_without_a_value_declines(self, frame):
        """Rendering a strip with an implicit cut-off would assert a QC verdict
        the user never chose."""
        assert numeric_layout_payload(frame, {}, "v", "threshold") is None

    def test_threshold_passes_direction_and_warn_through(self, frame):
        card = {"threshold_value": 10, "threshold_direction": "max", "threshold_warn": 15}
        r = numeric_layout_payload(frame, card, "v", "threshold")
        assert r is not None
        assert r["direction"] == "max"
        assert r["warn_threshold"] == 15.0

    def test_attrition_prepends_the_cards_own_column(self, frame):
        """The card's column is the first stage; a user listing only the later
        ones still gets a funnel that starts where the card does."""
        r = numeric_layout_payload(frame, {"attrition_cols": ["b"]}, "v", "attrition")
        assert r is not None
        assert [s["name"] for s in r["stages"]] == ["v", "b"]

    def test_attrition_does_not_duplicate_an_explicit_first_stage(self, frame):
        r = numeric_layout_payload(frame, {"attrition_cols": ["v", "b"]}, "v", "attrition")
        assert r is not None
        assert [s["name"] for s in r["stages"]] == ["v", "b"]

    def test_missing_columns_are_dropped_not_raised(self, frame):
        """A column renamed upstream must degrade to a shorter funnel rather
        than break the whole dashboard's card compute."""
        r = numeric_layout_payload(frame, {"attrition_cols": ["b", "gone"]}, "v", "attrition")
        assert r is not None
        assert [s["name"] for s in r["stages"]] == ["v", "b"]

    def test_unknown_column_declines(self, frame):
        assert numeric_layout_payload(frame, {}, "nope", "histogram") is None

    def test_unknown_layout_declines(self, frame):
        assert numeric_layout_payload(frame, {}, "v", "not_a_layout") is None

    def test_accepts_a_lazyframe(self, frame):
        """The preview endpoint passes a scan, not a materialised frame."""
        assert numeric_layout_payload(frame.lazy(), {}, "v", "completeness") == (
            numeric_layout_payload(frame, {}, "v", "completeness")
        )


class TestLayoutsStayInSync:
    def test_every_numeric_layout_is_a_valid_model_layout(self):
        from typing import get_args

        allowed = set(get_args(CardLiteComponent.model_fields["secondary_layout"].annotation))
        assert set(NUMERIC_LAYOUTS) <= allowed

    def test_model_accepts_each_layout_with_its_config(self):
        base = {
            "component_type": "card",
            "column_name": "v",
            "column_type": "float64",
            "aggregation": "average",
        }
        CardLiteComponent(**base, secondary_layout="histogram")
        CardLiteComponent(**base, secondary_layout="completeness")
        CardLiteComponent(**base, secondary_layout="threshold", threshold_value=30)
        CardLiteComponent(**base, secondary_layout="attrition", attrition_cols=["a", "b"])

    def test_threshold_direction_rejects_a_typo(self):
        """A misspelled direction silently defaulting to ``min`` would invert a
        QC verdict without telling anyone."""
        with pytest.raises(ValueError):
            CardLiteComponent(
                component_type="card",
                column_name="v",
                column_type="float64",
                aggregation="average",
                secondary_layout="threshold",
                threshold_value=30,
                threshold_direction="minimum",
            )

    def test_frontend_mirror_lists_the_same_layouts(self):
        """The builder gates its config fields and preview fetch on the
        frontend copy; drift means a layout renders with no strip."""
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "depictio-react-core"
            / "src"
            / "components"
            / "card"
            / "SecondaryMetrics.tsx"
        )
        if not source.exists():
            pytest.skip("frontend package not present in this checkout")
        block = re.search(r"export const NUMERIC_LAYOUTS\s*=\s*\[(.*?)\]", source.read_text(), re.S)
        assert block, "NUMERIC_LAYOUTS not found — did the export get renamed?"
        names = set(re.findall(r"'([a-z_]+)'", block.group(1)))
        assert names, "parsed an empty layout list — the guard would pass vacuously"
        assert names == set(NUMERIC_LAYOUTS)
