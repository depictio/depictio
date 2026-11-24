"""depictio's plot palettes: one source of truth for Python and TypeScript.

The colours live in ``depictio_palettes.json`` next to this module. Python reads
them here; the viewer reads ``packages/depictio-react-core/src/palettes.generated.ts``,
which ``scripts/gen_palette_ts.py`` writes from the same file. Nothing else in the
code base should carry a categorical palette of its own.

Every palette has 8 categorical slots, in a light and a dark variant that keep the
same hue per slot, plus a sequential and a diverging ramp per mode. Each one is
tested (``tests/unit/test_palettes.py``) to keep any two slots apart under normal
vision and the three colour-vision deficiencies.

Assignment rule (:func:`assign_colors`), the same on both sides:

1. a pinned colour (``category_colors`` on the dashboard) wins;
2. a reserved value (Other, Unclassified, NA, ...) takes its semantic grey;
3. the remaining values, in case-insensitive order over the *whole* universe of
   values (never the filtered subset), or in the caller's rank order with
   ``ranked=True``, take the palette slots no pin already uses;
4. past the last slot, a value never repeats a colour: ``overflow`` (default
   ``style.overflow``; a brand sets ``plots.overflow``) decides whether it takes the
   Other grey (``other``) or, first, a lightness-shifted twin of each slot (``shade``,
   then grey). Shades exist only for a named palette, or a list holding exactly one
   palette's colours: a free colorway falls back to the grey.

A plot that folds its tail into an "Other" category (top_n) still does so itself;
step 4 only keeps an unfolded tail from reusing a hue.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from . import ui_hues as _ui_hues

Mode = Literal["light", "dark"]
ReservedKind = Literal["other", "unclassified", "na"]


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """The parsed ``depictio_palettes.json``."""
    text = resources.files(__name__).joinpath("depictio_palettes.json").read_text("utf-8")
    return json.loads(text)


def default_palette_id() -> str:
    return load()["default"]


def palette_ids() -> list[str]:
    """Palette ids in the order a picker should list them (default first)."""
    return list(load()["palettes"])


def palette_labels() -> dict[str, str]:
    return {pid: spec["label"] for pid, spec in load()["palettes"].items()}


def _spec(palette_id: str | None) -> dict[str, Any]:
    palettes = load()["palettes"]
    return palettes.get(palette_id or "") or palettes[default_palette_id()]


def _mode(mode: str | None) -> Mode:
    return "dark" if mode == "dark" else "light"


def categorical(palette_id: str | None = None, mode: str | None = "light") -> list[str]:
    """The 8 categorical colours of a palette (default palette when unknown)."""
    return list(_spec(palette_id)["categorical"][_mode(mode)])


def sequential(palette_id: str | None = None, mode: str | None = "light") -> list[str]:
    """Sequential ramp, from the background end to the emphasis end."""
    return list(_spec(palette_id)["sequential"][_mode(mode)])


def diverging(palette_id: str | None = None, mode: str | None = "light") -> list[str]:
    """Diverging ramp, low end -> neutral -> high end (odd length, neutral in the middle)."""
    return list(_spec(palette_id)["diverging"][_mode(mode)])


def colorscale(colors: list[str]) -> list[list[float | str]]:
    """Plotly colorscale (``[[0, c0], ..., [1, cn]]``) from evenly spaced stops."""
    last = len(colors) - 1
    return [[i / last, c] for i, c in enumerate(colors)]


def ui_hue_names() -> list[str]:
    """Mantine hue names a dashboard remaps onto the active palette."""
    return list(load()["ui_hues"]["default"])


@lru_cache(maxsize=None)
def _ui_hue_tuples(palette_id: str) -> dict[str, dict[str, list[str]]]:
    return _ui_hues.ui_hue_tuples(load(), palette_id)


def ui_hue_tuple(name: str, palette_id: str | None = None, mode: str | None = "light") -> list[str]:
    """The 10-shade Mantine tuple of a remapped hue name (``teal``, ``grape``...).

    ``light`` anchors the slot colour on shade 6, ``dark`` anchors the dark slot colour
    on shade 4; lightness falls from shade 0 to shade 9 in both. Default palette when
    ``palette_id`` is unknown; ``KeyError`` for a name that is not remapped.
    """
    pid: str = (
        palette_id if palette_id and palette_id in load()["palettes"] else default_palette_id()
    )
    return list(_ui_hue_tuples(pid)[name][_mode(mode)])


def ui_hue_anchor(name: str, palette_id: str | None = None, mode: str | None = "light") -> str:
    """The slot colour (after the pair nudge) that ``ui_hue_tuple`` pins on its anchor shade."""
    pid: str = (
        palette_id if palette_id and palette_id in load()["palettes"] else default_palette_id()
    )
    spec = _ui_hues.hue_specs(load(), pid)[name]
    return _ui_hues.ui_hue_anchor(spec, load()["palettes"][pid], _mode(mode))


UI_HUE_ANCHOR_SHADE: dict[str, int] = {
    "light": _ui_hues.LIGHT_ANCHOR,
    "dark": _ui_hues.DARK_ANCHOR,
}


def semantic(kind: ReservedKind, mode: str | None = "light") -> str:
    """Grey of a reserved value kind (other / unclassified / na)."""
    return load()["semantic"][kind][_mode(mode)]


def direction(kind: Literal["up", "down"], mode: str | None = "light") -> str:
    """Colour of a differential direction (up / down), shared by every DE tile."""
    return load()["direction"][kind][_mode(mode)]


def ordinal_colors(values: Iterable[str], mode: str | None = "light") -> dict[str, str] | None:
    """Colours along a documented ordinal scale, when every value belongs to one.

    ``None`` unless there are at least two values and each one (case-insensitive)
    is a level of the same vocabulary in ``ordinal_vocabularies``: SnpEff's
    HIGH / MODERATE / LOW / MODIFIER is a severity, so it reads red to grey
    rather than taking whichever categorical slots its sort order lands on.
    """
    distinct = list(dict.fromkeys(values))
    if len(distinct) < 2:
        return None
    for key, vocab in load()["ordinal_vocabularies"].items():
        if key.startswith("$"):
            continue
        levels = {k.casefold(): c for k, c in vocab["values"].items()}
        if all(v.casefold() in levels for v in distinct):
            return {v: levels[v.casefold()][_mode(mode)] for v in distinct}
    return None


def annotation_ink(mode: str | None = "light") -> str:
    """Default colour of a drawn annotation: neutral, told apart from data by form."""
    return load()["annotation_ink"][_mode(mode)]


def chrome(mode: str | None = "light") -> dict[str, str]:
    """Plot chrome tokens: text, muted, grid, zero, axis_line, hover_*, surface."""
    return dict(load()["chrome"][_mode(mode)])


def font_family() -> str:
    return load()["chrome"]["font_family"]


def style() -> dict[str, Any]:
    """The overview style's constants: ``bar_corner_radius``, ``top_n``, ``scatter_markers``."""
    return load()["style"]


