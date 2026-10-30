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
    "cnv_profile": ("cnv_profile", 0),
    "complex_heatmap": ("complex_heatmap", 0),
    "contact_map": ("contact_map", 0),
    "coverage_track": ("coverage_track", 0),
    "da_barplot": ("da_barplot", 0),
    "damage_profile": ("damage_profile", 0),
    "dot_plot": ("dotplot", 0),
    "embedding": ("sc_umap", 0),
    "embedding_pca": ("sample_pca", 0),
    "genome_chord": ("genome_chord", 0),
    "genome_view": ("genome_view", 1),
    "group_compare": ("group_compare", 0),
    "knee_plot": ("knee_plot", 0),
    "lollipop": ("lollipop", 0),
    "manhattan": ("manhattan", 0),
    "oncoplot": ("oncoplot", 0),
    "parallel_coordinates": ("parallel_coordinates", 0),
    "phylogenetic": ("phylogeny", 0),
    "phylogenetic_summary": ("phylogeny", 0),
    "rarefaction": ("rarefaction", 0),
    "record_card": ("record_card", 0),
    "sankey": ("categorical_flow", 0),
    "stacked_taxonomy": ("stacked_taxonomy", 0),
    "sunburst": ("sunburst", 0),
    "transcript_structure": ("transcript_structure", 0),
    "upset_plot": ("upset", 0),
    "volcano": ("volcano", 0),
    "controls_header": ("volcano", 0),
    "controls_popover": ("volcano", 0),
    "controls_rail": ("volcano", 0),
}
# docs image name -> the viz_kind stored in the seed (differs for retired kinds)
SEED_KIND = {
    "embedding_pca": "embedding",
    "roc_pr_curve": "pr_benchmark",
    "phylogenetic_summary": "phylogenetic",
    "controls_header": "volcano",
    "controls_popover": "volcano",
    "controls_rail": "volcano",
}


def _placement(label: str, keep_open: bool = False):
    """Switch the tile's controls placement with the switch in its controls."""

    def act(page, tile):
        # DOM clicks: the tile head overlaps the placement switch.
        tile.get_by_text(label, exact=True).first.dispatch_event("click")
        page.wait_for_timeout(2500)
        # Switching to the popover opens it; open it if it is not.
        opener = tile.get_by_label("Viz settings")
        if keep_open and opener.count():
            opener.first.dispatch_event("click")
            page.wait_for_timeout(1500)

    return act


def _phylo_summary(page, tile):
    """Full tree -> Summary by rank, collapsed to Genus, top 12 (header controls)."""
    tile.get_by_text("Summary by rank", exact=True).first.click()
    page.wait_for_timeout(2500)
    tile.get_by_label("Collapse to").click()
    page.get_by_role("option", name="Genus", exact=True).click()
    page.wait_for_timeout(800)
    top_n = tile.get_by_label("Top N")
    top_n.fill("12")
    top_n.press("Enter")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(3000)


def _sashimi_arcs(page, tile):
    """Arcs view: the GenomeSpy view fails at v1.19.3 (subscribeMarkEvent of undefined)."""
    tile.get_by_text("Arcs", exact=True).first.dispatch_event("click")
    page.wait_for_timeout(4000)


# docs image name -> what to do on the tile before the shot
ACTIONS = {
    "sashimi": _sashimi_arcs,
    "phylogenetic_summary": _phylo_summary,
    "controls_header": _placement("Under the title"),
    "controls_rail": _placement("In a side rail"),
    "controls_popover": _placement("In the settings popover", keep_open=True),
}

# docs image name -> chrome style (`?chrome=`). The Glass chrome's Plotly patch
# drops axis lines, so the embedding's "Axis lines" plot style only shows in
# the Classic chrome ("base").
CHROME = {"embedding": "base", "embedding_pca": "base"}

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
                chrome = f"&chrome={CHROME[name]}" if name in CHROME else ""
                page.goto(f"{args.base}/dashboard/{dash_id}?no-walkthrough=1{chrome}")
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
                    # A DOM click: on a tall viewport the sidebar overlaps the button.
                    close.first.evaluate("e => e.click()")
                    page.wait_for_timeout(2500)
                if name in ACTIONS:
                    ACTIONS[name](page, tile)
                    # Off the tile, so its hover chrome does not show.
                    page.mouse.move(1, 1)
                    page.wait_for_timeout(800)
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
