# Internal usage statistics

Lightweight, self-hosted usage analytics: who uses the instance, how often, from
where, and what they open. The data stays in this deployment's MongoDB and is never
sent anywhere. You can read it in **Admin › Activity › Usage**, or fetch it from the API for
reports (agents, cron jobs).

On by default. Turn it off with `DEPICTIO_USAGE_STATS_ENABLED=false`, which makes the routes
return 404 and stops all recording.

## What is recorded

| Collection | One row per | Written by |
| --- | --- | --- |
| `usage_logins` | day × user × method | every token issue: `password`, `oidc:<provider>`, `magic_link`, `temporary` (public-mode guest), `single_user` |
| `usage_visits` | day × browser (`visitor_id`) | `POST /analytics/hit`, sent by the viewer once per page load |
| `usage_dashboard_views` | day × dashboard | the same beacon, when a dashboard is opened |

Rows are upserts. Their number grows with visitors × days, not with requests, and a TTL
index on `day` removes them after `DEPICTIO_USAGE_STATS_RETENTION_DAYS` (default 395, i.e.
13 months; capped at 25 months). A login also sets `users.last_login`.

**After 13 months: anonymous totals.** Before the daily rows expire, every closed month
and year is copied into `usage_archive` as totals only: the `UsagePoint` counts and the
breakdowns (countries, browsers, top dashboards…), without any visitor id, user id or
address hash. The copy runs daily and whenever the report is opened, and it is idempotent.
Archived totals are not personal data, so they are kept. A report over older periods reads
their series from the archive (`archived_periods` in the response). KPIs and breakdowns
always come from the daily rows.

**Flood guard.** The beacon needs no login. To keep a script minting a fresh browser id
per request from growing the table, at most `DEPICTIO_USAGE_STATS_MAX_DAILY_VISITORS`
(default 50,000) new browsers are recorded per day; known browsers keep counting. A
dashboard row keeps at most 2,000 distinct browsers per day, and its views keep counting
past that.

Bots and headless browsers are dropped by user agent. That covers crawlers, curl and
python-requests, Playwright and the screenshot engine. `/embed` renders send no beacon.

## Counting visitors, and shared addresses (NAT)

An institute often reaches the instance through one public address, so a count based on
the IP alone would show a single visitor. Three counts are reported side by side:

- **`visitors`**: distinct browsers. The viewer keeps a random UUID in localStorage. This
  count is correct behind a NAT and is the headline count in public mode.
- **`visitors_fp`**: distinct keyed hashes of IP + user agent, Umami's cookie-free approach.
  It undercounts identical machines behind one address. It is kept as a cross-check, or
  for browsers that block storage.
- **`unique_ips`**: distinct addresses, as hashes. The *Browsers per address* table lists
  the addresses that carry many browsers, which is a way to spot institutes.

## Users per deployment mode

| Mode | "Users" means | Headline numbers |
| --- | --- | --- |
| multi-user | real accounts (not temporary, not anonymous) | active users, logins (by method), new vs returning, new accounts |
| public / demo | real accounts only. Each guest's temporary account is counted apart (`temporary_users`) and never as a user | visitors, unique IPs, countries, page views |
| single-user | the one owner (`user_class=single_user`) | page views, dashboard views, browsers |

*Returning* means active in the period and already seen in an earlier period. *New* means
first seen in the period. Both are judged within the daily rows' retention (13 months), so a
person last seen more than 13 months ago counts as new again.

## Privacy

- **IP addresses** are never stored. Each one is reduced to an HMAC-SHA256 under a random
  per-instance key (`instance_settings._id = usage_stats_salt`). That key is not reversible
  without database access, and it is stable, so distinct addresses can still be counted
  over a year.
- **User agents** are never stored. Each one is reduced to a browser family, an OS family
  and a device class.
- **Referrers** are kept as the external domain only. Navigation within the site is not a
  referrer.
- **Responses** contain no emails and no IPs. Dashboards and projects appear by title.
- **Client IP**: `X-Real-IP` is honoured only when the TCP peer is a private or loopback
  address, i.e. the bundled nginx or an ingress. A client reaching the API directly is
  identified by its own address and cannot forge the header. The auth rate limiter uses
  the same rule.

## GDPR

The operator of the instance is the controller. Depictio's maintainers receive none of
this data.

