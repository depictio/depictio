"""A group filter finds its column whatever the case a collection spells it in.

Split / Colour-by names the dashboard's column as the first collection spells
it (`habitat`); a canonical recipe often capitalises it (`Habitat`). Without
the match the split fans out into panels that all hold the same rows.
"""

from __future__ import annotations

from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import _match_spelling, _with_column


def test_with_column_rewrites_top_level_and_nested_without_mutating() -> None:
    original = {
        "index": "__depictio_group__:panel:habitat=Soil",
        "value": ["Soil"],
        "column_name": "habitat",
        "source": "group_filter",
        "metadata": {"column_name": "habitat", "interactive_component_type": "MultiSelect"},
    }
    out = _with_column(original, "Habitat")
    assert out["column_name"] == "Habitat"
    assert out["metadata"]["column_name"] == "Habitat"
    assert out["metadata"]["interactive_component_type"] == "MultiSelect"
    assert original["column_name"] == "habitat"
    assert original["metadata"]["column_name"] == "habitat"


def test_with_column_leaves_absent_keys_absent() -> None:
    assert "column_name" not in _with_column({"value": ["x"]}, "Habitat")


def test_match_spelling_ignores_case_then_separators() -> None:
    assert _match_spelling({"Habitat", "sample_id"}, "habitat") == "Habitat"
    assert _match_spelling({"Kingdom", "sample_id"}, "sampleID") == "sample_id"


def test_match_spelling_refuses_an_ambiguous_or_absent_column() -> None:
    assert _match_spelling({"sample_id", "sample-id"}, "sampleID") is None
    assert _match_spelling({"Kingdom"}, "sampleID") is None
    # An exact-case-insensitive hit is not overridden by a looser one.
    assert _match_spelling({"Sample", "sample_"}, "sample") == "Sample"
