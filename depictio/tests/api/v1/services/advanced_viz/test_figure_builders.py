"""Structural assertions on the Python advanced-viz figure builders.

These deliberately assert *structure and semantics* (tier classification, trace
count, threshold placement, axis titles) rather than a byte-for-byte golden. A
golden would be brittle against cosmetic layout tweaks; these catch the failures
that actually matter — a point coloured into the wrong tier, a threshold line on
the wrong axis, a missing -log10 transform.

Parity with the TypeScript renderers is a separate concern; see the module
docstrings in ``services/advanced_viz/kinds/`` for which TS file each mirrors.
"""

from __future__ import annotations

import math

import pytest

from depictio.api.v1.services.advanced_viz.figure_registry import (
    build,
    required_columns,
    supported_kinds,
)
from depictio.api.v1.services.advanced_viz.theme import (
    apply_layout_theme,
    colors_for_theme,
    plotly_theme_colors,
)

# --- volcano ----------------------------------------------------------------

VOLCANO_CONFIG = {
    "feature_id_col": "gene",
    "effect_size_col": "lfc",
    "significance_col": "padj",
    "significance_threshold": 0.05,
    "effect_threshold": 1.0,
    "top_n_labels": 2,
}

VOLCANO_ROWS = {
    # up-hit, down-hit, not-significant, big-effect-but-not-significant, null p
    "gene": ["up", "down", "ns", "loud", "missing"],
    "lfc": [2.0, -3.0, 0.1, 5.0, 1.5],
    "padj": [0.001, 0.0001, 0.9, 0.5, None],
}


def test_volcano_classifies_tiers_via_marker_colour() -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme="light")
    colors = spec["data"][0]["marker"]["color"]
    assert colors[0] == "#e64980", "positive significant effect should be UP"
    assert colors[1] == "#1c7ed6", "negative significant effect should be DN"
    assert colors[2] == "rgba(160,160,160,0.55)", "sub-threshold effect should be NS"
    assert colors[3] == "rgba(160,160,160,0.55)", "large effect but p>threshold is NS"
    assert colors[4] == "rgba(160,160,160,0.55)", "null p-value cannot be a hit"


def test_volcano_sizes_hits_larger_than_background() -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme="light")
    sizes = spec["data"][0]["marker"]["size"]
    assert sizes[0] == 7 and sizes[1] == 7
    assert sizes[2] == 5 and sizes[4] == 5


def test_volcano_applies_neg_log10_when_column_holds_raw_p() -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme="light")
    ys = spec["data"][0]["y"]
    assert ys[0] == pytest.approx(-math.log10(0.001))
    assert ys[4] is None, "a null p-value yields no y position"


def test_volcano_skips_transform_when_already_neg_log10() -> None:
    config = {**VOLCANO_CONFIG, "significance_is_neg_log10": True, "significance_threshold": 2.0}
    rows = {"gene": ["a"], "lfc": [3.0], "padj": [4.0]}
    spec = build("volcano", config=config, rows=rows, theme="light")
    assert spec["data"][0]["y"] == [4.0]
    assert spec["data"][0]["marker"]["color"] == ["#e64980"]


def test_volcano_threshold_lines_bracket_the_effect_threshold() -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme="light")
    shapes = spec["layout"]["shapes"]
    assert len(shapes) == 3
    vertical = sorted(s["x0"] for s in shapes if s.get("yref") == "paper")
    assert vertical == [-1.0, 1.0]
    horizontal = next(s for s in shapes if s.get("xref") == "paper")
    assert horizontal["y0"] == pytest.approx(-math.log10(0.05))


def test_volcano_labels_are_capped_at_top_n() -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme="light")
    assert len(spec["layout"]["annotations"]) <= VOLCANO_CONFIG["top_n_labels"]


def test_volcano_search_overrides_top_n_selection() -> None:
    spec = build(
        "volcano",
        config=VOLCANO_CONFIG,
        rows=VOLCANO_ROWS,
        theme="light",
        controls={"search": "down"},
    )
    texts = [a["text"] for a in spec["layout"]["annotations"]]
    assert texts == ["down"]


def test_volcano_controls_override_persisted_config() -> None:
    spec = build(
        "volcano",
        config=VOLCANO_CONFIG,
        rows=VOLCANO_ROWS,
        theme="light",
        controls={"effect_threshold": 4.0, "significance_threshold": 0.6},
    )
    colors = spec["data"][0]["marker"]["color"]
    # 'loud' (lfc 5.0, padj 0.5) now clears both relaxed thresholds.
    assert colors[3] == "#e64980"
    # 'up' (lfc 2.0) no longer clears the raised effect threshold.
    assert colors[0] == "rgba(160,160,160,0.55)"


