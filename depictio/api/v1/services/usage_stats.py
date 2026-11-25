"""Internal usage statistics: record logins / visits, build the period report.

Design (see ``docs/usage-stats.md``):

* **Daily rollups, not events.** ``usage_visits`` holds one row per
  ``(day, visitor_id)``, ``usage_logins`` one per ``(day, user_id, method)``,
  ``usage_dashboard_views`` one per ``(day, dashboard_id)``. Every write is an
  idempotent upsert, so volume follows visitors x days whatever the traffic,
  and a replayed beacon only rewrites its own row. A TTL index on ``day``
  bounds retention.
* **Who is a visitor.** ``visitor_id`` is a random UUID the browser keeps, so
  a whole institute behind one NAT address still counts as many visitors.
  ``fp_hash`` (keyed hash of IP + user agent, Umami's approach) is kept as a
  second, cookie-free count, and ``ip_hash`` counts addresses.
* **Privacy.** IPs and user agents are never stored: IPs only as an HMAC under
  a per-instance random key (``instance_settings``), user agents reduced to
  browser / OS / device class. Country and city are resolved at reception from
  a local GeoIP file when one is configured. Offline-bundle downloads are
  counted on the dashboard row as a bare total, with no visitor attached.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Iterable, Literal, Optional
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import Request
from pymongo import ASCENDING
from pymongo.errors import OperationFailure

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.usage import (
    Granularity,
    UsageHit,
    UsageKpi,
    UsagePoint,
    UsageReport,
)
from depictio.models.timestamps import utc_now_naive

VISITS = "usage_visits"
LOGINS = "usage_logins"
DASHBOARD_VIEWS = "usage_dashboard_views"
#: Distinct browsers kept per dashboard per day (views keep counting past it).
MAX_DASHBOARD_VISITORS = 2000
_SALT_DOC_ID = "usage_stats_salt"

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|headless|playwright|puppeteer|lighthouse|phantomjs|"
    r"python-requests|httpx|curl|wget|go-http|java/|okhttp|uptime|monitor|probe",
    re.IGNORECASE,
)


def _db():
    from depictio.api.v1 import db as dbmod

    return dbmod.db


# ── Identity helpers ─────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _instance_key() -> bytes:
    """Per-instance HMAC key, created once and shared by every worker."""
    coll = _db()[settings.mongodb.collections.instance_settings_collection]
    coll.update_one(
        {"_id": _SALT_DOC_ID},
        {"$setOnInsert": {"value": secrets.token_hex(32)}},
        upsert=True,
    )
    doc = coll.find_one({"_id": _SALT_DOC_ID}) or {}
    return str(doc.get("value", "")).encode()


def keyed_hash(value: str, length: int = 16) -> str:
    return hmac.new(_instance_key(), value.encode(), hashlib.sha256).hexdigest()[:length]


def client_ip(request: Request) -> str:
    """Same rule as the auth rate limiter: nginx's ``X-Real-IP``, else the peer."""
    from depictio.api.v1.endpoints.user_endpoints.rate_limit import _client_ip

    return _client_ip(request)


def is_bot(user_agent: str) -> bool:
    return not user_agent or bool(_BOT_RE.search(user_agent))


def parse_user_agent(ua: str) -> tuple[str, str, str]:
    """Browser family, OS family and device class from a user agent string."""
    u = ua.lower()
    if "edg/" in u:
        browser = "Edge"
    elif "opr/" in u or "opera" in u:
        browser = "Opera"
    elif "firefox/" in u or "fxios" in u:
        browser = "Firefox"
    elif "chrome/" in u or "crios" in u or "chromium" in u:
        browser = "Chrome"
    elif "safari/" in u:
        browser = "Safari"
    else:
        browser = "Other"

    if "android" in u:
        os_name = "Android"
    elif "iphone" in u or "ipad" in u or "ios" in u:
        os_name = "iOS"
    elif "windows" in u:
        os_name = "Windows"
    elif "mac os x" in u or "macintosh" in u:
        os_name = "macOS"
    elif "cros" in u:
        os_name = "ChromeOS"
    elif "linux" in u or "x11" in u:
        os_name = "Linux"
    else:
        os_name = "Other"

    if "ipad" in u or "tablet" in u:
        device = "tablet"
    elif "mobi" in u or "iphone" in u or "android" in u:
        device = "mobile"
    else:
        device = "desktop"
    return browser, os_name, device


