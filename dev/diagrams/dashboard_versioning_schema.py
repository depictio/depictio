#!/usr/bin/env python3
"""Render the dashboard-versioning schemas as hand-drawn SVGs (+ PNGs).

Two diagrams, because the feature has two questions worth a picture:

* *capture*: why a hundred autosaves do not become a hundred timeline entries,
  and which saves leave no entry at all;
* *restore*: why putting a past version back cannot lose the present, and which
  fields deliberately never come from the snapshot.

Both draw the thing itself (a time axis with every save on it, a ledger as a
line of dots, dashboards as tile grids) rather than boxes joined by arrows. The
capture session is not hand-placed: ``simulate()`` replays it through the same
rules as ``versioning.capture_dashboard_version`` (anchored window, same-hash
no-op, explicit never folds, pin seals), so the bands and counts drawn are the
ones the rules produce.

Generated rather than drawn, so a change in the flow shows up as a diff. The
look and the primitives live in ``sketch.py``, and the seed is fixed so
re-running produces byte-identical SVGs.

Usage:
    python dev/diagrams/dashboard_versioning_schema.py --out docs/images/v0.12/react/schema
    # writes <out>_version_capture.{svg,png} and <out>_version_restore.{svg,png}
    # add --quantize to shrink the PNGs (ImageMagick, 256 colours)
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    BLUE_INK,
    DIM,
    GREEN,
    GREEN_INK,
    GREY,
    INK,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    write,
)

app = typer.Typer(add_completion=False)

#: ``settings.dashboard_versions`` defaults, restated here because a diagram
#: should not import the API. ``coalesce_window_seconds`` / ``max_versions_per_family``
#: / ``keep_daily_for_days`` / ``retention_days``.
WINDOW_MIN = 5
MAX_AUTOSAVES = 100
DAILY_AFTER_DAYS = 30
RETAIN_DAYS = 90


# ── the rules, replayed ─────────────────────────────────────────────────────


@dataclass
class Version:
    name: str
    kind: str
    opened: float
    until: float
    last: float
    saves: int = 1
    pinned: bool = False
    pinned_at: float | None = None
    marks: list[tuple[float, bool]] = field(default_factory=list)  # (minute, changed)


def simulate(
    events: list[tuple[float, str]],
    window: float = WINDOW_MIN,
    *,
    sliding: bool = False,
    first: int = 1,
) -> list[Version]:
    """Replay saves through ``capture_dashboard_version``.

    Events are ``(minute, what)`` with ``what`` in ``auto`` (changed content),
    ``same`` (autosave, identical hash), ``explicit`` and ``pin`` (pins the
    latest version). Mirrors ``versioning.py``: an unchanged autosave only
    touches the latest version's count; a changed one folds only into an
    unpinned autosave whose window is still open; an explicit save always opens
    its own entry. ``sliding`` is the rejected design, where every fold pushes
    the window end out.
    """
    versions: list[Version] = []
    for minute, what in events:
        latest = versions[-1] if versions else None
        if what == "pin":
            assert latest is not None
            latest.pinned = True
            latest.pinned_at = minute
            latest.until = latest.opened
            continue
        if what == "same":
            assert latest is not None
            latest.saves += 1
            latest.marks.append((minute, False))
            continue
        folds = (
            what == "auto"
            and latest is not None
            and latest.kind == "auto"
            and not latest.pinned
            and minute <= latest.until
        )
        if folds:
            assert latest is not None
            latest.saves += 1
            latest.last = minute
            latest.marks.append((minute, True))
            if sliding:
                latest.until = minute + window
        else:
            version = Version(
                name=f"v{first + len(versions)}",
                kind="explicit" if what == "explicit" else "auto",
                opened=minute,
                until=minute + window,
                last=minute,
            )
            version.marks.append((minute, True))
            versions.append(version)
    return versions


# ── diagram 1: how saves become (or do not become) versions ─────────────────

CAPTURE_W, CAPTURE_H = 1420, 1470

#: One editing session, minutes after 09:00. ``same`` is a save whose content
#: hash equals the latest version's (the screenshot task's ``last_saved_ts``
#: rewrite is the usual case).
SESSION: list[tuple[float, str]] = [
    (2, "auto"),
    (3, "auto"),
    (4, "auto"),
    (4.6, "same"),
    (6, "auto"),
    # 09:07 the window lapses, the next autosave opens a version
    (9, "auto"),
    (10, "auto"),
    (11, "auto"),
    (12, "auto"),
    (13, "auto"),
    (18, "explicit"),  # the Save button
    (24, "auto"),
    (25, "auto"),
    (26, "pin"),  # pinned and named while its window is still open
    (27, "auto"),  # would have folded into the pinned one, opens a new entry
    (28, "auto"),
    (29, "auto"),
    (31, "auto"),
    (37, "auto"),
    (38, "auto"),
    (39.5, "same"),
    (41, "auto"),
]


def _numbered(s: Sketch, x: float, y: float, n: int) -> None:
    """A circled number that points at a spot and matches a note below."""
    s.dot(x, y, 10, fill=WHITE)
    s.text(x, y + 4.5, str(n), size=13, weight="bold")


def _wrapped(
    s: Sketch, x: float, y: float, content: str, width: int, *, size: float = 13.5, gap: float = 18
) -> float:
    lines = textwrap.wrap(content, width)
    for i, line in enumerate(lines):
        s.text(x, y + i * gap, line, size=size, colour=DIM, anchor="start")
    return y + len(lines) * gap


def build_capture() -> Sketch:
    s = Sketch(CAPTURE_W, CAPTURE_H, seed=19)
    s.heading(
        46,
        52,
        "One editing session, a readable timeline",
        "the editor saves on every drag; the window, the hash and the pin decide what the timeline keeps",
    )

    # -- legend -----------------------------------------------------------
    ly = 128
    s.dot(56, ly - 5, 7, fill=BLUE_INK)
    s.text(72, ly, "opens a version", size=13.5, anchor="start")
    s.dot(214, ly - 5, 4.5, fill=BLUE_INK)
    s.text(226, ly, "folded into it", size=13.5, anchor="start")
    s.dot(352, ly - 5, 5, colour=GREY, dashed=True)
    s.text(364, ly, "same hash, no new entry", size=13.5, anchor="start")
    s.diamond(574, ly - 5, 8)
    s.text(588, ly, "explicit Save", size=13.5, anchor="start")
    s.lock(714, ly - 6, 9)
    s.text(728, ly, "pinned or named", size=13.5, anchor="start")
    s.shade(872, ly - 17, 34, 20, fill=BLUE, opacity=0.9, colour=DIM)
    s.text(914, ly, "window: 5 min from the version's creation", size=13.5, anchor="start")

    # -- the session axis -------------------------------------------------
    x0, px = 90.0, 27.5

    def mx(minute: float) -> float:
        return x0 + minute * px

    axis_y, band_top, dot_y = 340.0, 214.0, 300.0
    versions = simulate(SESSION, first=7)

    # Bands first, so ticks and dots sit on top of them.
    for v in versions:
        if v.kind != "auto":
            continue
        end = v.pinned_at if v.pinned_at is not None else v.until
        fill = VIOLET if v.pinned else BLUE
        s.shade(
            mx(v.opened),
            band_top,
            (end - v.opened) * px,
            axis_y - band_top,
            fill=fill,
            opacity=0.9,
            colour=DIM,
        )

    # Band labels, all above their band, with the numbers the notes refer to.
    for v in versions:
        if v.kind == "auto":
            span = round(v.last - v.opened)
            if v.pinned:
                label = f"{v.name}"
            else:
                label = f"{v.name} · {v.saves} saves over {span} min"
            s.text(mx(v.opened), band_top - 10, label, size=14, anchor="start", weight="bold")
        else:
            s.text(
                mx(v.opened),
                band_top - 10,
                f"{v.name} · Save",
                size=14,
                anchor="middle",
                weight="bold",
            )

    s.time_axis(
        x0,
        mx(45),
        axis_y,
        ticks=tuple((mx(m), f"09:{m:02d}") for m in range(0, 46, 5)),
    )

    # Every save: a stem from the axis and a head. Opening saves are larger.
    for v in versions:
        for minute, changed in v.marks:
            cx = mx(minute)
            opener = minute == v.opened
            if not changed:
                s.line(cx, axis_y - 3, cx, dot_y + 5, colour=GREY, amount=0.3, width=1.2, passes=1)
                s.dot(cx, dot_y, 5, colour=GREY, dashed=True)
            elif v.kind == "explicit":
                s.line(cx, axis_y - 3, cx, dot_y + 8, colour=DIM, amount=0.3, width=1.2, passes=1)
                s.diamond(cx, dot_y, 9)
            else:
                s.line(cx, axis_y - 3, cx, dot_y + 4, colour=DIM, amount=0.3, width=1.2, passes=1)
                s.dot(cx, dot_y, 7 if opener else 4.5, fill=BLUE_INK)

    # Window lapse: a small tick where an unpinned band ends.
    for v in versions:
        if v.kind == "auto" and not v.pinned:
            s.text(mx(v.until) - 6, band_top + 20, "lapses", size=11.5, colour=DIM, anchor="end")

    pinned = next(v for v in versions if v.pinned)
    assert pinned.pinned_at is not None
    s.lock(mx(pinned.pinned_at), dot_y - 3, 10)

    # Numbered pointers.
    v7, v8 = versions[0], versions[1]
    _numbered(s, (mx(v7.until) + mx(v8.opened)) / 2, dot_y - 4, 1)
    _numbered(s, mx(4.6), dot_y - 32, 2)
    explicit = next(v for v in versions if v.kind == "explicit")
    _numbered(s, mx(explicit.opened), dot_y - 34, 3)
    _numbered(s, mx(pinned.pinned_at) + 14, dot_y - 40, 4)

    # -- the timeline rows, as the UI lists them ---------------------------
    s.text(46, 545, "what the timeline lists", size=17, anchor="start", weight="bold")
    s.text(46, 568, "one row per version,", size=13.5, colour=DIM, anchor="start")
    s.text(46, 588, "placed where it was created", size=13.5, colour=DIM, anchor="start")
    for v in versions:
        cx = mx(v.opened)
        lane2 = v.pinned
        top = 520 if lane2 else 418
        w, h = 132, 66
        fill = YELLOW if v.kind == "explicit" else VIOLET if v.pinned else BLUE
        s.line(
            cx, axis_y + 36, cx, top - 2, colour=DIM, amount=0.8, width=1.2, dashed=True, passes=1
        )
        s.rect(Box(cx - w / 2, top, w, h, fill, ""))
        s.text(cx, top + 25, f"{v.name} · {v.kind}", size=16, weight="bold")
        count = f"{v.saves} save" + ("s" if v.saves != 1 else "")
        s.text(cx, top + 48, count + (", pinned" if v.pinned else ""), size=13.5, colour=DIM)
        if v.pinned:
            s.lock(cx + w / 2 - 14, top + 14, 8)

    # -- notes ---------------------------------------------------------------
    notes = [
        (
            1,
            "The window is anchored: it lapses 5 min after the version was created, however busy "
            "you stay. The next autosave opens v8.",
        ),
        (
            2,
            "Same hash as the latest version: no new entry, only its save count moves. "
            "`last_saved_ts` never counts as a change.",
        ),
        (
            3,
            "The Save button is explicit: it always opens its own entry, never folds, and is "
            "kept the full 90 days.",
        ),
        (
            4,
            "Pinning seals a version. The next autosave opens a new entry instead of folding "
            "into (and rewriting) the one you chose to keep.",
        ),
    ]
    for i, (n, text) in enumerate(notes):
        nx = 46 + i * 345
        _numbered(s, nx + 10, 628, n)
        _wrapped(s, nx + 28, 633, text, 40, size=13)

    # -- panel: anchored vs sliding ----------------------------------------
    py = 745
    s.text(
        46, py, "why the window is anchored, not sliding", size=19, anchor="start", weight="bold"
    )
    s.text(
        46,
        py + 24,
        "the same 25 saves, one every 48 seconds for 20 minutes",
        size=13.5,
        colour=DIM,
        anchor="start",
    )
    saves = [(round(0.4 + 0.8 * i, 1), "auto") for i in range(25)]
    ax0, apx = 150.0, 18.0

    def ax(minute: float) -> float:
        return ax0 + minute * apx

    def strip(y: float, versions_: list[Version], fill: str, cap_fill: str) -> None:
        for v in versions_:
            s.shade(
                ax(v.opened),
                y - 36,
                (v.until - v.opened) * apx,
                60,
                fill=fill,
                opacity=0.9,
                colour=DIM,
            )
        for v in versions_:
            for minute, _ in v.marks:
                s.dot(ax(minute), y, 3.5, fill=BLUE_INK)

    sliding = simulate(saves, sliding=True)
    anchored = simulate(saves)
    sy, ay = py + 100, py + 214
    s.text(46, sy + 4, "sliding", size=16, anchor="start", weight="bold")
    strip(sy, sliding, PINK, PINK)
    sv = sliding[0]
    s.text(
        ax(sv.opened) + 6,
        sy - 44,
        f"{sv.name} · {sv.saves} saves over {round(sv.last)} min",
        size=13.5,
        anchor="start",
        weight="bold",
    )
    s.text(
        ax(0.4),
        sy + 46,
        "every save pushes the end of the window out, so it never lapses",
        size=12.5,
        colour=RED,
        anchor="start",
    )
    s.text(46, ay + 4, "anchored", size=16, anchor="start", weight="bold")
    strip(ay, anchored, BLUE, BLUE)
    for v in anchored:
        s.text(
            ax(v.opened) + 4,
            ay - 44,
            f"{v.name} · {v.saves}",
            size=13.5,
            anchor="start",
            weight="bold",
        )
    s.text(
        ax(0.4),
        ay + 46,
        f"each window lapses 5 min after it opened: {len(anchored)} steps",
        size=12.5,
        colour=DIM,
        anchor="start",
    )
    s.time_axis(
        ax0,
        ax(25),
        ay + 70,
        ticks=tuple((ax(m), f"{m} min") for m in (0, 5, 10, 15, 20, 25)),
        size=11,
    )
    s.text(ax(25) + 34, sy + 4, "1 entry", size=14, colour=RED, anchor="start", weight="bold")
    s.cross(ax(25) + 34 + 62, sy, size=8)
    s.text(ax(25) + 34, sy + 24, "nothing to step", size=12.5, colour=RED, anchor="start")
    s.text(ax(25) + 34, sy + 42, "back through", size=12.5, colour=RED, anchor="start")
    s.text(ax(25) + 34, ay + 4, f"{len(anchored)} entries", size=14, anchor="start", weight="bold")
    s.text(ax(25) + 34, ay + 24, "each a state", size=12.5, colour=DIM, anchor="start")
    s.text(ax(25) + 34, ay + 42, "to return to", size=12.5, colour=DIM, anchor="start")

    # -- panel: the tab family ----------------------------------------------
    fx = 748
    s.text(fx, py, "a version covers the whole tab family", size=19, anchor="start", weight="bold")
    s.text(
        fx,
        py + 24,
        "main tab and child tabs are hashed together into one snapshot",
        size=13.5,
        colour=DIM,
        anchor="start",
    )
    layouts = (
        ((0.05, 0.08, 0.42, 0.32), (0.53, 0.08, 0.42, 0.32), (0.05, 0.48, 0.9, 0.44)),
        (
            (0.05, 0.08, 0.28, 0.4),
            (0.37, 0.08, 0.28, 0.4),
            (0.69, 0.08, 0.26, 0.4),
            (0.05, 0.56, 0.9, 0.36),
        ),
        ((0.05, 0.08, 0.9, 0.5), (0.05, 0.66, 0.9, 0.26)),
        ((0.05, 0.08, 0.55, 0.84), (0.66, 0.08, 0.29, 0.84)),
    )
    tw, th, gap = 100, 70, 24
    row1 = py + 70
    s.frame(
        fx - 14, row1 - 12, 3 * tw + 2 * gap + 28, th + 52, fill=WHITE, colour=GREY, dashed=True
    )
    for i, name in enumerate(("main tab", "child tab", "child tab")):
        tx = fx + i * (tw + gap)
        s.thumbnail(tx, row1, tw, th, tiles=layouts[i], fill=BLUE_INK)
        s.text(tx + tw / 2, row1 + th + 20, name, size=12.5, colour=DIM)
    box1 = Box(
        fx + 3 * (tw + gap) + 18,
        row1 - 12,
        238,
        th + 52,
        YELLOW,
        "one snapshot",
        ("sha256 over all 3 tabs", "ignores `last_saved_ts`", "and the dead Dash fields"),
    )
    s.box(box1)
    s.arrow(fx + 3 * tw + 2 * gap + 18, row1 + th / 2, box1.x - 8, row1 + th / 2)

    row2 = row1 + 140
    s.frame(fx - 14, row2 - 12, 4 * 82 + 3 * 18 + 28, th + 52, fill=WHITE, colour=GREY, dashed=True)
    tw2 = 82
    for i in range(4):
        tx = fx + i * (tw2 + 18)
        s.thumbnail(tx, row2, tw2, th, tiles=layouts[i], fill=GREEN_INK if i == 3 else BLUE_INK)
    s.text(fx + 3 * (tw2 + 18) + tw2 / 2, row2 + th + 20, "added", size=12.5, colour=DIM)
    box2 = Box(
        fx + 4 * tw2 + 3 * 18 + 18 + 8,
        row2 - 12,
        238,
        th + 52,
        ORANGE,
        "another hash",
        ("a new entry: adding a tab", "is undoable, and so is", "deleting one"),
    )
    s.box(box2)
    s.arrow(fx + 4 * tw2 + 3 * 18 + 14, row2 + th / 2, box2.x - 8, row2 + th / 2)

    # -- retention strip -------------------------------------------------
    ry = 1085
    s.text(
        46,
        ry,
        "retention: what is left as the months go by",
        size=19,
        anchor="start",
        weight="bold",
    )
    s.text(
        46,
        ry + 24,
        "pruned after a capture, once a dashboard holds over 120 versions",
        size=13.5,
        colour=DIM,
        anchor="start",
    )
    rx0, rpx = 170.0, 9.4

    def rx(day: float) -> float:
        return rx0 + day * rpx

    zone_top, zone_h = ry + 48, 214
    s.shade(rx(0), zone_top, 30 * rpx, zone_h, fill=BLUE, opacity=0.9, colour=DIM)
    s.shade(rx(30), zone_top, 60 * rpx, zone_h, fill=YELLOW, opacity=0.9, colour=DIM)
    s.shade(rx(90), zone_top, 30 * rpx, zone_h, fill=PINK, opacity=0.9, colour=DIM, dashed=True)
    s.text(rx(15), zone_top + 24, "the newest 100 autosaves", size=14, weight="bold")
    s.text(
        rx(60), zone_top + 24, "past 30 days: the last autosave of each day", size=14, weight="bold"
    )
    s.text(rx(105), zone_top + 24, "past 90 days: dropped", size=14, weight="bold")

    r1, r2, r3 = zone_top + 70, zone_top + 120, zone_top + 170
    s.text(46, r1 + 4, "autosaves", size=14, anchor="start", weight="bold")
    s.text(46, r2 + 4, "Save, restore,", size=14, anchor="start", weight="bold")
    s.text(46, r2 + 22, "import", size=14, anchor="start", weight="bold")
    s.text(46, r3 + 4, "pinned", size=14, anchor="start", weight="bold")
    for r in (r1, r2, r3):
        s.line(rx(0), r, rx(120), r, colour=GREY, amount=0.8, width=1.1, passes=1)
    # autosaves: dense while recent, one a day past 30, ghosts once dropped
    n = 0
    day = 0.4
    while day < 30:
        s.dot(rx(day), r1, 2.3, fill=BLUE_INK, width=0.8)
        day += 0.8
        n += 1
    for d in range(31, 91):
        s.dot(rx(d), r1, 3.1, fill=BLUE_INK, width=1)
    for d in range(92, 120, 3):
        s.dot(rx(d), r1, 3.4, colour=GREY, dashed=True, width=1)
    # explicit / restore / import: kept whole for the retention window
    for d in (2, 9, 21, 36, 52, 71, 86):
        s.diamond(rx(d), r2, 7)
    s.diamond(rx(97), r2, 7, fill=WHITE, colour=GREY)
    s.diamond(rx(112), r2, 7, fill=WHITE, colour=GREY)
    # pins survive every cut
    for d in (7, 44, 68, 103):
        s.lock(rx(d), r3 - 3, 10)
    s.text(rx(110), r3 + 4, "kept forever", size=13.5, anchor="start", weight="bold")
    s.line(rx(103) + 14, r3, rx(110) - 4, r3, amount=0.4, width=1.2, passes=1)

    s.time_axis(
        rx(0),
        rx(120),
        zone_top + zone_h + 22,
        ticks=tuple((rx(d), "today" if d == 0 else f"{d} d") for d in (0, 30, 60, 90, 120)),
        size=12.5,
    )
    s.text(
        rx(60),
        zone_top + zone_h + 84,
        "autosaves also stop at the 100 most recent, whatever their age",
        size=13,
        colour=DIM,
    )
    return s


# ── diagram 2: restore, and the boundary it does not cross ──────────────────

RESTORE_W, RESTORE_H = 1420, 1330


def build_restore() -> Sketch:
    s = Sketch(RESTORE_W, RESTORE_H, seed=23)
    s.heading(
        46,
        52,
        "Restore puts the past back without losing the present",
        "the present is captured first, only content is written, and access is never taken from a snapshot",
    )

    # -- the ledger, before and after --------------------------------------
    s.text(
        46,
        128,
        "the ledger, before and after restoring v12",
        size=19,
        anchor="start",
        weight="bold",
    )
    sp, lx0 = 125.0, 190.0
    before = (
        ("v10", "auto", "auto"),
        ("v11", "auto", "auto"),
        ("v12", "pinned", "pinned"),
        ("v13", "auto", "auto"),
        ("v14", "auto", "auto"),
        ("v15", "auto", "auto"),
        ("now", "not a version", "ghost"),
    )
    y1 = 205
    s.text(46, y1 + 5, "before", size=17, anchor="start", weight="bold")
    xs = s.ledger_strip(lx0, y1, before, spacing=sp)
    s.text(xs[2], y1 + 68, "“Before the Q3 re-run”", size=13, colour=DIM)

    y2 = 400
    s.text(46, y2 + 5, "after", size=17, anchor="start", weight="bold")
    after = (
        ("v10", "auto", "auto"),
        ("v11", "auto", "auto"),
        ("v12", "pinned", "pinned"),
        ("v13", "auto", "auto"),
        ("v14", "auto", "auto"),
        ("v15", "auto", "auto"),
        ("v16", "explicit", "explicit"),
        ("v17", "restore", "restore"),
        ("v18", "explicit", "ghost"),
        ("v19", "restore", "ghost"),
    )
    xa = s.ledger_strip(lx0, y2, after, spacing=sp)
    s.dot(xa[2], y2, 6, ring=True)
    s.text(xa[2], y2 + 68, "“Before the Q3 re-run”", size=13, colour=DIM)

    s.arrow(xs[2], y1 + 84, xa[2], y2 - 58)
    s.text(xs[2] + 12, y1 + 122, "restore v12", size=15, anchor="start", weight="bold")
    s.text(xs[2] + 12, y1 + 142, "needs editor", size=12.5, colour=DIM, anchor="start")

    # what the new entries are
    s.text(xa[6] + 8, y2 - 104, "1. captures the present", size=14, anchor="end", weight="bold")
    s.text(xa[6] + 8, y2 - 86, "before any write", size=12.5, colour=DIM, anchor="end")
    s.text(xa[7] - 8, y2 - 104, "3. marks the restore", size=14, anchor="start", weight="bold")
    s.text(xa[7] - 8, y2 - 86, "parent is v12", size=12.5, colour=DIM, anchor="start")
    s.arc(xa[7] - 4, y2 - 12, xa[2] + 12, y2 - 12, lift=80, dashed=True, colour=DIM)

    # undo
    s.arc(xa[6], y2 + 92, xa[8], y2 + 92, lift=70, colour=GREEN_INK)
    s.text(
        (xa[6] + xa[8]) / 2, y2 + 150, "restoring v16 undoes the restore", size=14, weight="bold"
    )
    s.text((xa[6] + xa[8]) / 2, y2 + 170, "it holds the present, as it was", size=12.5, colour=DIM)

    # -- the tabs ----------------------------------------------------------
    ty = 620
    s.text(
        46, ty, "2. then each tab is written to match v12", size=19, anchor="start", weight="bold"
    )
    s.text(
        46,
        ty + 24,
        "updates and recreates in snapshot order, deletes last",
        size=13.5,
        colour=DIM,
        anchor="start",
    )

    # the live document layer
    lay = Box(
        210,
        ty + 52,
        700,
        70,
        VIOLET,
        "the live document: permissions · is_public · project_id",
        ("never part of a snapshot",),
    )
    s.rect(lay, dashed=True)
    s.text(lay.cx, lay.y + 27, lay.title, size=17, weight="bold")
    s.text(lay.cx, lay.y + 51, lay.lines[0], size=13.5, colour=DIM)
    s.lock(lay.x + 26, lay.cy, 12)
    s.text(950, lay.y + 24, "TabSnapshot has no field for them,", size=14, anchor="start")
    s.text(950, lay.y + 44, "so a restore cannot re-grant access", size=14, anchor="start")
    s.text(950, lay.y + 64, "that was revoked since", size=14, anchor="start")

    cols = (210.0, 460.0, 710.0)
    cw, ch = 170.0, 86.0
    hy = lay.bottom + 86
    for cx, head in zip(cols, ("live now", "v12 snapshot", "after the restore")):
        s.text(cx + cw / 2, hy, head, size=16, weight="bold")
    s.line(cols[1] + cw / 2, hy - 22, cols[1] + cw / 2, lay.bottom + 14, dashed=True, colour=RED)
    s.cross(cols[1] + cw / 2, lay.bottom + 34, size=10)
    s.text(
        cols[1] + cw / 2 - 20, lay.bottom + 38, "never written", size=14, colour=RED, anchor="end"
    )

    L_A = ((0.05, 0.1, 0.42, 0.34), (0.53, 0.1, 0.42, 0.34), (0.05, 0.52, 0.9, 0.38))
    L_B = (
        (0.05, 0.1, 0.28, 0.4),
        (0.37, 0.1, 0.28, 0.4),
        (0.69, 0.1, 0.26, 0.4),
        (0.05, 0.58, 0.9, 0.32),
    )
    L_C = ((0.05, 0.1, 0.55, 0.8), (0.66, 0.1, 0.29, 0.8))
    L_D = ((0.05, 0.1, 0.9, 0.46), (0.05, 0.64, 0.9, 0.26))
    rows = (
        (
            "tab 1",
            "the main tab",
            L_A,
            L_B,
            L_B,
            "update",
            False,
            False,
            "updated in place",
            "title, components and layout come from v12",
        ),
        (
            "tab 2",
            "deleted since v12",
            None,
            L_C,
            L_C,
            "recreate",
            False,
            False,
            "recreated",
            "it comes back with the live main tab's permissions",
        ),
        (
            "tab 3",
            "added after v12",
            L_D,
            None,
            None,
            "delete",
            False,
            True,
            "deleted",
            "the family matches v12 exactly, and the main tab is never deleted",
        ),
    )
    r0 = hy + 22
    for i, (name, sub, live, snap, aft, verb, _, crossed, head, detail) in enumerate(rows):
        y = r0 + i * 112
        s.text(46, y + 34, name, size=16, anchor="start", weight="bold")
        s.text(46, y + 56, sub, size=12.5, colour=DIM, anchor="start")
        s.thumbnail(cols[0], y, cw, ch, tiles=live or (), fill=BLUE_INK, absent=live is None)
        s.thumbnail(cols[1], y, cw, ch, tiles=snap or (), fill=BLUE_INK, absent=snap is None)
        s.thumbnail(
            cols[2],
            y,
            cw,
            ch,
            tiles=aft or (),
            fill=GREEN_INK if aft else BLUE_INK,
            absent=aft is None,
        )
        if live is None:
            s.text(cols[0] + cw / 2, y + ch / 2 + 5, "absent", size=13, colour=GREY)
        if snap is None:
            s.text(cols[1] + cw / 2, y + ch / 2 + 5, "not in v12", size=13, colour=GREY)
        if aft is None:
            s.text(cols[2] + cw / 2, y + ch / 2 + 5, "gone", size=13, colour=GREY)
        s.arrow(
            cols[1] + cw + 10, y + ch / 2, cols[2] - 12, y + ch / 2, colour=RED if crossed else INK
        )
        s.text(
            (cols[1] + cw + cols[2]) / 2,
            y + ch / 2 - 10,
            verb,
            size=14,
            colour=RED if crossed else INK,
        )
        s.text(930, y + 28, head, size=16, anchor="start", weight="bold")
        _wrapped(s, 930, y + 50, detail, 42, size=13.5)

    # -- bottom notes -------------------------------------------------------
    by = r0 + 3 * 112 + 14
    s.box(
        Box(
            46,
            by,
            650,
            104,
            GREEN,
            "Undo is a restore",
            (
                "restore v16, the present as it was before any write",
                "it appends v18 (explicit) and v19 (restore)",
            ),
        )
    )
    s.box(
        Box(
            724,
            by,
            650,
            104,
            PINK,
            "The one thing a restore cannot reverse",
            (
                "deleting a version: owner only, and a pinned one needs force",
                "everything else, a restore included, can be undone",
            ),
        )
    )
    return s


@app.command()
def main(
    out: Path = typer.Option(
        Path("docs/images/v0.12/react/schema"),
        "--out",
        help="Output prefix; '_version_capture' / '_version_restore' are appended.",
    ),
    png: bool = typer.Option(True, "--png/--no-png", help="Also rasterise via Playwright."),
    quantize: bool = typer.Option(
        False, "--quantize/--no-quantize", help="Shrink the PNGs with ImageMagick (256 colours)."
    ),
) -> None:
    """Write both versioning schema SVGs (and PNGs) under --out."""
    write(build_capture(), out, "version_capture", png=png, quantize=quantize)
    write(build_restore(), out, "version_restore", png=png, quantize=quantize)


if __name__ == "__main__":
    app()
