"""Native Plotly ``mantine_light`` / ``mantine_dark`` templates, brand-aware.

The base implementation lives in ``depictio.cli.cli.utils.mantine_templates``
so that the CLI offline MultiQC figure prerender and the API render path share
one source of truth (the CLI cannot import ``depictio.api.v1.services.*``).

On the API/worker side this shim additionally applies the instance **brand
theme** (issue #397): after the CLI module registers the vanilla templates,
they are rebuilt with the resolved theme's figure colorway, sequential
colorscale and per-scheme surface colors — the ``DEPICTIO_BRANDING_*`` env
defaults overridden by the admin panel's live settings
(``services/branding.py``). The CLI module itself must stay settings-free:
CLI-only installs don't ship the server settings machinery.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Optional

import plotly.io as pio

from depictio.cli.cli.utils.mantine_templates import (
    ensure_mantine_templates as _ensure_base_templates,
)
from depictio.models.models.branding import BrandSurfaces, BrandTheme

#: Template name -> which surface block themes it.
_TEMPLATE_SCHEMES = {"mantine_light": "surfaces_light", "mantine_dark": "surfaces_dark"}

# Applied-state guard: re-patching only when the effective theme changed keeps
# this callable per render. `_vanilla` holds the pristine templates so clearing
# the branding from the admin panel restores them without a process restart.
_UNSET = object()
_applied_key: Any = _UNSET
_vanilla: dict[str, Any] = {}


def _effective_theme() -> BrandTheme:
    """The resolved brand theme, degrading to env defaults if Mongo is down."""
    try:
        from depictio.api.v1.services.branding import resolve_effective_brand_theme

        return resolve_effective_brand_theme()
    except Exception:
        from depictio.api.v1.configs.config import settings
        from depictio.models.models.branding import resolve_brand_theme

        return resolve_brand_theme(settings.branding.as_brand_theme())


def _patch_key(theme: BrandTheme) -> str:
    """Everything that can change a template, and nothing that can't."""
    return json.dumps(
        {
            "plots": theme.plots.model_dump(exclude_none=True) if theme.plots else None,
            "light": theme.surfaces_light.model_dump(exclude_none=True)
            if theme.surfaces_light
            else None,
            "dark": theme.surfaces_dark.model_dump(exclude_none=True)
            if theme.surfaces_dark
            else None,
            "font": theme.font_family,
        },
        sort_keys=True,
    )


def _apply_to_template(template: Any, theme: BrandTheme, surfaces: Optional[BrandSurfaces]) -> Any:
    """A copy of ``template`` with the brand theme's figure colors applied."""
    patched = copy.deepcopy(template)
    layout = patched.layout

    plots = theme.plots
    if plots and plots.colorway:
        layout.colorway = plots.colorway
    if plots and plots.sequential and len(plots.sequential) > 1:
        stops = len(plots.sequential) - 1
        layout.colorscale.sequential = [
            [i / stops, color] for i, color in enumerate(plots.sequential)
        ]
    if theme.font_family:
        layout.font.family = theme.font_family

    if surfaces:
        if surfaces.section_bg:
            # Figures sit *inside* cards, so the card background is the one
            # that has to match — an app background behind them would leave a
            # visible rectangle on every tile.
            layout.paper_bgcolor = surfaces.section_bg
            layout.plot_bgcolor = surfaces.section_bg
            layout.geo.bgcolor = surfaces.section_bg
        if surfaces.heading:
            layout.title.font.color = surfaces.heading
    return patched


def apply_brand_theme() -> None:
    """Sync the mantine templates with the effective brand theme.

    Called on every render path (cheap: the theme read is TTL-cached, and the
    templates are only rebuilt when the resolved theme actually changed). Falls
    back to the env-var branding if the overrides store is unreachable, so a
    Mongo hiccup can't take figure rendering down with it.
    """
    global _applied_key

    theme = _effective_theme()
    key = _patch_key(theme)
    if key == _applied_key:
        return

    if not _vanilla:
        for name in _TEMPLATE_SCHEMES:
            _vanilla[name] = copy.deepcopy(pio.templates[name])

    for name, surfaces_field in _TEMPLATE_SCHEMES.items():
        pio.templates[name] = _apply_to_template(
            _vanilla[name], theme, getattr(theme, surfaces_field)
        )
    _applied_key = key


def ensure_mantine_templates() -> None:
    """Register the mantine templates, branded when the instance is."""
    _ensure_base_templates()
    apply_brand_theme()


__all__ = ["apply_brand_theme", "ensure_mantine_templates"]
