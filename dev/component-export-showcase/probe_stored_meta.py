#!/usr/bin/env python3
"""Print the stored_metadata of a dashboard's interactive components.

The export manifest publishes `component_id`, but `_resolve_multiqc_sample_filter`
matches an incoming filter against `stored_metadata[].index`. This shows whether
those are the same string, and what else is on the record that a binder could
match against.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

from bson import ObjectId  # noqa: E402

from depictio.api.v1.db import dashboards_collection  # noqa: E402

DASHBOARDS = {
    "viralrecon": "746b0f3c1e4a2d7f8e5b9ca2",
    "ampliseq": "646b0f3c1e4a2d7f8e5b8cb3",
}

for name, dashboard_id in DASHBOARDS.items():
    doc = dashboards_collection.find_one({"_id": ObjectId(dashboard_id)})
    if not doc:
        print(f"{name}: not found")
        continue
    print(f"\n== {name}")
    for component in doc.get("stored_metadata") or []:
        if component.get("component_type") != "interactive":
            continue
        keep = {
            key: component.get(key)
            for key in (
                "index",
                "component_type",
                "interactive_component_type",
                "column_name",
                "column_type",
                "dc_id",
                "wf_id",
                "title",
            )
        }
        print(json.dumps({k: str(v) for k, v in keep.items()}, indent=2))
