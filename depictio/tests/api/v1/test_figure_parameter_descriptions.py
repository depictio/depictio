"""Tests for the parameter descriptions shown in the figure builder's hover cards.

Curated descriptions come from the inspector's knowledge bases; every other
parameter falls back to the Plotly Express docstring, parsed by
``parse_docstring_descriptions``.
"""

from depictio.api.v1.services.figure.definitions import get_visualization_registry
from depictio.api.v1.services.figure.parameter_discovery import (
    ParameterInspector,
    parse_docstring_descriptions,
)

DOC = """
    In a scatter plot, each row is a mark.

Parameters
----------
x: str or int
    Either a name of a column in `data_frame`, or a
    pandas Series.

undocumented: str
opacity: float
    Value between 0 and 1.

Returns
-------
    plotly.graph_objects.Figure
"""


def test_parse_joins_lines_and_drops_backticks():
    parsed = parse_docstring_descriptions(DOC)
    assert parsed["x"] == "Either a name of a column in data_frame, or a pandas Series."
    assert parsed["opacity"] == "Value between 0 and 1."


def test_parse_skips_entries_without_description_and_stops_at_returns():
    parsed = parse_docstring_descriptions(DOC)
    assert set(parsed) == {"x", "opacity"}


def test_parse_handles_missing_docstring():
    assert parse_docstring_descriptions(None) == {}
    assert parse_docstring_descriptions("No parameters section.") == {}


def test_uncurated_parameter_gets_plotly_description():
    params = {p.name: p for p in ParameterInspector().discover_parameters("scatter")}
    assert params["facet_row_spacing"].description.startswith("Spacing between facet rows")


def test_curated_description_wins_over_docstring():
    inspector = ParameterInspector()
    curated = inspector.get_parameter_metadata("x")["description"]
    params = {p.name: p for p in inspector.discover_parameters("scatter")}
    assert params["x"].description == curated


def test_every_registered_parameter_has_a_description():
    missing = [
        f"{viz}.{p.name}"
        for viz, definition in get_visualization_registry().items()
        for p in definition.parameters
        if not p.description.strip()
    ]
    assert missing == []
