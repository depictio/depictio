import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import db, projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _create_dc_from_upload,
    _create_multiqc_dc_from_uploads,
    _delete_data_collection_by_id,
    _delete_orphan_links_for_dc,
    _get_data_collection_specs,
    _update_data_collection_name,
    _update_dc_specific_properties,
    generate_join_dict,
)
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.endpoints.workflow_endpoints.routes import get_workflow_from_id
from depictio.models.models.base import PyObjectId

datacollections_endpoint_router = APIRouter()

workflows_collection = db[settings.mongodb.collections.workflow_collection]


@datacollections_endpoint_router.get("/specs/{data_collection_id}")
async def specs(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
):
    return await _get_data_collection_specs(data_collection_id, current_user)


@datacollections_endpoint_router.delete("/delete/{workflow_id}/{data_collection_id}")
async def delete_datacollection(
    workflow_id: str,
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    (
        workflow_oid,
        data_collection_oid,
        workflow,
        data_collection,
        user_oid,
    ) = validate_workflow_and_collection(
        workflows_collection,
        current_user.id,  # type: ignore[possibly-unbound-attribute]
        workflow_id,
        data_collection_id,
    )

    # delete the data collection from the workflow
    workflows_collection.update_one(
        {"_id": workflow_oid},
        {"$pull": {"data_collections": data_collection}},
    )

    links_pulled = _delete_orphan_links_for_dc(data_collection_id)
    if links_pulled:
        logger.info(
            f"Removed orphan cross-DC links from {links_pulled} project(s) after deleting DC {data_collection_id} (workflow {workflow_id})"
        )

    return {"message": "Data collection deleted successfully."}


@datacollections_endpoint_router.get("/get_dc_joined/{workflow_id}")
async def get_dc_joined(workflow_id: str, current_user: str = Depends(get_user_or_anonymous)):
    """
    Retrieve join details for data collections in a workflow.

    Now reads from project-level joins (project.joins[]) instead of
    DC-level join configs (dc.config.join).
    """
    # Retrieve workflow
    workflow = await get_workflow_from_id(workflow_id, current_user=current_user)

    # Get project containing this workflow
    project = None
    if workflow:
        project_id = workflow.get("project_id")
        if project_id:
            try:
                from depictio.api.v1.endpoints.projects_endpoints.routes import get_project_from_id

                # Use skip_enrichment=True for faster query (we only need joins[])
                project_response = await get_project_from_id(
                    project_id=str(project_id),
                    skip_enrichment=True,
                    current_user=current_user,
                )
                # Handle both dict and object responses
                project = (
                    project_response
                    if isinstance(project_response, dict)
                    else project_response.model_dump()
                )
            except Exception as e:
                logger.warning(f"Failed to fetch project for workflow {workflow_id}: {e}")

    # Generate join dict from project-level joins
    join_details_map = generate_join_dict(workflow, project=project)

    return join_details_map


@datacollections_endpoint_router.get("/get_tag_from_id/{data_collection_id}")
async def get_tag_from_id(
    data_collection_id: str,
    current_user: str = Depends(get_user_or_anonymous),
):
    try:
        data_collection_oid = ObjectId(data_collection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use MongoDB aggregation to directly retrieve the specific data collection
    pipeline = [
        # Match projects containing this collection and with appropriate permissions
        {
            "$match": {
                "workflows.data_collections._id": data_collection_oid,
                "$or": [
                    {"permissions.owners._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers._id": current_user.id},  # type: ignore[possibly-unbound-attribute]
                    {"permissions.viewers": "*"},
                    {"is_public": True},
                ],
            }
        },
        # Unwind the workflows array
        {"$unwind": "$workflows"},
        # Unwind the data_collections array
        {"$unwind": "$workflows.data_collections"},
        # Match the specific data collection ID
        {"$match": {"workflows.data_collections._id": data_collection_oid}},
        # Return only the data collection
        {"$replaceRoot": {"newRoot": "$workflows.data_collections"}},
    ]

    result = list(projects_collection.aggregate(pipeline))

    if not result:
        raise HTTPException(status_code=404, detail="Data collection not found or access denied.")

    if len(result) > 1:
        raise HTTPException(
            status_code=500, detail="Multiple data collections found for the same ID."
        )

    dc_tag = result[0]["data_collection_tag"]

    return dc_tag


@datacollections_endpoint_router.put("/{data_collection_id}/name")
async def update_data_collection_name(
    data_collection_id: str,
    request_data: dict,
    current_user: str = Depends(get_current_user),
):
    """Update the name of a data collection."""
    new_name = request_data.get("new_name")
    if new_name is None:
        raise HTTPException(status_code=400, detail="new_name is required")
    return await _update_data_collection_name(data_collection_id, new_name, current_user)


@datacollections_endpoint_router.patch("/{data_collection_id}/dc_specific_properties")
async def update_dc_specific_properties(
    data_collection_id: str,
    properties: dict,
    current_user: str = Depends(get_current_user),
):
    """Partially update dc_specific_properties for a data collection."""
    return await _update_dc_specific_properties(data_collection_id, properties, current_user)


@datacollections_endpoint_router.delete("/{data_collection_id}")
async def delete_data_collection_by_id(
    data_collection_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete a data collection by its ID."""
    return await _delete_data_collection_by_id(data_collection_id, current_user)


@datacollections_endpoint_router.post("/create_from_upload")
async def create_data_collection_from_upload(
    project_id: str = Form(...),
    name: str = Form(...),
    data_type: str = Form("table"),
    file_format: str = Form("csv"),
    separator: str = Form(","),
    custom_separator: str | None = Form(None),
    compression: str = Form("none"),
    has_header: bool = Form(True),
    description: str = Form(""),
    file: UploadFile = File(...),
    current_user=Depends(get_user_or_anonymous),
):
    """Create a data collection from an uploaded file (basic projects).

    Wraps the same scan + process pipeline used by depictio-cli, exposing
    it directly to the React UI so we don't need to round-trip through
    Dash anymore. Tolerates missing tokens (single-user / public mode); the
    project-permission check inside ``_create_dc_from_upload`` still gates
    write access.
    """
    file_bytes = await file.read()
    return await asyncio.to_thread(
        _create_dc_from_upload,
        project_id=project_id,
        name=name,
        description=description,
        data_type=data_type,
        file_format=file_format,
        separator=separator,
        custom_separator=custom_separator,
        compression=compression,
        has_header=has_header,
        file_bytes=file_bytes,
        filename=file.filename or "upload.dat",
        current_user=current_user,
    )


@datacollections_endpoint_router.post("/create_multiqc_from_upload")
async def create_multiqc_data_collection_from_upload(
    project_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    files: list[UploadFile] = File(...),
    current_user=Depends(get_user_or_anonymous),
):
    """Create a MultiQC data collection from one or more uploaded multiqc.parquet files.

    Each file's effective name is the browser-provided ``webkitRelativePath``
    (``run_01/multiqc_data/multiqc.parquet``) so the helper can group reports
    by parent folder. Per-file cap 50MB, total cap 500MB; per-file cap is
    enforced inside the helper, total is enforced here against the headers
    so we can fail fast before reading bodies.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    decoded_files: list[tuple[bytes, str]] = []
    running_total = 0
    for upload in files:
        body = await upload.read()
        running_total += len(body)
        if running_total > 500 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Total upload size {running_total / (1024 * 1024):.1f}MB exceeds 500MB limit."
                ),
            )
        decoded_files.append((body, upload.filename or "upload.parquet"))

    return await asyncio.to_thread(
        _create_multiqc_dc_from_uploads,
        project_id=project_id,
        name=name,
        description=description,
        decoded_files=decoded_files,
        current_user=current_user,
    )