- **Purpose and legal basis.** The data serves audience measurement of the instance
  itself: how many people use it, how often, which dashboards. Legal basis: legitimate
  interest (Art. 6(1)(f)). The design follows the conditions under which the CNIL exempts
  audience measurement from consent:
  - first-party only, never shared or combined with other data;
  - aggregated output;
  - browser identifier renewed after 13 months;
  - daily rows kept 13 months (at most 25);
  - IP addresses hashed;
  - location no finer than the city.
- **Information and objection.** The *About* page has a *Privacy* notice describing exactly
  what is recorded, and a switch that excludes the browser. Opting out also forgets its
  identifier. Browsers sending **Do Not Track** or **Global Privacy Control** are never
  recorded: the viewer sends nothing, and the API drops such hits.
- **Erasure.** Deleting an account deletes its login and visit rows and removes its browsers
  from the per-dashboard lists. Anonymous archived totals are unaffected; they hold nothing
  about the person.
- **No profiling.** Responses hold counts, titles and hashes only. The per-address table
  shows hashes truncated to 8 characters, to admins only.
- **Your obligations as operator.** Mention the statistics in your instance's privacy
  policy (the About notice can serve as the basis), and keep the retention at or below
  25 months. In the EU, if you enable GeoIP, keep it at city level, which is what DB-IP
  Lite provides.

## Countries and cities (optional)

Point `DEPICTIO_USAGE_STATS_GEOIP_DB_PATH` at a City `.mmdb` file, either
[DB-IP Lite](https://db-ip.com/db/lite.php) (CC-BY 4.0, no key) or MaxMind GeoLite2. The
lookup runs when a beacon arrives, and only the country code and city name are stored.
Without the file, the geo panels are hidden and `geoip_available` is `false`. In Helm, mount
the file into the backend and set the variable through `backend.env`. Refresh it monthly.

> IP geolocation by DB-IP.com (CC-BY 4.0), when DB-IP Lite is used.

## API (for agents and reports)

`GET /depictio/api/v1/analytics/usage` needs an admin token **or** the internal API key in
`X-Api-Key` (`DEPICTIO_AUTH_INTERNAL_API_KEY`).

| Query | Default | |
| --- | --- | --- |
| `granularity` | `month` | `day`, `week` (ISO, Monday), `month`, `year` |
| `periods` | `12` | number of periods ending with the current one |
| `start`, `end` | – | custom range (UTC, an offset is converted), aligned on period boundaries. `end` is **inclusive of its period** (`end=2026-04-01` with `month` includes April). `end` alone anchors `periods` |
| `format` | `json` | `csv` returns the time series only |

```bash
# Last 12 months, everything (KPIs with previous-period values, series, breakdowns)
curl -s -H "X-Api-Key: $KEY" "https://depictio.example.org/depictio/api/v1/analytics/usage?granularity=month&periods=12"

# Weekly series as CSV for a spreadsheet
curl -s -H "X-Api-Key: $KEY" "https://depictio.example.org/depictio/api/v1/analytics/usage?granularity=week&periods=26&format=csv"

# A token-cheap summary for an agent
curl -s -H "X-Api-Key: $KEY" ".../analytics/usage?granularity=month&periods=1" | jq '{mode, totals, kpis}'
```

The JSON has these top-level fields:

- `mode`, `start` / `end` (`[start, end)`), `geoip_available`;
- `totals`: users, temporary users, projects, dashboards, data collections, all time;
- `kpis`: `{current, previous}` for the range and for the range of the same length just
  before it;
- `series[]`: one entry per period (see `UsagePoint` in `depictio/models/models/usage.py`);
- `breakdowns`: top dashboards and projects, countries, cities, browsers, OS, devices,
  languages, referrers, login methods, browsers per address;
- `hours_heatmap`: page views as 7 × 24 (Mon..Sun × UTC hour).

The viewer beacon is `POST /analytics/hit`. It is rate-limited per address and
returns 204 with no body.

## Replaced system

The previous `DEPICTIO_ANALYTICS_*` subsystem is removed, along with its per-request
middleware, `/analytics-data/*`, `user_sessions` and `user_activities`. Its environment
variables are ignored, and its collections are left in place rather than dropped. Drop
them by hand once they are no longer needed.
