#!/usr/bin/env python3
"""Render the filter-persistence schemas as hand-drawn, illustrated SVGs.

Two diagrams, drawn with the shared sketch toolkit (little browser windows with
real-looking controls, a database cylinder, tabs, a toggle, chips, a URL bar):

* ``one_array``   - the five filter levels (panel and filter bar, scatter
  box / lasso, map, table rows, images) all converge on one
  ``InteractiveFilter[]``, which is kept in four places, each drawn with its
  lifetime: the cross-tab sessionStorage store, localStorage, the per-user
  server document and the ``#filters=`` share link.
* ``mount_merge`` - what happens when a dashboard opens: the synchronous
  three-source merge (remembered < cross-tab < link) that makes the first fetch
  already filtered, the pruning of entries whose component is gone, the async
  server copy behind four gates, and the two cases that restore nothing
  (``?version=`` preview, "Reset all").

Usage:
    python dev/diagrams/filter_persistence.py --out docs/images/filter_persistence
    # writes <out>_one_array.svg and <out>_mount_merge.svg (SVG only)

The seeded jitter makes re-runs byte-identical. Set DEPICTIO_VIRGIL_TTF when
previewing a PNG elsewhere; the SVGs name the font and need nothing else.
See sketch.py for the drawing primitives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    BLUE_INK,
    DIM,
    GOLD,
    GREEN,
    GREEN_INK,
    GREY,
    INK,
    LIGHT_GREY,
    ORANGE,
    ORANGE_INK,
    PINK,
    RED,
    RED_INK,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    circle,
    ellipse,
    tick,
    write,
)

app = typer.Typer(add_completion=False)


# --------------------------------------------------------------------------
# Glyphs: small pictograms shared by both diagrams.
# --------------------------------------------------------------------------


def panel(
    s: Sketch, x: float, y: float, w: float, h: float, fill: str = WHITE, **kw: object
) -> Box:
    b = Box(x, y, w, h, fill, "", ())
    s.rect(b, **kw)  # ty: ignore[invalid-argument-type]
    return b


def pill(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    label: str,
    fill: str = WHITE,
    *,
    h: float = 24,
    size: float = 12,
    colour: str = INK,
    line: str = INK,
    dashed: bool = False,
    weight: str = "normal",
) -> Box:
    b = panel(s, x, y, w, h, fill, colour=line, dashed=dashed)
    s.text(b.cx, y + h / 2 + size * 0.34, label, size=size, colour=colour, weight=weight)
    return b


def fchip(
    s: Sketch,
    x: float,
    y: float,
    label: str,
    fill: str = BLUE,
    *,
    w: float | None = None,
    size: float = 11.5,
    h: float = 22,
    close: bool = True,
    dashed: bool = False,
    colour: str = INK,
) -> float:
    """A filter-bar chip: the label and a small x. Returns its width."""
    width = w if w is not None else 18 + len(label) * 6.3 + (14 if close else 0)
    panel(s, x, y, width, h, fill, colour=GREY if dashed else INK, dashed=dashed)
    s.text(x + 9, y + h / 2 + size * 0.34, label, size=size, anchor="start", colour=colour)
    if close:
        cx, cy = x + width - 11, y + h / 2
        s.line(cx - 3, cy - 3, cx + 3, cy + 3, width=1.3, amount=0.2, passes=1, colour=DIM)
        s.line(cx - 3, cy + 3, cx + 3, cy - 3, width=1.3, amount=0.2, passes=1, colour=DIM)
    return width


def toggle(s: Sketch, x: float, y: float, on: bool, *, w: float = 40, h: float = 22) -> None:
    panel(s, x, y, w, h, GREEN_INK if on else LIGHT_GREY, colour=INK if on else GREY)
    kx = x + w - h / 2 if on else x + h / 2
    s.dot(kx, y + h / 2, h / 2 - 3, fill=WHITE, colour=INK if on else GREY)


def cylinder(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A database: a can with two bands, the top face drawn as an ellipse."""
    rx, ry = w / 2, 9
    bottom = top + h
    s._parts.append(
        f'<path d="M{cx - rx:.1f},{top:.1f} V{bottom:.1f} A{rx:.1f},{ry} 0 0 0 {cx + rx:.1f},'
        f'{bottom:.1f} V{top:.1f} Z" fill="{fill}"/>'
    )
    s.line(cx - rx, top, cx - rx, bottom, amount=1.0)
    s.line(cx + rx, top, cx + rx, bottom, amount=1.0)
    for dy in (h * 0.36, h * 0.68, h):
        s._parts.append(
            f'<path d="M{cx - rx:.1f},{top + dy:.1f} A{rx:.1f},{ry} 0 0 0 {cx + rx:.1f},'
            f'{top + dy:.1f}" fill="none" stroke="{INK}" stroke-width="1.6" '
            f'stroke-linecap="round"/>'
        )
    ellipse(s, cx, top, rx, ry, WHITE)


