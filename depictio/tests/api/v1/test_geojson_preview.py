"""`GET /advanced_viz/geojson/{dc_id}` serves only the file ingest stored."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.advanced_viz_endpoints import routes

DC_ID = ObjectId("646b0f3c1e4a2d7f8e5b8ca9")
BODY = b'{"type": "FeatureCollection", "features": []}'


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": io.BytesIO(BODY)}
    monkeypatch.setattr(routes, "_phylogeny_s3_client", lambda: s3)
    monkeypatch.setattr(routes, "_assert_dc_access", lambda dc_oid, user: None)
    return s3


def test_reads_the_fixed_key_in_the_instance_bucket(client: MagicMock):
    response = routes.get_geojson(DC_ID, current_user=object())

    assert response.body == BODY
    client.get_object.assert_called_once_with(
        Bucket=settings.s3.bucket, Key=f"{DC_ID}/geojson_data.geojson"
    )


def test_a_missing_file_is_a_404(client: MagicMock):
    client.get_object.side_effect = Exception("NoSuchKey")

    with pytest.raises(HTTPException) as caught:
        routes.get_geojson(DC_ID, current_user=object())

    assert caught.value.status_code == 404
    assert "NoSuchKey" not in caught.value.detail


def test_no_read_without_access(client: MagicMock, monkeypatch: pytest.MonkeyPatch):
    def refuse(dc_oid, user):
        raise HTTPException(status_code=404, detail="Data collection not found")

    monkeypatch.setattr(routes, "_assert_dc_access", refuse)

    with pytest.raises(HTTPException):
        routes.get_geojson(DC_ID, current_user=object())

    client.get_object.assert_not_called()
