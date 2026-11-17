"""``load_geojson_from_s3`` reads the collection's file from the instance bucket.

It used to build ``s3fs.S3FileSystem(**polars_s3_config)``: the polars/delta
storage options (``aws_access_key_id``...) are not s3fs arguments, so every
read failed with ``AioSession.__init__() got an unexpected keyword argument``
and the map rendered without its regions.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from depictio.api.v1 import deltatables_utils

GEOJSON = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}}]}


class _FakeS3:
    def __init__(self, objects: dict[tuple[str, str], bytes]):
        self.objects = objects
        self.calls: list[tuple[str, str]] = []

    def get_object(self, Bucket: str, Key: str):
        self.calls.append((Bucket, Key))
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


@pytest.fixture
def located(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {"delta_table_location": "s3://bucket-a/dc1/geojson_data.geojson"},
        )

    monkeypatch.setattr(deltatables_utils.httpx, "get", fake_get)
    fake = _FakeS3({("bucket-a", "dc1/geojson_data.geojson"): json.dumps(GEOJSON).encode()})
    monkeypatch.setattr("depictio.api.v1.s3.s3_client", fake)
    return fake


def test_reads_the_geojson_object_from_the_bucket(located):
    assert deltatables_utils.load_geojson_from_s3("dc1", TOKEN="t") == GEOJSON
    assert located.calls == [("bucket-a", "dc1/geojson_data.geojson")]


def test_a_location_that_is_not_s3_is_refused(monkeypatch, located):
    monkeypatch.setattr(
        deltatables_utils.httpx,
        "get",
        lambda url, headers=None, timeout=None: SimpleNamespace(
            status_code=200, text="", json=lambda: {"delta_table_location": "/etc/passwd"}
        ),
    )
    assert deltatables_utils.load_geojson_from_s3("dc1", TOKEN="t") is None
    assert located.calls == []
