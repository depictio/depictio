"""The single-file bundle page, composed from the static runtime.

One runtime serves both hosts (``viewer/src/static-runtime/combined/main.tsx``):
a report embeds it beside its tiles, and a single-file bundle is this page, in
the same shape the combined report's dashboard view writes into its iframe
(``combined/host.ts``): the app's stylesheet, ``#root``, the manifest in
``#bundle-manifest``, the add-ons, then the runtime's script. The runtime boots
the dashboard App when it finds ``#bundle-manifest`` and ``#root``, so no
second build of it is needed.

The add-ons go BEFORE the runtime's script: their globals (3Dmol.js) must exist
when it runs.

Standard library only: producer B runs on the CLI-only install.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

from depictio.serverless.inject import json_blob, script_text

DEFAULT_TITLE = "Depictio"

_STYLE_END = re.compile(r"</style", re.IGNORECASE)


def style_text(css: str) -> str:
    """``css`` safe inside a ``<style>`` element: no ``</style`` can end it."""
    return _STYLE_END.sub(r"<\\/style", css)


def compose_bundle_html(
    manifest: Any,
    *,
    js: str,
    css: str,
    title: str = "",
    addons: str = "",
) -> str:
    """The self-contained page for ``manifest``.

    ``manifest``: the bundle manifest as plain data (``model_dump(mode="json")``).
    ``js`` / ``css``: the runtime's script and stylesheet. ``addons``: the
    add-ons' markup (``serverless.addons.addons_html``), placed before the
    runtime's script. ``title`` is escaped; empty falls back to ``Depictio``.
    """
    return (
        '<!doctype html><html lang="en"><head><meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        '<meta name="color-scheme" content="light dark" />'
        f"<title>{escape(title or DEFAULT_TITLE)}</title>"
        f"<style>{style_text(css)}</style>"
        '</head><body><div id="root"></div>'
        f'<script id="bundle-manifest" type="application/json">{json_blob(manifest)}</script>'
        f"{addons}"
        f"<script>{script_text(js)}</script>"
        "</body></html>"
    )
