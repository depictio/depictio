"""Tests for the bulk-delete MultiQC reports endpoint and utility."""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.multiqc_endpoints.utils import (
    delete_all_multiqc_reports_for_dc,
)


def _build_report_doc(data_collection_id: str, suffix: str) -> dict:
    """Build a minimal MultiQC report-shaped Mongo doc for tests."""
    new_id = ObjectId()
    return {
        "_id": new_id,
        "id": str(new_id),
        "data_collection_id": data_collection_id,
        "metadata": {
            "samples": [],
            "modules": [],
            "plots": {},
            "sample_mappings": {},
            "canonical_samples": [],
        },
        "s3_location": f"s3://test-bucket/{data_collection_id}/{suffix}/multiqc.parquet",
        "original_file_path": f"/tmp/{suffix}/multiqc.parquet",
        "file_size_bytes": 1024,
        "report_name": f"Report {suffix}",
    }


@pytest.fixture
def mock_multiqc_collection():
    """Patch the multiqc_collection used by the utils module with a mongomock collection."""
    client = mongomock.MongoClient()
    db = client.test_db
    collection = db.multiqc_reports

    with patch(
        "depictio.api.v1.endpoints.multiqc_endpoints.utils.multiqc_collection",
        collection,
    ):
        yield collection
        client.close()


@pytest.mark.asyncio
async def test_delete_all_multiqc_reports_for_dc_deletes_matching_docs(mock_multiqc_collection):
    """Bulk delete removes all reports for the target DC and leaves others intact."""
    target_dc = str(ObjectId())
    other_dc = str(ObjectId())

    mock_multiqc_collection.insert_many(
        [
            _build_report_doc(target_dc, "a"),
            _build_report_doc(target_dc, "b"),
            _build_report_doc(target_dc, "c"),
            _build_report_doc(other_dc, "d"),
        ]
    )

    result = await delete_all_multiqc_reports_for_dc(target_dc, delete_s3_files=False)

    assert result["deleted_count"] == 3
    assert result["deleted_s3_count"] == 0
    assert mock_multiqc_collection.count_documents({"data_collection_id": target_dc}) == 0
    assert mock_multiqc_collection.count_documents({"data_collection_id": other_dc}) == 1


@pytest.mark.asyncio
async def test_delete_all_multiqc_reports_for_dc_empty_returns_zero(mock_multiqc_collection):
    """Bulk delete on a DC with no reports returns zero counts (not an error)."""
    empty_dc = str(ObjectId())

    result = await delete_all_multiqc_reports_for_dc(empty_dc, delete_s3_files=False)

    assert result == {"deleted_count": 0, "deleted_s3_count": 0}


@pytest.mark.asyncio
async def test_delete_all_multiqc_reports_for_dc_with_s3(mock_multiqc_collection):
    """When delete_s3_files=True, S3 helper is invoked once per report and counted on success."""
    target_dc = str(ObjectId())
    mock_multiqc_collection.insert_many(
        [
            _build_report_doc(target_dc, "a"),
            _build_report_doc(target_dc, "b"),
        ]
    )

    class _Paginator:
        def paginate(self, **_kwargs):
            return [{"Contents": [{"Key": "fake/key"}]}]

    with patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.s3_client") as mock_s3:
        mock_s3.get_paginator.return_value = _Paginator()
        mock_s3.delete_objects.return_value = {}

        result = await delete_all_multiqc_reports_for_dc(target_dc, delete_s3_files=True)

    assert result["deleted_count"] == 2
    assert result["deleted_s3_count"] == 2
    assert mock_multiqc_collection.count_documents({"data_collection_id": target_dc}) == 0


@pytest.mark.asyncio
async def test_delete_all_multiqc_reports_for_dc_continues_on_s3_failure(mock_multiqc_collection):
    """An S3 deletion failure is logged but does not block the Mongo delete_many."""
    target_dc = str(ObjectId())
    mock_multiqc_collection.insert_many(
        [
            _build_report_doc(target_dc, "a"),
            _build_report_doc(target_dc, "b"),
        ]
    )

    with patch("depictio.api.v1.endpoints.multiqc_endpoints.utils.s3_client") as mock_s3:
        mock_s3.get_paginator.side_effect = RuntimeError("boom")

        result = await delete_all_multiqc_reports_for_dc(target_dc, delete_s3_files=True)

    assert result["deleted_count"] == 2
    assert result["deleted_s3_count"] == 0
    assert mock_multiqc_collection.count_documents({"data_collection_id": target_dc}) == 0


@pytest.mark.asyncio
async def test_delete_all_multiqc_reports_for_dc_mongo_failure_raises(mock_multiqc_collection):
    """A Mongo delete_many failure surfaces as an HTTPException 500."""
    target_dc = str(ObjectId())

    with patch.object(
        mock_multiqc_collection,
        "delete_many",
        side_effect=RuntimeError("mongo down"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await delete_all_multiqc_reports_for_dc(target_dc, delete_s3_files=False)

    assert exc_info.value.status_code == 500
    assert "Failed to delete MultiQC reports" in exc_info.value.detail
