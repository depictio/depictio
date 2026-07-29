"""The ledger of what a MultiQC collection consisted of, ingest by ingest.

MultiQC parquet is already content-addressed — every ingest writes
``s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`` at a fresh key and leaves the
previous object in place, orphaned but intact. So reproducing a past state needs
no copying and no bucket versioning: it needs a record of *which keys* made up
the collection at that moment.

That record is what this module writes and reads. A dashboard version stamps a
manifest digest; rendering that version resolves the pinned key set instead of
the current one, and everything downstream — the figure builders, the prerender
cache, the sample lists — keys off that list already.

Nothing here may raise into an ingest. A missing manifest costs the ability to
replay one version; a failed ingest costs someone's data.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from pymongo import DESCENDING

from depictio.models.logging import logger


def compute_manifest_digest(s3_locations: list[str] | set[str]) -> str:
    """sha256 over the sorted, de-duplicated location set. ``""`` when empty.

    Deliberately identical to ``_compute_s3_locations_hash`` in ``celery_app``,
    which has computed exactly this for the prerender cache since before
    versioning existed. Keeping the construction the same means a manifest
    digest and a prerender key describe the same thing, so the cache cannot
    serve one generation's figures under another's identity.
    """
    unique = {str(loc) for loc in s3_locations if loc}
    if not unique:
        return ""
    return hashlib.sha256("|".join(sorted(unique)).encode()).hexdigest()


def _dc_queries(dc_id: str) -> list[dict]:
    """Both id shapes.

    ``data_collection_id`` is written as a string by some paths and an ObjectId
    by others — the same quirk ``_compute_s3_locations_hash`` and
    ``_collect_dc_components`` both handle. ``fetch_s3_locations_from_dc``
    queries only the string form and is inconsistent with them; anything new
    should match the broader behaviour rather than inherit the narrower one.
    """
    queries: list[dict] = [{"data_collection_id": str(dc_id)}]
    if ObjectId.is_valid(str(dc_id)):
        queries.append({"data_collection_id": ObjectId(str(dc_id))})
    return queries


def current_report_set(dc_id: str) -> tuple[list[str], int, int]:
    """``(s3_locations, report_count, sample_count)`` for a collection, now.

    Locations are sorted by ``_id`` ascending — insertion order — because the
    general-stats cache key derives from ``s3_locations[0]`` and a shuffled
    order would silently reuse a stale payload.
    """
    from depictio.api.v1.db import multiqc_collection

    locations: list[str] = []
    samples: set[str] = set()
    seen: set[str] = set()
    report_count = 0

    for query in _dc_queries(dc_id):
        cursor = multiqc_collection.find(
            query, {"s3_location": 1, "metadata.canonical_samples": 1, "metadata.samples": 1}
        ).sort([("_id", 1)])
        for doc in cursor:
            location = doc.get("s3_location")
            if not location or location in seen:
                continue
            seen.add(str(location))
            locations.append(str(location))
            report_count += 1
            meta = doc.get("metadata") or {}
            for sample in meta.get("canonical_samples") or meta.get("samples") or []:
                samples.add(str(sample))

    return locations, report_count, len(samples)


def record_generation(dc_id: str, *, trigger: str | None = None) -> Optional[dict]:
    """Snapshot the collection's current report set as a new generation.

    Idempotent by digest: re-running an ingest that produced the same object set
    records nothing and returns the existing generation, so a CLI retry after a
    dropped response does not inflate the ledger.

    Never raises. Returns the manifest document, or ``None`` if nothing was
    recorded (no reports, or a write failure that was logged).
    """
    try:
        from depictio.api.v1.db import multiqc_manifests_collection

        locations, report_count, sample_count = current_report_set(dc_id)
        if not locations:
            return None

        digest = compute_manifest_digest(locations)
        latest = multiqc_manifests_collection.find_one(
            {"data_collection_id": str(dc_id)}, sort=[("generation", DESCENDING)]
        )
        if latest and latest.get("digest") == digest:
            return latest

        document = {
            "data_collection_id": str(dc_id),
            "generation": int((latest or {}).get("generation", 0)) + 1,
            "digest": digest,
            "s3_locations": locations,
            "sample_count": sample_count,
            "report_count": report_count,
            "created_at": datetime.now(),
            "trigger": trigger,
        }
        multiqc_manifests_collection.insert_one(document)
        logger.info(
            f"multiqc manifest dc={dc_id} generation={document['generation']} "
            f"reports={report_count} samples={sample_count} digest={digest[:12]}"
        )
        return document
    except Exception as exc:  # noqa: BLE001 - a manifest must never break an ingest
        logger.warning(f"Failed to record MultiQC manifest for {dc_id}: {exc}")
        return None


def get_manifest(
    dc_id: str,
    *,
    digest: str | None = None,
    as_of: datetime | None = None,
) -> Optional[dict]:
    """Resolve a pinned generation, by digest or by instant.

    ``digest`` is exact and is what a dashboard version stamps. ``as_of`` is the
    fallback for a version recorded before manifests existed, or one whose
    digest no longer resolves because the objects were swept: it takes the
    newest generation at or before that instant, which is the best available
    answer rather than a guess dressed up as one.

    Returns ``None`` when neither locates a generation — callers then read live
    and report the collection as unpinned rather than failing.
    """
    try:
        from depictio.api.v1.db import multiqc_manifests_collection

        if digest:
            found = multiqc_manifests_collection.find_one(
                {"data_collection_id": str(dc_id), "digest": digest}
            )
            if found:
                return found

        if as_of is not None:
            return multiqc_manifests_collection.find_one(
                {"data_collection_id": str(dc_id), "created_at": {"$lte": as_of}},
                sort=[("created_at", DESCENDING)],
            )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to resolve MultiQC manifest for {dc_id}: {exc}")
        return None


def latest_manifest(dc_id: str) -> Optional[dict]:
    """The newest recorded generation, for stamping a version at save time."""
    try:
        from depictio.api.v1.db import multiqc_manifests_collection

        return multiqc_manifests_collection.find_one(
            {"data_collection_id": str(dc_id)}, sort=[("generation", DESCENDING)]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read latest MultiQC manifest for {dc_id}: {exc}")
        return None


def ensure_indexes() -> None:
    """Idempotent, and never raises — mirrors ``ensure_dashboard_version_storage``."""
    try:
        from depictio.api.v1.db import multiqc_manifests_collection

        multiqc_manifests_collection.create_index(
            [("data_collection_id", 1), ("generation", DESCENDING)]
        )
        multiqc_manifests_collection.create_index([("data_collection_id", 1), ("digest", 1)])
        multiqc_manifests_collection.create_index(
            [("data_collection_id", 1), ("created_at", DESCENDING)]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not ensure MultiQC manifest indexes: {exc}")


def summarise(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """The subset a dashboard version stamp records."""
    if not manifest:
        return {}
    return {
        "manifest_digest": manifest.get("digest"),
        "s3_locations": list(manifest.get("s3_locations") or []),
        "sample_count": manifest.get("sample_count"),
        "as_of": manifest.get("created_at"),
    }
