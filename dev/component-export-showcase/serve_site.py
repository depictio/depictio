#!/usr/bin/env python3
"""Serve the external showcase site — a *separate origin* from the Depictio API.

Separate origin is the whole point: Depictio runs on :8102, this runs on :8899,
so nothing here shares code, cookies or a build step with it.

Four pages, each a different integration shape:

    /            gallery — one card per component type, mixed layout widths
    /report      editorial article with figures inside the narrative
    /qc          per-file QC report: info table, plot grid, donut stat cards
    /versioning  how to freeze, pin and refresh an embedded figure

Routes:
    /exports/...      the saved exports, so the "saved file" mode serves the
                      self-contained HTML from *this* server, not Depictio's
    /site-data.json   generated per request from exports/index.json, so the
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

#: Curated order within each tier. Anything unlisted sorts after, alphabetically.
FEATURED = [
    "figure",
    "advanced_viz--volcano",
    "advanced_viz--complex_heatmap",
    "advanced_viz--manhattan",
    "advanced_viz--upset_plot",
    "advanced_viz--embedding",
    "advanced_viz--stacked_taxonomy",
    "advanced_viz--qq",
    "advanced_viz--ma",
    "advanced_viz--enrichment",
    "advanced_viz--sunburst",
    "advanced_viz--da_barplot",
    "advanced_viz--sankey",
    "multiqc",
    "table",
    "card",
    "interactive",
    "text",
]

#: Grid span per component type. A uniform grid flatters nothing: a manhattan
#: plot needs the full width to be readable at all, a heatmap and an upset both
#: want two columns, and a card or a text block looks absurd stretched out.
#: Keyed by type so the choice travels with the component rather than its
#: position, which would shuffle whenever the export set changes.
SPAN = {
    "advanced_viz--manhattan": "full",
    "advanced_viz--coverage_track": "full",
    "advanced_viz--stacked_taxonomy": "full",
    "advanced_viz--complex_heatmap": "wide",
    "advanced_viz--upset_plot": "wide",
    "advanced_viz--oncoplot": "wide",
    "advanced_viz--enrichment": "wide",
    "multiqc": "wide",
    "table": "wide",
    "card": "narrow",
    "text": "narrow",
    "interactive": "narrow",
}
DEFAULT_SPAN = "normal"

#: Sub-pages, in nav order. The landing page is deliberately absent: it is the
#: index these link *back* to, not a peer in the nav.
PAGES = [
    ("/qc-report", "QC report", "example_clean.html"),
    ("/example-limited", "Where it stops", "example_limited.html"),
    ("/gallery", "Gallery", "index.html"),
    ("/report", "Surveillance", "report.html"),
    ("/versioning", "Versioning", "versioning.html"),
]

#: Routes kept working after a rename. A demo that 404s its own old links is a
#: poor advertisement for stable URLs, which is half of what it is arguing for.
ALIASES = {
    "/example-clean": "/qc-report",
    # The original hand-built QC page has been superseded: /qc-report does the
    # same job from the same GHGA palette, and additionally carries the MultiQC
    # section and the live filter decks.
    "/qc": "/qc-report",
}

#: Not in the nav: a diagnostic, not a demo. Every filter the showcase sends is
#: fetched twice here and compared, because a filter that is accepted and then
#: ignored returns a perfectly healthy-looking 200.
UNLISTED = [
    ("/selftest", "selftest.html"),
]

#: The landing page, served at the root.
LANDING = ("/", "landing.html")

#: Dashboards the hand-written pages reference, keyed by the short name they use.
#:
#: Resolved by *title* at request time rather than baked into the JavaScript as an
#: ObjectId. An id is minted at import, so re-seeding a dashboard changes it and
#: every page pinning the old one 404s — silently, since the request is perfectly
#: well-formed. Titles come from the YAML and survive re-import.
#:
#: (Component ids are safe to hardcode: since `models: make a component's YAML tag
#: its stable id` they are the tags in the YAML, not fresh UUIDs.)
DASHBOARD_TITLES = {
    "viralrecon": "nf-core/viralrecon",
    "ampliseq": "nf-core/ampliseq",
    "community": "Community & Diversity",
    "bench_ci": "Metric ± CI forest (demo)",
    "bench_confusion": "Confusion matrix (demo)",
    "bench_pr": "Precision-recall benchmark (demo)",
    "bench_roc": "ROC / PR curve (demo)",
}


def dashboard_ids() -> dict[str, str]:
    """``{short name: dashboard_id}``, omitting any dashboard not on this instance.

    Omission rather than a placeholder is deliberate: a page can then say "this
    dashboard is not seeded here" instead of issuing a request guaranteed to 404.
    """
    try:
        by_title = s.dashboards_by_title(s.admin_token())
    except Exception as exc:  # instance down, or no admin token on this machine
        print(f"  ! could not resolve dashboard ids: {exc}")
        return {}
    return {
        name: by_title[title] for name, title in DASHBOARD_TITLES.items() if title in by_title
    }


def site_data() -> dict:
    """Gallery model: one entry per exported component, plus instance wiring."""
    index_path = EXPORT_DIR / "index.json"
    records = json.loads(index_path.read_text()) if index_path.exists() else []

    def rank(record: dict) -> tuple[int, int, str]:
        """JSON-capable components first, then the curated order.

        The gallery leads with what the API can hand over as a Plotly spec,
        because that is the recommended integration; the iframe-only types
        follow so the gap is visible rather than mixed in.
        """
        key = record["type"]
        tier = 0 if record.get("json", {}).get("status") == "ok" else 1
        position = FEATURED.index(key) if key in FEATURED else len(FEATURED)
        return (tier, position, key)

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
                "span": SPAN.get(record["type"], DEFAULT_SPAN),
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
        "pages": [{"href": href, "label": label} for href, label, _ in PAGES],
        "dashboards": dashboard_ids(),
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
        clean = path.split("?")[0].split("#")[0]
        if clean.startswith("/exports/"):
            return str(EXPORT_DIR / clean[len("/exports/") :])
        # Extensionless page routes, so the URLs read as a real site rather than
        # a directory of .html files.
        if clean in ("/", ""):
            return str(SITE_DIR / LANDING[1])
        # Old links keep working after a rename rather than 404ing.
        clean = ALIASES.get(clean.rstrip("/") or "/", clean)
        for route, filename in [(r, f) for r, _, f in PAGES] + UNLISTED:
            if clean == route or clean == route.rstrip("/") + "/":
                return str(SITE_DIR / filename)
        return str(SITE_DIR / clean.lstrip("/"))

    def log_message(self, fmt, *args):
        if "site-data" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    data = site_data()
    print(f"Depictio API   {data['apiBase']}")
    print(
        f"Components     {data['counts']['total']} "
        f"(spec {data['counts']['json']}, frame {data['counts']['html']})"
    )
    if not data["components"]:
        print("\n  No exports found. Run:  python export_all.py --clean\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), partial(Handler)) as httpd:
        print(f"\nExternal site  http://localhost:{args.port}   (Ctrl-C to stop)")
        print(f"    {'Index':12} http://localhost:{args.port}/")
        for href, label, _ in PAGES:
            print(f"    {label:12} http://localhost:{args.port}{href}")
        print("\nThis origin must appear in DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
