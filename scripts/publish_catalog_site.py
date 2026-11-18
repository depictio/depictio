"""Place one catalog-site export into the depictio-catalog Pages tree.

The Pages repository holds one directory per published slot: ``latest/`` (the
catalog on ``main``) and ``v<version>/`` for each release. This script copies an
export (``depictio catalog export-site``) into its slot, keeps only the newest
``--keep`` release directories, and rewrites the two files at the root:

- ``versions.json``: ``{"latest": "latest", "versions": ["v1.22.0", ...]}``,
  newest first, which the documentation reads to link a release's catalog;
- ``index.html``: a redirect to ``latest/``.

Usage::

    python scripts/publish_catalog_site.py --site DIR --export DIR --slot v1.22.0 [--keep 10]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

LATEST = "latest"
_RELEASE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-b(\d+))?$")

_REDIRECT = """<!doctype html>
<meta charset="utf-8">
<title>Depictio Tools Catalog</title>
<meta http-equiv="refresh" content="0; url=latest/">
<link rel="canonical" href="latest/">
<a href="latest/">Depictio Tools Catalog</a>
"""


def release_key(name: str) -> tuple[int, int, int, int]:
    """Sort key of a release slot; a beta sorts before its release."""
    m = _RELEASE.match(name)
    if m is None:
        raise ValueError(f"not a release slot: {name!r}")
    major, minor, patch, beta = m.groups()
    return (int(major), int(minor), int(patch), int(beta) if beta else 1_000_000)


def releases(site: Path) -> list[str]:
    """Release slots present in the site, newest first."""
    names = [p.name for p in site.iterdir() if p.is_dir() and _RELEASE.match(p.name)]
    return sorted(names, key=release_key, reverse=True)


def publish(site: Path, export: Path, slot: str, keep: int) -> list[str]:
    """Copy ``export`` into ``site/slot``, prune old releases, rewrite the root.

    Returns the release slots removed by the pruning.
    """
    if slot != LATEST:
        release_key(slot)  # refuse anything that is not latest or vX.Y.Z[-bN]
    if not (export / "index.html").is_file() or not (export / "data" / "index.json").is_file():
        raise SystemExit(f"{export} is not a catalog-site export (index.html, data/index.json)")
    if keep < 1:
        raise SystemExit("--keep must be at least 1")

    site.mkdir(parents=True, exist_ok=True)
    target = site / slot
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(export, target)

    present = releases(site)
    removed = present[keep:]
    for name in removed:
        shutil.rmtree(site / name)

    kept = present[:keep]
    (site / "versions.json").write_text(
        json.dumps({"latest": LATEST if (site / LATEST).is_dir() else None, "versions": kept})
        + "\n"
    )
    (site / "index.html").write_text(_REDIRECT)
    # Pages would otherwise run Jekyll and drop directories starting with "_".
    (site / ".nojekyll").touch()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True, help="Checkout of the Pages tree")
    parser.add_argument("--export", type=Path, required=True, help="catalog export-site output")
    parser.add_argument("--slot", required=True, help="'latest' or a release tag, e.g. v1.22.0")
    parser.add_argument("--keep", type=int, default=10, help="Release directories to keep")
    args = parser.parse_args()

    removed = publish(args.site, args.export, args.slot, args.keep)
    print(f"Published {args.slot}" + (f"; pruned {', '.join(removed)}" if removed else ""))


if __name__ == "__main__":
    main()
