#!/usr/bin/env python3
"""Generate the hand-drawn telemetry architecture diagram.

Produces an Excalidraw-style SVG (sketchy strokes, hachure fills, the Virgil
handwriting face the Depictio viewer already ships) summarising what the
installation-telemetry feature does end to end.

Written as a generator rather than a checked-in binary so the diagram can be
corrected when the architecture moves — a stale picture of a privacy-sensitive
data flow is worse than no picture.

The randomness is seeded, so re-running produces a byte-identical SVG and the
image only changes when the drawing instructions do.

Usage::

    python scripts/gen_telemetry_diagram.py            # writes the .svg
    python scripts/gen_telemetry_diagram.py --check    # fails if stale
"""

from __future__ import annotations

import argparse
import base64
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_SVG = REPO_ROOT / "docs" / "images" / "telemetry-architecture.svg"
FONT_PATH = REPO_ROOT / "depictio" / "viewer" / "src" / "assets" / "fonts" / "Virgil.ttf"

W, H = 1740, 1080

# Depictio brand palette (mirrors DEPICTIO_COLORS in depictio/cli/depictio_cli.py).
INK = "#1e1e1e"
PURPLE = "#9966CC"
VIOLET = "#7A5DC7"
BLUE = "#6495ED"
ORANGE = "#F68B33"
GREEN = "#8BC34A"
YELLOW = "#F9CB40"
TEAL = "#45B8AC"
PINK = "#E6779F"
MUTED = "#6b6b6b"

rng = random.Random(20260727)


def jitter(amount: float = 1.6) -> float:
    return rng.uniform(-amount, amount)


def rough_line(x1, y1, x2, y2, stroke=INK, width=2.0, passes=2, wobble=1.7):
    """A line drawn like a pen stroke: two nearly-coincident curved passes."""
    out = []
    for _ in range(passes):
        mx = (x1 + x2) / 2 + jitter(wobble * 2)
        my = (y1 + y2) / 2 + jitter(wobble * 2)
        out.append(
            f'<path d="M {x1 + jitter(wobble):.1f} {y1 + jitter(wobble):.1f} '
            f"Q {mx:.1f} {my:.1f} "
            f'{x2 + jitter(wobble):.1f} {y2 + jitter(wobble):.1f}" '
            f'fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linecap="round"/>'
        )
    return "".join(out)


def hachure(x, y, w, h, colour, gap=9, angle=-45, width=1.5, opacity=0.5):
    """Excalidraw's diagonal-line fill, clipped to the shape."""
    cid = f"clip{rng.randrange(1 << 30)}"
    lines = []
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    span = int((w + h) / gap) + 2
    for i in range(-span, span):
        ox, oy = x + i * gap, y
        x1, y1 = ox - dx * (w + h), oy - dy * (w + h)
        x2, y2 = ox + dx * (w + h), oy + dy * (w + h)
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{colour}" stroke-width="{width}" stroke-linecap="round"/>'
        )
    return (
        f'<defs><clipPath id="{cid}">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>'
        f"</clipPath></defs>"
        f'<g clip-path="url(#{cid})" opacity="{opacity}">{"".join(lines)}</g>'
    )


def rough_rect(x, y, w, h, stroke=INK, fill=None, width=2.2, fill_opacity=0.42, gap=9):
    """A rectangle whose corners overshoot slightly, as a hand-drawn one does."""
    parts = []
    if fill:
        parts.append(hachure(x, y, w, h, fill, gap=gap, opacity=fill_opacity))
    o = 3  # corner overshoot
    parts.append(rough_line(x - jitter(1), y, x + w + o, y, stroke, width))
    parts.append(rough_line(x + w, y - jitter(1), x + w, y + h + o, stroke, width))
    parts.append(rough_line(x + w + jitter(1), y + h, x - o, y + h, stroke, width))
    parts.append(rough_line(x, y + h + jitter(1), x, y - o, stroke, width))
    return "".join(parts)


def arrow(x1, y1, x2, y2, stroke=INK, width=2.4, head=15):
    """A sketched arrow with a two-stroke head."""
    body = rough_line(x1, y1, x2, y2, stroke, width, passes=2, wobble=1.2)
    ang = math.atan2(y2 - y1, x2 - x1)
    a1 = ang + math.radians(158)
    a2 = ang - math.radians(158)
    h1 = rough_line(
        x2, y2, x2 + head * math.cos(a1), y2 + head * math.sin(a1), stroke, width, 1, 0.7
    )
    h2 = rough_line(
        x2, y2, x2 + head * math.cos(a2), y2 + head * math.sin(a2), stroke, width, 1, 0.7
    )
    return body + h1 + h2


