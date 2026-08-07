"""Plotly theme helpers.

The implementation lives in ``depictio.cli.cli.utils.mantine_templates`` so
that the CLI offline MultiQC figure prerender and the API render path share one
``theme -> template name`` mapping. On the API/worker side this shim also
applies the instance branding colorway (issue #397) to the registered
templates — every server render path resolves its template name through here
(or through ``figure/mantine_templates.py``), so branding can't be skipped by
a path that never calls ``ensure_mantine_templates`` directly.
"""

from __future__ import annotations

from depictio.cli.cli.utils.mantine_templates import (
    get_theme_template as _get_theme_template_base,
)

from depictio.api.v1.services.figure.mantine_templates import apply_branding_colorway


def get_theme_template(theme: str) -> str:
    """Return the Plotly template name for the given UI theme (branded)."""
    name = _get_theme_template_base(theme)
    apply_branding_colorway()
    return name


__all__ = ["get_theme_template"]
