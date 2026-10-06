"""Guardrails on the component-from-prompt sheets and examples.

Every YAML example embedded in the prompt must pass the same validator the
endpoint applies to LLM output: if the component grammar drifts (a field
renamed, a new required key), this fails before any user sees the LLM emit
stale YAML that can never validate. The sheet/example/type sets must also
stay aligned, and the data-driven sheets must render from a DataContext.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest

from depictio.api.v1.endpoints.ai_endpoints import component_yaml
from depictio.api.v1.endpoints.ai_endpoints.context import (
    MAX_INVENTORY_COLLECTIONS,
    MAX_INVENTORY_COLUMNS,
    ColumnSummary,
    DataContext,
    InventoryEntry,
    ProjectInventory,
)
from depictio.api.v1.endpoints.ai_endpoints.prompts import (
    _CONSTRAINT_SHEETS,
    _YAML_EXAMPLES,
    FALLBACK_ADVANCED_VIZ_KINDS,
    MAX_ADVANCED_VIZ_KINDS,
    _constraint_sheet,
    component_from_prompt_messages,
    route_component_messages,
    suggest_figures_messages,
)
from depictio.api.v1.endpoints.ai_endpoints.schemas import ComponentType
from depictio.models.components.constants import MAX_INTERACTIVE_GROUP_SIZE, VISU_TYPES

# `<column>`-style placeholders → plausible concrete values. Substitution
# keyed on hint words so type-sensitive fields stay valid.
_PLACEHOLDER = re.compile(r"<[^>]+>")


def _fill(match: re.Match[str]) -> str:
    token = match.group(0)
    if "workflow_tag" in token:
        return "wf"
    if "data_collection_tag" in token:
        return "dc"
    return "colx"


def _ctx(columns: dict[str, str]) -> DataContext:
    return DataContext(
        data_collection_id="6" * 24,
        workflow_id="7" * 24,
        project_name="P",
        project_description=None,
        dc_name="dc",
        dc_description=None,
        columns=[
            ColumnSummary(name=n, dtype=d, null_pct=0.0, nunique=10) for n, d in columns.items()
        ],
        sample_rows=[],
        row_count=100,
        workflow_tag="wf",
        data_collection_tag="dc",
    )


DE_COLUMNS = {
    "gene_id": "String",
    "log2FoldChange": "Float64",
    "padj": "Float64",
    "symbol": "String",
}
IRIS_COLUMNS = {"sepal_length": "Float64", "variety": "String"}


@pytest.mark.parametrize("component_type", sorted(_YAML_EXAMPLES))
def test_prompt_yaml_example_validates(component_type: str) -> None:
    concrete = _PLACEHOLDER.sub(_fill, _YAML_EXAMPLES[component_type])
    parsed = component_yaml.validate_single(concrete)
    assert parsed["component_type"] == component_type


def test_every_component_type_has_a_sheet_and_an_example() -> None:
    """One source of truth: the Literal, the sheets and the examples agree."""
    types = set(get_args(ComponentType))
    assert set(_CONSTRAINT_SHEETS) == types
    assert set(_YAML_EXAMPLES) == types
    assert len(types) == 9


@pytest.mark.parametrize("component_type", sorted(set(get_args(ComponentType)) - {"advanced_viz"}))
def test_static_sheets_ignore_the_data_context(component_type: str) -> None:
    ctx = _ctx(DE_COLUMNS)
    assert _constraint_sheet(component_type, None) == _constraint_sheet(component_type, ctx)
    assert _constraint_sheet(component_type, None).strip()


def test_interactive_sheet_quotes_the_current_group_cap() -> None:
    sheet = _constraint_sheet("interactive", None)
    assert f"≤ {MAX_INTERACTIVE_GROUP_SIZE}" in sheet
    assert "≤ 3 " not in sheet


def test_figure_sheet_and_suggest_prompt_list_every_visu_type() -> None:
    sheet = _constraint_sheet("figure", None)
    suggest = suggest_figures_messages(_ctx(IRIS_COLUMNS), 2)[0]["content"]
    for visu in VISU_TYPES:
        assert visu in sheet
        assert visu in suggest
    assert "|".join(VISU_TYPES) in suggest


class TestAdvancedVizSheet:
    def test_names_kinds_and_config_keys_for_the_dc(self) -> None:
        sheet = _constraint_sheet("advanced_viz", _ctx(DE_COLUMNS))
        assert "viz_kind: volcano" in sheet
        for key in ("config.feature_id_col", "config.effect_size_col", "config.significance_col"):
            assert key in sheet
        # The ranker's candidates are surfaced next to the role they fit.
        assert "log2FoldChange" in sheet
        assert "optional settings:" in sheet

    def test_is_bounded(self) -> None:
        sheet = _constraint_sheet("advanced_viz", _ctx(DE_COLUMNS))
        assert 0 < sheet.count("- viz_kind:") <= MAX_ADVANCED_VIZ_KINDS

    def test_falls_back_to_the_best_few_when_nothing_is_recommended(self) -> None:
        sheet = _constraint_sheet("advanced_viz", _ctx(IRIS_COLUMNS))
        assert sheet.count("- viz_kind:") == FALLBACK_ADVANCED_VIZ_KINDS

    def test_renders_without_a_context(self) -> None:
        assert "ADVANCED_VIZ" in _constraint_sheet("advanced_viz", None)


class TestComponentFromPromptMessages:
    def test_data_driven_prompt_carries_the_dataset(self) -> None:
        system = component_from_prompt_messages(_ctx(IRIS_COLUMNS), "scatter", "figure")[0][
            "content"
        ]
        assert "DATASET SCHEMA:" in system
        assert "SAMPLE ROWS:" in system
        assert "DASHBOARD COMPONENTS" not in system
        assert "workflow_tag: wf" in system

    def test_text_prompt_uses_the_dashboard_summary_instead(self) -> None:
        block = "- f1 (figure, dc=abc): Sepal scatter"
        system = component_from_prompt_messages(None, "intro", "text", dashboard_block=block)[0][
            "content"
        ]
        assert "DATASET SCHEMA:" not in system
        assert "DASHBOARD COMPONENTS" in system
        assert "Sepal scatter" in system
        assert "TEXT:" in system
        assert "Do not emit workflow_tag" in system

    def test_text_prompt_without_dashboard_says_so(self) -> None:
        system = component_from_prompt_messages(None, "intro", "text")[0]["content"]
        assert "(no dashboard context available)" in system


# ---------------------------------------------------------------------------
# Routing prompt
# ---------------------------------------------------------------------------

ALL_TYPES: list[str] = sorted(get_args(ComponentType))
# Prompt budget for the largest inventory the builder produces.
ROUTE_PROMPT_MAX_CHARS = 12_000


def _inventory(n_collections: int, n_columns: int, *, on_dashboard: int = 1) -> ProjectInventory:
    entries = [
        InventoryEntry(
            data_collection_id=f"{i:024d}",
            data_collection_tag=f"collection_{i:02d}",
            workflow_id="7" * 24,
            workflow_tag="wf",
            dc_type="table",
            description=f"Measurements batch {i} with a fairly long free-text description",
            columns=[(f"measurement_value_{c:02d}", "float64") for c in range(n_columns)],
            on_dashboard=i < on_dashboard,
        )
        for i in range(n_collections)
    ]
    return ProjectInventory(
        dashboard_id="d", project_id="p", project_name="Big project", entries=entries
    )


class TestRouteComponentMessages:
    def test_names_every_type_and_every_tag(self) -> None:
        inv = _inventory(3, 4, on_dashboard=1)
        system, user = route_component_messages("show me something", inv, ALL_TYPES)
        assert user == {"role": "user", "content": "show me something"}
        text = system["content"]
        for t in ALL_TYPES:
            assert f"- {t}:" in text
        for tag in inv.tags():
            assert tag in text
        assert text.count("on dashboard]") == 1
        assert "collection_00 [table, on dashboard]" in text
        assert "collection_01 [table]" in text
        assert "measurement_value_00:float64" in text
        assert '"component_type"' in text
        assert "PINNED BY THE USER" not in text

    def test_pins_are_stated(self) -> None:
        inv = _inventory(2, 2)
        text = route_component_messages(
            "x", inv, ["card"], pinned_type="card", pinned_dc_tag="collection_01"
        )[0]["content"]
        assert 'component_type is fixed to "card"' in text
        assert 'data_collection_tag is fixed to "collection_01"' in text
        # Only the allowed type is described.
        assert "- card:" in text
        assert "- figure:" not in text

    def test_stays_under_the_size_cap_at_the_inventory_limits(self) -> None:
        inv = _inventory(MAX_INVENTORY_COLLECTIONS, MAX_INVENTORY_COLUMNS, on_dashboard=5)
        text = route_component_messages("x", inv, ALL_TYPES)[0]["content"]
        assert len(text) < ROUTE_PROMPT_MAX_CHARS
        for tag in inv.tags():
            assert tag in text
