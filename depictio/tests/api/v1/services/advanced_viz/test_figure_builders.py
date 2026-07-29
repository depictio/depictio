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


# --- stacked_taxonomy -------------------------------------------------------

TAXONOMY_CONFIG = {
    "sample_id_col": "sample",
    "taxon_col": "taxon",
    "rank_col": "rank",
    "abundance_col": "abundance",
    "top_n": 2,
    "normalise_to_one": False,
}

TAXONOMY_ROWS = {
    # Two samples at genus rank plus one row at a different rank that must be
    # excluded, and three taxa so top_n=2 forces one into "Other".
    "sample": ["s1", "s1", "s1", "s2", "s2", "s2", "s1"],
    "taxon": ["Bacteroides", "Prevotella", "Rare", "Bacteroides", "Prevotella", "Rare", "Ignored"],
    "rank": ["genus", "genus", "genus", "genus", "genus", "genus", "phylum"],
    "abundance": [10.0, 6.0, 1.0, 4.0, 8.0, 2.0, 999.0],
}


def _series(spec: dict) -> dict[str, list[float]]:
    return {trace["name"]: trace["y"] for trace in spec["data"]}


def test_stacked_taxonomy_filters_to_the_active_rank() -> None:
    """The phylum row carries abundance 999 and must not reach any trace."""
    spec = build("stacked_taxonomy", config=TAXONOMY_CONFIG, rows=TAXONOMY_ROWS, theme="light")
    assert "Ignored" not in _series(spec)
    assert max(max(ys) for ys in _series(spec).values()) < 999


def test_stacked_taxonomy_lumps_below_top_n_into_other() -> None:
    spec = build("stacked_taxonomy", config=TAXONOMY_CONFIG, rows=TAXONOMY_ROWS, theme="light")
    series = _series(spec)
    assert set(series) == {"Bacteroides", "Prevotella", "Other"}
    # "Rare" totals 1 + 2 across the two samples and is the only lumped taxon.
    assert series["Other"] == [1.0, 2.0]


def test_stacked_taxonomy_ranks_top_n_globally_not_per_sample() -> None:
    """Prevotella loses sample s1 but wins overall, so it must survive top-N."""
    spec = build("stacked_taxonomy", config=TAXONOMY_CONFIG, rows=TAXONOMY_ROWS, theme="light")
    assert "Prevotella" in _series(spec)


def test_stacked_taxonomy_normalise_locks_the_axis_to_percent() -> None:
    """Without the explicit range the toggle is invisible on pre-normalised data."""
    config = {**TAXONOMY_CONFIG, "normalise_to_one": True}
    spec = build("stacked_taxonomy", config=config, rows=TAXONOMY_ROWS, theme="light")
    assert spec["layout"]["yaxis"]["range"] == [0, 1]
    assert spec["layout"]["yaxis"]["tickformat"] == ".0%"
    for values in _series(spec).values():
        assert all(0.0 <= v <= 1.0 for v in values)


def test_stacked_taxonomy_is_a_stacked_bar_chart() -> None:
    spec = build("stacked_taxonomy", config=TAXONOMY_CONFIG, rows=TAXONOMY_ROWS, theme="light")
    assert spec["layout"]["barmode"] == "stack"
    assert {trace["type"] for trace in spec["data"]} == {"bar"}


# --- manhattan --------------------------------------------------------------

MANHATTAN_CONFIG = {
    "chr_col": "chrom",
    "pos_col": "pos",
    "score_col": "score",
    "feature_col": "rsid",
    "score_threshold": 5.0,
    "top_n_labels": 1,
}

MANHATTAN_ROWS = {
    # Deliberately out of natural order so the sort is exercised: X before 2.
    "chrom": ["chr1", "chrX", "chr2", "chr1"],
    "pos": [100.0, 50.0, 75.0, 900.0],
    "score": [7.0, 2.0, 6.0, 1.0],
    "rsid": ["rs1", "rs2", "rs3", "rs4"],
}


def test_manhattan_orders_chromosomes_naturally() -> None:
    """chr2 must precede chrX, which string sorting gets wrong."""
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    assert spec["layout"]["xaxis"]["ticktext"] == ["1", "2", "X"]


def test_manhattan_offsets_positions_onto_one_axis() -> None:
    """Two chr1 points keep their spacing; chr2 and chrX start beyond chr1's end."""
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    xs = spec["data"][0]["x"]
    assert xs[0] == 100.0 and xs[3] == 900.0, "chr1 sits at offset 0"
    assert xs[2] > 900.0, "chr2 must start after chr1's span"
    assert xs[1] > xs[2], "chrX comes last"


