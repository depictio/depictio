"""Inspect the confusion-matrix spec used by the QC page."""

import showcase_lib as s

token = s.admin_token()
DASH = "6a6a671b2b176f56bdcf5f2c"

comps = s.manifest(DASH, token)
target = next((c for c in comps if c.get("viz_kind") == "confusion_matrix"), None)
if target is None:
    raise SystemExit(f"no confusion_matrix on {DASH}: {[c.get('viz_kind') for c in comps]}")

spec = s.export_json(DASH, target["component_id"], token)
trace = spec["data"][0]
print("colorscale:", trace.get("colorscale"))
print("reversescale:", trace.get("reversescale"))
print("zmin/zmax:", trace.get("zmin"), trace.get("zmax"))
print("z:", trace.get("z"))
anns = spec["layout"].get("annotations") or []
print(f"{len(anns)} annotations")
for a in anns:
    print("   ", repr(a.get("text")), "->", (a.get("font") or {}).get("color"))
