"""Capture slices of real dashboards (a feature in context, not a lone tile).

Needs a running `depictio local up` whose home holds the nf-core protein and
oncoanalyser templates (`depictio ingest <megatest dir> --server local`) and the
dashboard of `option_cards_demo.yaml` (`depictio dashboard import ... --server local`).
Dashboards are found by project title and tab title, so no id is hard-coded.

Usage:
    python dev/advanced_viz_docs_screenshots/capture_slices.py OUT_DIR \
        [--base http://127.0.0.1:8162] [--only linked_view scope_banner ...]
Writes <name>_light.webp and <name>_dark.webp (cwebp -q 82) into OUT_DIR.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HOME = Path.home() / ".depictio/local-shots-v1192"
PAD = 4


def token() -> str:
    cfg = (HOME / "cli/admin_config.yaml").read_text()
    return re.search(r"access_token: (\S+)", cfg).group(1)


def api(base: str, path: str):
    req = urllib.request.Request(
        f"{base}/depictio/api/v1{path}", headers={"Authorization": f"Bearer {token()}"}
    )
    return json.load(urllib.request.urlopen(req))


def find_tab(base: str, project: str, tab: str) -> str:
    for main in api(base, "/dashboards/list"):
        if main["title"] != project:
            continue
        if main.get("main_tab_name") == tab:
            return main["dashboard_id"]
        for child in api(base, f"/dashboards/tabs/{main['dashboard_id']}")["child_tabs"]:
            if child["title"] == tab:
                return child["dashboard_id"]
    raise SystemExit(f"no tab {tab!r} in {project!r}")


def union(*boxes: dict) -> dict:
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def box_of(page: Page, selector: str, text: str | None = None) -> dict:
    loc = page.locator(selector)
    if text:
        loc = loc.filter(has_text=text)
    return loc.first.bounding_box()


# Each slice: where, viewport, UI tidying, and how to find the clip.
def linked_view(page: Page) -> dict:
    section = box_of(page, ".is-linked-view")
    pane = box_of(page, ".depictio-linked-view-pane", "Picked structure")
    return {**section, "y": pane["y"] - 6, "height": section["y"] + section["height"] - pane["y"] + 6}


def scope_banner(page: Page) -> dict:
    b = box_of(page, ".depictio-scope-banner")
    return {**b, "y": b["y"] - 6, "height": b["height"] + 108}


def category_colors(page: Page) -> dict:
    return union(
        box_of(page, ".depictio-section-item", "Clonality"),
        box_of(page, ".depictio-section-item", "Along the genome"),
    )


def floating_structure(page: Page) -> dict:
    return {"x": 0, "y": 0, "width": 1600, "height": 690}


def option_cards(page: Page) -> dict:
    return {"x": 64, "y": 84, "width": 1528, "height": 590}


SLICES = {
    "linked_view": dict(
        project="nf-core/proteinfold", tab="Structure", size=(1780, 2800), close_filters=True,
        clip=linked_view,
    ),
    "scope_banner": dict(
        project="nf-core/proteinannotator", tab="Structure", size=(1780, 1100), close_filters=True,
        clip=scope_banner,
    ),
    "category_colors": dict(
        project="nf-core/oncoanalyser", tab="Small variants", size=(1780, 2000), close_filters=True,
        clip=category_colors,
    ),
    "floating_structure": dict(
        project="nf-core/proteinfamilies", tab="Families", size=(1600, 760), close_filters=True,
        clip=floating_structure,
    ),
    "option_cards": dict(
        project="Domain databases", tab="Domains", size=(1600, 760), collapse_tabs=True,
        clip=option_cards,
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--base", default="http://127.0.0.1:8162")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--wait", type=int, default=25000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, spec in SLICES.items():
            if args.only and name not in args.only:
                continue
            dash = find_tab(args.base, spec["project"], spec["tab"])
            for theme in ("light", "dark"):
                w, h = spec["size"]
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(
                    f"localStorage.setItem('theme-store', JSON.stringify('{theme}'));"
                    f"localStorage.setItem('mantine-color-scheme-value', '{theme}');"
                    "localStorage.setItem('depictio.walkthrough.builder', 'seen');"
                )
                page = ctx.new_page()
                page.goto(f"{args.base}/dashboard/{dash}?no-walkthrough=1")
                page.add_style_tag(
                    content=".hoverlayer, .modebar-container, .mantine-Notifications-root, .mantine-Tooltip-tooltip"
                    "{display:none!important}"
                )
                page.wait_for_timeout(args.wait)
                if spec.get("close_filters"):
                    close = page.get_by_label("Close filters")
                    if close.count():
                        close.first.click()
                        page.wait_for_timeout(3000)
                if spec.get("collapse_tabs"):
                    toggle = page.get_by_label("Collapse sidebar")
                    if toggle.count():
                        toggle.first.click()
                        page.wait_for_timeout(2500)
                page.mouse.move(800, 740)  # no tooltip from the last click
                page.wait_for_timeout(600)
                clip = spec["clip"](page)
                clip = {
                    "x": max(clip["x"] - PAD, 0),
                    "y": max(clip["y"] - PAD, 0),
                    "width": clip["width"] + 2 * PAD,
                    "height": clip["height"] + 2 * PAD,
                }
                png = args.out / f"{name}_{theme}.png"
                page.screenshot(path=str(png), clip=clip)
                webp = png.with_suffix(".webp")
                subprocess.run(
                    ["cwebp", "-quiet", "-q", "82", "-m", "6", str(png), "-o", str(webp)], check=True
                )
                png.unlink()
                print(f"{name:<20}{theme:<6}{int(clip['width'])}x{int(clip['height'])}")
                ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
