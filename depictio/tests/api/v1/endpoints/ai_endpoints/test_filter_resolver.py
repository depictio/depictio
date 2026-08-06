"""filter_resolver: widget matching, expression gating, quantile thresholds.

`load_deltatable_lite` is monkeypatched — no Delta/S3. The invariant under
test: only validated, resolvable filters come back; everything else
degrades to a warning string.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.endpoints.ai_endpoints import filter_resolver
from depictio.api.v1.endpoints.ai_endpoints.context import DashboardContext, FilterSummary
from depictio.api.v1.endpoints.ai_endpoints.schemas import FilterProposal, ThresholdSpec

WF_ID = "7" * 24
DC_ID = "6" * 24


@pytest.fixture()
def dashboard_ctx() -> DashboardContext:
    return DashboardContext(
        dashboard_id="d" * 24,
        figures=[],
        filters=[
            FilterSummary(
                component_id="widget-depth",
                component_type="RangeSlider",
                column="depth",
                value=None,
            )
        ],
    )


@pytest.fixture()
def patch_delta(monkeypatch):
    df = pl.DataFrame({"depth": list(range(1, 101))})  # 1..100

    def fake_load(**kwargs):
        return df.select(kwargs.get("select_columns") or df.columns)

    monkeypatch.setattr(filter_resolver, "load_deltatable_lite", fake_load)
    # Resolved from Mongo and passed as an argument to the loader, so it
    # runs even though the loader is faked.
    monkeypatch.setattr(
        filter_resolver,
        "init_data_for_dc",
        lambda dc_id: {str(dc_id): {"delta_location": "s3://fake", "dc_type": "table"}},
    )
    return df


def _resolve(proposals, ctx, active=None):
    return filter_resolver.resolve_proposals(
        proposals,
        dashboard_ctx=ctx,
        workflow_id=WF_ID,
        data_collection_id=DC_ID,
        active_filters=active,
    )


class TestSetWidget:
    def test_known_widget_passes(self, dashboard_ctx):
        resolved, warnings = _resolve(
            [FilterProposal(kind="set_widget", component_id="widget-depth", value=[10, 50])],
            dashboard_ctx,
        )
        assert warnings == []
        assert resolved[0].kind == "set_widget"
        assert resolved[0].component_id == "widget-depth"
        assert resolved[0].value == [10, 50]

    def test_unknown_widget_is_dropped_with_warning(self, dashboard_ctx):
        resolved, warnings = _resolve(
            [FilterProposal(kind="set_widget", component_id="nope", value=1)],
            dashboard_ctx,
        )
        assert resolved == []
        assert any("unknown component" in w for w in warnings)


class TestFilterExpr:
    def test_valid_expr_passes(self, dashboard_ctx):
        resolved, warnings = _resolve(
            [FilterProposal(kind="filter_expr", filter_expr="col('depth') >= 30")],
            dashboard_ctx,
        )
        assert warnings == []
        assert resolved[0].kind == "filter_expr"
        assert resolved[0].filter_expr == "col('depth') >= 30"
        assert resolved[0].dc_id == DC_ID

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os').system('rm -rf /')",
            "eval('1+1')",
            "col('x').__class__",
        ],
    )
    def test_dangerous_expr_is_dropped(self, dashboard_ctx, expr):
        resolved, warnings = _resolve(
            [FilterProposal(kind="filter_expr", filter_expr=expr)],
            dashboard_ctx,
        )
        assert resolved == []
        assert len(warnings) == 1


class TestThreshold:
    def test_top_3_percent_resolves_to_concrete_comparison(self, dashboard_ctx, patch_delta):
        resolved, warnings = _resolve(
            [
                FilterProposal(
                    kind="threshold",
                    threshold=ThresholdSpec(column="depth", q=0.97, op=">="),
                )
            ],
            dashboard_ctx,
        )
        assert warnings == []
        (entry,) = resolved
        assert entry.kind == "filter_expr"
        # Quantile(0.97, nearest) over 1..100 = 97.
        assert entry.filter_expr == "col('depth') >= 97.0"
        assert "top 3% of depth" in entry.description

    def test_bottom_5_percent_description(self, dashboard_ctx, patch_delta):
        resolved, _ = _resolve(
            [
                FilterProposal(
                    kind="threshold",
                    threshold=ThresholdSpec(column="depth", q=0.05, op="<="),
                )
            ],
            dashboard_ctx,
        )
        assert "bottom 5% of depth" in resolved[0].description

    def test_unknown_column_is_warning(self, dashboard_ctx, monkeypatch):
        def fake_load(**kwargs):
            raise Exception("column 'nope' not found")

        monkeypatch.setattr(filter_resolver, "load_deltatable_lite", fake_load)
        resolved, warnings = _resolve(
            [
                FilterProposal(
                    kind="threshold",
                    threshold=ThresholdSpec(column="nope", q=0.9, op=">="),
                )
            ],
            dashboard_ctx,
        )
        assert resolved == []
        assert len(warnings) == 1

    def test_quote_escaping_column_is_rejected(self, dashboard_ctx, patch_delta):
        resolved, warnings = _resolve(
            [
                FilterProposal(
                    kind="threshold",
                    threshold=ThresholdSpec(column="x') | col('y", q=0.9, op=">="),
                )
            ],
            dashboard_ctx,
        )
        assert resolved == []
        assert any("unsupported column name" in w for w in warnings)

    def test_active_filters_are_passed_to_loader(self, patch_delta, dashboard_ctx, monkeypatch):
        captured: dict = {}

        def fake_load(**kwargs):
            captured.update(kwargs)
            return pl.DataFrame({"depth": [1.0, 2.0, 3.0]})

        monkeypatch.setattr(filter_resolver, "load_deltatable_lite", fake_load)
        active = [{"metadata": {"interactive_component_type": "Select", "column_name": "qc"}}]
        _resolve(
            [
                FilterProposal(
                    kind="threshold",
                    threshold=ThresholdSpec(column="depth", q=0.5, op=">="),
                )
            ],
            dashboard_ctx,
            active=active,
        )
        assert captured["metadata"] == active


class TestMixedBatch:
    def test_one_bad_proposal_does_not_void_the_rest(self, dashboard_ctx):
        resolved, warnings = _resolve(
            [
                FilterProposal(kind="filter_expr", filter_expr="col('depth') > 10"),
                FilterProposal(kind="set_widget", component_id="ghost", value=1),
            ],
            dashboard_ctx,
        )
        assert len(resolved) == 1
        assert len(warnings) == 1
