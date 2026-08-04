"""The ``__breakdown__`` payload the card's categorical strips draw.

Two callers compute it — ``bulk_compute_cards`` for a saved card and
``/deltatables/breakdown`` for the builder preview — and they must agree, or the
preview lies about what the card will show once saved. Historically it did
exactly that: the preview invented ``Bucket 1 / Bucket 2 / Bucket 3`` at a
uniform 33/33/34 split, so a correctly configured card looked broken in the
builder and rendered different numbers on the dashboard.

These tests pin the shared helper's contract: the per-group reduction mirrors
the hero aggregation, the whole-distribution fields describe the tail the strip
cannot draw, and nothing about the payload is synthesised.
"""

import polars as pl
import pytest

from depictio.api.v1.services.card_breakdown import (
    BREAKDOWN_LAYOUTS,
    MAX_TOP_N,
    compute_breakdown,
    group_expr,
)
from depictio.models.components.lite import CardLiteComponent


@pytest.fixture
def frame() -> pl.DataFrame:
    """50 Setosa / 30 Versicolor / 20 Virginica, with a numeric hero column."""
    return pl.DataFrame(
        {
            "variety": ["Setosa"] * 50 + ["Versicolor"] * 30 + ["Virginica"] * 20,
            "petal": list(range(100)),
            # Deliberately fewer distinct values than rows, so ``nunique`` per
            # group differs from the row count and the two reductions are
            # distinguishable.
            "batch": (["b1"] * 25 + ["b2"] * 25) + (["b3"] * 30) + (["b4"] * 20),
        }
    )


class TestPayloadShape:
    def test_names_are_the_real_categories(self, frame):
        """The regression that started this: no invented ``Bucket N`` labels."""
        payload = compute_breakdown(frame, "petal", "variety", "count", 3)
        assert [r["name"] for r in payload["top"]] == ["Setosa", "Versicolor", "Virginica"]

    def test_counts_are_the_real_distribution(self, frame):
        """And not a uniform spread across the top-N."""
        payload = compute_breakdown(frame, "petal", "variety", "count", 3)
        assert [r["count"] for r in payload["top"]] == [50, 30, 20]
        assert [r["percent"] for r in payload["top"]] == [0.5, 0.3, 0.2]

    def test_sorted_by_descending_count(self, frame):
        counts = [
            r["count"] for r in compute_breakdown(frame, "petal", "variety", "count", 3)["top"]
        ]
        assert counts == sorted(counts, reverse=True)

    def test_whole_distribution_fields_cover_the_undrawn_tail(self, frame):
        """``top`` is truncated; ``total`` / ``unique_values`` / ``top_share``
        must still describe every group, or the "Other" remainder is wrong."""
        payload = compute_breakdown(frame, "petal", "variety", "count", 1)
        assert len(payload["top"]) == 1
        assert payload["total"] == 100
        assert payload["unique_values"] == 3
        assert payload["top_share"] == pytest.approx(0.5)

    def test_top_share_is_one_when_nothing_is_truncated(self, frame):
        payload = compute_breakdown(frame, "petal", "variety", "count", 5)
        assert payload["top_share"] == pytest.approx(1.0)

    def test_top_n_is_clamped_to_the_renderer_limit(self, frame):
        """Past ``MAX_TOP_N`` the strip is illegible; the model caps at the same
        number, so the helper must not out-run it."""
        payload = compute_breakdown(frame, "petal", "batch", "count", 99)
        assert len(payload["top"]) <= MAX_TOP_N

    def test_accepts_a_lazyframe(self, frame):
        """The endpoint passes a scan, not a materialised frame."""
        eager = compute_breakdown(frame, "petal", "variety", "count", 3)
        lazy = compute_breakdown(frame.lazy(), "petal", "variety", "count", 3)
        assert eager == lazy


