"""Contract for ``POST /dashboards/map_data/{dashboard_id}/{component_id}``.

The endpoint backs the viewer's "show underlying data" popover on a map. It
returns every column of the map's data collection, filtered by the dashboard,
in the column-oriented shape ``/advanced_viz/data`` uses — so the two share one
grid on the client.

The prologue it runs on (``_component_context``) is also the authorisation
boundary: it is what stops a caller reading a data collection through a
component id they were never shown. Its refusals are tested here rather than
only its happy path.
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes

DASHBOARD_ID = "507f1f77bcf86cd799439011"
PROJECT_ID = "507f1f77bcf86cd799439012"
WF_ID = "507f1f77bcf86cd799439013"
DC_ID = "507f1f77bcf86cd799439014"
COMPONENT_ID = "map-1"


def _map_component(**overrides) -> dict:
    component = {
        "index": COMPONENT_ID,
        "component_type": "map",
        "wf_id": WF_ID,
        "dc_id": DC_ID,
        "map_type": "scatter_map",
        "lat_column": "lat",
        "lon_column": "lon",
        "selection_column": "city",
        "hover_columns": ["country"],
        "dc_config": {"delta_location": "s3://bucket/delta", "type": "table"},
    }
    component.update(overrides)
    return component


def _dashboard(components: list[dict] | None = None) -> dict:
    return {
        "dashboard_id": DASHBOARD_ID,
        "project_id": PROJECT_ID,
        "stored_metadata": [_map_component()] if components is None else components,
    }


def _frame(rows: int = 3) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "run_id": [f"r{i}" for i in range(rows)],
            "lat": [48.85 + i for i in range(rows)],
            "lon": [2.35 + i for i in range(rows)],
            "city": [f"city{i}" for i in range(rows)],
            "country": ["FR"] * rows,
            "n_samples": list(range(rows)),
        }
    )


class _Ctx:
    """Patches the module-level collaborators ``_component_context`` reaches for."""

    def __init__(self, dashboard: dict | None, *, permitted: bool = True):
        self.dashboard = dashboard
        self.permitted = permitted

    def __enter__(self):
        self._patches = [
            patch.object(
                routes,
                "dashboards_collection",
                type("C", (), {"find_one": lambda _self, *a, **k: self.dashboard})(),
            ),
            patch.object(routes, "check_project_permission", lambda *a, **k: self.permitted),
            # Link resolution needs a project + DB; the map's own filters pass
            # straight through in every case exercised here.
            patch.object(routes, "_resolve_link_filters_cached", lambda **kw: kw["filters"]),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


def _call(request: dict | None = None, component_id: str = COMPONENT_ID):
    return routes.map_data_endpoint(
        DASHBOARD_ID,
        component_id,
        request or {"filters": []},
        current_user=None,
        access_token=None,
    )


# ---------------------------------------------------------------------------
# Authorisation and resolution
# ---------------------------------------------------------------------------


def test_unknown_dashboard_is_404() -> None:
    with _Ctx(None), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 404


def test_permission_denied_is_403() -> None:
    with _Ctx(_dashboard(), permitted=False), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 403


def test_unknown_component_is_404() -> None:
    with _Ctx(_dashboard()), pytest.raises(HTTPException) as exc:
        _call(component_id="does-not-exist")
    assert exc.value.status_code == 404


def test_non_map_component_is_404() -> None:
    """The component-type guard is the security-relevant half of the prologue.

    Without it, a table's id would read its data collection through an endpoint
    that never checks the table's own permissions.
    """
    table = _map_component(component_type="table")
    with _Ctx(_dashboard([table])), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 404


def test_component_without_dc_is_400() -> None:
    broken = _map_component(dc_id=None)
    with _Ctx(_dashboard([broken])), pytest.raises(HTTPException) as exc:
        _call()
    assert exc.value.status_code == 400


def test_unreadable_data_collection_is_422_not_500() -> None:
    """A data problem is not a server fault — the popover can say what broke."""
    with (
        _Ctx(_dashboard()),
        patch(
            "depictio.api.v1.deltatables_utils.load_deltatable_lite",
            side_effect=RuntimeError("delta table missing"),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        _call()
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_returns_every_column_of_the_collection() -> None:
    df = _frame()
    with (
        _Ctx(_dashboard()),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=df),
    ):
        result = _call()

    assert set(result["columns"]) == set(df.columns), "user asked for all DC columns"
    assert result["row_count"] == 3
    assert result["total_rows"] == 3
    assert result["truncated"] is False
    assert result["filter_applied"] is False
    # Column-oriented, matching /advanced_viz/data so both feed the same grid.
    assert result["rows"]["city"] == ["city0", "city1", "city2"]


def test_map_columns_lead_the_ordering() -> None:
    df = _frame()
    with (
        _Ctx(_dashboard()),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=df),
    ):
        result = _call()

    assert result["columns"][:4] == ["city", "lat", "lon", "country"], (
        "selection / coordinates / hover columns open the table, not whatever "
        "the DC happens to store first"
    )


def test_filters_reach_the_loader_and_are_reported() -> None:
    captured: dict = {}

    def _load(**kwargs):
        captured.update(kwargs)
        return _frame(1)

    request = {
        "filters": [
            {
                "index": "habitat-filter",
                "column_name": "country",
                "interactive_component_type": "MultiSelect",
                "value": ["FR"],
            }
        ]
    }
    with (
        _Ctx(_dashboard()),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", side_effect=_load),
    ):
        result = _call(request)

    assert result["filter_applied"] is True
    assert captured["metadata"] == [
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "country",
            "value": ["FR"],
        }
    ]


def test_row_cap_truncates_and_reports_the_real_total() -> None:
    """The cap must be visible in the payload, not a silent short read."""
    with (
        _Ctx(_dashboard()),
        patch.object(routes, "MAP_DATA_MAX_ROWS", 2),
        # The loader is asked for MAX+1 so a frame that exactly fills the cap is
        # still recognisable as truncated.
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=_frame(3)),
        patch.object(routes, "_cached_row_count", return_value=57),
    ):
        result = _call()

    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert result["total_rows"] == 57, "the honest count, not the capped one"
    assert len(result["rows"]["city"]) == 2


def test_exactly_at_the_cap_is_not_truncated() -> None:
    with (
        _Ctx(_dashboard()),
        patch.object(routes, "MAP_DATA_MAX_ROWS", 3),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=_frame(3)),
    ):
        result = _call()

    assert result["truncated"] is False
    assert result["row_count"] == 3
    assert result["total_rows"] == 3


def test_non_json_native_columns_are_serialised_as_text() -> None:
    """Datetime / Categorical would otherwise reach the JSON encoder as objects."""
    df = _frame(2).with_columns(
        pl.Series("collected_at", ["2026-01-01", "2026-02-01"]).str.to_date(),
        pl.Series("tier", ["a", "b"]).cast(pl.Categorical),
    )
    with (
        _Ctx(_dashboard()),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=df),
    ):
        result = _call()

    assert all(isinstance(v, str) for v in result["rows"]["collected_at"])
    assert all(isinstance(v, str) for v in result["rows"]["tier"])
    # Numerics and booleans stay native — the grid's numeric filters need them.
    assert all(isinstance(v, int) for v in result["rows"]["n_samples"])
    assert all(isinstance(v, float) for v in result["rows"]["lat"])


def test_columns_polars_refuses_to_cast_still_come_back() -> None:
    """List / Array / Duration raise on ``cast(String)`` in Polars.

    The endpoint returns *every* column, so one such column anywhere in the
    collection used to cost the user the whole table with a 500.
    """
    df = _frame(2).with_columns(
        pl.Series("read_lengths", [[1, 2], [3]]),
        pl.Series("elapsed", [1_000, 2_000]).cast(pl.Duration("us")),
    )
    with (
        _Ctx(_dashboard()),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=df),
    ):
        result = _call()

    assert all(isinstance(v, str) for v in result["rows"]["read_lengths"])
    assert all(isinstance(v, str) for v in result["rows"]["elapsed"])
    assert result["row_count"] == 2


def test_truncated_response_never_reports_fewer_rows_than_it_returns() -> None:
    """``count_deltatable_lite`` answers 0 rather than raising when it fails.

    Unguarded that surfaced in the UI as "first 10,000 of 0".
    """
    with (
        _Ctx(_dashboard()),
        patch.object(routes, "MAP_DATA_MAX_ROWS", 2),
        patch("depictio.api.v1.deltatables_utils.load_deltatable_lite", return_value=_frame(3)),
        patch.object(routes, "_cached_row_count", return_value=0),
    ):
        result = _call()

    assert result["row_count"] == 2
    assert result["total_rows"] == 2, "degraded to 'of 2', never to 'of 0'"


# ---------------------------------------------------------------------------
# Column ordering helper
# ---------------------------------------------------------------------------


def test_column_order_keeps_every_column() -> None:
    columns = ["run_id", "lat", "country", "lon", "city", "depth"]
    ordered = routes._map_column_order(_map_component(), columns)
    assert sorted(ordered) == sorted(columns), "ordering only — nothing is dropped"


def test_column_order_ignores_columns_the_frame_lacks() -> None:
    """A map can name a column its DC no longer has (renamed, re-ingested)."""
    ordered = routes._map_column_order(
        _map_component(color_column="gone", hover_columns=["also_gone", "country"]),
        ["run_id", "lat", "lon", "city", "country"],
    )
    assert ordered == ["city", "lat", "lon", "country", "run_id"]
