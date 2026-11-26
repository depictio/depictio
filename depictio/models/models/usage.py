"""Internal usage statistics: the hit beacon and the report contract.

Storage is three daily-rollup collections written by
``depictio.api.v1.services.usage_stats`` (``usage_visits``, ``usage_logins``,
``usage_dashboard_views``): one upserted row per visitor (or user, or
dashboard) per day, so their size follows visitors x days, never requests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Granularity = Literal["day", "week", "month", "year"]

#: Who an activity belongs to. Only ``real`` users count as "users"; temporary
#: guests (public/demo mode) and the single-user owner are reported apart.
UserClass = Literal["real", "temporary", "single_user", "anonymous"]


class UsageHit(BaseModel):
    """One SPA navigation, sent by the viewer (``POST /analytics/hit``)."""

    visitor_id: str = Field(
        ...,
        pattern=r"^[0-9a-fA-F-]{32,36}$",
        description="Random per-browser id the viewer keeps in localStorage",
    )
    path_kind: str = Field(
        default="other",
        max_length=32,
        pattern=r"^[a-z_-]+$",
        description="Which app was opened (dashboards, viewer, editor, ...)",
    )
    dashboard_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{24}$")
    referrer: Optional[str] = Field(default=None, max_length=512)
    lang: Optional[str] = Field(default=None, max_length=35)


class UsagePoint(BaseModel):
    """One period of the time series."""

    period_start: datetime
    active_users: int = 0
    new_users: int = 0
    returning_users: int = 0
    logins: int = 0
    logins_by_method: dict[str, int] = Field(default_factory=dict)
    visitors: int = 0
    new_visitors: int = 0
    returning_visitors: int = 0
    visitors_fp: int = 0
    unique_ips: int = 0
    pageviews: int = 0
    dashboard_views: int = 0
    #: Offline-bundle downloads of a dashboard, counted per day like views but
    #: with no visitor attached. Default 0 so stored archives still validate.
    downloads: int = 0
    temporary_users: int = 0
    signups: int = 0
    new_projects: int = 0
    new_dashboards: int = 0
    ingestions: int = 0


class UsageKpi(BaseModel):
    """A range total and the same total over the span just before it."""

    current: float = 0
    previous: float = 0


class UsageReport(BaseModel):
    """Everything the Usage pane shows, in one response (also the agent API)."""

    granularity: Granularity
    start: datetime
    end: datetime
    generated_at: datetime
    mode: Literal["single_user", "public", "multi_user"]
    geoip_available: bool
    archived_periods: int = Field(
        default=0, description="Periods read from the anonymous archive (older than retention)"
    )
    timezone: str = "UTC"
    totals: dict[str, int]
    kpis: dict[str, UsageKpi]
    series: list[UsagePoint]
    breakdowns: dict[str, list[dict[str, Any]]]
    hours_heatmap: list[list[int]] = Field(
        default_factory=list, description="7 rows (Mon..Sun) x 24 hours (UTC), pageviews"
    )
