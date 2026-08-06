"""Unit tests for the AI component_yaml validator.

These tests exercise the pure validator helpers — no DB, no LLM. The
goal is to guarantee that:
1. Every supported component type round-trips through the CLI's
   `DashboardDataLite.from_yaml(...)` validator we delegate to.
2. Bad payloads surface errors the retry-prompt formatter can serialize.
3. The YAML-fence stripper tolerates ``` ```yaml fences the LLM sometimes
   adds despite the prompt instructions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints import component_yaml

# ---------------------------------------------------------------------------
# Happy path — one minimal valid YAML for each of the 7 component types
# ---------------------------------------------------------------------------


HAPPY_PATH_FIXTURES: dict[str, str] = {
    "figure": (
        "component_type: figure\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "visu_type: scatter\n"
        "dict_kwargs:\n"
        "  x: a\n"
        "  y: b\n"
    ),
    "card": (
        "component_type: card\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "aggregation: average\n"
        "column_name: x\n"
        "column_type: float64\n"
    ),
    "interactive": (
        "component_type: interactive\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "interactive_component_type: MultiSelect\n"
        "column_name: variety\n"
        "column_type: object\n"
    ),
    "table": ("component_type: table\nworkflow_tag: wf\ndata_collection_tag: dc\n"),
    "image": (
        "component_type: image\nworkflow_tag: wf\ndata_collection_tag: dc\nimage_column: path\n"
    ),
    "multiqc": (
        "component_type: multiqc\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "selected_module: fastqc\n"
        "selected_plot: per_base_sequence_quality\n"
    ),
    "map": (
        "component_type: map\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "map_type: scatter_map\n"
        "lat_column: lat\n"
        "lon_column: lon\n"
    ),
}


@pytest.mark.parametrize("component_type", list(HAPPY_PATH_FIXTURES.keys()))
def test_validate_single_happy_path(component_type: str) -> None:
    yaml_text = HAPPY_PATH_FIXTURES[component_type]
    result = component_yaml.validate_single(yaml_text)
    assert result["component_type"] == component_type
    assert result["workflow_tag"] == "wf"
    assert result["data_collection_tag"] == "dc"


# ---------------------------------------------------------------------------
# Bad payloads — every error must reach the formatter without crashing
# ---------------------------------------------------------------------------


def test_validate_single_bad_aggregation_for_string_column() -> None:
    yaml_text = (
        "component_type: card\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "aggregation: average\n"  # invalid for object column
        "column_name: variety\n"
        "column_type: object\n"
    )
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        component_yaml.validate_single(yaml_text)
    msg = component_yaml.format_validation_error_for_llm(exc_info.value)
    assert "aggregation" in msg.lower()


def test_validate_single_map_missing_lat_column() -> None:
    yaml_text = (
        "component_type: map\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "map_type: scatter_map\n"
        "lon_column: lon\n"  # missing lat_column
    )
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        component_yaml.validate_single(yaml_text)
    msg = component_yaml.format_validation_error_for_llm(exc_info.value)
    assert "lat_column" in msg


def test_validate_single_unknown_component_type() -> None:
    yaml_text = "component_type: gizmo\nworkflow_tag: wf\ndata_collection_tag: dc\n"
    with pytest.raises((ValidationError, ValueError)):
        component_yaml.validate_single(yaml_text)


def test_validate_single_invalid_yaml_grammar() -> None:
    with pytest.raises(ValueError) as exc_info:
        component_yaml.validate_single("component_type: figure\n  : bad")
    msg = component_yaml.format_validation_error_for_llm(exc_info.value)
    assert msg  # non-empty


# ---------------------------------------------------------------------------
# Fence stripping + envelope tolerance
# ---------------------------------------------------------------------------


def test_validate_single_strips_yaml_fence() -> None:
    fenced = (
        "```yaml\n"
        "component_type: figure\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "visu_type: histogram\n"
        "dict_kwargs:\n"
        "  x: foo\n"
        "```"
    )
    result = component_yaml.validate_single(fenced)
    assert result["component_type"] == "figure"


def test_validate_single_accepts_single_item_list() -> None:
    list_yaml = (
        "- component_type: figure\n"
        "  workflow_tag: wf\n"
        "  data_collection_tag: dc\n"
        "  visu_type: histogram\n"
        "  dict_kwargs: {x: foo}\n"
    )
    result = component_yaml.validate_single(list_yaml)
    assert result["component_type"] == "figure"


def test_validate_single_extracts_from_full_envelope() -> None:
    """Tolerate the LLM accidentally including a dashboard wrapper."""
    envelope = (
        "title: Some Dashboard\n"
        "components:\n"
        "  - component_type: card\n"
        "    workflow_tag: wf\n"
        "    data_collection_tag: dc\n"
        "    aggregation: count\n"
        "    column_name: x\n"
        "    column_type: object\n"
    )
    result = component_yaml.validate_single(envelope)
    assert result["component_type"] == "card"
    assert result["aggregation"] == "count"


def test_validate_single_preserves_component_title() -> None:
    """Regression: card / map / base lite components have a `title`
    field, which must survive the dashboard-key strip. Routes.py reads
    `parsed.title` for the response's explanation, and the user loses
    the AI-suggested name if we drop it."""
    yaml_text = (
        "component_type: card\n"
        "workflow_tag: wf\n"
        "data_collection_tag: dc\n"
        "aggregation: count\n"
        "column_name: x\n"
        "column_type: object\n"
        "title: Sample summary\n"
    )
    result = component_yaml.validate_single(yaml_text)
    assert result["title"] == "Sample summary"


# ---------------------------------------------------------------------------
# dump_single — drops runtime-only fields, keeps user-authored ones
# ---------------------------------------------------------------------------


def test_dump_single_strips_runtime_fields() -> None:
    component = {
        "component_type": "figure",
        "workflow_tag": "wf",
        "data_collection_tag": "dc",
        "visu_type": "scatter",
        "dict_kwargs": {"x": "a"},
        "index": "deadbeef-uuid",
        "tag": "auto-generated-tag",
        "wf_id": "ignored",
        "dc_id": "ignored",
        "displayed_data_count": 0,
        "title": "kept",
    }
    out = component_yaml.dump_single(component)
    assert "component_type: figure" in out
    assert "title: kept" in out
    # The auto-generated `tag` field is dropped, but the `workflow_tag`
    # / `data_collection_tag` fields naturally contain "tag:" as a
    # substring — anchor the check on a line-start match for `tag:`.
    assert "\ntag:" not in "\n" + out
    assert "index" not in out
    assert "wf_id" not in out
    assert "displayed_data_count" not in out


# ---------------------------------------------------------------------------
# format_validation_error_for_llm — preserves Pydantic v2 error shape
# ---------------------------------------------------------------------------


def test_format_validation_error_non_pydantic() -> None:
    err = ValueError("kaboom")
    out = component_yaml.format_validation_error_for_llm(err)
    assert "ValueError" in out
    assert "kaboom" in out
