"""The static runtime in a rendered report: the report alone, or the report AND
the dashboard in one HTML file.

One runtime, ``dist-static/combined-runtime.{js,css}``
(``viewer/vite.combined.config.ts``): the whole viewer App plus the report
host that mounts the report's tiles. Every report that embeds the runtime
carries it, in one of two outputs that differ only by the report's config:

* ``report`` — the report alone: its tiles drawn by the dashboard's renderers,
  its filter panel recomputing them in the page;
* ``combined`` — the same, plus the whole interactive dashboard behind a
  "Report | Dashboard" switch. The dashboard is the viewer App, written into a
  same-origin iframe the first time it is asked for, from the script,
  stylesheet and manifest the page already holds: nothing is stored twice.

So a report-only file becomes the combined one by flipping its config
(:func:`set_output`, ``depictio dashboard combine-report``), offline.

The runtime also stands in for Quarto's own plotly.js: the report's static
figures call ``window.Plotly`` while the page parses, so the runtime's script
goes where that copy was and exposes its own Plotly. A report that carries its
own 3Dmol.js (py3Dmol's structures) lends it to the dashboard rather than
shipping the add-on a second time.

:func:`compose_report` is pure text in, text out; :func:`embed_runtime` is the
same with the built runtime and add-ons.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from depictio.notebook.report_runtime import (
    COMBINED_KEY,
    CONFIG_ID,
    MANIFEST_ID,
    RUNTIME_ATTR,
    json_script,
    runtime_parts,
)
from depictio.serverless.report import runtime_dir

RUNTIME_JS = "combined-runtime.js"
RUNTIME_CSS = "combined-runtime.css"

Output = Literal["report", "combined"]
DefaultView = Literal["report", "dashboard"]
OUTPUTS: tuple[str, ...] = ("report", "combined")
DEFAULT_VIEWS: tuple[str, ...] = ("report", "dashboard")


class RuntimeUnavailable(RuntimeError):
    """The static runtime is not built next to the static template."""


def combined_filename(stem: str) -> str:
    """The combined file's name: the report's, marked as holding the dashboard."""
    return f"{stem}-report-dashboard.html"


# ── The built runtime ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RuntimeAssets:
    js: str
    css: str


def runtime_available() -> bool:
    folder = runtime_dir()
    return (folder / RUNTIME_JS).is_file() and (folder / RUNTIME_CSS).is_file()


def runtime_assets() -> RuntimeAssets:
    """The built runtime's script and stylesheet."""
    folder = runtime_dir()
    try:
        return RuntimeAssets(
            js=(folder / RUNTIME_JS).read_text(encoding="utf-8"),
            css=(folder / RUNTIME_CSS).read_text(encoding="utf-8"),
        )
    except OSError as exc:
        raise RuntimeUnavailable(
            f"static runtime not built: {folder / RUNTIME_JS} is missing — run "
            "`cd depictio/viewer && pnpm run build:static`, or point "
            f"DEPICTIO_REPORT_RUNTIME_DIR at a folder holding {RUNTIME_JS} and {RUNTIME_CSS}"
        ) from exc


# ── Reading a rendered report ────────────────────────────────────────────────

_SCRIPT_OPEN = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_PLOTLY_HEAD = re.compile(r"\s*/\*\*\s*\n\s*\*\s*plotly\.js v\d")
_THREEDMOL_HEAD = "/*! For license information please see 3Dmol-min.js.LICENSE.txt */"


def _script_spans(html: str):
    """``(start, body_start, body_end, end)`` of every ``<script>`` element."""
    pos = 0
    while True:
        m = _SCRIPT_OPEN.search(html, pos)
        if not m:
            return
        close = html.find("</script>", m.end())
        if close < 0:
            return
        yield m.start(), m.end(), close, close + len("</script>")
        pos = close + len("</script>")


def plotly_script_span(html: str) -> tuple[int, int] | None:
    """Where Quarto inlined plotly.js (the report's static figures' copy)."""
    for start, body, body_end, end in _script_spans(html):
        if _PLOTLY_HEAD.match(html, body, min(body_end, body + 200)):
            return start, end
    return None


def threedmol_script_span(html: str) -> tuple[int, int] | None:
    """The report's own 3Dmol.js (py3Dmol's structures), if it carries one."""
    for start, body, body_end, end in _script_spans(html):
        if html.startswith(_THREEDMOL_HEAD, body) and "data-depictio-addon" not in html[start:body]:
            return start, end
    return None


def _json_block(html: str, element_id: str) -> tuple[int, int, Any] | None:
    m = re.search(
        rf'<script type="application/json" id="{re.escape(element_id)}">', html, re.IGNORECASE
    )
    if not m:
        return None
    close = html.find("</script>", m.end())
    if close < 0:
        return None
    try:
        payload = json.loads(html[m.end() : close])
    except ValueError:
        payload = None
    return m.start(), close + len("</script>"), payload


def embedded_manifest(html: str) -> dict[str, Any] | None:
    block = _json_block(html, MANIFEST_ID)
    return block[2] if block else None