@lru_cache(maxsize=1)
def _geoip_reader() -> Any:
    path = settings.usage_stats.geoip_db_path
    if not path:
        return None
    try:
        import maxminddb

        return maxminddb.open_database(path)
    except Exception as exc:  # missing file or package: geo stays empty
        logger.warning(f"usage_stats: GeoIP database unavailable ({path}): {exc}")
        return None


def geoip_available() -> bool:
    return _geoip_reader() is not None


def geolocate(ip: str) -> tuple[Optional[str], Optional[str]]:
    """``(ISO country code, city)`` for ``ip``, or ``(None, None)``."""
    reader = _geoip_reader()
    if reader is None:
        return None, None
    try:
        rec = reader.get(ip) or {}
    except Exception:
        return None, None
    country = (rec.get("country") or {}).get("iso_code")
    city = ((rec.get("city") or {}).get("names") or {}).get("en")
    return country, city


def referrer_domain(referrer: Optional[str], request: Request) -> Optional[str]:
    """External referring domain only; same-site navigation is not a referrer."""
    if not referrer:
        return None
    host = (urlparse(referrer).hostname or "").lower()
    if not host or host == (request.url.hostname or "").lower():
        return None
    return host[:255]


def user_class(user: Any) -> str:
    if settings.auth.is_single_user_mode:
        return "single_user"
    if user is None or getattr(user, "is_anonymous", False):
        return "anonymous"
    if getattr(user, "is_temporary", False):
        return "temporary"
    return "real"


def _day(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day)


# ── Writes ───────────────────────────────────────────────────────────────────


def ensure_usage_indexes(database: Any = None) -> None:
    """Unique rollup keys + TTL on ``day``. Idempotent, never raises."""
    database = _db() if database is None else database
    ttl = int(settings.usage_stats.retention_days) * 86_400
    specs = {
        VISITS: [("day", ASCENDING), ("visitor_id", ASCENDING)],
        LOGINS: [("day", ASCENDING), ("user_id", ASCENDING), ("method", ASCENDING)],
        DASHBOARD_VIEWS: [("day", ASCENDING), ("dashboard_id", ASCENDING)],
    }
    for name, keys in specs.items():
        coll = database[name]
        try:
            coll.create_index(keys, unique=True, name="rollup_key")
            try:
                coll.create_index("day", expireAfterSeconds=ttl, name="day_ttl")
            except OperationFailure:
                # Same key, another retention: retune the TTL in place.
                database.command(
                    "collMod", name, index={"keyPattern": {"day": 1}, "expireAfterSeconds": ttl}
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"usage_stats: failed to ensure indexes on {name}: {exc}")


async def record_login(user: Any, method: str, request: Optional[Request] = None) -> None:
    """Count one login and stamp ``last_login``. Never raises, never blocks the loop."""
    if not settings.usage_stats.enabled or user is None or getattr(user, "id", None) is None:
        return
    if request is not None and is_bot(request.headers.get("user-agent", "")):
        return
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(_write_login, user, method)


def _write_login(user: Any, method: str) -> None:
    try:
        now = utc_now_naive()
        day = _day(now)
        database = _db()
        database[LOGINS].update_one(
            {"day": day, "user_id": str(user.id), "method": method[:64]},
            {
                "$inc": {"count": 1},
                "$set": {"user_class": user_class(user)},
            },
            upsert=True,
        )
        database[settings.mongodb.collections.users_collection].update_one(
            {"_id": ObjectId(str(user.id))}, {"$set": {"last_login": now.isoformat()}}
        )
    except Exception as exc:
        logger.warning(f"usage_stats: failed to record login: {exc}")


def refuses_tracking(request: Request) -> bool:
    """Do Not Track or Global Privacy Control sent by the browser."""
    return request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1"


def erase_user_usage(user_id: str) -> None:
    """Right to erasure: drop a deleted account's logins, visits and its browsers'
    trace in dashboard views. Never raises."""
    try:
        database = _db()
        visitor_ids = database[VISITS].distinct("visitor_id", {"user_id": user_id})
        database[VISITS].delete_many({"user_id": user_id})
        database[LOGINS].delete_many({"user_id": user_id})
        if visitor_ids:
            database[DASHBOARD_VIEWS].update_many(
                {"visitors": {"$in": visitor_ids}}, {"$pull": {"visitors": {"$in": visitor_ids}}}
            )
    except Exception as exc:
        logger.warning(f"usage_stats: failed to erase usage of a deleted user: {exc}")


