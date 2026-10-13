"""A card's number `format`: the vocabulary it shares with a text tile's live
values, the rules against `decimals` and counts, and the round trips (lite to
full and back, YAML, the MVP export)."""

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import CardLiteComponent, TextValueSpec
from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.yaml_serialization.mvp_format import dashboard_to_yaml_mvp

GOOD = ["percent", "integer", "si", "decimals:0", "decimals:6"]
BAD = ["decimals:7", "decimals", "pct", "Percent", "percent ", "", 2]

RATE = {
    "component_type": "card",
    "tag": "kpi-mapped",
    "workflow_tag": "nf-core/rnaseq",
    "data_collection_tag": "qc",
    "aggregation": "median",
    "column_name": "mapped_rate",
    "column_type": "float64",
    "title": "Mapped",
    "layout": {"x": 0, "y": 0, "w": 2, "h": 2},
}


def _card(**kw) -> CardLiteComponent:
    return CardLiteComponent(**{**RATE, **kw})


def _dash(*components) -> DashboardDataLite:
    return DashboardDataLite(title="QC", components=list(components))


class TestVocabulary:
    @pytest.mark.parametrize("fmt", GOOD)
    def test_accepts_each_form(self, fmt):
        assert _card(format=fmt).format == fmt

    @pytest.mark.parametrize("fmt", GOOD)
    def test_accepts_each_form_in_the_display_block(self, fmt):
        _dash({**RATE, "display": {"format": fmt}})

    @pytest.mark.parametrize("fmt", BAD)
    def test_rejects_anything_else(self, fmt):
        with pytest.raises(ValidationError):
            _card(format=fmt)

    @pytest.mark.parametrize("fmt", BAD)
    def test_rejects_anything_else_in_the_display_block(self, fmt):
        with pytest.raises(ValidationError, match="format"):
            _dash({**RATE, "display": {"format": fmt}})

    @pytest.mark.parametrize("fmt", GOOD + BAD)
    def test_same_vocabulary_as_a_text_value(self, fmt):
        def ok(build) -> bool:
            try:
                build()
            except ValidationError:
                return False
            return True

        card = ok(lambda: _card(format=fmt))
        text = ok(lambda: TextValueSpec(dc="d", column="c", aggregation="median", format=fmt))
        assert card == text

    def test_unset_by_default(self):
        assert _card().format is None


class TestRules:
    def test_format_and_decimals_together_are_refused(self):
        with pytest.raises(ValidationError, match="not both"):
            _card(format="percent", decimals=1)

    def test_the_pair_is_refused_inside_the_display_block_too(self):
        with pytest.raises(ValidationError, match="not both"):
            _dash({**RATE, "display": {"format": "si", "decimals": 1}})
        with pytest.raises(ValidationError, match="not both"):
            _dash({**RATE, "format": "si", "display": {"decimals": 0}})

    @pytest.mark.parametrize("agg", ["count", "nunique"])
    def test_percent_on_a_count_is_refused(self, agg):
        with pytest.raises(ValidationError, match="0-1 fraction"):
            _card(aggregation=agg, column_type="object", format="percent")

    @pytest.mark.parametrize("fmt", ["integer", "si", "decimals:0"])
    def test_a_count_takes_the_other_formats(self, fmt):
        assert _card(aggregation="count", format=fmt).format == fmt


class TestRoundTrip:
    @pytest.mark.parametrize("fmt", GOOD)
    def test_display_block_reaches_the_stored_card_and_back(self, fmt):
        card = {**RATE, "display": {"format": fmt, "caption": "median across samples"}}
        full = _dash(card).to_full()
        assert full["stored_metadata"][0]["format"] == fmt
        exported = DashboardDataLite.from_full(full).components[0]
        assert exported.display == {"format": fmt, "caption": "median across samples"}

    def test_top_level_field_reaches_the_stored_card(self):
        full = _dash({**RATE, "format": "si"}).to_full()
        assert full["stored_metadata"][0]["format"] == "si"

    def test_survives_yaml_export_and_import(self):
        dash = _dash({**RATE, "display": {"format": "percent"}})
        exported = DashboardDataLite.from_full(dash.to_full())
        text = exported.to_yaml()
        assert "format: percent" in text
        reloaded = DashboardDataLite.from_yaml(text)
        assert reloaded.to_full()["stored_metadata"][0]["format"] == "percent"

    def test_unset_is_left_out(self):
        full = _dash(RATE).to_full()
        assert "format" not in full["stored_metadata"][0]
        exported = DashboardDataLite.from_full(full)
        assert "format" not in exported.to_yaml()

    def test_decimals_zero_survives_export(self):
        full = _dash({**RATE, "display": {"decimals": 0}}).to_full()
        assert full["stored_metadata"][0]["decimals"] == 0
        assert DashboardDataLite.from_full(full).components[0].display == {"decimals": 0}

    def test_mvp_export_keeps_it_with_the_card_styling(self):
        full = _dash({**RATE, "display": {"format": "si"}}).to_full()
        mvp = dashboard_to_yaml_mvp(full)
        assert mvp["components"][0]["styling"]["format"] == "si"
