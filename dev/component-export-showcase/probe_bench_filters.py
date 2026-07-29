#!/usr/bin/env python3
"""Do the new benchmark controls actually change the exported figures?

Adding interactive components to a dashboard makes them *discoverable* through
the export manifest. Whether the resulting filter reaches the figure is a
separate question, and the whole point of the deck on the QC page is that it
does. This drives each control the way the page does — column name and value,
no dashboard-internal ids — and reports what moved.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API = "http://localhost:8102/depictio/api/v1"

PR = ("6a6a671b2b176f56bdcf5f2e", "pr-demo-viz")
ROC = ("6a6a671b2b176f56bdcf5f30", "roc-demo-viz")
CM = ("6a6a671b2b176f56bdcf5f2c", "cm-demo-viz")
CI = ("6a6a671b2b176f56bdcf5f2a", "ci-demo-precision")

CASES = [
    ("pr · no filter", PR, None, None),
    (
        "pr · caller in {deepvariant, strelka2}",
        PR,
        [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "tool",
                "value": ["deepvariant", "strelka2"],
            }
        ],
        None,
    ),
    (
        "pr · fp <= 300",
        PR,
        [{"interactive_component_type": "RangeSlider", "column_name": "fp", "value": [95, 300]}],
        None,
    ),
    (
        "pr · tp >= 18000",
        PR,
        [
            {
                "interactive_component_type": "RangeSlider",
                "column_name": "tp",
                "value": [18000, 18800],
            }
        ],
        None,
    ),
    ("cm · no filter", CM, None, None),
    (
        "cm · fp <= 300",
        CM,
        [{"interactive_component_type": "RangeSlider", "column_name": "fp", "value": [95, 300]}],
        None,
    ),
    ("ci · no filter", CI, None, None),
    (
        "ci · caller in {deepvariant, strelka2}",
        CI,
        [
            {
                "interactive_component_type": "MultiSelect",
                "column_name": "tool",
                "value": ["deepvariant", "strelka2"],
            }
        ],
        None,
    ),
    ("roc · no filter", ROC, None, {"mode": "roc"}),
    (
        "roc · quality >= 50",
        ROC,
        [
            {
                "interactive_component_type": "RangeSlider",
                "column_name": "quality",
                "value": [50, 100],
            }
        ],
        {"mode": "roc"},
    ),
]


def export(target, filters, controls):
    dashboard, component = target
    params = {"format": "json", "theme": "light"}
    if filters:
        params["filters"] = json.dumps(filters)
    if controls:
        params["controls"] = json.dumps(controls)
    url = f"{API}/export/dashboards/{dashboard}/components/{component}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            spec = json.loads(response.read())
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}: {error.read()[:120]!r}"
    traces = spec.get("data") or []
    points = sum(len(trace.get("x") or trace.get("y") or trace.get("z") or []) for trace in traces)
    unmatched = (spec.get("meta") or {}).get("unmatched_filter_columns")
    return {
        "traces": len(traces),
        "points": points,
        "unmatched": unmatched,
    }


def main() -> int:
    baselines: dict[str, dict] = {}
    for label, target, filters, controls in CASES:
        result = export(target, filters, controls)
        key = label.split(" · ")[0]
        if filters is None:
            baselines[key] = result
            print(f"{label:44s} {result}")
            continue
        base = baselines.get(key)
        moved = isinstance(result, dict) and isinstance(base, dict) and result != base
        flag = "CHANGED" if moved else "unchanged  <-- filter had no effect"
        print(f"{label:44s} {result}  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
