#!/usr/bin/env python3
"""Hand-drawn schema of the SAML SSO login flow (PR #968).

Built on the shared sketch toolkit; the seeded jitter makes re-runs
byte-identical, so the picture can be corrected in a diff when the flow moves.

Usage::

    python dev/diagrams/saml_login.py            # writes docs/images/*.svg/.png
    python dev/diagrams/saml_login.py --no-png   # svg only (no browser render)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sketch import (  # noqa: E402
    BLUE,
    DIM,
    GREEN,
    ORANGE,
    PINK,
    RED,
    VIOLET,
    YELLOW,
    Box,
    Sketch,
    write,
)

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "images" / "saml-login"

W, H = 1560, 760


def build_login_flow() -> Sketch:
    s = Sketch(W, H, seed=968)
    s.heading(
        40,
        52,
        "SAML SSO login (SP-initiated)",
        "the browser round-trips through the IdP, then lands in the viewer with a single-use ticket",
    )

    browser = Box(40, 150, 230, 150, BLUE, "Browser", ("user clicks", '"Sign in with EMBL"'))
    api = Box(
        500,
        150,
        330,
        170,
        YELLOW,
        "Depictio API",
        ("GET  /auth/saml/login", "POST /auth/saml/callback"),
    )
    idp = Box(
        1100, 150, 280, 150, VIOLET, "IdP (Keycloak)", ("SAML realm", "authenticates the user")
    )
    for b in (browser, api, idp):
        s.box(b)

    # 1. login -> AuthnRequest -> IdP
    s.arrow(browser.right, 190, api.x, 190)
    s.text(385, 176, "1  /login", size=14, colour=DIM)
    s.arrow(api.right, 190, idp.x, 190)
    s.text(965, 176, "2  AuthnRequest", size=14, colour=DIM)
    s.text(965, 208, "(redirect binding)", size=13, colour=DIM)

    # 3. IdP -> browser, routed above the boxes so it crosses nothing
    s.line(idp.x + 60, idp.y, idp.x + 60, 124, dashed=True, colour=DIM)
    s.line(idp.x + 60, 124, browser.cx, 124, dashed=True, colour=DIM)
    s.arrow(browser.cx, 124, browser.cx, browser.y, dashed=True, colour=DIM)
    s.text(
        660,
        114,
        "3  user signs in at the IdP, browser POSTs the signed SAMLResponse",
        size=14,
        colour=DIM,
    )
    s.arrow(browser.right, 270, api.x, 270)
    s.text(385, 256, "4  ACS", size=14, colour=DIM)

    # server-side checks
    checks = Box(
        500,
        470,
        330,
        230,
        GREEN,
        "ACS validates",
        (
            "InResponseTo is one WE issued",
            "(shared one-shot store, replay-safe)",
            "assertion signature vs IdP cert",
            "email from attribute or NameID",
            "RelayState from the IdP: ignored",
        ),
    )
    s.box(checks)
    s.arrow(api.cx, api.bottom, checks.cx, checks.y)

    store = Box(
        40,
        470,
        340,
        140,
        ORANGE,
        "auth state store",
        (
            "Redis SET NX EX / GETDEL",
            "in-process fallback if Redis is down",
            "request id -> relay path",
        ),
    )
    s.box(store)
    s.arrow(checks.x, 540, store.right, 540, dashed=True, colour=DIM)
    s.text(210, 640, "/login stores the id, the ACS consumes it once", size=13, colour=DIM)

    user = Box(
        960,
        470,
        420,
        230,
        PINK,
        "user + session",
        (
            "create_or_get_sso_user(email)",
            "(registration_disabled -> refused)",
            "magic-link ticket, 2 min, single use",
            "303 -> /auth/magic#ticket=...&next=/path",
            "fragment: never sent to servers or logs",
        ),
    )
    s.box(user)
    s.arrow(checks.right, 585, user.x, 585)
    s.text(895, 570, "5", size=14, colour=DIM)
    s.text(
        1170,
        730,
        "6  viewer's MagicLinkCallback redeems the ticket - no JWT in a URL",
        size=14,
        colour=RED,
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