def clock(s: Sketch, cx: float, cy: float, r: float = 11) -> None:
    circle(s, cx, cy, r, WHITE)
    s.line(cx, cy, cx, cy - r * 0.62, amount=0.2, passes=1, width=1.6)
    s.line(cx, cy, cx + r * 0.5, cy + r * 0.12, amount=0.2, passes=1, width=1.6)
    s.dot(cx, cy, 1.6, fill=INK)


def link_glyph(s: Sketch, cx: float, cy: float, size: float = 9, colour: str = INK) -> None:
    """Two chain links."""
    for dx in (-size * 0.55, size * 0.55):
        s._parts.append(
            f'<rect x="{cx + dx - size * 0.85:.1f}" y="{cy - size * 0.42:.1f}" '
            f'width="{size * 1.7:.1f}" height="{size * 0.84:.1f}" rx="{size * 0.42:.1f}" '
            f'fill="none" stroke="{colour}" stroke-width="1.9" '
            f'transform="rotate(-35 {cx:.1f} {cy:.1f})"/>'
        )


def cursor(s: Sketch, x: float, y: float) -> None:
    s.poly(
        [
            (x, y),
            (x, y + 17),
            (x + 4.5, y + 13),
            (x + 8, y + 20),
            (x + 11, y + 18.5),
            (x + 7.5, y + 12),
            (x + 13, y + 12),
        ],
        fill=WHITE,
        amount=0.4,
    )


def eye(s: Sketch, cx: float, cy: float) -> None:
    ellipse(s, cx, cy, 13, 8, WHITE, n=20)
    s.dot(cx, cy, 4.5, fill=INK)


def pin(s: Sketch, cx: float, cy: float) -> None:
    s.poly([(cx - 5.5, cy), (cx + 5.5, cy), (cx, cy + 11)], fill=RED_INK, amount=0.3)
    circle(s, cx, cy - 4, 7, RED_INK)
    s.dot(cx, cy - 4, 2.6, fill=WHITE, width=0.8)


def tab(
    s: Sketch, x: float, y: float, w: float, h: float, label: str, *, active: bool = False
) -> None:
    pts = [(x, y + h), (x, y + 6), (x + 6, y), (x + w - 6, y), (x + w, y + 6), (x + w, y + h)]
    s.poly(pts, fill=YELLOW if active else LIGHT_GREY, edges=(0, 1, 2, 3, 4), amount=0.7)
    s.text(x + w / 2, y + h / 2 + 4, label, size=11.5, weight="bold" if active else "normal")


def avatar(s: Sketch, cx: float, cy: float, r: float, ghost: bool = False) -> None:
    """A person: head and shoulders."""
    colour = GREY if ghost else INK
    s.dot(cx, cy - r * 0.35, r * 0.42, fill=WHITE, colour=colour, dashed=ghost)
    s._parts.append(
        f'<path d="M{cx - r * 0.85:.1f},{cy + r * 0.85:.1f} Q{cx:.1f},{cy - r * 0.35:.1f} '
        f'{cx + r * 0.85:.1f},{cy + r * 0.85:.1f}" fill="none" stroke="{colour}" '
        f'stroke-width="1.6" stroke-linecap="round"'
        f"{' stroke-dasharray=' + chr(34) + '3 3' + chr(34) if ghost else ''}/>"
    )


def window(s: Sketch, x: float, y: float, w: float, h: float, url: str = "") -> None:
    """A small browser window: traffic lights, an address pill, a blank page."""
    panel(s, x, y, w, h, WHITE)
    s.line(x, y + 20, x + w, y + 20, amount=0.6, passes=1)
    for i, c in enumerate(("#ff8787", "#ffd43b", "#69db7c")):
        s._parts.append(f'<circle cx="{x + 10 + i * 10:.1f}" cy="{y + 10:.1f}" r="3" fill="{c}"/>')
    if url:
        panel(s, x + 42, y + 4, w - 50, 12, LIGHT_GREY, colour=GREY)
        s.text(x + 47, y + 13.5, url, size=8.5, anchor="start", colour=DIM)


def bars(s: Sketch, x: float, y: float, w: float, h: float, values: tuple[float, ...]) -> None:
    """Axes with bars: a chart that is plainly a chart."""
    s.line(x, y, x, y + h, amount=0.5, width=1.3, passes=1)
    s.line(x, y + h, x + w, y + h, amount=0.5, width=1.3, passes=1)
    bw = (w - 8) / len(values) - 5
    for i, v in enumerate(values):
        bx = x + 6 + i * (bw + 5)
        panel(s, bx, y + h - h * v, bw, h * v, BLUE_INK)


def mark(s: Sketch, x: float, y: float, ok: bool) -> None:
    if ok:
        tick(s, x, y, size=6)
    else:
        s.cross(x, y, size=5.5)


def lifetime(
    s: Sketch, x: float, y: float, rows: tuple[tuple[str, bool], ...], *, gap: float
) -> None:
    """The lifetime strip: what survives which event, as tick / cross + caption."""
    for i, (label, ok) in enumerate(rows):
        cx = x + i * gap
        mark(s, cx + 8, y, ok)
        s.text(cx + 22, y + 4, label, size=11.5, anchor="start", colour=INK if ok else DIM)


# --------------------------------------------------------------------------
# 1. One array, four places it can live.
# --------------------------------------------------------------------------

