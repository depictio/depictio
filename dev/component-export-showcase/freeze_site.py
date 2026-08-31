#!/usr/bin/env python3
"""Freeze the showcase into a directory of static files.

Answers "can I just send someone a link?" — the pages are plain HTML, CSS and JS
with no build step, and their only server dependency is `/site-data.json`, which
`serve_site.py` generates per request. Write that file out once and the site is
static: any object store or GitHub Pages will serve it.

What *cannot* be frozen is the Depictio API the pages fetch from. Three postures,
in ascending order of what the recipient gets:

  --api https://api.example.org/depictio/api/v1
      Point the frozen site at a reachable Depictio. Every page is fully live:
      filters refetch, ETags revalidate, embedded controls work. Requires that
      instance to have embed_enabled and to name the site's origin in
      embed_allowed_origins.

  --snapshot
      Additionally copy exports/ next to the pages, so the "saved file" mode and
      the JSON specs resolve locally. Figures render with no Depictio at all;
      anything interactive still needs the API.

  (neither)
      The pages ship as-is and read /site-data.json's recorded apiBase, which is
      almost certainly a localhost URL and will not resolve for anyone else. Fine
      for a colleague on the same machine, useless as a link.

    python freeze_site.py --out /tmp/showcase --api https://api.demo.example.org/depictio/api/v1
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import serve_site  # noqa: E402
import showcase_lib as s  # noqa: E402

SITE_DIR = Path(__file__).resolve().parent / "site"


def freeze(out: Path, api_base: str | None, snapshot: bool) -> dict:
    """Write the static site to ``out``; returns the site-data that was baked in."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_DIR, out)

    data = serve_site.site_data()
    if api_base:
        data["apiBase"] = api_base.rstrip("/")
        # Component URLs are absolute and recorded at export time, so they must be
        # rebased too or the frozen page still points at the exporting machine.
        old = s.api_base().rstrip("/")
        for entry in data["components"]:
            for key in ("liveUrl", "jsonUrl"):
                if entry.get(key):
                    entry[key] = entry[key].replace(old, data["apiBase"])

    (out / "site-data.json").write_text(json.dumps(data, indent=1))

    # Extensionless routes (/gallery, /report, …) are a server behaviour. A static
    # host needs real files, so write each page at `<route>/index.html`.
    for href, _label, filename in serve_site.PAGES:
        route = out / href.strip("/")
        route.mkdir(parents=True, exist_ok=True)
        shutil.copy(out / filename, route / "index.html")
    for href, filename in serve_site.UNLISTED:
        route = out / href.strip("/")
        route.mkdir(parents=True, exist_ok=True)
        shutil.copy(out / filename, route / "index.html")
    shutil.copy(out / serve_site.LANDING[1], out / "index.html")

    if snapshot and s.EXPORT_DIR.exists():
        shutil.copytree(s.EXPORT_DIR, out / "exports")

    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("/tmp/depictio-showcase"))
    parser.add_argument(
        "--api",
        default=None,
        help="Public API base the frozen pages should fetch from, e.g. "
        "https://api.demo.depictio.embl.org/depictio/api/v1",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Also copy exports/ (~160 MB), so saved-file mode works without Depictio",
    )
    args = parser.parse_args()

    data = freeze(args.out, args.api, args.snapshot)
    total = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())

    print(f"out       {args.out}")
    print(f"apiBase   {data['apiBase']}")
    print(f"size      {total / 1024 / 1024:.1f} MB")
    print(f"pages     {len(serve_site.PAGES) + 1}")
    if not args.api:
        print(
            "\n  ! apiBase is this machine's address. Pass --api with a URL the "
            "recipient can reach,\n    or the pages will load and every figure will fail."
        )
    else:
        print(
            f"\n  Serve {args.out} from any static host, then add that host's origin to\n"
            "  DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS on the instance above."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
