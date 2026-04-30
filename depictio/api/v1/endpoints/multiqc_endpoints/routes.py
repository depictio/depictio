"""
MultiQC Reports API endpoints.

This module provides REST API endpoints for managing MultiQC reports:
- List MultiQC reports for a data collection
- Get specific MultiQC report details
- Delete MultiQC reports
- Get MultiQC report metadata and plots
"""

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from depictio.api.v1.db import multiqc_collection, projects_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission
from depictio.api.v1.endpoints.multiqc_endpoints.utils import (
    check_duplicate_multiqc_report,
    create_multiqc_report_in_db,
    delete_all_multiqc_reports_for_dc,
    delete_multiqc_report_by_id,
    generate_multiqc_download_url,
    get_multiqc_report_by_id,
    get_multiqc_report_metadata_by_id,
    get_multiqc_reports_by_data_collection,
    update_multiqc_report_by_id,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.multiqc_reports import MultiQCReport
from depictio.models.models.users import User


def _project_id_for_dc(data_collection_id: str) -> str | None:
    """Return the owning project's id for a DC, or None if unknown.

    Walks ``projects.workflows[].data_collections[]`` in Mongo to locate
    the workflow that owns the DC. The shape mirrors what the rest of
    the codebase already does (see e.g. ``_fetch_s3_locations_from_dc``);
    we don't have a flat dc → project index.
    """
    project = projects_collection.find_one(
        {"workflows.data_collections._id": ObjectId(data_collection_id)},
        {"_id": 1},
    )
    return str(project["_id"]) if project else None


def _require_dc_editor_or_404(data_collection_id: str, user: User) -> None:
    """Authorize a destructive call against a MultiQC DC.

    Mirrors the project-permission check that the dashboard delete uses
    so a stolen JWT can't reach across tenants and wipe another user's
    MultiQC reports + S3 parquets via the bulk endpoint. Returns 404
    instead of 403 when the DC isn't found OR the user has no rights —
    don't leak existence to non-members.
    """
    project_id = _project_id_for_dc(data_collection_id)
    if not project_id or not check_project_permission(project_id, user, "editor"):
        raise HTTPException(
            status_code=404,
            detail=f"Data collection {data_collection_id} not found",
        )


class MultiQCReportResponse(BaseModel):
    """Response model for MultiQC report data."""

    report: MultiQCReport
    data_collection_tag: str | None = None
    workflow_name: str | None = None


class MultiQCReportsListResponse(BaseModel):
    """Response model for list of MultiQC reports."""

    reports: list[MultiQCReportResponse]
    total_count: int


router = APIRouter(tags=["MultiQC"])


@router.post(
    "/reports",
    response_model=MultiQCReportResponse,
    summary="Create a new MultiQC report",
)
async def create_multiqc_report(
    report: MultiQCReport,
    current_user: User = Depends(get_current_user),
):
    """
    Create a new MultiQC report in the database.

    Args:
        report: MultiQC report data
        current_user: Authenticated user

    Returns:
        Created MultiQC report with assigned ID
    """
    saved_report = await create_multiqc_report_in_db(report)

    response = MultiQCReportResponse(
        report=saved_report,
        data_collection_tag="multiqc_data",  # Could be retrieved from data collection if needed
        workflow_name="multiqc_workflow",  # Could be retrieved from workflow if needed
    )

    return response


@router.put(
    "/reports/{report_id}",
    response_model=MultiQCReportResponse,
    summary="Update an existing MultiQC report",
)
async def update_multiqc_report(
    report_id: str,
    report: MultiQCReport,
    current_user: User = Depends(get_current_user),
):
    """
    Update an existing MultiQC report in the database.

    This endpoint is primarily used for overwrite operations where the S3 file
    is updated in place and the metadata needs to be refreshed while preserving
    the report ID.

    Args:
        report_id: ID of the report to update
        report: Updated MultiQC report data
        current_user: Authenticated user

    Returns:
        Updated MultiQC report with preserved ID
    """
    updated_report = await update_multiqc_report_by_id(report_id, report)

    response = MultiQCReportResponse(
        report=updated_report,
        data_collection_tag="multiqc_data",  # Could be retrieved from data collection if needed
        workflow_name="multiqc_workflow",  # Could be retrieved from workflow if needed
    )

    return response


@router.get(
    "/reports/check-duplicate",
    response_model=dict,
    summary="Check if a MultiQC report already exists",
)
async def check_duplicate_report(
    data_collection_id: str = Query(..., description="ID of the data collection"),
    original_file_path: str = Query(..., description="Original file path of the MultiQC report"),
    current_user: User = Depends(get_current_user),
):
    """
    Check if a MultiQC report already exists for the same data collection and file path.

    Args:
        data_collection_id: ID of the data collection
        original_file_path: Original local file path of the MultiQC report
        current_user: Authenticated user

    Returns:
        Dict with exists flag and report data if found
    """
    existing_report = await check_duplicate_multiqc_report(data_collection_id, original_file_path)

    if existing_report:
        return {
            "exists": True,
            "report_id": str(existing_report.id),
            "report": existing_report.model_dump(mode="json"),
        }
    else:
        return {"exists": False, "report_id": None, "report": None}


@router.get(
    "/reports/data-collection/{data_collection_id}",
    response_model=MultiQCReportsListResponse,
    summary="List MultiQC reports for a data collection",
)
async def list_multiqc_reports_by_data_collection(
    data_collection_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """
    List all MultiQC reports associated with a specific data collection.

    Args:
        data_collection_id: ID of the data collection
        limit: Maximum number of reports to return
        offset: Number of reports to skip
        current_user: Authenticated user

    Returns:
        List of MultiQC reports with metadata
    """
    reports, total_count = await get_multiqc_reports_by_data_collection(
        data_collection_id, limit, offset
    )

    report_responses = [
        MultiQCReportResponse(
            report=report, data_collection_tag="multiqc_data", workflow_name="multiqc_workflow"
        )
        for report in reports
    ]

    return MultiQCReportsListResponse(reports=report_responses, total_count=total_count)


@router.get(
    "/reports/{report_id}",
    response_model=MultiQCReportResponse,
    summary="Get specific MultiQC report",
)
async def get_multiqc_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed information about a specific MultiQC report.

    Args:
        report_id: ID of the MultiQC report
        current_user: Authenticated user

    Returns:
        MultiQC report details with metadata
    """
    report = await get_multiqc_report_by_id(report_id)

    return MultiQCReportResponse(
        report=report, data_collection_tag="multiqc_data", workflow_name="multiqc_workflow"
    )


@router.delete(
    "/reports/{report_id}",
    response_model=dict,
    summary="Delete MultiQC report",
)
async def delete_multiqc_report(
    report_id: str,
    delete_s3_file: bool = Query(False, description="Whether to also delete the S3 file"),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a MultiQC report and optionally its S3 file.

    Args:
        report_id: ID of the MultiQC report to delete
        delete_s3_file: Whether to also delete the associated S3 file
        current_user: Authenticated user

    Returns:
        Deletion confirmation
    """
    try:
        report_oid = ObjectId(report_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid report id: {report_id}")

    report_doc = multiqc_collection.find_one({"_id": report_oid}, {"data_collection_id": 1})
    if not report_doc:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    _require_dc_editor_or_404(str(report_doc["data_collection_id"]), current_user)

    return await delete_multiqc_report_by_id(report_id, delete_s3_file)


@router.delete(
    "/reports/data-collection/{data_collection_id}",
    response_model=dict,
    summary="Bulk-delete all MultiQC reports for a data collection",
)
async def delete_all_reports_for_data_collection(
    data_collection_id: str,
    delete_s3_files: bool = Query(
        False, description="Whether to also delete the associated S3 parquet objects"
    ),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all MultiQC reports linked to a data collection in a single Mongo call.

    Optionally also deletes the underlying S3 parquet objects. Returns counts for
    both Mongo and S3 deletions.
    """
    try:
        ObjectId(data_collection_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=400, detail=f"Invalid data collection id: {data_collection_id}"
        )

    _require_dc_editor_or_404(data_collection_id, current_user)

    result = await delete_all_multiqc_reports_for_dc(data_collection_id, delete_s3_files)
    return {**result, "data_collection_id": data_collection_id}


@router.get(
    "/reports/{report_id}/sample-mappings",
    response_model=dict,
    summary="Get sample mappings for MultiQC report",
)
async def get_sample_mappings(
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get sample ID mappings from canonical IDs to MultiQC variants.

    This endpoint returns the mapping that allows filtering MultiQC visualizations
    based on canonical sample IDs from external metadata tables.

    Args:
        report_id: ID of the MultiQC report
        current_user: Authenticated user

    Returns:
        Dictionary with:
        - sample_mappings: Dict mapping canonical IDs to variant lists
        - canonical_samples: List of all canonical sample IDs
    """
    metadata = await get_multiqc_report_metadata_by_id(report_id)
    return {
        "sample_mappings": metadata.get("sample_mappings", {}),
        "canonical_samples": metadata.get("canonical_samples", []),
    }


@router.get(
    "/reports/{report_id}/metadata",
    response_model=dict,
    summary="Get MultiQC report metadata",
)
async def get_multiqc_report_metadata(
    report_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get the extracted metadata (samples, modules, plots) from a MultiQC report.

    Args:
        report_id: ID of the MultiQC report
        current_user: Authenticated user

    Returns:
        MultiQC metadata including samples, modules, and plots
    """
    return await get_multiqc_report_metadata_by_id(report_id)


@router.get(
    "/reports/{report_id}/download-url",
    response_model=dict,
    summary="Get download URL for MultiQC parquet file",
)
async def get_multiqc_download_url(
    report_id: str,
    expiration_hours: int = Query(24, ge=1, le=168, description="URL expiration in hours"),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a presigned URL to download the MultiQC parquet file from S3.

    Args:
        report_id: ID of the MultiQC report
        expiration_hours: How long the download URL should be valid (1-168 hours)
        current_user: Authenticated user

    Returns:
        Presigned download URL and metadata
    """
    return await generate_multiqc_download_url(report_id, expiration_hours)
