"""
API routes for universal DC linking system.

This module provides endpoints for:
- Creating, reading, updating, and deleting DC links
- Resolving filtered values through links
- Querying links by source or target DC

The link resolution endpoint is the primary integration point for Dash callbacks
to apply cross-DC filtering without pre-computed joins.
"""

from typing import Any

import polars as pl
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    deltatables_collection,
    multiqc_collection,
    projects_collection,
)
from depictio.api.v1.endpoints.links_endpoints.resolvers import get_resolver
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user
from depictio.models.models.base import PyObjectId
from depictio.models.models.links import (
    DCLink,
    LinkConfig,
    LinkCreateRequest,
    LinkResolutionRequest,
    LinkResolutionResponse,
    LinkUpdateRequest,
)
from depictio.models.models.users import User

# Define the router
links_endpoint_router = APIRouter()


def _get_project_or_404(project_id: str, current_user: User) -> dict:
    """Get project by ID or raise 404.

    Args:
        project_id: Project ID string
        current_user: Authenticated user

    Returns:
        Project document dict

    Raises:
        HTTPException: 404 if not found or 403 if no access
    """
    try:
        project_oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid project ID format: {project_id}")

    project = projects_collection.find_one({"_id": project_oid})
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Check permissions
    permissions = project.get("permissions", {})
    owners = permissions.get("owners", [])
    editors = permissions.get("editors", [])
    viewers = permissions.get("viewers", [])

    user_email = current_user.email
    is_admin = current_user.is_admin

    # Check if user has access
    has_access = (
        is_admin
        or user_email in owners
        or user_email in editors
        or user_email in viewers
        or project.get("is_public", False)
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied to project")

    return project


def _find_link_by_id(project: dict, link_id: str) -> tuple[DCLink | None, int]:
    """Find a link by ID in project links.

    Args:
        project: Project document
        link_id: Link ID to find

    Returns:
        Tuple of (link, index) or (None, -1) if not found
    """
    links = project.get("links", [])
    for i, link_data in enumerate(links):
        lid = str(link_data.get("id") or link_data.get("_id", ""))
        if lid == link_id:
            return DCLink(**link_data), i
    return None, -1


def _find_link_for_resolution(project: dict, source_dc_id: str, target_dc_id: str) -> DCLink | None:
    """Find a link between source and target DCs.

    Args:
        project: Project document
        source_dc_id: Source DC ID
        target_dc_id: Target DC ID

    Returns:
        DCLink if found and enabled, None otherwise
    """
    links = project.get("links", [])
    for link_data in links:
        if (
            link_data.get("source_dc_id") == source_dc_id
            and link_data.get("target_dc_id") == target_dc_id
            and link_data.get("enabled", True)
        ):
            return DCLink(**link_data)
    return None


async def _translate_filter_values(
    source_dc_id: str,
    filter_column: str,
    filter_values: list[Any],
    link_column: str,
) -> list[Any]:
    """Translate filter values from one column to another via source DC query.

    When filtering by column A but the link is defined on column B, this function
    queries the source DC to translate values from column A to column B.

    Example:
        Filter: habitat IN ["Groundwater", "Riverwater"]
        Link: sample (habitat -> sample)
        Query: SELECT sample FROM metadata WHERE habitat IN ["Groundwater", "Riverwater"]
        Returns: ["SRR10070131", "SRR10070132", "SRR10070133", ...]

    Args:
        source_dc_id: Data collection ID to query
        filter_column: Column being filtered (e.g., "habitat")
        filter_values: Values selected in filter (e.g., ["Groundwater"])
        link_column: Column used in link definition (e.g., "sample")

    Returns:
        List of unique values from link_column that match the filter

    Raises:
        HTTPException: If DC not found, Delta table not accessible, or columns missing
    """
    # Get Delta table location (try both string and ObjectId formats for compatibility)
    deltatable_doc = deltatables_collection.find_one({"data_collection_id": source_dc_id})
    if not deltatable_doc:
        # Try with ObjectId format
        deltatable_doc = deltatables_collection.find_one(
            {"data_collection_id": ObjectId(source_dc_id)}
        )
    if not deltatable_doc or "delta_table_location" not in deltatable_doc:
        logger.error(
            f"Delta table not found for DC {source_dc_id}. "
            f"Document exists: {deltatable_doc is not None}, "
            f"Has location: {deltatable_doc and 'delta_table_location' in deltatable_doc}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"Delta table not found for DC {source_dc_id}",
        )

    delta_table_location = deltatable_doc["delta_table_location"]
    logger.debug(f"Querying Delta table at {delta_table_location}")

    try:
        # Read Delta table with S3 credentials
        from depictio.api.v1.s3 import polars_s3_config

        df = pl.read_delta(delta_table_location, storage_options=polars_s3_config)

        # Validate columns exist
        if filter_column not in df.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Filter column '{filter_column}' not found in source DC. "
                f"Available: {', '.join(df.columns)}",
            )
        if link_column not in df.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Link column '{link_column}' not found in source DC. "
                f"Available: {', '.join(df.columns)}",
            )

        # Filter and extract link column values
        filtered_df = df.filter(pl.col(filter_column).is_in(filter_values))
        link_values = filtered_df[link_column].unique().to_list()

        logger.info(
            f"Column translation: {len(filter_values)} {filter_column} values -> "
            f"{len(link_values)} {link_column} values (from {len(filtered_df)} rows)"
        )

        return link_values

    except Exception as e:
        logger.error(f"Error querying source DC for column translation: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query source DC for column translation: {str(e)}",
        )