def test_manhattan_colours_by_tier_when_a_threshold_is_set() -> None:
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    colors = spec["data"][0]["marker"]["color"]
    assert colors[0] == "#0ca678", "score 7 >= 5 is ABOVE"
    assert colors[2] == "#0ca678", "score 6 >= 5 is ABOVE"
    assert colors[1] == "rgba(160,160,160,0.45)", "sub-threshold dims under highlight=above"


def test_manhattan_draws_the_threshold_as_a_horizontal_line() -> None:
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    lines = [s for s in spec["layout"]["shapes"] if s["type"] == "line"]
    assert len(lines) == 1
    assert lines[0]["y0"] == lines[0]["y1"] == 5.0
    assert lines[0]["xref"] == "paper", "the line must span the plot, not a data range"


def test_manhattan_labels_the_highest_scoring_hit() -> None:
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    assert [a["text"] for a in spec["layout"]["annotations"]] == ["rs1"]


def test_manhattan_labels_the_lowest_when_highlighting_below() -> None:
    """Sort direction follows the highlight target; easy to leave inverted."""
    spec = build(
        "manhattan",
        config=MANHATTAN_CONFIG,
        rows=MANHATTAN_ROWS,
        theme="light",
        controls={"highlight": "below"},
    )
    assert [a["text"] for a in spec["layout"]["annotations"]] == ["rs4"]


def test_manhattan_clamps_bounded_score_kinds() -> None:
    config = {**MANHATTAN_CONFIG, "score_kind": "allele frequency"}
    spec = build("manhattan", config=config, rows=MANHATTAN_ROWS, theme="light")
    assert spec["layout"]["yaxis"]["range"] == [0, 1.05]


def test_manhattan_avoids_webgl_trace_types() -> None:
    """An exported spec may be rendered where WebGL is unavailable."""
    spec = build("manhattan", config=MANHATTAN_CONFIG, rows=MANHATTAN_ROWS, theme="light")
    assert all(not str(t.get("type", "")).endswith("gl") for t in spec["data"])


# --- embedding --------------------------------------------------------------

EMBEDDING_CONFIG = {
    "sample_id_col": "sample",
    "dim_1_col": "dim_1",
    "dim_2_col": "dim_2",
    "cluster_col": "cluster",
    "color_col": "numeric_coord",
    "compute_method": "pca",
}

EMBEDDING_ROWS = {
    "sample": ["a", "b", "c", "d"],
    "dim_1": [1.0, 2.0, 3.0, 4.0],
    "dim_2": [4.0, 3.0, 2.0, 1.0],
    "cluster": ["ctrl", "ctrl", "treat", "treat"],
    "numeric_coord": [0.1, 0.2, 0.3, 0.4],
}


def test_embedding_prefers_cluster_col_over_color_col() -> None:
    """The TSX default is `cluster_col || color_col`. Reversing it silently
    swaps a categorical legend for a continuous colorbar."""
    spec = build("embedding", config=EMBEDDING_CONFIG, rows=EMBEDDING_ROWS, theme="light")
    assert sorted(t["name"] for t in spec["data"]) == ["ctrl", "treat"]
    assert spec["layout"]["showlegend"] is True


def test_embedding_splits_categories_into_separate_traces() -> None:
    spec = build("embedding", config=EMBEDDING_CONFIG, rows=EMBEDDING_ROWS, theme="light")
    by_name = {t["name"]: t for t in spec["data"]}
    assert by_name["ctrl"]["x"] == [1.0, 2.0]
    assert by_name["treat"]["x"] == [3.0, 4.0]


def test_embedding_colours_categories_off_the_universe() -> None:
    """Same rule as palette.stable_color_map: filtering must not re-map colours."""
    spec = build("embedding", config=EMBEDDING_CONFIG, rows=EMBEDDING_ROWS, theme="light")
    colors = {t["name"]: t["marker"]["color"] for t in spec["data"]}
    assert colors["ctrl"] == "#1f77b4"
    assert colors["treat"] == "#ff7f0e"


def test_embedding_uses_a_colorbar_for_numeric_bindings() -> None:
    config = {k: v for k, v in EMBEDDING_CONFIG.items() if k != "cluster_col"}
    spec = build("embedding", config=config, rows=EMBEDDING_ROWS, theme="light")
    assert len(spec["data"]) == 1
    marker = spec["data"][0]["marker"]
    assert marker["colorscale"] == "Spectral"
    assert marker["color"] == [0.1, 0.2, 0.3, 0.4]
    assert spec["layout"]["showlegend"] is False


def test_embedding_falls_back_to_literal_dim_keys() -> None:
    """Live-compute mode returns vectors keyed `dim_1`/`dim_2` with no config
    bindings; without the fallback the figure renders empty."""
    config = {"sample_id_col": "sample", "cluster_col": "cluster"}
    spec = build("embedding", config=config, rows=EMBEDDING_ROWS, theme="light")
    assert sum(len(t["x"]) for t in spec["data"]) == 4


