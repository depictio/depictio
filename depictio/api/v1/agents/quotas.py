"""Daily write quotas per token, on top of the per-run caps.

A run id is only a label the client may choose (``X-Depictio-Run-Id``), so a
client rotating it would get a fresh per-run budget each time. These counters
are keyed by token and UTC day instead, which the client cannot change.
Callers without a token (sessions, the in-app assistant) are bounded by the
per-run caps alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.logging_init import logger

MAX_THREADS_PER_TOKEN_PER_DAY = 200
MAX_REPORTS_PER_TOKEN_PER_DAY = 50
# A counter is only read on its own day; two days leaves room for clock skew.
_TTL = timedelta(days=2)

QuotaKind = Literal["threads", "reports"]


def _collection() -> Any:
    # Resolved at call time so tests can patch the module-level handle.
    from depictio.api.v1 import db

    return db.agent_quotas_collection


def _today() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d}"


def daily_run_id(key: str) -> str:
    """The run id of a caller that sends none: stable per token (or user) and UTC day."""
    return f"token-{key}-{_today()}"


def take(kind: QuotaKind, token_id: str, limit: int) -> bool:
    """Count one write of ``kind`` for ``token_id`` today; False once ``limit`` is reached.

    Atomic: the filter only matches a counter still under the limit, so a full
    counter makes the upsert collide with the existing document instead.
    """
    try:
        _collection().update_one(
            {"_id": f"{kind}:{token_id}:{_today()}", "count": {"$lt": limit}},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {"expires_at": datetime.now(timezone.utc) + _TTL},
            },
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    return True


def ensure_quota_indexes() -> None:
    """TTL on ``expires_at``. Idempotent, never raises."""
    try:
        _collection().create_index("expires_at", expireAfterSeconds=0, name="expires_at_ttl")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"agents: failed to ensure agent_quotas indexes: {exc}")
