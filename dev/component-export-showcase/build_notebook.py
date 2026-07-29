#!/usr/bin/env python3
"""Generate the showcase notebook.

Written as a generator rather than a checked-in .ipynb so the source stays
reviewable in a diff: an .ipynb is JSON with embedded outputs and is unreadable
in review. Run this, then execute the notebook to fill in outputs.

    python build_notebook.py && \
      .venv/bin/jupyter nbconvert --to notebook --execute --inplace \
        component_export_tour.ipynb
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parent / "component_export_tour.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.strip().splitlines(keepends=True),
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.strip().splitlines(keepends=True),
    }


CELLS = [
    md(
        """
# Depictio component export — a tour

`GET /depictio/api/v1/export/dashboards/{dashboard_id}/components/{component_id}`
hands you one dashboard component in one of two forms:

| `format` | you get | size | good for |
|---|---|---|---|
| `json` | `{data, layout, config, meta}` — a Plotly figure spec | ~1–500 KB | **re-plotting in your own page**, restyling, further analysis |
| `html` | one self-contained file, no network calls | ~7 MB | types with no server-side figure; archiving a result |

**Reach for `json` first.** It hands you a finished figure you own: restyle it,
resize it, subset the traces, or pull the numbers out. `html` inlines the entire
React renderer to carry component types that are not Plotly at all (tables,
cards), which is why it costs ~7 MB to deliver a few hundred KB of data.

This notebook does five things:

1. asks the API which components exist and what each one supports
2. pulls a figure as JSON and draws it here
3. restyles that same figure, to show the spec is genuinely yours
4. pulls a component as HTML and frames it inline
5. shows what happens for the types that deliberately cannot do JSON

