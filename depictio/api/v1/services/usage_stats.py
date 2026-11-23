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
  a local GeoIP file when one is configured.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Iterable, Optional
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
    """Count one login and stamp ``last_login``. Never raises."""
    if not settings.usage_stats.enabled or user is None or getattr(user, "id", None) is None:
        return
    try:
        if request is not None and is_bot(request.headers.get("user-agent", "")):
            return
        now = utc_now_naive()
        day = _day(now)
        database = _db()
        database[LOGINS].update_one(
            {"day": day, "user_id": str(user.id), "method": method[:64]},
            {
                "$inc": {"count": 1},
                "$set": {"user_class": user_class(user), "last_at": now},
            },
            upsert=True,
        )
        database[settings.mongodb.collections.users_collection].update_one(
            {"_id": ObjectId(str(user.id))}, {"$set": {"last_login": now.isoformat()}}
        )
    except Exception as exc:
        logger.warning(f"usage_stats: failed to record login: {exc}")


def record_hit(hit: UsageHit, request: Request, user: Any) -> bool:
    """Upsert today's visit row for this browser (+ dashboard view). Never raises."""
    ua = request.headers.get("user-agent", "")
    if not settings.usage_stats.enabled or is_bot(ua):
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
            "last_seen": now,
            "user_class": cls,
            "ip_hash": keyed_hash(f"ip|{ip}"),
            "fp_hash": keyed_hash(f"fp|{ip}|{ua}"),
            "browser": browser,
            "os": os_name,
            "device": device,
        }
        if user_id:
            on_set["user_id"] = user_id
        if country:
            on_set["country"] = country
            on_set["city"] = city
        on_insert: dict[str, Any] = {"first_seen": now}
        ref = referrer_domain(hit.referrer, request)
        if ref:
            on_insert["referrer"] = ref
        if hit.lang:
            on_insert["lang"] = hit.lang.split("-")[0].lower()[:8]
        database = _db()
        database[VISITS].update_one(
            {"day": day, "visitor_id": hit.visitor_id.lower()},
            {
                "$set": on_set,
                "$setOnInsert": on_insert,
                "$inc": {"pageviews": 1, f"hours.{now.hour}": 1, f"kinds.{hit.path_kind}": 1},
            },
            upsert=True,
        )
        if hit.dashboard_id:
            database[DASHBOARD_VIEWS].update_one(
                {"day": day, "dashboard_id": hit.dashboard_id},
                {
                    "$inc": {"views": 1},
                    "$addToSet": {"visitors": hit.visitor_id.lower()},
                },
                upsert=True,
            )
        return True
    except Exception as exc:
        logger.warning(f"usage_stats: failed to record hit: {exc}")
        return False


# ── Report ───────────────────────────────────────────────────────────────────


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