def record_hit(hit: UsageHit, request: Request, user: Any) -> bool:
    """Upsert today's visit row for this browser (+ dashboard view). Never raises."""
    ua = request.headers.get("user-agent", "")
    if not settings.usage_stats.enabled or is_bot(ua) or refuses_tracking(request):
        return False
    try:
        now = utc_now_naive()
        day = _day(now)
        ip = client_ip(request)
        browser, os_name, device = parse_user_agent(ua)
        country, city = geolocate(ip)
        cls = user_class(user)
        user_id = str(user.id) if user is not None and cls != "anonymous" else None
        on_set: dict[str, Any] = {
            "ip_hash": keyed_hash(f"ip|{ip}"),
            "fp_hash": keyed_hash(f"fp|{ip}|{ua}"),
            "browser": browser,
            "os": os_name,
            "device": device,
        }
        # The account is set only when one is known, so a logout later the same
        # day never turns a signed-in day back into an anonymous one.
        if user_id:
            on_set["user_id"] = user_id
            on_set["user_class"] = cls
        if country:
            on_set["country"] = country
            on_set["city"] = city
        on_insert: dict[str, Any] = {} if user_id else {"user_class": "anonymous"}
        ref = referrer_domain(hit.referrer, request)
        if ref:
            on_insert["referrer"] = ref
        if hit.lang:
            on_insert["lang"] = hit.lang.split("-")[0].lower()[:8]
        database = _db()
        vid = hit.visitor_id.lower()
        key = {"day": day, "visitor_id": vid}
        # A script minting a fresh id per request could otherwise grow the table
        # without bound: past the daily cap, only known browsers are counted.
        if database[VISITS].find_one(key, {"_id": 1}) is None and (
            database[VISITS].count_documents({"day": day})
            >= settings.usage_stats.max_daily_visitors
        ):
            return False
        database[VISITS].update_one(
            key,
            {
                "$set": on_set,
                "$setOnInsert": on_insert,
                "$inc": {"pageviews": 1, f"hours.{now.hour}": 1},
            },
            upsert=True,
        )
        if hit.dashboard_id:
            views = database[DASHBOARD_VIEWS]
            views.update_one(
                {"day": day, "dashboard_id": hit.dashboard_id}, {"$inc": {"views": 1}}, upsert=True
            )
            # Distinct visitors are kept up to a bound, so one row never nears 16MB.
            views.update_one(
                {
                    "day": day,
                    "dashboard_id": hit.dashboard_id,
                    f"visitors.{MAX_DASHBOARD_VISITORS - 1}": {"$exists": False},
                },
                {"$addToSet": {"visitors": vid}},
            )
        return True
    except Exception as exc:
        logger.warning(f"usage_stats: failed to record hit: {exc}")
        return False


def record_download(dashboard_id: str, request: Request) -> bool:
    """Count one offline-bundle download of a dashboard on its views row. Never
    raises, and stores no identifier of any kind: no IP, user agent, user or
    visitor id, only the daily total."""
    ua = request.headers.get("user-agent", "")
    if not settings.usage_stats.enabled or is_bot(ua) or refuses_tracking(request):
        return False
    try:
        day = _day(utc_now_naive())
        _db()[DASHBOARD_VIEWS].update_one(
            {"day": day, "dashboard_id": dashboard_id},
            {"$inc": {"downloads": 1}},
            upsert=True,
        )
        return True
    except Exception as exc:
        logger.warning(f"usage_stats: failed to record download: {exc}")
        return False


# ── Report ───────────────────────────────────────────────────────────────────

#: Anonymous totals of closed months and years (no identifier of any kind).
#: Not under the TTL: this is what remains once the daily rows expire.
ARCHIVE = "usage_archive"
_ARCHIVED_GRANULARITIES: tuple[Granularity, ...] = ("month", "year")
#: Breakdowns holding pseudonymous keys are never archived.
_NOT_ARCHIVED = {"visitors_per_ip"}

_PREV = datetime.min  # bucket key of the previous range in the accumulator


