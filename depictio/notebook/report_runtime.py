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
* :func:`compose_report_runtime`, the one block inlined at the end of the
  document: the runtime's stylesheet, the report's look, the manifest, any
  add-on the manifest names, then the runtime's script.

Pure standard library, so it ships with the notebook client: the server
composes the block for a report it renders, and a reader's own render composes
it from :meth:`DepictioClient.report_runtime`. Neither path touches the
fallbacks; without the block (or with scripts blocked) the report reads
exactly as it did before the runtime existed.
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
# Marks the block, so a document (and a test) can tell it was embedded once.
RUNTIME_MARK = "data-depictio-report-runtime"
# Set by the worker that renders a report: the block, composed in-process, for
# the document's last cell to print instead of asking the API for it.
RUNTIME_FILE_ENV = "DEPICTIO_REPORT_RUNTIME_FILE"


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


def _inline_script(js: str) -> str:
    # Inside script data, `</script` ends the element and `<!--` can switch the
    # tokenizer into its escaped states. Both are only ever inside string or
    # regex literals in a minified bundle, where `<\/` and `<\!` read the same.
    return js.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def compose_report_runtime(
    *,
    js: str,
    css: str,
    manifest: dict[str, Any] | str,
    config: dict[str, Any] | None = None,
    addons: str = "",
) -> str:
    """The block a report inlines once, at its end.

    ``addons`` is the add-ons' markup (``serverless.addons.addons_html``), placed
    before the runtime's script so their globals exist when it runs.
    """
    style = css.replace("</style", "<\\/style")
    return "".join(
        [
            f'<style {RUNTIME_MARK}="css">{style}</style>',
            json_script(CONFIG_ID, config or {}),
            json_script(MANIFEST_ID, manifest),
            addons,
            f'<script {RUNTIME_MARK}="js">{_inline_script(js)}</script>',
        ]
    )


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
