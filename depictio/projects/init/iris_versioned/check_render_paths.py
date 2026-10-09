"""Do the non-card render paths honour a data pin?

`bulk_compute_cards` was checked end to end and works. Every other renderer —
figures, tables, maps, images — takes its own endpoint, and a pin that reaches
the request body but is dropped server-side looks exactly like the bug reported
here: "changing data version does not update the underlying data".

Each check pins the collection to a commit whose contents are known and asserts
the response reflects it. A figure drawn from 50 rows and a figure drawn from
150 cannot have the same number of points.
"""

import os
import sys

import requests
import yaml

API = os.environ.get("DEPICTIO_API", "http://localhost:8100") + "/depictio/api/v1"
CONFIG = os.environ.get("DEPICTIO_CLI_CONFIG", "/tmp/admin_cli.yaml")
DASHBOARD_TITLE = os.environ.get("DASHBOARD_TITLE", "Iris Versioned — Survey")

token = yaml.safe_load(open(CONFIG))["user"]["token"]["access_token"]
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

failures: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        failures.append(label)


def differs(label, a, b):
    ok = a != b
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {a} vs {b}")
    if not ok:
        failures.append(f"{label} (identical -> pin ignored)")
        return
    return


dashboards = requests.get(f"{API}/dashboards/list_all", headers=H, timeout=30).json()
match = next((d for d in dashboards if d.get("title") == DASHBOARD_TITLE), None)
if match is None:
    sys.exit(f"Dashboard {DASHBOARD_TITLE!r} not found; run rebuild_demo.py first.")
DASH = str(match["dashboard_id"])

doc = requests.get(f"{API}/dashboards/get/{DASH}", headers=H, timeout=30).json()
meta = doc.get("stored_metadata") or []


def first(kind):
    return next(
        (m for m in meta if m.get("component_type") == kind and m.get("dc_id")),
        None,
    )


figure = first("figure")
table = first("table")
DC = str((figure or table)["dc_id"])
print(f"dashboard={DASH} dc={DC}\n")

# v0 holds 50 rows (Setosa only), v3 holds 150 (all three varieties). Any
# renderer that honours the pin must produce visibly different output.
PINNED = {"data_versions": {DC: 0}}
LIVE: dict = {}

print("1. render_figure honours data_versions")
if figure is None:
    print("  SKIP  no figure component on this dashboard")
else:
    idx = figure["index"]

    def figure_points(body):
        r = requests.post(
            f"{API}/dashboards/render_figure/{DASH}/{idx}",
            headers=H,
            json={"filters": [], "theme": "light", **body},
            timeout=90,
        )
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        spec = r.json()
        data = (spec.get("figure") or {}).get("data") or []
        # Trace count is the cheapest thing that must move: batch 1 has one
        # variety, batch 4 has three, and these charts split by variety.
        total = 0
        for trace in data:
            for axis in ("x", "y"):
                vals = trace.get(axis)
                if isinstance(vals, list):
                    total += len(vals)
        return (len(data), total)

    pinned = figure_points(PINNED)
    live = figure_points(LIVE)
    differs("figure (traces, points) pinned v0 vs live", pinned, live)

print("\n2. render_table honours data_versions")
if table is None:
    print("  SKIP  no table component on this dashboard")
else:
    idx = table["index"]

    def table_rows(body):
        r = requests.post(
            f"{API}/dashboards/render_table/{DASH}/{idx}",
            headers=H,
            json={"filters": [], "offset": 0, "limit": 5, "sort_dir": "desc", **body},
            timeout=90,
        )
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        payload = r.json()
        return payload.get("total") or payload.get("total_rows")

    check("table total @ pinned v0", table_rows(PINNED), 50)
    check("table total @ live", table_rows(LIVE), 150)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("ALL PASS")
