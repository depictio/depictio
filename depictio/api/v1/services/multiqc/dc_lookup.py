"""MultiQC data-collection lookups (extracted from depictio.dash.modules.multiqc_component.models).

These functions resolve S3 parquet locations and metadata for a given
data-collection id, used by the celery prerender tasks and FastAPI
render endpoints.
"""

import hashlib
from typing import Any, Dict, Iterable, List, Optional

from depictio.models.logging import logger


def report_set_digest(report_ids: Iterable[str]) -> str:
    """sha256 over the sorted report ids: the identity of "this set of reports".

    The stamp records it (``manifest_digest``) and a pinned render salts its
    cache key with it, so the two never disagree about what "the same set" is.
    """
    return hashlib.sha256(",".join(sorted(str(r) for r in report_ids)).encode()).hexdigest()


def fetch_reports_for_dc(data_collection_id: str) -> List[Dict[str, Any]]:
    """The reports of a MultiQC DC as ``{id, s3_location, samples}``, oldest first.

    Feeds the manifest stamp a dashboard version records. Mongo only (no object
    store round trip), so it is cheap enough for the save path. A failed lookup
    returns an empty list: the stamp then says "no reports" instead of failing
    the save.
    """
    try:
        from depictio.api.v1.db import multiqc_collection

        cursor = multiqc_collection.find(
            {"data_collection_id": str(data_collection_id)},
            {"s3_location": 1, "metadata.samples": 1},
        ).sort([("_id", 1)])
        return [
            {
                "id": str(doc["_id"]),
                "s3_location": doc.get("s3_location") or "",
                "samples": list((doc.get("metadata") or {}).get("samples") or []),
            }
            for doc in cursor
        ]
    except Exception as e:
        logger.error(f"Failed to fetch reports of DC {data_collection_id}: {e}")
        return []


def fetch_s3_locations_for_reports(data_collection_id: str, report_ids: Iterable[str]) -> List[str]:
    """S3 locations of the named reports of one DC, in insertion order.

    Ids that are not valid, belong to another DC, or no longer exist are
    dropped, so a baseline that names a deleted report renders the rest.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    object_ids = []
    for report_id in report_ids:
        try:
            object_ids.append(ObjectId(str(report_id)))
        except (InvalidId, TypeError):
            continue
    if not object_ids:
        return []
    try:
        from depictio.api.v1.db import multiqc_collection

        cursor = multiqc_collection.find(
            {"data_collection_id": str(data_collection_id), "_id": {"$in": object_ids}},
            {"s3_location": 1},
        ).sort([("_id", 1)])
        return [loc for doc in cursor if (loc := doc.get("s3_location"))]
    except Exception as e:
        logger.error(f"Failed to fetch pinned reports of DC {data_collection_id}: {e}")
        return []


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