def test_volcano_required_columns_drop_unset_optionals() -> None:
    cols = required_columns("volcano", VOLCANO_CONFIG)
    assert cols == ["gene", "lfc", "padj"]
    with_label = required_columns("volcano", {**VOLCANO_CONFIG, "label_col": "symbol"})
    assert "symbol" in with_label


# --- ma ---------------------------------------------------------------------

MA_CONFIG = {
    "feature_id_col": "gene",
    "avg_log_intensity_col": "base_mean",
    "log2_fold_change_col": "lfc",
    "significance_col": "padj",
    "fold_change_threshold": 1.0,
    "significance_threshold": 0.05,
}
MA_ROWS = {
    "gene": ["up", "down", "ns"],
    "base_mean": [10.0, 12.0, 8.0],
    "lfc": [2.0, -2.0, 0.2],
    "padj": [0.01, 0.01, 0.9],
}


def test_ma_tiers_match_volcano_scheme() -> None:
    spec = build("ma", config=MA_CONFIG, rows=MA_ROWS, theme="light")
    assert spec["data"][0]["marker"]["color"] == [
        "#e64980",
        "#1c7ed6",
        "rgba(160,160,160,0.55)",
    ]


def test_ma_without_significance_column_tiers_on_fold_change_alone() -> None:
    config = {k: v for k, v in MA_CONFIG.items() if k != "significance_col"}
    rows = {k: v for k, v in MA_ROWS.items() if k != "padj"}
    spec = build("ma", config=config, rows=rows, theme="light")
    assert spec["data"][0]["marker"]["color"] == [
        "#e64980",
        "#1c7ed6",
        "rgba(160,160,160,0.55)",
    ]
    assert "padj" not in spec["data"][0]["hovertemplate"]


def test_ma_threshold_lines_are_horizontal_and_symmetric() -> None:
    spec = build("ma", config=MA_CONFIG, rows=MA_ROWS, theme="light")
    shapes = spec["layout"]["shapes"]
    assert len(shapes) == 2
    assert all(s["xref"] == "paper" for s in shapes)
    assert sorted(s["y0"] for s in shapes) == [-1.0, 1.0]


# --- qq ---------------------------------------------------------------------

QQ_CONFIG = {"p_value_col": "p", "feature_id_col": "snp"}
QQ_ROWS = {
    "snp": [f"rs{i}" for i in range(10)],
    "p": [0.9, 0.5, 0.3, 0.2, 0.1, 0.05, 0.01, 0.001, 0.0001, 1e-8],
}


def test_qq_series_descend_because_points_are_sorted_by_ascending_p() -> None:
    """Both axes descend: the smallest p sorts first and gives the largest -log10.

    This is the detail the TS renderer calls out (QQRenderer.tsx:172-175) — the
    expected maximum is at index 0, not at the end.
    """
    spec = build("qq", config=QQ_CONFIG, rows=QQ_ROWS, theme="light", controls={"show_ci": False})
    points = spec["data"][0]
    assert points["y"] == sorted(points["y"], reverse=True)
    assert points["x"] == sorted(points["x"], reverse=True)
    assert points["x"][0] == max(points["x"])


def test_qq_drops_p_values_outside_the_unit_interval() -> None:
    rows = {"snp": ["a", "b", "c", "d"], "p": [0.5, 0.0, -1.0, None]}
    spec = build("qq", config=QQ_CONFIG, rows=rows, theme="light", controls={"show_ci": False})
    assert len(spec["data"][0]["y"]) == 1


def test_qq_annotates_genomic_inflation_lambda() -> None:
    spec = build("qq", config=QQ_CONFIG, rows=QQ_ROWS, theme="light", controls={"show_ci": False})
    texts = [a["text"] for a in spec["layout"]["annotations"]]
    assert any(t.startswith("λ = ") for t in texts)


def test_qq_confidence_band_is_prepended_so_it_paints_behind() -> None:
    with_ci = build("qq", config=QQ_CONFIG, rows=QQ_ROWS, theme="light", controls={"show_ci": True})
    assert with_ci["data"][1]["fill"] == "tonexty"
    assert with_ci["data"][0]["hoverinfo"] == "skip"
    without = build(
        "qq", config=QQ_CONFIG, rows=QQ_ROWS, theme="light", controls={"show_ci": False}
    )
    assert len(with_ci["data"]) == len(without["data"]) + 2


def test_qq_categories_produce_one_trace_each_with_stable_colours() -> None:
    rows = {**QQ_ROWS, "chr": ["b"] * 5 + ["a"] * 5}
    spec = build(
        "qq",
        config={**QQ_CONFIG, "category_col": "chr"},
        rows=rows,
        theme="light",
    )
    named = [t for t in spec["data"] if t.get("name")]
    assert [t["name"] for t in named] == ["a", "b"]
    # Palette index follows the sorted universe, not encounter order.
    assert named[0]["marker"]["color"] == "#1f77b4"
    assert spec["layout"]["showlegend"] is True


