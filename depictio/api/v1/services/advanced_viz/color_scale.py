"""Python mirror of ``packages/depictio-react-core/src/utils/colorScale.ts``.

Exists for one job: choosing a text colour that survives on top of a heatmap
cell. A server-built figure has to bake its annotation colours in, so it needs
the same scale sampling and the same WCAG luminance rule the TypeScript
renderers use, or labels vanish into dark cells.

Stops are approximate on purpose — they feed contrast decisions and Plotly's own
interpolation, not colour-critical output — and are copied from the TSX so the
two cannot drift apart silently.
"""

from __future__ import annotations

import math

RGB = tuple[int, int, int]

#: Light (t=0) → dark (t=1). Mirrors SCALES in colorScale.ts.
SCALES: dict[str, list[tuple[float, RGB]]] = {
    "Blues": [
        (0.0, (247, 251, 255)),
        (0.25, (198, 219, 239)),
        (0.5, (107, 174, 214)),
        (0.75, (33, 113, 181)),
        (1.0, (8, 48, 107)),
    ],
    "Greens": [
        (0.0, (247, 252, 245)),
        (0.5, (116, 196, 118)),
        (1.0, (0, 68, 27)),
    ],
    "YlOrRd": [
        (0.0, (255, 255, 204)),
        (0.25, (255, 237, 160)),
        (0.5, (254, 178, 76)),
        (0.75, (240, 59, 32)),
        (1.0, (189, 0, 38)),
    ],
    "Viridis": [
        (0.0, (68, 1, 84)),
        (0.25, (59, 82, 139)),
        (0.5, (33, 145, 140)),
        (0.75, (94, 201, 98)),
        (1.0, (253, 231, 37)),
    ],
    "Tealgrn": [
        (0.0, (176, 242, 188)),
        (0.5, (56, 177, 148)),
        (1.0, (11, 84, 99)),
    ],
    "Sunsetdark": [
        (0.0, (252, 222, 156)),
        (0.5, (227, 109, 99)),
        (1.0, (122, 4, 102)),
    ],
}

#: WCAG crossover: above this luminance, dark text wins.
_LUMINANCE_PIVOT = 0.179


def _round_half_up(value: float) -> int:
    """Round .5 away from zero, as JavaScript's ``Math.round`` does.

    Python's built-in ``round`` uses banker's rounding, so a channel landing
    exactly on .5 — which happens at every midpoint between two stops — comes
    out one lower than the TypeScript renderer's. One RGB step is invisible, but
    a Python port that quietly disagrees with its TS original is the kind of
    drift these mirrors exist to prevent.
    """
    return math.floor(value + 0.5)


def sample_colorscale(name: str, t: float) -> RGB:
    """Colour at position ``t`` on a named scale, by linear interpolation."""
    stops = SCALES.get(name) or SCALES["Blues"]
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            span = (t1 - t0) or 1.0
            k = (t - t0) / span
            return (
                _round_half_up(c0[0] + (c1[0] - c0[0]) * k),
                _round_half_up(c0[1] + (c1[1] - c0[1]) * k),
                _round_half_up(c0[2] + (c1[2] - c0[2]) * k),
            )
    return stops[-1][1]


def _srgb_to_linear(channel: int) -> float:
    cs = channel / 255
    return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    r, g, b = rgb
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrasting_text(rgb: RGB) -> str:
    """Near-black or white, whichever has more contrast against ``rgb``."""
    return "#1a1a1a" if relative_luminance(rgb) > _LUMINANCE_PIVOT else "#ffffff"


def contrasting_text_for_value(name: str, t: float) -> str:
    """Text colour for a cell at position ``t`` on a named scale."""
    return contrasting_text(sample_colorscale(name, t))
