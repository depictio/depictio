"""Does a filter change figure *content*, not just trace count?

Trace count is a poor signal: a sunburst is always one trace, and a stacked
taxonomy keeps one trace per taxon. Compare the total number of plotted points
instead, which moves whenever rows are actually dropped.
"""

import json
from urllib.parse import urlencode

import showcase_lib as s

token = s.admin_token()
DASH = "646b0f3c1e4a2d7f8e5b8cb3"


def point_count(spec: dict) -> int:
    total = 0
    for trace in spec.get("data", []):
        for key in ("x", "labels", "values", "y"):
            seq = trace.get(key)
            if isinstance(seq, list):
                total += len(seq)
                break
    return total


CASES = [
    ("adv-stacked-taxonomy", "MultiSelect", "Kingdom", ["Bacteria"]),
    ("adv-sunburst", "MultiSelect", "Kingdom", ["Bacteria"]),
    ("d595144f-eaab-45f9-9138-b6f342fe2582", "MultiSelect", "habitat", ["Soil"]),
    ("adv-upset-plot", "MultiSelect", "Kingdom", ["Bacteria"]),
]

for comp, ctype, column, value in CASES:
    filters = [{"interactive_component_type": ctype, "column_name": column, "value": value}]
    query = urlencode({"format": "json", "filters": json.dumps(filters)})
    try:
        base = s.export_json(DASH, comp, token)
        filt = s.request(f"/export/dashboards/{DASH}/components/{comp}?{query}", token=token)
    except Exception as exc:  # noqa: BLE001 - probe script
        print(f"{comp}: {exc}")
        continue
    b, f = point_count(base), point_count(filt)
    mark = "changed" if b != f else "SAME"
    print(f"{comp:40s} {column:9s} points {b:5d} -> {f:5d}  {mark}")
