"""``GET /deltatables/data/{dc_id}``: the Parquet a notebook reads."""

from __future__ import annotations

import io
from unittest.mock import patch

import polars as pl
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.deltatables_endpoints import routes

DC_ID = ObjectId()
FRAME = pl.DataFrame(
    {
        "species": ["Adelie", "Gentoo"],
        "body_mass_g": [3500.0, 5000.0],
        "depictio_aggregation_time": ["t", "t"],
    }
)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(routes, "_resolve_delta_location", lambda dc, user: "s3://bucket/dc")
    monkeypatch.setattr(routes.pl, "scan_delta", lambda loc, storage_options=None: FRAME.lazy())
    yield


async def _call(**kwargs):
    return await routes.get_data_parquet(data_collection_id=DC_ID, current_user=object(), **kwargs)


@pytest.mark.asyncio
async def test_round_trips_the_table_as_parquet(patched):
    resp = await _call()
    assert resp.media_type == "application/vnd.apache.parquet"
    assert resp.headers["X-Depictio-Rows"] == "2"
    df = pl.read_parquet(io.BytesIO(resp.body))
    assert df.columns == ["species", "body_mass_g"]  # the internal timestamp is dropped
    assert df["body_mass_g"].to_list() == [3500.0, 5000.0]


@pytest.mark.asyncio
async def test_columns_projection_and_unknown_column(patched):
    resp = await _call(columns="species")
    assert pl.read_parquet(io.BytesIO(resp.body)).columns == ["species"]
    with pytest.raises(HTTPException) as exc:
        await _call(columns="species,nope")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_row_cap_refuses_with_413(patched):
    with patch.object(routes.settings.notebook_export, "max_rows", 1):
        with pytest.raises(HTTPException) as exc:
            await _call()
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_unreadable_table_is_404(monkeypatch):
    monkeypatch.setattr(routes, "_resolve_delta_location", lambda dc, user: "s3://bucket/dc")

    def boom(loc, storage_options=None):
        raise RuntimeError("not a delta table")

    monkeypatch.setattr(routes.pl, "scan_delta", boom)
    with pytest.raises(HTTPException) as exc:
        await _call()
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_permission_denial_propagates(monkeypatch):
    def deny(dc, user):
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    monkeypatch.setattr(routes, "_resolve_delta_location", deny)
    with pytest.raises(HTTPException) as exc:
        await _call()
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_feature_flag_off_is_404(patched):
    with patch.object(routes.settings.notebook_export, "enabled", False):
        with pytest.raises(HTTPException) as exc:
            await _call()
    assert exc.value.status_code == 404