ARRAY_W, ARRAY_H = 1350, 960

CARD_X, CARD_W, CARD_H, CARD_GAP, TOP = 40, 360, 134, 14, 130


def _mock_panel(s: Sketch, x: float, y: float) -> None:
    """Left panel: a select, a range slider and the chips of the filter bar."""
    panel(s, x, y, 140, 100, WHITE)
    panel(s, x + 8, y + 8, 100, 22, LIGHT_GREY, colour=GREY)
    s.text(x + 15, y + 23, "setosa", size=11.5, anchor="start")
    s.poly(
        [(x + 92, y + 16), (x + 102, y + 16), (x + 97, y + 23)], fill=INK, amount=0.2, colour=INK
    )
    s.line(x + 10, y + 50, x + 130, y + 50, colour=GREY, amount=0.4, width=3, passes=1)
    s.line(x + 38, y + 50, x + 98, y + 50, colour=BLUE_INK, amount=0.4, width=4, passes=1)
    s.dot(x + 38, y + 50, 6, fill=WHITE, width=1.6)
    s.dot(x + 98, y + 50, 6, fill=WHITE, width=1.6)
    fchip(s, x + 8, y + 68, "EU", BLUE, size=11)
    fchip(s, x + 56, y + 68, "2019", BLUE, size=11)
    s.text(x + 118, y + 83, "...", size=12, colour=DIM)


def _mock_scatter(s: Sketch, x: float, y: float) -> None:
    panel(s, x, y, 140, 100, WHITE)
    s.line(x + 12, y + 8, x + 12, y + 88, amount=0.4, passes=1, width=1.2)
    s.line(x + 12, y + 88, x + 132, y + 88, amount=0.4, passes=1, width=1.2)
    pts = (
        (0.08, 0.70, 0), (0.18, 0.52, 0), (0.30, 0.66, 0), (0.30, 0.30, 1), (0.42, 0.42, 1),
        (0.50, 0.24, 1), (0.58, 0.46, 1), (0.66, 0.30, 1), (0.80, 0.34, 0), (0.88, 0.14, 0),
        (0.20, 0.84, 0), (0.46, 0.80, 0), (0.74, 0.62, 0),
    )  # fmt: skip
    for fx, fy, sel in pts:
        s.dot(x + 16 + fx * 112, y + 10 + fy * 74, 3.6, fill=GOLD if sel else WHITE, width=1.1)
    lasso = [(0.22, 0.20), (0.48, 0.10), (0.74, 0.18), (0.76, 0.44), (0.52, 0.56), (0.28, 0.50)]
    d = "M" + " L".join(f"{x + 16 + a * 112:.1f},{y + 10 + b * 74:.1f}" for a, b in lasso) + " Z"
    s._parts.append(
        f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.5" stroke-dasharray="4 3" '
        f'stroke-linejoin="round"/>'
    )


def _mock_map(s: Sketch, x: float, y: float) -> None:
    panel(s, x, y, 140, 100, WHITE)
    regions = (
        ([(10, 26), (56, 12), (74, 44), (40, 66), (12, 56)], GOLD),
        ([(56, 12), (112, 20), (124, 54), (74, 44)], GOLD),
        ([(40, 66), (74, 44), (124, 54), (106, 90), (50, 90)], LIGHT_GREY),
    )
    for pts, fill in regions:
        s.poly([(x + a, y + b) for a, b in pts], fill=fill, amount=0.7)
    pin(s, x + 50, y + 36)


def _mock_table(s: Sketch, x: float, y: float) -> None:
    panel(s, x, y, 140, 100, WHITE)
    s.line(x + 6, y + 22, x + 134, y + 22, amount=0.4, passes=1, width=1.2)
    s.text(x + 28, y + 15, "id", size=9.5, anchor="start", colour=GREY)
    s.text(x + 70, y + 15, "sample", size=9.5, anchor="start", colour=GREY)
    for i, on in enumerate((False, True, True, False)):
        ry = y + 28 + i * 17
        if on:
            panel(s, x + 4, ry - 2, 132, 17, BLUE, colour=BLUE_INK)
        panel(s, x + 10, ry + 1, 10, 10, BLUE_INK if on else WHITE, colour=INK if on else GREY)
        if on:
            tick(s, x + 15, ry + 6, size=3.2, colour=WHITE)
        s.line(x + 28, ry + 6, x + 48 + (i % 2) * 8, ry + 6, colour=GREY, amount=0.3, passes=1)
        s.line(x + 70, ry + 6, x + 104 - i * 4, ry + 6, colour=GREY, amount=0.3, passes=1)


