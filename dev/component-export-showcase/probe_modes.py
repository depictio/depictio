"""Are the ROC and PR panels actually different figures?

The screenshot shows 'ROC curve' with axes labelled Precision/Recall, which
either means ?controls={"mode":"roc"} is being ignored, or the panel titles are
simply wrong. The ETags tell us which: distinct ETags mean the server really
did build two different figures.
"""

import json
from urllib.parse import urlencode

import showcase_lib as s

token = s.admin_token()
DASH = "6a6a671b2b176f56bdcf5f30"

comps = s.manifest(DASH, token)
target = next(c for c in comps if c.get("viz_kind") == "roc_pr_curve")
comp_id = target["component_id"]
print("component:", comp_id, target.get("title"))

for mode in ("roc", "pr", None):
    params = {"format": "json", "theme": "light"}
    if mode:
        params["controls"] = json.dumps({"mode": mode})
    url = f"/export/dashboards/{DASH}/components/{comp_id}?{urlencode(params)}"
    spec = s.request(url, token=token)
    layout = spec.get("layout") or {}

    def axis(key: str) -> str:
        title = (layout.get(key) or {}).get("title")
        if isinstance(title, dict):
            return str(title.get("text") or "")
        return str(title or "")

    first = (spec.get("data") or [{}])[0]
    print(
        f"mode={str(mode):5s} x={axis('xaxis')[:22]:24s} y={axis('yaxis')[:22]:24s} "
        f"traces={len(spec.get('data', []))} name={first.get('name')}"
    )
    print(f"          etag={(spec.get('meta') or {}).get('etag')}")