def resolve_range(
    granularity: Granularity,
    periods: int,
    start: Optional[datetime],
    end: Optional[datetime],
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """``[start, end)`` aligned on period boundaries."""
    now = now or utc_now_naive()
    if start is not None:
        s = period_start(start, granularity)
        e = next_period(period_start(end or now, granularity), granularity)
        return s, max(e, next_period(s, granularity))
    e = next_period(period_start(now, granularity), granularity)
    s = e
    for _ in range(max(1, periods)):
        s = period_start(s - timedelta(days=1), granularity)
    return s, e


def _oid_time(oid: Any) -> Optional[datetime]:
    if isinstance(oid, ObjectId):
        return oid.generation_time.replace(tzinfo=None)
    return None


def _created_between(coll: Any, start: datetime, end: datetime, query: dict | None = None):
    q = dict(query or {})
    q["_id"] = {"$gte": ObjectId.from_datetime(start), "$lt": ObjectId.from_datetime(end)}
    return [_oid_time(d["_id"]) for d in coll.find(q, {"_id": 1})]


def _top(counter: Counter, n: int = 15, key: str = "name") -> list[dict[str, Any]]:
    return [{key: k, "visitors": v} for k, v in counter.most_common(n) if k]


def _mode() -> str:
    if settings.auth.is_single_user_mode:
        return "single_user"
    if settings.auth.is_public_mode:
        return "public"
    return "multi_user"


def _first_seen(coll: Any, field: str, ids: Iterable[str]) -> dict[str, datetime]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    pipeline = [
        {"$match": {field: {"$in": ids}}},
        {"$group": {"_id": f"${field}", "first": {"$min": "$day"}}},
    ]
    return {d["_id"]: d["first"] for d in coll.aggregate(pipeline)}


def build_report(
    granularity: Granularity = "month",
    periods: int = 12,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> UsageReport:
    from depictio.api.v1 import db as dbmod

    database = dbmod.db
    s, e = resolve_range(granularity, periods, start, end, now)
    prev_s = s - (e - s)

    buckets: list[datetime] = []
    cur = s
    while cur < e:
        buckets.append(cur)
        cur = next_period(cur, granularity)

    def bucket_of(dt: datetime) -> Optional[datetime]:
        if dt < s or dt >= e:
            return None
        return period_start(dt, granularity)

    visits = list(database[VISITS].find({"day": {"$gte": prev_s, "$lt": e}}, {"_id": 0}))
    logins = list(database[LOGINS].find({"day": {"$gte": prev_s, "$lt": e}}, {"_id": 0}))
    dviews = list(database[DASHBOARD_VIEWS].find({"day": {"$gte": prev_s, "$lt": e}}, {"_id": 0}))

    real_ids = {v["user_id"] for v in visits if v.get("user_class") == "real" and v.get("user_id")}
    real_ids |= {lg["user_id"] for lg in logins if lg.get("user_class") == "real"}
    first_user: dict[str, datetime] = {}
    for coll in (database[VISITS], database[LOGINS]):
        for uid, first in _first_seen(coll, "user_id", real_ids).items():
            first_user[uid] = min(first, first_user.get(uid, first))
    first_visitor = _first_seen(database[VISITS], "visitor_id", {v["visitor_id"] for v in visits})

    per: dict[datetime, dict[str, Any]] = defaultdict(
        lambda: {
            "users": set(),
            "visitors": set(),
            "fps": set(),
            "ips": set(),
            "temps": set(),
            "logins": Counter(),
            "pageviews": 0,
            "dviews": 0,
        }
    )
    prev: dict[str, Any] = {
        "users": set(),
        "visitors": set(),
        "ips": set(),
        "countries": set(),
        "logins": 0,
        "pageviews": 0,
        "dviews": 0,
        "signups": 0,
    }

    browsers: Counter = Counter()
    oses: Counter = Counter()
    devices: Counter = Counter()
    countries: Counter = Counter()
    cities: Counter = Counter()
    langs: Counter = Counter()
    refs: Counter = Counter()
    seen_dims: set[tuple[str, str]] = set()
    ip_visitors: dict[str, set] = defaultdict(set)
    heat = [[0] * 24 for _ in range(7)]

    for v in visits:
        b = bucket_of(v["day"])
        vid = v["visitor_id"]
        if b is None:
            prev["visitors"].add(vid)
            prev["ips"].add(v.get("ip_hash"))
            prev["pageviews"] += v.get("pageviews", 0)
            if v.get("country"):
                prev["countries"].add(v["country"])
            if v.get("user_class") == "real" and v.get("user_id"):
                prev["users"].add(v["user_id"])
            continue
        p = per[b]
        p["visitors"].add(vid)
        p["fps"].add(v.get("fp_hash"))
        p["ips"].add(v.get("ip_hash"))
        p["pageviews"] += v.get("pageviews", 0)
        if v.get("user_class") == "real" and v.get("user_id"):
            p["users"].add(v["user_id"])
        if v.get("user_class") == "temporary" and v.get("user_id"):
            p["temps"].add(v["user_id"])
        # Breakdowns count each browser once over the whole range.
        if ("v", vid) not in seen_dims:
            seen_dims.add(("v", vid))
            browsers[v.get("browser")] += 1
            oses[v.get("os")] += 1
            devices[v.get("device")] += 1
            if v.get("country"):
                countries[v["country"]] += 1
                cities[(v["country"], v.get("city") or "?")] += 1
            if v.get("lang"):
                langs[v["lang"]] += 1
        if v.get("referrer"):
            refs[v["referrer"]] += 1
        if v.get("ip_hash"):
            ip_visitors[v["ip_hash"]].add(vid)
        wd = v["day"].weekday()
        for h, n in (v.get("hours") or {}).items():
            heat[wd][int(h)] += int(n)

    login_methods: Counter = Counter()
    for lg in logins:
        b = bucket_of(lg["day"])
        n = int(lg.get("count", 1))
        if b is None:
            prev["logins"] += n
            if lg.get("user_class") == "real":
                prev["users"].add(lg["user_id"])
            continue
        per[b]["logins"][lg["method"]] += n
        login_methods[lg["method"]] += n
        if lg.get("user_class") == "real":
            per[b]["users"].add(lg["user_id"])
        elif lg.get("user_class") == "temporary":
            per[b]["temps"].add(lg["user_id"])

    dash_views: Counter = Counter()
    dash_visitors: dict[str, set] = defaultdict(set)
    for dv in dviews:
        b = bucket_of(dv["day"])
        if b is None:
            prev["dviews"] += dv.get("views", 0)
            continue
        per[b]["dviews"] += dv.get("views", 0)
        dash_views[dv["dashboard_id"]] += dv.get("views", 0)
        dash_visitors[dv["dashboard_id"]].update(dv.get("visitors") or [])

    # Creations (ObjectId time) per bucket.
    cols = settings.mongodb.collections
    users_coll = database[cols.users_collection]
    real_user_q = {"is_temporary": {"$ne": True}, "is_anonymous": {"$ne": True}}
    created: dict[str, Counter] = {}
    for key, coll, q in (
        ("signups", users_coll, real_user_q),
        ("new_projects", database[cols.projects_collection], None),
        ("new_dashboards", database[cols.dashboards_collection], {"parent_dashboard_id": None}),
        ("ingestions", database[cols.ingestion_runs_collection], None),
    ):
        c: Counter = Counter()
        for t in _created_between(coll, prev_s, e, q):
            if t is None:
                continue
            b = bucket_of(t)
            if b is None:
                if key == "signups":
                    prev["signups"] += 1
            else:
                c[b] += 1
        created[key] = c

    series: list[UsagePoint] = []
    for b in buckets:
        p = per[b]
        users = p["users"]
        new_u = sum(1 for u in users if first_user.get(u, b) >= b)
        vis = p["visitors"]
        new_v = sum(1 for x in vis if first_visitor.get(x, b) >= b)
        series.append(
            UsagePoint(
                period_start=b,
                active_users=len(users),
                new_users=new_u,
                returning_users=len(users) - new_u,
                logins=sum(p["logins"].values()),
                logins_by_method=dict(p["logins"]),
                visitors=len(vis),
                new_visitors=new_v,
                returning_visitors=len(vis) - new_v,
                visitors_fp=len(p["fps"] - {None}),
                unique_ips=len(p["ips"] - {None}),
                pageviews=p["pageviews"],
                dashboard_views=p["dviews"],
                temporary_users=len(p["temps"]),
                signups=created["signups"][b],
                new_projects=created["new_projects"][b],
                new_dashboards=created["new_dashboards"][b],
                ingestions=created["ingestions"][b],
            )
        )

    all_users: set = set().union(*(per[b]["users"] for b in buckets)) if buckets else set()
    all_visitors: set = set().union(*(per[b]["visitors"] for b in buckets)) if buckets else set()
    all_ips: set = set().union(*(per[b]["ips"] for b in buckets)) - {None} if buckets else set()

    def kpi(cur_v: float, prev_v: float) -> UsageKpi:
        return UsageKpi(current=cur_v, previous=prev_v)

    kpis = {
        "active_users": kpi(len(all_users), len(prev["users"])),
        "logins": kpi(sum(sp.logins for sp in series), prev["logins"]),
        "signups": kpi(sum(sp.signups for sp in series), prev["signups"]),
        "returning_users_pct": kpi(
            round(100 * sum(1 for u in all_users if first_user.get(u, s) < s) / len(all_users), 1)
            if all_users
            else 0,
            0,
        ),
        "visitors": kpi(len(all_visitors), len(prev["visitors"])),
        "unique_ips": kpi(len(all_ips), len(prev["ips"] - {None})),
        "pageviews": kpi(sum(sp.pageviews for sp in series), prev["pageviews"]),
        "dashboard_views": kpi(sum(sp.dashboard_views for sp in series), prev["dviews"]),
        "countries": kpi(len(countries), len(prev["countries"])),
    }

    # Titles for the top dashboards / projects (no ids without a name in the UI).
    top_ids = [d for d, _ in dash_views.most_common(15)]
    dash_docs = {
        str(d["_id"]): d
        for d in database[cols.dashboards_collection].find(
            {"_id": {"$in": [ObjectId(i) for i in top_ids if ObjectId.is_valid(i)]}},
            {"title": 1, "project_id": 1},
        )
    }
    project_views: Counter = Counter()
    for did, n in dash_views.items():
        doc = dash_docs.get(did)
        if doc and doc.get("project_id"):
            project_views[str(doc["project_id"])] += n
    proj_ids = [ObjectId(p) for p in project_views if ObjectId.is_valid(p)]
    proj_names = {
        str(p["_id"]): p.get("name", "")
        for p in database[cols.projects_collection].find({"_id": {"$in": proj_ids}}, {"name": 1})
    }

    breakdowns: dict[str, list[dict[str, Any]]] = {
        "top_dashboards": [
            {
                "dashboard_id": did,
                "title": (dash_docs.get(did) or {}).get("title") or "(deleted)",
                "project": proj_names.get(str((dash_docs.get(did) or {}).get("project_id")), ""),
                "views": n,
                "visitors": len(dash_visitors[did]),
            }
            for did, n in dash_views.most_common(15)
        ],
        "top_projects": [
            {"project_id": pid, "name": proj_names.get(pid, "(deleted)"), "views": n}
            for pid, n in project_views.most_common(10)
        ],
        "countries": _top(countries, 50, "country"),
        "cities": [
            {"country": c, "city": city, "visitors": n} for (c, city), n in cities.most_common(25)
        ],
        "browsers": _top(browsers),
        "os": _top(oses),
        "devices": _top(devices),
        "languages": _top(langs),
        "referrers": [{"domain": k, "visits": v} for k, v in refs.most_common(15)],
        "login_methods": [{"method": k, "logins": v} for k, v in login_methods.most_common()],
        "visitors_per_ip": [
            {"ip_hash": ip, "visitors": len(vs)}
            for ip, vs in sorted(ip_visitors.items(), key=lambda kv: -len(kv[1]))[:15]
        ],
    }

    totals = {
        "users": users_coll.count_documents(real_user_q),
        "temporary_users": users_coll.count_documents({"is_temporary": True}),
        "projects": database[cols.projects_collection].count_documents({}),
        "dashboards": database[cols.dashboards_collection].count_documents(
            {"parent_dashboard_id": None}
        ),
        "data_collections": database[cols.data_collection].count_documents({}),
    }

    return UsageReport(
        granularity=granularity,
        start=s,
        end=e,
        generated_at=utc_now_naive(),
        mode=_mode(),  # type: ignore[arg-type]
        geoip_available=geoip_available(),
        totals=totals,
        kpis=kpis,
        series=series,
        breakdowns=breakdowns,
        hours_heatmap=heat,
    )


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