def embedded_config(html: str) -> dict[str, Any]:
    block = _json_block(html, CONFIG_ID)
    return block[2] if block and isinstance(block[2], dict) else {}


def runtime_embedded(html: str) -> bool:
    """Whether ``html`` already carries the runtime's script and a manifest."""
    return f'<script {RUNTIME_ATTR}="js">' in html and embedded_manifest(html) is not None


# ── Composing the file ───────────────────────────────────────────────────────


def output_config(
    config: dict[str, Any] | None, output: Output, default_view: DefaultView = "report"
) -> dict[str, Any]:
    """``config`` (the report's look) with the section ``output`` asks for."""
    if output not in OUTPUTS:
        raise ValueError(f"output must be 'report' or 'combined', not {output!r}")
    if default_view not in DEFAULT_VIEWS:
        raise ValueError(f"default_view must be 'report' or 'dashboard', not {default_view!r}")
    merged = {k: v for k, v in (config or {}).items() if k != COMBINED_KEY}
    if output == "combined":
        merged[COMBINED_KEY] = {"default_view": default_view}
    return merged


def set_output(html: str, output: Output, default_view: DefaultView = "report") -> str:
    """A report that embeds the runtime, switched to ``output``: its config
    rewritten, everything else (runtime, manifest, add-ons) kept as it is."""
    block = _json_block(html, CONFIG_ID)
    if block is None or not runtime_embedded(html):
        raise ValueError("this report does not embed the dashboard's runtime")
    start, end, previous = block
    config = output_config(previous if isinstance(previous, dict) else {}, output, default_view)
    return html[:start] + json_script(CONFIG_ID, config) + html[end:]


def _tag_addon(html: str, span: tuple[int, int], name: str) -> str:
    at = span[0] + len("<script")
    return html[:at] + f' data-depictio-addon="{name}"' + html[at:]


def _body_end(html: str) -> int:
    """Where ``</body>`` is, without a lower-cased copy of a 20 MB page."""
    at = html.rfind("</body>")
    return at if at >= 0 else html.rfind("</BODY>")


@dataclass(frozen=True)
class ComposedReport:
    html: str
    #: Bytes Quarto's own plotly.js took, now served by the runtime (0 when the
    #: report had none).
    plotly_dropped: int
    #: Add-ons the report already carried and lent to the dashboard.
    addons_shared: tuple[str, ...]


def compose_report(
    report_html: str,
    manifest: dict[str, Any] | str,
    *,
    js: str,
    css: str,
    addons: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    output: Output = "report",
    default_view: DefaultView = "report",
) -> ComposedReport:
    """A rendered report with the runtime embedded, for ``output``.

    ``report_html`` holds no runtime yet (the worker renders the document with
    its last cell printing nothing). ``manifest`` is producer A's (a dict, or
    its JSON text); ``addons`` maps an add-on's name to its markup
    (``addons.addon_markup``); ``config`` is the report's look
    (``NotebookBuilder.runtime_config``).
    """
    config = output_config(config, output, default_view)
    html = report_html
    addons = dict(addons or {})
    shared: list[str] = []
    if "3dmol" in addons:
        own = threedmol_script_span(html)
        if own:
            html = _tag_addon(html, own, "3dmol")
            del addons["3dmol"]
            shared.append("3dmol")

    data, code = runtime_parts(
        js=js, css=css, manifest=manifest, config=config, addons="".join(addons.values())
    )
    plotly = plotly_script_span(html)
    dropped = 0
    if plotly:
        dropped = plotly[1] - plotly[0]
        html = html[: plotly[0]] + code + html[plotly[1] :]
        code = ""
    tail = data + code
    at = _body_end(html)
    html = html + tail if at < 0 else html[:at] + tail + html[at:]
    return ComposedReport(html=html, plotly_dropped=dropped, addons_shared=tuple(shared))


def embed_runtime(
    report_html: str,
    manifest: dict[str, Any] | str,
    addon_entries: list[Any],
    *,
    config: dict[str, Any] | None = None,
    output: Output = "report",
    default_view: DefaultView = "report",
) -> ComposedReport:
    """:func:`compose_report` with the built runtime and the manifest's add-ons
    (``addon_entries``: ``BundleManifest.addons``)."""
    from depictio.serverless.addons import addon_markup

    assets = runtime_assets()
    return compose_report(
        report_html,
        manifest,
        js=assets.js,
        css=assets.css,
        addons=addon_markup(addon_entries),
        config=config,
        output=output,
        default_view=default_view,
    )


__all__ = [
    "RUNTIME_CSS",
    "RUNTIME_JS",
    "ComposedReport",
    "RuntimeUnavailable",
    "combined_filename",
    "compose_report",
    "embed_runtime",
    "embedded_config",
    "embedded_manifest",
    "output_config",
    "plotly_script_span",
    "runtime_assets",
    "runtime_available",
    "runtime_embedded",
    "set_output",
    "threedmol_script_span",
]
