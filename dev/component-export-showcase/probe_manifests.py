#!/usr/bin/env python3
"""Dump the component manifest for every dashboard the showcase pages use.

The pages address components by id, and ids are long and easy to mistype. This
prints what actually exists, with each component's viz kind, data collection and
filter contract, so a page's panel list can be checked against reality rather
than against memory.
"""

from __future__ import annotations

import json
import sys
import urllib.request

API = "http://localhost:8102/depictio/api/v1"

DASHBOARDS = {
    "viralrecon": "746b0f3c1e4a2d7f8e5b9ca2",
    "ampliseq": "646b0f3c1e4a2d7f8e5b8cb3",
    "bench-ci": "6a6a671b2b176f56bdcf5f2a",
    "bench-confusion": "6a6a671b2b176f56bdcf5f2c",
    "bench-pr": "6a6a671b2b176f56bdcf5f2e",
    "bench-roc": "6a6a671b2b176f56bdcf5f30",
}


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def main() -> int:
    wanted = sys.argv[1:] or list(DASHBOARDS)
    for name in wanted:
        dashboard = DASHBOARDS.get(name, name)
        url = f"{API}/export/dashboards/{dashboard}/components?include_filter_options=true"
        try:
            manifest = fetch(url)
        except Exception as error:  # noqa: BLE001 - probe script, report and continue
            print(f"\n== {name} ({dashboard}) -> {error}")
            continue
        print(f"\n== {name} ({dashboard}) — {len(manifest)} components")
        for component in manifest:
            kind = component.get("viz_kind") or component.get("component_type")
            formats = ",".join(component.get("formats", []))
            print(
                f"  {component['component_id']}  {component.get('component_type'):<12}"
                f" {str(kind):<20} [{formats}]  {component.get('title')!r}"
            )
            print(f"      dc={component.get('dc_id')}  dc_name={component.get('dc_name')}")
            filter_contract = component.get("filter")
            if filter_contract:
                options = filter_contract.get("options") or {}
                values = options.get("values")
                summary = (
                    f"{len(values)} values: {values[:6]}"
                    if isinstance(values, list)
                    else f"min={options.get('min')} max={options.get('max')}"
                )
                print(
                    f"      filter: {filter_contract.get('interactive_component_type')}"
                    f" on {filter_contract.get('column_name')}"
                    f" ({filter_contract.get('column_type')}) kind={options.get('kind')} {summary}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
