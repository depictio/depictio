"""The upsert route records a collection that has no Delta table.

MultiQC is raw parquet and GeoJSON is one opaque blob under a fixed key: neither
has a Delta log. The route used to open one for every type except MultiQC, so
registering a GeoJSON collection answered 500 (`TableNotFoundError`).
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.deltatables_endpoints import routes
from depictio.api.v1.endpoints.deltatables_endpoints.routes import (
    _compute_upsert_artifacts,
    _should_offload,
    _upsert_hash,
    stores_delta_table,
)


@pytest.mark.parametrize("dc_type", ["table", "Table", "image", "jbrowse2", "genomic_tracks", ""])
def test_delta_backed_types(dc_type):
    assert stores_delta_table(dc_type) is True


@pytest.mark.parametrize("dc_type", ["multiqc", "MultiQC", "geojson", "GeoJSON"])
def test_types_without_a_delta_table(dc_type):
    assert stores_delta_table(dc_type) is False


@pytest.fixture
def no_delta_log(monkeypatch):
    """Fail loudly if anything tries to read a Delta log."""

    def _boom(*args, **kwargs):
        raise AssertionError("a Delta log was read for a collection that has none")

    monkeypatch.setattr(routes, "delta_identity_hash", _boom)
    monkeypatch.setattr(routes.pl, "scan_delta", _boom)


def test_hash_of_a_blob_collection_reads_no_delta_log(no_delta_log):
    h = _upsert_hash("s3://bucket/dc/geojson_data.geojson", no_delta_table=True)
    assert len(h) == 64


def test_artifacts_of_a_blob_collection_have_no_column_specs(no_delta_log):
    h, specs = _compute_upsert_artifacts(
        "s3://bucket/dc/geojson_data.geojson", {}, no_delta_table=True
    )
    assert len(h) == 64
    assert specs == []


def test_a_blob_collection_is_never_offloaded(monkeypatch):
    assert _should_offload(True, no_delta_table=True) is False
