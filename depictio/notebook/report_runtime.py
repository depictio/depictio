"""The report host of Depictio's static runtime: markup only, no server.

A rendered report and a serverless bundle are two hosts of one runtime. The
bundle (``static.html``) mounts the viewer App over a whole page; a report
mounts the same renderers into the tiles its Quarto document laid out, from
the same manifest contract (``BundleManifest``, built by producer A). This
module is the report's half of that contract, as text:

* the placeholders the generator writes around each tile's own output (its
  *fallback*): ``<div data-depictio-tile="<tab_id>:<index>">`` holding a
  ``.depictio-fallback`` div, and ``<div data-depictio-filters>`` where the
  dashboard's controls are drawn;
* :func:`runtime_parts`, the one composer of what a report embeds: the
  report's look (with the ``combined`` section when the file also holds the
  dashboard), the manifest, the runtime's stylesheet as inert text, the
  add-ons, then the runtime's script. ``serverless/combined.py`` places those
  parts in a rendered report; a reader's own render prints them from the
  document's last cell (:meth:`DepictioClient.report_runtime`).

Pure standard library, so it ships with the notebook client. Without the
runtime (or with scripts blocked) the report reads exactly as it did before
the runtime existed: every fallback stays.
"""

from __future__ import annotations

import json
import math
import re
from html import escape
from typing import Any

TILE_ATTR = "data-depictio-tile"
FILTERS_ATTR = "data-depictio-filters"
FALLBACK_CLASS = "depictio-fallback"
TILE_CLASS = "depictio-tile"
MANIFEST_ID = "depictio-report-manifest"
CONFIG_ID = "depictio-report-config"
# Marks the runtime's script, its stylesheet text and the elements its host
# adds (`viewer/src/static-runtime/combined/host.ts`).
RUNTIME_ATTR = "data-depictio-runtime"
# The config section that turns the "Report | Dashboard" switch on. Without it
# the runtime draws the report's tiles only (the report-only output).
COMBINED_KEY = "combined"
# Set by the worker that renders a report: it embeds the runtime itself once
# the render is done, so the document's last cell prints nothing.
RUNTIME_DEFERRED_ENV = "DEPICTIO_REPORT_RUNTIME_DEFERRED"


def tile_ref(tab_id: str, index: str) -> str:
    return f"{tab_id}:{index}"


def tile_open(refs: list[str]) -> str:
    """The fenced-div lines opening a tile placeholder and its fallback.

    Quarto (pandoc) turns ``::: {.cls key="v"}`` into ``<div class="cls"
    key="v">``, so the placeholder is plain markdown and the cells inside it
    stay ordinary cells: their output is the fallback.
    """
    value = escape(" ".join(refs), quote=True)
    return f'::: {{.{TILE_CLASS} {TILE_ATTR}="{value}"}}\n::: {{.{FALLBACK_CLASS}}}'


def tile_close() -> str:
    return ":::\n:::"


def filters_placeholder(tab_id: str) -> str:
    """Where the runtime draws the dashboard's controls (empty without it)."""
    return f'<div class="depictio-filters-placeholder" {FILTERS_ATTR}="{escape(tab_id, quote=True)}"></div>'


def _json_safe(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def json_script(element_id: str, payload: Any) -> str:
    """A ``<script type="application/json">`` that no payload can close."""
    if isinstance(payload, str):
        blob = payload
    else:
        blob = json.dumps(_json_safe(payload), default=str, separators=(",", ":"))
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\u0021--")
    return f'<script type="application/json" id="{element_id}">{blob}</script>'


def script_text(text: str) -> str:
    """``text`` safe inside a ``<script>`` element (run, or inert ``text/plain``).

    Inside script data, ``</script`` ends the element and ``<!--`` can switch
    the tokenizer into its escaped states. In a minified bundle both only ever
    sit in string or regex literals, where ``<\\/`` and ``<\\!`` read the
    same; in CSS a ``\\/`` reads as ``/``.
    """
    return text.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def runtime_parts(
    *,
    js: str,
    css: str,
    manifest: Any,
    config: dict[str, Any] | None = None,
    addons: str = "",
) -> tuple[str, str]:
    """What a report embeds, as ``(data, code)``.

    ``data``: the report's look (``config``, with its ``combined`` section when
    the file also holds the dashboard), the manifest, and the runtime's
    stylesheet as inert text (the report view scopes it onto the runtime's
    roots, the dashboard view takes it as written). ``code``: the add-ons'
    markup (``serverless.addons.addon_markup``), then the runtime's script, so
    their globals exist when it runs. The two go together at the page's end,
    or apart when the script takes the place of the report's own plotly.js.
    """
    data = "".join(
        [
            json_script(CONFIG_ID, config or {}),
            json_script(MANIFEST_ID, manifest),
            f'<script type="text/plain" {RUNTIME_ATTR}="css">{script_text(css)}</script>',
        ]
    )
    code = addons + f'<script {RUNTIME_ATTR}="js">{script_text(js)}</script>'
    return data, code


_BACKTICKS = re.compile(r"`{3,}")


def raw_html_block(html: str) -> str:
    """``html`` as a pandoc raw block, passed to the page verbatim.

    Printed by an ``output: asis`` cell. A raw block, not bare HTML: pandoc
    would otherwise parse the markup as markdown first. The fence is longer
    than any backtick run inside, so the content cannot close it.
    """
    if not html:
        return ""
    longest = max((len(m.group(0)) for m in _BACKTICKS.finditer(html)), default=2)
    fence = "`" * max(3, longest + 1)
    return f"\n{fence}{{=html}}\n{html}\n{fence}\n"
