"""The combined export: one HTML file, the rendered report AND the dashboard.

Depictio's two offline outputs, in one file a reader opens and switches
between ("Report | Dashboard"):

* the page is the rendered Quarto report — its contents list, prose, code
  and print layout untouched;
* the dashboard is the full viewer App, written into a same-origin iframe the
  first time it is asked for, from the script, stylesheet and manifest the
  page already holds — nothing is stored twice.

One runtime serves both: ``dist-static/combined-runtime.{js,css}``
(``viewer/vite.combined.config.ts``), the whole App plus the report host that
mounts the report's tiles. It replaces the report runtime a report embeds
(``report.py``), and Quarto's own plotly.js too: the report's static figures
call ``window.Plotly`` while the page parses, so the runtime goes where that
copy was and exposes its own Plotly. A report that carries its own 3Dmol.js
(py3Dmol's structures) lends it to the dashboard rather than shipping the
add-on a second time.

:func:`compose_combined` is pure text in, text out: it works on a report the
worker just rendered (with an empty runtime slot) and on any report rendered
with the report runtime embedded, whose block it replaces.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from depictio.notebook.components import public_reason
from depictio.notebook.report_runtime import (
    CONFIG_ID,
    MANIFEST_ID,
    RUNTIME_MARK,
    json_script,
)

COMBINED_JS = "combined-runtime.js"
COMBINED_CSS = "combined-runtime.css"
# Marks the combined runtime's parts in the page (`viewer/.../combined/host.ts`).
COMBINED_MARK = "data-depictio-runtime"

DefaultView = Literal["report", "dashboard"]


class CombinedRuntimeUnavailable(RuntimeError):
    """The combined runtime is not built next to the static template."""


def runtime_dir() -> Path:
    from depictio.serverless.report import runtime_dir as _dir

    return _dir()


def combined_runtime_available() -> bool:
    folder = runtime_dir()
    return (folder / COMBINED_JS).is_file() and (folder / COMBINED_CSS).is_file()


@dataclass(frozen=True)
class CombinedAssets:
    js: str
    css: str


def combined_assets() -> CombinedAssets:
    folder = runtime_dir()
    try:
        return CombinedAssets(
            js=(folder / COMBINED_JS).read_text(encoding="utf-8"),
            css=(folder / COMBINED_CSS).read_text(encoding="utf-8"),
        )
    except OSError as exc:
        raise CombinedRuntimeUnavailable(
            f"combined runtime not built: {folder / COMBINED_JS} is missing — run "
            "`cd depictio/viewer && pnpm run build:static`"
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


def report_runtime_span(html: str) -> tuple[int, int] | None:
    """The report runtime's block (``compose_report_runtime``), if embedded.

    The block is contiguous: its stylesheet, config, manifest, add-ons, then
    its script, whose text cannot hold a literal ``</script>``.
    """
    start = html.find(f"<style {RUNTIME_MARK}=")
    js = html.find(f"<script {RUNTIME_MARK}=", start if start >= 0 else 0)
    if start < 0 or js < 0:
        return None
    end = html.find("</script>", js)
    if end < 0:
        return None
    return start, end + len("</script>")


def embedded_manifest(html: str) -> dict[str, Any] | None:
    block = _json_block(html, MANIFEST_ID)
    return block[2] if block else None


def embedded_config(html: str) -> dict[str, Any]:
    block = _json_block(html, CONFIG_ID)
    return block[2] if block and isinstance(block[2], dict) else {}


# ── Scrubbing what a fallback says ───────────────────────────────────────────

_REASON_BLOCKS = (
    # `_placeholder_html`: the reason line under "<title> could not be shown here."
    re.compile(r'(<div style="margin-top:4px;color:#868e96">)(.*?)(</div>)', re.DOTALL),
    # The genome browser's "No snapshot of the view (<reason>). <link>"
    re.compile(r"(No snapshot of the view \()(.*?)(\)\. )", re.DOTALL),
)


def scrub_fallback_reasons(html: str) -> str:
    """The reasons a report's fallbacks give, without the renderer's paths.

    New reports write them through ``public_reason`` already; a report
    rendered before that may carry a worker's filesystem paths (a Playwright
    launch error) and is cleaned here before it travels again.
    """

    def clean(m: re.Match[str]) -> str:
        text = _html.unescape(m.group(2))
        return m.group(1) + _html.escape(public_reason(text), quote=False) + m.group(3)

    for pattern in _REASON_BLOCKS:
        html = pattern.sub(clean, html)
    return html


# ── Composing the file ───────────────────────────────────────────────────────


def _inline_script(js: str) -> str:
    return js.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def _inert_text(css: str) -> str:
    # Inert: a `<script type="text/plain">` is never run nor applied. In CSS,
    # `\/` reads as `/`, so the escape changes nothing the parser sees.
    return css.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def _tag_addon(html: str, span: tuple[int, int], name: str) -> str:
    start, _ = span
    return (
        html[: start + len("<script")]
        + f' data-depictio-addon="{name}"'
        + html[start + len("<script") :]
    )


@dataclass(frozen=True)
class CombinedResult:
    html: str
    #: Bytes Quarto's own plotly.js took, now served by the runtime (0 when the
    #: report had none).
    plotly_dropped: int
    #: Add-ons the report already carried and lent to the dashboard.
    addons_shared: tuple[str, ...]


def compose_combined(
    report_html: str,
    manifest: dict[str, Any] | str,
    *,
    js: str,
    css: str,
    addons: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    default_view: DefaultView = "report",
) -> CombinedResult:
    """The combined file, from a rendered report and producer A's manifest.

    ``addons`` maps an add-on's name to its markup (``addons.addon_script``);
    ``config`` is the report's look (``NotebookBuilder.runtime_config``), to
    which the combined section (``default_view``) is added. A report runtime
    already embedded in ``report_html`` is replaced, its config kept under
    ``config``'s keys.
    """
    if default_view not in ("report", "dashboard"):
        raise ValueError(f"default_view must be 'report' or 'dashboard', not {default_view!r}")
    html = report_html
    previous = embedded_config(html)
    span = report_runtime_span(html)
    if span:
        html = html[: span[0]] + html[span[1] :]
    html = scrub_fallback_reasons(html)

    addons = dict(addons or {})
    shared: list[str] = []
    if "3dmol" in addons:
        own = threedmol_script_span(html)
        if own:
            html = _tag_addon(html, own, "3dmol")
            del addons["3dmol"]
            shared.append("3dmol")

    plotly = plotly_script_span(html)
    dropped = 0
    runtime = (
        "".join(addons.values()) + f'<script {COMBINED_MARK}="js">{_inline_script(js)}</script>'
    )
    if plotly:
        dropped = plotly[1] - plotly[0]
        html = html[: plotly[0]] + runtime + html[plotly[1] :]
        runtime = ""

    merged = {**previous, **(config or {})}
    merged["combined"] = {"default_view": default_view}
    tail = "".join(
        [
            json_script(CONFIG_ID, merged),
            json_script(MANIFEST_ID, manifest),
            f'<script type="text/plain" {COMBINED_MARK}="css">{_inert_text(css)}</script>',
            runtime,
        ]
    )
    at = html.lower().rfind("</body>")
    html = html + tail if at < 0 else html[:at] + tail + html[at:]
    return CombinedResult(html=html, plotly_dropped=dropped, addons_shared=tuple(shared))


def addon_markup_for(manifest: dict[str, Any]) -> dict[str, str]:
    """Each add-on the manifest names, as its embedding markup (pyodide's
    data blocks included)."""
    from depictio.serverless.addons import addons_html

    out: dict[str, str] = {}
    for entry in manifest.get("addons") or []:
        name = str(entry.get("name") or "")
        if not name:
            continue
        packages = list(entry.get("packages") or []) if name == "pyodide" else None
        out[name] = addons_html([name], packages)
    return out


def combine_report(
    report_html: str,
    manifest: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    default_view: DefaultView = "report",
) -> CombinedResult:
    """:func:`compose_combined` with the built runtime and add-ons."""
    assets = combined_assets()
    return compose_combined(
        report_html,
        manifest,
        js=assets.js,
        css=assets.css,
        addons=addon_markup_for(manifest),
        config=config,
        default_view=default_view,
    )


def build_combined(
    report_html: str,
    dashboard_id: str,
    user: Any,
    state: Any,
    *,
    config: dict[str, Any] | None = None,
    default_view: DefaultView = "report",
    python_runtime: str = "off",
) -> CombinedResult:
    """The combined file for a report rendered from ``dashboard_id``'s export.

    The manifest is producer A's, opening on ``state`` (``report.
    build_report_manifest``): refused on the same grounds as a static export.
    """
    from depictio.serverless.report import build_report_manifest

    if not combined_runtime_available():
        raise CombinedRuntimeUnavailable(f"combined runtime not built in {runtime_dir()}")
    manifest = build_report_manifest(dashboard_id, user, state, python_runtime=python_runtime)
    return combine_report(
        report_html,
        manifest.model_dump(mode="json"),
        config=config,
        default_view=default_view,
    )


def runtime_floor_html(js: str, css: str) -> str:
    """The bytes every combined file pays for its runtime (CI's budget floor)."""
    page = "<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>"
    return compose_combined(page, "null", js=js, css=css).html


__all__ = [
    "COMBINED_CSS",
    "COMBINED_JS",
    "CombinedResult",
    "CombinedRuntimeUnavailable",
    "build_combined",
    "combine_report",
    "combined_runtime_available",
    "compose_combined",
    "embedded_config",
    "embedded_manifest",
    "plotly_script_span",
    "report_runtime_span",
    "scrub_fallback_reasons",
    "threedmol_script_span",
]
