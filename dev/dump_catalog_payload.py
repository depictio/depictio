#!/usr/bin/env python
"""Dump the catalog gallery payload for the HMR dev server.

`pnpm dev:catalog-preview` serves the gallery with hot-reload, but the CLI's
``__CATALOG_PAYLOAD__`` placeholder is only filled when serving the *built*
bundle (`depictio catalog gallery`). This writes the exact payload
``build_gallery_payload()`` produces to a JSON the dev server can fetch, so the
HMR gallery shows real catalog data while you edit the React components live.

Usage:
    python dev/dump_catalog_payload.py [--theme light|dark]
    cd depictio/viewer && pnpm dev:catalog-preview
    # open http://localhost:5173/catalog-preview.html

Re-run this whenever the *data* changes (a recipe, module.yaml, fixture);
component (.tsx) edits hot-reload on their own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Put the repo root on sys.path so `depictio` resolves to the source tree even
# when run as a script (where sys.path[0] is dev/, not the repo root) — this also
# shadows the slim depictio-cli's strict editable finder, which hides
# depictio.catalog. Must precede the depictio imports.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from depictio.catalog.payload import _json_safe, build_gallery_payload  # noqa: E402
from depictio.models.components.advanced_viz.catalog import load_catalog_entries  # noqa: E402

OUT = REPO_ROOT / "depictio" / "viewer" / "public" / "catalog-payload.dev.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    args = ap.parse_args()

    payload = build_gallery_payload(load_catalog_entries(), args.theme)
    # Same serialization the CLI uses to embed the payload (handles datetimes etc).
    OUT.write_text(json.dumps(_json_safe(payload), default=str))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print("next: cd depictio/viewer && pnpm dev:catalog-preview")
    print("then open http://localhost:5173/catalog-preview.html")


if __name__ == "__main__":
    main()