async def _get_multiqc_sample_mappings(target_dc_id: str) -> dict[str, list[str]]:
    """Fetch and aggregate sample mappings from ALL MultiQC reports for a DC.

    A single MultiQC data collection can have multiple reports (e.g., from different
    parquet files). Each report may have different samples with their own mappings.
    This function aggregates all sample_mappings from all reports for the DC.

    Args:
        target_dc_id: MultiQC data collection ID

    Returns:
        Aggregated sample mappings dict or empty dict if not found
    """
    try:
        # Find ALL reports for this DC, not just the first one
        aggregated_mappings: dict[str, list[str]] = {}

        cursor = multiqc_collection.find(
            {"data_collection_id": target_dc_id},
            {"metadata.sample_mappings": 1},
        )

        report_count = 0
        for report in cursor:
            report_count += 1
            mappings = report.get("metadata", {}).get("sample_mappings", {})
            if mappings:
                # Merge mappings - if same key exists, combine variant lists
                for sample_id, variants in mappings.items():
                    if sample_id in aggregated_mappings:
                        # Add new variants, avoiding duplicates
                        existing = set(aggregated_mappings[sample_id])
                        for v in variants:
                            if v not in existing:
                                aggregated_mappings[sample_id].append(v)
                    else:
                        aggregated_mappings[sample_id] = list(variants)

        if aggregated_mappings:
            logger.debug(
                f"Aggregated {len(aggregated_mappings)} sample mappings "
                f"from {report_count} MultiQC reports for DC {target_dc_id}"
            )
        return aggregated_mappings

    except Exception as e:
        logger.warning(f"Failed to fetch MultiQC sample mappings for {target_dc_id}: {e}")
    return {}


# ============================================================================
# CRUD Endpoints
# ============================================================================


@links_endpoint_router.get(
    "/{project_id}",
    response_model=list[DCLink],
    summary="Get all links for a project",
)
async def get_project_links(
    project_id: str = Path(..., description="Project ID"),
    current_user: User = Depends(get_current_user),
) -> list[DCLink]:
    """Get all DC links defined for a project.

    Args:
        project_id: Project ID to get links for
        current_user: Authenticated user

    Returns:
        List of DCLink objects
    """
    project = _get_project_or_404(project_id, current_user)
    links_data = project.get("links", [])

    links = []
    for link_data in links_data:
        try:
            links.append(DCLink(**link_data))
        except Exception as e:
            logger.warning(f"Failed to parse link: {e}")

    logger.info(f"Retrieved {len(links)} links for project {project_id}")
    return links


