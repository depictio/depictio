"""Unit tests for the prompt-side dashboard context."""

from depictio.api.v1.endpoints.ai_endpoints.context import DashboardContext, FilterSummary


def _ctx() -> DashboardContext:
    return DashboardContext(
        dashboard_id="d1",
        figures=[],
        filters=[
            FilterSummary(
                component_id="w-species",
                component_type="interactive",
                column="species",
                value=None,
                interactive_component_type="MultiSelect",
            ),
            FilterSummary(
                component_id="w-mass",
                component_type="interactive",
                column="body_mass_g",
                value=[2700, 6300],
                interactive_component_type="RangeSlider",
            ),
        ],
    )


class TestWithActiveFilters:
    def test_no_active_filters_is_identity(self):
        ctx = _ctx()
        assert ctx.with_active_filters(None) is ctx
        assert ctx.with_active_filters([]) is ctx

    def test_widget_value_overlays_stored_default(self):
        out = _ctx().with_active_filters(
            [{"index": "w-species", "value": ["Gentoo"], "column_name": "species"}]
        )
        by_id = {f.component_id: f for f in out.filters}
        assert by_id["w-species"].value == ["Gentoo"]
        # Untouched widgets keep their stored value.
        assert by_id["w-mass"].value == [2700, 6300]
        assert "w-species (interactive, col=species): ['Gentoo']" in out.filters_block()

    def test_cleared_widget_reads_as_unset(self):
        out = _ctx().with_active_filters(
            [{"index": "w-mass", "value": None, "column_name": "body_mass_g"}]
        )
        assert {f.component_id: f.value for f in out.filters}["w-mass"] is None

    def test_expression_only_filter_is_appended(self):
        out = _ctx().with_active_filters(
            [
                {
                    "index": "ai-abc-0",
                    "value": True,
                    "source": "ai_prompt",
                    "filter_expr": "pl.col('island') == 'Biscoe'",
                    "metadata": {"filter_expr": "pl.col('island') == 'Biscoe'"},
                }
            ]
        )
        assert len(out.filters) == 3
        extra = out.filters[-1]
        assert extra.component_type == "filter_expr"
        assert extra.value == "pl.col('island') == 'Biscoe'"
        assert "filter_expr" in out.filters_block()

    def test_original_context_is_not_mutated(self):
        ctx = _ctx()
        ctx.with_active_filters(
            [{"index": "w-species", "value": ["Adelie"], "column_name": "species"}]
        )
        assert ctx.filters[0].value is None
