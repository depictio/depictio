"""Native Plotly ``mantine_light`` / ``mantine_dark`` templates.

The implementation now lives in ``depictio.cli.cli.utils.mantine_templates`` so
that the CLI offline MultiQC figure prerender and the API render path share one
source of truth (the CLI cannot import ``depictio.api.v1.services.*``). This
module is a thin re-export kept in place so every existing
``from depictio.api.v1.services.figure.mantine_templates import
ensure_mantine_templates`` import continues to work unchanged.
"""

from __future__ import annotations

from depictio.cli.cli.utils.mantine_templates import ensure_mantine_templates

__all__ = ["ensure_mantine_templates"]
