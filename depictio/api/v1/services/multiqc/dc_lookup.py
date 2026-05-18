"""MultiQC data-collection lookups (extracted from depictio.dash.modules.multiqc_component.models).

These functions resolve S3 parquet locations and metadata for a given
data-collection id, used by the celery prerender tasks and FastAPI
render endpoints.
"""

from typing import Any, Dict, List, Optional

from depictio.models.logging import logger


def fetch_s3_locations_from_dc(
    data_collection_id: str, project_id: Optional[str] = None
) -> List[str]:
    """Fetch S3 locations from data collection config.

    Walks the ``multiqc_reports`` collection for the DC and returns every
    report's S3 parquet location. The ``dc_specific_properties.s3_location``
    field on the DC config only stores the *first* parquet captured by the
    processor — using it alone caused MultiQC plot rendering to ignore N-1
    reports after appends. The reports collection is the source of truth.

    Falls back to the singular ``dc_specific_properties.s3_location`` if the
    reports collection lookup yields nothing (covers minimal YAML imports
    that ship that field but no per-report rows).

    Args:
        data_collection_id: Data collection ID.
        project_id: Optional project ID for the YAML-minimal fallback path.

    Returns:
        List of S3 locations — one per ingested report, or single-element
        from the DC config fallback, or empty if nothing is found.
    """
    try:
        # Primary path: walk multiqc_reports — this is where every appended
        # report's S3 location lives.
        from depictio.api.v1.db import multiqc_collection

        # Sort by _id ascending so insertion order is stable across mutations
        # — append/replace can shuffle MongoDB's default cursor order, and the
        # GS endpoint cache key derives from s3_locations[0]. Without this,
        # `[0]` could keep pointing to the same parquet after an append, hiding
        # the new reports behind a stale cached payload.
        cursor = multiqc_collection.find(
            {"data_collection_id": str(data_collection_id)},
            {"s3_location": 1},
        ).sort([("_id", 1)])
        s3_locations: List[str] = [loc for doc in cursor if (loc := doc.get("s3_location"))]
        if s3_locations:
            return s3_locations

        # Fallback: the DC config's singular s3_location field. Useful for
        # minimal YAML imports that don't ship per-report documents.
        if project_id:
            from bson import ObjectId

            from depictio.api.v1.db import projects_collection

            project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
            if project_doc and "workflows" in project_doc:
                for wf in project_doc.get("workflows", []):
                    if "data_collections" in wf:
                        for dc in wf["data_collections"]:
                            if str(dc.get("_id")) == str(data_collection_id):
                                dc_config = dc.get("config", dc)
                                dc_specific_props = dc_config.get("dc_specific_properties", {})
                                s3_location = dc_specific_props.get("s3_location")
                                if s3_location:
                                    return [s3_location]

        return []

    except Exception as e:
        logger.error(f"Failed to fetch s3_locations from DC {data_collection_id}: {e}")
        return []


def fetch_metadata_from_dc(
    data_collection_id: str, project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Fetch MultiQC metadata (modules, plots, samples) from data collection config.

    Regenerates metadata structure needed for dropdowns, ensuring YAML is minimal.

    Args:
        data_collection_id: Data collection ID.
        project_id: Optional project ID for nested lookup.

    Returns:
        Dictionary with modules, plots, and samples.
    """
    try:
        # Import here to avoid circular dependencies
        from depictio.api.v1.db import projects_collection

        # Search in projects for nested data collections
        if project_id:
            from bson import ObjectId

            project_doc = projects_collection.find_one({"_id": ObjectId(project_id)})
            if project_doc and "workflows" in project_doc:
                for wf in project_doc.get("workflows", []):
                    if "data_collections" in wf:
                        for dc in wf["data_collections"]:
                            if str(dc.get("_id")) == str(data_collection_id):
                                dc_config = dc.get("config", dc)
                                dc_specific_props = dc_config.get("dc_specific_properties", {})

                                metadata = {}
                                if dc_specific_props.get("modules"):
                                    metadata["modules"] = dc_specific_props["modules"]
                                if dc_specific_props.get("plots"):
                                    metadata["plots"] = dc_specific_props["plots"]
                                if dc_specific_props.get("samples"):
                                    metadata["samples"] = dc_specific_props["samples"]

                                if metadata:
                                    return metadata

        return {}

    except Exception as e:
        logger.error(f"Failed to fetch metadata from DC {data_collection_id}: {e}")
        return {}