Before running: the instance needs `DEPICTIO_FASTAPI_EMBED_ENABLED=true` and the
embed bundle built (`cd depictio/viewer && pnpm run build:embed`).
        """
    ),
    md(
        "## 1. Connect\n\nPorts and token come from the worktree's `.env.instance`, so nothing is hardcoded."
    ),
    code(
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import showcase_lib as depictio  # noqa: E402

TOKEN = depictio.admin_token()
print("API      ", depictio.api_base())
print("token    ", TOKEN[:24] + "…")
        """
    ),
    md(
        """
## 2. Ask what is exportable

The manifest route is the thing to integrate against. It reports, per component,
which formats are available and *why* one is not — so a consumer never has to
hardcode the support matrix or probe for 501s.
        """
    ),
    code(
        """
import pandas as pd

DASHBOARDS = {
    "Community Analysis (ampliseq)": "646b0f3c1e4a2d7f8e5b8cb3",
    "Volcano":                       "646b0f3c1e4a2d7f8e5b8d00",
    "ComplexHeatmap":                "646b0f3c1e4a2d7f8e5b8d27",
    "Phylogeny":                     "646b0f3c1e4a2d7f8e5b8d18",
}

rows = []
for label, dashboard_id in DASHBOARDS.items():
    for entry in depictio.manifest(dashboard_id, TOKEN):
        rows.append({
            "dashboard": label,
            "type": entry["component_type"],
            "viz_kind": entry.get("viz_kind") or "",
            "title": (entry.get("title") or "")[:40],
            "json": "json" in entry["formats"],
            "html": "html" in entry["formats"],
            "component_id": entry["component_id"],
        })

manifest = pd.DataFrame(rows)
manifest.groupby(["type", "viz_kind"])[["json", "html"]].agg(["sum", "count"])
        """
    ),
    md(
        """
Note the asymmetry: `html` covers nearly everything, `json` only the components
whose figure is built in Python. That is a property of where the figure is
assembled, not an oversight — see `docs/design/component-export.md`.
        """
    ),
    md(
        "## 3. A figure as JSON\n\nThe response is a plain Plotly spec. `go.Figure(spec)` accepts it directly."
    ),
    code(
        """
import plotly.graph_objects as go
import plotly.io as pio

# `notebook_connected` loads plotly.js from a CDN rather than inlining ~4.8 MB of
# it into every saved figure. That keeps this committed .ipynb reviewable; switch
# to "notebook" if you need the file to work with no network.
pio.renderers.default = "notebook_connected"

figures = manifest[(manifest["type"] == "figure") & manifest["json"]]
row = figures.iloc[0]
spec = depictio.export_json(DASHBOARDS[row["dashboard"]], row["component_id"], TOKEN)

print("keys   ", list(spec))
print("traces ", len(spec["data"]))
print("meta   ", json.dumps(spec["meta"], indent=2)[:300])

fig = go.Figure(data=spec["data"], layout=spec["layout"])
fig.update_layout(height=420)
fig
        """
    ),
    md(
        """
## 4. It is your figure now

The point of `format=json` over `format=html` is ownership: the spec is data, so
you can restyle it, subset the traces, or feed the numbers into something else.
        """
    ),
    code(
        """
restyled = go.Figure(data=spec["data"], layout=spec["layout"])
restyled.update_layout(
    height=420,
    template="plotly_white",
    title="Same data, our styling",
    font=dict(family="Georgia, serif", size=12),
    showlegend=False,
)
restyled.update_traces(marker_line_width=0)
restyled
        """
    ),
    code(
        """
# The numbers, not just the picture.
records = []
for trace in spec["data"]:
    xs, ys = trace.get("x") or [], trace.get("y") or []
    for x, y in zip(xs, ys):
        records.append({"series": trace.get("name", "—"), "x": x, "y": y})

values = pd.DataFrame(records)
print(f"{len(values)} points across {values['series'].nunique()} series")
values.head()
        """
    ),
    md(
        """
## 5. A whole component as HTML

`format=html` returns one file with the data *and* the viewer's real renderer
inlined. It works with Depictio switched off, which is what makes it useful for
archiving a result next to a manuscript.

The advanced-viz kinds are the interesting case: their Plotly spec is assembled
in TypeScript, so `json` cannot serve them, but `html` runs that same TypeScript
offline and renders correctly.
        """
    ),
    code(
        """
import re

from IPython.display import IFrame, display

out_dir = Path("notebook_exports")
out_dir.mkdir(exist_ok=True)

target = manifest[manifest["viz_kind"] == "complex_heatmap"].iloc[0]
html = depictio.export_html(DASHBOARDS[target["dashboard"]], target["component_id"], TOKEN)

path = out_dir / "complex_heatmap.html"
path.write_bytes(html)
print(f"{path}  {len(html) / 1e6:.1f} MB, self-contained")

# Proof it is offline. Inline <script> bodies are stripped first: a bundled
# library can mention a CDN in a string it never fetches, and matching raw text
# would count that as a dependency. Only real tags load anything.
markup = re.sub(rb"<script(?![^>]*\\bsrc=)[^>]*>.*?</script>", b"", html, flags=re.S | re.I)
external = {
    "script src": re.findall(rb'<script[^>]*\\bsrc="([^"]+)"', markup),
    "link href": re.findall(rb'<link[^>]*href="([^"]+)"', markup),
    "img src": re.findall(rb'<img[^>]*src="(https?://[^"]+)"', markup),
}
print({label: hits or "none" for label, hits in external.items()})

# The CSP the API serves says the same thing, and enforces it.
_, headers = depictio.request(
    f"/export/dashboards/{DASHBOARDS[target['dashboard']]}/components/{target['component_id']}",
    token=TOKEN, params={"format": "html"}, raw=True,
)
print("\\nconnect-src:", [p.strip() for p in headers["content-security-policy"].split(";")
                          if "connect-src" in p])

display(IFrame(src=str(path), width="100%", height=520))
        """
    ),
    md(
        """
## 6. Where `json` says no, and why

A client-only viz kind answers **501** rather than pretending. The body names the
reason and hands over a working `html_url`, so a caller can fall back
automatically instead of failing.
        """
    ),
    code(
        """
client_only = manifest[(manifest["type"] == "advanced_viz") & ~manifest["json"]]
if client_only.empty:
    print("every advanced_viz kind on these dashboards has a Python builder")
else:
    row = client_only.iloc[0]
    try:
        depictio.export_json(DASHBOARDS[row["dashboard"]], row["component_id"], TOKEN)
    except depictio.ExportError as exc:
        print(f"HTTP {exc.status}")
        print(json.dumps(exc.detail, indent=2)[:700])
        """
    ),
    md(
        """
## 7. Embedding it elsewhere

For a real page you do not download anything — you point an `<iframe>` at the
export URL and let Depictio render on request:

```html
<iframe src="…/export/dashboards/DASH/components/CID?format=html&theme=light"
        width="100%" height="420" frameborder="0"></iframe>
```

Two settings gate this, both off by default:

| setting | why |
|---|---|
| `DEPICTIO_FASTAPI_EMBED_ENABLED` | master switch; while off, every export route 404s |
| `DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS` | origins allowed to frame the embed, as CSP `frame-ancestors`. Empty means embeds render standalone but cannot be iframed |

`dev/component-export-showcase/` has a working example: `serve_site.py` runs a
separate site on `:8899` that frames these components cross-origin.
        """
    ),
    code(
        """
for _, row in manifest[manifest["html"]].head(6).iterrows():
    print(depictio.embed_url(DASHBOARDS[row["dashboard"]], row["component_id"]))
        """
    ),
]


def main() -> None:
    # nbformat >= 5.1 requires a stable cell id; derive it from position so
    # regenerating produces an identical file rather than a churny diff.
    cells = []
    for position, cell in enumerate(CELLS):
        cells.append({**cell, "id": f"cell-{position:02d}"})

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, indent=1))
    print(f"wrote {NOTEBOOK} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
