"""Indexes of the ``comment_threads`` collection."""

from __future__ import annotations

from pymongo import ASCENDING

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import comment_threads_collection


def ensure_comment_indexes() -> None:
    """Create the comment-thread indexes. Idempotent.

    Never raises: a missing index slows listing down, it must not break boot.
    """
    try:
        comment_threads_collection.create_index(
            [("anchor.dashboard_id", ASCENDING), ("anchor.component_index", ASCENDING)]
        )
        comment_threads_collection.create_index("parent_dashboard_id")
        comment_threads_collection.create_index("project_id")
        comment_threads_collection.create_index("dedupe_key", sparse=True)
        comment_threads_collection.create_index("run_id", sparse=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"comments: failed to ensure comment_threads indexes: {exc}")
