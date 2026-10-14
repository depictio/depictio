#!/usr/bin/env python3
"""Hand-drawn schema of the SAML SSO login flow (PR #968).

SP-initiated login, drawn as the screens the user sees and the envelope that
travels between them: the Depictio login page, the IdP page, the signed
SAMLResponse, the URL bar carrying the ticket in its fragment, the viewer that
redeems it. Built on the shared sketch toolkit; the seeded jitter makes re-runs
byte-identical, so the picture can be corrected in a diff when the flow moves.

Usage::

    python dev/diagrams/saml_login.py            # writes docs/images/*.svg/.png
    python dev/diagrams/saml_login.py --no-png   # svg only (no browser render)
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
    GREY,
    INK,
    LIGHT_GREY,
    ORANGE,
    PINK,
    RED,
    RED_INK,
    VIOLET,
    WHITE,
    YELLOW,
    Box,
    Sketch,
    browser,
    button,
    circle,
    ellipse,
    field,
    page,
    tick,
    write,
)

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "saml-login"

W, H = 1680, 1470


# -- glyphs local to this diagram ---------------------------------------------


def badge(s: Sketch, cx: float, cy: float, n: int) -> None:
    """A numbered step marker: the reading order of the whole picture."""
    s.dot(cx, cy, 14, fill=GOLD, width=1.8)
    s.text(cx, cy + 5.5, str(n), size=16, weight="bold")


def screen_bg(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """The grey page behind a login card, inside a browser's content area."""
    s.shade(x + 3, y + 30, w - 6, h - 33, fill=LIGHT_GREY, opacity=1.0)


def url_pill(s: Sketch, x: float, y: float, w: float, text: str) -> None:
    s.rect(Box(x, y + 5, w, 18, WHITE, "", ()), colour=GREY)
    s.text(x + 8, y + 18, f"`{text}`", size=11, anchor="start", colour=DIM)


def cursor(s: Sketch, x: float, y: float) -> None:
    """A mouse pointer: the click that starts everything."""
    s.poly(
        [(x, y), (x, y + 24), (x + 6, y + 18), (x + 11, y + 28), (x + 15, y + 26), (x + 10, y + 16)]
        + [(x + 18, y + 16)],
        fill=WHITE,
        amount=0.5,
    )


def key_glyph(s: Sketch, cx: float, cy: float) -> None:
    circle(s, cx - 6, cy, 5, WHITE)
    s.line(cx - 1, cy, cx + 10, cy, amount=0.3, passes=1, width=1.6)
    s.line(cx + 6, cy, cx + 6, cy + 4, amount=0.2, passes=1, width=1.5)
    s.line(cx + 10, cy, cx + 10, cy + 4, amount=0.2, passes=1, width=1.5)


def server_rack(s: Sketch, x: float, y: float, w: float = 54, row: float = 22) -> None:
    h = row - 4
    for i in range(3):
        s.rect(Box(x, y + i * row, w, h, WHITE, "", ()))
        s.dot(x + 10, y + i * row + h / 2, 3, fill=BLUE_INK if i != 1 else GOLD, width=1.1)
        s.line(
            x + 20,
            y + i * row + h / 2,
            x + w - 8,
            y + i * row + h / 2,
            colour=GREY,
            amount=0.3,
            passes=1,
        )


def cylinder(s: Sketch, cx: float, top: float, w: float, h: float, fill: str) -> None:
    """A store: a can with a lid, the shape of "something is kept here"."""
    left, right, bottom = cx - w / 2, cx + w / 2, top + h
    s.poly(
        [(left, top), (right, top), (right, bottom), (left, bottom)],
        fill=fill,
        edges=(1, 3),
        amount=1.0,
    )
    n = 14
    arc = [
        (cx + (w / 2) * math.cos(math.pi * i / n), bottom + 10 * math.sin(math.pi * i / n))
        for i in range(n + 1)
    ]
    s.curve(arc, colour=INK)
    ellipse(s, cx, top, w / 2, 10, fill)


