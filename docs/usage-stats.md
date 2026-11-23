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
index on `day` removes them after `DEPICTIO_USAGE_STATS_RETENTION_DAYS` (default 400, so a
year can be compared with the previous one). A login also sets `users.last_login`.

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

*Returning* means active in the period and already seen in an earlier period (first
activity within the retention window). *New* means first seen in the period.

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
- **Client IP** comes from `X-Real-IP` (set by the bundled nginx / ingress-nginx), or
  otherwise from the TCP peer. This is the same rule as the auth rate limiter. Make sure
  your proxy overwrites `X-Real-IP`. A client that can reach the API directly can set it
  itself.

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
| `start`, `end` | – | custom range (UTC dates), aligned on period boundaries; overrides `periods` |
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