@links_endpoint_router.get(
    "/{project_id}/source/{dc_id}",
    response_model=list[DCLink],
    summary="Get links by source DC",
)
async def get_links_by_source_dc(
    project_id: str = Path(..., description="Project ID"),
    dc_id: str = Path(..., description="Source data collection ID"),
    current_user: User = Depends(get_current_user),
) -> list[DCLink]:
    """Get all links where the specified DC is the source.

    Useful for finding all target DCs that can be updated when
    a filter is applied to the source DC.

    Args:
        project_id: Project ID
        dc_id: Source data collection ID
        current_user: Authenticated user

    Returns:
        List of DCLink objects with matching source_dc_id
    """
    project = _get_project_or_404(project_id, current_user)
    links_data = project.get("links", [])

    links = []
    for link_data in links_data:
        if link_data.get("source_dc_id") == dc_id:
            try:
                links.append(DCLink(**link_data))
            except Exception as e:
                logger.warning(f"Failed to parse link: {e}")

    logger.info(f"Found {len(links)} links with source DC {dc_id}")
    return links


@links_endpoint_router.get(
    "/{project_id}/target/{dc_id}",
    response_model=list[DCLink],
    summary="Get links by target DC",
)
async def get_links_by_target_dc(
    project_id: str = Path(..., description="Project ID"),
    dc_id: str = Path(..., description="Target data collection ID"),
    current_user: User = Depends(get_current_user),
) -> list[DCLink]:
    """Get all links where the specified DC is the target.

    Useful for finding what source DCs can drive filtering for this target.

    Args:
        project_id: Project ID
        dc_id: Target data collection ID
        current_user: Authenticated user

    Returns:
        List of DCLink objects with matching target_dc_id
    """
    project = _get_project_or_404(project_id, current_user)
    links_data = project.get("links", [])

    links = []
    for link_data in links_data:
        if link_data.get("target_dc_id") == dc_id:
            try:
                links.append(DCLink(**link_data))
            except Exception as e:
                logger.warning(f"Failed to parse link: {e}")

    logger.info(f"Found {len(links)} links with target DC {dc_id}")
    return links


@links_endpoint_router.post(
    "/{project_id}",
    response_model=DCLink,
    summary="Create a new link",
    status_code=201,
)
async def create_link(
    request: LinkCreateRequest,
    project_id: str = Path(..., description="Project ID"),
    current_user: User = Depends(get_current_user),
) -> DCLink:
    """Create a new DC link for a project.

    Args:
        request: Link creation request
        project_id: Project ID
        current_user: Authenticated user

    Returns:
        Created DCLink object
    """
    project = _get_project_or_404(project_id, current_user)

    # Check user has edit permissions
    permissions = project.get("permissions", {})
    owners = permissions.get("owners", [])
    editors = permissions.get("editors", [])

    if not current_user.is_admin and current_user.email not in owners + editors:
        raise HTTPException(status_code=403, detail="Edit permission required to create links")

    # Create new link
    new_link = DCLink(
        id=PyObjectId(),
        source_dc_id=request.source_dc_id,
        source_column=request.source_column,
        target_dc_id=request.target_dc_id,
        target_type=request.target_type,
        link_config=request.link_config,
        description=request.description,
        enabled=request.enabled,
    )

    # Add to project
    link_dict = new_link.model_dump()
    link_dict["id"] = str(new_link.id)

    result = projects_collection.update_one(
        {"_id": ObjectId(project_id)},
        {"$push": {"links": link_dict}},
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to create link")

    logger.info(
        f"Created link {new_link.id} in project {project_id}: "
        f"{request.source_dc_id} -> {request.target_dc_id}"
    )
    return new_link


@links_endpoint_router.put(
    "/{project_id}/{link_id}",
    response_model=DCLink,
    summary="Update a link",
)
async def update_link(
    request: LinkUpdateRequest,
    project_id: str = Path(..., description="Project ID"),
    link_id: str = Path(..., description="Link ID to update"),
    current_user: User = Depends(get_current_user),
) -> DCLink:
    """Update an existing DC link.

    Only provided fields are updated.

    Args:
        request: Update request with fields to modify
        project_id: Project ID
        link_id: Link ID to update
        current_user: Authenticated user

    Returns:
        Updated DCLink object
    """
    project = _get_project_or_404(project_id, current_user)

    # Check edit permissions
    permissions = project.get("permissions", {})
    owners = permissions.get("owners", [])
    editors = permissions.get("editors", [])

    if not current_user.is_admin and current_user.email not in owners + editors:
        raise HTTPException(status_code=403, detail="Edit permission required to update links")

    # Find existing link
    existing_link, link_index = _find_link_by_id(project, link_id)
    if existing_link is None:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")

    # Build update dict with only provided fields
    update_data = request.model_dump(exclude_none=True)
    if not update_data:
        return existing_link  # Nothing to update

    # Apply updates to link
    link_dict = existing_link.model_dump()
    link_dict.update(update_data)

    # Handle link_config specially - merge with existing
    if request.link_config:
        existing_config = existing_link.link_config.model_dump()
        new_config = request.link_config.model_dump(exclude_none=True)
        existing_config.update(new_config)
        link_dict["link_config"] = existing_config

    # Ensure ID is preserved as string
    link_dict["id"] = link_id

    # Update in database
    result = projects_collection.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {f"links.{link_index}": link_dict}},
    )

    if result.modified_count == 0:
        logger.warning(f"No changes made to link {link_id}")

    updated_link = DCLink(**link_dict)
    logger.info(f"Updated link {link_id} in project {project_id}")
    return updated_link


