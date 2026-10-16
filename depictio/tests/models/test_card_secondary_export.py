"""A card's secondary strip and a table's row selection survive the export.

`from_full` once wrote none of them, so a dashboard exported and imported again
turned every breakdown, coverage, threshold, trend or attrition card back into a
plain vertical one, and lost its tables' row selection."""

import pytest

from depictio.models.models.dashboards import DashboardDataLite

CARD = {
    "component_type": "card",
    "tag": "kpi-samples",
    "workflow_tag": "ampliseq",
    "data_collection_tag": "metadata",
    "aggregation": "nunique",
    "column_name": "ID",
    "column_type": "object",
    "title": "Samples",
    "layout": {"x": 0, "y": 0, "w": 2, "h": 2},
}

STRIPS = {
    "composition": {"secondary_layout": "composition", "breakdown_col": "platform"},
    "top_n": {"secondary_layout": "top_n", "breakdown_col": "locality", "top_n_count": 2},
    "donut": {"secondary_layout": "donut", "breakdown_col": "locality"},
    "coverage": {"secondary_layout": "coverage", "coverage_max": 85.0},
    "threshold": {
        "secondary_layout": "threshold",
        "threshold_value": 0.05,
        "threshold_direction": "max",
        "threshold_warn": 0.1,
    },
    "trend": {"secondary_layout": "trend", "trend_col": "sampling_date"},
    "attrition": {"secondary_layout": "attrition", "attrition_cols": ["reads_in", "mapped"]},
}

TABLE = {
    "component_type": "table",
    "tag": "table-samples",
    "workflow_tag": "ampliseq",
    "data_collection_tag": "samplesheet",
    "title": "Samplesheet",
    "layout": {"x": 0, "y": 0, "w": 6, "h": 6},
}


def _dash(*components) -> DashboardDataLite:
    return DashboardDataLite(title="TREC", components=list(components))


def _round_trip(component: dict) -> dict:
    """The stored card of a dashboard exported to YAML and imported again."""
    exported = DashboardDataLite.from_full(_dash(component).to_full())
    reloaded = DashboardDataLite.from_yaml(exported.to_yaml())
    return reloaded.to_full()["stored_metadata"][0]


@pytest.mark.parametrize("name", STRIPS)
def test_the_secondary_strip_survives_the_round_trip(name):
    stored = _round_trip({**CARD, **STRIPS[name]})
    for key, value in STRIPS[name].items():
        assert stored[key] == value, key


@pytest.mark.parametrize("name", STRIPS)
def test_the_strip_is_exported_without_an_import_in_between(name):
    full = _dash({**CARD, **STRIPS[name]}).to_full()
    exported = DashboardDataLite.from_full(full).components[0]
    for key, value in STRIPS[name].items():
        assert getattr(exported, key) == value, key


def test_a_plain_card_exports_none_of_them():
    text = DashboardDataLite.from_full(_dash(CARD).to_full()).to_yaml()
    # the lite model writes its own defaults; none of the optional strip inputs appears
    for key in ("breakdown_col", "coverage_max", "trend_col", "threshold_value", "attrition_cols"):
        assert f"{key}:" not in text


def test_a_row_selecting_table_keeps_its_selection():
    stored = _round_trip({**TABLE, "row_selection_enabled": True, "row_selection_column": "ID"})
    assert stored["row_selection_enabled"] is True
    assert stored["row_selection_column"] == "ID"


def test_a_plain_table_exports_no_selection():
    full = _dash(TABLE).to_full()
    exported = DashboardDataLite.from_full(full).components[0]
    assert exported.row_selection_enabled is False
    assert exported.row_selection_column is None