def _mock_images(s: Sketch, x: float, y: float) -> None:
    panel(s, x, y, 140, 100, WHITE)
    for i in range(3):
        tx, ty = x + 9 + i * 44, y + 14
        on = i == 1
        panel(s, tx, ty, 38, 50, LIGHT_GREY, colour=INK if on else GREY)
        s.dot(tx + 26, ty + 14, 4, fill=GOLD, width=0.9)
        s.poly(
            [(tx + 3, ty + 44), (tx + 15, ty + 24), (tx + 24, ty + 36), (tx + 29, ty + 30),
             (tx + 35, ty + 44)],
            fill=GREEN_INK,
            amount=0.4,
        )  # fmt: skip
        if on:
            s._parts.append(
                f'<rect x="{tx - 4}" y="{ty - 4}" width="46" height="58" rx="6" fill="none" '
                f'stroke="{INK}" stroke-width="1.4" stroke-dasharray="4 3"/>'
            )
            circle(s, tx + 36, ty + 2, 8, GREEN_INK)
            tick(s, tx + 36, ty + 2, size=3.6, colour=WHITE)
    s.text(x + 70, y + 88, "gallery picks", size=9.5, colour=DIM)


LEVELS = (
    (
        BLUE,
        _mock_panel,
        "Left panel + filter bar",
        ("select, slider, switch,", "text; chips list them"),
    ),
    (GREEN, _mock_scatter, "Scatter box + lasso", ("points picked in the", "plot become a filter")),
    (YELLOW, _mock_map, "Map selection", ("regions picked on the", "map, grid or floating")),
    (VIOLET, _mock_table, "Table row selection", ("ticked rows become", "a filter on those rows")),
    (ORANGE, _mock_images, "Image selection", ("gallery picks become", "a filter on those images")),
)

CHIPS = (
    "species = setosa",
    "lasso: 14 points",
    "region in DE, FR",
    "rows: 3 selected",
    "images: 2 picked",
)


def _home_a(s: Sketch, x: float, y: float, h: float) -> None:
    """sessionStorage: a strip of browser tabs, the filter surviving the switch."""
    window(s, x + 12, y + 20, 164, 96)
    # replace the title bar with a tab strip
    panel(s, x + 13, y + 21, 162, 26, LIGHT_GREY, colour=LIGHT_GREY)
    tab(s, x + 20, y + 24, 54, 24, "map", active=True)
    tab(s, x + 78, y + 24, 54, 24, "table")
    s.text(x + 150, y + 41, "+", size=15, colour=DIM)
    # the page: the selected map region + a persistent section chip
    s.poly(
        [(x + 26, y + 90), (x + 44, y + 62), (x + 66, y + 70), (x + 60, y + 96)],
        fill=GOLD,
        amount=0.5,
    )
    pin(s, x + 46, y + 74)
    fchip(s, x + 84, y + 62, "section", VIOLET, size=11)
    s.text(x + 130, y + 100, "kept", size=10.5, colour=DIM, anchor="start")
    # a closed tab, with the cross
    panel(s, x + 108, y + 2, 66, 18, WHITE, colour=GREY, dashed=True)
    s.text(x + 116, y + 15, "closed", size=10, anchor="start", colour=GREY)
    s.cross(x + 160, y + 11, size=4.5)


def _home_b(s: Sketch, x: float, y: float, h: float) -> None:
    """localStorage: the Remember switch in Dashboard settings > Filters."""
    window(s, x + 12, y + 20, 164, 108)
    s.text(x + 22, y + 56, "Dashboard settings", size=10, anchor="start", colour=DIM)
    s.text(x + 22, y + 70, "> Filters", size=10, anchor="start", colour=DIM)
    s.line(x + 18, y + 76, x + 170, y + 76, colour=GREY, amount=0.3, passes=1, width=1)
    s.text(x + 22, y + 96, "Remember my", size=11, anchor="start")
    s.text(x + 22, y + 110, "filters", size=11, anchor="start")
    toggle(s, x + 124, y + 88, True, w=40, h=22)
    s.text(x + 144, y + 122, "default ON", size=9, colour=DIM)


def _home_c(s: Sketch, x: float, y: float, h: float) -> None:
    """Server document: a window writing (debounced) into a database."""
    window(s, x + 12, y + 18, 62, 52)
    fchip(s, x + 18, y + 40, "EU", BLUE, size=9, h=16, w=34)
    cylinder(s, x + 128, y + 24, 76, 56, GREEN)
    panel(s, x + 108, y + 44, 40, 24, WHITE, colour=INK)
    s.text(x + 128, y + 59, "doc", size=10.5, weight="bold")
    s.arrow(x + 78, y + 46, x + 86, y + 46)
    clock(s, x + 38, y + 96, 11)
    s.text(x + 56, y + 100, "~800 ms", size=11, anchor="start")
    s.text(x + 56, y + 113, "debounced", size=9.5, anchor="start", colour=DIM)
    # anonymous visitors
    avatar(s, x + 30, y + 150, 12, ghost=True)
    s.cross(x + 30, y + 150, size=7)
    s.text(x + 52, y + 146, "anonymous:", size=11, anchor="start")
    s.text(x + 52, y + 160, "nothing stored", size=11, anchor="start", colour=DIM)


