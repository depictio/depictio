"""What the component-history modal will actually show, per version.

The modal's central claim is that one component, viewed at each version, shows
what it showed then — the config of that version drawn against the data of that
version. That is two axes at once, and either being ignored produces a modal
that looks right and lies:

* config ignored -> today's question asked of yesterday's data;
* data ignored   -> yesterday's chart drawn over today's numbers.

This drives the exact calls the modal makes (`bulk_compute_cards` with
`component_overrides` + `data_versions`) and asserts the values differ where
they must. Run against the live stack after `rebuild_demo.py`.
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


def fail(label, detail):
    print(f"  FAIL  {label}: {detail}")
    failures.append(label)


def ok(label, detail):
    print(f"  PASS  {label}: {detail}")


dashboards = requests.get(f"{API}/dashboards/list_all", headers=H, timeout=30).json()
match = next((d for d in dashboards if d.get("title") == DASHBOARD_TITLE), None)
if match is None:
    sys.exit(f"Dashboard {DASHBOARD_TITLE!r} not found; run rebuild_demo.py first.")
DASH = str(match["dashboard_id"])

versions = requests.get(f"{API}/dashboards/{DASH}/versions", headers=H, timeout=30).json()
named = [
    v
    for v in sorted(versions["versions"], key=lambda x: x["seq"])
    if v.get("label") and v["label"].startswith("v")
]
if len(named) < 2:
    sys.exit("Fewer than two named versions; run rebuild_demo.py first.")

details = {}
for v in named:
    details[v["version_id"]] = requests.get(
        f"{API}/dashboards/versions/{v['version_id']}", headers=H, timeout=30
    ).json()


def component_in(detail, index):
    for tab in detail.get("tabs") or []:
        for component in tab.get("stored_metadata") or []:
            if str(component.get("index")) == index:
                return component
    return None


def stamp_in(detail, dc_id):
    for stamp in detail.get("data_collections") or []:
        if str(stamp.get("dc_id")) == str(dc_id):
            if stamp.get("version_kind") == "delta":
                return stamp.get("delta_version")
    return None


print(f"dashboard={DASH}\n")

print("1. The modal can find the same component in every version")
# This is what silently failed before component ids were derived from the YAML
# tag: with fresh ids per import, the modal reported "did not exist in that
# version" for every component in every version.
first = details[named[0]["version_id"]]
last = details[named[-1]["version_id"]]
first_ids = {
    str(c["index"]) for tab in first.get("tabs") or [] for c in tab.get("stored_metadata") or []
}
last_ids = {
    str(c["index"]) for tab in last.get("tabs") or [] for c in tab.get("stored_metadata") or []
}
shared = first_ids & last_ids
if not shared:
    fail("shared component ids", "none — component history can follow nothing")
else:
    ok("component ids present in both first and last version", len(shared))

print("\n2. A retyped card reads differently at each version")
# The demo retypes one card: mean petal length in v1, variety count afterwards.
# Same component id, genuinely different question.
target = None
for index in sorted(shared):
    titles = {
        v["label"]: (component_in(details[v["version_id"]], index) or {}).get("title")
        for v in named
    }
    kinds = {
        (component_in(details[v["version_id"]], index) or {}).get("component_type") for v in named
    }
    if len(set(titles.values())) > 1 and kinds == {"card"}:
        target = index
        break

if target is None:
    fail("a card that changes across versions", "none found")
else:
    dc_id = str((component_in(first, target) or {}).get("dc_id") or "")
    seen = []
    for v in named:
        detail = details[v["version_id"]]
        component = component_in(detail, target)
        if component is None:
            continue
        delta = stamp_in(detail, dc_id)
        body = {
            "filters": [],
            "component_ids": [target],
            "component_overrides": {target: component},
        }
        if delta is not None:
            body["data_versions"] = {dc_id: delta}
        res = requests.post(
            f"{API}/dashboards/bulk_compute_cards/{DASH}", headers=H, json=body, timeout=60
        )
        if res.status_code != 200:
            fail(f"{v['label']} compute", f"HTTP {res.status_code}")
            continue
        value = res.json().get("values", {}).get(target)
        seen.append((v["label"], component.get("title"), delta, value))
        print(
            f"  ....  {v['label']:18} {str(component.get('title'))[:22]:24} "
            f"data v{delta}  ->  {value}"
        )

    values = [s[3] for s in seen]
    if len(set(values)) > 1:
        ok("values differ across versions", f"{values}")
    else:
        fail("values differ across versions", f"all identical: {values}")

print("\n3. The two axes are independent")
# The modal lets a version's config be drawn against any commit. Holding the
# config fixed while moving the data must still change the answer, or the
# dataset select is decoration.
if target is not None:
    component = component_in(last, target)
    dc_id = str((component or {}).get("dc_id") or "")
    by_commit = {}
    for delta in (0, 3):
        res = requests.post(
            f"{API}/dashboards/bulk_compute_cards/{DASH}",
            headers=H,
            json={
                "filters": [],
                "component_ids": [target],
                "component_overrides": {target: component},
                "data_versions": {dc_id: delta},
            },
            timeout=60,
        )
        by_commit[delta] = res.json().get("values", {}).get(target)
    print(f"  ....  newest config @ data v0 -> {by_commit[0]}")
    print(f"  ....  newest config @ data v3 -> {by_commit[3]}")
    if by_commit[0] != by_commit[3]:
        ok("same config, different data, different answer", f"{by_commit[0]} vs {by_commit[3]}")
    else:
        fail("same config, different data", f"identical: {by_commit[0]}")

print("\n4. The compare pane's 'current' half reads live data")
if target is not None:
    component = component_in(last, target)
    live = (
        requests.post(
            f"{API}/dashboards/bulk_compute_cards/{DASH}",
            headers=H,
            json={"filters": [], "component_ids": [target]},
            timeout=60,
        )
        .json()
        .get("values", {})
        .get(target)
    )
    pinned = (
        requests.post(
            f"{API}/dashboards/bulk_compute_cards/{DASH}",
            headers=H,
            json={
                "filters": [],
                "component_ids": [target],
                "component_overrides": {target: component_in(first, target)},
                "data_versions": {str((component or {}).get("dc_id")): 0},
            },
            timeout=60,
        )
        .json()
        .get("values", {})
        .get(target)
    )
    print(f"  ....  live={live}  oldest={pinned}")
    if live != pinned:
        ok("the two compare panes differ", f"{pinned} vs {live}")
    else:
        fail("the two compare panes differ", f"identical: {live}")

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("ALL PASS")
