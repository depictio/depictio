"""Brand theme models (issue #397).

One shared shape for every layer that can re-skin a deployment:

- **Deployment defaults** — the ``DEPICTIO_BRANDING_*`` env vars
  (``depictio.api.v1.configs.settings_models.BrandingConfig``).
- **Instance overrides** — the singleton ``instance_settings`` document edited
  from the /admin Branding panel.
- **Dashboard override** — ``DashboardData.brand_theme``, so a single dashboard
  can carry its own identity inside an otherwise neutral instance.

Every field is ``None`` by default and ``None`` means *inherit from the layer
below*, which is what makes ``merge_brand_themes()`` a plain per-field
right-wins fold. Defaults such as ``tint_mode="accent"`` are applied by
``resolve_brand_theme()`` at the end of the chain rather than on the model, so
an untouched theme serialises to ``{}`` and never pollutes a YAML export.

``resolve_brand_theme()`` also materialises the *derived* values (figure
colorway, sequential colorscale). Those derivations live here, in the shared
models package, because both the Python render path and the React viewer need
them: computing them once server-side and shipping the result is the only way
the two can't drift.
"""

from __future__ import annotations

import colorsys
import re
from typing import Any, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: A concrete color value: ``#rrggbb``.
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
#: A Mantine palette name (e.g. ``teal``) — the other accepted color form.
PALETTE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

TintMode = Literal["accent", "full"]
LogoMode = Literal["inherit", "none", "custom"]

#: How many categorical colors a derived colorway carries. Matches the length
#: of the stock ``mantine_light`` colorway so a branded instance doesn't
#: suddenly wrap sooner than an unbranded one.
COLORWAY_LENGTH = 8
#: Stops in a derived sequential colorscale (same count as ``_SEQUENTIAL_COLORS``
#: in ``depictio.cli.cli.utils.mantine_templates``).
SEQUENTIAL_LENGTH = 8

#: Mantine color tuples are always 10 shades, and it paints a filled control
#: with shade 6 in light mode / shade 8 in dark — so shade 6 is where a brand
#: color has to land to actually be the color of a button.
PALETTE_LENGTH = 10
_PALETTE_ANCHOR = 6


def validate_color(value: str, *, allow_palette_name: bool = True) -> str:
    """Return ``value`` if it is an acceptable color, else raise ``ValueError``."""
    text = value.strip()
    if HEX_COLOR_RE.fullmatch(text):
        return text.lower()
    if allow_palette_name and PALETTE_NAME_RE.fullmatch(text):
        return text
    expected = "a hex color (#rrggbb)" + (
        " or a Mantine palette name" if allow_palette_name else ""
    )
    raise ValueError(f"{value!r} is not {expected}")


# ── Color math ────────────────────────────────────────────────────────────────
# Pure stdlib (colorsys) on purpose: the models package is imported by the CLI,
# which must stay free of heavy color libraries.


def _hex_to_hls(color: str) -> tuple[float, float, float]:
    r = int(color[1:3], 16) / 255
    g = int(color[3:5], 16) / 255
    b = int(color[5:7], 16) / 255
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(hue: float, lightness: float, saturation: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hue % 1.0, _clamp(lightness), _clamp(saturation))
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


#: Derived variants stay inside this lightness band: below the floor every hue
#: reads as black, above the ceiling every hue reads as white.
_LIGHTNESS_FLOOR = 0.16
_LIGHTNESS_CEILING = 0.88


def shift_lightness(color: str, delta: float) -> str:
    """Same hue, lightness moved by ``delta`` (-1..1).

    Lightening in HLS at full saturation produces neon (``#00a550`` +0.16 gives
    ``#00f778``), so a positive delta also relaxes saturation. Darkening keeps
    it, which is what reads as "the same color, deeper".
    """
    hue, lightness, saturation = _hex_to_hls(color)
    target = lightness + delta
    # An already-dark seed darkened again collapses to near-black (EMBL's
    # #00514b - 0.26 is #000a09), which is indistinguishable from every other
    # over-darkened hue. Reflect the step instead of clipping into the void.
    if not _LIGHTNESS_FLOOR <= target <= _LIGHTNESS_CEILING:
        target = lightness - delta
        delta = -delta
    if delta > 0:
        saturation *= max(0.55, 1.0 - delta)
    return _hls_to_hex(hue, _clamp(target, _LIGHTNESS_FLOOR, _LIGHTNESS_CEILING), saturation)