def _home_d(s: Sketch, x: float, y: float, w: float) -> None:
    """Share link: the copy button, and the URL with the fragment highlighted."""
    window(s, x + 12, y + 18, 164, 84)
    s.text(x + 22, y + 54, "Settings > Filters", size=10, anchor="start", colour=DIM)
    panel(s, x + 20, y + 62, 148, 32, GREEN, colour=INK)
    s.text(x + 94, y + 76, "Copy link with", size=10.5, weight="bold")
    s.text(x + 94, y + 89, "current filters", size=10.5, weight="bold")
    # URL bar with the fragment in gold
    bx, by, bw = x + 12, y + 118, w - 24
    panel(s, bx, by, bw, 28, LIGHT_GREY, colour=GREY)
    prefix = "app/dashboard/6a1f"
    frag = "#filters=2;<index>:<dc_id>:<type>:<column>:<value>"
    cw = 6.7
    fx = bx + 10 + len(prefix) * cw
    panel(s, fx - 3, by + 4, len(frag) * cw + 6, 20, GOLD, colour=GOLD)
    s.text(bx + 10, by + 19, f"`{prefix}`", size=11.5, anchor="start", colour=DIM)
    s.text(fx, by + 19, f"`{frag}`", size=11.5, anchor="start")
    s.arrow(x + 94, y + 102, x + 94, by - 3)


