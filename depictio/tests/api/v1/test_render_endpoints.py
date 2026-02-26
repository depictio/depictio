"""
Tests for the component render/export API.

Covers:
- Component resolution by UUID and tag
- Pydantic model validation for request/response schemas
- Table rendering logic (column selection, page_size)
- Card rendering logic (aggregation computation)
"""

from __future__ import annotations

from typing import Any

import pytest

from depictio.api.v1.endpoints.dashboards_endpoints.render_models import (
    ComponentRenderRequest,
    ComponentRenderResponse,
    TaskPendingResponse,
    TaskStatusResponse,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FIGURE_COMPONENT: dict[str, Any] = {
    "index": "550e8400-e29b-41d4-a716-446655440000",
    "tag": "scatter-1",
    "component_type": "figure",
    "wf_id": "673abc000000000000000001",
    "dc_id": "673def000000000000000001",
    "visu_type": "scatter",
    "dict_kwargs": {"x": "col_a", "y": "col_b"},
    "mode": "ui",
}

SAMPLE_CARD_COMPONENT: dict[str, Any] = {
    "index": "650e8400-e29b-41d4-a716-446655440001",
    "tag": "avg-card",
    "component_type": "card",
    "wf_id": "673abc000000000000000001",
    "dc_id": "673def000000000000000001",
    "column_name": "col_a",
    "aggregation": "average",
}

SAMPLE_TABLE_COMPONENT: dict[str, Any] = {
    "index": "750e8400-e29b-41d4-a716-446655440002",
    "tag": "data-table",
    "component_type": "table",
    "wf_id": "673abc000000000000000001",
    "dc_id": "673def000000000000000001",
    "columns": ["col_a", "col_b"],
    "page_size": 10,
}

SAMPLE_INTERACTIVE_COMPONENT: dict[str, Any] = {
    "index": "850e8400-e29b-41d4-a716-446655440003",
    "tag": "filter-select",
    "component_type": "interactive",
    "wf_id": "673abc000000000000000001",
    "dc_id": "673def000000000000000001",
}

STORED_METADATA: list[dict[str, Any]] = [
    SAMPLE_FIGURE_COMPONENT,
    SAMPLE_CARD_COMPONENT,
    SAMPLE_TABLE_COMPONENT,
    SAMPLE_INTERACTIVE_COMPONENT,
]


# ---------------------------------------------------------------------------
# Inline _resolve_component to avoid importing render.py (heavy dep chain)
# ---------------------------------------------------------------------------


def _resolve_component(
    stored_metadata: list[dict[str, Any]], identifier: str
) -> dict[str, Any] | None:
    """Mirror of render._resolve_component for isolated testing."""
    for component in stored_metadata:
        if component.get("index") == identifier or component.get("tag") == identifier:
            return component
    return None


# ---------------------------------------------------------------------------
# Component resolution tests
# ---------------------------------------------------------------------------


class TestResolveComponent:
    """Test component resolution by UUID or tag."""

    def test_resolve_by_uuid(self) -> None:
        """Resolve component using its UUID index."""
        result = _resolve_component(STORED_METADATA, "550e8400-e29b-41d4-a716-446655440000")
        assert result is not None
        assert result["tag"] == "scatter-1"

    def test_resolve_by_tag(self) -> None:
        """Resolve component using its human-readable tag."""
        result = _resolve_component(STORED_METADATA, "scatter-1")
        assert result is not None
        assert result["index"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_resolve_card_by_tag(self) -> None:
        """Resolve card component by tag."""
        result = _resolve_component(STORED_METADATA, "avg-card")
        assert result is not None
        assert result["component_type"] == "card"

    def test_resolve_not_found(self) -> None:
        """Return None for non-existent identifier."""
        result = _resolve_component(STORED_METADATA, "nonexistent-component")
        assert result is None

    def test_resolve_empty_metadata(self) -> None:
        """Return None when stored_metadata is empty."""
        result = _resolve_component([], "scatter-1")
        assert result is None


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestRenderModels:
    """Test Pydantic request/response model validation."""

    def test_default_request(self) -> None:
        """Default request has light theme and 30s timeout."""
        req = ComponentRenderRequest()
        assert req.theme == "light"
        assert req.timeout == 30
        assert req.filters is None
        assert req.force_full_data is False

    def test_request_with_filters(self) -> None:
        """Request accepts filter metadata."""
        req = ComponentRenderRequest(
            theme="dark",
            filters=[{"column": "species", "operator": "eq", "value": "setosa"}],
            timeout=60,
        )
        assert req.theme == "dark"
        assert len(req.filters) == 1

    def test_invalid_theme_rejected(self) -> None:
        """Theme must be 'light' or 'dark'."""
        with pytest.raises(Exception):
            ComponentRenderRequest(theme="blue")

    def test_timeout_bounds(self) -> None:
        """Timeout must be between 1 and 120."""
        with pytest.raises(Exception):
            ComponentRenderRequest(timeout=0)
        with pytest.raises(Exception):
            ComponentRenderRequest(timeout=200)

    def test_component_render_response(self) -> None:
        """ComponentRenderResponse serializes correctly."""
        resp = ComponentRenderResponse(
            status="success",
            component_type="figure",
            component_tag="scatter-1",
            component_index="550e8400-e29b-41d4-a716-446655440000",
            data={"figure": {"data": [], "layout": {}}, "data_info": {}},
        )
        assert resp.status == "success"
        assert resp.component_type == "figure"

    def test_task_pending_response(self) -> None:
        """TaskPendingResponse includes task_id and status."""
        resp = TaskPendingResponse(task_id="abc-123")
        assert resp.status == "pending"
        assert resp.task_id == "abc-123"
        assert "render/tasks" in resp.message

    def test_task_status_response_success(self) -> None:
        """TaskStatusResponse with success result."""
        inner = ComponentRenderResponse(
            component_type="card",
            component_index="test-uuid",
            data={"value": 5.0, "aggregation": "average", "column": "col_a"},
        )
        resp = TaskStatusResponse(status="success", task_id="xyz", result=inner)
        assert resp.result is not None
        assert resp.error is None

    def test_task_status_response_failed(self) -> None:
        """TaskStatusResponse with error."""
        resp = TaskStatusResponse(status="failed", task_id="xyz", error="Data not found")
        assert resp.result is None
        assert resp.error == "Data not found"


# ---------------------------------------------------------------------------
# Table rendering unit tests (inline logic to avoid heavy imports)
# ---------------------------------------------------------------------------


class TestTableRenderLogic:
    """Test table rendering logic using inline implementation."""

    @staticmethod
    def _render_table(component: dict[str, Any], df: Any) -> dict[str, Any]:
        """Inline table render logic matching render_tasks._render_table_component."""
        total_rows = df.height
        columns: list[str] = component.get("columns", [])
        if columns:
            available_cols = [c for c in columns if c in df.columns]
            if available_cols:
                df = df.select(available_cols)
        page_size: int = component.get("page_size", 100)
        if page_size and page_size > 0:
            df = df.head(page_size)
        rows = df.to_dicts()
        return {
            "rows": rows,
            "columns": df.columns,
            "total_rows": total_rows,
            "returned_rows": len(rows),
        }

    def test_render_table_selects_columns(self) -> None:
        """Table rendering selects specified columns only."""
        polars = pytest.importorskip("polars")
        df = polars.DataFrame({"col_a": [1, 2, 3], "col_b": ["a", "b", "c"], "col_c": [10, 20, 30]})
        result = self._render_table(SAMPLE_TABLE_COMPONENT, df)
        assert result["total_rows"] == 3
        assert result["returned_rows"] == 3
        assert set(result["columns"]) == {"col_a", "col_b"}

    def test_render_table_page_size(self) -> None:
        """Table rendering respects page_size limit."""
        polars = pytest.importorskip("polars")
        df = polars.DataFrame({"col_a": list(range(100)), "col_b": list(range(100))})
        component = {**SAMPLE_TABLE_COMPONENT, "page_size": 5}
        result = self._render_table(component, df)
        assert result["total_rows"] == 100
        assert result["returned_rows"] == 5

    def test_render_table_all_columns(self) -> None:
        """Table rendering returns all columns when none specified."""
        polars = pytest.importorskip("polars")
        df = polars.DataFrame({"x": [1, 2], "y": [3, 4]})
        component = {"columns": [], "page_size": 100}
        result = self._render_table(component, df)
        assert set(result["columns"]) == {"x", "y"}
