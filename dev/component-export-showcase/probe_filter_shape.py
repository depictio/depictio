#!/usr/bin/env python3
"""Which filter payload shape does the MultiQC export actually honour?

`_resolve_multiqc_sample_filter` looks each filter up in the dashboard's
`stored_metadata` by its `index`, which is a *dashboard-internal* identifier. An
external host building a filter from the export manifest sends the column name
and the value, because that is what the manifest publishes as the contract. If
only the `index` form works, the published contract is not the one the server
honours.

Three shapes, same intended meaning, compared by point count.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API = "http://localhost:8102/depictio/api/v1"
DASHBOARD = "746b0f3c1e4a2d7f8e5b9ca2"
FASTP = "fd469b5b-6b43-46fa-a97e-282ca203faf9"
MQC_DC = "746b0f3c1e4a2d7f8e5b9c11"

SAMPLES = ["SAMPLE_01", "SAMPLE_02", "SAMPLE_03"]

SHAPES = {
    "no index (what the manifest implies)": [
        {"interactive_component_type": "MultiSelect", "column_name": "sample", "value": SAMPLES}
    ],
    "with dc_id": [
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "sample",
            "dc_id": MQC_DC,
            "value": SAMPLES,
        }
    ],
    "with index (dashboard-internal)": [
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "sample",
            "index": "mqc-sample-filter",
            "value": SAMPLES,
        }
    ],
    "lineage, with index": [
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "lineage",
            "index": "mqc-lineage-filter",
            "value": ["B.1.1.7"],
        }
    ],
}


def points(component: str, filters=None):
    params = {"format": "json", "theme": "light"}
    if filters:
        params["filters"] = json.dumps(filters)
    url = f"{API}/export/dashboards/{DASHBOARD}/components/{component}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            spec = json.loads(response.read())
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    traces = spec.get("data") or []
    total = sum(len(trace.get("x") or trace.get("y") or []) for trace in traces)
    return f"{len(traces)} traces / {total} points"


def main() -> int:
    print("baseline (no filter):", points(FASTP))
    for label, filters in SHAPES.items():
        print(f"{label:38s} {points(FASTP, filters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