def scatter_marker(n: int) -> dict[str, Any]:
    """Marker ``size`` / ``opacity`` / ``outline`` for a scatter of ``n`` points.

    The first bucket whose ``max_n`` is at least ``n``; the last bucket has no
    ``max_n`` and takes everything above. More points, smaller and fainter.
    """
    buckets = style()["scatter_markers"]
    for bucket in buckets:
        if bucket["max_n"] is None or n <= bucket["max_n"]:
            return dict(bucket)
    return dict(buckets[-1])


def line_style(n_series: int) -> dict[str, Any]:
    """Stroke ``width`` for a figure of ``n_series`` lines, and how short a
    series must be (``marker_max_points``) to show a dot on every point.

    Up to ``many_series`` lines each is drawn bold; past it they thin out so a
    bundle of lines does not merge into one band.
    """
    spec = style()["line_style"]
    width = spec["width"] if n_series <= spec["many_series"] else spec["width_many"]
    return {"width": width, "marker_max_points": spec["marker_max_points"]}


def line_marker_size(width: float) -> int:
    """A line's dot: about twice its width plus three, never under 6, so the dot
    clears the stroke it sits on (``markerSizeFor`` in the viewer)."""
    return max(6, round(2 * width + 3))


@lru_cache(maxsize=1)
def _reserved_lookup() -> dict[str, ReservedKind]:
    out: dict[str, ReservedKind] = {}
    for kind, names in load()["reserved_values"].items():
        for name in names:
            out[name] = kind
    return out


