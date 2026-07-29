"""End-to-end check of dataset time travel + component history on the live stack.

Drives the real HTTP API against the ingested iris_versioned demo, which has
three Delta commits (100 rows / 150 rows / 150 rows recalibrated) and a real
dashboard. Everything here is a claim the features make to a user; if any of
it is wrong the feature is lying, not merely broken.
"""

import json
import os
import sys

import requests
import yaml

# Everything is discovered from the running instance rather than hard-coded,
# so this runs against any deployment that has the demo ingested. Only the API
# root and the CLI config need supplying, and both have sensible defaults.
API = os.environ.get("DEPICTIO_API", "http://localhost:8100") + "/depictio/api/v1"
CONFIG = os.environ.get("DEPICTIO_CLI_CONFIG", "/tmp/admin_cli.yaml")
DASHBOARD_TITLE = os.environ.get("DASHBOARD_TITLE", "Iris Versioned — Survey")

token = yaml.safe_load(open(CONFIG))["user"]["token"]["access_token"]
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def discover():
    """Find the demo dashboard, its data collection and a card to compute."""
    dashboards = requests.get(f"{API}/dashboards/list_all", headers=H, timeout=30).json()
    match = next((d for d in dashboards if d.get("title") == DASHBOARD_TITLE), None)
    if match is None:
        sys.exit(
            f"Dashboard {DASHBOARD_TITLE!r} not found. Ingest the demo first "
            "(see README) or set DASHBOARD_TITLE."
        )
    dashboard_id = str(match["dashboard_id"])

    doc = requests.get(f"{API}/dashboards/get/{dashboard_id}", headers=H, timeout=30).json()
    card = next(
        (
            m
            for m in doc.get("stored_metadata") or []
            if m.get("component_type") == "card" and m.get("dc_id")
        ),
        None,
    )
    if card is None:
        sys.exit("The demo dashboard has no card bound to a data collection.")
    return dashboard_id, str(card["dc_id"]), str(card["index"])


DASH, DC, CARD = discover()
print(f"dashboard={DASH} dc={DC} card={CARD}\n")

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        failures.append(label)


def close(label, got, want, tol=1e-6):
    ok = got is not None and abs(got - want) < tol
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        failures.append(label)


print("1. Save writes a version whose stamps record a real Delta commit")
live = requests.get(f"{API}/dashboards/get/{DASH}", headers=H, timeout=30).json()
# Round-trip the whole document, which is what the editor posts. A partial
# body 422s, and a 422 would leave the pre-fix version as "newest" and make
# the stamp assertions below silently check the wrong record.
#
# The subtitle nudge is load-bearing: an unchanged save deliberately writes no
# version (content is hashed and compared), so re-posting the document
# verbatim would leave the newest version as a pre-fix record and the stamp
# assertions would silently grade the wrong row.
live["subtitle"] = f"e2e check {json.dumps(len(live.get('stored_metadata') or []))}"
r = requests.post(f"{API}/dashboards/save/{DASH}", headers=H, json=live, timeout=60)
check("save status", r.status_code, 200)

versions = requests.get(f"{API}/dashboards/{DASH}/versions", headers=H, timeout=30).json()
newest = versions["versions"][0]
detail = requests.get(
    f"{API}/dashboards/versions/{newest['version_id']}", headers=H, timeout=30
).json()
stamps = detail.get("data_collections") or []
check("stamp count", len(stamps), 1)
check("stamp kind", stamps[0].get("version_kind"), "delta")
check("stamp delta_version", stamps[0].get("delta_version"), 2)
check("stamp tag", stamps[0].get("data_collection_tag"), "iris_versioned_table")

print("\n2. Dataset time travel: the card reads each commit's own data")
for delta_version, want in ((0, 100), (1, 150), (2, 150)):
    res = requests.post(
        f"{API}/dashboards/bulk_compute_cards/{DASH}",
        headers=H,
        json={"filters": [], "component_ids": [CARD], "data_versions": {DC: delta_version}},
        timeout=60,
    ).json()
    check(f"count @ delta v{delta_version}", res["values"][CARD], want)

print("\n3. as_of_version expands a stored version's stamps into pins")
res = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={"filters": [], "component_ids": [CARD], "as_of_version": newest["version_id"]},
    timeout=60,
).json()
check("count as of newest version", res["values"][CARD], 150)

print("\n4. Equal row counts, different values — a version-blind cache would pass on rows alone")
for delta_version, want in ((1, 3.7579999999999996), (2, 3.5600666666666667)):
    res = requests.post(
        f"{API}/dashboards/bulk_compute_cards/{DASH}",
        headers=H,
        json={
            "filters": [],
            "component_ids": [CARD],
            "data_versions": {DC: delta_version},
            "component_overrides": {CARD: {"column_name": "petal.length", "aggregation": "mean"}},
        },
        timeout=60,
    ).json()
    close(f"mean petal.length @ delta v{delta_version}", res["values"][CARD], want, tol=1e-9)

print("\n5. Live reads are unaffected by the pinned reads above (no cache poisoning)")
res = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={"filters": [], "component_ids": [CARD]},
    timeout=60,
).json()
check("live count still current", res["values"][CARD], 150.0)

print("\n6. Boundaries hold")
res = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={
        "filters": [],
        "component_ids": [CARD],
        "component_overrides": {
            CARD: {"dc_id": "646b0f3c1e4a2d7f8e5b8c9c", "aggregation": "count"}
        },
    },
    timeout=60,
).json()
check("dc_id override ignored", res["values"][CARD], 150.0)

r = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={"filters": [], "as_of_version": "does-not-exist"},
    timeout=60,
)
check("stale as_of_version rejected", r.status_code, 400)

r = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={"filters": [], "component_ids": [CARD], "component_overrides": {CARD: "not-a-dict"}},
    timeout=60,
)
check("malformed override degrades gracefully", r.status_code, 200)

print("\n7. Dataset history powers the picker")
hist = requests.get(f"{API}/deltatables/history/{DC}", headers=H, timeout=30).json()
check("current_version", hist["current_version"], 2)
check("degraded", hist["degraded"], False)
check("selectable commits", len([v for v in hist["versions"] if v.get("version") is not None]), 3)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("ALL PASS")