@links_endpoint_router.delete(
    "/{project_id}/{link_id}",
    status_code=204,
    summary="Delete a link",
)
async def delete_link(
    project_id: str = Path(..., description="Project ID"),
    link_id: str = Path(..., description="Link ID to delete"),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a DC link.

    Args:
        project_id: Project ID
        link_id: Link ID to delete
        current_user: Authenticated user
    """
    project = _get_project_or_404(project_id, current_user)

    # Check edit permissions
    permissions = project.get("permissions", {})
    owners = permissions.get("owners", [])
    editors = permissions.get("editors", [])

    if not current_user.is_admin and current_user.email not in owners + editors:
        raise HTTPException(status_code=403, detail="Edit permission required to delete links")

    # Find link to confirm it exists
    existing_link, _ = _find_link_by_id(project, link_id)
    if existing_link is None:
        raise HTTPException(status_code=404, detail=f"Link not found: {link_id}")

    # Remove from database
    result = projects_collection.update_one(
        {"_id": ObjectId(project_id)},
        {"$pull": {"links": {"id": link_id}}},
    )

    if result.modified_count == 0:
        # Try with _id field (MongoDB format)
        result = projects_collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$pull": {"links": {"_id": link_id}}},
        )

    logger.info(f"Deleted link {link_id} from project {project_id}")


# ============================================================================
# Resolution Endpoint
# ============================================================================


@links_endpoint_router.post(
    "/{project_id}/resolve",
    response_model=LinkResolutionResponse,
    summary="Resolve filter values via link",
)
async def resolve_link(
    request: LinkResolutionRequest,
    project_id: str = Path(..., description="Project ID"),
    current_user: User = Depends(get_current_user),
) -> LinkResolutionResponse:
    """Resolve filtered values from source DC to target DC via link.

    This is the primary endpoint for cross-DC filtering. When a filter is
    applied to a source DC, call this endpoint to get the resolved values
    that should be applied to the target DC.

    The resolution process:
    1. Find the link definition for source_dc -> target_dc
    2. Get the appropriate resolver based on link_config.resolver
    3. For MultiQC targets with sample_mapping resolver, auto-fetch mappings if not provided
    4. Resolve source values to target identifiers
    5. Return resolved values with metadata

    Args:
        request: Resolution request with source DC, column, filter values, and target DC
        project_id: Project ID
        current_user: Authenticated user

    Returns:
        LinkResolutionResponse with resolved values and metadata

    Raises:
        HTTPException: 404 if no link found between source and target DCs
    """
    project = _get_project_or_404(project_id, current_user)

    # Find link between source and target
    link = _find_link_for_resolution(project, request.source_dc_id, request.target_dc_id)

    if link is None:
        raise HTTPException(
            status_code=404,
            detail=f"No enabled link found from {request.source_dc_id} to {request.target_dc_id}",
        )

    logger.info(
        f"Resolving link {link.id}: {request.source_dc_id}:{request.source_column} "
        f"-> {request.target_dc_id} ({link.target_type})"
    )

    # Translate filter values if filtering by different column than link column
    values_to_resolve = request.filter_values
    if request.source_column != link.source_column:
        logger.info(
            f"Filter column '{request.source_column}' differs from link column '{link.source_column}'. "
            f"Translating filter values via source DC query."
        )
        # Query source DC to translate filter values to link column values
        translated_values = await _translate_filter_values(
            source_dc_id=request.source_dc_id,
            filter_column=request.source_column,
            filter_values=request.filter_values,
            link_column=link.source_column,
        )
        logger.info(
            f"Translated {len(request.filter_values)} {request.source_column} values "
            f"to {len(translated_values)} {link.source_column} values"
        )
        values_to_resolve = translated_values

    # Get resolver
    try:
        resolver = get_resolver(link.link_config.resolver)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Prepare link config - auto-fetch sample mappings for MultiQC if needed
    effective_config = link.link_config

    if (
        link.target_type == "multiqc"
        and link.link_config.resolver == "sample_mapping"
        and not link.link_config.mappings
    ):
        # Auto-fetch sample mappings from MultiQC report
        sample_mappings = await _get_multiqc_sample_mappings(link.target_dc_id)
        if sample_mappings:
            # Create new config with fetched mappings
            effective_config = LinkConfig(
                resolver=link.link_config.resolver,
                mappings=sample_mappings,
                pattern=link.link_config.pattern,
                target_field=link.link_config.target_field,
                case_sensitive=link.link_config.case_sensitive,
            )
            logger.info(
                f"Auto-fetched {len(sample_mappings)} sample mappings for MultiQC DC "
                f"{link.target_dc_id}"
            )

    # Resolve values
    resolved_values, unmapped_values = resolver.resolve(
        source_values=values_to_resolve,
        link_config=effective_config,
        target_known_values=None,  # Could be enhanced to fetch from target DC
    )

    response = LinkResolutionResponse(
        resolved_values=resolved_values,
        link_id=str(link.id),
        resolver_used=link.link_config.resolver,
        match_count=len(resolved_values),
        target_type=link.target_type,
        source_count=len(request.filter_values),
        unmapped_values=unmapped_values,
    )

    logger.info(
        f"Link resolution complete: {len(request.filter_values)} source values "
        f"-> {len(resolved_values)} resolved values"
    )

    return response


@links_endpoint_router.get(
    "/{project_id}/resolvers",
    response_model=list[str],
    summary="List available resolvers",
)
async def list_available_resolvers(
    project_id: str = Path(..., description="Project ID"),
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """List all available resolver types.

    Args:
        project_id: Project ID (for access check)
        current_user: Authenticated user

    Returns:
        List of resolver type names
    """
    # Verify project access
    _get_project_or_404(project_id, current_user)

    from depictio.api.v1.endpoints.links_endpoints.resolvers import list_resolvers

    return list_resolvers()


@links_endpoint_router.get(
    "/{project_id}/multiqc/{dc_id}/sample-mappings",
    response_model=dict[str, list[str]],
    summary="Get aggregated sample mappings for a MultiQC DC",
)
async def get_multiqc_sample_mappings(
    project_id: str = Path(..., description="Project ID"),
    dc_id: str = Path(..., description="MultiQC data collection ID"),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[str]]:
    """Get aggregated sample mappings from all MultiQC reports for a DC.

    This endpoint aggregates sample_mappings from ALL MultiQC reports associated
    with the specified data collection. Useful for getting the complete list of
    samples for reset operations.

    Args:
        project_id: Project ID (for access check)
        dc_id: MultiQC data collection ID
        current_user: Authenticated user

    Returns:
        Aggregated sample mappings dict {canonical_id: [variant1, variant2, ...]}
    """
    # Verify project access
    _get_project_or_404(project_id, current_user)

    # Fetch aggregated sample mappings
    mappings = await _get_multiqc_sample_mappings(dc_id)

    logger.info(f"Returning {len(mappings)} aggregated sample mappings for MultiQC DC {dc_id}")

    return mappings