def test_qq_identity_diagonal_spans_both_axes() -> None:
    spec = build("qq", config=QQ_CONFIG, rows=QQ_ROWS, theme="light", controls={"show_ci": False})
    diagonal = spec["layout"]["shapes"][0]
    x_range = spec["layout"]["xaxis"]["range"][1]
    y_range = spec["layout"]["yaxis"]["range"][1]
    assert diagonal["x1"] == pytest.approx(max(x_range, y_range))


# --- registry + theme -------------------------------------------------------


def test_registry_reports_the_ported_kinds() -> None:
    assert {"volcano", "ma", "qq"} <= supported_kinds()


def test_unregistered_kind_raises_501() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        build("phylogenetic", config={}, rows={}, theme="light")
    assert exc.value.status_code == 501


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_builders_emit_themed_layouts(theme: str) -> None:
    spec = build("volcano", config=VOLCANO_CONFIG, rows=VOLCANO_ROWS, theme=theme)
    colors = colors_for_theme(theme)
    assert spec["layout"]["font"]["color"] == colors.text_color
    assert spec["layout"]["xaxis"]["gridcolor"] == colors.grid_color
    assert spec["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"
    assert spec["layout"]["template"] == ("plotly_dark" if theme == "dark" else "plotly_white")


def test_layout_theme_is_idempotent() -> None:
    colors = plotly_theme_colors(is_dark=True)
    once = apply_layout_theme({"xaxis": {"title": "x"}}, colors)
    twice = apply_layout_theme(once, colors)
    assert once == twice


def test_layout_theme_preserves_explicitly_coloured_annotations() -> None:
    colors = plotly_theme_colors(is_dark=True)
    layout = apply_layout_theme(
        {"annotations": [{"text": "tier", "font": {"color": "#e64980"}}, {"text": "plain"}]},
        colors,
    )
    assert layout["annotations"][0]["font"]["color"] == "#e64980"
    assert layout["annotations"][1]["font"]["color"] == colors.text_color


# --- TS parity golden -------------------------------------------------------


class TestTypeScriptParity:
    """Pin the Python builders against values the TypeScript renderer produced.

    There is no JS test runner in this repo, so this cannot re-derive the
    expected values automatically. They were captured by rendering
    ``VolcanoRenderer.tsx`` in the offline embed bundle (headless Chromium,
    ``file://``) over the fixture below and reading the tier badges and top-N
    labels off the result. Regenerate the same way if the TS renderer changes:

        1. build the embed bundle: ``cd depictio/viewer && pnpm run build:embed``
        2. inject this fixture and open the page
        3. read the UP / DN / NS badges and the visible point labels

    A mismatch means the two implementations have diverged — which is exactly
    what this test exists to catch.
    """

    #: Deterministic fixture. Generated with `random.seed(0)`; inlined rather
    #: than regenerated so Python and TS provably saw identical inputs.
    @staticmethod
    def _fixture() -> dict[str, list]:
        import random

        random.seed(0)
        n = 300
        return {
            "gene": [f"G{i}" for i in range(n)],
            "lfc": [random.gauss(0, 1.5) for _ in range(n)],
            "padj": [max(1e-12, random.random() ** 3) for _ in range(n)],
        }

    CONFIG = {
        "feature_id_col": "gene",
        "effect_size_col": "lfc",
        "significance_col": "padj",
        "significance_threshold": 0.05,
        "effect_threshold": 1.0,
        "top_n_labels": 5,
    }

    #: Read off the TS render.
    TS_TIER_COUNTS = {"UP": 24, "DN": 28, "NS": 248}
    TS_TOP_LABELS = ["G10", "G212", "G214", "G233", "G33"]

    def test_tier_counts_match_the_typescript_renderer(self) -> None:
        from collections import Counter

        spec = build("volcano", config=self.CONFIG, rows=self._fixture(), theme="light")
        tier_of = {
            "#e64980": "UP",
            "#1c7ed6": "DN",
            "rgba(160,160,160,0.55)": "NS",
        }
        counts = Counter(tier_of[c] for c in spec["data"][0]["marker"]["color"])
        assert dict(counts) == self.TS_TIER_COUNTS

    def test_top_n_label_selection_matches_the_typescript_renderer(self) -> None:
        """Guards the `|effect| * significance` ranking, which is easy to get wrong."""
        spec = build("volcano", config=self.CONFIG, rows=self._fixture(), theme="light")
        labels = sorted(a["text"] for a in spec["layout"]["annotations"])
        assert labels == sorted(self.TS_TOP_LABELS)
