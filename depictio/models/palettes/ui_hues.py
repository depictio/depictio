"""Mantine hue names re-drawn in a depictio palette, for the dashboard's own chrome.

A dashboard names colours as Mantine hues (``teal``, ``grape``, ``orange``...):
KPI icons, section and tab colours, filter accents, step numbers. Inside a
dashboard those names are remapped onto the active plot palette, so the chrome
and the figures read as one family. ``depictio_palettes.json`` lists the remap
(``ui_hues``): each name takes a categorical slot, and the pairs that Mantine
keeps apart (violet/grape, blue/indigo, teal/cyan, green/lime) keep a visible
difference through an OKLCH nudge on the same slot.

Pure stdlib, no imports from the rest of ``depictio``: ``scripts/gen_palette_ts.py``
loads this file by path to write ``UI_HUE_TUPLES`` into the TypeScript copy.

A tuple has 10 shades like Mantine's own. Light mode anchors the slot colour on
shade 6 (the shade a filled control paints with); dark mode anchors the dark slot
colour on shade 4 (the shade a text or icon takes), with 6 and 8 a little deeper
so a filled control still reads. Lightness runs strictly from light (0) to dark (9).
"""

from __future__ import annotations

import math
from typing import Any

LIGHT_ANCHOR = 6
DARK_ANCHOR = 4
SHADES = 10
# Shade 0 never goes past this lightness: pure white tints vanish on a card.
_TOP_LIGHTNESS = 0.975
# How far the darkest shade sits under the anchor (OKLab lightness).
_DEPTH = 0.30
_FLOOR = 0.16


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    return c * 12.92 if c <= 0.0031308 else 1.055 * math.copysign(abs(c) ** (1 / 2.4), c) - 0.055


def hex_to_oklch(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    r, g, b = (_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return lightness, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def _oklch_to_linear(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    return all(-0.0005 <= c <= 1.0005 for c in rgb)


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """sRGB hex of an OKLCH colour; chroma is pulled in until the colour fits the gamut."""
    lightness = min(1.0, max(0.0, lightness))
    chroma = max(0.0, chroma)
    rgb = _oklch_to_linear(lightness, chroma, hue)
    if not _in_gamut(rgb):
        lo, hi = 0.0, chroma
        for _ in range(24):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_linear(lightness, mid, hue)):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_to_linear(lightness, lo, hue)
    return "#" + "".join(f"{round(min(1.0, max(0.0, _to_srgb(c))) * 255):02X}" for c in rgb)


def adjusted(hex_color: str, adjust: dict[str, Any]) -> str:
    """``hex_color`` nudged by ``dL`` / ``dC`` / ``dh`` (OKLCH); itself when there is none."""
    dl, dc, dh = (float(adjust.get(k, 0)) for k in ("dL", "dC", "dh"))
    if not (dl or dc or dh):
        return hex_color.upper()
    lightness, chroma, hue = hex_to_oklch(hex_color)
    return oklch_to_hex(lightness + dl, chroma + dc, (hue + dh) % 360)


def ramp(anchor: str, anchor_index: int) -> list[str]:
    """10 shades with ``anchor`` on ``anchor_index``: lighter tints above, deeper shades below."""
    lightness, chroma, hue = hex_to_oklch(anchor)
    top = max(_TOP_LIGHTNESS, min(0.99, lightness + 0.04))
    bottom = max(_FLOOR, lightness - _DEPTH)
    shades: list[str] = []
    for index in range(SHADES):
        if index == anchor_index:
            shades.append(anchor.upper())
        elif index < anchor_index:
            t = (anchor_index - index) / anchor_index
            # Tints keep a trace of the hue, not the full chroma.
            shades.append(
                oklch_to_hex(lightness + (top - lightness) * t, chroma * (1 - 0.86 * t**1.3), hue)
            )
        else:
            t = (index - anchor_index) / (SHADES - 1 - anchor_index)
            shades.append(oklch_to_hex(lightness - (lightness - bottom) * t, chroma, hue))
    return shades


def hue_specs(data: dict[str, Any], palette_id: str) -> dict[str, dict[str, Any]]:
    """The remap of one palette: the default entries, over-ridden by its ``per_palette`` ones."""
    block = data["ui_hues"]
    return {**block["default"], **block.get("per_palette", {}).get(palette_id, {})}


# The chrome writes in these hues (findings numbers, tab links, KPI icons), so the
# anchor must read on its background: WCAG 2.x 3:1, the floor for large text and
# UI components. Higher (4.5) deepened most hues into mud; a colour that already
# reads keeps its own value, and one that does not is deepened with its chroma
# raised, so it stays vivid. The data slots only promise 2.0 / 3.0.
TEXT_CONTRAST = 3.0
_CHROMA_BOOST = 1.012
_BACKGROUND = {"light": "#FFFFFF", "dark": "#1A1B1E"}


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)))
    return (lb + 0.05) / (la + 0.05)


def _readable(hex_color: str, mode: str) -> str:
    """``hex_color``, deepened (light) or lightened (dark) in OKLCH until it reads as text."""
    background = _BACKGROUND[mode]
    lightness, chroma, hue = hex_to_oklch(hex_color)
    step = -0.005 if mode == "light" else 0.005
    out = hex_color.upper()
    while contrast(out, background) < TEXT_CONTRAST and 0.05 < lightness < 0.98:
        lightness += step
        chroma *= _CHROMA_BOOST  # oklch_to_hex pulls it back into the gamut
        out = oklch_to_hex(lightness, chroma, hue).upper()
    return out


def ui_hue_anchor(spec: dict[str, Any], palette: dict[str, Any], mode: str) -> str:
    """The slot colour a hue takes in ``mode``, after its OKLCH nudge, readable as text."""
    mode = "dark" if mode == "dark" else "light"
    return _readable(adjusted(palette["categorical"][mode][int(spec["slot"])], spec), mode)


def ui_hue_tuples(data: dict[str, Any], palette_id: str) -> dict[str, dict[str, list[str]]]:
    """``{hue: {"light": [10], "dark": [10]}}`` for one palette of the parsed JSON."""
    palette = data["palettes"][palette_id]
    return {
        name: {
            "light": ramp(ui_hue_anchor(spec, palette, "light"), LIGHT_ANCHOR),
            "dark": ramp(ui_hue_anchor(spec, palette, "dark"), DARK_ANCHOR),
        }
        for name, spec in hue_specs(data, palette_id).items()
    }


def overflow_shades(colours: list[str], dl: float) -> list[str]:
    """The palette's slots shifted in lightness by ``dl`` (OKLCH), hue and chroma kept.

    ``style.overflow: shade`` gives these to the values past the last slot, so a ninth
    value is a darker (light mode) or lighter (dark mode) twin of the first, not a repeat.
    """
    out = []
    for colour in colours:
        lightness, chroma, hue = hex_to_oklch(colour)
        out.append(oklch_to_hex(min(0.97, max(0.08, lightness + dl)), chroma, hue).upper())
    return out