def build_one_array() -> Sketch:
    s = Sketch(ARRAY_W, ARRAY_H, seed=967)
    s.heading(
        40,
        52,
        "Every filter level, one array, four places it can live",
        "whatever you filter by ends up in the same InteractiveFilter[]: "
        "keep that one array and the whole view comes back",
    )
    s.text(CARD_X, 112, "five ways to filter", size=13, anchor="start", colour=GREY)
    s.text(500, 112, "one array", size=13, anchor="start", colour=GREY)
    s.text(
        810, 112, "four places it can live, and for how long", size=13, anchor="start", colour=GREY
    )

    # -- the five levels -----------------------------------------------------
    level_cy = []
    for i, (fill, mock, title, lines) in enumerate(LEVELS):
        y = TOP + i * (CARD_H + CARD_GAP)
        panel(s, CARD_X, y, CARD_W, CARD_H, fill)
        mock(s, CARD_X + 12, y + 17)
        s.text(CARD_X + 166, y + 52, title, size=15, weight="bold", anchor="start")
        for j, line in enumerate(lines):
            s.text(CARD_X + 166, y + 76 + j * 18, line, size=12, colour=DIM, anchor="start")
        level_cy.append(y + CARD_H / 2)

    # -- the array -----------------------------------------------------------
    ax, aw = 500, 200
    s.text(ax + aw / 2, 400, "InteractiveFilter[]", size=20, weight="bold")
    s.text(ax + aw / 2, 420, "in the viewer's App state", size=12, colour=DIM)
    top, step = 438, 36
    bot = top + 5 * step + 8
    for bx, sign in ((ax - 6, 1), (ax + aw + 6, -1)):
        s.line(bx, top, bx, bot, width=2.6, amount=1.0)
        s.line(bx, top, bx + sign * 12, top, width=2.6, amount=0.6, passes=1)
        s.line(bx, bot, bx + sign * 12, bot, width=2.6, amount=0.6, passes=1)
    chip_cy = []
    for i, label in enumerate(CHIPS):
        cy = top + 22 + i * step
        pill(s, ax + 12, cy - 15, aw - 24, label, LEVELS[i][0], h=30, size=12)
        chip_cy.append(cy)
    s.text(ax + aw / 2, bot + 28, "merged per (index, source):", size=12, colour=DIM)
    s.text(ax + aw / 2, bot + 46, "a chart pick and a slider", size=12, colour=DIM)
    s.text(ax + aw / 2, bot + 64, "coexist, nothing overwritten", size=12, colour=DIM)
    for cy_l, cy_c in zip(level_cy, chip_cy):
        s.arrow(CARD_X + CARD_W + 4, cy_l, ax - 8, cy_c)

    # -- the four homes ------------------------------------------------------
    hx, hw = 810, 500
    homes = (
        (130, 150, VIOLET),
        (294, 150, BLUE),
        (458, 196, GREEN),
        (668, 214, YELLOW),
    )
    homes_cy = []
    for (hy, hh, fill), mock in zip(homes, (_home_a, _home_b, _home_c, _home_d)):
        panel(s, hx, hy, hw, hh, fill)
        if mock is _home_d:
            mock(s, hx, hy, hw)
        else:
            mock(s, hx, hy, hh)
        homes_cy.append(hy + hh / 2)
    tx = hx + 192
    gap = 100

    # a. sessionStorage
    hy = 130
    s.text(tx, hy + 28, "sessionStorage", size=15, weight="bold", anchor="start")
    pill(
        s, hx + hw - 118, hy + 10, 106, "already on main", ORANGE, h=20, size=10.5, line=ORANGE_INK
    )
    s.text(
        tx, hy + 52, "cross-tab: the floating map's selection", size=12, colour=DIM, anchor="start"
    )
    s.text(tx, hy + 70, "and the persistent filter sections", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 94, "lives as long as the browser tab", size=12, colour=INK, anchor="start")
    lifetime(
        s, tx, hy + 126,
        (("tab switch", True), ("tab closed", False), ("other device", False)),
        gap=gap,
    )  # fmt: skip

    # b. localStorage
    hy = 294
    s.text(tx, hy + 28, "localStorage · per dashboard", size=15, weight="bold", anchor="start")
    s.text(tx, hy + 52, '"Remember my filters", on by default', size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 70, "written on every change, so it", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 88, "restores instantly on the next visit", size=12, colour=INK, anchor="start")
    lifetime(
        s, tx, hy + 126,
        (("tab switch", True), ("tab closed", True), ("other device", False)),
        gap=gap,
    )  # fmt: skip

    # c. server document
    hy = 458
    s.text(tx, hy + 28, "server · one doc per user", size=15, weight="bold", anchor="start")
    s.text(tx, hy + 52, "`dashboard_filter_states`", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 70, "one document per user + dashboard,", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 88, "written debounced (~800 ms)", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 116, "follows you to another browser", size=12, colour=INK, anchor="start")
    s.text(tx, hy + 134, "or device when you sign in", size=12, colour=INK, anchor="start")
    lifetime(
        s, tx, hy + 168,
        (("tab switch", True), ("tab closed", True), ("other device", True)),
        gap=gap,
    )  # fmt: skip

    # d. share link
    hy = 668
    s.text(tx, hy + 28, "share link · `#filters=`", size=15, weight="bold", anchor="start")
    s.text(tx, hy + 52, "the array, one readable line per", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 70, "component, travels in the address", size=12, colour=DIM, anchor="start")
    s.text(tx, hy + 88, "of the page, not in any storage", size=12, colour=DIM, anchor="start")
    lifetime(
        s, hx + 14, hy + 168,
        (("read once on load", True), ("then stripped from the URL", True)),
        gap=170,
    )  # fmt: skip
    mark(s, hx + 14 + 8, hy + 192, False)
    s.text(
        hx + 14 + 22,
        hy + 196,
        "over 8000 characters: refuses to become a link",
        size=11.5,
        anchor="start",
        colour=DIM,
    )

    # arrows array -> homes
    for i, cy in enumerate(homes_cy):
        s.arrow(ax + aw + 14, 500 + (i - 1.5) * 24, hx - 6, cy)

    s.text(
        40,
        ARRAY_H - 36,
        "Same InteractiveFilter[] everywhere: whichever copy is read back, the view is rebuilt from it.",
        size=15,
        anchor="start",
        colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 2. Opening a dashboard: who wins.
# --------------------------------------------------------------------------

MERGE_W, MERGE_H = 1350, 1190


def _step(s: Sketch, y: float, n: str, title: str, sub: str) -> None:
    circle(s, 70, y + 22, 16, GOLD)
    s.text(70, y + 28, n, size=17, weight="bold")
    s.text(98, y + 29, title, size=19, weight="bold", anchor="start")
    s.text(98, y + 52, sub, size=13, colour=DIM, anchor="start")


def _source(s: Sketch, y: float, fill: str, title: str, sub: str, glyph: str) -> None:
    x = 100
    panel(s, x, y, 290, 62, fill)
    gx, gy = x + 28, y + 31
    if glyph == "toggle":
        toggle(s, gx - 18, gy - 9, True, w=36, h=18)
    elif glyph == "tab":
        tab(s, gx - 20, gy - 12, 40, 24, "tab")
    else:
        link_glyph(s, gx, gy, 9)
    s.text(x + 62, y + 27, title, size=14, weight="bold", anchor="start")
    s.text(x + 62, y + 46, sub, size=11.5, colour=DIM, anchor="start")


def _merged_row(s: Sketch, x: float, y: float, key: str, kind: str) -> None:
    s.text(x, y + 18, f"`{key}`", size=12.5, anchor="start")
    cx = x + 104
    if kind == "link":
        fchip(s, cx, y, "setosa", BLUE, size=11, close=False, dashed=True, colour=GREY)
        s.line(cx + 6, y + 11, cx + 66, y + 11, colour=RED, width=1.5, amount=0.3, passes=1)
        s.arrow(cx + 74, y + 11, cx + 104, y + 11)
        fchip(s, cx + 110, y, "virginica", YELLOW, close=False)
        s.text(cx + 214, y + 16, "the link wins", size=12, colour=DIM, anchor="start")
    elif kind == "local":
        fchip(s, cx, y, "2019 - 2021", BLUE, close=False)
        s.text(cx + 214, y + 16, "link is silent: kept", size=12, colour=DIM, anchor="start")
    else:
        fchip(s, cx, y, "DE, FR", VIOLET, close=False)
        s.text(cx + 214, y + 16, "from the tab switch", size=12, colour=DIM, anchor="start")


def _result_window(s: Sketch, x: float, y: float) -> None:
    window(s, x, y, 250, 166, "app/dashboard/6a1f")
    fchip(s, x + 12, y + 30, "species: virginica", YELLOW, size=10.5, h=20)
    bars(s, x + 18, y + 64, 150, 82, (0.8, 0.45, 0.65, 0.3))
    s.text(x + 205, y + 98, "50 rows", size=10.5, colour=DIM)
    s.text(x + 205, y + 112, "fetched", size=10.5, colour=DIM)


def _gate(s: Sketch, x: float, y: float, kind: str, lines: tuple[str, ...]) -> None:
    w, h = 188, 132
    panel(s, x, y, w, h, WHITE)
    cx, cy = x + w / 2, y + 30
    if kind == "exists":
        toggle(s, cx - 38, cy - 11, True, w=40, h=22)
        panel(s, cx + 8, cy - 12, 26, 24, GREEN, colour=INK)
        tick(s, cx + 21, cy, size=5)
    elif kind == "newer":
        clock(s, cx - 24, cy, 12)
        s.text(cx - 2, cy + 5, "<", size=17, colour=DIM)
        clock(s, cx + 26, cy, 12)
        s.text(cx - 24, cy + 28, "local", size=9.5, colour=DIM)
        s.text(cx + 26, cy + 28, "server", size=9.5, colour=DIM)
    elif kind == "link":
        link_glyph(s, cx, cy, 11)
        s.cross(cx + 4, cy + 1, size=15)
    else:
        cursor(s, cx - 6, cy - 12)
        s.cross(cx + 18, cy - 2, size=9)
    for i, line in enumerate(lines):
        s.text(cx, y + 78 + i * 17, line, size=12, colour=INK if i == 0 else DIM)


def build_mount_merge() -> Sketch:
    s = Sketch(MERGE_W, MERGE_H, seed=967)
    s.heading(
        40,
        52,
        "Opening a dashboard: who wins",
        "three sources are merged before the first fetch; the server copy comes later "
        "and only if nothing else got there first",
    )

    # ---- step 1 -------------------------------------------------------------
    panel(s, 40, 100, 1270, 350, WHITE, colour=GREY, dashed=True)
    _step(s, 112, "1", "Synchronous, inside the first render",
          "so the very first data fetch is already filtered, never once unfiltered and then again")  # fmt: skip
    _source(s, 196, BLUE, "remembered state", "localStorage, if Remember is on", "toggle")
    _source(s, 272, VIOLET, "cross-tab selection", "sessionStorage, tab switch", "tab")
    _source(s, 348, YELLOW, "`#filters=` link", "a share link being opened", "link")
    s.arrow(66, 200, 66, 404)
    s.text_rotated(52, 304, "ascending priority", rotate=-90, size=12)

    s.arrow(402, 300, 448, 300)
    px, py, pw, ph = 456, 190, 520, 232
    panel(s, px, py, pw, ph, WHITE)
    s.text(
        px + 16, py + 28, "merged per (index, source) key", size=14.5, weight="bold", anchor="start"
    )
    s.text(px + pw - 14, py + 28, "InteractiveFilter[]", size=11, colour=GREY, anchor="end")
    for i, kind in enumerate(("link", "local", "tab")):
        key = ("species", "year", "map")[i]
        _merged_row(s, px + 16, py + 54 + i * 48, key, kind)
    s.line(px + 12, py + 200, px + pw - 12, py + 200, colour=GREY, amount=0.3, passes=1, width=1)
    s.text(
        px + 16,
        py + 220,
        "the link overrides only what it mentions",
        size=12,
        colour=DIM,
        anchor="start",
    )
    s.arrow(984, 300, 1030, 300)

    _result_window(s, 1038, 190)
    s.text(1163, 378, "first fetch: already filtered", size=13, weight="bold")
    s.cross(1052, 410, size=7)
    s.text(1068, 414, "no flash of unfiltered data", size=12, colour=DIM, anchor="start")

    # ---- step 2 -------------------------------------------------------------
    panel(s, 40, 470, 1270, 214, WHITE, colour=GREY, dashed=True)
    _step(s, 482, "2", "Pruned once the dashboard family is known",
          "a restored filter must still point at something that exists")  # fmt: skip
    ax, ay = 60, 552
    panel(s, ax, ay, 560, 112, VIOLET)
    window(s, ax + 14, ay + 14, 120, 84)
    pin(s, ax + 40, ay + 56)
    fchip(s, ax + 62, ay + 40, "map", WHITE, size=10, h=18, w=44, close=False)
    fchip(s, ax + 62, ay + 66, "section", WHITE, size=10, h=18, w=60, close=False)
    tick(s, ax + 112, ay + 49, size=4)
    tick(s, ax + 112, ay + 75, size=4)
    s.text(ax + 156, ay + 38, "cross-tab entries", size=14.5, weight="bold", anchor="start")
    s.text(
        ax + 156,
        ay + 62,
        "validated against the floating maps",
        size=12,
        colour=DIM,
        anchor="start",
    )
    s.text(
        ax + 156, ay + 80, "and persistent sections that exist", size=12, colour=DIM, anchor="start"
    )

    bx = 650
    panel(s, bx, ay, 660, 112, BLUE)
    s.thumbnail(
        bx + 16,
        ay + 14,
        150,
        84,
        tiles=((0.06, 0.1, 0.42, 0.5), (0.54, 0.1, 0.4, 0.5)),
        fill=BLUE_INK,
    )
    s._parts.append(
        f'<rect x="{bx + 16 + 150 * 0.06:.1f}" y="{ay + 14 + 84 * 0.66:.1f}" width="{150 * 0.88:.1f}" '
        f'height="{84 * 0.26:.1f}" rx="3" fill="{WHITE}" stroke="{RED}" stroke-width="1.4" '
        f'stroke-dasharray="4 3"/>'
    )
    s.cross(bx + 16 + 30, ay + 14 + 84 * 0.79, size=6)
    s.text(
        bx + 16 + 52, ay + 14 + 84 * 0.79 + 4, "deleted tile", size=10.5, colour=DIM, anchor="start"
    )
    s.text(
        bx + 190,
        ay + 38,
        "restored entries (local + link)",
        size=14.5,
        weight="bold",
        anchor="start",
    )
    s.text(
        bx + 190,
        ay + 62,
        "dropped when their component is gone from",
        size=12,
        colour=DIM,
        anchor="start",
    )
    s.text(
        bx + 190,
        ay + 80,
        "the dashboard family: stale storage, a deleted tile",
        size=12,
        colour=DIM,
        anchor="start",
    )

    # ---- step 3 -------------------------------------------------------------
    panel(s, 40, 704, 1270, 306, WHITE, colour=GREY, dashed=True)
    _step(s, 716, "3", "Asynchronous: the per-user server copy",
          "never blocks the first paint; applied only when all four gates pass")  # fmt: skip
    cylinder(s, 112, 800, 76, 62, GREEN)
    s.text(112, 888, "server copy", size=13, weight="bold")
    s.text(112, 906, "one doc per user", size=11, colour=DIM)
    s.text(112, 920, "+ dashboard", size=11, colour=DIM)
    gates = (
        ("exists", ("it exists and", "Remember is on")),
        ("newer", ("newer than the", "local copy, read before", "this load's writes")),
        ("link", ("no share link was", "used in this load")),
        ("touched", ("the viewer has not", "touched a filter yet")),
    )
    gx0, gstep = 228, 214
    s.arrow(152, 835, gx0 - 8, 835)
    for i, (kind, lines) in enumerate(gates):
        gx = gx0 + i * gstep
        _gate(s, gx, 774, kind, lines)
        if i < len(gates) - 1:
            s.arrow(gx + 190, 835, gx + gstep - 4, 835)
        # a failed gate: drop out of the corridor
        s.arrow(gx + 94, 908, gx + 94, 934, dashed=True, colour=RED)
    s.arrow(gx0 + 3 * gstep + 190, 835, 1100, 835)
    window(s, 1104, 774, 190, 112)
    fchip(s, 1114, 802, "species: virginica", YELLOW, size=10, h=20)
    bars(s, 1124, 836, 100, 38, (0.8, 0.5, 0.65))
    s.text(1199, 906, "applied: merged and", size=11.5, colour=DIM)
    s.text(1199, 922, "sanitised", size=11.5, colour=DIM)
    panel(s, gx0, 938, 3 * gstep + 188, 28, PINK, colour=RED, dashed=True)
    s.text(gx0 + (3 * gstep + 188) / 2, 957, "a gate fails: the copy is simply not applied, the viewer keeps what they see", size=12.5)  # fmt: skip
    # adopted preference
    toggle(s, 100, 975, False, w=36, h=18)
    s.text(150, 989, "Remember switched off in another browser? That preference is adopted here.", size=12.5, anchor="start", colour=DIM)  # fmt: skip

    # ---- the two exclusions -----------------------------------------------
    s.text(40, 1050, "and two cases that restore nothing", size=19, anchor="start")
    # a. version preview
    panel(s, 40, 1068, 620, 100, WHITE, colour=GREY, dashed=True)
    window(s, 56, 1082, 200, 72, "app/dashboard/6a1f?version=3")
    eye(s, 156, 1130)
    s.text(280, 1100, "`?version=` time-travel preview", size=14.5, weight="bold", anchor="start")
    s.text(280, 1122, "a read-only look at a past version:", size=12, colour=DIM, anchor="start")
    s.text(
        280, 1140, "it neither restores nor remembers filters", size=12, colour=DIM, anchor="start"
    )
    s.cross(612, 1118, size=13)
    # b. reset all
    panel(s, 690, 1068, 620, 100, WHITE, colour=GREY, dashed=True)
    panel(s, 708, 1098, 92, 34, PINK, colour=RED)
    s.text(754, 1120, "Reset all", size=13.5, weight="bold")
    s.arrow(806, 1115, 850, 1115)
    cylinder(s, 886, 1090, 50, 40, LIGHT_GREY)
    s.line(870, 1116, 902, 1116, colour=GREY, amount=0.3, passes=1, width=1)
    s.text(950, 1100, "clears the stored copy", size=14.5, weight="bold", anchor="start")
    s.text(950, 1122, "and returns to the declared", size=12, colour=DIM, anchor="start")
    s.text(950, 1140, "default values", size=12, colour=DIM, anchor="start")
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/filter_persistence"),
        "--out",
        help="Output prefix; '_<name>.svg' is appended.",
    ),
) -> None:
    """Write the two filter-persistence schemas (SVG only) under --out."""
    write(build_one_array(), out, "one_array", png=False)
    write(build_mount_merge(), out, "mount_merge", png=False)


if __name__ == "__main__":
    app()
