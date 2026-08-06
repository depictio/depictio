"""Plotly theme helpers.

The implementation now lives in ``depictio.cli.cli.utils.mantine_templates`` so
that the CLI offline MultiQC figure prerender and the API render path share one
``theme -> template name`` mapping. This module is a thin re-export kept in
place so every existing ``from depictio.api.v1.services.multiqc.themes import
get_theme_template`` import continues to work unchanged.
"""

from __future__ import annotations

from depictio.cli.cli.utils.mantine_templates import get_theme_template

__all__ = ["get_theme_template"]