def envelope(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """The signed SAMLResponse: a sealed letter."""
    s.rect(Box(x, y, w, h, YELLOW, "", ()))
    cx = x + w / 2
    s.line(x + 2, y + 2, cx, y + h * 0.58, amount=0.8, passes=1)
    s.line(x + w - 2, y + 2, cx, y + h * 0.58, amount=0.8, passes=1)
    circle(s, cx, y + h * 0.58, 9, RED_INK)
    s.text(cx, y + h * 0.58 + 4.5, "S", size=12, weight="bold")


def avatar(s: Sketch, cx: float, cy: float) -> None:
    circle(s, cx, cy - 8, 9, WHITE)
    s.poly(
        [(cx - 17, cy + 20), (cx - 14, cy + 6), (cx + 14, cy + 6), (cx + 17, cy + 20)],
        fill=WHITE,
        amount=0.8,
    )


def ticket(s: Sketch, x: float, y: float, w: float = 46, h: float = 30) -> None:
    """The magic-link ticket: a stub with a notch on each side."""
    s.rect(Box(x, y, w, h, GOLD, "", ()))
    for nx in (x, x + w):
        s.dot(nx, y + h / 2, 5, fill=WHITE, width=1.4)
    s.line(x + 14, y + 4, x + 14, y + h - 4, amount=0.3, passes=1, dashed=True, width=1.2)
    s.line(x + 22, y + 11, x + w - 10, y + 11, colour=DIM, amount=0.3, passes=1, width=1.2)
    s.line(x + 22, y + 19, x + w - 14, y + 19, colour=DIM, amount=0.3, passes=1, width=1.2)


def check_row(s: Sketch, x: float, y: float, ok: bool, head: str, sub: str) -> None:
    """One validation, as a tick (or a cross) and what it asserts."""
    if ok:
        tick(s, x + 10, y + 6, size=9)
    else:
        s.cross(x + 10, y + 8, size=8)
    s.text(x + 34, y + 10, head, size=14, anchor="start")
    if sub:
        s.text(x + 34, y + 30, sub, size=12.5, anchor="start", colour=DIM)


def mini_dashboard(s: Sketch, x: float, y: float, w: float, h: float) -> None:
    """The place the user wanted to be: a browser holding a dashboard."""
    browser(s, x, y, w, h)
    inner = w - 24
    card = (inner - 12) / 2
    s.rect(Box(x + 12, y + 40, card, 30, GREEN, "", ()))
    s.rect(Box(x + 24 + card, y + 40, card, 30, YELLOW, "", ()))
    bars = (0.5, 0.8, 0.6, 0.9, 0.7)
    base = y + h - 14
    bw = inner / len(bars) - 6
    for i, v in enumerate(bars):
        bh = (h - 96) * v
        s.rect(Box(x + 12 + i * (bw + 6), base - bh, bw, bh, BLUE, "", ()))


# -- the diagram --------------------------------------------------------------


def build_login_flow() -> Sketch:
    s = Sketch(W, H, seed=968)
    s.heading(
        40,
        52,
        "Signing in with SAML",
        "SP-initiated: the browser goes out to the IdP and comes back with a signed assertion, "
        "then trades a one-use ticket for a session",
    )

    # ---- 1. the Depictio login page -------------------------------------
    bx, by, bw, bh = 40, 128, 410, 340
    browser(s, bx, by, bw, bh)
    screen_bg(s, bx, by, bw, bh)
    url_pill(s, bx + 70, by, bw - 90, "depictio.example.org/auth")
    card = Box(bx + 30, by + 42, bw - 60, 282, WHITE, "", ())
    s.rect(card, colour=GREY)
    s.text(card.cx, by + 72, "Sign in", size=18, weight="bold")
    sso = Box(bx + 60, by + 86, bw - 120, 34, YELLOW, "", ())
    halo = Box(sso.x - 6, sso.y - 6, sso.w + 12, sso.h + 12, "none", "", ())
    s.rect(halo, colour=BLUE_INK, dashed=True)
    s.rect(sso)
    key_glyph(s, sso.x + 26, sso.cy)
    s.text(sso.cx + 12, sso.cy + 5, "Sign in with SSO", size=14, weight="bold")
    cursor(s, sso.right - 40, sso.cy + 4)
    s.text(card.cx, by + 150, "or with your email", size=11, colour=DIM)
    s.line(card.x + 20, by + 146, card.cx - 60, by + 146, colour=GREY, amount=0.3, passes=1)
    s.line(card.cx + 60, by + 146, card.right - 20, by + 146, colour=GREY, amount=0.3, passes=1)
    field(s, bx + 60, by + 158, bw - 120, "Email", "name@example.org")
    field(s, bx + 60, by + 210, bw - 120, "Password", "••••••••")
    button(s, bx + 60, by + 266, bw - 120, "Sign in", enabled=False)
    badge(s, bx + 2, by - 6, 1)
    s.text(
        bx,
        by + bh + 28,
        "button text: `DEPICTIO_AUTH_SAML_LOGIN_LABEL`",
        size=13,
        anchor="start",
        colour=DIM,
    )

    # ---- 1 -> API ---------------------------------------------------------
    s.arrow(bx + bw + 2, 230, 588, 230)
    s.text(519, 202, "click:", size=13, colour=DIM)
    s.text(519, 220, "full-page GET", size=13, colour=DIM)

    # ---- the API handler --------------------------------------------------
    api = Box(590, 128, 420, 182, YELLOW, "", ())
    s.rect(api)
    server_rack(s, 612, 152)
    s.text(692, 172, "Depictio API", size=18, anchor="start", weight="bold")
    s.text(692, 196, "`GET /auth/saml/login`", size=14, anchor="start")
    lines = ("builds the AuthnRequest", "keeps its request id, one-shot", "answers 302 to the IdP")
    for i, line in enumerate(lines):
        s.text(612, 236 + i * 22, line, size=14, anchor="start", colour=DIM)

    # the one-shot store
    cylinder(s, 660, 380, 84, 52, ORANGE)
    s.arrow(660, 312, 660, 366, dashed=True, colour=DIM)
    s.text(648, 346, "stores the id", size=13, anchor="end", colour=DIM)
    s.text(722, 392, "auth state store", size=15, anchor="start", weight="bold")
    s.text(722, 414, "Redis `SET NX EX`, expires in 10 min", size=13, anchor="start", colour=DIM)
    s.text(722, 436, "in-process dict if Redis is down", size=13, anchor="start", colour=DIM)

    # ---- API -> IdP -------------------------------------------------------
    s.arrow(1012, 230, 1198, 230)
    s.text(1105, 194, "302 redirect", size=14, colour=DIM)
    s.text(1105, 212, "carrying the AuthnRequest", size=12.5, colour=DIM)
    s.text(1105, 256, "(HTTP-Redirect binding)", size=12.5, colour=DIM)

    # ---- 2. the IdP login page ----------------------------------
    kx, ky, kw, kh = 1200, 128, 440, 340
    browser(s, kx, ky, kw, kh)
    screen_bg(s, kx, ky, kw, kh)
    url_pill(s, kx + 70, ky, kw - 90, "<idp>/realms/<realm>/protocol/saml")
    kcard = Box(kx + 40, ky + 42, kw - 80, 282, WHITE, "", ())
    s.rect(kcard, colour=GREY)
    s.text(kcard.cx, ky + 72, "Sign in to your account", size=17, weight="bold")
    s.text(kcard.cx, ky + 92, "realm: example", size=12, colour=DIM)
    field(s, kx + 70, ky + 106, kw - 140, "Username or email", "jdoe")
    field(s, kx + 70, ky + 158, kw - 140, "Password", "••••••••")
    button(s, kx + 70, ky + 226, kw - 140, "Sign In", enabled=True)
    s.text(kcard.cx, ky + 292, "any SAML IdP", size=12, colour=DIM)
    badge(s, kx + 2, ky - 6, 2)

    # ---- IdP -> the signed response ---------------------------------------
    s.arrow(1420, 472, 1420, 566)
    s.text(1406, 506, "authenticates the user,", size=13, anchor="end", colour=DIM)
    s.text(1406, 524, "signs the assertion", size=13, anchor="end", colour=DIM)

    envelope(s, 1256, 580, 118, 78)
    s.text(1400, 604, "browser form POST", size=15, anchor="start", weight="bold")
    s.text(1400, 626, "`SAMLResponse`, base64 XML", size=13, anchor="start", colour=DIM)
    s.text(1400, 648, "the assertion inside is signed", size=13, anchor="start", colour=DIM)

    # the envelope, opened: what the ACS reads
    s.arrow(1315, 664, 1315, 696, dashed=True, colour=DIM)
    doc = Box(1230, 700, 410, 214, WHITE, "", ())
    s.rect(doc, colour=GREY)
    s.text(1250, 724, "the POST: what the ACS reads", size=14, anchor="start", weight="bold")
    s.shade(1242, 744, 386, 30, fill=BLUE, opacity=1.0)
    s.shade(1242, 780, 386, 30, fill=YELLOW, opacity=1.0)
    s.shade(1242, 816, 386, 30, fill=YELLOW, opacity=1.0)
    s.text(1252, 764, "`<Signature>…</Signature>`", size=14, anchor="start")
    s.text(1626, 764, "vs the IdP cert", size=12.5, anchor="end", colour=DIM)
    s.text(1252, 800, "`<Attribute Name=…>`", size=14, anchor="start")
    s.text(1626, 800, "email, if configured", size=12.5, anchor="end", colour=DIM)
    s.text(1252, 836, "`<NameID>…</NameID>`", size=14, anchor="start")
    s.text(1626, 836, "else the NameID", size=12.5, anchor="end", colour=DIM)
    s.text(1250, 868, "`InResponseTo`: the id we stored", size=13, anchor="start", colour=DIM)
    s.text(1250, 896, "`RelayState`: echoed back, ignored", size=13, anchor="start", colour=DIM)

    # ---- 3. the ACS ---------------------------------------------------------
    s.arrow(1226, 632, 1114, 632)
    s.text(1170, 608, "POST", size=14, colour=DIM)
    acs = Box(560, 560, 552, 392, GREEN, "", ())
    s.rect(acs)
    s.text(584, 590, "ACS: validates before it trusts", size=18, anchor="start", weight="bold")
    s.text(584, 614, "`POST /auth/saml/callback`", size=14, anchor="start")
    check_row(
        s, 584, 640, True, "InResponseTo is an id WE issued", "consumed once: a replay is refused"
    )
    check_row(s, 584, 692, True, "assertion signature verified", "against the IdP certificate")
    check_row(s, 584, 744, True, "email from the attribute or the NameID", "")
    check_row(
        s, 584, 796, False, "RelayState echoed by the IdP", "ignored: the path comes from our store"
    )
    check_row(
        s, 584, 848, True, "redirect target: a same-origin path", "relative only, never `//host`"
    )
    s.line(584, 898, 1088, 898, colour=GREY, amount=0.4, passes=1, width=1.2)
    s.cross(594, 922, size=7)
    s.text(
        612,
        927,
        "any check fails: 303 to `/auth?error=saml_failed`",
        size=13,
        anchor="start",
        colour=RED,
    )
    badge(s, 562, 558, 3)

    # the ACS reads the store
    s.arrow(700, 556, 700, 470, dashed=True, colour=DIM)
    s.text(712, 520, "consumes the id: GETDEL", size=13, anchor="start", colour=DIM)

    # ---- ACS -> user --------------------------------------------------------
    s.arrow(558, 750, 492, 750)
    s.text(525, 730, "email", size=13, colour=DIM)

    # ---- 4. the user --------------------------------------------------------
    usr = Box(40, 560, 450, 392, PINK, "", ())
    s.rect(usr)
    avatar(s, 84, 606)
    s.text(122, 598, "`create_or_get_sso_user`", size=15, anchor="start", weight="bold")
    s.text(122, 620, "the login door for IdP-verified emails", size=13, anchor="start", colour=DIM)
    tick(s, 70, 668, size=9)
    s.text(94, 674, "known email: that user signs in", size=14, anchor="start")
    tick(s, 70, 712, size=9)
    s.text(94, 718, "unknown email: account created", size=14, anchor="start")
    s.text(94, 738, "only while registration is open", size=12.5, anchor="start", colour=DIM)
    s.cross(70, 774, size=8)
    s.text(94, 780, "unknown, and `registration_disabled`:", size=14, anchor="start")
    s.text(94, 800, "refused, no account is made", size=12.5, anchor="start", colour=DIM)
    s.rect(Box(94, 816, 360, 26, WHITE, "", ()), colour=GREY)
    s.text(
        106, 834, "303 `/auth?error=registration_disabled`", size=12.5, anchor="start", colour=RED
    )
    # the muted forward pointer
    s.rect(Box(60, 866, 410, 66, "none", "", ()), colour=GREY, dashed=True)
    s.dot(86, 899, 11, fill=WHITE, colour=GREY, width=1.5)
    s.text(86, 905, "+", size=17, colour=DIM)
    s.text(112, 892, "PR #972 later hooks group and profile", size=13.5, anchor="start", colour=DIM)
    s.text(112, 914, "sync in here, once the user is known", size=13.5, anchor="start", colour=DIM)
    badge(s, 42, 558, 4)

    # ---- 5. the redirect: ticket in the fragment ---------------------------
    s.arrow(262, 956, 262, 1034)
    ticket(s, 288, 972)
    s.text(350, 984, "303 redirect", size=14, anchor="start", weight="bold")
    s.text(350, 1004, "ticket: 2 minutes, single use", size=13, anchor="start", colour=DIM)

    vx, vy, vw, vh = 40, 1040, 800, 316
    browser(s, vx, vy, vw, vh)
    s.line(vx, vy + 76, vx + vw, vy + 76, amount=0.8, passes=1)
    s.text(vx + 24, vy + 60, "<", size=18, colour=DIM)
    s.text(vx + 52, vy + 60, ">", size=18, colour=DIM)
    s.rect(Box(vx + 80, vy + 38, vw - 100, 30, WHITE, "", ()), colour=GREY)
    cw = 8.45  # monospace advance at size 16
    ux = vx + 94
    base_url = "https://depictio.example.org/auth/magic"
    frag = "#ticket=<ticket>&next=/dashboards"
    fx = ux + len(base_url) * cw
    s.shade(fx + 3, vy + 42, len(frag) * cw + 8, 22, fill=GOLD, opacity=0.75, colour=RED)
    s.text(ux, vy + 59, f"`{base_url}`", size=16, anchor="start")
    s.text(fx + 7, vy + 59, f"`{frag}`", size=16, anchor="start")
    badge(s, vx + 2, vy - 6, 5)

    # the callout: the fragment never leaves the browser
    cb = Box(330, 1136, 480, 124, YELLOW, "", ())
    s.rect(cb, colour=GREY, dashed=True)
    s.arrow(fx + 130, cb.y - 2, fx + 130, vy + 74, colour=RED)
    s.text(cb.cx, cb.y + 26, "the #fragment is never sent to", size=14.5, weight="bold")
    for cx, label in ((cb.x + 90, "servers"), (cb.cx, "proxies"), (cb.right - 90, "access logs")):
        if label == "servers":
            server_rack(s, cx - 24, cb.y + 38, 48, row=16)
        elif label == "proxies":
            s.rect(Box(cx - 28, cb.y + 50, 56, 36, WHITE, "", ()))
            s.arrow(cx - 20, cb.y + 62, cx + 20, cb.y + 62)
            s.arrow(cx + 20, cb.y + 74, cx - 20, cb.y + 74)
        else:
            page(s, cx - 15, cb.y + 42, 30, 46)
        s.cross(cx, cb.y + 66, size=15)
        s.text(cx, cb.y + 108, label, size=12.5, colour=DIM)

    # ---- 6. the viewer redeems the ticket ----------------------------------
    sc = Box(64, 1136, 238, 124, WHITE, "", ())
    s.rect(sc, colour=GREY)
    s.dot(sc.cx, sc.y + 40, 16, dashed=True, width=3.2)
    s.text(sc.cx, sc.y + 84, "Signing you in…", size=15, weight="bold")
    s.text(sc.cx, sc.y + 104, "Completing sign-in…", size=12, colour=DIM)
    badge(s, sc.x, sc.y - 2, 6)
    s.text(
        330,
        1290,
        "`MagicLinkCallback` reads the ticket, then strips the fragment",
        size=13.5,
        anchor="start",
    )
    s.text(
        330,
        1312,
        "`POST /auth/magic/exchange`: the ticket is burned, a session comes back",
        size=13.5,
        anchor="start",
        colour=DIM,
    )

    # ---- viewer -> dashboard ------------------------------------------------
    s.arrow(842, 1240, 996, 1240)
    s.text(919, 1204, "session stored,", size=13, colour=DIM)
    s.text(919, 1222, "then go to `next`", size=13, colour=DIM)
    mini_dashboard(s, 1000, 1130, 260, 190)
    s.text(1130, 1344, "the page you asked for", size=13, colour=DIM)

    # ---- setup, once --------------------------------------------------------
    st = Box(1296, 1040, 344, 316, WHITE, "", ())
    s.rect(st, colour=GREY, dashed=True)
    s.text(1316, 1070, "Setup, once", size=18, anchor="start", weight="bold")
    s.text(1316, 1090, "what the IdP admin registers", size=13, anchor="start", colour=DIM)
    tick(s, 1326, 1118, size=8)
    s.text(1346, 1124, "ACS URL, HTTP-POST binding", size=13.5, anchor="start")
    s.text(
        1346, 1144, "`…/depictio/api/v1/auth/saml/callback`", size=12.5, anchor="start", colour=DIM
    )
    tick(s, 1326, 1172, size=8)
    s.text(1346, 1178, "entity id", size=13.5, anchor="start")
    s.text(1346, 1198, "`DEPICTIO_AUTH_SAML_SP_ENTITY_ID`", size=12.5, anchor="start", colour=DIM)
    tick(s, 1326, 1226, size=8)
    s.text(1346, 1232, "sign assertions: on", size=13.5, anchor="start")
    page(s, 1318, 1252, 26, 34, fill=VIOLET)
    s.text(1356, 1268, "or import the SP metadata", size=13.5, anchor="start")
    s.text(1356, 1288, "`GET /auth/saml/metadata`", size=12.5, anchor="start", colour=DIM)
    s.line(1316, 1306, 1620, 1306, colour=GREY, amount=0.4, passes=1, width=1.2)
    s.text(
        1316, 1326, "and gives Depictio the IdP's entity id,", size=13, anchor="start", colour=DIM
    )
    s.text(
        1316,
        1344,
        "SSO URL and cert: `DEPICTIO_AUTH_SAML_IDP_*`",
        size=13,
        anchor="start",
        colour=DIM,
    )

    s.text(
        40,
        1420,
        "The session never rides in a URL: the API sees a signed assertion over POST, "
        "the viewer sees a 2-minute ticket only in the fragment.",
        size=14.5,
        anchor="start",
        colour=DIM,
    )
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-png", action="store_true", help="skip the browser PNG render")
    args = parser.parse_args()
    write(build_login_flow(), OUT, "flow", png=not args.no_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
