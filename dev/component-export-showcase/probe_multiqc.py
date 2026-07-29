"""Inspect the MultiQC panels available for the showcase pages.

The FastQC per-base quality histogram is the panel most people picture when
they say "MultiQC plot", so check what it actually exports before building a
page around it.
"""

import showcase_lib as s

token = s.admin_token()
VIRALRECON = "746b0f3c1e4a2d7f8e5b9ca2"

comps = s.manifest(VIRALRECON, token)
for comp in comps:
    if comp["component_type"] != "multiqc":
        continue
    title = comp.get("title") or "(untitled)"
    try:
        spec = s.export_json(VIRALRECON, comp["component_id"], token)
    except Exception as exc:  # noqa: BLE001
        print(f"{title[:44]:44s} FAILED {str(exc)[:60]}")
        continue
    data = spec.get("data") or []
    types = sorted({t.get("type") or "scatter" for t in data})
    points = sum(len(t.get("x") or t.get("y") or []) for t in data)
    layout = spec.get("layout") or {}
    xaxis = (layout.get("xaxis") or {}).get("title")
    yaxis = (layout.get("yaxis") or {}).get("title")

    def label(axis: object) -> str:
        if isinstance(axis, dict):
            return str(axis.get("text") or "")
        return str(axis or "")

    print(
        f"{title[:44]:44s} {comp['component_id'][:8]} "
        f"traces={len(data):3d} pts={points:5d} {','.join(types):16s} "
        f"x={label(xaxis)[:22]:22s} y={label(yaxis)[:20]}"
    )
