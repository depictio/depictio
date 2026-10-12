"""Why do the MultiQC 'general statistics' components export zero traces?

A spec with no traces is an empty white box on a host page. It matters whether
that is a bug in the exporter or a genuine "this panel is a table, not a plot",
because the first needs fixing and the second needs labelling.
"""

import json

import showcase_lib as s

token = s.admin_token()

for dash_id, comp_id in (
    ("746b0f3c1e4a2d7f8e5b9ca2", "05c68041"),
    ("646b0f3c1e4a2d7f8e5b8ca2", "8a810350"),
):
    comps = s.manifest(dash_id, token)
    match = next((c for c in comps if c["component_id"].startswith(comp_id)), None)
    if not match:
        print(f"{comp_id} not found")
        continue
    print(f"=== {dash_id[-6:]} / {match['component_id']} — {match.get('title')!r}")
    print("    declared formats:", match["formats"])
    spec = s.export_json(dash_id, match["component_id"], token)
    print("    data:", json.dumps(spec.get("data"))[:200])
    layout = spec.get("layout") or {}
    print("    layout keys:", sorted(layout)[:12])
    print("    title:", (layout.get("title") or {}))
    print("    meta:", json.dumps(spec.get("meta"))[:400])
