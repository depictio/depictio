#!/usr/bin/env python3
"""Hand-drawn schemas for the user-groups feature (PR #972).

Two illustrated diagrams, built on the shared sketch toolkit:

- ``user-groups_sharing_model`` - people and a lab group on the left, the
  project folder (lock, direct and group permission blocks) in the middle, the
  one permissions gate and the resources behind it on the right, plus bob's
  role ladder, the live membership lookup, the floors and the bypasses.
- ``user-groups_saml_sync`` - a SAML assertion through the ACS of PR #968 into
  ``sync_sso_user`` (groups re-synced both ways, profile, pending P.I. claim),
  then who runs a group and where it happens in the UI.

Generated rather than drawn so the picture can be corrected in a diff when the
flow moves; the seeded jitter makes re-runs byte-identical.

Usage::

    python dev/diagrams/user_groups.py            # writes docs/images/*.svg/.png
    python dev/diagrams/user_groups.py --no-png   # svg only (no browser render)
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

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
    TICK_GREEN,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    circle,
    ellipse,
    folder,
    hourglass,
    page,
    table_stack,
    tick,
    write,
)

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "user-groups"


# --------------------------------------------------------------------------
# Glyphs shared by both diagrams: people, badges, chips.
# --------------------------------------------------------------------------


def halo(s: Sketch, cx: float, cy: float, r: float, colour: str = INK) -> None:
    """The dashed ring that means "this one, look here"."""
    s._parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="none" stroke="{colour}" '
        f'stroke-width="1.5" stroke-dasharray="4 3"/>'
    )


def crown(s: Sketch, cx: float, cy: float, size: float = 9) -> None:
    """The P.I. mark, as in the real UI."""
    k = size
    s.poly(
        [
            (cx - k, cy + k * 0.6),
            (cx - k, cy - k * 0.5),
            (cx - k * 0.45, cy + k * 0.05),
            (cx, cy - k * 0.7),
            (cx + k * 0.45, cy + k * 0.05),
            (cx + k, cy - k * 0.5),
            (cx + k, cy + k * 0.6),
        ],
        fill=GOLD,
        amount=0.5,
    )


def shield(s: Sketch, cx: float, cy: float, size: float = 8) -> None:
    """The group-admin mark, as in the real UI."""
    k = size
    s.poly(
        [(cx - k, cy - k), (cx + k, cy - k), (cx + k, cy), (cx, cy + k * 1.25), (cx - k, cy)],
        fill=BLUE_INK,
        amount=0.5,
    )
    tick(s, cx, cy - k * 0.1, size=k * 0.5, colour=WHITE)


def avatar(
    s: Sketch,
    cx: float,
    cy: float,
    r: float,
    initials: str,
    fill: str = BLUE,
    *,
    pi: bool = False,
    admin: bool = False,
    ghost: bool = False,
    ring: str | None = None,
) -> None:
    """A person: a circle with initials, plus the crown / shield badges."""
    if ghost:
        s.dot(cx, cy, r, fill=WHITE, colour=GREY, dashed=True)
    else:
        circle(s, cx, cy, r, fill)
    s.text(
        cx,
        cy + r * 0.32,
        initials,
        size=r * 0.9,
        weight="bold",
        colour=GREY if ghost else INK,
    )
    if ring:
        halo(s, cx, cy, r + 7, ring)
    if pi:
        crown(s, cx, cy - r - r * 0.32, r * 0.36)
    if admin:
        shield(s, cx + r * 0.82, cy + r * 0.78, r * 0.3)


def pill(
    s: Sketch,
    x: float,
    y: float,
    w: float,
    label: str,
    fill: str = WHITE,
    *,
    h: float = 26,
    size: float = 12.5,
    colour: str = INK,
    dashed: bool = False,
    line: str = INK,
    weight: str = "normal",
) -> Box:
    box = Box(x, y, w, h, fill, "", ())
    s.rect(box, colour=line, dashed=dashed)
    s.text(box.cx, y + h / 2 + size * 0.35, label, size=size, colour=colour, weight=weight)
    return box


def user_chip(s: Sketch, x: float, y: float, name: str, initials: str, fill: str = BLUE) -> float:
    """A user snapshot as it sits in a permissions list; returns its width."""
    w = 40 + len(name) * 8.2
    s.rect(Box(x, y, w, 28, WHITE, "", ()))
    circle(s, x + 15, y + 14, 9, fill)
    s.text(x + 15, y + 18, initials, size=10, weight="bold")
    s.text(x + 30, y + 19, name, size=13, anchor="start")
    return w


def group_glyph(s: Sketch, cx: float, cy: float, r: float = 8) -> None:
    """Two overlapping heads: a group."""
    circle(s, cx + r * 0.55, cy, r, VIOLET)
    circle(s, cx - r * 0.55, cy, r, WHITE)


def group_chip(s: Sketch, x: float, y: float, name: str) -> float:
    w = 52 + len(name) * 8.2
    s.rect(Box(x, y, w, 28, WHITE, "", ()))
    group_glyph(s, x + 20, y + 14, 7)
    s.text(x + 38, y + 19, name, size=13, anchor="start")
    return w


def sticker(s: Sketch, x: float, y: float, w: float, label: str, fill: str = ORANGE) -> None:
    pill(s, x, y, w, label, fill, h=22, size=11.5, line=ORANGE_INK)


def plus(s: Sketch, cx: float, cy: float, size: float = 7) -> None:
    s.line(cx - size, cy, cx + size, cy, colour=TICK_GREEN, width=2.4, amount=0.3, passes=1)
    s.line(cx, cy - size, cx, cy + size, colour=TICK_GREEN, width=2.4, amount=0.3, passes=1)


def minus(s: Sketch, cx: float, cy: float, size: float = 7) -> None:
    s.line(cx - size, cy, cx + size, cy, colour=RED, width=2.4, amount=0.3, passes=1)


# --------------------------------------------------------------------------
# 1. Sharing model: people -> project -> one gate -> resources.
# --------------------------------------------------------------------------

SHARE_W, SHARE_H = 1760, 1240


def _turnstile(s: Sketch, cx: float, top: float) -> None:
    """The gate: a pillar with a card reader and a three-arm rotor."""
    s.rect(Box(cx - 24, top, 48, 230, YELLOW, "", ()))
    s.rect(Box(cx - 17, top + 14, 34, 26, GREEN, "", ()), colour=INK)
    tick(s, cx, top + 27, size=6)
    hub_y = top + 128
    for deg in (-90, 30, 150):
        a = math.radians(deg)
        s.line(cx, hub_y, cx + 54 * math.cos(a), hub_y + 54 * math.sin(a), width=3.4, amount=0.8)
    s.dot(cx, hub_y, 8, fill=WHITE, width=1.8)
    s.line(cx - 52, top + 230, cx + 52, top + 230, width=3, amount=1.0)


def _tile(s: Sketch, x: float, y: float, label: str, icon: str) -> None:
    """One resource behind the gate: a small icon over its name."""
    w, h = 130, 120
    s.rect(Box(x, y, w, h, WHITE, "", ()))
    cx, cy = x + w / 2, y + 48
    if icon == "projects":
        folder(s, cx - 26, cy - 20, 52, 38, YELLOW)
    elif icon == "dashboards":
        s.thumbnail(
            cx - 34,
            cy - 24,
            68,
            48,
            tiles=((0.08, 0.1, 0.4, 0.3), (0.52, 0.1, 0.4, 0.3), (0.08, 0.5, 0.84, 0.4)),
            fill=BLUE,
        )
    elif icon == "runs":
        for k in range(3):
            s.dot(cx - 32 + k * 32, cy, 8, fill=GREEN_INK if k < 2 else WHITE)
        s.line(cx - 24, cy, cx - 8, cy, amount=0.4, passes=1)
        s.line(cx + 8, cy, cx + 24, cy, amount=0.4, passes=1)
    elif icon == "files":
        page(s, cx - 34, cy - 24, 26, 36)
        table_stack(s, cx - 2, cy - 6, 34, 24, GREEN, n=2)
    elif icon == "catalog":
        page(s, cx - 34, cy - 24, 28, 38)
        s.arrow(cx - 2, cy - 4, cx + 34, cy - 4)
    elif icon == "viz":
        for k, v in enumerate((0.45, 0.8, 0.6, 1.0)):
            bh = 44 * v
            s.rect(Box(cx - 34 + k * 18, cy + 22 - bh, 13, bh, BLUE, "", ()))
    elif icon == "events":
        s.curve(
            [
                (cx - 36, cy),
                (cx - 22, cy - 18),
                (cx - 8, cy + 14),
                (cx + 8, cy - 14),
                (cx + 22, cy + 10),
                (cx + 36, cy),
            ],
            colour=INK,
        )
    elif icon == "camera":
        s.rect(Box(cx - 30, cy - 14, 60, 38, LIGHT_GREY, "", ()))
        s.rect(Box(cx - 10, cy - 22, 20, 8, LIGHT_GREY, "", ()))
        circle(s, cx, cy + 5, 11, WHITE)
    elif icon == "ingest":
        circle(s, cx, cy, 22, GREEN)
        s.poly([(cx - 7, cy - 11), (cx + 12, cy), (cx - 7, cy + 11)], fill=WHITE, amount=0.5)
    s.text(cx, y + 104, label, size=13)


def build_sharing_model() -> Sketch:
    s = Sketch(SHARE_W, SHARE_H, seed=972)
    s.heading(
        40,
        52,
        "Sharing a project with users and groups",
        "a role is granted to people or to whole groups - the highest one wins, "
        "and one gate checks it everywhere",
    )
    for x, label in (
        (40, "who gets access"),
        (480, "what the project stores"),
        (1130, "who checks it, everywhere"),
    ):
        s.text(x, 126, label, size=13, anchor="start", colour=GREY)

    # -- 1. people ---------------------------------------------------------
    avatar(s, 80, 190, 28, "A", BLUE)
    s.text(80, 242, "alice", size=15, weight="bold")
    s.text(80, 260, "direct owner", size=12, colour=DIM)

    avatar(s, 80, 335, 28, "B", PINK, ring=INK)
    s.text(80, 387, "bob", size=15, weight="bold")
    s.text(80, 405, "direct viewer", size=12, colour=DIM)

    lab = Box(40, 440, 380, 200, VIOLET, "", ())
    s.rect(lab, dashed=True)
    group_glyph(s, 66, 466, 9)
    s.text(90, 472, "Lab X", size=17, weight="bold", anchor="start")
    s.text(160, 472, "a group", size=12, colour=DIM, anchor="start")
    members = (
        (95, "C", "carol", True, True, GREEN),
        (175, "D", "dave", False, True, BLUE),
        (255, "B", "bob", False, False, PINK),
        (335, "E", "erin", False, False, YELLOW),
    )
    for mx, ini, name, pi, adm, fill in members:
        avatar(s, mx, 538, 24, ini, fill, pi=pi, admin=adm, ring=INK if name == "bob" else None)
        s.text(mx, 584, name, size=12.5)
        if name == "bob":
            s.text(mx, 600, "same person", size=11, colour=DIM)
    crown(s, 70, 618, 6)
    s.text(82, 622, "P.I.", size=12, colour=DIM, anchor="start")
    shield(s, 150, 616, 6)
    s.text(162, 622, "group admin", size=12, colour=DIM, anchor="start")

    # -- 2. the project ----------------------------------------------------
    folder(s, 480, 130, 560, 480, YELLOW)
    s.text(505, 172, "Project", size=20, weight="bold", anchor="start")
    s.lock(1002, 168, 15)

    s.rect(Box(505, 190, 510, 160, BLUE, "", ()))
    s.text(522, 214, "direct", size=15, weight="bold", anchor="start")
    s.text(580, 214, "(UserBase snapshots)", size=12, colour=DIM, anchor="start")
    s.rect(Box(505, 366, 510, 160, VIOLET, "", ()))
    s.text(522, 390, "groups", size=15, weight="bold", anchor="start")
    s.text(590, 390, "({id, name} snapshots)", size=12, colour=DIM, anchor="start")

    rows = (
        (248, "`owners`", lambda y: user_chip(s, 655, y - 21, "alice", "A", BLUE)),
        (286, "`editors`", None),
        (324, "`viewers`", lambda y: user_chip(s, 655, y - 21, "bob", "B", PINK)),
        (424, "`group_owners`", lambda y: group_chip(s, 655, y - 21, "Lab X")),
        (462, "`group_editors`", None),
        (500, "`group_viewers`", None),
    )
    for ry, label, draw in rows:
        s.text(522, ry, label, size=13.5, anchor="start")
        if draw is None:
            s.text(657, ry, "`[ ]`", size=13, anchor="start", colour=GREY)
        else:
            draw(ry)

    s.text(
        760, 556, "`is_public` or `*` in viewers = a viewer floor for anyone", size=13, colour=DIM
    )
    s.text(
        760, 580, "empty lists by default: pre-groups projects load unchanged", size=13, colour=DIM
    )

    s.arrow(112, 192, 502, 244)
    s.text(300, 206, "owner", size=13, colour=DIM)
    s.arrow(112, 336, 502, 322)
    s.text(300, 316, "viewer", size=13, colour=DIM)
    s.arrow(424, 520, 502, 438)

    # -- 3. the gate and what it guards -----------------------------------
    s.text(1215, 154, "one chokepoint", size=18, weight="bold")
    s.text(1215, 174, "`permissions.py`", size=12, colour=DIM)
    _turnstile(s, 1215, 190)

    s.arrow(1044, 300, 1168, 300)
    s.text(1106, 270, "the project's", size=12, colour=DIM)
    s.text(1106, 286, "permissions", size=12, colour=DIM)

    s.rect(Box(1313, 138, 430, 400, WHITE, "", ()), colour=GREY, dashed=True)
    s.arrow(1272, 318, 1308, 318)
    tiles = (
        ("projects", "projects"),
        ("dashboards", "dashboards"),
        ("workflows / runs", "runs"),
        ("files / deltatables", "files"),
        ("catalog / export", "catalog"),
        ("multiqc / adv. viz", "viz"),
        ("events (websocket)", "events"),
        ("screenshots", "camera"),
        ("ingestion trigger", "ingest"),
    )
    for i, (label, icon) in enumerate(tiles):
        _tile(s, 1325 + (i % 3) * 138, 150 + (i // 3) * 126, label, icon)

    s.rect(Box(1313, 556, 430, 100, WHITE, "", ()), colour=GREY, dashed=True)
    s.text(1328, 582, "list queries: `build_access_query`  (Mongo $or)", size=13, anchor="start")
    s.text(1328, 606, "one document: `resolve_effective_role`", size=13, anchor="start")
    s.text(1328, 630, "screenshots: Celery, its own Mongo client", size=13, anchor="start")

    # -- bob's worked example: the role ladder ------------------------------
    s.line(40, 690, 1720, 690, colour=GREY, dashed=True, amount=1.2)
    s.text(40, 730, "worked example: bob", size=21, anchor="start")
    s.text(
        40,
        752,
        "a direct viewer, and a member of Lab X which is a group owner",
        size=13,
        colour=DIM,
        anchor="start",
    )
    rail_l, rail_r = 330, 410
    s.line(rail_l, 790, rail_l, 1120, width=2.4, amount=1.2)
    s.line(rail_r, 790, rail_r, 1120, width=2.4, amount=1.2)
    rungs = ((830, "owner"), (950, "editor"), (1070, "viewer"))
    s.shade(318, 810, 300, 40, fill=GOLD, opacity=0.55)
    for ry, label in rungs:
        s.line(rail_l, ry, rail_r, ry, width=2.6, amount=0.6)
        s.text(432, ry + 5, label, size=17, weight="bold", anchor="start")
    s.dot(370, 830, 8, fill=GOLD, ring=True)
    s.dot(370, 1070, 7, fill=BLUE_INK)

    avatar(s, 150, 950, 28, "B", PINK, ring=INK)
    s.text(196, 956, "bob", size=15, weight="bold", anchor="start")
    pill(s, 40, 1056, 230, "direct: viewer", BLUE, h=30, size=14)
    pill(s, 40, 815, 230, "via Lab X: group owner", VIOLET, h=30, size=14)
    s.line(150, 922, 150, 848, colour=DIM, dashed=True, amount=1.0)
    s.line(150, 980, 150, 1052, colour=DIM, dashed=True, amount=1.0)
    s.arrow(272, 830, 322, 830)
    s.arrow(272, 1071, 322, 1071)
    s.text(432, 890, "highest of the two wins:", size=13, colour=DIM, anchor="start")
    s.text(432, 910, "effective role = owner", size=13, colour=INK, anchor="start", weight="bold")
    s.arrow(596, 880, 596, 858, colour=DIM)

    # -- membership is read live -------------------------------------------
    s.text(660, 730, "membership is read live", size=21, anchor="start")
    s.rect(Box(660, 765, 160, 84, WHITE, "", ()))
    s.text(676, 788, "Lab X", size=14, weight="bold", anchor="start")
    s.text(812, 788, "`groups`", size=11, colour=GREY, anchor="end")
    for i, (ini, fill) in enumerate((("C", GREEN), ("D", BLUE), ("B", PINK))):
        avatar(s, 698 + i * 40, 822, 13, ini, fill)
    s.arrow(828, 810, 898, 810)
    s.text(863, 794, "bob leaves", size=12, colour=DIM)
    s.rect(Box(906, 765, 160, 84, WHITE, "", ()))
    s.text(922, 788, "Lab X", size=14, weight="bold", anchor="start")
    s.text(1058, 788, "`groups`", size=11, colour=GREY, anchor="end")
    for i, (ini, fill) in enumerate((("C", GREEN), ("D", BLUE))):
        avatar(s, 944 + i * 40, 822, 13, ini, fill)
    avatar(s, 1024, 822, 13, "B", WHITE, ghost=True)
    s.cross(1024, 822, size=9)
    s.text(
        660, 884, "`get_user_group_ids` runs on every request,", size=13, anchor="start", colour=DIM
    )
    s.text(
        660, 904, "never copied onto users or tokens: a change", size=13, anchor="start", colour=DIM
    )
    s.text(660, 924, "applies on the very next request", size=13, anchor="start", colour=DIM)
    s.arrow(1062, 770, 1204, 428, dashed=True, colour=DIM)
    s.text(1162, 600, "your groups,", size=12, colour=DIM, anchor="start")
    s.text(1162, 616, "read per request", size=12, colour=DIM, anchor="start")

    # -- group admins manage sharing ---------------------------------------
    s.text(1280, 730, "group admins manage sharing", size=21, anchor="start")
    avatar(s, 1332, 810, 28, "C", GREEN, pi=True, admin=True)
    s.text(1332, 862, "carol", size=15, weight="bold")
    s.arrow(1372, 808, 1468, 808)
    s.text(1420, 790, "edits who", size=12, colour=DIM)
    s.text(1420, 828, "it is shared with", size=12, colour=DIM)
    folder(s, 1480, 772, 86, 62, YELLOW)
    s.lock(1523, 806, 12)
    pill(s, 1585, 790, 146, "Lab X in group_owners", VIOLET, h=36, size=12)
    s.text(
        1280,
        904,
        "needs: group admin of a group that is listed",
        size=13,
        anchor="start",
        colour=DIM,
    )
    s.text(
        1280,
        924,
        "in the project's group_owners (direct owners",
        size=13,
        anchor="start",
        colour=DIM,
    )
    s.text(1280, 944, "and sysadmins can edit it too)", size=13, anchor="start", colour=DIM)

    # -- floors and bypasses ------------------------------------------------
    s.text(660, 990, "floors and bypasses", size=21, anchor="start")
    # public floor
    circle(s, 725, 1050, 26, BLUE)
    ellipse(s, 725, 1050, 11, 26, "none", n=20)
    s.line(699, 1050, 751, 1050, amount=0.4, passes=1, width=1.2)
    s.text(790, 1042, "`is_public`", size=14, anchor="start")
    s.text(790, 1064, "or `*` in viewers", size=14, anchor="start")
    s.text(725, 1104, "a viewer floor for anyone", size=13, colour=DIM)
    # sysadmin
    avatar(s, 975, 1050, 26, "SA", ORANGE, ring=GOLD)
    s.text(1040, 1042, "sysadmins", size=15, weight="bold", anchor="start")
    s.text(1040, 1064, "skip every filter", size=13, colour=DIM, anchor="start")
    s.text(1010, 1104, "owner everywhere", size=13, colour=DIM)
    # anonymous
    avatar(s, 1225, 1050, 26, "?", WHITE, ghost=True)
    s.text(1290, 1042, "anonymous", size=15, weight="bold", anchor="start")
    s.text(1290, 1064, "public only", size=13, colour=DIM, anchor="start")
    s.text(1265, 1104, "never above viewer", size=13, colour=DIM)

    # -- still direct-owner ------------------------------------------------
    s.rect(Box(1480, 980, 263, 170, WHITE, "", ()), colour=GREY, dashed=True)
    s.lock(1506, 1010, 11)
    s.text(1528, 1016, "still direct-owner", size=16, weight="bold", anchor="start")
    s.text(1496, 1048, "project create, update,", size=13, anchor="start", colour=DIM)
    s.text(1496, 1068, "delete", size=13, anchor="start", colour=DIM)
    s.text(1496, 1096, "data-collection rename,", size=13, anchor="start", colour=DIM)
    s.text(1496, 1116, "delete", size=13, anchor="start", colour=DIM)

    s.text(
        40,
        1206,
        "No token to invalidate and no copy to refresh: add or remove someone from Lab X and "
        "every gate sees it on the next request.",
        size=15,
        anchor="start",
        colour=DIM,
    )
    return s


# --------------------------------------------------------------------------
# 2. SSO sync, governance and the screens.
# --------------------------------------------------------------------------

SAML_W, SAML_H = 1760, 1700


def _group_row(
    s: Sketch,
    x: float,
    y: float,
    name: str,
    members: list[tuple[str, str, str]],
    *,
    sso: bool = True,
    absent: bool = False,
    w: float = 290,
) -> None:
    """One group as a row: its name and tag, then its members as avatars.

    Members are ``(initials, fill, state)`` with state ``""`` (plain), ``"new"``
    (just added), ``"gone"`` (just removed) or ``"pi"``.
    """
    if absent:
        s.rect(Box(x, y, w, 50, WHITE, "", ()), colour=GREY, dashed=True)
        s.text(x + w / 2, y + 30, "does not exist yet", size=13, colour=GREY)
        return
    s.rect(Box(x, y, w, 50, VIOLET if sso else LIGHT_GREY, "", ()))
    s.text(x + 12, y + 21, name, size=14.5, weight="bold", anchor="start")
    s.text(
        x + 12,
        y + 39,
        "sso_managed" if sso else "manual group",
        size=11,
        colour=DIM,
        anchor="start",
    )
    for i, (ini, fill, state) in enumerate(members):
        cx = x + 158 + i * 38
        if state == "gone":
            avatar(s, cx, y + 25, 14, ini, WHITE, ghost=True)
            s.cross(cx, y + 25, size=8)
        else:
            avatar(s, cx, y + 25, 14, ini, fill, ring=GREEN_INK if state == "new" else None)
    if not sso:
        s.lock(x + w - 20, y + 25, 9)


def _shift(s: Sketch, dy: float) -> None:
    """Open a group that moves everything drawn after it down by ``dy``."""
    s._parts.append(f'<g transform="translate(0,{dy:g})">')


def _unshift(s: Sketch) -> None:
    s._parts.append("</g>")


def _station(s: Sketch, cx: float, y: float, n: str, title: str, sub: str) -> None:
    """One step of sync_sso_user: a numbered card."""
    w = 300
    s.rect(Box(cx - w / 2, y, w, 46, WHITE, "", ()))
    circle(s, cx - w / 2 + 22, y + 23, 12, GOLD)
    s.text(cx - w / 2 + 22, y + 28, n, size=14, weight="bold")
    s.text(cx - w / 2 + 44, y + 21, title, size=14.5, weight="bold", anchor="start")
    s.text(cx - w / 2 + 44, y + 38, sub, size=11.5, colour=DIM, anchor="start")


def _mock_admin(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """Admin -> Groups: a sidebar, the group list, the members table."""
    browser(s, x, y, w, h)
    s.text(x + w / 2, y + 19, "Administration", size=11, colour=DIM)
    top = y + 28
    s.line(x + 84, top, x + 84, y + h, colour=GREY, amount=0.4, passes=1, width=1)
    for i, (label, sel) in enumerate((("Users", False), ("Groups", True), ("Projects", False))):
        iy = top + 12 + i * 30
        if sel:
            s.rect(Box(x + 8, iy - 4, 70, 24, BLUE, "", ()), colour=BLUE_INK)
        s.text(x + 16, iy + 13, label, size=12, anchor="start", weight="bold" if sel else "normal")
    gx = x + 96
    s.text(gx, top + 22, "group", size=10.5, colour=GREY, anchor="start")
    s.text(gx + 106, top + 22, "#", size=10.5, colour=GREY, anchor="end")
    s.line(gx, top + 27, gx + 112, top + 27, colour=GREY, amount=0.3, passes=1, width=1)
    for i, (name, n, sel) in enumerate(
        (("admin", "1", False), ("korbel-lab", "2", True), ("users", "2", False))
    ):
        gy = top + 32 + i * 28
        if sel:
            s.rect(Box(gx - 4, gy, 120, 24, BLUE, "", ()), colour=BLUE_INK)
        s.text(gx, gy + 17, name, size=12, anchor="start")
        s.text(gx + 106, gy + 17, n, size=12, anchor="end")
    mx = x + 226
    s.line(mx - 8, top + 8, mx - 8, y + h - 8, colour=GREY, amount=0.4, passes=1, width=1)
    s.text(mx, top + 22, "member", size=10.5, colour=GREY, anchor="start")
    s.text(mx + 90, top + 22, "admin", size=10.5, colour=GREY, anchor="start")
    s.text(mx + 135, top + 22, "P.I.", size=10.5, colour=GREY, anchor="start")
    s.line(mx, top + 27, x + w - 12, top + 27, colour=GREY, amount=0.3, passes=1, width=1)
    for i, (name, pi) in enumerate((("ada", True), ("ben", False))):
        my = top + 34 + i * 30
        s.text(mx, my + 17, name, size=12.5, anchor="start")
        s.rect(Box(mx + 92, my + 3, 15, 15, BLUE_INK, "", ()))
        tick(s, mx + 99.5, my + 11, size=3.8, colour=WHITE)
        if pi:
            crown(s, mx + 147, my + 11, 6)
    s.rect(Box(mx, top + 104, w - 238, 24, LIGHT_GREY, "", ()), colour=GREY)
    s.text(mx + 8, top + 121, "add a member...", size=11, colour=GREY, anchor="start")


def _mock_my_groups(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """The self-service page: your groups, with crown / shield next to each."""
    browser(s, x, y, w, h)
    s.text(x + w / 2, y + 19, "My Groups", size=11, colour=DIM)
    top = y + 28
    s.text(x + 14, top + 24, "group", size=10.5, colour=GREY, anchor="start")
    s.line(x + 12, top + 29, x + 150, top + 29, colour=GREY, amount=0.3, passes=1, width=1)
    for i, (name, kind, sel) in enumerate(
        (("korbel-lab", "pi", True), ("imaging-core", "admin", False), ("users", "", False))
    ):
        gy = top + 34 + i * 30
        if sel:
            s.rect(Box(x + 8, gy, 150, 26, BLUE, "", ()), colour=BLUE_INK)
        s.text(x + 16, gy + 18, name, size=12, anchor="start")
        if kind == "pi":
            crown(s, x + 138, gy + 13, 6)
        elif kind == "admin":
            shield(s, x + 138, gy + 11, 6)
    s.line(x + 172, top + 8, x + 172, y + h - 8, colour=GREY, amount=0.4, passes=1, width=1)
    s.text(x + 186, top + 26, "korbel-lab", size=13.5, weight="bold", anchor="start")
    s.text(x + 186, top + 50, "you are the P.I.", size=11.5, colour=DIM, anchor="start")
    s.text(x + 186, top + 76, "members can be added,", size=11.5, colour=DIM, anchor="start")
    s.text(x + 186, top + 92, "promoted or removed", size=11.5, colour=DIM, anchor="start")
    s.text(x + 186, top + 108, "by its group admins", size=11.5, colour=DIM, anchor="start")


def _mock_permissions(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """Project permissions: the Groups section is a role grid, one row per group."""
    browser(s, x, y, w, h)
    s.text(x + w / 2, y + 19, "Project permissions", size=11, colour=DIM)
    top = y + 28
    s.text(x + 14, top + 24, "Groups", size=14, weight="bold", anchor="start")
    cols = (("Owner", x + w - 138), ("Editor", x + w - 92), ("Viewer", x + w - 44))
    s.line(x + 12, top + 52, x + w - 12, top + 52, colour=GREY, amount=0.3, passes=1, width=1)
    s.text(x + 14, top + 46, "group", size=10.5, colour=GREY, anchor="start")
    for label, cx in cols:
        s.text(cx, top + 46, label, size=10.5, colour=GREY)
    grid = (("Lab X", (True, False, False)), ("imaging-core", (False, False, True)))
    for i, (name, flags) in enumerate(grid):
        gy = top + 62 + i * 32
        s.text(x + 14, gy + 16, name, size=12.5, anchor="start")
        for (_, cx), on in zip(cols, flags):
            s.rect(
                Box(cx - 8, gy + 3, 16, 16, BLUE_INK if on else WHITE, "", ()),
                colour=INK if on else GREY,
            )
            if on:
                tick(s, cx, gy + 11, size=4, colour=WHITE)
    s.rect(Box(x + 12, top + 134, w - 24, 24, LIGHT_GREY, "", ()), colour=GREY)
    s.text(x + 20, top + 151, "add a group...", size=11, colour=GREY, anchor="start")


def _mock_profile(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """Profile: the Name / Title rows and the group badges (crown = P.I., shield = admin)."""
    browser(s, x, y, w, h)
    s.text(x + w / 2, y + 19, "Profile", size=11, colour=DIM)
    top = y + 28
    avatar(s, x + 40, top + 38, 22, "AL", BLUE)
    s.text(x + 76, top + 34, "Ada L.", size=15, weight="bold", anchor="start")
    s.text(x + 76, top + 52, "ada@lab.org", size=11.5, colour=DIM, anchor="start")
    rows = (("Name", "Ada L."), ("Title", "group leader"))
    for i, (label, value) in enumerate(rows):
        ry = top + 82 + i * 24
        s.text(x + 14, ry, label, size=11.5, colour=GREY, anchor="start")
        s.text(x + 80, ry, value, size=12.5, anchor="start")
    gy = top + 130
    s.text(x + 14, gy + 16, "Groups", size=11.5, colour=GREY, anchor="start")
    pill(s, x + 80, gy, 108, "korbel-lab", WHITE, h=24, size=12)
    crown(s, x + 91, gy + 12, 5.5)
    pill(s, x + 196, gy, 100, "new-lab", WHITE, h=24, size=12)


def build_saml_sync() -> Sketch:
    s = Sketch(SAML_W, SAML_H, seed=968)
    s.heading(
        40,
        52,
        "SSO sync and who runs a group",
        "every SAML login re-syncs the user's groups and profile; people, not code, "
        "decide who administers them",
    )

    # -- 1. the login and the assertion ----------------------------------
    s.text(40, 126, "a login through the identity provider", size=13, anchor="start", colour=GREY)
    browser(s, 40, 140, 250, 190)
    s.text(165, 159, "company login", size=11, colour=DIM)
    avatar(s, 76, 214, 20, "AL", BLUE)
    s.text(104, 210, "Ada L.", size=14, weight="bold", anchor="start")
    s.text(104, 227, "signs in with SSO", size=11.5, colour=DIM, anchor="start")
    s.rect(Box(58, 252, 214, 28, LIGHT_GREY, "", ()), colour=GREY)
    s.text(70, 271, "ada", size=12, anchor="start")
    s.rect(Box(58, 288, 214, 32, GREEN, "", ()))
    s.text(165, 309, "Sign in", size=13, weight="bold")

    s.arrow(296, 235, 350, 235)

    card = Box(356, 140, 300, 262, WHITE, "", ())
    s.rect(card)
    s.rect(Box(356, 140, 300, 34, VIOLET, "", ()))
    s.text(372, 163, "SAML assertion", size=16, weight="bold", anchor="start")
    s.text(640, 163, "attributes", size=11.5, colour=DIM, anchor="end")
    attrs = (
        ("groups", "korbel-lab, new-lab", "`DEPICTIO_AUTH_SAML_ATTRIBUTE_GROUPS`"),
        ("title", "group leader", "`..._ATTRIBUTE_TITLE`"),
        ("display name", "Ada L.", "`..._ATTRIBUTE_DISPLAY_NAME`"),
        ("login", "ada", "`..._ATTRIBUTE_LOGIN`"),
    )
    for i, (name, value, env) in enumerate(attrs):
        ay = 196 + i * 46
        s.text(372, ay + 6, name, size=14, weight="bold", anchor="start")
        s.text(472, ay + 6, value, size=13.5, anchor="start")
        s.text(372, ay + 27, env, size=11.5, colour=DIM, anchor="start")
        if i:
            s.line(364, ay - 14, 648, ay - 14, colour=LIGHT_GREY, amount=0.3, passes=1, width=1.2)
    s.text(506, 392, "each mapping is optional: unset = skipped", size=12, colour=DIM)

    s.arrow(662, 235, 716, 235)

    acs = Box(722, 140, 250, 190, WHITE, "", ())
    s.rect(acs)
    sticker(s, 738, 124, 84, "PR #968", ORANGE)
    s.text(acs.cx, 176, "ACS callback", size=18, weight="bold")
    s.text(acs.cx, 204, "`create_or_get_sso_user`", size=12.5, colour=DIM)
    s.text(acs.cx, 232, "then a magic-link ticket", size=13, colour=DIM)
    s.text(acs.cx, 252, "and the user lands in", size=13, colour=DIM)
    s.text(acs.cx, 272, "the viewer", size=13, colour=DIM)

    # the 3-line hook, drawn as a link that is not there yet
    s.arrow(978, 235, 1060, 235, dashed=True, colour=RED)
    hourglass(s, 1019, 212, size=9)
    s.rect(Box(1060, 140, 671, 190, WHITE, "", ()), colour=RED, dashed=True)
    sticker(s, 1076, 124, 330, "lands once #968 and #972 are merged", PINK)
    s.text(
        1080,
        176,
        "the whole hook in the ACS handler: 3 lines",
        size=15,
        weight="bold",
        anchor="start",
    )
    for n, ny in (("1", 208), ("2", 235), ("3", 262)):
        s.text(1086, ny, f"`{n}`", size=12, colour=GREY, anchor="end")
    s.text(1100, 208, "`from ...sso_sync import sync_sso_user`", size=14, anchor="start")
    s.text(1100, 262, "`await sync_sso_user(user, auth.get_attributes())`", size=14, anchor="start")
    s.text(
        1080,
        296,
        "after the user is created or fetched, before the magic-link ticket",
        size=13,
        colour=DIM,
        anchor="start",
    )
    s.text(
        1080, 316, "each missing mapping simply skips its step", size=13, colour=DIM, anchor="start"
    )

    # -- 2. the sync band ----------------------------------------------------
    s.arrow(1395, 334, 1395, 412, dashed=True, colour=RED)
    _shift(s, 30)
    s.rect(Box(40, 386, 1691, 108, YELLOW, "", ()))
    s.text(60, 412, "sync_sso_user(user, attributes)", size=18, weight="bold", anchor="start")
    s.text(380, 412, "`auth_endpoints/sso_sync.py`", size=12.5, colour=DIM, anchor="start")
    s.text(
        1711,
        412,
        "idempotent - no attributes in the assertion = a no-op, nothing is wiped",
        size=13,
        colour=DIM,
        anchor="end",
    )
    centres = (410, 995, 1470)
    _station(s, centres[0], 432, "1", "groups", "`_sync_groups`")
    _station(s, centres[1], 432, "2", "profile", "`_sync_profile`")
    _station(s, centres[2], 432, "3", "claim a pending P.I.", "`claim_pending_pi_groups`")
    for cx in centres:
        s.arrow(cx, 496, cx, 524)

    # -- 3a. groups, before and after ------------------------------------
    s.rect(Box(40, 530, 740, 312, WHITE, "", ()), colour=GREY, dashed=True)
    s.text(
        58,
        558,
        "groups are re-synced both ways, on every login",
        size=16,
        weight="bold",
        anchor="start",
    )
    s.text(206, 586, "before", size=13, colour=GREY)
    s.text(616, 586, "after", size=13, colour=GREY)
    bx, ax = 56, 470
    ys = (598, 654, 710, 766)
    A, B, C = ("A", BLUE), ("B", PINK), ("C", GREEN)
    # before
    _group_row(s, bx, ys[0], "korbel-lab", [(*B, ""), (*C, "")])
    _group_row(s, bx, ys[1], "imaging-core", [(*A, ""), (*B, "")])
    _group_row(s, bx, ys[2], "new-lab", [], absent=True)
    _group_row(s, bx, ys[3], "journal-club", [(*A, "")], sso=False)
    # after
    _group_row(s, ax, ys[0], "korbel-lab", [(*A, "new"), (*B, ""), (*C, "")])
    _group_row(s, ax, ys[1], "imaging-core", [(*A, "gone"), (*B, "")])
    _group_row(s, ax, ys[2], "new-lab", [(*A, "new")])
    _group_row(s, ax, ys[3], "journal-club", [(*A, "")], sso=False)
    # the verbs, in the gap
    s.arrow(354, 698, 462, 698)
    s.text(408, 650, "assertion:", size=12, colour=DIM)
    s.text(408, 666, "korbel-lab,", size=12, colour=DIM)
    s.text(408, 682, "new-lab", size=12, colour=DIM)
    for cy, kind in ((ys[0] + 25, "+"), (ys[1] + 25, "-"), (ys[2] + 25, "+")):
        (plus if kind == "+" else minus)(s, 768, cy, 6)
    s.text(
        60,
        834,
        "ada joins korbel-lab, leaves imaging-core, new-lab appears; the manual group stays put",
        size=12.5,
        colour=DIM,
        anchor="start",
    )

    # -- 3b. the profile ---------------------------------------------------
    s.rect(Box(810, 530, 370, 312, WHITE, "", ()), colour=GREY, dashed=True)
    s.text(828, 558, "the profile is refreshed", size=16, weight="bold", anchor="start")
    _mock_profile(s, 826, 580, 338, 190)
    s.text(995, 794, "title, display name and login are written when they", size=12.5, colour=DIM)
    s.text(995, 814, "change; `sso_provider` is stamped saml", size=12.5, colour=DIM)

    # -- 3c. pending P.I. --------------------------------------------------
    s.rect(Box(1210, 530, 521, 312, WHITE, "", ()), colour=GREY, dashed=True)
    s.text(
        1228, 558, "a P.I. named before they ever signed in", size=16, weight="bold", anchor="start"
    )
    avatar(s, 1272, 618, 20, "SA", ORANGE)
    s.text(1272, 658, "sysadmin", size=12.5, colour=DIM)
    s.arrow(1300, 614, 1346, 614)
    s.rect(Box(1352, 590, 356, 58, VIOLET, "", ()))
    s.text(1368, 614, "korbel-lab", size=14.5, weight="bold", anchor="start")
    s.text(1368, 636, "`pending_pi_email: ada@lab.org`", size=12, anchor="start")
    hourglass(s, 1678, 619, size=9)
    s.text(1530, 672, "parked: ada has no account yet", size=12.5, colour=DIM)

    s.arrow(1530, 680, 1530, 706)
    avatar(s, 1272, 750, 20, "AL", BLUE, ghost=True)
    s.text(1272, 790, "ada logs in", size=12.5, colour=DIM)
    s.arrow(1300, 746, 1346, 746)
    s.rect(Box(1352, 710, 356, 76, VIOLET, "", ()))
    s.text(1368, 734, "korbel-lab", size=14.5, weight="bold", anchor="start")
    s.text(1368, 758, "`pending_pi_email` cleared", size=11.5, colour=DIM, anchor="start")
    tick(s, 1380, 774, size=6)
    s.text(1396, 778, "claimed", size=12, colour=DIM, anchor="start")
    avatar(s, 1618, 752, 20, "AL", BLUE, pi=True, admin=True)
    s.text(1648, 757, "P.I.", size=12.5, anchor="start")
    s.text(
        1470,
        824,
        "on an sso_managed group the IdP must assert her membership first",
        size=12,
        colour=DIM,
    )

    # -- 4. who runs a group -------------------------------------------------
    s.line(40, 872, 1720, 872, colour=GREY, dashed=True, amount=1.2)
    s.text(40, 912, "who runs a group", size=22, anchor="start")

    avatar(s, 150, 1004, 34, "SA", ORANGE, ring=GOLD)
    s.text(150, 1064, "sysadmin", size=16, weight="bold")
    s.text(150, 1086, "creates / deletes groups", size=13, colour=DIM)
    s.text(150, 1104, "designates the P.I.", size=13, colour=DIM)

    s.rect(Box(420, 930, 740, 240, VIOLET, "", ()), dashed=True)
    group_glyph(s, 448, 960, 9)
    s.text(474, 966, "korbel-lab", size=18, weight="bold", anchor="start")
    org = (
        (520, "C", "carol", True, True, GREEN, "P.I."),
        (680, "D", "dave", False, True, BLUE, "group admin"),
        (840, "E", "erin", False, False, YELLOW, "member"),
        (1000, "F", "frank", False, False, PINK, "member"),
    )
    for ox, ini, name, pi, adm, fill, role in org:
        avatar(s, ox, 1066, 32, ini, fill, pi=pi, admin=adm)
        s.text(ox, 1124, name, size=15, weight="bold")
        s.text(ox, 1144, role, size=12.5, colour=DIM)
    s.arc(546, 1040, 656, 1040, lift=-46)
    s.text(601, 1008, "promotes", size=12.5, colour=DIM)
    s.arrow(188, 994, 480, 1060, colour=INK)
    s.text(350, 1012, "designates the P.I.", size=12.5, colour=DIM)
    s.arrow(178, 966, 414, 946, colour=INK)
    s.text(300, 944, "creates", size=12.5, colour=DIM)

    shield(s, 1204, 956, 8)
    s.text(1224, 962, "group admins can", size=18, weight="bold", anchor="start")
    acts = (
        "add and remove members",
        "promote and demote admins",
        "rename, edit the description",
        "manage the sharing of projects",
        "that the group owns",
    )
    for i, line in enumerate(acts):
        s.text(
            1224,
            1000 + i * 26 + (4 if i == 4 else 0),
            line,
            size=14.5,
            anchor="start",
            colour=INK if i != 4 else DIM,
        )
    s.lock(1480, 1073, 10)

    # the guards, as three small scenes
    gy = 1196
    avatar(s, 70, gy + 30, 18, "D", BLUE, admin=True)
    s.arc(94, gy + 14, 94, gy + 46, lift=-26, colour=RED)
    s.cross(122, gy + 30, size=9)
    s.text(150, gy + 26, "no self-demotion", size=14.5, weight="bold", anchor="start")
    s.text(150, gy + 46, "an admin cannot demote themselves", size=12.5, colour=DIM, anchor="start")

    shield(s, 566, gy + 22, 11)
    s.text(596, gy + 26, "a group keeps at least 1 admin", size=14.5, weight="bold", anchor="start")
    s.text(596, gy + 46, "only a sysadmin may override it", size=12.5, colour=DIM, anchor="start")

    avatar(s, 1090, gy + 30, 18, "F", PINK, ghost=True)
    s.cross(1090, gy + 30, size=8)
    s.text(1124, gy + 26, "removing a member", size=14.5, weight="bold", anchor="start")
    s.text(
        1124,
        gy + 46,
        "also drops their admin role and clears P.I.",
        size=12.5,
        colour=DIM,
        anchor="start",
    )

    # -- 5. where it happens ------------------------------------------------
    s.line(40, 1290, 1720, 1290, colour=GREY, dashed=True, amount=1.2)
    s.text(40, 1330, "where it happens", size=22, anchor="start")
    mocks = (
        (40, _mock_admin, "Admin > Groups", "sysadmin: every group"),
        (463, _mock_my_groups, "My Groups page", "self-service: your groups"),
        (886, _mock_permissions, "Project permissions", "the Groups section"),
        (1309, _mock_profile, "Profile", "crown = P.I., shield = group admin"),
    )
    for mx, fn, title, sub in mocks:
        fn(s, mx, 1356, 405, 196)
        s.text(mx + 202, 1582, title, size=15, weight="bold")
        s.text(mx + 202, 1602, sub, size=12.5, colour=DIM)

    s.text(
        40,
        1650,
        "The identity provider owns who is in an SSO group; a person owns who administers it.",
        size=15,
        anchor="start",
        colour=DIM,
    )
    _unshift(s)
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-png", action="store_true", help="skip the browser PNG render")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT,
        help="output stem (default docs/images/user-groups); use a scratch dir to preview PNGs",
    )
    args = parser.parse_args()

    write(build_sharing_model(), args.out, "sharing_model", png=not args.no_png)
    write(build_saml_sync(), args.out, "saml_sync", png=not args.no_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
