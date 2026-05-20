import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import db, projects_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _check_multiqc_uniformity_from_uploads,
    _create_dc_from_upload,
    _create_multiqc_dc_from_uploads,
    _delete_data_collection_by_id,
    _delete_orphan_links_for_dc,
    _get_data_collection_polars_schema,
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


@datacollections_endpoint_router.get("/polars_schema/{data_collection_id}")
async def polars_schema(
    data_collection_id: PyObjectId,
    current_user: str = Depends(get_user_or_anonymous),
) -> dict[str, str]:
    """Return the Delta-table schema as ``{column: polars-dtype-name}``.

    Used by the advanced-viz builder UI for editor-time validation of column
    bindings (see depictio/models/components/advanced_viz/schemas.py).
    """
    return await _get_data_collection_polars_schema(data_collection_id, current_user)


@datacollections_endpoint_router.get("/viz-suggestions/{data_collection_id}")
async def viz_suggestions(
    data_collection_id: PyObjectId,
    min_confidence: float = 1.0,
    current_user: str = Depends(get_user_or_anonymous),
) -> dict:
    """Reverse-lookup viz kinds + known producers compatible with this DC.

    Drives the React DC card's "Suggested visualisations" chip row and the
    component-creation flow's DC pre-filter. Both surfaces share the same
    pure-Python suggestion engine in
    `depictio/models/components/advanced_viz/schemas.py`:

      - `viz_kinds`: every AdvancedVizKind whose required role schema can be
        satisfied by some column-dtype combination in this DC. Each entry
        carries per-role candidate columns the UI uses to pre-fill bindings.
      - `producers`: known tool outputs (DESeq2 results, mosdepth coverage,
        Bracken, …) whose column-name fingerprint matches this DC. When a
        producer matches, the UI can pre-fill bindings exactly rather than
        guessing.

    Query params:
        min_confidence: 0.0-1.0 — minimum fraction of required roles that
            must have a candidate column for a viz kind to appear in the
            suggestions list. Default 1.0 = strict (only full matches).
    """
    from depictio.models.components.advanced_viz.producers import get_producer
    from depictio.models.components.advanced_viz.schemas import (
        suggest_producers,
        suggest_viz_kinds,
    )

    schema = await _get_data_collection_polars_schema(data_collection_id, current_user)

    viz = suggest_viz_kinds(schema, min_confidence=min_confidence)
    producer_hits = suggest_producers(schema)

    producers = []
    for name, ratio in producer_hits:
        p = get_producer(name)
        producers.append(
            {
                "name": name,
                "confidence": ratio,
                "tool": p.tool if p else name,
                "description": p.description if p else "",
                "feeds_viz": list(p.feeds_viz) if p else [],
            }
        )

    return {
        "data_collection_id": str(data_collection_id),
        "schema": schema,
        "viz_kinds": [
            {
                "viz_kind": s.viz_kind,
                "confidence": s.confidence,
                "role_candidates": s.role_candidates,
            }
            for s in viz
        ],
        "producers": producers,
    }


class SuggestFromColumnsRequest(BaseModel):
    """Body for the pre-DC viz suggestion endpoint.

    The DC creation modal calls this with just column names parsed from the
    file header — before the file is uploaded. Producer fingerprints match on
    column names alone, so name-only input is enough to detect DESeq2 results,
    mosdepth, Bracken, QIIME2, etc.
    """

    columns: list[str] = Field(..., min_length=1)


