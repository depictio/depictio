"""Live values in a text tile: `values:` and the `{{name}}` / `{{param:KEY}}` placeholders.

The model's rules (names, placeholders the viewer can print, declared and used,
`weight` and `format`), the YAML round trip (the ids the import resolves never
reach a YAML), and the dashboard-level validation that now covers text tiles.
"""

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import (
    TEXT_VALUE_AGGREGATIONS,
    CardLiteComponent,
    TextLiteComponent,
    TextValueSpec,
)
from depictio.models.components.text import TextComponent
from depictio.models.models.dashboards import DashboardDataLite, exportable_text_values

TOP = {"dc": "rel_abundance", "column": "Phylum", "aggregation": "top", "weight": "abundance"}
SHARE = {**TOP, "aggregation": "top_share", "format": "percent"}
MEDIAN = {"dc": "alpha", "column": "shannon", "aggregation": "median", "format": "decimals:2"}


def _text(body: str, values: dict | None = None, title: str = "") -> TextLiteComponent:
    return TextLiteComponent(tag="t", title=title, body=body, values=values)


class TestTextValueSpec:
    def test_card_aggregations_and_the_category_ones(self):
        assert {"count", "nunique", "median", "mode", "top", "top_share"} <= set(
            TEXT_VALUE_AGGREGATIONS
        )
        assert "box_plot_stats" not in TEXT_VALUE_AGGREGATIONS

    def test_unknown_aggregation(self):
        with pytest.raises(ValidationError, match="is not one of"):
            TextValueSpec(dc="d", column="c", aggregation="biggest")

    def test_weight_only_with_top(self):
        TextValueSpec(**TOP)
        TextValueSpec(**{**TOP, "weight": None, "aggregation": "top_share"})
        with pytest.raises(ValidationError, match="`weight` only applies"):
            TextValueSpec(dc="d", column="c", aggregation="sum", weight="w")

    @pytest.mark.parametrize("fmt", ["percent", "integer", "si", "decimals:0", "decimals:6"])
    def test_formats(self, fmt):
        TextValueSpec(dc="d", column="c", aggregation="sum", format=fmt)

    @pytest.mark.parametrize("fmt", ["decimals:7", "decimals", "pct", "Percent"])
    def test_bad_formats(self, fmt):
        with pytest.raises(ValidationError, match="format"):
            TextValueSpec(dc="d", column="c", aggregation="sum", format=fmt)

    def test_filter_expr_is_validated_like_a_cards(self):
        TextValueSpec(dc="d", column="id", aggregation="nunique", filter_expr="col('q') < 0.05")
        with pytest.raises(ValidationError):
            TextValueSpec(
                dc="d", column="id", aggregation="nunique", filter_expr="__import__('os')"
            )

    def test_unknown_keys_are_refused(self):
        with pytest.raises(ValidationError):
            TextValueSpec(dc="d", column="c", aggregation="sum", dc_id="abc")


class TestTextPlaceholders:
    def test_declared_and_used(self):
        comp = _text("- **{{share}}** are {{top}}", {"top": TOP, "share": SHARE})
        assert set(comp.values or {}) == {"top", "share"}

    def test_title_counts_as_use(self):
        _text("", {"shannon": MEDIAN}, title="Median Shannon {{shannon}}")

    def test_params_need_no_declaration(self):
        _text("Classified with {{param:dada_ref_taxonomy}} ({{param:a.b-c_1}})")

    def test_undeclared_name(self):
        with pytest.raises(ValidationError, match="not a declared value"):
            _text("{{top}}")

    def test_declared_but_unused(self):
        with pytest.raises(ValidationError, match="declared but not used"):
            _text("{{top}}", {"top": TOP, "shannon": MEDIAN})

    @pytest.mark.parametrize(
        "placeholder",
        ["{{ top }}", "{{top }}", "{{Top}}", "{{1x}}", "{{param:}}", "{{param:a b}}", "{{}}"],
    )
    def test_what_the_viewer_would_print_raw_is_refused(self, placeholder):
        with pytest.raises(ValidationError, match="not a placeholder the viewer prints"):
            _text(f"x {placeholder} {{{{top}}}}", {"top": TOP})

    @pytest.mark.parametrize("name", ["Top", "1st", "a_name_far_too_long", "a-b"])
    def test_bad_names(self, name):
        with pytest.raises(ValidationError, match="must match"):
            _text(f"{{{{{name}}}}}", {name: TOP})

    def test_twelve_characters_is_the_longest_name(self):
        _text("{{abcdefghijkl}}", {"abcdefghijkl": TOP})


class TestCardsStillRefuseTop:
    @pytest.mark.parametrize("agg", ["top", "top_share"])
    def test_hero_and_secondary(self, agg):
        with pytest.raises(ValidationError, match="only available to a text tile"):
            CardLiteComponent(aggregation=agg, column_name="c")
        with pytest.raises(ValidationError, match="only available to a text tile"):
            CardLiteComponent(aggregation="count", aggregations=[agg], column_name="c")


class TestDashboardValidation:
    def test_text_is_in_the_component_type_map(self):
        assert DashboardDataLite._COMPONENT_TYPE_MAP["text"] is TextLiteComponent

    def test_a_bad_text_tile_fails_the_dashboard(self):
        ok, errors = DashboardDataLite.validate_yaml(
            "title: T\ncomponents:\n  - component_type: text\n    tag: intro\n    body: '{{x}}'\n"
        )
        assert not ok
        assert errors[0]["tag"] == "intro"
        assert "not a declared value" in errors[0]["msg"]


class TestRoundTrip:
    YAML = """
title: T
components:
  - component_type: text
    tag: findings
    values:
      top: {dc: rel_abundance, column: Phylum, aggregation: top, weight: abundance}
      shannon: {dc: alpha, column: shannon, aggregation: median, format: "decimals:2"}
    body: |
      - The dominant phylum is {{top}}
      - Median Shannon {{shannon}}, reference {{param:dada_ref_taxonomy}}
"""

    def test_to_full_carries_the_specs_without_unset_fields(self):
        full = DashboardDataLite.from_yaml(self.YAML).to_full()
        values = full["stored_metadata"][0]["values"]
        assert values == {
            "top": TOP,
            "shannon": MEDIAN,
        }

    def test_export_drops_the_resolved_ids(self):
        full = DashboardDataLite.from_yaml(self.YAML).to_full()
        full["stored_metadata"][0]["values"]["top"].update(dc_id="d1", wf_id="w1")
        lite = DashboardDataLite.from_full(full)
        out = lite.to_yaml()
        assert "dc_id" not in out and "wf_id" not in out
        again = DashboardDataLite.from_yaml(out).to_full()["stored_metadata"][0]
        assert again["values"] == {"top": TOP, "shannon": MEDIAN}
        assert again["body"] == full["stored_metadata"][0]["body"]

    def test_values_are_written_before_the_body(self):
        out = DashboardDataLite.from_yaml(self.YAML).to_yaml()
        assert out.index("values:") < out.index("body:")

    def test_exportable_values_helper(self):
        assert exportable_text_values(None) is None
        assert exportable_text_values({}) is None
        assert exportable_text_values({"a": {**TOP, "dc_id": None, "filter_expr": None}}) == {
            "a": TOP
        }

    def test_the_stored_component_takes_the_resolved_ids(self):
        comp = TextComponent(
            body="{{top}}", values={"top": {**TOP, "dc_id": "64b0c0ffee00000000000001"}}
        )
        assert comp.values is not None
        assert comp.values["top"].dc_id == "64b0c0ffee00000000000001"
        assert comp.values["top"].wf_id is None
