#!/usr/bin/env python3
"""Are the writes that bypass ``/save`` actually recoverable, on a real stack?

``/save`` is not the only route that changes a dashboard. A rename, a tab edit, a
reorder and a tab delete all mutate content, and each of them recorded nothing
until the capture calls were wired in — so the previous state was unrecoverable.

The unit tests for that live in ``test_dashboard_version_routes.py`` and drive
mongomock. This drives the real API, because the two paths that matter most are
the ones mongomock cannot vouch for:

* a **tab delete** anchors its capture on the *parent*, since the tab is gone by
  the time it runs. Get that wrong and you get a version that exists and is
  empty, rather than an error;
* the **baseline** is what holds the pre-write state. Without it the timeline
  gains an entry that records the change and nothing that records what it
  replaced — the feature looks present and does not work.

Creates a throwaway child tab on the demo dashboard, deletes it, checks the
timeline can still see it, then removes every version it added so the demo keeps
the four its README describes.

    uv run python check_bypass_capture.py
"""

import os
import sys

import requests

API = os.environ.get("DEPICTIO_API", "http://localhost:8100") + "/depictio/api/v1"
PARENT = os.environ.get("DASHBOARD_ID", "6a6a6d1e56f07a2b61f51c4e")
TAB_TITLE = "Probe tab (delete me)"


def main() -> int:
    tok = requests.post(
        f"{API}/auth/login",
        data={"username": "admin@example.com", "password": "changeme"},
        timeout=15,
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    def versions() -> list[dict]:
        return requests.get(f"{API}/dashboards/{PARENT}/versions", headers=h, timeout=30).json()[
            "versions"
        ]

    def snapshot_titles(version_id: str) -> set[str]:
        detail = requests.get(
            f"{API}/dashboards/versions/{version_id}", headers=h, timeout=30
        ).json()
        return {t.get("title") for t in (detail.get("tabs") or [])}

    baseline = len(versions())
    print(f"{baseline} versions before")

    # Create the tab exactly as `createTab` in api.ts does: there is no
    # dedicated create-tab route, the client mints an id and POSTs it to /save.
    parent = requests.get(f"{API}/dashboards/get/{PARENT}", headers=h, timeout=30).json()
    tab_id = f"{int(__import__('time').time()):08x}" + "0" * 16
    payload = {
        "dashboard_id": tab_id,
        "version": 1,
        "title": TAB_TITLE,
        "subtitle": "",
        "icon": "mdi:tab",
        "icon_color": "blue",
        "icon_variant": "filled",
        "workflow_system": "none",
        "notes_content": "",
        "permissions": parent.get("permissions") or {},
        "is_public": False,
        "last_saved_ts": "",
        "project_id": parent["project_id"],
        "is_main_tab": False,
        "parent_dashboard_id": PARENT,
        "tab_order": 99,
        "stored_metadata": [],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [],
    }
    created = requests.post(f"{API}/dashboards/save/{tab_id}", headers=h, json=payload, timeout=30)
    if created.status_code >= 400:
        print(f"could not create a probe tab: {created.status_code} {created.text[:300]}")
        return 2
    print(f"created child tab {tab_id}")

    after_create = versions()
    print(f"  after create: {len(after_create)} versions")

    deleted = requests.delete(f"{API}/dashboards/tab/{tab_id}", headers=h, timeout=30)
    print(f"DELETE /tab -> {deleted.status_code}")
    after_delete = versions()
    print(f"  after delete: {len(after_delete)} versions")

    failures = []
    if len(after_delete) <= len(after_create):
        failures.append("the delete recorded no version")
    else:
        newest = after_delete[0]
        if newest["kind"] != "explicit":
            failures.append(f"the delete's version is {newest['kind']!r}, not 'explicit'")
        # The point of the whole exercise: some entry must still hold the tab.
        holding = [v for v in after_delete if TAB_TITLE in snapshot_titles(v["version_id"])]
        if not holding:
            failures.append("no version holds the deleted tab — it is unrecoverable")
        else:
            print(f"  the deleted tab survives in {len(holding)} version(s): recoverable")
        if TAB_TITLE in snapshot_titles(newest["version_id"]):
            failures.append("the post-delete version still contains the deleted tab")

    # Clean up: drop every version this probe added, so the demo keeps the four
    # its README describes.
    for v in versions():
        if v.get("label"):
            continue
        requests.delete(f"{API}/dashboards/versions/{v['version_id']}", headers=h, timeout=30)
    print(f"cleaned up -> {len(versions())} versions")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: deleting a tab is recorded, explicit, and recoverable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