@datacollections_endpoint_router.post("/suggest-from-columns")
async def suggest_from_columns(
    body: SuggestFromColumnsRequest,
    current_user: str = Depends(get_user_or_anonymous),
) -> dict:
    """Run the producer suggestion engine on a bare column list (no DC required).

    Used by the DC-creation modal to decide whether to surface a passive
    "looks like X" hint vs. the coordinates fallback toggle. Only producer
    fingerprints run here — viz-kind reverse lookup needs dtype info that
    isn't available until the file is parsed server-side.
    """
    from depictio.models.components.advanced_viz.producers import get_producer
    from depictio.models.components.advanced_viz.schemas import suggest_producers

    # suggest_producers only inspects schema keys; the dtype values are unused
    # by the fingerprint path, so a sentinel value is fine.
    producer_hits = suggest_producers({c: "" for c in body.columns})

    producers: list[dict] = []
    for name, ratio in producer_hits:
        p = get_producer(name)
        producers.append(
            {
                "name": name,
                "confidence": ratio,
                "tool": p.tool if p else name,
                "description": p.description if p else "",
                "feeds_viz": list(p.feeds_viz) if p else [],
            }
        )

    return {"producers": producers}


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


@datacollections_endpoint_router.post("/{data_collection_id}/append")
async def append_table_dc(
    data_collection_id: str,
    files: list[UploadFile] = File(...),
    current_user=Depends(get_current_user),
):
    """Append uploaded files to an existing Table DC (preserves rows).

    Mirrors the MultiQC `/append` semantics. Each file is read into memory
    under per-file 50MB / total 500MB caps before being concatenated with
    the existing delta-backed rows.
    """
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        append_table_uploads,
    )
    from depictio.api.v1.endpoints.multiqc_endpoints.routes import (
        _read_multiqc_uploads_with_caps,
    )

    decoded_files = await _read_multiqc_uploads_with_caps(files)
    return await asyncio.to_thread(
        append_table_uploads,
        data_collection_id=data_collection_id,
        decoded_files=decoded_files,
        current_user=current_user,
    )


@datacollections_endpoint_router.post("/{data_collection_id}/replace")
async def replace_table_dc(
    data_collection_id: str,
    files: list[UploadFile] = File(...),
    current_user=Depends(get_current_user),
):
    """Replace all rows of a Table DC with the uploaded files."""
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        replace_table_uploads,
    )
    from depictio.api.v1.endpoints.multiqc_endpoints.routes import (
        _read_multiqc_uploads_with_caps,
    )

    decoded_files = await _read_multiqc_uploads_with_caps(files)
    return await asyncio.to_thread(
        replace_table_uploads,
        data_collection_id=data_collection_id,
        decoded_files=decoded_files,
        current_user=current_user,
    )


@datacollections_endpoint_router.delete("/{data_collection_id}/data")
async def clear_table_dc(
    data_collection_id: str,
    current_user=Depends(get_current_user),
):
    """Wipe a Table DC's rows on S3 + Mongo, keeping the DC config intact."""
    from depictio.api.v1.endpoints.datacollections_endpoints.table_manage import (
        clear_table_data,
    )

    return await asyncio.to_thread(
        clear_table_data,
        data_collection_id=data_collection_id,
        current_user=current_user,
    )


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
    lat_column: str | None = Form(None),
    lon_column: str | None = Form(None),
    file: UploadFile = File(...),
    current_user=Depends(get_user_or_anonymous),
):
    """Create a data collection from an uploaded file (basic projects).

    Wraps the same scan + process pipeline used by depictio-cli, exposing
    it directly to the React UI so we don't need to round-trip through
    Dash anymore. Tolerates missing tokens (single-user / public mode); the
    project-permission check inside ``_create_dc_from_upload`` still gates
    write access.

    When ``lat_column`` and ``lon_column`` are provided, the resulting DC
    config is a ``DCTableCoordinatesConfig`` (still ``dc_type='table'``) —
    consumed by Map components for geographic data.
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
        lat_column=lat_column,
        lon_column=lon_column,
    )


@datacollections_endpoint_router.post("/multiqc_uniformity_check")
async def multiqc_uniformity_check(
    files: list[UploadFile] = File(...),
    current_user=Depends(get_user_or_anonymous),
):
    """Dry-run MultiQC uniformity check (no DC created, no S3 writes).

    Lets the React Create DC modal preview the same checks the create flow
    runs (modules, plots, version, samples) before the user commits to Create.
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

    return await asyncio.to_thread(_check_multiqc_uniformity_from_uploads, decoded_files)


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
