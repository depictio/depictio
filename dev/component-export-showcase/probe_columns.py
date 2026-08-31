#!/usr/bin/env python3
"""What columns do the benchmark and ampliseq data collections actually carry?

Filters can only be built for columns that exist. The benchmark dashboards have
no interactive components at all, so a section-level filter deck has to be
grounded in the real column set rather than guessed.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

from bson import ObjectId  # noqa: E402

from depictio.api.v1.db import (  # noqa: E402
    data_collections_collection,
    deltatables_collection,
)

DCS = {
    "bench-metrics": "646b0f3c1e4a2d7f8e5b8d60",
    "bench-curves": "646b0f3c1e4a2d7f8e5b8d61",
    "ampliseq-samples": "646b0f3c1e4a2d7f8e5b8ca5",
    "ampliseq-taxonomy": "646b0f3c1e4a2d7f8e5b8ca9",
}

for name, dc_id in DCS.items():
    print(f"\n== {name} ({dc_id})")
    dc = data_collections_collection.find_one({"_id": ObjectId(dc_id)})
    print("   dc_tag:", (dc or {}).get("data_collection_tag"))
    doc = deltatables_collection.find_one({"data_collection_id": ObjectId(dc_id)})
    if not doc:
        print("   no deltatable")
        continue
    aggregation = (doc.get("aggregation") or [])[-1:]
    for agg in aggregation:
        specs = agg.get("aggregation_columns_specs") or []
        for spec in specs:
            name_ = spec.get("name")
            dtype = spec.get("type")
            info = spec.get("specs") or {}
            summary = {
                key: info.get(key) for key in ("min", "max", "nunique") if info.get(key) is not None
            }
            unique = info.get("unique")
            if isinstance(unique, list):
                summary["unique"] = unique[:8]
            print(f"   {name_:24s} {str(dtype):10s} {json.dumps(summary, default=str)[:150]}")
