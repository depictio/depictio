#!/usr/bin/env python3
"""Does a filter actually change a MultiQC export?

The viralrecon dashboard's two interactive controls sit on a *different* data
collection (…9c11) from the MultiQC panels (…9c10), so the "only apply a filter
where the column exists" rule the report page uses would drop them entirely. If
that rule is wrong here, the dashboard page would show controls that do nothing.

This asks the API directly: same component, with and without a filter, and
compares trace counts, point counts and the ETag.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API = "http://localhost:8102/depictio/api/v1"
DASHBOARD = "746b0f3c1e4a2d7f8e5b9ca2"

PANELS = {
    "FastQC histogram": "dc03abc8-5ff5-412b-bf78-50c18dc1d238",
    "fastp filtered reads": "fd469b5b-6b43-46fa-a97e-282ca203faf9",
    "general statistics": "05c68041-76a3-46c2-ac3d-bc90d283d9a3",
    "mosdepth coverage": "3f9fcc72-8cfa-46aa-a0a0-36f3ffd5f475",
}

FILTER = [
    {
        "interactive_component_type": "MultiSelect",
        "column_name": "sample",
        "value": ["SAMPLE_01", "SAMPLE_02", "SAMPLE_03"],
    }
]


def export(component: str, filters=None):
    params = {"format": "json", "theme": "light"}
    if filters:
        params["filters"] = json.dumps(filters)
    url = f"{API}/export/dashboards/{DASHBOARD}/components/{component}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            spec = json.loads(response.read())
            etag = response.headers.get("etag")
    except urllib.error.HTTPError as error:
        return {"error": f"HTTP {error.code} {error.read()[:200]!r}"}
    traces = spec.get("data") or []
    points = sum(len(trace.get("x") or trace.get("y") or []) for trace in traces)
    names = [trace.get("name") for trace in traces[:6]]
    return {
        "traces": len(traces),
        "points": points,
        "names": names,
        "etag": (etag or "")[:24],
        "filter_applied": (spec.get("meta") or {}).get("filter_applied"),
    }


def main() -> int:
    for label, component in PANELS.items():
        plain = export(component)
        filtered = export(component, FILTER)
        print(f"\n== {label}")
        print(f"   unfiltered {plain}")
        print(f"   filtered   {filtered}")
        if "error" not in plain and "error" not in filtered:
            changed = plain["traces"] != filtered["traces"] or plain["points"] != filtered["points"]
            print(f"   -> filter changes the figure: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
