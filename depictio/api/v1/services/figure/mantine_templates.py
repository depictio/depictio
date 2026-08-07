"""Native Plotly ``mantine_light`` / ``mantine_dark`` templates.

The base implementation lives in ``depictio.cli.cli.utils.mantine_templates``
so that the CLI offline MultiQC figure prerender and the API render path share
one source of truth (the CLI cannot import ``depictio.api.v1.services.*``).

On the API/worker side this shim additionally applies the instance branding
colorway (issue #397, ``DEPICTIO_BRANDING_COLORWAY``): after the CLI module
registers the vanilla templates, their ``layout.colorway`` is overwritten from
settings, once per process. The CLI module itself must stay settings-free —
CLI-only installs don't ship the server settings machinery.
"""

from __future__ import annotations

import plotly.io as pio

from depictio.cli.cli.utils.mantine_templates import (
    ensure_mantine_templates as _ensure_base_templates,
)

_branding_applied = False


def apply_branding_colorway() -> None:
    """Overwrite the mantine templates' colorway from instance branding.

    No-op when ``DEPICTIO_BRANDING_COLORWAY`` is unset/invalid. Idempotent —
    guarded by a module flag so the settings lookup happens once per process.
    """
    global _branding_applied
    if _branding_applied:
        return
    _branding_applied = True

    from depictio.api.v1.configs.config import settings

    colorway = settings.branding.colorway_list
    if not colorway:
        return
    for name in ("mantine_light", "mantine_dark"):
        pio.templates[name].layout.colorway = colorway


def ensure_mantine_templates() -> None:
    """Register the mantine templates, branded when the instance is."""
    _ensure_base_templates()
    apply_branding_colorway()


__all__ = ["ensure_mantine_templates", "apply_branding_colorway"]
