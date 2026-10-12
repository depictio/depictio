"""A stored advanced-viz component must reach the builder that draws what it shows.

Main folded ``ma``/``qq`` into ``volcano``, ``enrichment`` into ``dot_plot`` and
``roc_pr_curve`` into ``pr_benchmark``, each with a ``view``. The builders are
still one per drawing, so the export has to read the view, and has to read it the
same way for a document saved before the merge (retired kind) and after it
(survivor + view). Getting this wrong exports a volcano for a tile showing an MA
plot, with a 200.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.services.advanced_viz.views import canonical_kind, plan_for


def _av(viz_kind: str, **config) -> dict:
    return {
        "component_type": "advanced_viz",
        "viz_kind": viz_kind,
        "wf_id": "w1",
        "dc_id": "d1",
        "config": {"viz_kind": viz_kind, **config},
    }


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("ma", "volcano"),
        ("qq", "volcano"),
        ("enrichment", "dot_plot"),
        ("roc_pr_curve", "pr_benchmark"),
        ("ancombc_differentials", "da_barplot"),
        ("volcano", "volcano"),
        (None, None),
    ],
)
def test_canonical_kind(stored: str | None, expected: str | None) -> None:
    assert canonical_kind(stored) == expected


class TestRetiredAndSurvivorAgree:
    """The two shapes a stored component can hold resolve to the same plan."""

    def test_retired_ma_and_volcano_on_ma_view(self) -> None:
        columns = {
            "feature_id_col": "gene",
            "avg_log_intensity_col": "A",
            "log2_fold_change_col": "M",
            "significance_col": "padj",
        }
        retired = plan_for(_av("ma", **columns))
        survivor = plan_for(_av("volcano", view="ma", effect_size_col="M", **columns))
        assert retired is not None and survivor is not None
        assert retired.kind == survivor.kind == "volcano"
        assert retired.builders == survivor.builders == ("ma",)

    def test_retired_roc_curve_and_pr_benchmark_on_roc_view(self) -> None:
        retired = plan_for(_av("roc_pr_curve", fpr_col="fpr"))
        survivor = plan_for(_av("pr_benchmark", view="roc", fpr_col="fpr"))
        assert retired is not None and survivor is not None
        assert retired.builders == survivor.builders == ("roc_pr_curve",)
        assert retired.controls["roc_pr_curve"]["mode"] == "roc"


class TestViews:
    def test_default_view_draws_with_the_survivors_own_builder(self) -> None:
        plan = plan_for(_av("volcano", feature_id_col="g", effect_size_col="e"))
        assert plan is not None
        assert plan.view == "volcano" and plan.builders == ("volcano",)

    def test_controls_pick_the_view(self) -> None:
        plan = plan_for(_av("volcano", p_value_col="p"), {"view": "qq", "show_ci": False})
        assert plan is not None
        assert plan.builders == ("qq",)
        assert plan.controls["qq"] == {"show_ci": False}, "`view` is consumed, the rest passed on"

    def test_unknown_view_falls_back_to_the_default(self) -> None:
        plan = plan_for(_av("pr_benchmark"), {"view": "nonsense"})
        assert plan is not None and plan.view == "pr"

    def test_ma_view_falls_back_to_the_effect_size_for_m(self) -> None:
        plan = plan_for(_av("volcano", view="ma", avg_log_intensity_col="A", effect_size_col="lfc"))
        assert plan is not None
        assert plan.config["log2_fold_change_col"] == "lfc"
        assert plan.source is None

    def test_ma_view_reads_its_own_table_when_the_volcano_has_no_a_column(self) -> None:
        plan = plan_for(_av("volcano", view="ma", ma_wf_id="w2", ma_dc_id="d2"))
        assert plan is not None
        assert plan.source == ("w2", "d2")
        assert plan.config["avg_log_intensity_col"] == "avg_log_intensity"

    def test_ma_table_needs_both_ids(self) -> None:
        """Same rule as `maTableOf` in deViews.ts."""
        plan = plan_for(_av("volcano", view="ma", ma_dc_id="d2", effect_size_col="lfc"))
        assert plan is not None and plan.source is None

    def test_qq_view_falls_back_to_the_significance_column(self) -> None:
        plan = plan_for(_av("volcano", view="qq", significance_col="pvalue"))
        assert plan is not None
        assert plan.config["p_value_col"] == "pvalue"

    def test_roc_view_stays_in_pr_space_without_an_fpr_column(self) -> None:
        plan = plan_for(_av("pr_benchmark", view="roc", threshold_col="q"))
        assert plan is not None
        assert plan.controls["roc_pr_curve"]["mode"] == "pr"

    def test_explicit_sweep_mode_wins(self) -> None:
        plan = plan_for(_av("pr_benchmark", view="roc", fpr_col="fpr"), {"mode": "threshold"})
        assert plan is not None
        assert plan.controls["roc_pr_curve"]["mode"] == "threshold"

    def test_both_overlays_the_sweep_on_the_points_in_pr_space(self) -> None:
        plan = plan_for(_av("pr_benchmark", view="both", fpr_col="fpr"))
        assert plan is not None
        assert plan.builders == ("pr_benchmark", "roc_pr_curve")
        assert plan.controls["roc_pr_curve"]["mode"] == "pr"

    def test_dot_plot_enrichment_view(self) -> None:
        plan = plan_for(_av("dot_plot", view="enrichment", term_col="term"))
        assert plan is not None and plan.builders == ("enrichment",)

    def test_kind_without_views(self) -> None:
        plan = plan_for(_av("manhattan"))
        assert plan is not None
        assert plan.view is None and plan.builders == ("manhattan",)

    def test_no_kind_at_all(self) -> None:
        assert plan_for({"component_type": "advanced_viz", "config": {}}) is None


class TestExportDrawsThePlan:
    """`_python_advanced_viz_spec` reads where the plan says and overlays its builders."""

    def _spec(self, component: dict, rows: dict, controls: dict | None = None):
        from unittest.mock import patch

        from depictio.api.v1.services.export.plotly_export import _python_advanced_viz_spec

        with patch(
            "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
            return_value={"rows": rows},
        ) as load:
            spec = _python_advanced_viz_spec(component, [], object(), None, controls)
        return spec, load.call_args.kwargs

    def test_both_view_carries_the_points_and_the_sweep(self) -> None:
        component = _av(
            "pr_benchmark",
            view="both",
            label_col="caller",
            threshold_col="q",
        )
        rows = {
            "caller": ["a", "b"],
            "recall": [0.8, 0.9],
            "precision": [0.9, 0.7],
            "f1": [0.85, 0.79],
            "q": [10, 20],
        }
        spec, kwargs = self._spec(component, rows)
        assert kwargs["viz_kind"] == "pr_benchmark", "the survivor picks the sampling policy"
        points_only, _ = self._spec(_av("pr_benchmark", label_col="caller"), rows)
        assert len(spec["data"]) > len(points_only["data"])

    def test_ma_view_reads_the_ma_table(self) -> None:
        component = _av("volcano", view="ma", ma_wf_id="w2", ma_dc_id="d2")
        rows = {
            "feature_id": ["g1", "g2"],
            "avg_log_intensity": [5.0, 7.0],
            "log2_fold_change": [1.5, -2.0],
            "significance": [0.01, 0.2],
        }
        spec, kwargs = self._spec(component, rows)
        assert (kwargs["wf_id"], kwargs["dc_id"]) == ("w2", "d2")
        assert spec["data"], "the MA builder drew from the MA table's columns"