def text(x, y, s, size=19, colour=INK, anchor="start", weight="normal", opacity=1.0):
    esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<text x="{x}" y="{y}" font-family="Virgil, Segoe Print, Comic Sans MS, cursive" '
        f'font-size="{size}" fill="{colour}" text-anchor="{anchor}" '
        f'font-weight="{weight}" opacity="{opacity}">{esc}</text>'
    )


def lines(x, y, rows, size=17, colour=MUTED, step=26, anchor="start"):
    return "".join(text(x, y + i * step, r, size, colour, anchor) for i, r in enumerate(rows))


def font_face() -> str:
    """Embed Virgil so the drawing keeps its handwriting on any machine."""
    if not FONT_PATH.exists():
        print(f"warning: {FONT_PATH} missing; falling back to system fonts", file=sys.stderr)
        return ""
    b64 = base64.b64encode(FONT_PATH.read_bytes()).decode("ascii")
    return (
        "<style>@font-face{font-family:'Virgil';"
        f"src:url(data:font/ttf;base64,{b64}) format('truetype');"
        "font-display:block;}</style>"
    )


def build() -> str:
    p: list[str] = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Depictio anonymous installation telemetry architecture">'
    )
    p.append(font_face())
    p.append(f'<rect width="{W}" height="{H}" fill="#fdfdfc"/>')

    # ── Title ────────────────────────────────────────────────────────────────
    p.append(text(56, 74, "Anonymous installation telemetry", 40, INK, weight="bold"))
    p.append(
        text(
            56,
            112,
            "How many Depictio installations exist — without learning anything about them",
            21,
            MUTED,
        )
    )
    p.append(rough_line(56, 132, 1080, 132, PURPLE, 2.5, 2, 2.2))

    # ── 1. Sources ───────────────────────────────────────────────────────────
    p.append(text(56, 186, "1 · WHO REPORTS", 17, PURPLE, weight="bold"))
    sources = [
        (BLUE, "Docker Compose", ["API server", 'kind = "docker-compose"']),
        (VIOLET, "Kubernetes / Helm", ["API server", 'kind = "kubernetes"']),
        (TEAL, "depictio-cli", ["user's machine", "one event per command"]),
    ]
    sy = 210
    for i, (col, name, sub) in enumerate(sources):
        y = sy + i * 132
        p.append(rough_rect(56, y, 300, 108, INK, col))
        p.append(text(76, y + 42, name, 23, INK, weight="bold"))
        p.append(lines(76, y + 70, sub, 16, MUTED, 23))
        # Each source feeds the shared core straight across from its own row.
        p.append(arrow(366, y + 54, 450, y + 54))

    # ── 2. Shared core / gates ───────────────────────────────────────────────
    p.append(text(462, 186, "2 · WHAT IT REFUSES TO SEND", 17, PURPLE, weight="bold"))
    p.append(rough_rect(462, 210, 470, 504, INK, None))
    p.append(text(486, 248, "depictio/telemetry/", 24, INK, weight="bold"))
    p.append(text(486, 274, "shared by the server and the CLI", 16, MUTED))

    p.append(rough_rect(486, 292, 422, 118, INK, ORANGE, fill_opacity=0.30))
    p.append(text(506, 326, "kill switches", 20, INK, weight="bold"))
    p.append(
        lines(
            506,
            352,
            ["DO_NOT_TRACK · TELEMETRY_ENABLED=false", "CI · pytest · MONGODB_WIPE"],
            16,
            MUTED,
            24,
        )
    )

    p.append(rough_rect(486, 428, 422, 128, INK, GREEN, fill_opacity=0.30))
    p.append(text(506, 462, "counts → buckets", 20, INK, weight="bold"))
    p.append(text(506, 492, "37 users", 18, MUTED))
    p.append(arrow(590, 486, 646, 486, GREEN, 2.0, 11))
    p.append(text(656, 492, '"11–50"', 18, INK))
    p.append(text(506, 522, "exact sizes fingerprint a deployment", 15, MUTED))

    p.append(rough_rect(486, 574, 422, 118, INK, PINK, fill_opacity=0.30))
    p.append(text(506, 608, "argv → allowlist", 20, INK, weight="bold"))
    p.append(text(506, 636, "process --config /home/alice/x.yaml", 15, MUTED))
    p.append(arrow(506, 650, 560, 650, PINK, 2.0, 11))
    p.append(text(572, 656, '"data process"', 17, INK))

    p.append(arrow(942, 460, 1024, 460))

    # ── 3. Send guard ────────────────────────────────────────────────────────
    p.append(text(1038, 186, "3 · EXACTLY ONCE", 17, PURPLE, weight="bold"))
    p.append(rough_rect(1038, 210, 300, 250, INK, YELLOW, fill_opacity=0.28))
    p.append(text(1060, 250, "send guard", 24, INK, weight="bold"))
    p.append(text(1060, 276, "atomic insert in MongoDB", 16, MUTED))
    # Twelve boxes, matching the twelve concurrent workers the guard test asserts on.
    for i in range(12):
        cx = 1074 + (i % 6) * 42
        cy = 298 + (i // 6) * 30
        p.append(rough_rect(cx, cy, 24, 22, INK, None, width=1.6))
    p.append(text(1060, 372, "12 workers × N replicas", 16, MUTED))
    p.append(arrow(1188, 386, 1188, 410, INK, 2.2, 12))
    p.append(text(1188, 444, "1 send / day", 22, INK, anchor="middle", weight="bold"))

    p.append(
        lines(
            1038,
            492,
            [
                "NOT gated on should_initialize —",
                "that is true only on the first-ever",
                "boot, so it would report once and",
                "then go quiet forever.",
            ],
            15,
            MUTED,
            23,
        )
    )
    p.append(rough_rect(1038, 596, 300, 118, INK, None, width=1.8))
    p.append(text(1058, 630, "instance ID", 20, INK, weight="bold"))
    p.append(
        lines(
            1058,
            658,
            ["own collection, so a dev", "wipe cannot mint a new one"],
            15,
            MUTED,
            22,
        )
    )

    p.append(arrow(1348, 340, 1420, 340))

    # ── 4. Destination ───────────────────────────────────────────────────────
    p.append(text(1432, 186, "4 · WHERE IT LANDS", 17, PURPLE, weight="bold"))
    p.append(rough_rect(1432, 210, 252, 250, INK, PURPLE, fill_opacity=0.26))
    p.append(text(1452, 250, "PostHog", 26, INK, weight="bold"))
    p.append(text(1452, 278, "Cloud EU — data stays", 15, MUTED))
    p.append(text(1452, 298, "inside the EEA", 15, MUTED))
    p.append(rough_line(1452, 314, 1664, 314, INK, 1.6, 1, 1.2))
    p.append(
        lines(
            1452,
            340,
            ["server_install  (once)", "server_heartbeat (daily)", "cli_command"],
            16,
            INK,
            26,
        )
    )
    p.append(text(1452, 428, "no person profiles", 16, TEAL))

    # ── Bottom band ──────────────────────────────────────────────────────────
    p.append(rough_line(56, 758, 1684, 758, PURPLE, 2.2, 2, 2.4))

    p.append(rough_rect(56, 790, 500, 246, INK, None, width=2.0))
    p.append(text(80, 830, "never sent", 24, INK, weight="bold"))
    p.append(
        lines(
            80,
            864,
            [
                "emails · usernames · project names",
                "dashboard titles · column names",
                "hostnames · URLs · IP addresses",
                "file paths · S3 endpoints · buckets",
                "tokens · CLI arguments · your data",
            ],
            16,
            MUTED,
            27,
        )
    )
    p.append(text(80, 1014, "schema forbids undeclared fields", 15, PINK))

    p.append(rough_rect(600, 790, 500, 246, INK, None, width=2.0))
    p.append(text(624, 830, "verify it yourself", 24, INK, weight="bold"))
    p.append(
        lines(
            624,
            864,
            [
                "GET /utils/telemetry/preview",
                "(admin) returns the real payload,",
                "built by the code that sends it.",
                "",
                "TELEMETRY_DEBUG=true logs the",
                "payload instead of sending it.",
            ],
            16,
            MUTED,
            25,
        )
    )

    p.append(rough_rect(1144, 790, 540, 246, INK, None, width=2.0))
    p.append(text(1168, 830, "turn it off", 24, INK, weight="bold"))
    p.append(rough_rect(1168, 852, 492, 46, INK, ORANGE, fill_opacity=0.22, gap=7))
    p.append(text(1186, 882, "DEPICTIO_TELEMETRY_ENABLED=false", 18, INK))
    p.append(rough_rect(1168, 912, 492, 46, INK, ORANGE, fill_opacity=0.22, gap=7))
    p.append(text(1186, 942, "DO_NOT_TRACK=1", 18, INK))
    p.append(
        lines(
            1168,
            990,
            ["either one is enough · auto-off in CI,", "under pytest, and on a database wipe"],
            15,
            MUTED,
            24,
        )
    )

    p.append("</svg>")
    return "".join(p)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args()

    svg = build()

    if args.check:
        if not OUT_SVG.exists() or OUT_SVG.read_text(encoding="utf-8") != svg:
            print(f"{OUT_SVG} is stale. Run: python scripts/gen_telemetry_diagram.py")
            return 1
        print(f"{OUT_SVG} is up to date.")
        return 0

    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUT_SVG} ({len(svg) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
