"""Single-component restore, against the live API.

The unit tests use mongomock and an in-process app. This drives the real
service, because the failure this endpoint is most likely to have is one
mongomock cannot show: an ObjectId that survives the round trip as a string,
leaving a component that looks restored and renders nothing.
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


dashboards = requests.get(f"{API}/dashboards/list_all", headers=H, timeout=30).json()
match = next((d for d in dashboards if d.get("title") == DASHBOARD_TITLE), None)
if match is None:
    sys.exit(f"Dashboard {DASHBOARD_TITLE!r} not found; run rebuild_demo.py first.")
DASH = str(match["dashboard_id"])

versions = requests.get(f"{API}/dashboards/{DASH}/versions", headers=H, timeout=30).json()
named = {
    v["label"]: v for v in versions["versions"] if v.get("label") and v["label"].startswith("v")
}
v1 = named.get("v1 Survey")
if v1 is None:
    sys.exit("No 'v1 Survey' version; run rebuild_demo.py first.")

print(f"dashboard={DASH} restoring from {v1['label']!r}\n")

detail = requests.get(f"{API}/dashboards/versions/{v1['version_id']}", headers=H, timeout=30).json()
snapshot = {str(c["index"]): c for tab in detail["tabs"] for c in tab.get("stored_metadata") or []}

live = requests.get(f"{API}/dashboards/get/{DASH}", headers=H, timeout=30).json()
live_by_index = {str(c["index"]): c for c in live.get("stored_metadata") or []}

# The demo retypes one card between v1 and v2 — same id, different question —
# which is exactly the component worth restoring on its own.
#
# Restricted to a data-bound component on purpose. The dc_id check below asks
# the server to compute a value, and a text tile has no data by design: it
# would report "renders nothing" for a restore that worked perfectly.
target = next(
    (
        idx
        for idx, comp in snapshot.items()
        if idx in live_by_index
        and comp.get("title") != live_by_index[idx].get("title")
        and comp.get("component_type") == "card"
        and comp.get("dc_id")
    ),
    None,
)
if target is None:
    sys.exit(
        "No card differs between v1 and live; nothing to restore. "
        "Run rebuild_demo.py, which builds versions that retype a card."
    )

was = live_by_index[target].get("title")
want = snapshot[target].get("title")
others_before = {i: c.get("title") for i, c in live_by_index.items() if i != target}

print("1. Restoring one component changes only that component")
r = requests.post(
    f"{API}/dashboards/versions/{v1['version_id']}/restore_component",
    headers=H,
    json={"component_index": target},
    timeout=60,
)
check("restore status", r.status_code, 200)

after = requests.get(f"{API}/dashboards/get/{DASH}", headers=H, timeout=30).json()
after_by_index = {str(c["index"]): c for c in after.get("stored_metadata") or []}
check(f"component {target[:8]} title restored", after_by_index[target].get("title"), want)
others_after = {i: c.get("title") for i, c in after_by_index.items() if i != target}
check("every other component untouched", others_after, others_before)

print("\n2. The restored component still renders (dc_id survived as an ObjectId)")
# A string dc_id passes every structural check and then matches no lookup, so
# the only honest test is asking the server to compute the thing.
res = requests.post(
    f"{API}/dashboards/bulk_compute_cards/{DASH}",
    headers=H,
    json={"filters": [], "component_ids": [target]},
    timeout=60,
)
check("bulk-compute status", res.status_code, 200)
if res.status_code == 200:
    value = res.json().get("values", {}).get(target)
    ok = value is not None
    print(f"  {'PASS' if ok else 'FAIL'}  restored component computes a value: {value}")
    if not ok:
        failures.append("restored component renders nothing (dc_id likely a string)")

print("\n3. The pre-restore state was captured, so this is undoable")
after_versions = requests.get(f"{API}/dashboards/{DASH}/versions", headers=H, timeout=30).json()[
    "versions"
]
titles = []
for summary in after_versions[:3]:
    d = requests.get(
        f"{API}/dashboards/versions/{summary['version_id']}", headers=H, timeout=30
    ).json()
    for tab in d.get("tabs") or []:
        for c in tab.get("stored_metadata") or []:
            if str(c.get("index")) == target:
                titles.append(c.get("title"))
ok = was in titles
print(f"  {'PASS' if ok else 'FAIL'}  the overwritten state {was!r} is recoverable")
if not ok:
    failures.append("pre-restore state not captured")

print("\n4. Restoring it back leaves the dashboard as it was found")
# Leaves no trace: this script is run against a live demo, and a check that
# quietly mutates the fixture makes the next run start somewhere else.
back = next(
    (v for v in named.values() if v["label"] == "v4 Complete"),
    None,
)
if back:
    requests.post(
        f"{API}/dashboards/versions/{back['version_id']}/restore_component",
        headers=H,
        json={"component_index": target},
        timeout=60,
    )
    final = requests.get(f"{API}/dashboards/get/{DASH}", headers=H, timeout=30).json()
    final_title = next(
        (c.get("title") for c in final["stored_metadata"] if str(c["index"]) == target), None
    )
    check("component back to its pre-check state", final_title, was)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("ALL PASS")
