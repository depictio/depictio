#!/usr/bin/env python3
"""Serve the external showcase site — a *separate origin* from the Depictio API.

Separate origin is the whole point: Depictio runs on :8102, this runs on :8899,
so every embed here is a genuine cross-origin frame. If the CSP `frame-ancestors`
list, the nginx location block or the middleware exemption were wrong, this page
would show empty boxes instead of components.

Routes:
    /                 the showcase page (static files from site/)
    /exports/...      the saved exports, so the "downloaded file" mode serves the
                      7 MB self-contained HTML from *this* server, not Depictio's
    /site-data.json   generated on each request from exports/index.json, so the
                      gallery always reflects what was actually exported

    python serve_site.py [--port 8899]
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import showcase_lib as s  # noqa: E402

SITE_DIR = Path(__file__).resolve().parent / "site"
EXPORT_DIR = s.EXPORT_DIR

#: Curated order for the gallery. Anything not listed sorts after, alphabetically.
FEATURED = [
    "figure",
    "advanced_viz--volcano",
    "advanced_viz--complex_heatmap",
    "advanced_viz--upset_plot",
    "advanced_viz--qq",
    "advanced_viz--ma",
    "advanced_viz--sankey",
    "multiqc",
    "table",
    "card",
    "interactive",
    "text",
]


def site_data() -> dict:
    """Gallery model: one entry per exported component, plus instance wiring."""
    index_path = EXPORT_DIR / "index.json"
    records = json.loads(index_path.read_text()) if index_path.exists() else []

    def rank(record: dict) -> tuple[int, str]:
        key = record["type"]
        return (FEATURED.index(key), "") if key in FEATURED else (len(FEATURED), key)

    entries = []
    for record in sorted(records, key=rank):
        html = record.get("html", {})
        json_part = record.get("json", {})
        entries.append(
            {
                "type": record["type"],
                "componentType": record["component_type"],
                "vizKind": record.get("viz_kind"),
                "title": record.get("title") or record["type"],
                "dashboardId": record["dashboard_id"],
                "dashboardTitle": record["dashboard_title"],
                "componentId": record["component_id"],
                "formats": record["declared_formats"],
                "liveUrl": record["embed_url"],
                "jsonUrl": record["embed_url"].replace("format=html", "format=json"),
                "savedHtml": f"/exports/{html['path']}" if html.get("path") else None,
                "savedJson": f"/exports/{json_part['path']}" if json_part.get("path") else None,
                "htmlStatus": html.get("status", "unknown"),
                "htmlBytes": html.get("bytes"),
                "jsonStatus": json_part.get("status", "unknown"),
                "jsonBytes": json_part.get("bytes"),
                "jsonTraces": json_part.get("traces"),
                "jsonReason": json_part.get("detail") or "",
            }
        )

    return {
        "apiBase": s.api_base(),
        "components": entries,
        "counts": {
            "total": len(entries),
            "html": sum(1 for e in entries if e["htmlStatus"] == "ok"),
            "json": sum(1 for e in entries if e["jsonStatus"] == "ok"),
        },
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] == "/site-data.json":
            body = json.dumps(site_data()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def translate_path(self, path: str) -> str:
        clean = path.split("?")[0].split("#")[0].lstrip("/")
        if clean.startswith("exports/"):
            return str(EXPORT_DIR / clean[len("exports/"):])
        return str(SITE_DIR / (clean or "index.html"))

    def log_message(self, fmt, *args):
        if "site-data" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    data = site_data()
    print(f"Depictio API   {data['apiBase']}")
    print(f"Components     {data['counts']['total']} "
          f"(html ok {data['counts']['html']}, json ok {data['counts']['json']})")
    if not data["components"]:
        print("\n  No exports found. Run:  python export_all.py --clean\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), partial(Handler)) as httpd:
        print(f"\nExternal site  http://localhost:{args.port}   (Ctrl-C to stop)")
        print("This origin must appear in DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