def reserved_kind(value: Any) -> ReservedKind | None:
    """``other`` / ``unclassified`` / ``na`` when ``value`` is a reserved remainder value."""
    if value is None:
        return "na"
    return _reserved_lookup().get(str(value).strip().casefold())


def assign_colors(
    values: Iterable[Any],
    *,
    pinned: Mapping[str, str] | None = None,
    palette: str | Iterable[str] | None = None,
    mode: str | None = "light",
    ranked: bool = False,
    overflow: str | None = None,
) -> dict[str, str]:
    """A stable colour for every distinct value (see the module docstring for the rule).

    Args:
        values: The universe of values (all of them, not the filtered subset).
            Order and duplicates do not matter; ``None`` and ``""`` count as NA.
        pinned: ``{value: colour}`` set by the dashboard; always wins.
        palette: A palette id, an explicit colour list (a brand colorway), or
            ``None`` for the default palette.
        mode: ``light`` or ``dark``; picks the variant of a named palette.
        ranked: keep the order of ``values`` (first occurrence), most important
            first, instead of sorting them: the top ranks get the slots.
        overflow: ``other`` / ``shade`` past the last slot; ``None`` for the default.
    """
    pinned = {str(k): v for k, v in (pinned or {}).items() if v}
    if palette is None or isinstance(palette, str):
        colours = categorical(palette, mode)
    else:
        colours = list(palette) or categorical(None, mode)

    as_text = ["" if v is None else str(v) for v in values]
    if ranked:
        ordered = list(dict.fromkeys(as_text))
    else:
        ordered = sorted(set(as_text), key=lambda s: (s.casefold(), s))

    result: dict[str, str] = {}
    free_values: list[str] = []
    for value in ordered:
        if value in pinned:
            result[value] = pinned[value]
        elif (kind := reserved_kind(value)) is not None:
            result[value] = semantic(kind, mode)
        else:
            free_values.append(value)

    ordinal = ordinal_colors(free_values, mode)
    if ordinal is not None:
        result.update(ordinal)
        free_values = []

    used = {c.lower() for c in pinned.values()}
    slots = [c for c in colours if c.lower() not in used]
    shade_id = (
        named_palette_of(palette if palette is None or isinstance(palette, str) else colours, mode)
        if overflow_mode(overflow) == "shade"
        else None
    )
    if shade_id:
        # shades only for a named palette: TypeScript reads them pre-computed
        shades = _ui_hues.overflow_shades(categorical(shade_id, mode), _overflow_dl(mode))
        slots += [c for c in shades if c.lower() not in used]
    remainder = semantic("other", mode)
    for i, value in enumerate(free_values):
        result[value] = slots[i] if i < len(slots) else remainder
    for value, colour in pinned.items():
        result.setdefault(value, colour)
    return result


def overflow_mode(value: str | None = None) -> Literal["other", "shade"]:
    """What a value past the last slot gets: ``other`` grey or a ``shade`` twin.

    ``value`` when it is one of the two, else the default in ``style.overflow``.
    """
    if value not in ("other", "shade"):
        value = style().get("overflow")
    return "shade" if value == "shade" else "other"


def named_palette_of(palette: str | Iterable[str] | None, mode: str | None = "light") -> str | None:
    """The palette id ``palette`` stands for: an id, ``None`` (the default), or a list
    equal to one palette's colours in ``mode``; ``None`` for a free colour list."""
    if palette is None or isinstance(palette, str):
        return palette if palette in load()["palettes"] else default_palette_id()
    key = [c.lower() for c in palette]
    if not key:
        return default_palette_id()
    for pid in palette_ids():
        if [c.lower() for c in categorical(pid, mode)] == key:
            return pid
    return None


def _overflow_dl(mode: str | None) -> float:
    return float(style()["overflow_shade_dl"]["dark" if mode == "dark" else "light"])


def order_with_remainder_last(values: Iterable[Any]) -> list[Any]:
    """Keep ``values`` in order but move reserved remainder values to the end.

    Other comes before Unclassified, which comes before NA, so a stack always ends
    on the least informative band.
    """
    rank = {"other": 1, "unclassified": 2, "na": 3}
    items = list(values)
    return sorted(items, key=lambda v: rank.get(reserved_kind(v) or "", 0))
