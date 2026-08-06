#!/usr/bin/env python3
"""Screenshot the Load-all control in a real dashboard panel, light and dark.

The docs used to only describe this button ("an action icon in each panel's
hover cluster"), which is not much help when you are looking at the UI trying
to find it. A cropped capture of the real chrome shows where it sits, what it
looks like next to the other actions, and what the reduction badge beside it
says.

Captured against a running dev stack rather than mocked, so the badge carries
genuine counts from the benchmark project and the shot cannot drift from the
component it documents without the capture failing.

Usage:
    python dev/diagrams/capture_load_all.py --out <dir> [--dashboard <id>]
"""

from __future__ import annotations

from pathlib import Path

import typer
from playwright.sync_api import Page, sync_playwright

app = typer.Typer(add_completion=False)

VIEWER = "http://localhost:5600"

# A 4-component panel from the benchmark project: real bounded data, and few
# enough panels that the first figure settles quickly.
DASHBOARD = "6a69c9a48bf698169768f943"

# Padding around the cropped region, in CSS pixels. Enough to show the panel
# corner the cluster is anchored to without pulling in a neighbouring panel.
PAD_X, PAD_Y = 14, 12

# Room for the Load-all tooltip, which renders outside the panel box and to
# the left of the icon.
TOOLTIP_ROOM = 30


def _find_reduced_panel(page: Page):
    """Return the panel whose figure is showing a reduced view.

    Keyed off the badge text ("10,000 / 5,000,000 pts") rather than a test id,
    so the capture fails loudly if the reduction indicator stops rendering
    instead of quietly producing a shot of an unreduced panel.
    """
    badge = page.locator("text=/[\\d,]+ \\/ [\\d,]+ pts/").first
    badge.wait_for(state="visible", timeout=120_000)
    return badge


def _capture(page: Page, out: Path, theme: str) -> None:
    """Shoot the whole panel with its action cluster and tooltip showing.

    The panel rather than a cropped corner: the point of the figure is *where*
    the control lives, which a floating cluster of icons on white cannot say.
    """
    badge = _find_reduced_panel(page)
    panel = badge.locator("xpath=ancestor::*[contains(@class,'react-grid-item')][1]")
    panel.scroll_into_view_if_needed()

    # The action cluster only exists on hover, so the pointer has to stay over
    # the panel for the whole capture.
    panel.hover()
    page.wait_for_timeout(600)

    actions = panel.locator(".depictio-component-actions").first
    actions.wait_for(state="visible", timeout=10_000)

    # Hover the Load-all icon itself so its tooltip renders in the shot: the
    # tooltip is what tells a reader the control can be slow on a large
    # collection, which is the whole reason it is opt-in.
    load_all = actions.locator('button[aria-label^="Load all"]').first
    load_all.wait_for(state="visible", timeout=10_000)
    load_all.hover()
    page.wait_for_timeout(700)

    box = panel.bounding_box()
    tip = page.locator(".mantine-Tooltip-tooltip").first
    tip_box = tip.bounding_box() if tip.count() else None
    if not box:
        raise SystemExit("could not measure the panel")

    # The tooltip renders outside the panel, so the clip has to cover both.
    left = box["x"] - PAD_X
    top = box["y"] - PAD_Y
    right = box["x"] + box["width"] + PAD_X
    bottom = box["y"] + box["height"] + PAD_Y
    if tip_box:
        left = min(left, tip_box["x"] - TOOLTIP_ROOM)
        top = min(top, tip_box["y"] - TOOLTIP_ROOM)
        # The tooltip overhangs the panel's right edge, but following it all the
        # way would pull the neighbouring panel into frame. Stop at the tooltip
        # and let its last few pixels sit flush with the crop.
        right = max(right, tip_box["x"] + tip_box["width"] + 6)

    left, top = max(left, 0), max(top, 0)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(
        path=str(out),
        clip={"x": left, "y": top, "width": right - left, "height": bottom - top},
    )
    print(f"→ {out}  ({theme})")


def _set_theme(page: Page, theme: str) -> None:
    """Persist the colour scheme the way the app itself reads it.

    ``main.tsx::readInitialColorScheme`` parses ``theme-store`` and takes
    ``colorScheme`` off it, so writing that key is what makes the reload come
    up in the requested theme. Merging into any existing value rather than
    overwriting keeps the rest of the store intact.
    """
    page.evaluate(
        """t => {
          let store = {};
          try { store = JSON.parse(localStorage.getItem('theme-store') ?? '{}') ?? {}; }
          catch { store = {}; }
          store.colorScheme = t;
          localStorage.setItem('theme-store', JSON.stringify(store));
        }""",
        theme,
    )


def _dismiss_walkthrough(page: Page) -> None:
    """Clear the overlays that would otherwise sit on top of the shot.

    The guided tour renders a fixed spotlight backdrop that intercepts pointer
    events, so the panel never receives the hover that reveals the action
    cluster. Persisting a "completed" state would need the tour's current
    version string to match, which silently stops working the moment a step is
    added; hiding it by its own data attribute keeps working regardless.

    Plotly's modebar appears on the same hover and would crowd the frame with
    controls that are not what this figure documents, so it goes too.
    """
    page.add_style_tag(
        content="""
        [data-walkthrough="backdrop"], [data-walkthrough="card"] {
          display: none !important;
          pointer-events: none !important;
        }
        .modebar-container, .modebar { display: none !important; }
        """
    )


def _assert_theme(page: Page, theme: str) -> None:
    """Fail rather than quietly shipping two identical "light" and "dark" shots.

    A wrong storage key produces a perfectly valid screenshot in the default
    theme, which is exactly the kind of error that survives review.
    """
    try:
        # Mantine sets the attribute once the provider mounts, which is after
        # DOM-ready, so this has to be waited for rather than read immediately.
        page.wait_for_function(
            "t => document.documentElement.getAttribute('data-mantine-color-scheme') === t",
            arg=theme,
            timeout=30_000,
        )
    except Exception:
        actual = page.evaluate(
            "() => document.documentElement.getAttribute('data-mantine-color-scheme')"
        )
        raise SystemExit(f"expected the {theme} theme, the page rendered {actual!r}")


@app.command()
def main(
    out: Path = typer.Option(..., "--out", help="Directory to write the PNGs into."),
    dashboard: str = typer.Option(DASHBOARD, "--dashboard"),
    themes: str = typer.Option("light,dark", "--themes"),
) -> None:
    """Capture load_all_<theme>.png for each requested theme."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in [t.strip() for t in themes.split(",") if t.strip()]:
            page = browser.new_page(
                viewport={"width": 1600, "height": 1000}, device_scale_factor=2
            )
            page.goto(f"{VIEWER}/dashboard/{dashboard}", wait_until="domcontentloaded")
            _set_theme(page, theme)
            page.reload(wait_until="domcontentloaded")
            _assert_theme(page, theme)
            _dismiss_walkthrough(page)
            _capture(page, out / f"load_all_{theme}.png", theme)
            page.close()
        browser.close()


if __name__ == "__main__":
    app()
