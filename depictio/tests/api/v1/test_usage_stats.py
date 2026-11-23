"""Internal usage statistics: rollup writes, the period report, access."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException
from mongomock import MongoClient

from depictio.api.v1.services import usage_stats as us
from depictio.models.models.usage import UsageHit

CHROME = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
def db():
    client = MongoClient()
    database = client.usage_test
    us._instance_key.cache_clear()
    with patch("depictio.api.v1.db.db", database):
        yield database
    us._instance_key.cache_clear()
    client.close()


def _request(ip: str, ua: str, host: str = "depictio.example.org"):
    return SimpleNamespace(
        headers={"user-agent": ua, "x-real-ip": ip},
        client=SimpleNamespace(host=ip),
        url=SimpleNamespace(hostname=host),
    )


def _user(uid: str | None = None, temporary: bool = False):
    return SimpleNamespace(
        id=ObjectId(uid) if uid else ObjectId(), is_temporary=temporary, is_anonymous=False
    )


def _vid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-000000000000"


def _hit_on(day: datetime, vid: str, ip: str, ua: str = CHROME, user=None, **kw):
    with patch.object(us, "utc_now_naive", return_value=day):
        return us.record_hit(UsageHit(visitor_id=vid, **kw), _request(ip, ua), user)


def test_user_agent_parsing_and_bot_filter():
    assert us.parse_user_agent(CHROME) == ("Chrome", "Linux", "desktop")
    assert us.parse_user_agent(FIREFOX) == ("Firefox", "Windows", "desktop")
    assert us.parse_user_agent(IPHONE) == ("Safari", "iOS", "mobile")
    assert us.is_bot("Mozilla/5.0 HeadlessChrome/120.0")
    assert us.is_bot("Googlebot/2.1")
    assert us.is_bot("")
    assert not us.is_bot(CHROME)


def test_hit_is_one_row_per_browser_per_day_and_stores_no_raw_ip(db):
    day = datetime(2026, 3, 4, 10)
    for _ in range(3):
        assert _hit_on(day, _vid(1), "10.1.2.3", dashboard_id="a" * 24)
    assert not _hit_on(day, _vid(2), "10.1.2.3", ua="curl/8.0")  # bot: dropped

    rows = list(db[us.VISITS].find())
    assert len(rows) == 1
    row = rows[0]
    assert row["pageviews"] == 3 and row["hours"] == {"10": 3}
    assert "10.1.2.3" not in str(row) and "Chrome/120" not in str(row)
    assert row["ip_hash"] == us.keyed_hash("ip|10.1.2.3")  # stable across calls
    dv = db[us.DASHBOARD_VIEWS].find_one()
    assert dv["views"] == 3 and dv["visitors"] == [_vid(1)]


def test_shared_nat_address_still_counts_each_browser(db):
    day = datetime(2026, 3, 4)
    for i, ua in enumerate([CHROME, CHROME, FIREFOX]):
        _hit_on(day, _vid(i), "192.0.2.7", ua=ua)
    report = us.build_report("month", 1, now=day)
    point = report.series[-1]
    assert point.visitors == 3
    assert point.unique_ips == 1
    # The cookie-free hash cannot tell two identical browsers apart.
    assert point.visitors_fp == 2
    assert report.breakdowns["visitors_per_ip"][0]["visitors"] == 3


@pytest.mark.asyncio
async def test_logins_bucketed_by_week_with_methods_and_last_login(db):
    real = _user()
    temp = _user(temporary=True)
    db.users.insert_many([{"_id": real.id}, {"_id": temp.id, "is_temporary": True}])
    for when, user, method in [
        (datetime(2026, 3, 2), real, "password"),  # Monday, week 10
        (datetime(2026, 3, 3), real, "oidc:google"),
        (datetime(2026, 3, 10), real, "password"),  # week 11
        (datetime(2026, 3, 10), temp, "temporary"),
    ]:
        with patch.object(us, "utc_now_naive", return_value=when):
            await us.record_login(user, method)

    assert db.users.find_one({"_id": real.id})["last_login"].startswith("2026-03-10")
    report = us.build_report("week", 2, now=datetime(2026, 3, 11))
    w10, w11 = report.series
    assert w10.period_start == datetime(2026, 3, 2)
    assert (w10.active_users, w10.logins, w10.new_users) == (1, 2, 1)
    assert w10.logins_by_method == {"password": 1, "oidc:google": 1}
    # Week 11: the same person comes back, the guest is not a "user".
    assert (w11.active_users, w11.returning_users, w11.temporary_users) == (1, 1, 1)
    assert report.kpis["active_users"].current == 1
    methods = {m["method"]: m["logins"] for m in report.breakdowns["login_methods"]}
    assert methods == {"password": 2, "oidc:google": 1, "temporary": 1}


def test_custom_range_previous_period_and_content(db):
    proj = ObjectId.from_datetime(datetime(2026, 2, 10))
    dash = ObjectId.from_datetime(datetime(2026, 2, 11))
    db.projects.insert_one({"_id": proj, "name": "Iris"})
    db.dashboards.insert_one(
        {"_id": dash, "title": "Overview", "project_id": proj, "parent_dashboard_id": None}
    )
    _hit_on(datetime(2026, 1, 15), _vid(1), "198.51.100.1")  # previous period
    _hit_on(datetime(2026, 2, 12), _vid(1), "198.51.100.1", dashboard_id=str(dash))
    _hit_on(datetime(2026, 2, 13), _vid(2), "198.51.100.2", ua=IPHONE, lang="fr-FR")

    report = us.build_report("month", 1, start=datetime(2026, 2, 1), end=datetime(2026, 2, 20))
    assert (report.start, report.end) == (datetime(2026, 2, 1), datetime(2026, 3, 1))
    (feb,) = report.series
    assert (feb.visitors, feb.new_visitors, feb.returning_visitors) == (2, 1, 1)
    assert (feb.new_projects, feb.new_dashboards, feb.dashboard_views) == (1, 1, 1)
    assert report.kpis["visitors"].previous == 1
    assert report.breakdowns["top_dashboards"][0]["title"] == "Overview"
    assert report.breakdowns["top_projects"][0]["name"] == "Iris"
    assert {"name": "fr", "visitors": 1} in report.breakdowns["languages"]
    assert {d["name"] for d in report.breakdowns["devices"]} == {"desktop", "mobile"}
    assert report.totals["projects"] == 1 and report.geoip_available is False

    csv = us.report_to_csv(report)
    header, row = csv.strip().splitlines()
    assert header.startswith("period_start,active_users")
    assert row.startswith("2026-02-01T00:00:00,")


def test_external_referrer_domain_only(db):
    req = _request("203.0.113.9", CHROME)
    assert us.referrer_domain("https://www.embl.org/page?x=1", req) == "www.embl.org"
    assert us.referrer_domain("https://depictio.example.org/dashboards", req) is None
    assert us.referrer_domain(None, req) is None


def test_hit_payload_rejects_a_non_uuid_visitor():
    with pytest.raises(ValueError):
        UsageHit(visitor_id="<script>")


@pytest.mark.asyncio
async def test_report_access_requires_admin_or_api_key():
    from depictio.api.v1.endpoints.analytics_endpoints import routes

    admin = SimpleNamespace(id="a", is_admin=True, is_temporary=False)
    guest_admin = SimpleNamespace(id="b", is_admin=True, is_temporary=True)
    plain = SimpleNamespace(id="c", is_admin=False, is_temporary=False)

    async def fetch(token):
        return {"admin": admin, "guest": guest_admin, "plain": plain}.get(token)

    with (
        patch.object(routes, "_async_fetch_user_from_token", side_effect=fetch),
        patch.object(
            type(routes.settings.auth), "internal_api_key", property(lambda _self: "k" * 32)
        ),
    ):
        await routes.require_analytics_admin(token="admin", x_api_key=None)
        await routes.require_analytics_admin(token=None, x_api_key="k" * 32)
        for token, key in [("plain", None), ("guest", None), (None, "wrong"), (None, None)]:
            with pytest.raises(HTTPException) as exc:
                await routes.require_analytics_admin(token=token, x_api_key=key)
            assert exc.value.status_code == 403


def test_hit_route_records_anonymously_and_returns_no_body(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from depictio.api.v1.endpoints.analytics_endpoints import routes

    app = FastAPI()
    app.include_router(routes.router, prefix="/analytics")
    with patch.object(routes, "enforce_rate_limit"):
        client = TestClient(app)
        ok = client.post(
            "/analytics/hit",
            json={"visitor_id": _vid(9), "path_kind": "dashboards"},
            headers={"user-agent": CHROME},
        )
        bad = client.post("/analytics/hit", json={"visitor_id": "x"})
        report = client.get("/analytics/usage")
    assert ok.status_code == 204 and ok.content == b""
    assert bad.status_code == 422
    assert report.status_code == 403
    row = db[us.VISITS].find_one()
    assert row["user_class"] == "anonymous" and row["kinds"] == {"dashboards": 1}
