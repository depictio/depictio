"""Native Plotly ``mantine_light`` / ``mantine_dark`` templates.

The base implementation lives in ``depictio.cli.cli.utils.mantine_templates``
so that the CLI offline MultiQC figure prerender and the API render path share
one source of truth (the CLI cannot import ``depictio.api.v1.services.*``).

On the API/worker side this shim additionally applies the instance branding
colorway (issue #397): after the CLI module registers the vanilla templates,
their ``layout.colorway`` is overwritten from the *effective* branding — the
``DEPICTIO_BRANDING_COLORWAY`` env default overridden by the admin panel's
live settings (services/branding.py). The CLI module itself must stay
settings-free — CLI-only installs don't ship the server settings machinery.
"""

from __future__ import annotations

from typing import Any

import plotly.io as pio

from depictio.cli.cli.utils.mantine_templates import (
    ensure_mantine_templates as _ensure_base_templates,
)

_TEMPLATE_NAMES = ("mantine_light", "mantine_dark")

# Applied-state guard: re-patching only when the effective colorway changed
# keeps this callable per render. `_vanilla` remembers the unbranded colorways
# so clearing the branding from the admin panel restores them without a
# process restart.
_UNSET = object()
_applied_colorway: Any = _UNSET
_vanilla: dict[str, Any] = {}


def apply_branding_colorway() -> None:
    """Sync the mantine templates' colorway with the effective branding.

    Called on every render path (cheap: the branding read is TTL-cached, and
    templates are only touched when the value actually changed). Falls back
    to the env-var branding if the overrides store is unreachable, so a
    Mongo hiccup can't take figure rendering down with it.
    """
    global _applied_colorway

    try:
        from depictio.api.v1.services.branding import get_effective_branding

        colorway = get_effective_branding().get("colorway")
    except Exception:
        from depictio.api.v1.configs.config import settings

        colorway = settings.branding.colorway_list

    if colorway == _applied_colorway:
        return
    if not _vanilla:
        for name in _TEMPLATE_NAMES:
            _vanilla[name] = pio.templates[name].layout.colorway
    for name in _TEMPLATE_NAMES:
        pio.templates[name].layout.colorway = colorway if colorway else _vanilla[name]
    _applied_colorway = colorway


def ensure_mantine_templates() -> None:
    """Register the mantine templates, branded when the instance is."""
    _ensure_base_templates()
    apply_branding_colorway()


__all__ = ["ensure_mantine_templates", "apply_branding_colorway"]