class TestGroupReductionMirrorsHero:
    """The strip's percentages have to add up to the hero value printed above
    them, so the per-group reduction must match the hero aggregation."""

    def test_count_hero_counts_rows(self, frame):
        payload = compute_breakdown(frame, "petal", "variety", "count", 3)
        assert payload["total"] == frame.height

    def test_nunique_hero_counts_distinct_values_per_group(self, frame):
        payload = compute_breakdown(frame, "batch", "variety", "nunique", 3)
        by_name = {r["name"]: r["count"] for r in payload["top"]}
        # Setosa spans b1+b2, the others one batch each.
        assert by_name == {"Setosa": 2, "Versicolor": 1, "Virginica": 1}

    def test_sum_hero_sums_the_column(self, frame):
        payload = compute_breakdown(frame, "petal", "variety", "sum", 3)
        assert payload["total"] == sum(range(100))

    def test_unique_is_accepted_as_a_spelling_of_nunique(self, frame):
        """Precomputed specs record numeric distinct-counts as ``unique``; a card
        carrying that spelling must not silently fall back to row counts."""
        # ``breakdown_kind`` deliberately echoes the card's own spelling, so
        # compare the computed numbers rather than the whole payload.
        alias = compute_breakdown(frame, "batch", "variety", "unique", 3)
        canonical = compute_breakdown(frame, "batch", "variety", "nunique", 3)
        assert alias["top"] == canonical["top"]
        assert alias["total"] == canonical["total"]
        # And it genuinely differs from the row-count reduction, or this would
        # pass for the wrong reason.
        assert alias["top"] != compute_breakdown(frame, "batch", "variety", "count", 3)["top"]

    def test_hero_column_equal_to_breakdown_falls_back_to_row_count(self, frame):
        """``n_unique(variety)`` within each ``variety`` group is trivially 1 —
        N equal bars carrying no information. Row count is the useful reading."""
        payload = compute_breakdown(frame, "variety", "variety", "nunique", 3)
        assert [r["count"] for r in payload["top"]] == [50, 30, 20]

    def test_group_expr_is_the_documented_choice(self):
        """Guards the branch table itself, so a refactor can't quietly collapse
        two reductions into one."""
        assert str(group_expr("a", "b", "sum")) != str(group_expr("a", "b", "count"))
        assert str(group_expr("a", "b", "nunique")) != str(group_expr("a", "b", "count"))
        # Hero == breakdown short-circuits to the row count regardless of hero.
        assert str(group_expr("b", "b", "nunique")) == str(group_expr("a", "b", "count"))


class TestEdgeCases:
    def test_nulls_become_a_visible_category(self):
        """A column that is 40% unfilled is exactly what a composition bar
        should show — an unlabelled empty segment would hide it."""
        df = pl.DataFrame({"g": ["x", "x", None, None], "v": [1, 2, 3, 4]})
        payload = compute_breakdown(df, "v", "g", "count", 3)
        assert {r["name"] for r in payload["top"]} == {"x", "(null)"}

    def test_empty_frame_does_not_divide_by_zero(self):
        df = pl.DataFrame({"g": [], "v": []}, schema={"g": pl.Utf8, "v": pl.Int64})
        payload = compute_breakdown(df, "v", "g", "count", 3)
        assert payload["total"] == 0
        assert payload["top"] == []
        assert payload["top_share"] == 0.0
        assert payload["evenness"] is None

    def test_single_category_reports_degenerate_evenness(self):
        """One category would score 0, which reads as "dominated" when the
        honest answer is "not applicable"."""
        df = pl.DataFrame({"g": ["only"] * 10, "v": list(range(10))})
        assert compute_breakdown(df, "v", "g", "count", 3)["evenness"] is None

    def test_balanced_and_dominated_distributions_are_distinguishable(self):
        balanced = pl.DataFrame({"g": ["a"] * 50 + ["b"] * 50, "v": list(range(100))})
        dominated = pl.DataFrame({"g": ["a"] * 99 + ["b"], "v": list(range(100))})
        assert compute_breakdown(balanced, "v", "g", "count", 2)["evenness"] == pytest.approx(1.0)
        assert compute_breakdown(dominated, "v", "g", "count", 2)["evenness"] < 0.15


class TestLayoutsStayInSync:
    """A layout that needs the payload but isn't in ``BREAKDOWN_LAYOUTS`` renders
    an empty strip — the failure mode ``composition`` nearly shipped with."""

    def test_every_breakdown_layout_is_a_valid_model_layout(self):
        from typing import get_args

        allowed = set(get_args(CardLiteComponent.model_fields["secondary_layout"].annotation))
        assert set(BREAKDOWN_LAYOUTS) <= allowed

    def test_donut_is_wired_through(self):
        """The layout the user asked for, end to end: model accepts it and it is
        gated as needing a breakdown."""
        assert "donut" in BREAKDOWN_LAYOUTS
        card = CardLiteComponent(
            component_type="card",
            column_name="variety",
            column_type="object",
            aggregation="count",
            secondary_layout="donut",
            breakdown_col="variety",
        )
        assert card.secondary_layout == "donut"

    def test_frontend_mirror_lists_the_same_layouts(self):
        """``SecondaryMetrics.tsx`` re-declares this set for the builder's
        required-field gating. Drift there means the builder hides the breakdown
        picker for a layout that needs it."""
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
        if not source.exists():  # packages/ is absent in some install layouts
            pytest.skip("frontend package not present in this checkout")
        block = re.search(
            r"export const BREAKDOWN_LAYOUTS\s*=\s*\[(.*?)\]", source.read_text(), re.S
        )
        assert block, "BREAKDOWN_LAYOUTS not found — did the export get renamed?"
        names = set(re.findall(r"'([a-z_]+)'", block.group(1)))
        assert names, "parsed an empty layout list — the guard would pass vacuously"
        assert names == set(BREAKDOWN_LAYOUTS)