# --- da_barplot -------------------------------------------------------------

DA_CONFIG = {
    "feature_id_col": "feature",
    "contrast_col": "contrast",
    "lfc_col": "lfc",
    "significance_col": "padj",
    "significance_threshold": 0.05,
    "top_n": 3,
}

DA_ROWS = {
    "feature": ["f1", "f2", "f3", "f4", "other"],
    "contrast": ["A_vs_B"] * 4 + ["C_vs_D"],
    "lfc": [3.0, -2.0, 0.5, 4.0, 9.0],
    "padj": [0.01, 0.001, 0.9, 0.5, 0.01],
}


def test_da_barplot_renders_one_contrast_and_names_it() -> None:
    """No tabs in an export, so the contrast must be on the figure itself."""
    spec = build("da_barplot", config=DA_CONFIG, rows=DA_ROWS, theme="light")
    assert spec["layout"]["title"]["text"] == "A_vs_B"
    assert "other" not in spec["data"][0]["y"], "the C_vs_D row belongs to another panel"


def test_da_barplot_honours_an_explicit_contrast() -> None:
    spec = build(
        "da_barplot",
        config=DA_CONFIG,
        rows=DA_ROWS,
        theme="light",
        controls={"contrast": "C_vs_D"},
    )
    assert spec["layout"]["title"]["text"] == "C_vs_D"
    assert spec["data"][0]["y"] == ["other"]


def test_da_barplot_selects_by_magnitude_then_orders_signed() -> None:
    """Top-N by |lfc| (so 0.5 drops), then ascending signed for a diverging ladder."""
    spec = build("da_barplot", config=DA_CONFIG, rows=DA_ROWS, theme="light")
    assert spec["data"][0]["x"] == [-2.0, 3.0, 4.0]


def test_da_barplot_fades_non_significant_bars() -> None:
    spec = build("da_barplot", config=DA_CONFIG, rows=DA_ROWS, theme="light")
    by_label = dict(zip(spec["data"][0]["y"], spec["data"][0]["marker"]["color"]))
    assert by_label["f1"] == "#1f77b4", "significant positive"
    assert by_label["f2"] == "#d62728", "significant negative"
    assert by_label["f4"] == "rgba(127,127,127,0.45)", "padj 0.5 is not significant"


def test_da_barplot_treats_missing_significance_as_not_significant() -> None:
    rows = {**DA_ROWS, "padj": [None, 0.001, 0.9, 0.5, 0.01]}
    spec = build("da_barplot", config=DA_CONFIG, rows=rows, theme="light")
    by_label = dict(zip(spec["data"][0]["y"], spec["data"][0]["marker"]["color"]))
    assert by_label["f1"] == "rgba(127,127,127,0.45)"


# --- enrichment -------------------------------------------------------------

ENRICH_CONFIG = {
    "term_col": "term",
    "nes_col": "nes",
    "padj_col": "padj",
    "gene_count_col": "n_genes",
    "padj_threshold": 0.05,
    "top_n": 3,
}

ENRICH_ROWS = {
    "term": ["most_sig", "mid", "least_sig", "filtered_out"],
    "nes": [1.0, -2.5, 2.0, 3.0],
    "padj": [0.0001, 0.001, 0.01, 0.9],
    "n_genes": [10, 40, 20, 99],
}


def test_enrichment_drops_terms_above_the_padj_threshold() -> None:
    spec = build("enrichment", config=ENRICH_CONFIG, rows=ENRICH_ROWS, theme="light")
    assert "filtered_out" not in spec["data"][0]["y"]


def test_enrichment_selects_by_significance_then_orders_by_nes() -> None:
    """Plotly draws the first category at the bottom, so NES ascending puts
    positive enrichment at the top."""
    spec = build("enrichment", config=ENRICH_CONFIG, rows=ENRICH_ROWS, theme="light")
    assert spec["data"][0]["y"] == ["mid", "most_sig", "least_sig"]
    assert spec["data"][0]["x"] == [-2.5, 1.0, 2.0]


def test_enrichment_scales_marker_size_by_gene_count() -> None:
    spec = build("enrichment", config=ENRICH_CONFIG, rows=ENRICH_ROWS, theme="light")
    sizes = dict(zip(spec["data"][0]["y"], spec["data"][0]["marker"]["size"]))
    assert sizes["mid"] > sizes["least_sig"] > sizes["most_sig"]


