"""Capture one tile per advanced-viz kind, light and dark, from a running instance.

Playwright drives a local depictio (`depictio local up`, with the
`advanced_viz_showcase` project seeded) and clips each viz tile out of its
showcase dashboard at 1x with 10 px of padding, then converts to WebP.

A very tall viewport renders the whole dashboard without scrolling, so a clip
never meets the floating toolbar or a lazy tile. The first-run tour is marked
as seen, and the Plotly hover layer, modebar and toasts are hidden.

Usage:
    python dev/advanced_viz_docs_screenshots/capture_tiles.py OUT_DIR \
        [--base http://127.0.0.1:8162] [--only molecule_3d msa ...] [--keep-png]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SEEDS = Path(__file__).resolve().parents[2] / "depictio/projects/init/advanced_viz_showcase/.db_seeds"

# docs image name -> (showcase dashboard seed, nth advanced_viz tile of that kind)
TARGETS: dict[str, tuple[str, int]] = {
    "molecule_3d": ("protein_structure", 0),
    "msa": ("protein_structure", 0),
    "sequence_track": ("protein_structure", 0),
    "hmm_logo": ("protein_families", 0),
    "domain_architecture": ("protein_families", 0),
    "secondary_structure": ("protein_quality", 0),
    "pae_matrix": ("protein_quality", 0),
    "ramachandran": ("protein_quality", 0),
    "pr_benchmark": ("benchmark_pr", 0),
    "roc_pr_curve": ("benchmark_pr", 1),
    "confusion_matrix": ("benchmark_confusion", 0),
    "metric_ci_bars": ("benchmark_ci", 0),
    "profile": ("profile", 0),
    "signal_matrix": ("signal_matrix", 0),
    "fusion_structure": ("fusion_structure", 0),
    "gene_arrow_track": ("gene_arrow_track", 0),
    "gsea_running_score": ("gsea_running_score", 0),
    "sashimi": ("sashimi", 0),
    "scatter_xy": ("scatter_xy", 0),
}
# docs image name -> the viz_kind stored in the seed (differs for retired kinds)
SEED_KIND = {"roc_pr_curve": "pr_benchmark"}

HIDE_CSS = (
    ".hoverlayer, .modebar-container, .mantine-Notifications-root "
    "{display:none!important}"
)
PAD = 4


def locate(name: str) -> tuple[str, str]:
    seed, nth = TARGETS[name]
    data = json.loads((SEEDS / f"dashboard_{seed}.json").read_text())
    kind = SEED_KIND.get(name, name)
    tiles = [
        c for c in data["stored_metadata"]
        if c.get("component_type") == "advanced_viz" and c.get("viz_kind") == kind
    ]
    return data["dashboard_id"]["$oid"], tiles[nth]["index"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--base", default="http://127.0.0.1:8162")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--wait", type=int, default=9000, help="ms to let tiles render")
    ap.add_argument("--keep-png", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in TARGETS:
            if args.only and name not in args.only:
                continue
            dash_id, index = locate(name)
            for theme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": 1780, "height": 3300})
                ctx.add_init_script(
                    f"localStorage.setItem('theme-store', JSON.stringify('{theme}'));"
                    f"localStorage.setItem('mantine-color-scheme-value', '{theme}');"
                    "localStorage.setItem('depictio.walkthrough.builder', 'seen');"
                )
                page = ctx.new_page()
                page.goto(f"{args.base}/dashboard/{dash_id}?no-walkthrough=1")
                page.add_style_tag(content=HIDE_CSS)
                tile = page.locator(
                    f'.depictio-component-chrome[data-component-type="advanced_viz"]'
                    f'[data-component-index="{index}"]'
                )
                tile.wait_for(timeout=30000)
                page.wait_for_timeout(args.wait)
                # Close the filter panel so tiles take the full grid width.
                close = page.get_by_label("Close filters")
                if close.count():
                    close.first.click()
                    page.wait_for_timeout(2500)
                box = tile.bounding_box()
                png = args.out / f"{name}_{theme}.png"
                page.screenshot(
                    path=str(png),
                    clip={
                        "x": max(box["x"] - PAD, 0),
                        "y": max(box["y"] - PAD, 0),
                        "width": box["width"] + 2 * PAD,
                        "height": box["height"] + 2 * PAD,
                    },
                )
                webp = png.with_suffix(".webp")
                subprocess.run(["cwebp", "-quiet", "-q", "82", "-m", "6", str(png), "-o", str(webp)], check=True)
                if not args.keep_png:
                    png.unlink()
                print(f"{name:<22}{theme:<6}{int(box['width'])}x{int(box['height'])}")
                ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
