#!/usr/bin/env python3
"""
Export Depictio dashboard components to a standalone HTML page.

Calls the render API for a figure, a card, and a table, then assembles
a single self-contained HTML file that can be opened in any browser —
no Depictio, no Python, no Jupyter required.

Usage:
    python export_to_html.py              # writes dashboard_export.html
    python export_to_html.py -o out.html  # custom output path
"""

from __future__ import annotations

import argparse
import html
import json
import sys

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_BASE = "http://localhost:8135/depictio/api/v1"
DASHBOARD_ID = "6824cb3b89d2b72169309737"
TOKEN = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJuYW1lIjoiZGVmYXVsdF90b2tlbiIsInRva2VuX2xpZmV0aW1lIjoibG9uZy1saXZlZCIsInRva2VuX3R5cGUiOiJiZWFyZXIiLCJzdWIiOiI2NzY1OGJhMDMzYzhiNTlhZDQ4OWQ3YzciLCJleHAiOjE4MDM3MjczMjR9."
    "kXyOArNVvh9UMjcNRchdd6bhbV6TivUskevm-1X7IZw2UtSjdysxq4V7e0w4NC2CRtPoX7fiSxoRh172-X8J0fEc1wlX8432zBq1o64HMExED9vUku1ubcamxDIq3QVaVo25pq4qiVWpwhMVhf3TI5O7h1ZJCXflpyWTh11-0rZ5TeObf-i1pJ6Z-Wa2p4pPf5MkHufm2U0iFL6Ce3QaXqX4dA-LxZov1FSR5rKru7axHL_0pTk9uTyoBLsMTN7uG6jxUOBQfb29yy9zob5f8gS9MAfgd64A7UvOGi0_hXs_sQirf_2YRrA30k_0Yz2ygpRD9JJJHNHVkqnFBRFzOA"
)
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Components to export (tag → human label)
COMPONENTS = {
    "figure-scatter_sepal_length_sepal_width-d4feb7": "Scatter Plot — Sepal Length vs Width",
    "card-sepal_length_average-cdb8b8": "Card — Average Sepal Length",
    "table-table-822ba8": "Table — Iris Dataset",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def render_component(tag: str, theme: str = "light") -> dict:
    url = f"{API_BASE}/render/{DASHBOARD_ID}/components/{tag}"
    resp = requests.post(url, json={"theme": theme, "timeout": 30}, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------
def build_figure_html(data: dict, div_id: str) -> str:
    """Plotly figure → a <div> with inline Plotly.newPlot call."""
    fig_json = json.dumps(data["data"]["figure"])
    return f"""
    <div id="{div_id}" style="width:100%;height:500px;"></div>
    <script>Plotly.newPlot("{div_id}", {fig_json}.data, {fig_json}.layout, {{responsive:true}});</script>
    """


def build_card_html(data: dict) -> str:
    """Card → a styled stat box."""
    d = data["data"]
    value = d["value"]
    agg = d["aggregation"]
    col = d["column"]
    display_val = f"{value:.4f}" if isinstance(value, float) else str(value)
    return f"""
    <div class="card">
      <div class="card-label">{html.escape(agg.upper())} of {html.escape(col)}</div>
      <div class="card-value">{html.escape(display_val)}</div>
    </div>
    """


def build_table_html(data: dict) -> str:
    """Table → an HTML <table>."""
    d = data["data"]
    cols = d["columns"]
    rows = d["rows"]
    header = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for row in rows[:50]:  # cap at 50 rows for the HTML preview
        cells = "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in cols)
        body_rows.append(f"<tr>{cells}</tr>")
    caption = f"Showing {len(body_rows)} of {d['total_rows']} rows"
    return f"""
    <p class="table-caption">{caption}</p>
    <div class="table-wrap">
      <table>
        <thead><tr>{header}</tr></thead>
        <tbody>{"".join(body_rows)}</tbody>
      </table>
    </div>
    """


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Depictio — Exported Dashboard Components</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           margin: 0; padding: 2rem; background: #f8f9fa; color: #212529; }}
    h1 {{ margin-bottom: .25rem; }}
    .subtitle {{ color: #6c757d; margin-bottom: 2rem; }}
    section {{ background: #fff; border-radius: 8px; padding: 1.5rem;
              margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    section h2 {{ margin-top: 0; }}
    .card {{ display: inline-block; background: linear-gradient(135deg, #667eea, #764ba2);
             color: #fff; border-radius: 12px; padding: 1.5rem 2.5rem; text-align: center; }}
    .card-label {{ font-size: .85rem; opacity: .85; margin-bottom: .5rem; }}
    .card-value {{ font-size: 2.2rem; font-weight: 700; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
    th, td {{ padding: .5rem .75rem; border: 1px solid #dee2e6; text-align: left; }}
    th {{ background: #f1f3f5; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #f8f9fa; }}
    .table-caption {{ color: #6c757d; font-size: .85rem; }}
    .tag {{ font-family: monospace; font-size: .8rem; color: #6c757d; }}
  </style>
</head>
<body>
  <h1>Depictio — Exported Dashboard Components</h1>
  <p class="subtitle">
    Dashboard <code>{dashboard_id}</code> &middot; rendered via <code>/render</code> API
  </p>
  {sections}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", default="dashboard_export.html", help="Output HTML file")
    args = parser.parse_args()

    sections: list[str] = []

    for tag, label in COMPONENTS.items():
        print(f"Rendering {tag} …")
        try:
            result = render_component(tag)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            sections.append(
                f'<section><h2>{html.escape(label)}</h2>'
                f'<p class="tag">{html.escape(tag)}</p>'
                f"<p>Error: {html.escape(str(exc))}</p></section>"
            )
            continue

        ctype = result["component_type"]
        inner = ""
        if ctype == "figure":
            div_id = tag.replace("-", "_").replace(".", "_")
            inner = build_figure_html(result, div_id)
        elif ctype == "card":
            inner = build_card_html(result)
        elif ctype == "table":
            inner = build_table_html(result)
        else:
            inner = f"<pre>{html.escape(json.dumps(result, indent=2))}</pre>"

        sections.append(
            f'<section><h2>{html.escape(label)}</h2>'
            f'<p class="tag">tag: <code>{html.escape(tag)}</code></p>'
            f"{inner}</section>"
        )
        print(f"  OK ({ctype})")

    page = HTML_TEMPLATE.format(
        dashboard_id=DASHBOARD_ID,
        sections="\n".join(sections),
    )
    with open(args.output, "w") as f:
        f.write(page)
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