def relative_luminance(color: str) -> float:
    """WCAG relative luminance, used to pick readable text over a brand color."""

    def channel(raw: int) -> float:
        value = raw / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def derive_colorway(bases: list[str], length: int = COLORWAY_LENGTH) -> list[str]:
    """Build a categorical palette from one to three brand hues.

    With several bases the hues are cycled first and the lightness only moves
    once a full cycle is done, so *adjacent* series always differ in hue (the
    thing that actually makes a chart readable) and a repeated hue is always
    separated by a clear lightness step. Lighter variants come before darker
    ones because a very dark tint reads as "almost black" against a light
    background well before a light one reads as "almost white".

    With a single base there is no second hue to alternate with, so the walk
    falls back to golden-angle hue rotation, which spreads N colors around the
    wheel about as evenly as a closed form can.
    """
    seeds = [c for c in bases if c and HEX_COLOR_RE.fullmatch(c)]
    if not seeds or length <= 0:
        return []

    if len(seeds) == 1:
        hue, lightness, saturation = _hex_to_hls(seeds[0])
        golden = 0.381966  # 1 - 1/phi, the golden angle as a fraction of the wheel
        return [
            _hls_to_hex(
                hue + golden * i,
                lightness + (0.10 if i % 3 == 1 else -0.08 if i % 3 == 2 else 0.0),
                saturation,
            )
            for i in range(length)
        ]

    out: list[str] = []
    for step in (0.0, 0.18, -0.14, 0.34, -0.26, 0.46, -0.36):
        for seed in seeds:
            if len(out) >= length:
                return out
            out.append(seed if step == 0.0 else shift_lightness(seed, step))
    return out[:length]


def derive_palette(base: str) -> list[str]:
    """A Mantine-shaped 10-shade tuple with `base` pinned at the filled shade.

    Mantine paints a filled control with shade 6 in light mode and shade 8 in
    dark, so a tuple whose shade 6 is not the brand color means the buttons are
    a lightened cousin of the brand rather than the brand — which is exactly
    what a generated ramp gives you for anything but a mid-lightness seed
    (`#00a550` lands at shade 9, leaving a neon `#37fe86` on every button).

    So the ladder is anchored instead of fitted: shade 6 IS the seed, the tints
    above it climb to near-white, and the shades below it darken to a floor.
    Saturation is damped on the tint side so pale shades read as tints of the
    brand rather than as pastels of their own.
    """
    if not base or not HEX_COLOR_RE.fullmatch(base):
        return []
    hue, lightness, saturation = _hex_to_hls(base)
    # Both bounds are pinned on the anchor's side of it: a clamp that crosses
    # the seed inverts that half of the ramp (a near-white brand tinting *up*
    # to shade 0, a near-black one darkening *up* to shade 9), which paints
    # hover and pressed states on the wrong side of the button they belong to.
    top = max(lightness, _clamp(max(0.96, lightness + 0.08), 0.0, 0.99))
    # Dark enough to read as "pressed" next to the anchor, without collapsing
    # an already-dark brand into black — with the floor itself capped relative
    # to the seed, per the note above (`#1a0000` bottomed out at `#290000`).
    bottom = min(lightness * 0.55, lightness - 0.06)
    bottom = max(bottom, min(0.08, lightness * 0.55))

    shades: list[str] = []
    for index in range(PALETTE_LENGTH):
        if index == _PALETTE_ANCHOR:
            shades.append(base.lower())
            continue
        if index < _PALETTE_ANCHOR:
            ratio = index / _PALETTE_ANCHOR
            shade_lightness = top - (top - lightness) * ratio
            # Fully tinted at the top, full brand saturation at the anchor.
            shade_saturation = saturation * (0.55 + 0.45 * ratio)
        else:
            ratio = (index - _PALETTE_ANCHOR) / (PALETTE_LENGTH - 1 - _PALETTE_ANCHOR)
            shade_lightness = lightness - (lightness - bottom) * ratio
            shade_saturation = min(1.0, saturation * (1.0 + 0.12 * ratio))
        shades.append(_hls_to_hex(hue, shade_lightness, shade_saturation))
    return shades


def derive_sequential(base: str, length: int = SEQUENTIAL_LENGTH) -> list[str]:
    """A light-to-dark ramp in the brand hue, for continuous colorscales."""
    if not base or not HEX_COLOR_RE.fullmatch(base) or length <= 1:
        return []
    hue, _, saturation = _hex_to_hls(base)
    saturation = max(saturation, 0.35)
    top, bottom = 0.92, 0.22
    return [
        _hls_to_hex(
            hue,
            top - (top - bottom) * (i / (length - 1)),
            saturation * (0.55 + 0.45 * (i / (length - 1))),
        )
        for i in range(length)
    ]


# ── Models ────────────────────────────────────────────────────────────────────


