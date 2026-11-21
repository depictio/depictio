"""Colour-vision checks for the palettes: CVD simulation, CIEDE2000, WCAG contrast.

Pure stdlib on purpose (the models package is imported by the CLI). Used by the
palette tests and by anyone adding a palette to ``depictio_palettes.json``.

- CVD simulation: Machado, Oliveira & Fernandes (2009), severity 1.0, applied in
  linear RGB.
- Perceived difference: CIEDE2000 on CIELAB (D65).
- Contrast: WCAG 2.x relative-luminance ratio.
"""

from __future__ import annotations

import itertools
import math
from typing import Literal

Vision = Literal["normal", "deutan", "protan", "tritan"]
VISIONS: tuple[Vision, ...] = ("normal", "deutan", "protan", "tritan")

_MACHADO: dict[str, tuple[tuple[float, float, float], ...]] = {
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "tritan": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def simulate(hex_color: str, vision: Vision) -> tuple[float, float, float]:
    """sRGB (0..1) of ``hex_color`` as seen with ``vision``."""
    rgb = _rgb(hex_color)
    if vision == "normal":
        return rgb
    lin = [_to_linear(c) for c in rgb]
    m = _MACHADO[vision]
    r, g, b = (_to_srgb(sum(m[row][k] * lin[k] for k in range(3))) for row in range(3))
    return r, g, b


def lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000 colour difference."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    c_bar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    d_l, d_c = L2 - L1, c2p - c1p
    if c1p * c2p == 0:
        d_h = 0.0
    else:
        d_h = h2p - h1p
        if d_h > 180:
            d_h -= 360
        elif d_h < -180:
            d_h += 360
    d_hh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(d_h / 2))
    l_bar, c_bar_p = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    else:
        h_bar = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * c_bar_p
    s_h = 1 + 0.015 * c_bar_p * t
    r_t = (
        -2
        * math.sqrt(c_bar_p**7 / (c_bar_p**7 + 25**7))
        * math.sin(math.radians(60 * math.exp(-(((h_bar - 275) / 25) ** 2))))
    )
    return math.sqrt(
        (d_l / s_l) ** 2 + (d_c / s_c) ** 2 + (d_hh / s_h) ** 2 + r_t * (d_c / s_c) * (d_hh / s_h)
    )


def min_pair_delta_e(colors: list[str], vision: Vision = "normal") -> float:
    """Smallest CIEDE2000 between any two of ``colors`` as seen with ``vision``."""
    labs = [lab(simulate(c, vision)) for c in colors]
    return min(delta_e(a, b) for a, b in itertools.combinations(labs, 2))


def worst_delta_e(colors: list[str]) -> tuple[float, Vision]:
    """The weakest pair over every vision, and the vision it happens in."""
    return min((min_pair_delta_e(colors, v), v) for v in VISIONS)


def relative_luminance(hex_color: str) -> float:
    r, g, b = (_to_linear(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((relative_luminance(a), relative_luminance(b)))
    return (lb + 0.05) / (la + 0.05)
