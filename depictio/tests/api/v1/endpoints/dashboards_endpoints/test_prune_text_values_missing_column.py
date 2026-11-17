"""A text line citing a column its collection does not carry is taken out at import.

An optional sheet column (a donor template, a reference amplicon) leaves the
column out of the hub when the run has none. The line that cites it would
print a dash or a meaningless zero, so it goes with its data.
"""

from unittest.mock import patch

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes

DC_ID = "64b000000000000000000001"


def _tile(values: dict, body: str) -> dict:
    return {
        "component_type": "text",
        "index": "study",
        "values": {
            n: {"dc": "samples", "dc_id": DC_ID, "wf_id": "w", **v} for n, v in values.items()
        },
        "body": body,
    }


def _prune(tile: dict, columns: set[str] | None) -> bool:
    with (
        patch.object(dash_routes, "_dc_column_names", return_value=columns),
        patch.object(dash_routes, "_component_has_data", return_value=True),
    ):
        return dash_routes._prune_unresolved_text_values(tile, {})


BODY = "### The study\n- **Libraries** {{libs}}\n- **Amplicon** {{amp}} bp\n"
VALUES = {
    "libs": {"column": "sample", "aggregation": "nunique"},
    "amp": {"column": "amplicon_length", "aggregation": "median"},
}


def test_a_line_reading_an_absent_column_is_removed():
    tile = _tile(VALUES, BODY)
    assert _prune(tile, {"sample", "protospacer"}) is True
    assert "Amplicon" not in tile["body"]
    assert "Libraries" in tile["body"]
    assert set(tile["values"]) == {"libs"}


def test_a_column_the_collection_carries_keeps_its_line():
    tile = _tile(VALUES, BODY)
    assert _prune(tile, {"sample", "amplicon_length"}) is True
    assert "Amplicon" in tile["body"]
    assert set(tile["values"]) == {"libs", "amp"}


def test_a_column_named_only_by_the_filter_counts_too():
    values = {
        "donors": {
            "column": "sample",
            "aggregation": "count",
            "filter_expr": "col('has_template') == 'yes'",
        }
    }
    tile = _tile(values, "### The study\n- **Donors** {{donors}}\n- **Other** text\n")
    assert _prune(tile, {"sample"}) is True
    assert "Donors" not in tile["body"]


def test_an_unknown_schema_never_removes_a_line():
    tile = _tile(VALUES, BODY)
    assert _prune(tile, None) is True
    assert "Amplicon" in tile["body"]


def test_a_tile_left_with_nothing_is_dropped():
    tile = _tile({"amp": VALUES["amp"]}, "### The study\n- **Amplicon** {{amp}} bp\n")
    assert _prune(tile, {"sample"}) is False
