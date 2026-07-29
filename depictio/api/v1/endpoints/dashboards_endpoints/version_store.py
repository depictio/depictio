"""Persistence for the dashboard version ledger.

Thin pymongo CRUD over ``dashboard_versions`` and its per-family sequence
counters, mirroring the plain-dict style of ``monitoring/store.py``; no Beanie.

Retention lives here too. There is deliberately **no TTL index**: a TTL index
is unconditional, so it could not exempt pinned versions, and the thinning
policy (keep one version per day past a threshold) is application logic no
index can express. ``prune_family`` is called opportunistically after a
capture rather than on a schedule, because this codebase has no Celery beat
schedule — a scheduled prune would never run.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import (
    dashboard_version_counters_collection,
    dashboard_versions_collection,
)


def ensure_dashboard_version_storage() -> None:
    """Create the version-ledger indexes. Idempotent, never raises."""
    try:
        dashboard_versions_collection.create_index("version_id", unique=True, name="version_id")
        # The uniqueness backstop for sequence allocation: even if two captures
        # somehow derived the same seq, only one can land.
        dashboard_versions_collection.create_index(
            [("family_id", ASCENDING), ("seq", DESCENDING)], unique=True, name="family_seq"
        )
        # Timeline pagination.
        dashboard_versions_collection.create_index(
            [("family_id", ASCENDING), ("created_at", DESCENDING)], name="family_created"
        )
        # Prune and "pinned only" filtering.
        dashboard_versions_collection.create_index(
            [("family_id", ASCENDING), ("pinned", ASCENDING)], name="family_pinned"
        )
        dashboard_version_counters_collection.create_index("family_id", unique=True, name="family")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dashboard_versions: failed to ensure indexes: {exc}")


def next_seq(family_id: str) -> int:
    """Allocate the next version number for a family.

    A dedicated counter document incremented atomically, rather than
    ``max(seq) + 1`` over the versions themselves: two concurrent saves on the
    same dashboard would both read the same max and both try to write it.
    """
    doc = dashboard_version_counters_collection.find_one_and_update(
        {"family_id": family_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int((doc or {}).get("seq", 1))


def latest_version(family_id: str) -> Optional[dict[str, Any]]:
    """Most recent version for a family, or None."""
    return dashboard_versions_collection.find_one(
        {"family_id": family_id}, sort=[("seq", DESCENDING)]
    )


def insert_version(record: dict[str, Any]) -> dict[str, Any]:
    dashboard_versions_collection.insert_one(dict(record))
    return record


def fold_into_version(version_id: str, updates: dict[str, Any]) -> None:
    """Merge a coalesced save into an existing version."""
    dashboard_versions_collection.update_one(
        {"version_id": version_id},
        {"$set": updates, "$inc": {"save_count": 1}},
    )


def touch_version(version_id: str, now: datetime) -> None:
    """Record that a save happened but changed nothing."""
    dashboard_versions_collection.update_one(
        {"version_id": version_id},
        {"$set": {"updated_at": now}, "$inc": {"save_count": 1}},
    )


def get_version(version_id: str) -> Optional[dict[str, Any]]:
    return dashboard_versions_collection.find_one({"version_id": version_id})


def list_versions(
    family_id: str, *, limit: int = 50, before_seq: int | None = None, pinned_only: bool = False
) -> list[dict[str, Any]]:
    """Timeline page, newest first, with the snapshot payload projected away."""
    query: dict[str, Any] = {"family_id": family_id}
    if before_seq is not None:
        query["seq"] = {"$lt": before_seq}
    if pinned_only:
        query["pinned"] = True

    # `tabs` is ~95% of a record's bytes and the drawer lists far more often
    # than it opens; ship counts instead. `data_collections` is small and the
    # timeline badges provenance coverage from it.
    projection = {"tabs": 0}
    cursor = (
        dashboard_versions_collection.find(query, projection)
        .sort("seq", DESCENDING)
        .limit(max(1, min(limit, 200)))
    )
    return list(cursor)


def count_versions(family_id: str) -> int:
    return dashboard_versions_collection.count_documents({"family_id": family_id})


def set_version_fields(version_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    return dashboard_versions_collection.find_one_and_update(
        {"version_id": version_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


def delete_version(version_id: str) -> bool:
    return dashboard_versions_collection.delete_one({"version_id": version_id}).deleted_count > 0


def delete_family(family_id: str) -> int:
    """Drop a family's whole ledger — used when the dashboard itself is deleted."""
    removed = dashboard_versions_collection.delete_many({"family_id": family_id}).deleted_count
    dashboard_version_counters_collection.delete_one({"family_id": family_id})
    return removed


