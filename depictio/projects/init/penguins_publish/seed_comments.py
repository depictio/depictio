#!/usr/bin/env python3
"""Seed comment threads, one annotation and a logo on the penguins_publish dashboard.

Run it after `dashboard import`, against the instance that will PUBLISH the project.
The point is to give the push something to carry besides the dashboard itself, so that
the receiving instance can be checked for:

  * a thread anchored on a component, with a reply
  * a thread whose annotation (a reference line on a scatter plot) is published
  * a resolved thread
  * a thread pinned to the tab itself rather than a component
  * the dashboard logo

Everything is created through the public API as the user the token belongs to, so
the authors on the receiving instance keep the source user ids (a known gap of the
feature). Threads carry a `dedupe_key`, so running the script twice updates them
instead of piling up duplicates; the logo is simply overwritten.

    DEPICTIO_TOKEN=<access token> python seed_comments.py \
        --api-url https://dev.api.depictio.embl.org --dashboard-title "Penguins Publish Test"

The token is read from the environment (or --token-file), never from the command line
and never written anywhere.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import struct
import sys
import zlib
from pathlib import Path

import httpx

API_PREFIX = "/depictio/api/v1"

# Titles of components in dashboards/species_analysis.yaml.
SCATTER_TITLE = "Body Mass vs Flipper Length"
BOX_TITLE = "Body Mass Distribution by Species"
CARD_TITLE = "Individuals"


def _logo_png() -> bytes:
    """A 64x64 flat teal PNG, built here so the script needs no asset file."""
    w = h = 64
    row = b"\x00" + bytes((0x15, 0x90, 0x90)) * w
    raw = row * h

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class Client:
    def __init__(self, api_url: str, token: str, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=api_url.rstrip("/") + API_PREFIX,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def get(self, path: str, **kw):
        r = self._http.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, **kw):
        r = self._http.post(path, **kw)
        if r.status_code >= 400:
            sys.exit(f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def patch(self, path: str, **kw):
        r = self._http.patch(path, **kw)
        if r.status_code >= 400:
            sys.exit(f"PATCH {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def find_dashboard(client: Client, title: str) -> dict:
    matches = [d for d in client.get("/dashboards/list") if d.get("title") == title]
    if not matches:
        sys.exit(f"No dashboard titled {title!r} for this user. Import the YAML first.")
    if len(matches) > 1:
        ids = ", ".join(str(d.get("dashboard_id")) for d in matches)
        sys.exit(f"{len(matches)} dashboards titled {title!r} ({ids}); use --dashboard-id.")
    return matches[0]


def component_index(dashboard: dict, title: str) -> str:
    for comp in dashboard.get("stored_metadata") or []:
        if isinstance(comp, dict) and comp.get("title") == title and comp.get("index"):
            return str(comp["index"])
    sys.exit(f"No component titled {title!r} on dashboard {dashboard.get('dashboard_id')}.")


def thread(client: Client, dashboard_id: str, **body) -> dict:
    anchor = {"dashboard_id": dashboard_id, **body.pop("anchor", {})}
    return client.post("/comments/threads", json={"anchor": anchor, **body})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api-url", required=True, help="Backend base URL (no /depictio/api/v1).")
    p.add_argument("--dashboard-title", default="Penguins Publish Test")
    p.add_argument("--dashboard-id", help="Skip the title lookup.")
    p.add_argument("--token-file", help="File holding the token; default: $DEPICTIO_TOKEN.")
    p.add_argument("--logo", help="PNG/JPEG/WebP to upload; default: a generated teal square.")
    p.add_argument("--no-logo", action="store_true")
    args = p.parse_args()

    token = (
        Path(args.token_file).read_text().strip()
        if args.token_file
        else os.environ.get("DEPICTIO_TOKEN", "")
    )
    if not token:
        sys.exit("No token: set DEPICTIO_TOKEN or pass --token-file.")

    client = Client(args.api_url, token)
    dashboard = (
        client.get(f"/dashboards/get/{args.dashboard_id}")
        if args.dashboard_id
        else find_dashboard(client, args.dashboard_title)
    )
    dashboard_id = str(dashboard["dashboard_id"])
    # `/list` rows may not carry the components; fetch the full document when needed.
    if not dashboard.get("stored_metadata"):
        dashboard = client.get(f"/dashboards/get/{dashboard_id}")
    print(f"dashboard {dashboard_id} ({dashboard.get('title')})")

    scatter = component_index(dashboard, SCATTER_TITLE)
    box = component_index(dashboard, BOX_TITLE)
    card = component_index(dashboard, CARD_TITLE)

    # 1. A thread on a component, then a reply.
    t1 = thread(
        client,
        dashboard_id,
        anchor={"component_index": scatter},
        body="Publish test: this comment is anchored on the scatter plot.",
        dedupe_key="publish-test-component",
    )
    client.post(
        f"/comments/threads/{t1['id']}/comments",
        json={"body": "Reply, to check that a thread keeps its comments in order."},
    )

    # 2. A thread with an annotation. A reference line at an arbitrary position: it
    #    exists to be carried over, not to claim anything about the data.
    t2 = thread(
        client,
        dashboard_id,
        anchor={"component_index": scatter},
        body="Publish test: annotation drawn on the scatter plot.",
        annotation={
            "kind": "line",
            "geometry": {"kind": "ref_line", "axis": "y", "value": 4000},
            "label": "Test annotation (arbitrary position)",
            "color": "teal",
            "published": True,
        },
        dedupe_key="publish-test-annotation",
    )

    # 3. A thread that ends up resolved.
    t3 = thread(
        client,
        dashboard_id,
        anchor={"component_index": box},
        body="Publish test: this thread is resolved.",
        dedupe_key="publish-test-resolved",
    )
    client.patch(f"/comments/threads/{t3['id']}", json={"status": "resolved"})

    # 4. A thread on the tab itself (no component).
    t4 = thread(
        client,
        dashboard_id,
        anchor={"component_index": None},
        body="Publish test: pinned to the tab, not to a component.",
        dedupe_key="publish-test-tab",
    )

    # A fifth anchor, on a card, so the threads span three component kinds.
    t5 = thread(
        client,
        dashboard_id,
        anchor={"component_index": card},
        body="Publish test: anchored on a card.",
        dedupe_key="publish-test-card",
    )

    print("threads:", ", ".join(t["id"] for t in (t1, t2, t3, t4, t5)))

    if not args.no_logo:
        if args.logo:
            content = Path(args.logo).read_bytes()
            ctype = mimetypes.guess_type(args.logo)[0] or "image/png"
            name = Path(args.logo).name
        else:
            content, ctype, name = _logo_png(), "image/png", "logo.png"
        out = client.post(
            f"/dashboards/upload_logo/{dashboard_id}", files={"file": (name, content, ctype)}
        )
        print("logo:", out.get("logo_url"))


if __name__ == "__main__":
    main()
