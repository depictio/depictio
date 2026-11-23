"""Internal usage statistics API (``/analytics``).

* ``POST /analytics/hit``: the viewer's navigation beacon (token optional).
* ``GET /analytics/usage``: the period report, for the Admin Usage pane and for
  agents. Admin session **or** ``X-Api-Key`` (``DEPICTIO_AUTH_INTERNAL_API_KEY``).

See ``docs/usage-stats.md``.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    _async_fetch_user_from_token,
)
from depictio.api.v1.endpoints.user_endpoints.rate_limit import enforce_rate_limit
from depictio.api.v1.endpoints.user_endpoints.routes import (
    _is_valid_internal_api_key,
    oauth2_scheme_optional,
)
from depictio.api.v1.services import usage_stats
from depictio.models.models.usage import Granularity, UsageHit, UsageReport

router = APIRouter()

#: Navigations per minute per address. A whole institute shares one address,
#: so this only stops a script, not a busy room.
_HITS_PER_MINUTE = 600


async def require_analytics_admin(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
    x_api_key: str | None = Header(
        default=None,
        alias="X-Api-Key",
        description="Internal API key (alternative to an authenticated admin session)",
    ),
) -> None:
    """Admin session (not a temporary guest) or the internal API key."""
    if _is_valid_internal_api_key(x_api_key):
        return
    if token is not None:
        user = await _async_fetch_user_from_token(token)
        if user is not None and user.is_admin and not getattr(user, "is_temporary", False):
            return
    raise HTTPException(status_code=403, detail="Administrator privileges required")


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """API timestamps are naive UTC: convert an offset, don't drop it."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _require_enabled() -> None:
    if not settings.usage_stats.enabled:
        raise HTTPException(status_code=404, detail="Usage statistics are disabled")


@router.post("/hit", status_code=204)
async def track_hit(
    hit: UsageHit,
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> Response:
    """Record one navigation. Idempotent per browser per day; never echoes data."""
    _require_enabled()
    enforce_rate_limit(request, "analytics/hit", max_calls=_HITS_PER_MINUTE)
    user = None
    if token:
        try:
            user = await _async_fetch_user_from_token(token)
        except Exception:  # an expired token still counts as a visit
            user = None
    await run_in_threadpool(usage_stats.record_hit, hit, request, user)
    return Response(status_code=204)


@router.get(
    "/usage",
    response_model=UsageReport,
    dependencies=[Depends(require_analytics_admin)],
)
def get_usage(
    granularity: Granularity = Query("month"),
    periods: int = Query(12, ge=1, le=120),
    start: Optional[datetime] = Query(None, description="Custom range start (UTC)"),
    end: Optional[datetime] = Query(
        None, description="Custom range end (UTC), inclusive of its period"
    ),
    format: Literal["json", "csv"] = Query("json"),
):
    """Usage report per period: users, logins, visitors, content, breakdowns."""
    _require_enabled()
    start, end = _naive_utc(start), _naive_utc(end)
    if start and end and end < start:
        raise HTTPException(status_code=400, detail="end is before start")
    try:
        usage_stats.archive_closed_periods()
        report = usage_stats.build_report(granularity, periods, start, end)
    except Exception as exc:
        logger.error(f"usage_stats: report failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to build the usage report") from exc
    if format == "csv":
        return Response(
            content=usage_stats.report_to_csv(report),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="depictio-usage.csv"'},
        )
    return report