def test_enrichment_colours_by_significance_by_default() -> None:
    spec = build("enrichment", config=ENRICH_CONFIG, rows=ENRICH_ROWS, theme="light")
    marker = spec["data"][0]["marker"]
    assert marker["colorbar"]["title"]["text"] == "-log10(padj)"
    colors = dict(zip(spec["data"][0]["y"], marker["color"]))
    assert colors["most_sig"] == pytest.approx(4.0), "padj 1e-4 -> -log10 = 4"


def test_enrichment_nes_sign_mode_pins_the_colour_domain() -> None:
    """A two-bucket scale must not auto-fit, or the boundary drifts off zero."""
    spec = build(
        "enrichment",
        config=ENRICH_CONFIG,
        rows=ENRICH_ROWS,
        theme="light",
        controls={"color_by": "nes_sign"},
    )
    marker = spec["data"][0]["marker"]
    assert (marker["cmin"], marker["cmax"]) == (-1, 1)
    assert marker["colorbar"]["ticktext"] == ["down", "up"]


def test_enrichment_survives_a_zero_padj() -> None:
    """-log10(0) is infinity and would serialise as invalid JSON."""
    rows = {**ENRICH_ROWS, "padj": [0.0, 0.001, 0.01, 0.9]}
    spec = build("enrichment", config=ENRICH_CONFIG, rows=rows, theme="light")
    assert all(math.isfinite(c) for c in spec["data"][0]["marker"]["color"])


def test_enrichment_reports_an_empty_result_rather_than_an_empty_figure() -> None:
    config = {**ENRICH_CONFIG, "padj_threshold": 1e-9}
    spec = build("enrichment", config=config, rows=ENRICH_ROWS, theme="light")
    assert spec["data"] == []
    assert "No terms" in spec["layout"]["annotations"][0]["text"]


# --- sunburst ---------------------------------------------------------------

SUNBURST_CONFIG = {
    "rank_cols": ["kingdom", "phylum", "genus"],
    "abundance_col": "abundance",
}

SUNBURST_ROWS = {
    # "shared" appears under two different phyla and must stay two nodes.
    "kingdom": ["Bacteria", "Bacteria", "Bacteria"],
    "phylum": ["Firmicutes", "Bacteroidetes", "Firmicutes"],
    "genus": ["shared", "shared", "unique"],
    "abundance": [10.0, 5.0, 3.0],
}


def test_sunburst_accumulates_leaf_values_into_every_ancestor() -> None:
    spec = build("sunburst", config=SUNBURST_CONFIG, rows=SUNBURST_ROWS, theme="light")
    values = dict(zip(spec["data"][0]["ids"], spec["data"][0]["values"]))
    assert values["Bacteria"] == 18.0
    assert values["Bacteria | Firmicutes"] == 13.0
    assert values["Bacteria | Bacteroidetes"] == 5.0


def test_sunburst_keys_nodes_by_path_not_label() -> None:
    """Same genus under two phyla must not merge into one slice."""
    spec = build("sunburst", config=SUNBURST_CONFIG, rows=SUNBURST_ROWS, theme="light")
    ids = spec["data"][0]["ids"]
    assert "Bacteria | Firmicutes | shared" in ids
    assert "Bacteria | Bacteroidetes | shared" in ids


def test_sunburst_declares_branchvalues_total() -> None:
    """Without this Plotly re-sums children and inflates the inner rings."""
    spec = build("sunburst", config=SUNBURST_CONFIG, rows=SUNBURST_ROWS, theme="light")
    assert spec["data"][0]["branchvalues"] == "total"


def test_sunburst_links_children_to_their_parent_path() -> None:
    spec = build("sunburst", config=SUNBURST_CONFIG, rows=SUNBURST_ROWS, theme="light")
    trace = spec["data"][0]
    parents = dict(zip(trace["ids"], trace["parents"]))
    assert parents["Bacteria"] == ""
    assert parents["Bacteria | Firmicutes"] == "Bacteria"
    assert parents["Bacteria | Firmicutes | shared"] == "Bacteria | Firmicutes"


def test_sunburst_stops_at_a_null_rank() -> None:
    """A row with a missing mid rank must not fabricate a deeper node."""
    rows = {**SUNBURST_ROWS, "phylum": ["Firmicutes", None, "Firmicutes"]}
    spec = build("sunburst", config=SUNBURST_CONFIG, rows=rows, theme="light")
    assert not any(i.startswith("Bacteria | None") for i in spec["data"][0]["ids"])


def test_sunburst_needs_two_ranks() -> None:
    config = {**SUNBURST_CONFIG, "rank_cols": ["kingdom"]}
    spec = build("sunburst", config=config, rows=SUNBURST_ROWS, theme="light")
    assert spec["data"] == []
    assert "at least two rank columns" in spec["layout"]["annotations"][0]["text"]