def period_start(dt: datetime, granularity: Granularity) -> datetime:
    d = _day(dt)
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    if granularity == "year":
        return d.replace(month=1, day=1)
    return d


def next_period(dt: datetime, granularity: Granularity) -> datetime:
    if granularity == "day":
        return dt + timedelta(days=1)
    if granularity == "week":
        return dt + timedelta(days=7)
    if granularity == "month":
        return (dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    return dt.replace(year=dt.year + 1)


def _back(dt: datetime, granularity: Granularity, n: int) -> datetime:
    for _ in range(max(1, n)):
        dt = period_start(dt - timedelta(days=1), granularity)
    return dt


def resolve_range(
    granularity: Granularity,
    periods: int,
    start: Optional[datetime],
    end: Optional[datetime],
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """``[start, end)`` on period boundaries. ``end`` is inclusive of its period;
    without ``start``, ``periods`` periods ending with ``end``'s (or now's)."""
    anchor = end or now or utc_now_naive()
    e = next_period(period_start(anchor, granularity), granularity)
    if start is None:
        return _back(e, granularity, periods), e
    s = period_start(start, granularity)
    return s, max(e, next_period(s, granularity))


def _mode() -> Literal["single_user", "public", "multi_user"]:
    if settings.auth.is_single_user_mode:
        return "single_user"
    if settings.auth.is_public_mode:
        return "public"
    return "multi_user"


@dataclass
class _Acc:
    """Everything counted for one period (or the previous range)."""

    users: set = field(default_factory=set)
    visitors: set = field(default_factory=set)
    fps: set = field(default_factory=set)
    ips: set = field(default_factory=set)
    temps: set = field(default_factory=set)
    countries: set = field(default_factory=set)
    logins: Counter = field(default_factory=Counter)
    pageviews: int = 0
    dviews: int = 0
    downloads: int = 0
    created: Counter = field(default_factory=Counter)


@dataclass
class _Dims:
    """Range-wide breakdowns (current range only)."""

    browsers: Counter = field(default_factory=Counter)
    os: Counter = field(default_factory=Counter)
    devices: Counter = field(default_factory=Counter)
    countries: Counter = field(default_factory=Counter)
    cities: Counter = field(default_factory=Counter)
    langs: Counter = field(default_factory=Counter)
    refs: Counter = field(default_factory=Counter)
    methods: Counter = field(default_factory=Counter)
    dash_views: Counter = field(default_factory=Counter)
    #: Daily download totals per dashboard, kept beside the views.
    dash_downloads: Counter = field(default_factory=Counter)
    dash_visitors: dict = field(default_factory=lambda: defaultdict(set))
    ip_visitors: dict = field(default_factory=lambda: defaultdict(set))
    seen: set = field(default_factory=set)
    heat: list = field(default_factory=lambda: [[0] * 24 for _ in range(7)])


def _first_seen(coll: Any, key: str, before: datetime) -> dict[str, datetime]:
    """First day each id appears, within retention. Streamed, no ``$in`` list."""
    pipeline = [
        {"$match": {"day": {"$lt": before}, key: {"$ne": None}}},
        {"$group": {"_id": f"${key}", "first": {"$min": "$day"}}},
    ]
    return {d["_id"]: d["first"] for d in coll.aggregate(pipeline)}


def _fold_visits(rows: Iterable[dict], bucket_of, acc: dict, dims: _Dims) -> None:
    for v in rows:
        b = bucket_of(v["day"])
        a = acc[b]
        vid = v["visitor_id"]
        a.visitors.add(vid)
        a.fps.add(v.get("fp_hash"))
        a.ips.add(v.get("ip_hash"))
        a.pageviews += v.get("pageviews", 0)
        if v.get("country"):
            a.countries.add(v["country"])
        cls, uid = v.get("user_class"), v.get("user_id")
        if uid and cls == "real":
            a.users.add(uid)
        elif uid and cls == "temporary":
            a.temps.add(uid)
        if b is _PREV:
            continue
        if vid not in dims.seen:  # each browser once over the range
            dims.seen.add(vid)
            dims.browsers[v.get("browser")] += 1
            dims.os[v.get("os")] += 1
            dims.devices[v.get("device")] += 1
            dims.langs[v.get("lang")] += 1
            if v.get("country"):
                dims.countries[v["country"]] += 1
                dims.cities[(v["country"], v.get("city") or "?")] += 1
        if v.get("referrer"):
            dims.refs[v["referrer"]] += 1
        if v.get("ip_hash"):
            dims.ip_visitors[v["ip_hash"]].add(vid)
        for h, n in (v.get("hours") or {}).items():
            dims.heat[v["day"].weekday()][int(h)] += int(n)


def _fold_logins(rows: Iterable[dict], bucket_of, acc: dict, dims: _Dims) -> None:
    for lg in rows:
        b = bucket_of(lg["day"])
        n = int(lg.get("count", 1))
        acc[b].logins[lg["method"]] += n
        if lg.get("user_class") == "real":
            acc[b].users.add(lg["user_id"])
        elif lg.get("user_class") == "temporary":
            acc[b].temps.add(lg["user_id"])
        if b is not _PREV:
            dims.methods[lg["method"]] += n


def _fold_dashboard_views(rows: Iterable[dict], bucket_of, acc: dict, dims: _Dims) -> None:
    for dv in rows:
        b = bucket_of(dv["day"])
        acc[b].dviews += dv.get("views", 0)
        acc[b].downloads += dv.get("downloads", 0)
        if b is not _PREV:
            dims.dash_views[dv["dashboard_id"]] += dv.get("views", 0)
            dims.dash_downloads[dv["dashboard_id"]] += dv.get("downloads", 0)
            dims.dash_visitors[dv["dashboard_id"]].update(dv.get("visitors") or [])


_REAL_USERS = {"is_temporary": {"$ne": True}, "is_anonymous": {"$ne": True}}


def _fold_creations(database: Any, lo: datetime, hi: datetime, bucket_of, acc: dict) -> None:
    """Accounts, projects, dashboards and ingestion runs created, by ObjectId time
    (an imported document keeps its source's creation time)."""
    cols = settings.mongodb.collections
    for key, name, q in (
        ("signups", cols.users_collection, _REAL_USERS),
        ("new_projects", cols.projects_collection, {}),
        ("new_dashboards", cols.dashboards_collection, {"parent_dashboard_id": None}),
        ("ingestions", cols.ingestion_runs_collection, {}),
    ):
        query = {
            **q,
            "_id": {"$gte": ObjectId.from_datetime(lo), "$lt": ObjectId.from_datetime(hi)},
        }
        for d in database[name].find(query, {"_id": 1}):
            acc[bucket_of(d["_id"].generation_time.replace(tzinfo=None))].created[key] += 1


def _point(b: datetime, a: _Acc, first_user: dict, first_visitor: dict) -> UsagePoint:
    new_u = sum(1 for u in a.users if first_user.get(u, b) >= b)
    new_v = sum(1 for x in a.visitors if first_visitor.get(x, b) >= b)
    return UsagePoint(
        period_start=b,
        active_users=len(a.users),
        new_users=new_u,
        returning_users=len(a.users) - new_u,
        logins=sum(a.logins.values()),
        logins_by_method=dict(a.logins),
        visitors=len(a.visitors),
        new_visitors=new_v,
        returning_visitors=len(a.visitors) - new_v,
        visitors_fp=len(a.fps - {None}),
        unique_ips=len(a.ips - {None}),
        pageviews=a.pageviews,
        dashboard_views=a.dviews,
        downloads=a.downloads,
        temporary_users=len(a.temps),
        signups=a.created["signups"],
        new_projects=a.created["new_projects"],
        new_dashboards=a.created["new_dashboards"],
        ingestions=a.created["ingestions"],
    )


def _breakdowns(database: Any, dims: _Dims) -> dict[str, list[dict[str, Any]]]:
    cols = settings.mongodb.collections
    dash_ids = set(dims.dash_views) | set(dims.dash_downloads)
    ids = [ObjectId(i) for i in dash_ids if ObjectId.is_valid(i)]
    dash_docs = {
        str(d["_id"]): d
        for d in database[cols.dashboards_collection].find(
            {"_id": {"$in": ids}}, {"title": 1, "project_id": 1}
        )
    }
    project_views: Counter = Counter()
    for did, n in dims.dash_views.items():
        pid = (dash_docs.get(did) or {}).get("project_id")
        if pid:
            project_views[str(pid)] += n
    names = {
        str(p["_id"]): p.get("name", "")
        for p in database[cols.projects_collection].find(
            {"_id": {"$in": [ObjectId(p) for p in project_views if ObjectId.is_valid(p)]}},
            {"name": 1},
        )
    }

    def top(counter: Counter, key: str = "name", n: int = 15) -> list[dict[str, Any]]:
        return [{key: k, "visitors": v} for k, v in counter.most_common(n) if k]

    return {
        "top_dashboards": [
            {
                "dashboard_id": did,
                "title": (dash_docs.get(did) or {}).get("title") or "(deleted)",
                "project": names.get(str((dash_docs.get(did) or {}).get("project_id")), ""),
                "views": dims.dash_views.get(did, 0),
                "downloads": dims.dash_downloads.get(did, 0),
                "visitors": len(dims.dash_visitors[did]),
            }
            # Views lead the order; a dashboard only downloaded still shows.
            for did in sorted(
                dash_ids, key=lambda d: (dims.dash_views[d], dims.dash_downloads[d]), reverse=True
            )[:15]
        ],
        "top_projects": [
            {"project_id": pid, "name": names.get(pid, "(deleted)"), "views": n}
            for pid, n in project_views.most_common(10)
        ],
        "countries": top(dims.countries, "country", 60),
        "cities": [
            {"country": c, "city": city, "visitors": n}
            for (c, city), n in dims.cities.most_common(25)
        ],
        "browsers": top(dims.browsers),
        "os": top(dims.os),
        "devices": top(dims.devices),
        "languages": top(dims.langs),
        "referrers": [{"domain": k, "visits": v} for k, v in dims.refs.most_common(15)],
        "login_methods": [{"method": k, "logins": v} for k, v in dims.methods.most_common()],
        "visitors_per_ip": [
            {"ip_hash": ip, "visitors": len(vs)}
            for ip, vs in sorted(dims.ip_visitors.items(), key=lambda kv: -len(kv[1]))[:15]
        ],
    }


def _totals(database: Any) -> dict[str, int]:
    cols = settings.mongodb.collections
    users = database[cols.users_collection]
    return {
        "users": users.count_documents(_REAL_USERS),
        "temporary_users": users.count_documents({"is_temporary": True}),
        "projects": database[cols.projects_collection].count_documents({}),
        "dashboards": database[cols.dashboards_collection].count_documents(
            {"parent_dashboard_id": None}
        ),
        "data_collections": database[cols.data_collection].count_documents({}),
    }


def _raw_floor(now: datetime) -> datetime:
    """First day still held as daily rows."""
    return _day(now) - timedelta(days=int(settings.usage_stats.retention_days))


def build_report(
    granularity: Granularity = "month",
    periods: int = 12,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    now: Optional[datetime] = None,
    use_archive: bool = True,
) -> UsageReport:
    """The usage report for ``[start, end)``, plus the same span just before it.

    Periods older than the daily rows' retention come from ``usage_archive``
    (anonymous totals) when one was kept; KPIs and breakdowns cover the daily
    rows only.
    """
    database = _db()
    now = now or utc_now_naive()
    s, e = resolve_range(granularity, periods, start, end, now)
    buckets: list[datetime] = []
    cur = s
    while cur < e:
        buckets.append(cur)
        cur = next_period(cur, granularity)
    prev_s = _back(s, granularity, len(buckets))

    def bucket_of(dt: datetime) -> datetime:
        return _PREV if dt < s else period_start(dt, granularity)

    acc: dict[datetime, _Acc] = defaultdict(_Acc)
    dims = _Dims()
    window = {"day": {"$gte": prev_s, "$lt": e}}
    _fold_visits(database[VISITS].find(window, {"_id": 0}), bucket_of, acc, dims)
    _fold_logins(database[LOGINS].find(window, {"_id": 0}), bucket_of, acc, dims)
    _fold_dashboard_views(database[DASHBOARD_VIEWS].find(window, {"_id": 0}), bucket_of, acc, dims)
    _fold_creations(database, prev_s, e, bucket_of, acc)

    first_user: dict[str, datetime] = {}
    for name in (VISITS, LOGINS):
        for uid, first in _first_seen(database[name], "user_id", e).items():
            first_user[uid] = min(first, first_user.get(uid, first))
    first_visitor = _first_seen(database[VISITS], "visitor_id", e)

    series = [_point(b, acc[b], first_user, first_visitor) for b in buckets]
    archived = 0
    if use_archive:
        floor = _raw_floor(now)
        kept = {
            d["period_start"]: d["point"]
            for d in database[ARCHIVE].find(
                {"granularity": granularity, "period_start": {"$gte": s, "$lt": min(e, floor)}}
            )
        }
        for i, b in enumerate(buckets):
            if b in kept:
                series[i] = UsagePoint(**kept[b])
                archived += 1

    cur_acc = _Acc()
    for b in buckets:
        a = acc[b]
        for name in ("users", "visitors", "ips", "countries"):
            getattr(cur_acc, name).update(getattr(a, name))
    prev = acc[_PREV]

    def returning_pct(users: set, since: datetime) -> float:
        back = sum(1 for u in users if first_user.get(u, since) < since)
        return round(100 * back / len(users), 1) if users else 0

    def total(attr: str) -> int:
        return sum(getattr(p, attr) for p in series)

    kpis = {
        "active_users": UsageKpi(current=len(cur_acc.users), previous=len(prev.users)),
        "logins": UsageKpi(current=total("logins"), previous=sum(prev.logins.values())),
        "signups": UsageKpi(current=total("signups"), previous=prev.created["signups"]),
        "returning_users_pct": UsageKpi(
            current=returning_pct(cur_acc.users, s), previous=returning_pct(prev.users, prev_s)
        ),
        "visitors": UsageKpi(current=len(cur_acc.visitors), previous=len(prev.visitors)),
        "unique_ips": UsageKpi(current=len(cur_acc.ips - {None}), previous=len(prev.ips - {None})),
        "pageviews": UsageKpi(current=total("pageviews"), previous=prev.pageviews),
        "dashboard_views": UsageKpi(current=total("dashboard_views"), previous=prev.dviews),
        "downloads": UsageKpi(current=total("downloads"), previous=prev.downloads),
        "countries": UsageKpi(current=len(cur_acc.countries), previous=len(prev.countries)),
    }

    return UsageReport(
        granularity=granularity,
        start=s,
        end=e,
        generated_at=utc_now_naive(),
        mode=_mode(),
        geoip_available=geoip_available(),
        archived_periods=archived,
        totals=_totals(database),
        kpis=kpis,
        series=series,
        breakdowns=_breakdowns(database, dims),
        hours_heatmap=dims.heat,
    )


def archive_closed_periods(now: Optional[datetime] = None) -> int:
    """Keep anonymous totals of every closed month and year still covered by the
    daily rows, before the TTL removes those rows. Idempotent; never raises."""
    now = now or utc_now_naive()
    database = _db()
    written = 0
    try:
        oldest = database[VISITS].find_one({}, {"day": 1}, sort=[("day", 1)])
        if oldest is None:
            return 0
        for g in _ARCHIVED_GRANULARITIES:
            ps = period_start(oldest["day"], g)
            current = period_start(now, g)
            while ps < current:
                key = f"{g}:{ps.date().isoformat()}"
                if database[ARCHIVE].find_one({"_id": key}, {"_id": 1}) is None:
                    rpt = build_report(g, 1, start=ps, end=ps, now=now, use_archive=False)
                    database[ARCHIVE].update_one(
                        {"_id": key},
                        {
                            "$setOnInsert": {
                                "granularity": g,
                                "period_start": ps,
                                "point": rpt.series[0].model_dump(),
                                "breakdowns": {
                                    k: v
                                    for k, v in rpt.breakdowns.items()
                                    if k not in _NOT_ARCHIVED
                                },
                                "archived_at": now,
                            }
                        },
                        upsert=True,
                    )
                    written += 1
                ps = next_period(ps, g)
    except Exception as exc:
        logger.warning(f"usage_stats: archiving closed periods failed: {exc}")
    return written


SERIES_CSV_FIELDS = [f for f in UsagePoint.model_fields if f != "logins_by_method"]


def report_to_csv(report: UsageReport) -> str:
    lines = [",".join(SERIES_CSV_FIELDS)]
    for p in report.series:
        row = p.model_dump()
        lines.append(
            ",".join(
                row[f].isoformat() if isinstance(row[f], datetime) else str(row[f])
                for f in SERIES_CSV_FIELDS
            )
        )
    return "\n".join(lines) + "\n"