class BrandSurfaces(BaseModel):
    """Chrome colors for one color scheme. All optional, all hex."""

    model_config = ConfigDict(extra="forbid")

    app_bg: Optional[str] = Field(
        default=None, description="Page background (Mantine `--mantine-color-body`)."
    )
    section_bg: Optional[str] = Field(
        default=None, description="Card / Paper / section-accordion background."
    )
    nav_bg: Optional[str] = Field(
        default=None, description="App shell navbar and header background."
    )
    heading: Optional[str] = Field(default=None, description="Title and section-title text color.")

    @field_validator("app_bg", "section_bg", "nav_bg", "heading")
    @classmethod
    def _check_hex(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else validate_color(value, allow_palette_name=False)

    @property
    def is_empty(self) -> bool:
        return not any(self.model_dump(exclude_none=True).values())


class BrandPlots(BaseModel):
    """Figure defaults. Component-explicit values always win over these."""

    model_config = ConfigDict(extra="forbid")

    template: Optional[str] = Field(
        default=None,
        description="Plotly template name (e.g. 'seaborn', 'plotly_white') used by all figures "
        "whose component doesn't pick one. Unset/`mantine_light`/`mantine_dark` mean "
        "'follow the UI theme'.",
    )
    colorway: Optional[list[str]] = Field(
        default=None,
        description="Categorical color sequence (hex list) for figures that set neither "
        "`color_discrete_sequence` nor `color_discrete_map`. Unset means 'derive from the "
        "brand palette'.",
    )
    sequential: Optional[list[str]] = Field(
        default=None,
        description="Continuous colorscale stops (hex list, light to dark). Unset means "
        "'derive from the primary color'.",
    )

    @field_validator("colorway", "sequential")
    @classmethod
    def _check_hex_list(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return [validate_color(c, allow_palette_name=False) for c in value] or None

    @property
    def is_empty(self) -> bool:
        return self.template is None and not self.colorway and not self.sequential


class BrandTheme(BaseModel):
    """A deployment's (or a dashboard's) visual identity.

    Unset fields inherit from the layer below — see ``merge_brand_themes()``.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Identity ──
    app_name: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Instance display name: browser tab title and login-page greeting.",
    )
    logo_mode: Optional[LogoMode] = Field(
        default=None,
        description="'inherit' uses the layer below's logo, 'none' shows no logo, "
        "'custom' uses `logo_url`. Unset resolves to 'inherit'.",
    )
    logo_url: Optional[str] = Field(default=None, max_length=2000)
    logo_url_dark: Optional[str] = Field(
        default=None, max_length=2000, description="Dark-scheme variant; falls back to `logo_url`."
    )

    # ── Brand palette ──
    primary: Optional[str] = Field(
        default=None, description="Primary brand color: hex, or a Mantine palette name."
    )
    secondary: Optional[str] = Field(default=None, description="Secondary brand color.")
    tertiary: Optional[str] = Field(default=None, description="Tertiary / accent brand color.")

    # ── Semantic palette ──
    success: Optional[str] = Field(default=None, description="Overrides Mantine green.")
    warning: Optional[str] = Field(default=None, description="Overrides Mantine yellow.")
    danger: Optional[str] = Field(default=None, description="Overrides Mantine red.")

    # ── Reach ──
    tint_mode: Optional[TintMode] = Field(
        default=None,
        description="How far the brand hues reach into the existing UI. 'accent' re-tints the "
        "primary accent only; 'full' also remaps the secondary/tertiary accent families. "
        "Unset resolves to 'accent'.",
    )

    # ── Surfaces, typography, shape ──
    surfaces_light: Optional[BrandSurfaces] = None
    surfaces_dark: Optional[BrandSurfaces] = None
    font_family: Optional[str] = Field(default=None, max_length=300)
    headings_font_family: Optional[str] = Field(default=None, max_length=300)
    default_radius: Optional[str] = Field(
        default=None, description="Mantine radius token: xs, sm, md, lg or xl."
    )

    # ── Figures ──
    plots: Optional[BrandPlots] = None

    # ── Derived ──
    palettes: Optional[dict[str, list[str]]] = Field(
        default=None,
        description="Derived Mantine color tuples, keyed by role (primary, secondary, "
        "tertiary, success, warning, danger). Filled in by `resolve_brand_theme`; "
        "authors never set this.",
    )

    @field_validator("palettes")
    @classmethod
    def _check_palettes(
        cls, value: Optional[dict[str, list[str]]]
    ) -> Optional[dict[str, list[str]]]:
        if value is None:
            return None
        for role, shades in value.items():
            if len(shades) != PALETTE_LENGTH:
                raise ValueError(f"palettes['{role}'] must hold {PALETTE_LENGTH} shades")
            for shade in shades:
                validate_color(shade, allow_palette_name=False)
        return value

    @field_validator("primary", "secondary", "tertiary", "success", "warning", "danger")
    @classmethod
    def _check_color(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else validate_color(value)

    @field_validator("logo_url", "logo_url_dark")
    @classmethod
    def _check_logo_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.startswith(("https://", "http://", "/")):
            raise ValueError("Logo URL must be absolute (https://, http://) or a rooted path (/…)")
        return value

    @field_validator("default_radius")
    @classmethod
    def _check_radius(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if value not in ("xs", "sm", "md", "lg", "xl"):
            raise ValueError("default_radius must be one of xs, sm, md, lg, xl")
        return value

    @property
    def is_empty(self) -> bool:
        """True when nothing is set — the shape a neutral deployment serialises to.

        `palettes` doesn't count: it is derived from the colors, so a theme
        holding only derived tuples has nothing an author actually stated.
        """
        stated = self.model_dump(exclude_none=True)
        stated.pop("palettes", None)
        return not stated

    @property
    def palette(self) -> list[str]:
        """The brand hues that are concrete hex, in priority order."""
        return [
            c
            for c in (self.primary, self.secondary, self.tertiary)
            if c and HEX_COLOR_RE.fullmatch(c)
        ]


_NESTED_FIELDS = ("surfaces_light", "surfaces_dark", "plots")

_M = TypeVar("_M", bound=BaseModel)


def _merge_pair(base: Optional[_M], override: Optional[_M]) -> Optional[_M]:
    """Field-wise merge of two nested models; ``None`` fields inherit."""
    if override is None:
        return base
    if base is None:
        return override
    merged = base.model_dump()
    merged.update(override.model_dump(exclude_none=True))
    return type(base)(**merged)


def merge_brand_themes(*layers: Optional[BrandTheme]) -> BrandTheme:
    """Fold layers left to right; later layers win per field.

    Nested blocks (``surfaces_*``, ``plots``) merge field-wise too, so a
    dashboard that only sets ``plots.colorway`` keeps the instance's
    ``plots.template``.
    """
    result = BrandTheme()
    for layer in layers:
        if layer is None:
            continue
        flat = layer.model_dump(exclude_none=True)
        for field in _NESTED_FIELDS:
            flat.pop(field, None)
        merged = result.model_dump()
        merged.update(flat)
        for field in _NESTED_FIELDS:
            nested = _merge_pair(getattr(result, field), getattr(layer, field))
            merged[field] = nested.model_dump() if nested is not None else None
        result = BrandTheme(**merged)
    return result


def resolve_brand_theme(theme: Optional[BrandTheme]) -> BrandTheme:
    """Make every implicit value explicit: defaults applied, figures derived.

    This is what ships to the SPA and what the render path reads, so neither
    side ever has to re-derive a colorway (and drift from the other).
    """
    resolved = (theme or BrandTheme()).model_copy(deep=True)
    resolved.tint_mode = resolved.tint_mode or "accent"
    resolved.logo_mode = resolved.logo_mode or ("custom" if resolved.logo_url else "inherit")

    palette = resolved.palette
    plots = resolved.plots or BrandPlots()
    if not plots.colorway and palette:
        plots.colorway = derive_colorway(palette)
    if not plots.sequential and palette:
        plots.sequential = derive_sequential(palette[0])
    resolved.plots = None if plots.is_empty else plots

    # Roles given as a Mantine palette name already have a tuple on the client;
    # only hex needs one built, and it has to be built here so the admin
    # preview, the app chrome and any other consumer see identical shades.
    palettes = {
        role: derive_palette(color)
        for role in ("primary", "secondary", "tertiary", "success", "warning", "danger")
        if (color := getattr(resolved, role)) and HEX_COLOR_RE.fullmatch(color)
    }
    resolved.palettes = palettes or None
    return resolved


# ── Presets ───────────────────────────────────────────────────────────────────
# Starting points for the /admin Branding panel and for
# ``DEPICTIO_BRANDING_PRESET``. A preset is only ever a form seed: everything it
# sets stays editable afterwards.

BRAND_PRESETS: dict[str, dict[str, Any]] = {
    "depictio": {
        "label": "Depictio (default)",
        "theme": {},
    },
    "trec": {
        # EMBL TREC — Traversing European Coastlines. Sampled from the expedition
        # logo and media kit; approximate, and meant to be adjusted in the panel.
        "label": "TREC",
        "theme": {
            "primary": "#00a550",
            "secondary": "#1a4f8f",
            "tertiary": "#f5a11b",
            "tint_mode": "full",
        },
    },
    "embl": {
        "label": "EMBL",
        "theme": {
            "primary": "#009f4d",
            "secondary": "#00514b",
            "tertiary": "#a4c400",
            "tint_mode": "accent",
        },
    },
    "ocean": {
        "label": "Ocean",
        "theme": {
            "primary": "#1c7ed6",
            "secondary": "#0b7285",
            "tertiary": "#f59f00",
            "tint_mode": "full",
        },
    },
}


def preset_theme(name: str) -> Optional[BrandTheme]:
    """The ``BrandTheme`` for a preset id, or ``None`` when unknown."""
    preset = BRAND_PRESETS.get((name or "").strip().lower())
    return BrandTheme(**preset["theme"]) if preset else None
