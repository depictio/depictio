"""Drive the /screenshot-react-dual endpoint for every advanced-viz dashboard.

Hits the React-beta screenshot endpoint once per viz_kind, then converts the
resulting PNGs to WebP into the docs folder under their canonical viz_kind
name so the `#only-light` / `#only-dark` refs in components.md resolve.

Usage:
    python3 dev/advanced_viz_docs_screenshots/capture_react_screenshots.py \
        [--open-settings] [--only volcano ma ...]

See ./README.md for the auth-token bootstrap curl.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API_BASE = "http://localhost:8100"
SCREENSHOT_DIR = Path(
    "/Users/tweber/Gits/workspaces/depictio-workspace/"
    "depictio-worktrees/claude-volcano-plot-interactive-cTRTQ/"
    "depictio/dash/static/screenshots"
)
DOCS_DIR = Path(
    "/Users/tweber/Gits/workspaces/depictio-workspace/"
    "depictio-docs-worktrees/advanced-viz-docs/docs/images/"
    "guides/advanced-visualizations"
)
TOKEN_FILE = Path("/tmp/admin_token.txt")

# One representative dashboard per unique viz_kind. 5 embedding variants
# (pca, pcoa, tsne, umap, live) all share the embedding renderer — pick one.
VIZ_MAP: dict[str, str] = {
    "volcano": "646b0f3c1e4a2d7f8e5b8d00",
    "ma": "646b0f3c1e4a2d7f8e5b8d40",
    "da_barplot": "646b0f3c1e4a2d7f8e5b8d24",
    "enrichment": "646b0f3c1e4a2d7f8e5b8d26",
    "manhattan": "646b0f3c1e4a2d7f8e5b8d13",
    "lollipop": "646b0f3c1e4a2d7f8e5b8d42",
    "coverage_track": "646b0f3c1e4a2d7f8e5b8d46",
    "stacked_taxonomy": "646b0f3c1e4a2d7f8e5b8d14",
    "sunburst": "646b0f3c1e4a2d7f8e5b8d44",
    "rarefaction": "646b0f3c1e4a2d7f8e5b8d22",
    "phylogenetic": "646b0f3c1e4a2d7f8e5b8d18",
    "dot_plot": "646b0f3c1e4a2d7f8e5b8d41",
    "embedding": "646b0f3c1e4a2d7f8e5b8d15",
    "complex_heatmap": "646b0f3c1e4a2d7f8e5b8d27",
    "qq": "646b0f3c1e4a2d7f8e5b8d43",
    "upset_plot": "646b0f3c1e4a2d7f8e5b8d29",
    "sankey": "646b0f3c1e4a2d7f8e5b8d47",
    "oncoplot": "646b0f3c1e4a2d7f8e5b8d45",
}


def trigger(token: str, dashboard_id: str, prefix: str, open_settings: bool) -> dict:
    url = (
        f"{API_BASE}/depictio/api/v1/utils/screenshot-react-dual/"
        f"{dashboard_id}?filename_prefix={prefix}"
        f"{'&open_settings=true' if open_settings else ''}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    # The screenshot pass runs Playwright headlessly inside the API container
    # for both themes — ~25s per dashboard is normal; allow a generous ceiling.
    with urllib.request.urlopen(req, timeout=300) as resp:
        import json

        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--open-settings",
        action="store_true",
        help="Click the viz settings cog before capture (popover in shot).",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        help="Only run these viz_kinds (default: all 18).",
    )
    args = parser.parse_args()

    if not TOKEN_FILE.is_file():
        print(f"missing {TOKEN_FILE} — re-run the login curl first.", file=sys.stderr)
        return 1
    token = TOKEN_FILE.read_text().strip()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    targets = {k: v for k, v in VIZ_MAP.items() if not args.only or k in args.only}
    total = len(targets)
    print(f"Capturing {total} viz × 2 themes (open_settings={args.open_settings})")
    print(f"  source : {SCREENSHOT_DIR}")
    print(f"  dest   : {DOCS_DIR}")
    print()

    summary: list[tuple[str, str, str]] = []  # (viz_kind, status, detail)
    overall_start = time.time()

    for i, (viz_kind, dashboard_id) in enumerate(targets.items(), start=1):
        t0 = time.time()
        print(f"[{i:2d}/{total}] {viz_kind:<20} ({dashboard_id}) ...", end=" ", flush=True)
        try:
            result = trigger(token, dashboard_id, viz_kind, args.open_settings)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"FAIL ({elapsed:.1f}s) {e}")
            summary.append((viz_kind, "FAIL", str(e)[:100]))
            continue

        if result.get("status") != "success":
            elapsed = time.time() - t0
            print(f"NON-SUCCESS ({elapsed:.1f}s) status={result.get('status')}")
            summary.append((viz_kind, result.get("status", "?"), result.get("error", "") or ""))
            continue

        # Endpoint writes <prefix>_<dashboard_id>_<theme>.png — convert to
        # WebP (q82) on the way into the docs folder so the docs repo stays
        # under ~2 MB across 36 shots instead of carrying 4 MB of PNGs.
        copied = []
        for theme in ("light", "dark"):
            src = SCREENSHOT_DIR / f"{viz_kind}_{dashboard_id}_{theme}.png"
            dst = DOCS_DIR / f"{viz_kind}_{theme}.webp"
            if not src.is_file():
                print(f"MISSING {src.name}", end=" ")
                continue
            try:
                subprocess.run(
                    ["cwebp", "-quiet", "-q", "82", "-m", "6", str(src), "-o", str(dst)],
                    check=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fall back to the original PNG if cwebp isn't installed —
                # better to ship a too-large image than fail the whole pass.
                shutil.copy2(src, dst.with_suffix(".png"))
            copied.append(theme)

        elapsed = time.time() - t0
        if len(copied) == 2:
            print(f"OK ({elapsed:.1f}s)")
            summary.append((viz_kind, "OK", f"{elapsed:.1f}s"))
        else:
            print(f"PARTIAL ({elapsed:.1f}s) copied={copied}")
            summary.append((viz_kind, "PARTIAL", f"copied={copied}"))

    elapsed_total = time.time() - overall_start
    print()
    print(f"Done in {elapsed_total:.0f}s. Summary:")
    print(f"  {'viz_kind':<20} {'status':<10} detail")
    print("  " + "-" * 60)
    for viz_kind, status, detail in summary:
        print(f"  {viz_kind:<20} {status:<10} {detail}")

    n_ok = sum(1 for _, s, _ in summary if s == "OK")
    print()
    print(f"{n_ok}/{total} successful — see {DOCS_DIR}")
    return 0 if n_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