def _prunable(record: dict[str, Any]) -> bool:
    """Only unpinned autosaves are ever eligible for pruning.

    Pins are the user's explicit statement that a version matters. Explicit
    saves, restore points and imports are few and deliberate, so they are kept
    for the full retention window rather than thinned.
    """
    return not record.get("pinned", False) and record.get("kind") == "auto"


def prune_family(family_id: str, *, now: datetime | None = None) -> int:
    """Apply the retention policy to one family. Returns the number removed.

    Tiered, so the timeline stays readable at every zoom level:

    1. pinned versions are kept unconditionally, forever;
    2. non-``auto`` versions (explicit / restore / import) are kept for the
       whole retention window;
    3. the most recent ``max_versions_per_family`` autosaves are kept;
    4. past ``keep_daily_for_days``, autosaves thin to the last of each day;
    5. anything older than ``retention_days`` goes.
    """
    cfg = settings.dashboard_versions
    now = now or datetime.now()

    records = list(
        dashboard_versions_collection.find({"family_id": family_id}).sort("seq", DESCENDING)
    )
    if not records:
        return 0

    age_cutoff = now - timedelta(days=cfg.retention_days)
    daily_cutoff = now - timedelta(days=cfg.keep_daily_for_days)

    doomed: list[str] = []
    seen_recent = 0
    kept_days: set[str] = set()

    for record in records:
        created = record.get("created_at") or now
        if isinstance(created, str):  # defensive: legacy/hand-written records
            continue

        if not _prunable(record):
            # Rule 1 & 2 — but non-auto kinds still expire on age.
            if not record.get("pinned", False) and created < age_cutoff:
                doomed.append(record["version_id"])
            continue

        seen_recent += 1
        if seen_recent <= cfg.max_versions_per_family and created >= age_cutoff:
            # Rule 3, subject to rule 4 for the older part of the window.
            if created < daily_cutoff:
                day = created.strftime("%Y-%m-%d")
                if day in kept_days:
                    doomed.append(record["version_id"])
                else:
                    kept_days.add(day)
            continue

        doomed.append(record["version_id"])

    if not doomed:
        return 0

    # Scoped to the family as well as the ids. version_id is a uuid4 so an
    # id alone would be enough in practice, but a prune must be structurally
    # incapable of reaching another dashboard's history — and the compound
    # filter uses the family index rather than scanning.
    result = dashboard_versions_collection.delete_many(
        {"family_id": family_id, "version_id": {"$in": doomed}}
    )
    logger.debug(f"dashboard_versions: pruned {result.deleted_count} version(s) for {family_id}")
    return result.deleted_count


def maybe_prune_family(family_id: str, *, now: datetime | None = None) -> int:
    """Prune only once a family has visibly outgrown its cap.

    Called after every capture, so the common case must be a single cheap
    count rather than a full scan-and-sort of the family's ledger.
    """
    cfg = settings.dashboard_versions
    threshold = int(cfg.max_versions_per_family * 1.2)
    try:
        if count_versions(family_id) <= threshold:
            return 0
        return prune_family(family_id, now=now)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dashboard_versions: prune failed for {family_id}: {exc}")
        return 0
